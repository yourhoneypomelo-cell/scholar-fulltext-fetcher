#!/usr/bin/env python3
"""角度2 主线 PoC（多源增强版）：开放 API 多源检索 → 合并去重 → 定位 OA → 下载 → Zotero 入库。

在 openalex_oa_pipeline.py（单源简版）基础上增强：
  - 多源检索：OpenAlex / Crossref / Semantic Scholar bulk（--sources 可选）
  - 按 DOI 规范化合并去重（无 DOI 退化为标题键），记录命中源、补全缺失字段
  - OA 定位：各源自带直链优先；缺失或下载失败（落地页/HTML）时用 Unpaywall(DOI) 兜底重试
  - 入库导出：metadata.jsonl + CSL-JSON（Zotero 可直接导入）+ BibTeX
  - 可选：通过 Zotero Web API 直接写入个人/群组库（--zotero-key/--zotero-library）

仅依赖 requests。全程不碰 Google Scholar、无人机验证、合规。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

OPENALEX_WORKS = "https://api.openalex.org/works"
CROSSREF_WORKS = "https://api.crossref.org/works"
S2_BULK = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
UNPAYWALL_BASE = "https://api.unpaywall.org/v2/"
DEFAULT_TIMEOUT = 30


def _session(email):
    s = requests.Session()
    s.headers.update(
        {"User-Agent": f"scholar-multi-poc/1.0 (mailto:{email or 'anonymous@example.com'})"}
    )
    return s


def _norm_doi(doi):
    if not doi:
        return None
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip().lower())
    return doi or None


def search_openalex(sess, query, email, limit, year_from=None, oa_only=False, api_key=None):
    params = {"search": query, "cursor": "*"}
    filt = []
    if year_from:
        filt.append(f"from_publication_date:{year_from}-01-01")
    if oa_only:
        filt.append("is_oa:true")
    if filt:
        params["filter"] = ",".join(filt)
    if email:
        params["mailto"] = email
    if api_key:
        params["api_key"] = api_key
    out = []
    while len(out) < limit:
        params["per-page"] = min(50, limit - len(out))
        r = sess.get(OPENALEX_WORKS, params=params, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        d = r.json()
        for w in d.get("results", []):
            oa = w.get("open_access") or {}
            best = w.get("best_oa_location") or {}
            primary = w.get("primary_location") or {}
            authors = [a.get("author", {}).get("display_name")
                       for a in (w.get("authorships") or [])]
            out.append({
                "source": "openalex", "doi": _norm_doi(w.get("doi")),
                "title": w.get("display_name"), "year": w.get("publication_year"),
                "authors": [a for a in authors if a],
                "is_oa": oa.get("is_oa", False), "oa_status": oa.get("oa_status"),
                "cited_by_count": w.get("cited_by_count"),
                "pdf_url": best.get("pdf_url") or primary.get("pdf_url"),
                "venue": (primary.get("source") or {}).get("display_name"),
            })
            if len(out) >= limit:
                break
        cur = d.get("meta", {}).get("next_cursor")
        if not cur:
            break
        params["cursor"] = cur
        time.sleep(1.0)
    return out


def search_crossref(sess, query, email, limit, year_from=None):
    params = {
        "query.bibliographic": query,
        "rows": min(100, limit),
        "select": "DOI,title,author,issued,is-referenced-by-count,container-title,link",
    }
    if year_from:
        params["filter"] = f"from-pub-date:{year_from}-01-01"
    if email:
        params["mailto"] = email
    r = sess.get(CROSSREF_WORKS, params=params, timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    out = []
    for it in r.json().get("message", {}).get("items", []):
        authors = [" ".join(filter(None, [a.get("given"), a.get("family")]))
                   for a in it.get("author", [])]
        try:
            year = it.get("issued", {}).get("date-parts", [[None]])[0][0]
        except Exception:
            year = None
        pdf = None
        for ln in it.get("link", []):
            if ln.get("content-type") == "application/pdf":
                pdf = ln.get("URL")
                break
        out.append({
            "source": "crossref", "doi": _norm_doi(it.get("DOI")),
            "title": (it.get("title") or [None])[0], "year": year,
            "authors": [a for a in authors if a],
            "cited_by_count": it.get("is-referenced-by-count"),
            "pdf_url": pdf, "venue": (it.get("container-title") or [None])[0],
        })
        if len(out) >= limit:
            break
    return out


def search_s2(sess, query, limit, year_from=None, api_key=None):
    params = {"query": query,
              "fields": "title,year,authors,externalIds,citationCount,openAccessPdf,venue"}
    if year_from:
        params["year"] = f"{year_from}-"
    headers = {"x-api-key": api_key} if api_key else {}
    out, token = [], None
    while len(out) < limit:
        if token:
            params["token"] = token
        r = sess.get(S2_BULK, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            break
        d = r.json()
        for p in (d.get("data") or []):
            ext = p.get("externalIds") or {}
            oap = p.get("openAccessPdf") or {}
            out.append({
                "source": "s2", "doi": _norm_doi(ext.get("DOI")),
                "title": p.get("title"), "year": p.get("year"),
                "authors": [a.get("name") for a in (p.get("authors") or [])],
                "cited_by_count": p.get("citationCount"),
                "pdf_url": oap.get("url"), "venue": p.get("venue"),
            })
            if len(out) >= limit:
                break
        token = d.get("token")
        if not token:
            break
        time.sleep(1.0)
    return out


def merge_dedup(lists):
    """多源结果按 DOI（无 DOI 用标题）合并；保留首见、记录命中源、补全缺失字段。"""
    by_key, order = {}, []
    for recs in lists:
        for r in recs:
            title_key = "title::" + re.sub(r"\W+", "", (r.get("title") or "").lower())[:80]
            key = r.get("doi") or title_key
            if key in ("title::", None):
                continue
            if key not in by_key:
                r = dict(r)
                r["sources"] = [r.pop("source")]
                by_key[key] = r
                order.append(key)
            else:
                cur = by_key[key]
                cur["sources"].append(r.get("source"))
                for fld in ("pdf_url", "doi", "year", "venue", "cited_by_count"):
                    if not cur.get(fld) and r.get(fld):
                        cur[fld] = r[fld]
                if len(r.get("authors") or []) > len(cur.get("authors") or []):
                    cur["authors"] = r["authors"]
    return [by_key[k] for k in order]


def unpaywall_pdf(sess, doi, email):
    if not doi or not email:
        return None
    try:
        r = sess.get(f"{UNPAYWALL_BASE}{doi}", params={"email": email}, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return None
        loc = (r.json() or {}).get("best_oa_location") or {}
        return loc.get("url_for_pdf")
    except requests.RequestException:
        return None


def _safe_name(s, maxlen=120):
    s = re.sub(r"[^\w\u4e00-\u9fff\- ]+", "_", s or "untitled").strip()
    return (s[:maxlen] or "untitled").rstrip(". ")


def download_pdf(sess, url, dest):
    try:
        with sess.get(url, stream=True, timeout=DEFAULT_TIMEOUT) as r:
            if r.status_code != 200:
                return False
            if "html" in r.headers.get("Content-Type", "").lower():
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 14):
                    if chunk:
                        f.write(chunk)
        return dest.exists() and dest.stat().st_size > 1024
    except requests.RequestException:
        return False


def to_csljson(records):
    out = []
    for r in records:
        item = {"type": "article-journal", "title": r.get("title")}
        if r.get("doi"):
            item["DOI"] = r["doi"]
        if r.get("venue"):
            item["container-title"] = r["venue"]
        if r.get("year"):
            item["issued"] = {"date-parts": [[r["year"]]]}
        item["author"] = [{"literal": a} for a in (r.get("authors") or [])]
        if r.get("pdf_file"):
            item["file"] = r["pdf_file"]
        out.append(item)
    return out


def to_bibtex(records):
    lines = []
    for i, r in enumerate(records, 1):
        key = (r.get("doi") or f"item{i}").replace("/", "_")
        authors = " and ".join(r.get("authors") or [])
        lines.append(f"@article{{{key},")
        if r.get("title"):
            lines.append(f"  title = {{{r['title']}}},")
        if authors:
            lines.append(f"  author = {{{authors}}},")
        if r.get("year"):
            lines.append(f"  year = {{{r['year']}}},")
        if r.get("venue"):
            lines.append(f"  journal = {{{r['venue']}}},")
        if r.get("doi"):
            lines.append(f"  doi = {{{r['doi']}}},")
        lines.append("}")
    return "\n".join(lines)


def zotero_upload(sess, records, api_key, library_id, lib_type="user"):
    """通过 Zotero Web API 批量写入条目（每批 ≤50）。返回成功条数。"""
    url = f"https://api.zotero.org/{lib_type}s/{library_id}/items"
    headers = {"Zotero-API-Key": api_key, "Content-Type": "application/json",
               "Zotero-API-Version": "3"}
    items = [{
        "itemType": "journalArticle", "title": r.get("title") or "",
        "creators": [{"creatorType": "author", "name": a} for a in (r.get("authors") or [])],
        "date": str(r.get("year") or ""), "DOI": r.get("doi") or "",
        "publicationTitle": r.get("venue") or "",
    } for r in records]
    ok = 0
    for i in range(0, len(items), 50):
        try:
            resp = sess.post(url, headers=headers, data=json.dumps(items[i:i + 50]),
                             timeout=DEFAULT_TIMEOUT)
            if resp.status_code in (200, 201):
                ok += len((resp.json() or {}).get("successful") or {})
        except requests.RequestException:
            pass
        time.sleep(1.0)
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="开放 API 多源检索→合并去重→定位OA→下载→Zotero入库 PoC")
    ap.add_argument("query")
    ap.add_argument("--email", required=True,
                    help="你的真实邮箱（Unpaywall 必填且拒占位邮箱；OpenAlex 建议配 --openalex-key）")
    ap.add_argument("--sources", default="openalex,crossref,s2",
                    help="逗号分隔：openalex,crossref,s2")
    ap.add_argument("--max", type=int, default=25, help="每源最多条数")
    ap.add_argument("--year-from", type=int, default=None)
    ap.add_argument("--oa-only", action="store_true", help="（OpenAlex）只要 OA")
    ap.add_argument("--openalex-key", default=None)
    ap.add_argument("--s2-key", default=None)
    ap.add_argument("--out", default="out")
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--zotero-key", default=None)
    ap.add_argument("--zotero-library", default=None, help="Zotero userID 或 groupID")
    ap.add_argument("--zotero-type", default="user", choices=["user", "group"])
    args = ap.parse_args(argv)

    sess = _session(args.email)
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    out_dir = Path(args.out)
    pdf_dir = out_dir / "pdfs"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] 多源检索 {sources} ...", file=sys.stderr)
    lists = []
    if "openalex" in sources:
        try:
            r = search_openalex(sess, args.query, args.email, args.max,
                                args.year_from, args.oa_only, args.openalex_key)
            print(f"      OpenAlex: {len(r)}", file=sys.stderr)
            lists.append(r)
        except requests.RequestException as e:
            print(f"      OpenAlex 失败: {e}", file=sys.stderr)
    if "crossref" in sources:
        try:
            r = search_crossref(sess, args.query, args.email, args.max, args.year_from)
            print(f"      Crossref: {len(r)}", file=sys.stderr)
            lists.append(r)
        except requests.RequestException as e:
            print(f"      Crossref 失败: {e}", file=sys.stderr)
    if "s2" in sources:
        try:
            r = search_s2(sess, args.query, args.max, args.year_from, args.s2_key)
            print(f"      S2: {len(r)}", file=sys.stderr)
            lists.append(r)
        except requests.RequestException as e:
            print(f"      S2 失败: {e}", file=sys.stderr)

    records = merge_dedup(lists)
    print(f"[2/4] 合并去重后：{len(records)} 条", file=sys.stderr)

    print("[3/4] 定位 OA + 下载（失败用 Unpaywall 兜底重试）...", file=sys.stderr)
    n_pdf = 0
    for i, r in enumerate(records, 1):
        pdf_url = r.get("pdf_url")
        if not pdf_url and r.get("doi"):
            pdf_url = unpaywall_pdf(sess, r["doi"], args.email)
            r["pdf_url"] = pdf_url
        if pdf_url and not args.no_download:
            fname = f"{i:03d}_{_safe_name(r.get('title'))}.pdf"
            ok = download_pdf(sess, pdf_url, pdf_dir / fname)
            if not ok and r.get("doi"):
                alt = unpaywall_pdf(sess, r["doi"], args.email)
                if alt and alt != pdf_url and download_pdf(sess, alt, pdf_dir / fname):
                    r["pdf_url"], ok = alt, True
            if ok:
                r["pdf_file"] = (pdf_dir / fname).as_posix()
                n_pdf += 1
        time.sleep(0.4)

    with open(out_dir / "metadata.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(out_dir / "zotero.csl.json", "w", encoding="utf-8") as f:
        json.dump(to_csljson(records), f, ensure_ascii=False, indent=2)
    with open(out_dir / "references.bib", "w", encoding="utf-8") as f:
        f.write(to_bibtex(records))

    zot = None
    if args.zotero_key and args.zotero_library:
        print("[4/4] 写入 Zotero 库 ...", file=sys.stderr)
        zot = zotero_upload(sess, records, args.zotero_key, args.zotero_library, args.zotero_type)

    summary = {"query": args.query, "sources": sources, "merged": len(records),
               "with_oa": sum(1 for r in records if r.get("pdf_url")),
               "downloaded": n_pdf, "zotero_uploaded": zot}
    with open(out_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
