"""Internet Archive / Wayback Machine 存档 PDF 兜底源(按 DOI 或 URL 找存档快照)。

出版商 PDF / DOI 落地页常被 Wayback 存档,当在线原站付费墙/失效/被拦时,存档快照可作**免费兜底**。
本模块用两个官方只读 API 查存档并抽取「可直接取原文的」快照 URL(``id_`` 修饰符 → 去 Wayback 工具条):

  - 可用性 API:``https://archive.org/wayback/available?url=<URL>`` → 最近可用快照;
  - CDX API   :``https://web.archive.org/cdx/search/cdx?url=<URL>&output=json&filter=...`` → 历史快照表,
                可按 ``mimetype:application/pdf`` + ``statuscode:200`` 过滤,精确取存档 PDF。

产出:``web.archive.org/web/<timestamp>id_/<original>`` 形式的直取 URL 列表(下载交下游复用父包)。

按 DOI 查存档时,除 ``https://doi.org/<doi>``(其快照多为 HTML 跳转页、极少直接是 PDF)外,
还会补上**可由 DOI 确定性推导的常见出版商 PDF 直链**(Springer/Wiley/ACS/Nature),显著提升
"按 DOI 命中存档 PDF"的概率(URL 不可从 DOI 推导的 Elsevier/RSC/IEEE 等仍只靠 doi.org 兜底)。

设计:HTTP 用 curl_cffi(有则)否则 requests,**失败一律优雅跳过、绝不抛**;archive.org
限速(429/503)时**礼貌指数退避重试**;JSON 解析为纯函数,可注入取数(``fetch_json``)便于测试。
**离线 selftest 用 mock JSON 验证解析,不联网。**

对外接口:
    find_archived_pdf(doi=None, url=None, cfg=None, *, fetch_json=None, limit=20) -> list[str]
    parse_availability(data, *, pdf_only=True) -> list[str]
    parse_cdx(rows, *, pdf_only=True) -> list[str]
    build_availability_url(url) -> str ; build_cdx_url(url, *, limit=20, match_prefix=False) -> str
    _doi_candidate_urls(doi) -> list[str]   # doi.org + 可推导出版商 PDF 直链

合规:仅取 Wayback 已公开存档内容作 OA 兜底;尊重原始版权,下载后应核对元数据一致性。
离线自检:python -m fulltext_fetcher.sources.wayback  → 打印 WAYBACK_OK
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, List, Optional
from urllib.parse import quote

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_AVAIL_API = "https://archive.org/wayback/available"
_CDX_API = "https://web.archive.org/cdx/search/cdx"

# archive.org 限速(429/503)时的礼貌退避:默认底数(可经 cfg.wayback_backoff_base 覆盖)。
_BACKOFF_BASE_DEFAULT = 2.0
_RATE_LIMIT_CODES = (429, 503)


# ─────────────────────────── 小工具 ───────────────────────────
def _looks_pdf(url: Optional[str]) -> bool:
    low = (url or "").lower()
    path = low.split("#", 1)[0].split("?", 1)[0]
    return path.endswith(".pdf") or ".pdf?" in low or "/pdf/" in path


def _clean_doi(doi: str) -> str:
    """剥常见前缀得裸 DOI(供拼 https://doi.org/<doi>)。"""
    s = (doi or "").strip()
    low = s.lower()
    for p in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
              "http://dx.doi.org/", "doi:"):
        if low.startswith(p):
            s = s[len(p):]
            break
    return s.strip().rstrip(".,);")


def _doi_candidate_urls(doi: Optional[str]) -> List[str]:
    """由 DOI 生成 Wayback 查询候选:``https://doi.org/<doi>`` + 可**确定性推导**的常见出版商 PDF 直链。

    只收录"PDF URL 能从 DOI 直接拼出"的出版商——这样才可能在 Wayback 里精确命中存档 PDF;
    URL 不可从 DOI 推导的(Elsevier 10.1016 需 PII、RSC 10.1039、IEEE 10.1109 等)只保留 doi.org 兜底。
    去重保序返回。
    """
    d = _clean_doi(doi or "")
    if not d:
        return []
    urls = ["https://doi.org/" + d]
    prefix = d.split("/", 1)[0].lower()
    suffix = d.split("/", 1)[1] if "/" in d else ""
    if prefix in ("10.1007", "10.1140", "10.1186", "10.1023", "10.1057"):   # Springer 系
        urls.append("https://link.springer.com/content/pdf/" + d + ".pdf")
    elif prefix == "10.1002":                                                # Wiley
        urls.append("https://onlinelibrary.wiley.com/doi/pdfdirect/" + d)
        urls.append("https://onlinelibrary.wiley.com/doi/pdf/" + d)
    elif prefix == "10.1021":                                                # ACS
        urls.append("https://pubs.acs.org/doi/pdf/" + d)
    elif prefix == "10.1038" and suffix:                                     # Nature
        urls.append("https://www.nature.com/articles/" + suffix + ".pdf")
    # 去重保序
    seen: set = set()
    out: List[str] = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _to_id_url(wb_url: Optional[str]) -> Optional[str]:
    """把 Wayback 页面 URL 转成 ``id_`` 原始取回形式并强制 https。

    ``http://web.archive.org/web/<ts>/<orig>`` → ``https://web.archive.org/web/<ts>id_/<orig>``。
    已是 id_ 形式则仅规范 https。无法识别 → None。
    """
    if not wb_url:
        return None
    u = str(wb_url).strip()
    if not u:
        return None
    u = re.sub(r"^http://", "https://", u)
    if "/web/" not in u:
        return None
    if not re.search(r"/web/\d+id_/", u):
        u = re.sub(r"(/web/\d+)/", r"\1id_/", u, count=1)
    return u


def _orig_of(id_url: str) -> str:
    """从 ``.../web/<ts>id_/<orig>`` 抽出原始 URL(供 pdf 形态判断)。"""
    return re.sub(r"^https?://web\.archive\.org/web/\d+(?:id_)?/", "", id_url or "")


# ─────────────────────────── URL 构造 ───────────────────────────
def build_availability_url(url: str) -> str:
    return f"{_AVAIL_API}?url=" + quote(url or "", safe="")


def build_cdx_url(url: str, *, limit: int = 20, match_prefix: bool = False) -> str:
    """CDX 查询 URL:默认过滤 application/pdf + 200、按 digest 去重、限量。

    match_prefix=True 时用 ``matchType=prefix`` 找该路径下的所有存档(找落地页附带的 PDF)。
    """
    parts = [
        "url=" + quote(url or "", safe=""),
        "output=json",
        "filter=mimetype:application/pdf",
        "filter=statuscode:200",
        "collapse=digest",
        "limit=" + str(int(limit)),
    ]
    if match_prefix:
        parts.append("matchType=prefix")
    return _CDX_API + "?" + "&".join(parts)


# ─────────────────────────── 纯解析(可离线测试)───────────────────────────
def parse_availability(data: Any, *, pdf_only: bool = True) -> List[str]:
    """解析可用性 API 响应 → [id_ URL];不可用/非200/(pdf_only 时)非 PDF → []。绝不抛。"""
    try:
        snap = ((data or {}).get("archived_snapshots") or {}).get("closest") or {}
    except AttributeError:
        return []
    if not snap.get("available"):
        return []
    status = str(snap.get("status") or "")
    if status and status != "200":
        return []
    idurl = _to_id_url(snap.get("url"))
    if not idurl:
        return []
    if pdf_only and not _looks_pdf(_orig_of(idurl)):
        return []
    return [idurl]


def parse_cdx(rows: Any, *, pdf_only: bool = True) -> List[str]:
    """解析 CDX output=json(首行表头 + 记录行)→ [id_ URL],去重保序;非200/(pdf_only 时)非 PDF 跳过。绝不抛。"""
    if not isinstance(rows, list) or len(rows) < 2 or not isinstance(rows[0], list):
        return []
    header = [str(c).lower() for c in rows[0]]

    def _idx(name: str) -> int:
        return header.index(name) if name in header else -1

    ts_i, orig_i, mt_i, sc_i = _idx("timestamp"), _idx("original"), _idx("mimetype"), _idx("statuscode")
    if ts_i < 0 or orig_i < 0:
        return []
    out: List[str] = []
    for row in rows[1:]:
        if not isinstance(row, list) or ts_i >= len(row) or orig_i >= len(row):
            continue
        sc = str(row[sc_i]) if 0 <= sc_i < len(row) else ""
        if sc and sc != "200":
            continue
        mt = str(row[mt_i]).lower() if 0 <= mt_i < len(row) else ""
        orig = str(row[orig_i])
        if pdf_only and not (mt == "application/pdf" or _looks_pdf(orig)):
            continue
        idurl = f"https://web.archive.org/web/{row[ts_i]}id_/{orig}"
        if idurl not in out:
            out.append(idurl)
    return out


# ─────────────────────────── HTTP(失败优雅跳过)───────────────────────────
def _get_json(url: str, cfg: Any = None, *, retries: int = 2) -> Any:
    """GET JSON:curl_cffi(有则,impersonate)否则 requests;非 200 / 异常 / 非 JSON → None。

    archive.org 限速(429/503)时**礼貌指数退避**并重试至多 ``retries`` 次(底数取
    ``cfg.wayback_backoff_base``,缺省 2.0s);其余非 200 直接 None,异常也退避后放弃。绝不抛。
    """
    timeout = float(getattr(cfg, "timeout", 30.0) or 30.0)
    base = float(getattr(cfg, "wayback_backoff_base", 0) or _BACKOFF_BASE_DEFAULT)
    for attempt in range(retries + 1):
        try:
            try:
                from curl_cffi import requests as creq  # 延迟导入
                r = creq.get(url, impersonate="chrome", timeout=timeout)
            except ImportError:
                import requests as rq
                r = rq.get(url, timeout=timeout, headers={"User-Agent": _UA})
            sc = getattr(r, "status_code", None)
            if sc in _RATE_LIMIT_CODES:            # 被限速/过载 → 礼貌退避后重试
                if attempt < retries:
                    time.sleep(base * (attempt + 1))
                    continue
                return None
            if sc != 200:
                return None
            return r.json()
        except Exception:  # noqa: BLE001 - 网络/解析异常:退避后重试,仍失败则优雅跳过
            if attempt < retries:
                time.sleep(base * (attempt + 1))
                continue
            return None
    return None


# ─────────────────────────── 对外主入口 ───────────────────────────
def find_archived_pdf(doi: Optional[str] = None, url: Optional[str] = None, cfg: Any = None,
                      *, fetch_json: Optional[Callable[[str], Any]] = None,
                      limit: int = 20) -> List[str]:
    """按 DOI 或 URL 找 Wayback 存档 PDF,返回可直取的 id_ 快照 URL 列表(去重保序,可空)。

    - url:优先直接查(出版商 PDF / 落地页);doi:另查 ``https://doi.org/<doi>``。
    - 每个目标依次走 可用性 API + CDX(mimetype=application/pdf)API,合并去重。
    - fetch_json 可注入(selftest 用 mock);缺省用 _get_json(curl_cffi/requests,失败跳过)。
    - 任一步失败/无结果都不抛,返回已得到的(可能为空)列表。
    """
    fetch = fetch_json or (lambda u: _get_json(u, cfg))
    targets: List[str] = []
    if url:
        targets.append(str(url).strip())
    if doi:
        # doi.org + 可推导的出版商 PDF 直链(显著提升按 DOI 命中存档 PDF 的概率)
        targets.extend(_doi_candidate_urls(doi))
    # 去重保序(url 与 doi 候选、多来源可能重叠)
    _seen_t: set = set()
    targets = [t for t in targets if t and not (t in _seen_t or _seen_t.add(t))]

    out: List[str] = []
    for target in targets:
        if not target:
            continue
        try:
            av = fetch(build_availability_url(target))
        except Exception:  # noqa: BLE001
            av = None
        for u in parse_availability(av):
            if u not in out:
                out.append(u)
        try:
            cdx = fetch(build_cdx_url(target, limit=limit))
        except Exception:  # noqa: BLE001
            cdx = None
        for u in parse_cdx(cdx):
            if u not in out:
                out.append(u)
        if len(out) >= limit:
            break
    return out[:limit]


if __name__ == "__main__":  # 离线 selftest(mock JSON,不联网): python -m fulltext_fetcher.sources.wayback
    # ① parse_availability:可用 PDF 快照 → id_ URL
    av_pdf = {"archived_snapshots": {"closest": {
        "available": True, "status": "200", "timestamp": "20200101000000",
        "url": "http://web.archive.org/web/20200101000000/https://pub.org/a.pdf"}}}
    assert parse_availability(av_pdf) == [
        "https://web.archive.org/web/20200101000000id_/https://pub.org/a.pdf"], parse_availability(av_pdf)

    # 不可用 / 缺字段 / 非200 → []
    assert parse_availability({"archived_snapshots": {}}) == []
    assert parse_availability({"archived_snapshots": {"closest": {"available": False}}}) == []
    assert parse_availability({}) == [] and parse_availability(None) == []
    av_404 = {"archived_snapshots": {"closest": {"available": True, "status": "404",
              "timestamp": "20200101000000",
              "url": "http://web.archive.org/web/20200101000000/https://pub.org/a.pdf"}}}
    assert parse_availability(av_404) == []

    # 非 PDF 原始:pdf_only 排除;pdf_only=False 收录(并转 id_)
    av_html = {"archived_snapshots": {"closest": {"available": True, "status": "200",
               "timestamp": "20200101000000",
               "url": "http://web.archive.org/web/20200101000000/https://pub.org/landing.html"}}}
    assert parse_availability(av_html) == []
    assert parse_availability(av_html, pdf_only=False) == [
        "https://web.archive.org/web/20200101000000id_/https://pub.org/landing.html"]

    # ② parse_cdx:表头 + 记录;pdf/200 收,非200/非pdf 跳,去重
    rows = [
        ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
        ["org,pub)/a.pdf", "20190101000000", "https://pub.org/a.pdf", "application/pdf", "200", "D1", "1000"],
        ["org,pub)/b.pdf", "20180101000000", "https://pub.org/b.pdf", "application/pdf", "404", "D2", "0"],
        ["org,pub)/c", "20170101000000", "https://pub.org/c", "text/html", "200", "D3", "0"],
        ["org,pub)/a.pdf", "20190101000000", "https://pub.org/a.pdf", "application/pdf", "200", "D1", "1000"],
    ]
    assert parse_cdx(rows) == [
        "https://web.archive.org/web/20190101000000id_/https://pub.org/a.pdf"], parse_cdx(rows)
    assert parse_cdx([]) == [] and parse_cdx([["only-header"]]) == [] and parse_cdx(None) == []

    # ③ URL 构造
    assert build_availability_url("https://pub.org/a.pdf").startswith(
        "https://archive.org/wayback/available?url=")
    cdx_url = build_cdx_url("https://pub.org/a.pdf", limit=5)
    assert "filter=mimetype:application/pdf" in cdx_url and "output=json" in cdx_url and "limit=5" in cdx_url
    assert "matchType=prefix" in build_cdx_url("https://pub.org/", match_prefix=True)

    # ④ find_archived_pdf:注入 mock 取数,合并可用性 + CDX,去重
    def _mock(u: str) -> Any:
        if "wayback/available" in u:
            return av_pdf
        if "cdx/search" in u:
            return rows
        return None

    res = find_archived_pdf(url="https://pub.org/a.pdf", fetch_json=_mock)
    assert "https://web.archive.org/web/20200101000000id_/https://pub.org/a.pdf" in res, res
    assert "https://web.archive.org/web/20190101000000id_/https://pub.org/a.pdf" in res, res
    assert len(res) == len(set(res)), res                       # 去重

    # DOI 路径(拼 doi.org)+ limit 截断
    res_doi = find_archived_pdf(doi="doi:10.1000/xyz", fetch_json=_mock, limit=1)
    assert isinstance(res_doi, list) and len(res_doi) <= 1, res_doi

    # ⑤ 失败/无输入 优雅:取数恒 None → [];无 doi/url → []
    assert find_archived_pdf(url="https://pub.org/a.pdf", fetch_json=lambda u: None) == []
    assert find_archived_pdf() == []

    # ⑥ _doi_candidate_urls:doi.org 首位 + 可推导出版商 PDF 直链;不可推导者仅 doi.org
    acs = _doi_candidate_urls("10.1021/acscatal.7b01827")
    assert acs[0] == "https://doi.org/10.1021/acscatal.7b01827", acs
    assert "https://pubs.acs.org/doi/pdf/10.1021/acscatal.7b01827" in acs, acs
    wl = _doi_candidate_urls("doi:10.1002/aic.690210612")       # 带 doi: 前缀也要剥
    assert "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/aic.690210612" in wl, wl
    assert "https://onlinelibrary.wiley.com/doi/pdf/10.1002/aic.690210612" in wl, wl
    nat = _doi_candidate_urls("10.1038/s41929-019-0266-y")
    assert "https://www.nature.com/articles/s41929-019-0266-y.pdf" in nat, nat
    spr = _doi_candidate_urls("10.1007/s10562-020-03210-2")
    assert "https://link.springer.com/content/pdf/10.1007/s10562-020-03210-2.pdf" in spr, spr
    els = _doi_candidate_urls("10.1016/j.jcis.2018.03.044")     # Elsevier 不可推导 → 仅 doi.org
    assert els == ["https://doi.org/10.1016/j.jcis.2018.03.044"], els
    assert _doi_candidate_urls("") == [] and _doi_candidate_urls(None) == []

    print("WAYBACK_OK")
