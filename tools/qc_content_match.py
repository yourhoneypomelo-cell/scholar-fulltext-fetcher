"""内容比对 QC 复扫：量化 websearch「假阳(错论文)」率 + 「可能假阴(误杀)」风险。

背景:下载校验只看 %PDF + 体积,不做内容/DOI/标题比对,故 websearch 兜底可能下到
「错论文」却记 success(实锤:10.1002/cssc.201601217 落盘成皮肤病 cssc→jaad 论文)。
本工具**纯读** out/*/metadata.jsonl 中 success 且 source_used 含 websearch 的记录,
抽 PDF 首 2 页文本 + PDF 元数据 title,与该记录的 resolved title / DOI 做模糊匹配,
量化真实假阳率,并**双向报数**(假阳=收错 / 可能假阴=误杀风险),供审计人工抽样。

判定(每条,五档 verdict):
  - PDF 首2页文本里出现该记录的 DOI                         → match(强信号)
  - 否则 title_score = max(rapidfuzz token_set_ratio(期望title, [PDF元数据title, 首2页文本]))
      >= MATCH_HI(默认70)                                  → match
  - **抽不出正文文本(扫描/图片/CID字体乱码)** 且非上面的强命中 → scanned(单列;绝不判 mismatch)
      归入 uncertain 家族(不计入假阳分母),避免另一种误杀。
  - title_score <  MISMATCH_LO(默认50)                      → mismatch(明确他刊他题,疑似错论文)
  - MISMATCH_LO <= title_score < MATCH_HI                    → uncertain(中间带,留人工;可能是
      绿OA预印本/译名/子标题导致真命中标题略异 → 可能假阴)
  - PDF 缺失/损坏(PdfReader 抛错)                           → unreadable(单列)

双向口径(审计用):
  - 方向1 假阳(收错风险)      = mismatch;审计应对 mismatch **抽样人工核**,确认确为他刊他题。
  - 方向2 可能假阴(误杀风险)  = uncertain(+ 落在阈值边界带的样本);审计应人工回收真命中。
  - scanned / unreadable      = 无法判定,单列,既不算假阳也不算假阴。

阈值不宜过严:MISMATCH_LO 默认 50(可命中 cssc→jaad 一类 47.7 分的明确错论文),
MATCH_HI 默认 70;三者均可用 CLI 覆盖后重跑。

输出 out/qc_content_report.json 与 out/qc_content_report.md。

护栏:纯读 out/;新文件;不改核心码;不动 PDF/metadata。pypdf 必需;rapidfuzz 缺则降级 difflib。
用法:python tools/qc_content_match.py [--max-per-batch N] [--match-hi 70] [--mismatch-lo 50] [--border 8]
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import sys
import unicodedata
from typing import List, Optional, Tuple
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "out")
REPORT_JSON = os.path.join(OUT_DIR, "qc_content_report.json")
REPORT_MD = os.path.join(OUT_DIR, "qc_content_report.md")

# ── 默认阈值(可被 CLI 覆盖)────────────────────────────────────────────
MATCH_HI = 70       # title_score >= → match
MISMATCH_LO = 50    # title_score <  → mismatch(明确他刊他题);保持在 cssc→jaad(47.7) 之上
BORDER = 8          # 阈值边界带宽:落在 [MISMATCH_LO-BORDER, MATCH_HI+BORDER) 的判定标 borderline,供双向抽样

# ── 扫描/图片/CID字体"抽不出正文"判定 ──────────────────────────────────
# 目标:pypdf 抽不出可用正文(纯扫描图片 / CID 字体乱码 / 十六进制 mojibake)→ 归 scanned。
# 关键:isalpha() 覆盖 CJK/西里尔等所有语种字母,故"真·外文正文"(可读)不会被误判为 scanned,
#       仍走正常标题比对;只有真正的空文本 / 组合符·替换符·乱码(alpha 极少)才判 scanned。
MIN_TEXT_LEN = 40       # strip 后正文短于此 → 视为抽不出文本
MIN_USABLE_RATIO = 0.35  # 字母(任意语种)占比低于此 → 视为乱码/CID/mojibake

# ── 模糊匹配:rapidfuzz 优先,缺则 difflib 兜底 ─────────────────────────
try:
    from rapidfuzz import fuzz  # type: ignore

    def token_set_ratio(a: str, b: str) -> float:
        return float(fuzz.token_set_ratio(a, b))

    FUZZ_BACKEND = "rapidfuzz"
except Exception:  # noqa: BLE001
    import difflib

    def token_set_ratio(a: str, b: str) -> float:
        # difflib 兜底:用 token 集合的 Jaccard-ish + 序列相似度取较大者,粗略但可用
        ta, tb = set(a.split()), set(b.split())
        if not ta:
            return 0.0
        inter = len(ta & tb)
        jacc = 100.0 * inter / max(1, len(ta))          # 期望 title 的 token 有多少出现在候选里
        seq = 100.0 * difflib.SequenceMatcher(None, a, b).ratio()
        return max(jacc, seq)

    FUZZ_BACKEND = "difflib"

# ── pypdf 软导入:模块可被安全 import(不因缺 pypdf 而 sys.exit 杀掉宿主进程)──
# 只有真正读 PDF 的 extract_pdf()/CLI main() 才需要 pypdf;匹配原语(clean_title/
# norm_for_doi/is_unextractable/token_set_ratio/classify)不依赖它,供 download.py 等安全复用。
try:
    from pypdf import PdfReader  # type: ignore
    _PYPDF_ERR: Optional[str] = None
except Exception as e:  # noqa: BLE001
    PdfReader = None  # type: ignore
    _PYPDF_ERR = f"{type(e).__name__}: {e}"


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_NONALNUM = re.compile(r"[^0-9a-z]+")


def clean_title(s: Optional[str]) -> str:
    if not s:
        return ""
    s = html.unescape(str(s))
    s = _TAG.sub(" ", s)             # 去 <sub>/<sup>/<i> 等
    s = s.lower()
    s = _WS.sub(" ", s).strip()
    return s


def norm_for_doi(s: Optional[str]) -> str:
    """DOI 子串匹配用:小写 + 去所有非字母数字(容忍 PDF 里 DOI 断行/加前缀)。"""
    if not s:
        return ""
    return _NONALNUM.sub("", str(s).lower())


def is_unextractable(text: Optional[str]) -> bool:
    """pypdf 是否"抽不出可用正文":空文本 / 过短 / 乱码(CID字体·十六进制mojibake·组合符)。

    isalpha() 对 CJK/西里尔/拉丁等任意语种字母都为真,故真·外文正文不会被误判 scanned。
    """
    if not text:
        return True
    # NFC 合并"基字母+组合附加符"(如越南语/带音标拉丁),使可读外文正文不被误判为乱码;
    # 真·CID乱码(游离组合符 U+03xx / 替换符 / 十六进制 mojibake)无基字母可合并,仍判 scanned。
    t = _WS.sub(" ", unicodedata.normalize("NFC", text)).strip()
    if len(t) < MIN_TEXT_LEN:
        return True
    alpha = sum(1 for c in t if c.isalpha())
    return (alpha / len(t)) < MIN_USABLE_RATIO


# ── 来源域/DOI前缀:供审计法(URL域×DOI前缀)与本标题匹配法做并集合并 ──────────
# 说明:审计法靠"下载域 vs DOI 归属出版商不符"揪跨社错论文,揪不到①同社错论文(域相符但文不对)
# 与②仓库托管错论文(域是仓库,判不了对错)。本工具靠"标题不符"正好补这两类,故为每条附
# pdf_url / url_domain / doi_prefix / source_bucket,便于审计 145 合并、去重、出可信成功率下限。
_REPO_HINTS = (
    "researchgate", "semanticscholar", "academia.edu", "zenodo", "figshare",
    "chemrxiv", "arxiv", "biorxiv", "medrxiv", "preprints.org", "osf.io", "ssrn",
    "hal.", "digital.csic", "repositor", "dspace", "escholarship", "core.ac.uk",
    ".edu", ".ac.", "diva-portal", "hal-", "eprints", "openreview",
)
_PUBLISHER_HINTS = (
    "wiley", "onlinelibrary", "acs.org", "pubs.acs", "rsc.org", "pubs.rsc",
    "sciencedirect", "elsevier", "springer", "link.springer", "nature.com",
    "mdpi", "tandfonline", "sagepub", "iop.org", "iopscience", "aip.org",
    "pubs.aip", "acm.org", "ieee", "oup.com", "cambridge.org", "degruyter",
    "thieme", "aiche", "acnatsci", "pnas.org", "science.org", "jstage",
    "chemistry-europe", "jaad.org", "cell.com", "frontiersin", "hindawi",
)


def _url_domain(u: str) -> str:
    if not u:
        return ""
    try:
        netloc = (urlparse(u).netloc or "").lower()
    except Exception:  # noqa: BLE001
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _source_bucket(domain: str) -> str:
    """按下载域粗分:repository / publisher / other(搜索引擎·CDN·未知)。"""
    d = domain or ""
    if any(h in d for h in _REPO_HINTS):
        return "repository"
    if any(h in d for h in _PUBLISHER_HINTS):
        return "publisher"
    return "other"


def _doi_prefix(doi: str) -> str:
    """DOI 归属前缀(注册商),如 10.1002;供与下载域比对判是否同社。"""
    m = re.match(r"\s*(10\.\d{3,9})/", str(doi or "").lower())
    return m.group(1) if m else ""


# ── 从 PDF 正文抽 DOI:驱动系统性模式②同社近似DOI错论文 / ③跨社错论文 / ④未来年份 ──
_DOI_IN_TEXT = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.I)


def dois_in_text(text: Optional[str], limit: int = 8) -> List[str]:
    """抽正文中出现的 DOI(去尾部标点、小写、去重、保序)。用于比对是否落到他篇 DOI。"""
    if not text:
        return []
    out: List[str] = []
    seen = set()
    for m in _DOI_IN_TEXT.finditer(text):
        d = m.group(0).lower().rstrip(".,;:)]}>")
        # 去掉常见 PDF 断行拼接噪声尾巴
        d = re.sub(r"(pdf|full|abstract|epdf|meta)$", "", d)
        if d and d not in seen:
            seen.add(d)
            out.append(d)
        if len(out) >= limit:
            break
    return out


def _doi_year(s: str) -> Optional[int]:
    """尽力从 DOI/URL 串解析"年份":Nature s-系(s41598-026→2026)、显式 20xx、arXiv YYMM。保守,不确定返回 None。"""
    if not s:
        return None
    s = s.lower()
    # 显式 4 位年 20xx / 19xx
    m = re.search(r"(?:^|[^0-9])((?:19|20)\d{2})(?:[^0-9]|$)", s)
    if m:
        y = int(m.group(1))
        if 1950 <= y <= 2035:
            return y
    # Nature/BMC 系:s41598-0YY- / s41467-0YY-  (0YY 两三位年后缀)
    m = re.search(r"s\d{4,6}-(\d{2,3})-", s)
    if m:
        yy = int(m.group(1))
        yy = yy % 100
        return 2000 + yy
    return None


def resolve_pdf_path(pdf_path: str) -> Tuple[Optional[str], str]:
    """返回 (绝对路径 or None, location)。location ∈ {active, quarantined, ""}。

    稳健性:成员会把复核出的"错论文"从 <batch>/pdfs/ 移到 <batch>/rejected/ 做隔离,
    而 metadata 仍指向 pdfs/。故 pdfs/ 找不到时兜底去 rejected/(及常见隔离名)再找一次,
    使 QC 不因隔离动作而误判"文件缺失",并回填 pdf_location 供审计看"已隔离"状态。
    """
    if not pdf_path:
        return None, ""
    p = pdf_path.replace("\\", "/")
    cands: List[Tuple[str, str]] = [(p, "active")]
    if "/pdfs/" in p:
        for seg in ("/rejected/", "/quarantine/", "/rejected_pdfs/", "/bad/"):
            cands.append((p.replace("/pdfs/", seg), "quarantined"))
    for cp, loc in cands:
        full = cp if os.path.isabs(cp) else os.path.join(ROOT, cp)
        full = os.path.normpath(full)
        if os.path.isfile(full):
            return full, loc
    return None, ""


def extract_pdf(path: str, max_pages: int = 2, max_chars: int = 6000) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """返回 (pdf_meta_title, first_pages_text, error)。任何异常 → error 非空、其余 None。"""
    if PdfReader is None:
        return None, None, f"pypdf unavailable ({_PYPDF_ERR})"
    try:
        reader = PdfReader(path)
        meta_title = None
        try:
            md = reader.metadata
            if md and md.title:
                meta_title = str(md.title)
        except Exception:  # noqa: BLE001
            meta_title = None
        parts: List[str] = []
        for pg in reader.pages[:max_pages]:
            try:
                parts.append(pg.extract_text() or "")
            except Exception:  # noqa: BLE001
                continue
            if sum(len(x) for x in parts) >= max_chars:
                break
        text = (" ".join(parts))[:max_chars]
        return meta_title, text, None
    except Exception as e:  # noqa: BLE001
        return None, None, f"{type(e).__name__}: {e}"


def snippet(meta_title: Optional[str], text: Optional[str], n: int = 140) -> str:
    if meta_title and meta_title.strip():
        return _WS.sub(" ", html.unescape(meta_title)).strip()[:n]
    if text:
        return _WS.sub(" ", text).strip()[:n]
    return ""


def iter_records():
    for meta in sorted(glob.glob(os.path.join(OUT_DIR, "*", "metadata.jsonl"))):
        batch = os.path.basename(os.path.dirname(meta))
        try:
            with open(meta, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    yield batch, rec
        except Exception:  # noqa: BLE001
            continue


def classify(expected_title: Optional[str], doi: Optional[str], meta_title: Optional[str],
             text: Optional[str], match_hi: int = MATCH_HI, mismatch_lo: int = MISMATCH_LO):
    """纯函数单一真源:给定 期望标题 / DOI / PDF元数据标题 / PDF正文 → (verdict, score, reason)。

    不依赖 pypdf / 文件系统,供 download.py 等在"记 success 前"复用同一判定逻辑。
    判定顺序(与 judge 完全一致):
      DOI 在正文 → match;标题分>=hi → match;抽不出正文 → scanned(绝不 mismatch);
      无期望标题 → uncertain;标题分<lo → mismatch;中间 → uncertain。
    verdict ∈ {match, mismatch, uncertain, scanned};score 为 title_score(无可比时 -1.0)。
    """
    exp = clean_title(expected_title)
    doi_found = bool(doi) and norm_for_doi(doi) in norm_for_doi(text)
    meta_score = token_set_ratio(exp, clean_title(meta_title)) if (exp and meta_title) else -1.0
    body_score = token_set_ratio(exp, clean_title(text)) if (exp and text) else -1.0
    score = max(meta_score, body_score)
    no_body = is_unextractable(text)

    if doi_found:
        return "match", score, "doi present in pdf text"
    if score >= match_hi:
        return "match", score, "title matches pdf content"
    if no_body:
        return "scanned", score, "no extractable body text (scanned/image/CID-font pdf) — not judged as mismatch"
    if score < 0:
        return "uncertain", score, "no expected title to compare"
    if score < mismatch_lo:
        return "mismatch", score, "title absent from pdf (suspected wrong paper: different journal/topic)"
    return "uncertain", score, "partial title overlap (possible variant: preprint/translation/subtitle)"


def judge(rec: dict, match_hi: int, mismatch_lo: int, border: int) -> dict:
    doi = rec.get("doi") or ""
    exp_title = clean_title(rec.get("title"))
    pdf_path = rec.get("pdf_path") or ""
    pdf_url = rec.get("pdf_url") or ""
    resolved, pdf_loc = resolve_pdf_path(pdf_path)

    domain = _url_domain(pdf_url)
    row = {
        "doi": doi,
        "expected_title": (rec.get("title") or "")[:200],
        "pdf_path": pdf_path,
        "pdf_location": pdf_loc or "missing",   # active / quarantined(已移入rejected) / missing
        "pdf_url": pdf_url,
        "url_domain": domain,
        "doi_prefix": _doi_prefix(doi),
        "source_bucket": _source_bucket(domain),
        "pdf_actual": "",
        "title_score": None,
        "meta_title_score": None,
        "doi_in_text": False,
        "other_dois_in_text": [],
        "wrong_doi_same_pub": False,   # ②同社近似DOI错论文
        "wrong_doi_cross_pub": False,  # ③跨社错论文(正文含他社DOI)
        "future_year_suspect": False,  # ④未来年份DOI(served年份>目标年份)
        "junk_domain": False,          # ①垃圾域(跨记录聚合后回填)
        "patterns": [],                # 命中的系统性模式标签
        "scanned": False,
        "borderline": False,
        "verdict": "unreadable",
        "reason": "",
    }

    if not resolved:
        row["reason"] = "pdf missing on disk"
        return row

    meta_title, text, err = extract_pdf(resolved)
    if err is not None:
        row["reason"] = f"read error: {err}"
        return row

    row["pdf_actual"] = snippet(meta_title, text)

    text_doi_norm = norm_for_doi(text)
    doi_found = bool(doi) and norm_for_doi(doi) in text_doi_norm
    row["doi_in_text"] = doi_found

    # ── 正文 DOI 取证:落到"他篇 DOI"是错论文的强信号,并区分同社(②)/跨社(③)──
    exp_norm = norm_for_doi(doi)
    exp_pref = row["doi_prefix"]
    others = [d for d in dois_in_text(text) if norm_for_doi(d) != exp_norm]
    row["other_dois_in_text"] = others[:5]
    if not doi_found and others:
        for d in others:
            dp = _doi_prefix(d)
            if exp_pref and dp == exp_pref:
                row["wrong_doi_same_pub"] = True   # 同前缀不同后缀 → 同社他篇
            elif dp:
                row["wrong_doi_cross_pub"] = True   # 他社前缀 → 跨社他篇

    # ④ 未来年份:served(正文他篇DOI 或 下载URL)年份 > 目标 DOI 年份 = 物理不可能
    exp_year = _doi_year(doi)
    served_years = [y for y in (_doi_year(x) for x in ([pdf_url] + others)) if y]
    if exp_year and served_years and max(served_years) > exp_year:
        row["future_year_suspect"] = True

    # ── 判定走单一真源 classify()(与 download.py 复用同一逻辑)──
    verdict, title_score, reason = classify(rec.get("title"), doi, meta_title, text, match_hi, mismatch_lo)
    row["verdict"], row["reason"] = verdict, reason
    row["title_score"] = round(title_score, 1) if title_score >= 0 else None
    # meta-title 单独分(便于看"扫描但元数据命中"),不影响 verdict
    meta_score = token_set_ratio(exp_title, clean_title(meta_title)) if (exp_title and meta_title) else -1.0
    row["meta_title_score"] = round(meta_score, 1) if meta_score >= 0 else None
    row["scanned"] = is_unextractable(text)

    # 需求②:边界带标记 → 供双向人工抽样(既防假阳误报、也防假阴误杀)
    if row["verdict"] in ("mismatch", "uncertain") and title_score >= 0:
        if (mismatch_lo - border) <= title_score < (match_hi + border):
            row["borderline"] = True

    # 系统性模式标签(证据/归类;verdict 仍由标题主导,避免正文引文DOI造成误报)
    pats: List[str] = []
    if row["wrong_doi_same_pub"]:
        pats.append("same_pub_wrong_doi")   # ②
    if row["wrong_doi_cross_pub"]:
        pats.append("cross_pub_wrong_doi")  # ③
    if row["future_year_suspect"]:
        pats.append("future_year")          # ④
    row["patterns"] = pats

    return row


VERDICTS = ("match", "mismatch", "uncertain", "scanned", "unreadable")


def main() -> int:
    # pypdf 硬校验只在 CLI 入口做(不在模块顶层),这样 import 本模块复用匹配原语时不会被杀。
    if PdfReader is None:
        print(f"BLOCKED: pypdf 不可用({_PYPDF_ERR}); 请 pip install pypdf 后重跑。", file=sys.stderr)
        return 3
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-per-batch", type=int, default=0, help="每批最多扫多少条(0=不限,调试用)")
    ap.add_argument("--match-hi", type=int, default=MATCH_HI, help=f"match 阈值(>=,默认 {MATCH_HI})")
    ap.add_argument("--mismatch-lo", type=int, default=MISMATCH_LO, help=f"mismatch 阈值(<,默认 {MISMATCH_LO})")
    ap.add_argument("--border", type=int, default=BORDER, help=f"边界带宽(双向抽样,默认 {BORDER})")
    args = ap.parse_args()

    match_hi, mismatch_lo, border = args.match_hi, args.mismatch_lo, args.border

    rows: List[dict] = []
    per_batch: dict = {}
    seen_batch_count: dict = {}

    for batch, rec in iter_records():
        if not rec.get("success"):
            continue
        if "websearch" not in (rec.get("source_used") or ""):
            continue
        if args.max_per_batch:
            seen_batch_count[batch] = seen_batch_count.get(batch, 0) + 1
            if seen_batch_count[batch] > args.max_per_batch:
                continue
        row = judge(rec, match_hi, mismatch_lo, border)
        row["batch"] = batch
        rows.append(row)
        b = per_batch.setdefault(batch, {k: 0 for k in ("total",) + VERDICTS})
        b["total"] += 1
        b[row["verdict"]] += 1

    total = len(rows)
    agg = {k: 0 for k in VERDICTS}
    for r in rows:
        agg[r["verdict"]] += 1

    verifiable = agg["match"] + agg["mismatch"]     # 口径A:能判真/假的分母
    fp_rate_A = (agg["mismatch"] / verifiable * 100.0) if verifiable else 0.0
    fp_rate_B = (agg["mismatch"] / total * 100.0) if total else 0.0  # 口径B:占全部 websearch success

    n_border_mismatch = sum(1 for r in rows if r["verdict"] == "mismatch" and r["borderline"])
    n_border_uncertain = sum(1 for r in rows if r["verdict"] == "uncertain" and r["borderline"])

    # mismatch 按下载来源桶分:publisher/repository 两桶正是审计法(域×前缀)难判、
    # 本标题匹配法独补的"同社/仓库托管错论文";other 多与审计跨社结果重叠。供 145 合并参考。
    mm_by_bucket = {"publisher": 0, "repository": 0, "other": 0}
    for r in rows:
        if r["verdict"] == "mismatch":
            mm_by_bucket[r.get("source_bucket", "other")] = mm_by_bucket.get(r.get("source_bucket", "other"), 0) + 1

    # ── 系统性模式①:垃圾域检测(跨记录聚合)──────────────────────────────
    # 一个下载域被当成很多"不同 DOI 前缀(不同期刊/出版商)"的答案、且几乎无 match →
    # 高度可疑的垃圾域命中(如 frontiersin public-pages 被塞给一堆 ACS/RSC/Elsevier DOI)。
    dom_stats: dict = {}
    for r in rows:
        d = r.get("url_domain") or ""
        if not d:
            continue
        st = dom_stats.setdefault(d, {"n": 0, "prefixes": set(), "match": 0, "mismatch": 0, "dois": []})
        st["n"] += 1
        if r.get("doi_prefix"):
            st["prefixes"].add(r["doi_prefix"])
        if r["verdict"] == "match":
            st["match"] += 1
        elif r["verdict"] == "mismatch":
            st["mismatch"] += 1
        if len(st["dois"]) < 20:
            st["dois"].append(r.get("doi", ""))
    JUNK_MIN_PREFIXES = 3   # 服务>=3种不同DOI前缀
    JUNK_MIN_RECORDS = 4    # 且被>=4条命中
    junk_domains = {
        d: st for d, st in dom_stats.items()
        if len(st["prefixes"]) >= JUNK_MIN_PREFIXES and st["n"] >= JUNK_MIN_RECORDS and st["match"] == 0
    }
    for r in rows:
        if (r.get("url_domain") or "") in junk_domains:
            r["junk_domain"] = True
            if "junk_domain" not in r["patterns"]:
                r["patterns"].append("junk_domain")

    # ── 系统性模式②③④ 计数(证据/归类,供审计 145 合并测例)──────────────
    pat_counts = {
        "junk_domain": sum(1 for r in rows if r.get("junk_domain")),
        "same_pub_wrong_doi": sum(1 for r in rows if r.get("wrong_doi_same_pub")),
        "cross_pub_wrong_doi": sum(1 for r in rows if r.get("wrong_doi_cross_pub")),
        "future_year": sum(1 for r in rows if r.get("future_year_suspect")),
    }
    junk_top = sorted(
        ({"domain": d, "records": st["n"], "distinct_doi_prefixes": len(st["prefixes"]),
          "match": st["match"], "mismatch": st["mismatch"], "sample_dois": st["dois"][:8]}
         for d, st in junk_domains.items()),
        key=lambda x: (x["records"], x["distinct_doi_prefixes"]), reverse=True,
    )

    # 隔离状态:成员已把复核出的错论文从 pdfs/ 移到 rejected/;交叉看 verdict×location
    loc_counts = {"active": 0, "quarantined": 0, "missing": 0}
    quarantined_by_verdict = {k: 0 for k in VERDICTS}
    for r in rows:
        loc = r.get("pdf_location", "missing")
        loc_counts[loc] = loc_counts.get(loc, 0) + 1
        if loc == "quarantined":
            quarantined_by_verdict[r["verdict"]] = quarantined_by_verdict.get(r["verdict"], 0) + 1

    summary = {
        "generated": _now(),
        "fuzz_backend": FUZZ_BACKEND,
        "thresholds": {
            "match_hi": match_hi,
            "mismatch_lo": mismatch_lo,
            "border": border,
            "scanned_min_text_len": MIN_TEXT_LEN,
            "scanned_min_usable_ratio": MIN_USABLE_RATIO,
        },
        "websearch_success_scanned": total,
        "verdict_counts": agg,
        "false_positive_rate_pct": {
            "A_over_verifiable": round(fp_rate_A, 1),
            "B_over_all_websearch_success": round(fp_rate_B, 1),
            "verifiable_denominator": verifiable,
        },
        # 双向报数:假阳(收错) vs 可能假阴(误杀风险) —— 审计据此双向人工抽样
        "bidirectional": {
            "false_positive_suspected_wrong": {
                "count": agg["mismatch"],
                "rate_over_verifiable_pct": round(fp_rate_A, 1),
                "borderline_count": n_border_mismatch,
                "note": "疑似收错(他刊他题);审计应对 mismatch 抽样人工核,borderline 优先。",
            },
            "false_negative_risk_possible_variant": {
                "count": agg["uncertain"],
                "borderline_count": n_border_uncertain,
                "note": "中间带,可能是真命中被绿OA预印本/译名/子标题拉低分;人工回收以防误杀。",
            },
            "unverifiable": {
                "scanned": agg["scanned"],
                "unreadable": agg["unreadable"],
                "note": "抽不出正文(扫描/图片/CID)或文件缺失损坏;单列,不计入假阳/假阴。",
            },
        },
        # 供审计 145 合并:本法(标题不符)补审计法(URL域×DOI前缀)覆盖不到的同社/仓库错论文
        "mismatch_by_source_bucket": {
            **mm_by_bucket,
            "note": "publisher=下载域为出版商站(同社错论文,审计域法难判)/repository=预印仓库或机构库(托管错论文,审计难判)/other=搜索引擎·CDN·未知(多与审计跨社结果重叠)。两法取并集最全。",
        },
        # 审计 v2 的四类系统性模式检测(测例/规则):供 145 合并、复核
        # 隔离状态:pdfs/ 中"活跃" vs 已移入 rejected/ 的"已隔离";供审计看错论文清理进度
        "pdf_location": {
            **loc_counts,
            "quarantined_by_verdict": quarantined_by_verdict,
            "note": "quarantined=已被成员从 pdfs/ 移入 rejected/(错论文隔离);QC 兜底仍读 rejected/ 复核,不误判缺失。",
        },
        "systematic_patterns": {
            "counts": pat_counts,
            "junk_domains": junk_top,
            "note": "①junk_domain=同一下载域被塞给≥3种不同DOI前缀且0命中(如 frontiersin public-pages);"
                    "②same_pub_wrong_doi=正文含同前缀不同后缀DOI(同社近似DOI错论文);"
                    "③cross_pub_wrong_doi=正文含他社前缀DOI(跨社错论文);"
                    "④future_year=served(URL/正文DOI)年份>目标DOI年份(物理不可能)。"
                    "均为证据/归类标签,verdict 仍由标题主导以免引文DOI误报;审计可据此做测例与人核。",
        },
        "by_batch": per_batch,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "records": rows}, f, ensure_ascii=False, indent=2)

    _write_md(summary, rows)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n报告: {REPORT_JSON}\n      {REPORT_MD}")
    return 0


def _now() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_md(summary: dict, rows: List[dict]) -> None:
    a = summary["verdict_counts"]
    fp = summary["false_positive_rate_pct"]
    th = summary["thresholds"]
    bi = summary["bidirectional"]
    lines: List[str] = []
    lines.append("# websearch 内容比对 QC 复扫报告")
    lines.append("")
    lines.append(f"> 生成:{summary['generated']}｜模糊后端:{summary['fuzz_backend']}｜"
                 f"阈值:match≥{th['match_hi']} / mismatch<{th['mismatch_lo']} / 边界带±{th['border']}")
    lines.append("> 纯读 out/*/metadata.jsonl(success 且 source_used 含 websearch)+ PDF 首2页文本/元数据 title;不改任何源/PDF/metadata。")
    lines.append("")
    lines.append("## 总览")
    lines.append("")
    lines.append(f"- websearch success 扫描总数:**{summary['websearch_success_scanned']}**")
    lines.append(f"- 判定:match **{a['match']}** / mismatch(疑似错论文) **{a['mismatch']}** / "
                 f"uncertain **{a['uncertain']}** / scanned(抽不出正文) **{a['scanned']}** / unreadable **{a['unreadable']}**")
    lines.append(f"- **假阳率 A(mismatch / 可判定{fp['verifiable_denominator']}) = {fp['A_over_verifiable']}%**")
    lines.append(f"- 假阳率 B(mismatch / 全部 websearch success) = {fp['B_over_all_websearch_success']}%")
    loc = summary.get("pdf_location", {})
    if loc:
        qv = loc.get("quarantined_by_verdict", {})
        lines.append(f"- PDF 位置:active(pdfs/) **{loc.get('active', 0)}** / quarantined(已移入 rejected/) **{loc.get('quarantined', 0)}**"
                     f"(其中 mismatch {qv.get('mismatch', 0)} / uncertain {qv.get('uncertain', 0)} / match {qv.get('match', 0)}) / missing **{loc.get('missing', 0)}**")
        lines.append("  > 成员已将复核出的错论文从 pdfs/ 移入 rejected/ 隔离;QC 兜底仍读 rejected/ 复核,不误判缺失。")
    lines.append("")
    lines.append("> 口径说明:A 把 uncertain/scanned/unreadable 排除在分母外(最能反映『可判定样本里的错论文比例』);"
                 "B 是对全部 websearch success 的保守下界。真实值在 A、B 之间(uncertain/scanned 需人工抽验)。")
    lines.append("")

    lines.append("## 双向报数(审计抽样口径)")
    lines.append("")
    fpos = bi["false_positive_suspected_wrong"]
    fneg = bi["false_negative_risk_possible_variant"]
    unv = bi["unverifiable"]
    lines.append(f"- **方向1｜假阳(收错风险)** = mismatch **{fpos['count']}** 条"
                 f"(其中边界带 {fpos['borderline_count']} 条)。{fpos['note']}")
    lines.append(f"- **方向2｜可能假阴(误杀风险)** = uncertain **{fneg['count']}** 条"
                 f"(其中边界带 {fneg['borderline_count']} 条)。{fneg['note']}")
    lines.append(f"- 无法判定:scanned **{unv['scanned']}** / unreadable **{unv['unreadable']}**。{unv['note']}")
    mmb = summary.get("mismatch_by_source_bucket", {})
    lines.append(f"- **mismatch 按下载来源**:publisher(同社错论文){mmb.get('publisher', 0)} / "
                 f"repository(仓库托管错论文){mmb.get('repository', 0)} / other(多与审计跨社重叠){mmb.get('other', 0)}。"
                 "前两桶正是审计『URL域×DOI前缀』法难判、本『标题不符』法独补的部分;两法取并集最全。")
    lines.append("")
    lines.append("> 需求①:扫描/图片/CID字体『抽不出正文』的 PDF **绝不判 mismatch**,单列 scanned(归 uncertain 家族);"
                 "需求②:mismatch/uncertain 三档而非二分,阈值不过严(mismatch<50 仍能锁定 cssc→jaad 一类 47.7 分明确错论文),"
                 "边界带样本供**双向人工抽样**——mismatch 抽样确认确为他刊他题,uncertain 抽样回收真命中。")
    lines.append("")

    sp = summary.get("systematic_patterns", {})
    pc = sp.get("counts", {})
    lines.append("## 系统性模式检测(审计 v2 四类测例/规则)")
    lines.append("")
    lines.append(f"- ① junk_domain(垃圾域命中):**{pc.get('junk_domain', 0)}** 条")
    lines.append(f"- ② same_pub_wrong_doi(同社近似DOI错论文,正文含同前缀异后缀DOI):**{pc.get('same_pub_wrong_doi', 0)}** 条")
    lines.append(f"- ③ cross_pub_wrong_doi(跨社错论文,正文含他社前缀DOI):**{pc.get('cross_pub_wrong_doi', 0)}** 条")
    lines.append(f"- ④ future_year(served年份>目标年份,物理不可能):**{pc.get('future_year', 0)}** 条")
    lines.append("")
    lines.append("> 均为证据/归类标签(记于每条 `patterns`),verdict 仍由标题主导以免正文引文DOI误报;供审计做测例与人核。")
    lines.append("")
    junk = sp.get("junk_domains", [])
    if junk:
        lines.append("### ① 垃圾域 Top(被塞给多种不同 DOI 前缀、0 命中)")
        lines.append("")
        lines.append("| 下载域 | 命中条数 | 不同DOI前缀数 | mismatch | 样本DOI |")
        lines.append("|---|---:|---:|---:|---|")
        for j in junk[:15]:
            sd = ", ".join((j.get("sample_dois") or [])[:4]).replace("|", "/")
            lines.append(f"| {j['domain']} | {j['records']} | {j['distinct_doi_prefixes']} | {j['mismatch']} | {sd} |")
        lines.append("")

    lines.append("## 分批")
    lines.append("")
    lines.append("| 批次 | 总 | match | mismatch | uncertain | scanned | unreadable |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for b, s in sorted(summary["by_batch"].items()):
        lines.append(f"| {b} | {s['total']} | {s['match']} | {s['mismatch']} | {s['uncertain']} | {s['scanned']} | {s['unreadable']} |")
    lines.append("")

    mm = [r for r in rows if r["verdict"] == "mismatch"]
    lines.append(f"## 疑似错论文(mismatch,{len(mm)} 条 — 审计抽样确认『确为他刊他题』)")
    lines.append("")
    if mm:
        lines.append("| 批次 | DOI | 期望 title | PDF 实际(元数据/首页片段) | score | 边界 | 来源域(桶) | 模式 |")
        lines.append("|---|---|---|---|---:|:--:|---|:--:|")
        _PCODE = {"junk_domain": "J", "same_pub_wrong_doi": "S", "cross_pub_wrong_doi": "X", "future_year": "Y"}
        for r in sorted(mm, key=lambda x: (x["title_score"] is not None, x["title_score"] or 0), reverse=True):
            et = (r["expected_title"] or "").replace("|", "/")[:80]
            pa = (r["pdf_actual"] or "").replace("|", "/")[:80]
            flag = "⚠" if r["borderline"] else ""
            dom = (r.get("url_domain") or "").replace("|", "/")[:34]
            bkt = {"publisher": "社", "repository": "库", "other": "他"}.get(r.get("source_bucket", "other"), "他")
            pcode = "".join(_PCODE.get(p, "") for p in r.get("patterns", []))
            lines.append(f"| {r['batch']} | {r['doi']} | {et} | {pa} | {r['title_score']} | {flag} | {dom}({bkt}) | {pcode} |")
    else:
        lines.append("(无)")
    lines.append("")

    unc = [r for r in rows if r["verdict"] == "uncertain"]
    lines.append(f"## 存疑(uncertain,{len(unc)} 条 — 可能假阴,审计抽样回收真命中)")
    lines.append("")
    if unc:
        lines.append("| 批次 | DOI | 期望 title | PDF 实际 | score | 边界 | 原因 |")
        lines.append("|---|---|---|---|---:|:--:|---|")
        for r in sorted(unc, key=lambda x: (x["title_score"] is not None, x["title_score"] or 0), reverse=True)[:80]:
            et = (r["expected_title"] or "").replace("|", "/")[:60]
            pa = (r["pdf_actual"] or "").replace("|", "/")[:60]
            flag = "⚠" if r["borderline"] else ""
            lines.append(f"| {r['batch']} | {r['doi']} | {et} | {pa} | {r['title_score']} | {flag} | {r['reason']} |")
        if len(unc) > 80:
            lines.append(f"| … | 其余 {len(unc) - 80} 条见 JSON | | | | | |")
    else:
        lines.append("(无)")
    lines.append("")

    scn = [r for r in rows if r["verdict"] == "scanned"]
    lines.append(f"## 抽不出正文(scanned,{len(scn)} 条 — 扫描/图片/CID字体,单列不判 mismatch)")
    lines.append("")
    if scn:
        lines.append("| 批次 | DOI | 期望 title | PDF 实际(元数据/片段) | score |")
        lines.append("|---|---|---|---|---:|")
        for r in scn[:60]:
            et = (r["expected_title"] or "").replace("|", "/")[:70]
            pa = (r["pdf_actual"] or "").replace("|", "/")[:70]
            lines.append(f"| {r['batch']} | {r['doi']} | {et} | {pa} | {r['title_score']} |")
        if len(scn) > 60:
            lines.append(f"| … | 其余 {len(scn) - 60} 条见 JSON | | | |")
    else:
        lines.append("(无)")
    lines.append("")

    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
