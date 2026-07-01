#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
oa_resolver.py — OA-first academic PDF resolver (legal open-access only, no CAPTCHA).

给定 标题 + DOI，自动走一条【纯合法、无需人机验证】的开放获取 API 链路，
解析并下载 PDF，输出标准化文件名 + 检索报告；闭源命不中的进入待人工清单，
并自动生成 ILL / 作者索取邮件模板。

Resolution chain (命中一个有效 PDF 即短路 short-circuit):
    arXiv -> Unpaywall -> Semantic Scholar -> OpenAlex -> Europe PMC/PMC -> CORE -> Crossref link

设计要点:
  - 仅使用合法开放获取来源(Unpaywall/OpenAlex/Crossref/Europe PMC/PMC/CORE/Semantic Scholar/arXiv)。
  - 完全绕开谷歌学术与 CAPTCHA(因为已有 DOI)。
  - 闭源(closed)论文写入 manual_needed.txt + manual_requests.txt(含 ILL / 作者邮件模板)。
  - 零第三方依赖(仅 Python 3.8+ 标准库)。

Usage:
    python oa_resolver.py papers.csv -o pdfs/ -e you@example.com
    python oa_resolver.py papers.csv -o pdfs/ -e you@example.com --hitrate-only
    python oa_resolver.py --doi 10.1038/nature12373 -o pdfs/ -e you@example.com
    python oa_resolver.py --smoke-test -o pdfs/ -e you@example.com

输入格式(自动识别):
    * .txt   : 每行一个 DOI
    * .csv/.tsv : 含表头,必须有 DOI 列(大小写不敏感);可选 Title / PMID 列

可选提高命中率/额度的 Key:
    --openalex-key  (2026-02-13 起 OpenAlex API 需免费 key)
    --core-key      (CORE 需免费 key,不填则跳过 CORE)
"""

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Optional, Tuple, List, Dict, Any

DEFAULT_UA = "oa-resolver/1.0 (mailto:{email})"
MIN_PDF_BYTES = 10 * 1024  # 10 KB 下限,过滤掉错误页/占位页
PDF_MAGIC = b"%PDF"

# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------


def _request(url: str, headers: Dict[str, str], timeout: int = 30) -> Tuple[int, bytes, Dict[str, str]]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, b"", dict(getattr(e, "headers", {}) or {})
    except Exception:
        return 0, b"", {}


def http_get_json(url: str, email: str, timeout: int = 30, retries: int = 2) -> Optional[Any]:
    headers = {"User-Agent": DEFAULT_UA.format(email=email), "Accept": "application/json"}
    for attempt in range(retries + 1):
        code, body, _ = _request(url, headers, timeout)
        if code == 200 and body:
            try:
                return json.loads(body.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                return None
        if code in (429, 500, 502, 503) and attempt < retries:
            time.sleep(1.5 * (attempt + 1))
            continue
        return None
    return None


def http_get_bytes(url: str, email: str, timeout: int = 60) -> Tuple[int, bytes, str]:
    """Return (status, body, content_type). Follows redirects (urllib default)."""
    headers = {
        "User-Agent": DEFAULT_UA.format(email=email),
        "Accept": "application/pdf,*/*",
    }
    code, body, hdrs = _request(url, headers, timeout)
    ctype = (hdrs.get("Content-Type") or hdrs.get("content-type") or "").lower()
    return code, body, ctype


def looks_like_pdf(body: bytes) -> bool:
    return bool(body) and body[:len(PDF_MAGIC)] == PDF_MAGIC and len(body) >= MIN_PDF_BYTES


# ---------------------------------------------------------------------------
# Filename standardization
# ---------------------------------------------------------------------------


def slugify(text: str, max_len: int = 80) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[^\w\-. ]", "", text, flags=re.UNICODE)  # keep word chars, - . space
    text = text.replace(" ", "-")
    text = re.sub(r"-{2,}", "-", text).strip("-_.")
    return text[:max_len].rstrip("-_.")


def safe_doi(doi: str) -> str:
    return urllib.parse.quote(doi, safe="")


def build_filename(meta: "PaperMeta", scheme: str = "year_author_title") -> str:
    """标准化命名: {year}_{FirstAuthorFamily}_{title-slug}.pdf; 缺元数据时回退到 DOI。"""
    if scheme == "doi":
        return safe_doi(meta.doi) + ".pdf"
    year = meta.year or "n.d."
    author = slugify(meta.first_author or "", 30) or "Anon"
    title = slugify(meta.title or "", 80) or safe_doi(meta.doi)
    name = f"{year}_{author}_{title}.pdf"
    # Windows 保留字符已由 slugify 清理;再兜底一次长度
    return name[:180]


# ---------------------------------------------------------------------------
# Metadata (Crossref authoritative) + PaperMeta
# ---------------------------------------------------------------------------


@dataclass
class PaperMeta:
    doi: str
    title: Optional[str] = None
    first_author: Optional[str] = None
    year: Optional[str] = None
    journal: Optional[str] = None
    pmid: Optional[str] = None


def fetch_crossref_meta(doi: str, email: str) -> Tuple[PaperMeta, List[str]]:
    """Return (PaperMeta, pdf_links_from_crossref)."""
    meta = PaperMeta(doi=doi)
    pdf_links: List[str] = []
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}?mailto={urllib.parse.quote(email)}"
    data = http_get_json(url, email)
    if not data or "message" not in data:
        return meta, pdf_links
    m = data["message"]
    if m.get("title"):
        meta.title = m["title"][0]
    if m.get("author"):
        a0 = m["author"][0]
        meta.first_author = a0.get("family") or a0.get("name")
    issued = (m.get("issued") or {}).get("date-parts") or [[None]]
    if issued and issued[0] and issued[0][0]:
        meta.year = str(issued[0][0])
    if m.get("container-title"):
        meta.journal = m["container-title"][0]
    for link in m.get("link", []) or []:
        if "pdf" in (link.get("content-type", "") or "").lower() or \
           (link.get("intended-application") == "text-mining" and link.get("URL", "").lower().endswith(".pdf")):
            if link.get("URL"):
                pdf_links.append(link["URL"])
    return meta, pdf_links


# ---------------------------------------------------------------------------
# OA resolvers — each returns (pdf_url, source) or (None, "")
# ---------------------------------------------------------------------------

ARXIV_DOI_RE = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)
ARXIV_ID_RE = re.compile(r"^(?:arxiv:)?(\d{4}\.\d{4,5}(v\d+)?|[a-z\-]+(\.[A-Z]{2})?/\d{7})$", re.IGNORECASE)


def resolve_arxiv(doi: str, email: str) -> Tuple[Optional[str], str]:
    m = ARXIV_DOI_RE.match(doi.strip())
    arxiv_id = None
    if m:
        arxiv_id = m.group(1)
    elif ARXIV_ID_RE.match(doi.strip()):
        arxiv_id = re.sub(r"^arxiv:", "", doi.strip(), flags=re.IGNORECASE)
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}", "arxiv"
    return None, ""


def resolve_unpaywall(doi: str, email: str) -> Tuple[Optional[str], str, Optional[bool], Optional[str]]:
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={urllib.parse.quote(email)}"
    data = http_get_json(url, email)
    if not data:
        return None, "", None, None
    is_oa = data.get("is_oa")
    oa_status = data.get("oa_status")
    loc = data.get("best_oa_location") or {}
    pdf = loc.get("url_for_pdf") or loc.get("url")
    if pdf:
        return pdf, "unpaywall", is_oa, oa_status
    return None, "", is_oa, oa_status


def resolve_semantic_scholar(doi: str, email: str) -> Tuple[Optional[str], str]:
    url = (f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi)}"
           f"?fields=openAccessPdf")
    data = http_get_json(url, email)
    if data and data.get("openAccessPdf") and data["openAccessPdf"].get("url"):
        return data["openAccessPdf"]["url"], "semantic_scholar"
    return None, ""


def resolve_openalex(doi: str, email: str, key: Optional[str]) -> Tuple[Optional[str], str]:
    base = f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi)}"
    params = {"mailto": email}
    if key:
        params["api_key"] = key
    url = base + "?" + urllib.parse.urlencode(params)
    data = http_get_json(url, email)
    if not data:
        return None, ""
    for path in (("best_oa_location", "pdf_url"), ("primary_location", "pdf_url")):
        loc = data.get(path[0]) or {}
        if loc.get(path[1]):
            return loc[path[1]], "openalex"
    oa = data.get("open_access") or {}
    if oa.get("oa_url"):
        return oa["oa_url"], "openalex"
    return None, ""


def _doi_to_pmcid(doi: str, email: str) -> Optional[str]:
    # NCBI ID converter first
    url = (f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
           f"?ids={urllib.parse.quote(doi)}&format=json&tool=oa-resolver&email={urllib.parse.quote(email)}")
    data = http_get_json(url, email)
    if data and data.get("records"):
        pmcid = data["records"][0].get("pmcid")
        if pmcid:
            return pmcid
    # Fallback: Europe PMC search
    url2 = (f"https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            f"?query=doi:{urllib.parse.quote(doi)}&format=json&resultType=lite")
    data2 = http_get_json(url2, email)
    try:
        res = data2["resultList"]["result"][0]
        return res.get("pmcid")
    except (KeyError, IndexError, TypeError):
        return None


def resolve_europepmc(doi: str, email: str) -> Tuple[Optional[str], str]:
    pmcid = _doi_to_pmcid(doi, email)
    if pmcid:
        return (f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf",
                "europepmc")
    return None, ""


def resolve_core(doi: str, email: str, key: Optional[str]) -> Tuple[Optional[str], str]:
    if not key:
        return None, ""
    url = f"https://api.core.ac.uk/v3/works/{urllib.parse.quote(doi)}"
    headers = {"User-Agent": DEFAULT_UA.format(email=email),
               "Authorization": f"Bearer {key}", "Accept": "application/json"}
    code, body, _ = _request(url, headers)
    if code == 200 and body:
        try:
            data = json.loads(body.decode("utf-8", "replace"))
            if data.get("downloadUrl"):
                return data["downloadUrl"], "core"
        except json.JSONDecodeError:
            pass
    return None, ""


# ---------------------------------------------------------------------------
# Per-DOI processing
# ---------------------------------------------------------------------------


@dataclass
class Record:
    doi: str
    input_title: Optional[str] = None
    title: Optional[str] = None
    year: Optional[str] = None
    first_author: Optional[str] = None
    journal: Optional[str] = None
    is_oa: Optional[bool] = None
    oa_status: Optional[str] = None
    status: str = "pending"          # oa | manual | fail
    source: str = ""                 # which resolver produced the PDF
    pdf_url: str = ""
    filename: str = ""
    size_bytes: int = 0
    note: str = ""


def process_doi(doi: str, input_title: Optional[str], args) -> Record:
    email = args.email
    rec = Record(doi=doi, input_title=input_title)

    # 1) Authoritative metadata for naming (Crossref) — also yields crossref pdf links
    meta, crossref_pdfs = fetch_crossref_meta(doi, email)
    if not meta.title and input_title:
        meta.title = input_title
    rec.title = meta.title
    rec.year = meta.year
    rec.first_author = meta.first_author
    rec.journal = meta.journal

    # 2) Build resolver candidate list (ordered, short-circuit)
    candidates: List[Tuple[Optional[str], str]] = []

    u_pdf, u_src, is_oa, oa_status = resolve_unpaywall(doi, email)
    rec.is_oa, rec.oa_status = is_oa, oa_status

    candidates.append(resolve_arxiv(doi, email))
    if u_pdf:
        candidates.append((u_pdf, u_src))
    candidates.append(resolve_semantic_scholar(doi, email))
    candidates.append(resolve_openalex(doi, email, args.openalex_key))
    candidates.append(resolve_europepmc(doi, email))
    candidates.append(resolve_core(doi, email, args.core_key))
    for c in crossref_pdfs:
        candidates.append((c, "crossref"))

    # de-dup preserving order
    seen = set()
    ordered = []
    for url, src in candidates:
        if url and url not in seen:
            seen.add(url)
            ordered.append((url, src))

    if args.hitrate_only:
        # 只测覆盖:命中任一候选即视为"可获取"
        if ordered:
            rec.status = "oa"
            rec.pdf_url, rec.source = ordered[0]
        else:
            rec.status = "manual" if rec.is_oa is False else "manual"
        return rec

    # 3) Try to download & validate each candidate
    meta.title = rec.title
    for url, src in ordered:
        if args.verbose:
            print(f"    [{src}] trying {url[:90]}")
        code, body, ctype = http_get_bytes(url, email)
        if code == 200 and looks_like_pdf(body):
            rec.filename = build_filename(meta, args.naming)
            out_path = os.path.join(args.output, rec.filename)
            try:
                with open(out_path, "wb") as f:
                    f.write(body)
                rec.status = "oa"
                rec.source = src
                rec.pdf_url = url
                rec.size_bytes = len(body)
                return rec
            except OSError as e:
                rec.note = f"write failed: {e}"
        time.sleep(args.sleep)

    rec.status = "manual"
    rec.note = "no legal OA PDF found"
    return rec


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------


def load_inputs(path: str) -> List[Tuple[str, Optional[str]]]:
    out: List[Tuple[str, Optional[str]]] = []
    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        if ext in (".csv", ".tsv"):
            delim = "\t" if ext == ".tsv" else ","
            reader = csv.DictReader(f, delimiter=delim)
            cols = {c.lower(): c for c in (reader.fieldnames or [])}
            doi_col = cols.get("doi")
            title_col = cols.get("title")
            if not doi_col:
                raise SystemExit("CSV/TSV 必须包含 DOI 列")
            for row in reader:
                doi = (row.get(doi_col) or "").strip()
                if doi:
                    out.append((normalize_doi(doi), (row.get(title_col) or "").strip() or None))
        else:
            for line in f:
                doi = line.strip()
                if doi and not doi.startswith("#"):
                    out.append((normalize_doi(doi), None))
    return out


def normalize_doi(doi: str) -> str:
    doi = doi.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi


SMOKE_DOIS = [
    ("10.48550/arXiv.1706.03762", "Attention Is All You Need"),
    ("10.1371/journal.pone.0000308", "PLoS ONE gold OA sample"),
    ("10.7717/peerj.4375", "PeerJ gold OA sample"),
    ("10.1038/nature12373", "Nanometre-scale thermometry (likely closed/green)"),
    ("10.1016/j.cell.2011.10.002", "Cell (likely closed)"),
]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def write_reports(records: List[Record], args) -> None:
    # result.csv
    csv_path = os.path.join(args.output, "result.csv")
    fields = ["doi", "status", "source", "is_oa", "oa_status", "year", "first_author",
              "journal", "title", "filename", "size_bytes", "pdf_url", "note"]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in records:
            row = {k: getattr(r, k, "") for k in fields}
            w.writerow(row)

    # retrieval_report.json
    with open(os.path.join(args.output, "retrieval_report.json"), "w", encoding="utf-8") as f:
        json.dump({"count": summarize(records), "items": [asdict(r) for r in records]},
                  f, ensure_ascii=False, indent=2)

    # manual_needed.txt + templates (o3)
    manual = [r for r in records if r.status != "oa"]
    if manual:
        with open(os.path.join(args.output, "manual_needed.txt"), "w", encoding="utf-8") as f:
            for r in manual:
                f.write(f"{r.doi}\t{r.title or r.input_title or ''}\n")
        with open(os.path.join(args.output, "manual_requests.txt"), "w", encoding="utf-8") as f:
            f.write(build_manual_templates(manual))


def build_manual_templates(manual: List[Record]) -> str:
    """o3: 闭源残余的合法补救——生成 ILL / 作者索取邮件模板。"""
    out = io.StringIO()
    out.write("# 闭源/未命中论文的合法获取模板 (逐条)\n")
    out.write("# 建议顺序: 1) 机构代理/图书馆  2) 作者直邮  3) 馆际互借(ILL)  4) Zotero Find Available PDF\n\n")
    for r in manual:
        title = r.title or r.input_title or "(title unknown)"
        out.write("=" * 78 + "\n")
        out.write(f"DOI: {r.doi}\nTitle: {title}\nJournal: {r.journal or ''}  Year: {r.year or ''}\n\n")
        out.write("[作者索取邮件模板]\n")
        out.write(f"Subject: Request for a copy of your paper ({title[:60]})\n\n")
        out.write(f"Dear Dr. {r.first_author or '[Author]'},\n\n"
                  f"I am researching a related topic and found your paper\n"
                  f"  \"{title}\" ({r.journal or ''}, {r.year or ''}, DOI: {r.doi}).\n"
                  f"I was unable to access it through open-access channels. Would you kindly\n"
                  f"share a copy for my research? I will cite it appropriately.\n\n"
                  f"Thank you very much for your time.\nBest regards,\n[Your name / affiliation]\n\n")
        out.write("[馆际互借 ILL 条目]\n")
        out.write(f"  Title: {title}\n  DOI: {r.doi}\n  Journal: {r.journal or ''}\n  Year: {r.year or ''}\n\n")
    out.write("=" * 78 + "\n")
    out.write("提示: Zotero 中选中条目 -> 右键 'Find Available PDF' 可复用你自己的 OpenURL/机构代理,\n")
    out.write("      无需在本工具中硬编码任何机构凭据。\n")
    return out.getvalue()


def summarize(records: List[Record]) -> Dict[str, Any]:
    total = len(records)
    retrieved = sum(1 for r in records if r.status == "oa")
    by_source: Dict[str, int] = {}
    for r in records:
        if r.status == "oa":
            by_source[r.source] = by_source.get(r.source, 0) + 1
    oa_detected = sum(1 for r in records if r.is_oa is True)
    return {
        "total": total,
        "retrieved": retrieved,
        "manual_or_fail": total - retrieved,
        "hit_rate": round(retrieved / total, 3) if total else 0.0,
        "unpaywall_is_oa": oa_detected,
        "by_source": by_source,
    }


def print_summary(records: List[Record], args) -> None:
    s = summarize(records)
    print("\n" + "=" * 60)
    print(f"  总数 total          : {s['total']}")
    mode = "命中(可获取)" if args.hitrate_only else "已下载"
    print(f"  {mode:<16}: {s['retrieved']}  (hit-rate = {s['hit_rate']*100:.1f}%)")
    print(f"  待人工 manual/fail  : {s['manual_or_fail']}")
    print(f"  Unpaywall 标记 OA   : {s['unpaywall_is_oa']}")
    print(f"  各来源命中          : {s['by_source']}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(description="OA-first academic PDF resolver (legal, no CAPTCHA).")
    p.add_argument("input", nargs="?", help="输入文件 (.txt/.csv/.tsv)")
    p.add_argument("--doi", help="单个 DOI (与 input 二选一)")
    p.add_argument("--smoke-test", action="store_true", help="用内置样本 DOI 跑通/演示命中率")
    p.add_argument("-o", "--output", default="pdfs", help="输出目录 (默认 pdfs/)")
    p.add_argument("-e", "--email", required=True, help="联系邮箱 (Unpaywall/Crossref 礼貌池必填)")
    p.add_argument("--openalex-key", default=os.environ.get("OPENALEX_KEY"), help="OpenAlex API key")
    p.add_argument("--core-key", default=os.environ.get("CORE_KEY"), help="CORE API key")
    p.add_argument("--naming", choices=["year_author_title", "doi"], default="year_author_title",
                   help="文件命名方案")
    p.add_argument("--hitrate-only", action="store_true", help="只测 OA 命中率,不实际下载")
    p.add_argument("--sleep", type=float, default=0.4, help="每次候选下载间隔秒 (礼貌)")
    p.add_argument("--limit", type=int, default=0, help="最多处理前 N 条 (0=全部)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    if not (args.input or args.doi or args.smoke_test):
        p.error("请提供 input 文件,或 --doi,或 --smoke-test")

    os.makedirs(args.output, exist_ok=True)

    if args.smoke_test:
        items = SMOKE_DOIS
    elif args.doi:
        items = [(normalize_doi(args.doi), None)]
    else:
        items = load_inputs(args.input)

    if args.limit:
        items = items[:args.limit]

    print(f"待处理 {len(items)} 条  |  模式: {'命中率测试' if args.hitrate_only else '下载'}  |  输出: {args.output}")
    records: List[Record] = []
    for i, (doi, title) in enumerate(items, 1):
        print(f"[{i}/{len(items)}] {doi}")
        rec = process_doi(doi, title, args)
        tag = rec.source if rec.status == "oa" else rec.status
        print(f"    -> {rec.status.upper():6} via {tag:14} oa={rec.is_oa} status={rec.oa_status} "
              f"{('file=' + rec.filename) if rec.filename else ''}")
        records.append(rec)
        time.sleep(args.sleep)

    write_reports(records, args)
    print_summary(records, args)
    print(f"\n报告已写入: {os.path.join(args.output, 'result.csv')} / retrieval_report.json"
          f"{' / manual_needed.txt / manual_requests.txt' if any(r.status!='oa' for r in records) else ''}")


if __name__ == "__main__":
    main()
