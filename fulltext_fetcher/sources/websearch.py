"""免费网页搜索引擎(DuckDuckGo / Bing)按标题/DOI 发现可下载 PDF 候选(仅产候选、不下载)。

用途:对"OA 源都没命中"的论文,借免费搜索引擎的 SERP 找作者自存稿 / 机构库 / ResearchGate /
实验室主页上的 PDF。**只返回候选 URL 列表**,真正下载/校验仍复用父包(download.py)。

合规与稳健:
- 优先 DuckDuckGo HTML 端点(html.duckduckgo.com/html/)与 Bing(www.bing.com/search),二者通常
  **无 CAPTCHA**;失败即优雅跳过,绝不硬刚、绝不崩。
- HTTP 走 `curl_cffi`(impersonate=chrome,复用现有可选依赖);缺库降级标准库 `urllib`;都不可用
  或异常 → 返回 None/[](优雅降级)。**可选依赖一律函数内延迟导入,不进强制依赖。**
- 纯解析(SERP HTML → 候选 URL)为**离线纯函数**,自带 selftest(固定本地 HTML),打印 WEBSEARCH_OK。

对外接口(冻结,供后续由总指挥接线到 sources/__init__ + config):
    search_pdf_candidates(title, doi, cfg=None) -> list[str]
        · 返回前自动经 prefilter_candidates 做**下载前**候选预过滤(去黑名单域 / 未来年份错 DOI /
          嵌入 DOI 与目标不符,并对跨出版商 host 降权),减少"错论文"假阳;总开关
          cfg.websearch_prefilter(默认 True,置 False 整体回退)。与 download.py 的下载后内容门配对纵深防御。
    prefilter_candidates(urls, doi, *, cfg=None) -> list[str]   # 纯函数,可单测/复用

文件边界:本模块只新建 sources/websearch.py;**不改**任何既有/共享文件(sources/__init__.py /
config.py / pipeline.py / run_all_selftests.py 等,集成由总指挥统一做)。故本模块**不 @register**。
"""
from __future__ import annotations

import base64
import datetime as _dt
import html as _html
import re
import time
from typing import Any, List, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

_DDG_HTML = "https://html.duckduckgo.com/html/"
_DDG_LITE = "https://lite.duckduckgo.com/lite/"
_BING = "https://www.bing.com/search"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 搜索引擎自身 / 导航域名:其结果页里的这些链接是站内导航,非检索结果,过滤掉。
_ENGINE_HOSTS = (
    "duckduckgo.com", "bing.com", "microsoft.com", "msn.com",
    "microsofttranslator.com", "go.microsoft.com", "support.microsoft.com",
)

# 已知"全文/自存稿"域名(命中即视为可下载候选,即使 URL 不以 .pdf 结尾)。
_FULLTEXT_HOSTS = (
    "researchgate.net", "arxiv.org", "biorxiv.org", "medrxiv.org", "chemrxiv.org",
    "europepmc.org", "ncbi.nlm.nih.gov", "semanticscholar.org", "core.ac.uk",
    "ssrn.com", "academia.edu", "hal.science", "hal.archives-ouvertes.fr",
    "zenodo.org", "osf.io", "preprints.org", "researchsquare.com", "figshare.com",
)
# 机构库/仓储常见路径特征(DSpace/EPrints 等)。
_REPO_PATH_HINTS = ("/bitstream/", "/handle/", "/download/", "/viewcontent", "/fulltext")

_A_HREF_RE = re.compile(r'<a\b[^>]*\bhref\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', re.I)

_CONF_PDF = 80        # 直链 .pdf / 含 /pdf
_CONF_FULLTEXT = 55   # 已知全文域名 / 机构库路径

# ───────────── 下载前候选预过滤:减少 websearch"错论文"假阳(审计实锤 ≥14%)─────────────
# 与 161 的"下载后内容比对门"(download.py)配对做纵深防御:此处在**下载前**丢弃/降权明显错论文候选,
# 省流量 + 提精度。总开关 cfg.websearch_prefilter(默认 True;置 False 整体回退)。
#
# ① 垃圾域黑名单:审计发现会当"通配答案"命中大量无关查询的域(websearch 专用;合法金 OA 由
#    publisher_oa 等源另行覆盖,不受影响)。可经 cfg.websearch_blacklist_hosts 追加更多域。
_PREFILTER_BLACKLIST_HOSTS = (
    "frontiersin.org",   # 含 public-pages-files-*.frontiersin.org:审计实锤的通配假阳域
)
# ④ DOI 注册前缀 → 该出版商官方托管域(仅用于"跨出版商 host 不符"的保守降权:论文正本不会挂在
#    竞争出版商域名下,故"目标属 A 出版商、候选落在 B 出版商域"是强错论文信号)。
# 前缀标签集与 161 在 download.py 的下载后内容门(_QC_PREFIX_LABELS / _QC_HOST_LABELS)对齐,
# 避免前后两层判据发散;后续若抽 tools/publisher_map.py 共享表,两边 import 同一份(由 156 统筹)。
_PUBLISHER_BY_PREFIX = {
    "10.1016": ("sciencedirect.com", "elsevier.com"),                    # Elsevier
    "10.1021": ("pubs.acs.org", "acs.org"),                              # ACS
    "10.1039": ("pubs.rsc.org", "rsc.org"),                             # RSC
    "10.1002": ("onlinelibrary.wiley.com", "wiley.com"),               # Wiley
    "10.1111": ("onlinelibrary.wiley.com", "wiley.com"),               # Wiley
    "10.1007": ("link.springer.com", "springer.com", "springerlink.com"),  # Springer
    "10.1038": ("nature.com",),                                        # Nature / NPG
    "10.1080": ("tandfonline.com",),                                   # Taylor & Francis
    "10.1109": ("ieeexplore.ieee.org", "ieee.org"),                    # IEEE
    "10.1126": ("science.org", "sciencemag.org"),                      # AAAS / Science
    "10.1073": ("pnas.org",),                                          # PNAS
    "10.1093": ("academic.oup.com", "oup.com"),                        # OUP
    "10.3390": ("mdpi.com",),                                          # MDPI
    "10.1186": ("biomedcentral.com",),                                 # BMC
    "10.1371": ("journals.plos.org", "plos.org"),                      # PLOS
    "10.1088": ("iopscience.iop.org", "iop.org"),                      # IOP
    "10.1103": ("journals.aps.org", "aps.org"),                        # APS
    "10.1063": ("pubs.aip.org", "aip.scitation.org", "aip.org"),       # AIP
    "10.1177": ("journals.sagepub.com", "sagepub.com"),               # SAGE
    "10.1136": ("bmj.com",),                                           # BMJ
    "10.3389": ("frontiersin.org",),                                   # Frontiers(websearch 层已黑;此项供 target 侧④)
    "10.1145": ("dl.acm.org", "acm.org"),                              # ACM
    "10.1049": ("digital-library.theiet.org", "theiet.org",           # IET(部分卷经 Wiley 托管,故并列)
                "onlinelibrary.wiley.com", "wiley.com"),
}
_ALL_PUBLISHER_HOSTS = tuple(sorted({h for hs in _PUBLISHER_BY_PREFIX.values() for h in hs}))
# 内嵌 DOI 抽取(在 URL 内定位 10.xxxx/… 片段)。
_DOI_IN_TEXT_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>?#]+", re.I)


# ────────────────────────── 查询构造 ──────────────────────────
def _clean_text(s: Optional[str]) -> str:
    """清洗标题/DOI:反转义 HTML 实体 + 去 HTML 标签(<sub>/<sup>/<i> 等)+ 归一空白。

    Crossref/父包 metadata 的 title 常含 `CO<sub>2</sub>`、`&amp;` 等;直接进 query 会污染检索
    (实网实测:DuckDuckGo 因此返回 "no results")。故检索前必须先清洗——这是实网命中的关键修复。
    """
    s = _html.unescape(s or "")
    s = re.sub(r"<[^>]+>", "", s)          # 去标签为空:CO<sub>2</sub> → CO2(下标不被拆开)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _build_queries(title: Optional[str], doi: Optional[str]) -> List[str]:
    """多策略 query(标题先清洗去 HTML):精确标题+filetype:pdf、+site:researchgate、纯精确标题、DOI+filetype。"""
    out: List[str] = []
    t = _clean_text(title)
    d = _clean_text(doi).rstrip(".,);")
    if t:
        out.append(f'"{t}" filetype:pdf')
        out.append(f'"{t}" site:researchgate.net')
        out.append(f'"{t}"')                        # 纯精确标题:召回 RG/机构库/课题组主页等全文落地页
    if d:
        out.append(f'{d} filetype:pdf')
    # 去重保序
    seen: set = set()
    uniq: List[str] = []
    for q in out:
        if q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq


def _engine_urls(query: str, engines: Optional[List[str]] = None) -> List[str]:
    """给定 query → 选定搜索引擎的结果页 URL(GET)。engines 默认 ('ddg','bing');可选 'ddg_lite'。

    实网实测(2026-07,本机 IP):DuckDuckGo html 端点常被限速返回 0 结果,Bing 稳定返回;
    故可经 cfg.websearch_engines 调整引擎集(如仅 ['bing'] 或加 'ddg_lite' 兜底)。
    """
    q = quote_plus(query)
    eng = [e.lower() for e in (engines or ("ddg", "bing"))]
    urls: List[str] = []
    if "ddg" in eng:
        urls.append(f"{_DDG_HTML}?q={q}")
    if "ddg_lite" in eng:
        urls.append(f"{_DDG_LITE}?q={q}")
    if "bing" in eng:
        urls.append(f"{_BING}?q={q}&count=20")
    return urls


# ────────────────────────── SERP 解析(离线纯函数)──────────────────────────
def _decode_ddg(href: str) -> str:
    """DuckDuckGo HTML 结果是重定向链 //duckduckgo.com/l/?uddg=<编码真链> → 解出真链。"""
    low = href.lower()
    if "duckduckgo.com/l/" in low and "uddg=" in low:
        try:
            probe = href if "//" in href else "//" + href
            vals = parse_qs(urlparse(probe).query).get("uddg")
            if vals:
                return unquote(vals[0])
        except Exception:  # noqa: BLE001
            pass
    return href


def _decode_bing_ck(href: str) -> str:
    """Bing 有时用 /ck/a?...&u=a1<base64> 包装真链;best-effort 解出,失败返回原串。"""
    low = href.lower()
    if "bing.com/ck/a" not in low or "u=" not in low:
        return href
    try:
        u = parse_qs(urlparse(href).query).get("u")
        if not u:
            return href
        raw = u[0]
        if raw[:2].lower() == "a1":       # Bing 前缀标记
            raw = raw[2:]
        pad = "=" * (-len(raw) % 4)
        dec = base64.urlsafe_b64decode(raw + pad).decode("utf-8", "replace")
        if dec.lower().startswith(("http://", "https://")):
            return dec
    except Exception:  # noqa: BLE001
        pass
    return href


def _is_engine_host(host: str) -> bool:
    host = (host or "").lower()
    return any(host == h or host.endswith("." + h) for h in _ENGINE_HOSTS)


def extract_result_urls(html: str) -> List[str]:
    """从 DDG/Bing SERP HTML 抽取"检索结果真链"(解重定向、去站内导航、去重保序)。纯函数、不抛。"""
    out: List[str] = []
    if not isinstance(html, str) or not html:
        return out
    seen: set = set()
    for m in _A_HREF_RE.finditer(html):
        href = _html.unescape((m.group(1) or m.group(2) or "").strip())
        if not href:
            continue
        real = _decode_ddg(href)
        real = _decode_bing_ck(real)
        if real.startswith("//"):
            real = "https:" + real
        if not real.lower().startswith(("http://", "https://")):
            continue
        try:
            host = urlparse(real).netloc.lower()
        except Exception:  # noqa: BLE001
            continue
        if not host or _is_engine_host(host):
            continue
        if real not in seen:
            seen.add(real)
            out.append(real)
    return out


def _pdf_confidence(url: str) -> Optional[int]:
    """给候选 URL 评分:.pdf/含 /pdf → 高;已知全文域名/机构库路径 → 中;其余 → None(丢弃)。"""
    try:
        p = urlparse(url)
    except Exception:  # noqa: BLE001
        return None
    host = (p.netloc or "").lower()
    path = (p.path or "").lower()
    if path.endswith(".pdf") or "/pdf" in path or ".pdf" in path:
        return _CONF_PDF
    if host.endswith(".edu"):
        return _CONF_FULLTEXT
    if any(host == h or host.endswith("." + h) for h in _FULLTEXT_HOSTS):
        return _CONF_FULLTEXT
    if any(hint in path for hint in _REPO_PATH_HINTS):
        return _CONF_FULLTEXT
    return None


def filter_pdf_candidates(urls: List[str]) -> List[str]:
    """把结果真链过滤为"疑似可下载 PDF/全文"候选,去重后按可信度降序返回(稳定)。"""
    scored = []
    seen: set = set()
    for i, u in enumerate(urls or []):
        if not u or u in seen:
            continue
        conf = _pdf_confidence(u)
        if conf is None:
            continue
        seen.add(u)
        scored.append((conf, i, u))          # i 保证同分稳定(保持出现顺序)
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [u for _, _, u in scored]


def parse_serp_for_pdfs(html: str) -> List[str]:
    """离线纯解析:一页 SERP HTML → 疑似 PDF/全文 候选 URL(供 selftest 与 search 复用)。"""
    return filter_pdf_candidates(extract_result_urls(html))


# ────────────── 下载前候选预过滤(纯函数、不联网、绝不抛)──────────────
def _norm_doi(doi: Optional[str]) -> str:
    """归一 DOI 用于比较:去 doi.org/scheme 前缀、小写、去首尾空白与尾部标点。"""
    d = _clean_text(doi).lower()
    for pre in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                "http://dx.doi.org/", "doi.org/", "doi:"):
        if d.startswith(pre):
            d = d[len(pre):]
            break
    return d.strip().rstrip(".,);]")


def _safe_unquote(s: str) -> str:
    try:
        return unquote(s or "")
    except Exception:  # noqa: BLE001
        return s or ""


def _embedded_dois(url: str) -> List[str]:
    """从候选 URL(先 URL 解码)抽取所有内嵌 DOI(小写、去尾部标点),去重保序。"""
    out: List[str] = []
    seen: set = set()
    for m in _DOI_IN_TEXT_RE.finditer(_safe_unquote(url)):
        d = m.group(0).lower().rstrip(".,);]")
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _doi_matches(a: str, b: str) -> bool:
    """DOI 宽松相等:相等,或一方是另一方前缀(容忍 URL 内 DOI 带 .pdf / 路径尾巴)。"""
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def _year_from_doi(doi: Optional[str]) -> Optional[int]:
    """尽力从 DOI 抽发表年(仅高置信:Springer/Nature s#####-0YY-,或 DOI 内 19xx/20xx);取不到→None。"""
    if not doi:
        return None
    d = doi.lower()
    m = re.search(r"s\d{4,6}-(\d{3})-", d)     # s41598-020- → 2020;s41598-026- → 2026
    if m:
        n = int(m.group(1))
        if 0 <= n <= 99:
            return 2000 + n
    m = re.search(r"(?:19|20)\d{2}", d)         # j.apsusc.2022.… / cvpr.2016.90
    if m:
        return int(m.group(0))
    return None


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def _host_in(host: str, hosts) -> bool:
    host = (host or "").lower()
    return any(host == h or host.endswith("." + h) for h in (hosts or ()))


def _is_selfarchive_host(host: str) -> bool:
    """仓储/自存稿/机构域(合法托管他社论文):②③④ 对其保守放行,交给下载后内容门把关。"""
    host = (host or "").lower()
    if host.endswith(".edu") or host.endswith(".ac.uk") or ".edu." in host:
        return True
    return _host_in(host, _FULLTEXT_HOSTS)


def _publisher_hosts_for_doi(doi: str) -> tuple:
    """目标 DOI → 其出版商官方域元组(未知前缀 → ())。"""
    m = re.match(r"(10\.\d{4,9})/", doi or "")
    return _PUBLISHER_BY_PREFIX.get(m.group(1), ()) if m else ()


def prefilter_candidates(urls: List[str], doi: Optional[str] = None, *,
                         cfg: Any = None, current_year: Optional[int] = None,
                         blacklist=None, enable: Optional[bool] = None) -> List[str]:
    """下载前预过滤候选 URL,丢弃/降权明显"错论文"候选(纯函数、不联网、异常即放行原候选)。

    规则(cfg.websearch_prefilter=True 时生效,默认 True;False 整体回退):
      ① 垃圾域黑名单(frontiersin 等审计通配假阳域)→ 丢
      ② 未来/晚于目标年:候选内嵌(非目标)DOI 的年 > 当前年 或 > 目标 DOI 年 → 丢(物理不可能同篇)
      ③ 嵌入 DOI 不符:URL 内嵌明确 !=目标 的 DOI 且目标 DOI 不在 URL → 丢(指向别的论文)
      ④ 跨出版商 host 不符:目标属某出版商而候选落在"另一已知出版商"域(非仓储/edu)→ 降权(移末尾)
    保守起见:②③ 仅对"非仓储/自存稿/edu 域"生效,避免误杀机构库 / ResearchGate / arXiv 等合法托管。
    返回过滤后的 URL 列表(保序;被降权者置于末尾)。
    """
    urls = [u for u in (urls or []) if isinstance(u, str) and u]
    if enable is None:
        enable = bool(getattr(cfg, "websearch_prefilter", True))
    if not enable or not urls:
        return urls
    try:
        if current_year is None:
            current_year = int(getattr(cfg, "websearch_current_year", 0) or 0) or _dt.date.today().year
        bl = tuple(_PREFILTER_BLACKLIST_HOSTS)
        extra = blacklist if blacklist is not None else getattr(cfg, "websearch_blacklist_hosts", None)
        if extra:
            bl = bl + tuple(h.lower() for h in extra if isinstance(h, str) and h)

        target = _norm_doi(doi) if doi else ""
        target_year = _year_from_doi(target) if target else None
        target_pub = _publisher_hosts_for_doi(target) if target else ()

        keep: List[str] = []
        demote: List[str] = []
        for u in urls:
            host = _host_of(u)
            u_low = _safe_unquote(u).lower()
            embs = _embedded_dois(u)
            target_in_url = bool(target) and (target in u_low
                                              or any(_doi_matches(e, target) for e in embs))
            selfarchive = _is_selfarchive_host(host)

            # ① 垃圾域黑名单 → 丢(但"目标 DOI 明确在 URL 内"则保留:通配假阳页不含目标 DOI,
            #    而合法目标页含之——如 Frontiers 正规 OA 目标文章页,借此避免误杀正确论文)
            if host and _host_in(host, bl) and not target_in_url:
                continue

            # ②③ 用内嵌 DOI 判错(仅非仓储域;仓储/自存稿保守放行,交给下载后内容门)
            if embs and not selfarchive and not target_in_url:
                foreign_years = [y for y in
                                 (_year_from_doi(e) for e in embs
                                  if not (target and _doi_matches(e, target))) if y]
                cand_year = max(foreign_years) if foreign_years else None
                # ② 未来 / 晚于目标年 → 丢
                if cand_year and (cand_year > current_year
                                  or (target_year and cand_year > target_year)):
                    continue
                # ③ 内嵌别的 DOI、且目标 DOI 不在 URL → 丢(title-only 无目标则不判)
                if target:
                    continue

            # ④ 跨出版商 host 不符 → 降权(移末尾)
            if (target_pub and host and not target_in_url and not selfarchive
                    and _host_in(host, _ALL_PUBLISHER_HOSTS)
                    and not _host_in(host, target_pub)):
                demote.append(u)
                continue

            keep.append(u)
        return keep + demote
    except Exception:  # noqa: BLE001 - 预过滤绝不拖垮主流程,异常即放行原候选
        return urls


# ────────────────────────── HTTP 取回(curl_cffi → urllib → 跳过)──────────────────────────
def _http_get(url: str, cfg: Any = None, timeout: float = 20.0) -> Optional[str]:
    """取回 SERP HTML:优先 curl_cffi(impersonate),缺库降级 urllib;任何异常 → None(优雅跳过)。"""
    impersonate = getattr(cfg, "impersonate", None) or "chrome"
    headers = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
    try:
        from curl_cffi import requests as creq  # 可选依赖,函数内延迟导入
        try:
            r = creq.get(url, impersonate=impersonate, timeout=timeout,
                         headers=headers, allow_redirects=True)
            return r.text if getattr(r, "status_code", None) == 200 else None
        except Exception:  # noqa: BLE001 - 网络异常 → 跳过
            return None
    except ImportError:
        pass
    try:
        import urllib.request
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定搜索引擎域名
            if getattr(resp, "status", 200) != 200:
                return None
            return resp.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None


def search_pdf_candidates(title: Optional[str], doi: Optional[str], cfg: Any = None,
                          *, _fetch: Any = None, max_results: int = 12) -> List[str]:
    """用免费搜索引擎按 title/DOI 发现可下载 PDF 候选,返回去重排序的 URL 列表(不下载)。

    - 多策略 query × (DuckDuckGo HTML + Bing),聚合各页结果真链后统一过滤/排序。
    - `_fetch`:注入的取回函数 fetch(url, cfg)->html|None(测试/自定义);None → 用内建 _http_get。
    - 无 title/doi、或全程取不到页 → 返回 [](优雅降级,绝不抛)。
    """
    queries = _build_queries(title, doi)
    if not queries:
        return []
    engines = getattr(cfg, "websearch_engines", None)
    interval = float(getattr(cfg, "websearch_interval", 1.0) or 0.0)
    timeout = float(getattr(cfg, "websearch_timeout", 20.0) or 20.0)
    polite = _fetch is None                     # 仅真实取回时礼貌限速(不拖慢离线 selftest)
    fetch = _fetch or (lambda u, c: _http_get(u, c, timeout=timeout))
    raw: List[str] = []
    first = True
    for q in queries:
        for url in _engine_urls(q, engines):
            if polite and interval and not first:
                time.sleep(interval)            # 错峰礼貌限速,降低触发搜索引擎风控概率
            first = False
            try:
                html = fetch(url, cfg)
            except Exception:  # noqa: BLE001 - 单次取回异常不拖垮整体
                html = None
            if html:
                raw.extend(extract_result_urls(html))
    ranked = prefilter_candidates(filter_pdf_candidates(raw), doi, cfg=cfg)
    return ranked[:max_results]


# ────────────────────────── 不联网 selftest ──────────────────────────
def _selftest() -> int:
    # ① 查询构造:三种策略齐全
    qs = _build_queries("Deep Residual Learning", "10.1109/CVPR.2016.90")
    assert '"Deep Residual Learning" filetype:pdf' in qs, qs
    assert '"Deep Residual Learning" site:researchgate.net' in qs, qs
    assert "10.1109/CVPR.2016.90 filetype:pdf" in qs, qs
    assert _build_queries("", "") == [], "空输入应无 query"
    assert _build_queries("only title", None)  # 仅标题也可

    # ①b 标题 HTML 清洗(实网关键修复):<sub>/HTML 实体去除后再进 query
    assert _clean_text("CO<sub>2</sub> &amp; H<sub>2</sub>O reduction") == "CO2 & H2O reduction"
    qs2 = _build_queries("Ni<sub>3</sub>N Catalysis", None)
    assert '"Ni3N Catalysis" filetype:pdf' in qs2 and '"Ni3N Catalysis"' in qs2, qs2

    # ①c 引擎可选:默认含 DDG+Bing;可经 cfg.websearch_engines 仅选 Bing
    assert any("duckduckgo" in u for u in _engine_urls("q")), _engine_urls("q")
    assert any("bing.com" in u for u in _engine_urls("q")), _engine_urls("q")
    only_bing = _engine_urls("q", ["bing"])
    assert len(only_bing) == 1 and "bing.com" in only_bing[0], only_bing

    # ② DuckDuckGo HTML:uddg 重定向解码 + 站内导航过滤
    ddg = (
        '<div class="result results_links">'
        '<a class="result__a" href="//duckduckgo.com/l/?uddg='
        'https%3A%2F%2Foa.example.org%2Fpapers%2Fdeep.pdf&amp;rut=aa">Deep (PDF)</a></div>'
        '<a class="result__a" href="//duckduckgo.com/l/?uddg='
        'https%3A%2F%2Fwww.researchgate.net%2Fpublication%2F123_Deep&amp;rut=bb">RG</a>'
        '<a class="result__a" href="//duckduckgo.com/l/?uddg='
        'https%3A%2F%2Fnews.example.com%2Fblog&amp;rut=cc">Blog</a>'
        '<a href="https://duckduckgo.com/settings">settings</a>'
    )
    urls = extract_result_urls(ddg)
    assert urls == ["https://oa.example.org/papers/deep.pdf",
                    "https://www.researchgate.net/publication/123_Deep",
                    "https://news.example.com/blog"], urls          # 站内 settings 已滤除
    cands = parse_serp_for_pdfs(ddg)
    assert cands == ["https://oa.example.org/papers/deep.pdf",
                     "https://www.researchgate.net/publication/123_Deep"], cands  # blog 非全文→丢弃
    assert cands[0].endswith(".pdf"), "PDF 直链应排在已知全文域名之前"

    # ③ Bing:b_algo 直链 + 站内导航过滤 + 机构库路径识别
    bing = (
        '<li class="b_algo"><h2><a href="https://lib.univ.edu/bitstream/handle/1/p.pdf">'
        'Full text</a></h2></li>'
        '<li class="b_algo"><h2><a href="https://arxiv.org/abs/1512.03385">arXiv</a></h2></li>'
        '<li class="b_algo"><h2><a href="https://shop.example.com/buy">Buy</a></h2></li>'
        '<a href="https://www.bing.com/account">account</a>'
    )
    b_urls = extract_result_urls(bing)
    assert "https://lib.univ.edu/bitstream/handle/1/p.pdf" in b_urls
    assert "https://arxiv.org/abs/1512.03385" in b_urls
    assert "https://shop.example.com/buy" in b_urls           # extract 不判 PDF,只去站内
    assert all("bing.com" not in u for u in b_urls), b_urls
    b_cands = parse_serp_for_pdfs(bing)
    assert "https://lib.univ.edu/bitstream/handle/1/p.pdf" in b_cands  # .pdf + .edu
    assert "https://arxiv.org/abs/1512.03385" in b_cands              # 已知全文域名
    assert "https://shop.example.com/buy" not in b_cands, "购买页应丢弃"
    assert b_cands[0].endswith(".pdf"), b_cands

    # ③b Bing /ck/a?u=a1<base64> 重定向解码:实网 Bing 现普遍用此包装真链,补测此前未覆盖的解码路径
    _real_ck = "https://oa.example.org/bing/wrapped.pdf"
    _u_ck = "a1" + base64.urlsafe_b64encode(_real_ck.encode()).decode().rstrip("=")
    _ck = "https://www.bing.com/ck/a?u=" + _u_ck
    assert _decode_bing_ck(_ck) == _real_ck, _decode_bing_ck(_ck)
    assert _real_ck in extract_result_urls('<a href="%s">wrapped</a>' % _ck), _ck
    # 非 ck/a 链接原样透传;base64 损坏时不抛、原样返回
    assert _decode_bing_ck("https://x.org/a.pdf") == "https://x.org/a.pdf"
    assert _decode_bing_ck("https://www.bing.com/ck/a?u=a1@@bad") == \
        "https://www.bing.com/ck/a?u=a1@@bad"

    # ④ 过滤/去重/排序:.pdf(80) 优先于全文域名(55),非全文丢弃,去重
    mixed = ["https://x.org/a.pdf", "https://researchgate.net/publication/1",
             "https://x.org/a.pdf", "https://random.com/page", "https://arxiv.org/pdf/2101.1"]
    ranked = filter_pdf_candidates(mixed)
    assert ranked == ["https://x.org/a.pdf", "https://arxiv.org/pdf/2101.1",
                      "https://researchgate.net/publication/1"], ranked
    assert "https://random.com/page" not in ranked

    # ⑤ 端到端(注入 fake fetch,不联网):按 URL 分流 DDG/Bing 固定 HTML → 聚合候选
    def _fake_fetch(url: str, _cfg: Any):
        return ddg if "duckduckgo" in url else bing

    res = search_pdf_candidates("Deep Residual Learning", "10.1109/CVPR.2016.90",
                                _fetch=_fake_fetch)
    assert "https://oa.example.org/papers/deep.pdf" in res
    assert "https://lib.univ.edu/bitstream/handle/1/p.pdf" in res
    assert "https://arxiv.org/abs/1512.03385" in res
    assert res and res[0].endswith(".pdf"), res                # PDF 直链居首
    assert "https://news.example.com/blog" not in res and "https://shop.example.com/buy" not in res

    # ⑥ 优雅降级:取不到页 → [];无输入 → []
    assert search_pdf_candidates("t", "d", _fetch=lambda u, c: None) == []
    assert search_pdf_candidates(None, None) == []

    # ⑦ 下载前预过滤:黑名单 / 未来年份 / 嵌入DOI不符 / 跨出版商降权 / 不误杀 / 开关回退
    # ⑦a 垃圾域黑名单(frontiersin 通配假阳,含 public-pages-files-* 子域)→ 丢;合法 .pdf 留
    assert prefilter_candidates(
        ["https://public-pages-files-prod.frontiersin.org/x.pdf",
         "https://oa.example.org/right.pdf"],
        "10.1016/j.apsusc.2022.154379") == ["https://oa.example.org/right.pdf"]

    # ⑦a2 黑名单域但 URL 含目标 DOI → 保留(避免误杀 Frontiers 正规 OA 目标文章页)
    assert prefilter_candidates(
        ["https://www.frontiersin.org/articles/10.3389/fchem.2020.00001/pdf"],
        "10.3389/fchem.2020.00001") == \
        ["https://www.frontiersin.org/articles/10.3389/fchem.2020.00001/pdf"]

    # ⑦b 未来年份(title-only 亦拦):内嵌 2099 年 DOI → 丢
    assert prefilter_candidates(
        ["https://x.org/10.1038/s41598-099-12345-6.pdf", "https://x.org/plain.pdf"],
        None, current_year=2026) == ["https://x.org/plain.pdf"]
    # 候选年(2026) > 目标年(2016) 即使非未来也丢
    assert prefilter_candidates(
        ["https://x.org/10.1038/s41598-026-9.pdf", "https://x.org/ok.pdf"],
        "10.1038/s41598-016-0001-2", current_year=2030) == ["https://x.org/ok.pdf"]

    # ⑦c 嵌入 DOI≠目标 且 目标不在 URL → 丢(与年份无关,用旧年份隔离③);目标 DOI 在 URL/仓储域 → 留
    _tgt = "10.1016/j.apsusc.2022.154379"
    assert prefilter_candidates(
        ["https://pub.example.org/doi/10.9999/wrong.2001.1/full.pdf",
         "https://repo.edu/bitstream/%s/ms.pdf" % _tgt],
        _tgt) == ["https://repo.edu/bitstream/%s/ms.pdf" % _tgt]

    # ⑦d 跨出版商 host 不符 → 降权到末尾(仓储不动);该候选无内嵌 DOI,不触发③
    assert prefilter_candidates(
        ["https://pubs.acs.org/pb-assets/render/paper.pdf",
         "https://www.researchgate.net/publication/1_ok/download"],
        "10.1016/j.jcou.2019.11.025") == [
        "https://www.researchgate.net/publication/1_ok/download",
        "https://pubs.acs.org/pb-assets/render/paper.pdf"]

    # ⑦e 不误杀:正确 DOI / 仓储 / arXiv / edu / 纯 .pdf 全保留、顺序不变
    _good = ["https://oa.example.org/a.pdf",
             "https://repo.edu/bitstream/10.1016/j.apsusc.2022.154379/x.pdf",
             "https://arxiv.org/pdf/1512.03385",
             "https://www.researchgate.net/publication/9_z"]
    assert prefilter_candidates(_good, "10.1016/j.apsusc.2022.154379") == _good, "合法候选不应被误杀"

    # ⑦f 开关可回退:enable=False / cfg.websearch_prefilter=False → 原样返回(含黑名单域)
    _raw = ["https://frontiersin.org/x.pdf", "https://ok.org/y.pdf"]
    assert prefilter_candidates(_raw, "10.1/x", enable=False) == _raw

    class _CfgOff:
        websearch_prefilter = False
    assert prefilter_candidates(_raw, "10.1/x", cfg=_CfgOff()) == _raw

    # ⑦g 端到端:注入含黑名单/未来错DOI的 SERP,search 结果只剩正确候选
    def _fake_bad(url: str, _cfg: Any):
        return ('<a href="https://frontiersin.org/wild.pdf">wild</a>'
                '<a href="https://x.org/10.9999/wrong.2099.1/p.pdf">future-wrong</a>'
                '<a href="https://oa.example.org/correct.pdf">correct</a>')
    assert search_pdf_candidates("Some Title", "10.1016/j.jcou.2019.11.025",
                                 _fetch=_fake_bad) == ["https://oa.example.org/correct.pdf"]

    print("WEBSEARCH_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
