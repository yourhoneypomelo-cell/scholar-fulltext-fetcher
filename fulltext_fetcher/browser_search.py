"""无头隐身浏览器驱动搜索引擎找 PDF 候选(纯 HTTP 被拦时的兜底路径)。

场景:出版商/学术站点对数据中心 IP 直接 403 或弹人机验证时,用**隐身无头浏览器**渲染通用搜索
引擎(Bing / DuckDuckGo / Google)的结果页,尽量绕过/通过验证,从渲染后的 DOM 抽取
**PDF / 自存稿候选 URL**(本地 IP、无代理、免费)。本模块**只产候选 URL**,不下载(下载交
下游 download 复用父包)。

设计要点:
- **隐身取页(加固)**:内置直连驱动 nodriver / patchright(隐身参数:UA、语言、视口、
  ``--disable-blink-features=AutomationControlled``、渲染等待 + 滚动触发懒加载),优先 nodriver
  (已实网验证可过 Bing/DDG 软验证),失败回退 patchright;二者都不行时再回退复用
  ``fulltext_fetcher.scholar.fetcher`` 的引擎(不修改它)。取页函数可注入(``fetch``),便于测试。
- **浏览器依赖延迟导入**:所有反爬/浏览器库均函数级延迟导入;缺失即优雅返回空 + 记原因(不崩)。
  **离线 selftest 用 mock 取页函数,绝不启动真实浏览器。**
- **纯解析**:parse_pdf_candidates 仅标准库(html.parser + urllib),解各引擎重定向包装
  (Google ``/url?q=``、DuckDuckGo ``/l/?uddg=``、Bing ``/ck/a?...&u=a1<b64>``),识别 .pdf 直链
  **以及**已知自存稿/机构库域名与仓储路径(arXiv/ResearchGate/机构库等),复用父包
  ``landing.extract_pdf_links`` 合并直链;绝不抛异常。
- **多检索式 + 引擎兜底**:对同一输入尝试多种检索式(filetype:pdf、裸标题/DOI、site:researchgate),
  Bing 为主(见下),命中即止;主引擎被拦/空 → 回退下一引擎。**检测到验证码/风控页优雅跳过**。

⚠️ 合规:自动化驱动搜索引擎、绕过其人机验证多违反其 ToS,处灰色地带,仅供研究/小规模自用;
默认无代理、本地 IP、低频。使用者自负合规与法律责任(注意 nodriver=AGPL 等许可证传染)。

协同:与纯 HTTP 版 sources/websearch.py 分工——本模块(浏览器)主攻 Bing(冷门论文 Bing 召回优、
浏览器过 Bing 软验证),websearch(HTTP)主攻 DuckDuckGo;彼此保留另一引擎作兜底、错峰,避免
同一公网 IP 高频并发互相限速。

可选新增 config 字段(默认已用 getattr 兜底,不存在则用内置默认;建议由总指挥统一加入 ScholarConfig):
    user_agent: str            (已存在)降级/浏览器 UA
    browser_headless: bool = True        无头开关
    browser_render_wait: float = 3.0     渲染等待秒数(等 JS/结果加载)
    browser_max_queries: int = 2         每次每引擎尝试的检索式上限

对外接口(供下游/总指挥集成):
    build_search_query(raw, *, pdf_only=True) -> str
    build_search_queries(raw, *, pdf_only=True, max_queries=3) -> List[str]
    search_engine_url(engine, query) -> str
    parse_pdf_candidates(html, *, base_url="", engine="", include_fulltext=True) -> List[str]
    browser_search_pdfs(raw, *, cfg=None, ctx=None, search_engines=(...), fetch=None,
                        max_candidates=20, pdf_only=True, queries=None, max_queries=2,
                        include_fulltext=True, log=None) -> Dict[str, Any]

离线自检:python -m fulltext_fetcher.browser_search  → 打印 BROWSER_SEARCH_OK
"""
from __future__ import annotations

import base64
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

from .resolve import classify_input

# 搜索引擎结果页 URL 前缀(用可渲染 HTML 的端点:DuckDuckGo 用 html 版)。
_SEARCH_ENGINES: Dict[str, str] = {
    "bing": "https://www.bing.com/search?q=",
    "duckduckgo": "https://duckduckgo.com/html/?q=",
    "google": "https://www.google.com/search?q=",
}

# 默认引擎顺序(与 websearch 分工,实网校准 2026-07 收敛):本模块(无头浏览器)主攻 **Bing**
# ——冷门论文(如 batch6 催化类 DOI)Bing 召回明显优于 DDG,且浏览器可过 Bing 的 JS/软验证;
# websearch(纯 HTTP)主攻 **DuckDuckGo**。DDG 作本模块兜底(命中即止,故仅 Bing 空/被拦时才打
# DDG,低频错峰),避免同一公网 IP 两路高频并发互相限速。
_DEFAULT_ENGINES = ("bing", "duckduckgo")

# 浏览器降级取回用 UA(与 scholar.fetcher / config 默认一致)。
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 已知"全文/自存稿/预印本/机构库"域名(命中即视为可下载候选,即使 URL 不以 .pdf 结尾)。
_FULLTEXT_HOSTS = (
    "researchgate.net", "arxiv.org", "biorxiv.org", "medrxiv.org", "chemrxiv.org",
    "europepmc.org", "ncbi.nlm.nih.gov", "semanticscholar.org", "core.ac.uk",
    "ssrn.com", "academia.edu", "hal.science", "hal.archives-ouvertes.fr",
    "zenodo.org", "osf.io", "preprints.org", "researchsquare.com", "figshare.com",
    "papers.nips.cc", "proceedings.neurips.cc", "proceedings.mlr.press",
    "openreview.net", "aclanthology.org",
)
# 机构库/仓储常见路径特征(DSpace/EPrints/Invenio 等)。
_REPO_PATH_HINTS = ("/bitstream/", "/handle/", "/download/", "/viewcontent",
                    "/fulltext", "/record/", "/repository/")

# 搜索引擎自身/导航域名:其结果页里的这些链接是站内导航,非检索结果,过滤掉。
_ENGINE_HOSTS = (
    "bing.com", "duckduckgo.com", "google.com", "microsoft.com", "msn.com",
    "microsofttranslator.com", "go.microsoft.com", "support.microsoft.com",
    "gstatic.com", "googleusercontent.com",
)

# 验证码 / 风控 / 反爬拦截页标志(全小写匹配)。命中任一即判为被拦。
_BLOCK_MARKERS = (
    "unusual traffic", "detected unusual", "not a robot", "are you a robot",
    "verify you are human", "verify you're human", "/sorry/", "g-recaptcha",
    "recaptcha", "hcaptcha", "cf-challenge", "captcha-delivery",
    "please enable javascript and cookies", "access denied",
    "sending automated queries",
)


# ─────────────────────────── 查询构造 ───────────────────────────
def build_search_query(raw: str, *, pdf_only: bool = True) -> str:
    """由 title/DOI 原始输入构造(单条)搜索式。

    DOI → 带引号精确;标题含空格 → 带引号短语,否则原样。pdf_only 时附加 ``filetype:pdf``。
    """
    wi = classify_input(raw)
    core = (getattr(wi, "value", None) or raw or "").strip()
    if not core:
        core = (raw or "").strip()
    if getattr(wi, "kind", None) == "doi":
        base = f'"{core}"'
    else:
        base = f'"{core}"' if " " in core else core
    return f"{base} filetype:pdf" if pdf_only else base


def build_search_queries(raw: str, *, pdf_only: bool = True, max_queries: int = 3) -> List[str]:
    """由 title/DOI 构造**多条**检索式(提高召回:精确 PDF、裸检索、自存稿定向)。

    - DOI:``"DOI" filetype:pdf`` → ``"DOI"``(裸 DOI 常直出机构库/预印本)→ ``DOI pdf``;
    - 标题:``"T" filetype:pdf`` → ``"T"`` → ``"T" site:researchgate.net``。
    去重保序,截断到 max_queries。空输入 → []。
    """
    wi = classify_input(raw)
    core = (getattr(wi, "value", None) or raw or "").strip() or (raw or "").strip()
    if not core:
        return []
    kind = getattr(wi, "kind", None)
    qs: List[str] = []
    if kind == "doi":
        qs.append(f'"{core}" filetype:pdf' if pdf_only else f'"{core}"')
        qs.append(f'"{core}"')
        qs.append(f"{core} pdf")
    else:
        phrase = f'"{core}"' if " " in core else core
        if pdf_only:
            qs.append(f"{phrase} filetype:pdf")
        qs.append(phrase)
        qs.append(f"{phrase} site:researchgate.net")
    seen: set = set()
    out: List[str] = []
    for q in qs:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[: max(1, max_queries)]


def search_engine_url(engine: str, query: str) -> str:
    """拼某搜索引擎的结果页 URL(query 做 URL 编码)。未知引擎 → ValueError。"""
    base = _SEARCH_ENGINES.get((engine or "").lower())
    if not base:
        raise ValueError(f"unknown search engine: {engine!r} (支持: {', '.join(_SEARCH_ENGINES)})")
    return base + quote_plus(query)


# ─────────────────────────── 结果页解析 ───────────────────────────
class _AHrefParser(HTMLParser):
    """流式抽取所有 <a href> 值(convert_charrefs 自动解实体)。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: List[str] = []

    def handle_starttag(self, tag: str, attrs: List) -> None:
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.hrefs.append(v)


def _extract_hrefs(html: str) -> List[str]:
    p = _AHrefParser()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001 - 畸形 HTML 不得抛给调用方
        pass
    return p.hrefs


def _qs_get(url: str, name: str) -> Optional[str]:
    """从 URL 查询串取某参数(自动 urldecode);协议相对 // 前补 https。失败 None。"""
    try:
        u = "https:" + url if url.startswith("//") else url
        vals = parse_qs(urlparse(u).query).get(name)
        return vals[0] if vals else None
    except Exception:  # noqa: BLE001
        return None


def _b64url(s: str) -> Optional[str]:
    """urlsafe base64 解码(自动补 padding);失败 None。"""
    try:
        pad = "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s + pad).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None


def _unwrap_redirect(href: str) -> Optional[str]:
    """把搜索引擎的重定向包装解成真实目标 URL;非包装则原样返回。"""
    h = unescape((href or "").strip())
    if not h:
        return None
    low = h.lower()
    if "/url?" in low and "q=" in low:               # Google: /url?q=<URL>&...
        v = _qs_get(h, "q")
        if v:
            return v
    if "uddg=" in low:                               # DuckDuckGo: /l/?uddg=<urlenc>
        v = _qs_get(h, "uddg")
        if v:
            return v
    if "bing.com/ck/a" in low or "&u=a1" in low or "?u=a1" in low:  # Bing: u=a1<b64url>
        v = _qs_get(h, "u")
        if v and v.startswith("a1"):
            dec = _b64url(v[2:])
            if dec:
                return dec
    return h


def _looks_like_pdf_url(url: str) -> bool:
    low = (url or "").lower()
    path = low.split("#", 1)[0].split("?", 1)[0]
    return path.endswith(".pdf") or ".pdf?" in low or "/pdf/" in path


def _host(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def _is_engine_host(host: str) -> bool:
    host = (host or "").lower()
    return any(host == h or host.endswith("." + h) for h in _ENGINE_HOSTS)


def _is_fulltext_candidate(url: str) -> bool:
    """URL 是否指向已知自存稿/预印本/机构库(即使非 .pdf 结尾也视为可下载候选)。"""
    host = _host(url)
    if not host or _is_engine_host(host):
        return False
    try:
        path = (urlparse(url).path or "").lower()
    except Exception:  # noqa: BLE001
        return False
    if host.endswith(".edu"):
        return True
    if any(host == h or host.endswith("." + h) for h in _FULLTEXT_HOSTS):
        return True
    return any(hint in path for hint in _REPO_PATH_HINTS)


def _absolutize(target: str, base_url: str) -> str:
    if target.startswith("//"):
        return "https:" + target
    if base_url and target.startswith("/"):
        try:
            return urljoin(base_url, target)
        except Exception:  # noqa: BLE001
            return target
    return target


def parse_pdf_candidates(html: str, *, base_url: str = "", engine: str = "",
                         include_fulltext: bool = True) -> List[str]:
    """从渲染后的搜索结果 HTML 抽 PDF / 自存稿候选 URL(解包重定向 + 复用父包 landing 直链)。

    - 解各引擎重定向包装 → 绝对化 → 仅保留 http(s);
    - 命中 **.pdf 直链** 或(include_fulltext 时)**已知自存稿/机构库域名/仓储路径** → 收为候选;
    - 再复用 ``fulltext_fetcher.landing.extract_pdf_links`` 合并页面直链(仅 .pdf);
    - 去重保序;None/空/畸形 → 返回 [],绝不抛。engine 仅用于可读性,不改变逻辑。
    """
    if not isinstance(html, str) or not html:
        return []
    out: List[str] = []
    for href in _extract_hrefs(html):
        target = _unwrap_redirect(href)
        if not target:
            continue
        target = _absolutize(target, base_url)
        if not target.lower().startswith(("http://", "https://")):
            continue
        if _looks_like_pdf_url(target) or (include_fulltext and _is_fulltext_candidate(target)):
            if target not in out:
                out.append(target)
    try:  # 复用父包直链抽取器(只增不重复;仅 .pdf 直链)
        from .landing import extract_pdf_links
        for u in extract_pdf_links(html, base_url or "https://example.org"):
            if u and _looks_like_pdf_url(u) and u not in out:
                out.append(u)
    except Exception:  # noqa: BLE001 - landing 抽取失败不影响主解析
        pass
    return out


def _looks_blocked(html: Any) -> bool:
    """渲染结果是否为验证码 / 风控 / 反爬拦截页(供引擎回退 + reason 判定)。None/空 → False。"""
    if not isinstance(html, str) or not html:
        return False
    low = html.lower()
    return any(m in low for m in _BLOCK_MARKERS)


# ─────────────────────────── 隐身浏览器取页(加固:直连驱动 nodriver/patchright)───────────────────────────
def _warn(log: Any, msg: str) -> None:
    if log is not None:
        try:
            log.warning(msg)
        except Exception:  # noqa: BLE001
            pass


def _cfg_get(cfg: Any, attr: str, default: Any) -> Any:
    return getattr(cfg, attr, default) if cfg is not None else default


def _stealth_args(ua: Optional[str]) -> List[str]:
    """Chromium 隐身/稳健命令行(nodriver browser_args)。"""
    args = [
        "--lang=en-US",
        "--disable-blink-features=AutomationControlled",
        "--window-size=1920,1080",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate",
    ]
    if ua:
        args.append(f"--user-agent={ua}")
    return args


def _fetch_via_nodriver(url: str, *, ua: Optional[str] = None, headless: bool = True,
                        render_wait: float = 3.0, timeout: float = 30.0,
                        log: Any = None) -> Optional[str]:
    """nodriver 直连隐身取页(渲染 + 滚动触发懒加载)。缺库/失败 → None(不崩)。"""
    try:
        import asyncio

        import nodriver as nd  # 延迟导入(可选依赖)
    except Exception as e:  # noqa: BLE001
        _warn(log, f"browser_search: nodriver 不可用: {e}")
        return None

    async def _go() -> Optional[str]:
        browser = await nd.start(headless=headless, browser_args=_stealth_args(ua))
        try:
            page = await browser.get(url)
            await page.sleep(max(render_wait, 0.1))
            try:                                   # 滚动触发懒加载结果
                await page.scroll_down(600)
                await page.sleep(0.8)
            except Exception:  # noqa: BLE001
                pass
            try:
                return await page.get_content()
            except Exception:  # noqa: BLE001
                return None
        finally:
            try:
                browser.stop()
            except Exception:  # noqa: BLE001
                pass

    try:
        return asyncio.run(_go())
    except Exception as e:  # noqa: BLE001
        _warn(log, f"browser_search: nodriver 取页异常: {e}")
        return None


def _fetch_via_patchright(url: str, *, ua: Optional[str] = None, headless: bool = True,
                          render_wait: float = 3.0, timeout: float = 30.0,
                          log: Any = None) -> Optional[str]:
    """patchright(隐身 Playwright)直连取页:自定义 UA/locale/viewport + 渲染等待 + 滚动。"""
    try:
        from patchright.sync_api import sync_playwright  # 延迟导入(可选依赖)
    except Exception as e:  # noqa: BLE001
        _warn(log, f"browser_search: patchright 不可用: {e}")
        return None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless, channel="chrome")
            try:
                context = browser.new_context(
                    user_agent=ua or _UA, locale="en-US",
                    viewport={"width": 1920, "height": 1080},
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                )
                page = context.new_page()
                page.goto(url, timeout=int(max(timeout, 1) * 1000), wait_until="domcontentloaded")
                page.wait_for_timeout(int(max(render_wait, 0.1) * 1000))
                try:
                    page.mouse.wheel(0, 3000)
                    page.wait_for_timeout(600)
                except Exception:  # noqa: BLE001
                    pass
                return page.content()
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001
        _warn(log, f"browser_search: patchright 取页异常: {e}")
        return None


def _fetch_via_scholar_fetcher(url: str, cfg: Any = None, ctx: Any = None,
                               log: Any = None) -> Optional[str]:
    """最后兜底:复用 scholar.fetcher 的隐身引擎(不修改它)。缺失/失败 → None。"""
    try:
        from .scholar.fetcher import FetchContext, NodriverEngine, PatchrightEngine
    except Exception as e:  # noqa: BLE001
        _warn(log, f"browser_search: scholar.fetcher 不可用: {e}")
        return None
    context = ctx
    if context is None:
        try:
            from .scholar.config import ScholarConfig
            context = FetchContext(cfg=cfg or ScholarConfig())
        except Exception:  # noqa: BLE001
            context = FetchContext(cfg=cfg)
    for engine_cls in (PatchrightEngine, NodriverEngine):
        try:
            eng = engine_cls()
            if not eng.available():
                continue
            out = eng.get(url, context)
            if out is not None and getattr(out, "ok", False) and getattr(out, "html", None):
                return out.html
        except Exception as e:  # noqa: BLE001
            _warn(log, f"browser_search: 引擎 {getattr(engine_cls, 'name', engine_cls)} 取页异常: {e}")
            continue
    return None


def _browser_fetch_html(url: str, cfg: Any = None, ctx: Any = None, log: Any = None) -> Optional[str]:
    """隐身取页编排:加固直连(nodriver→patchright)→ 兜底 scholar.fetcher。全程优雅降级。"""
    ua = _cfg_get(cfg, "user_agent", None) or _UA
    headless = bool(_cfg_get(cfg, "browser_headless", True))
    render_wait = float(_cfg_get(cfg, "browser_render_wait", 3.0) or 0.0)
    timeout = float(_cfg_get(cfg, "timeout", 30.0) or 30.0)
    for drv in (_fetch_via_nodriver, _fetch_via_patchright):
        html = drv(url, ua=ua, headless=headless, render_wait=render_wait, timeout=timeout, log=log)
        if html:
            return html
    return _fetch_via_scholar_fetcher(url, cfg=cfg, ctx=ctx, log=log)


# ─────────────────────────── 对外主入口 ───────────────────────────
def browser_search_pdfs(raw: str, *, cfg: Any = None, ctx: Any = None,
                        search_engines=_DEFAULT_ENGINES,
                        fetch: Optional[Callable[[str], Optional[str]]] = None,
                        max_candidates: int = 20, pdf_only: bool = True,
                        queries: Optional[List[str]] = None, max_queries: int = 2,
                        include_fulltext: bool = True,
                        log: Any = None) -> Dict[str, Any]:
    """用无头隐身浏览器渲染搜索引擎结果页,聚合 PDF / 自存稿候选 URL。

    参数:
      - raw: 标题 / DOI。
      - fetch: 可注入取页函数 ``fetch(url) -> Optional[str]``(返回渲染后 HTML);缺省用隐身编排
        (nodriver→patchright→scholar.fetcher)。**selftest 传 mock,绝不启真浏览器。**
      - search_engines: 依次尝试的引擎(默认 bing, duckduckgo);命中即止,其余作兜底。
      - queries: 直接指定检索式列表;None → 由 build_search_queries 生成(取前 max_queries 条)。
    返回信封:``{available, candidates, by_engine, engine_used, query, queries,
                blocked_engines, reason}``。
      - available: 是否取到 >=1 候选;
      - reason: available=False 时说明("browser-unavailable" / "search-engine-blocked" /
        "no-pdf-candidates" / "bad-input")。
    """
    primary_query = build_search_query(raw, pdf_only=pdf_only)
    q_list = list(queries) if queries is not None else \
        build_search_queries(raw, pdf_only=pdf_only, max_queries=max_queries)
    if not q_list:
        q_list = [primary_query] if primary_query else []

    if not q_list:
        return {"available": False, "candidates": [], "by_engine": {}, "engine_used": None,
                "query": primary_query, "queries": [], "blocked_engines": [], "reason": "bad-input"}

    fetch_fn = fetch or (lambda u: _browser_fetch_html(u, cfg=cfg, ctx=ctx, log=log))
    candidates: List[str] = []
    by_engine: Dict[str, int] = {}
    blocked_engines: List[str] = []
    engine_used: Optional[str] = None
    any_html = False
    any_blocked = False

    for eng in search_engines:
        eng_added = 0
        for q in q_list:
            try:
                url = search_engine_url(eng, q)
            except ValueError as e:
                _warn(log, f"browser_search: {e}")
                continue
            try:
                html = fetch_fn(url)
            except Exception as e:  # noqa: BLE001 - 取页异常 → 视为该式未取到
                _warn(log, f"browser_search: 取页失败 {eng}: {e}")
                html = None
            if not html:
                continue
            any_html = True
            if _looks_blocked(html):
                any_blocked = True
                if eng not in blocked_engines:
                    blocked_engines.append(eng)
                continue
            for c in parse_pdf_candidates(html, base_url=url, engine=eng,
                                          include_fulltext=include_fulltext):
                if c not in candidates:
                    candidates.append(c)
                    eng_added += 1
            if len(candidates) >= max_candidates:
                break
        by_engine[eng] = eng_added
        if eng_added and engine_used is None:
            engine_used = eng
        if len(candidates) >= max_candidates:
            break
        if candidates:                 # 主引擎已出候选 → 其余引擎作兜底,不再打(省请求、避免同 IP 限速)
            break

    candidates = candidates[:max_candidates]
    if candidates:
        return {"available": True, "candidates": candidates, "by_engine": by_engine,
                "engine_used": engine_used, "query": primary_query, "queries": q_list,
                "blocked_engines": blocked_engines, "reason": None}
    if not any_html:
        reason = "browser-unavailable"
    elif any_blocked:
        reason = "search-engine-blocked"
    else:
        reason = "no-pdf-candidates"
    _warn(log, f"browser_search: 未获候选({reason}) · q={primary_query!r}")
    return {"available": False, "candidates": [], "by_engine": by_engine,
            "engine_used": None, "query": primary_query, "queries": q_list,
            "blocked_engines": blocked_engines, "reason": reason}


# ─────────────────────────── 不联网 selftest(mock 取页,不启真浏览器)───────────────────────────
def _selftest() -> int:
    # ① build_search_query:标题带引号 + filetype:pdf;DOI 精确
    qt = build_search_query("Attention is all you need")
    assert qt == '"Attention is all you need" filetype:pdf', qt
    assert build_search_query("10.1038/nature12373").startswith('"10.1038/nature12373"')
    assert build_search_query("Attention is all you need", pdf_only=False) == '"Attention is all you need"'

    # ①b build_search_queries:多检索式(标题/DOI),去重保序 + 截断
    tq = build_search_queries("Deep Residual Learning")
    assert tq[0] == '"Deep Residual Learning" filetype:pdf', tq
    assert '"Deep Residual Learning"' in tq and any("researchgate" in q for q in tq), tq
    dq = build_search_queries("10.1039/c3ee44078h")
    assert dq[0].startswith('"10.1039/c3ee44078h"') and any("filetype:pdf" in q for q in dq), dq
    assert '"10.1039/c3ee44078h"' in dq, dq
    assert build_search_queries("") == [], "空输入应无 query"
    assert len(build_search_queries("Deep Residual Learning", max_queries=2)) == 2

    # ② search_engine_url:三引擎 + 编码;未知引擎抛错
    ub = search_engine_url("bing", "x filetype:pdf")
    assert ub.startswith("https://www.bing.com/search?q=") and "filetype%3Apdf" in ub, ub
    assert search_engine_url("duckduckgo", "y").startswith("https://duckduckgo.com/html/?q=")
    assert search_engine_url("google", "z").startswith("https://www.google.com/search?q=")
    for _bad in ("yahoo", "", None):
        try:
            search_engine_url(_bad, "q")  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for engine {_bad!r}")

    # ③ parse_pdf_candidates:直链 + Google/DDG/Bing 重定向解包 + 非 PDF 排除 + 去重保序
    _bing_u = "a1" + base64.urlsafe_b64encode(b"https://ex.org/bing.pdf").decode().rstrip("=")
    html = (
        '<a href="https://ex.org/a.pdf">direct</a>'
        '<a href="/url?q=https://ex.org/b.pdf&amp;sa=U">google-wrap</a>'
        '<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fex.org%2Fc.pdf&amp;rut=x">ddg-wrap</a>'
        f'<a href="https://www.bing.com/ck/a?ver=2&amp;u={_bing_u}">bing-wrap</a>'
        '<a href="https://ex.org/landing.html">not-pdf</a>'
        '<a href="/relative/d.pdf">relative</a>'
        '<a href="https://ex.org/a.pdf">dup</a>'
    )
    cands = parse_pdf_candidates(html, base_url="https://www.google.com/search?q=x")
    assert "https://ex.org/a.pdf" in cands, cands
    assert "https://ex.org/b.pdf" in cands, cands            # Google /url?q= 解包
    assert "https://ex.org/c.pdf" in cands, cands            # DDG uddg= 解包
    assert "https://ex.org/bing.pdf" in cands, cands         # Bing u=a1<b64> 解包
    assert "https://www.google.com/relative/d.pdf" in cands, cands  # 相对 → 绝对
    assert "https://ex.org/landing.html" not in cands, cands  # 非 PDF、非自存稿 → 排除
    assert cands.count("https://ex.org/a.pdf") == 1, cands    # 去重
    assert parse_pdf_candidates("", base_url="x") == [] and parse_pdf_candidates(None) == []  # type: ignore[arg-type]

    # ③b 自存稿/机构库识别:arXiv /abs、ResearchGate、机构库 /handle 路径、.edu → 收;普通博客 → 弃
    ft_html = (
        '<a href="https://arxiv.org/abs/1706.03762">arxiv-abs</a>'
        '<a href="https://www.researchgate.net/publication/1_X">rg</a>'
        '<a href="https://lib.univ.edu/handle/123/4">repo-handle</a>'
        '<a href="https://news.example.com/blog">blog</a>'
        '<a href="https://www.bing.com/aclick?u=x">engine-nav</a>'
    )
    ft = parse_pdf_candidates(ft_html, base_url="https://www.bing.com/search?q=x")
    assert "https://arxiv.org/abs/1706.03762" in ft, ft
    assert "https://www.researchgate.net/publication/1_X" in ft, ft
    assert "https://lib.univ.edu/handle/123/4" in ft, ft
    assert "https://news.example.com/blog" not in ft, ft       # 非全文域名 → 弃
    assert not any("bing.com" in u for u in ft), ft            # 引擎导航 → 弃
    # include_fulltext=False → 仅 .pdf 直链,arXiv abs(非 .pdf)被排除
    ft2 = parse_pdf_candidates(ft_html, base_url="x", include_fulltext=False)
    assert "https://arxiv.org/abs/1706.03762" not in ft2, ft2

    # ③c 拦截页识别
    assert _looks_blocked("<html>Please verify you are human. g-recaptcha</html>") is True
    assert _looks_blocked("<html>Our systems have detected unusual traffic</html>") is True
    assert _looks_blocked("<a href='https://x/p.pdf'>ok</a>") is False
    assert _looks_blocked("") is False and _looks_blocked(None) is False  # type: ignore[arg-type]

    # ④ browser_search_pdfs:注入 mock 取页(不启真浏览器)→ 聚合候选
    calls: List[str] = []

    def _mock_fetch(url: str) -> Optional[str]:
        calls.append(url)
        return html

    res = browser_search_pdfs("Attention is all you need", search_engines=("bing",), fetch=_mock_fetch)
    assert res["available"] is True and res["candidates"], res
    assert "https://ex.org/a.pdf" in res["candidates"], res
    assert res["engine_used"] == "bing" and res["by_engine"]["bing"] >= 1, res
    assert calls and calls[0].startswith("https://www.bing.com/search?q="), calls
    assert "filetype" in res["query"], res
    assert isinstance(res["queries"], list) and res["queries"], res

    # 多引擎聚合 + max_candidates 截断
    res_multi = browser_search_pdfs("x", search_engines=("bing", "duckduckgo"),
                                    fetch=_mock_fetch, max_candidates=2)
    assert len(res_multi["candidates"]) == 2, res_multi

    # ④b 自存稿候选(mock 返回 arXiv abs,非 .pdf)→ available
    res_ft = browser_search_pdfs("some paper title", search_engines=("bing",),
                                 fetch=lambda u: ft_html)
    assert res_ft["available"] is True, res_ft
    assert "https://arxiv.org/abs/1706.03762" in res_ft["candidates"], res_ft

    # ④c 引擎兜底:bing 命中拦截页 → 回退 duckduckgo 取到候选
    _BLOCK = "<html><body>Please verify you are human before continuing. g-recaptcha</body></html>"

    def _fetch_engine(url: str) -> Optional[str]:
        return _BLOCK if "bing.com" in url else ft_html

    res_fb = browser_search_pdfs("t", search_engines=("bing", "duckduckgo"), fetch=_fetch_engine)
    assert res_fb["available"] is True and res_fb["engine_used"] == "duckduckgo", res_fb
    assert "bing" in res_fb["blocked_engines"], res_fb

    # ⑤ 浏览器不可用(mock 恒 None)→ 优雅返回空 + reason
    res_none = browser_search_pdfs("x", search_engines=("bing", "duckduckgo"),
                                   fetch=lambda u: None)
    assert res_none["available"] is False and res_none["candidates"] == [], res_none
    assert res_none["reason"] == "browser-unavailable", res_none

    # 取到 HTML 但无候选 → reason=no-pdf-candidates
    res_empty = browser_search_pdfs("x", search_engines=("bing",),
                                    fetch=lambda u: "<a href='https://ex.org/p.html'>x</a>")
    assert res_empty["available"] is False and res_empty["reason"] == "no-pdf-candidates", res_empty

    # 全引擎均被拦 → reason=search-engine-blocked
    res_blk = browser_search_pdfs("x", search_engines=("bing", "duckduckgo"),
                                  fetch=lambda u: _BLOCK)
    assert res_blk["available"] is False and res_blk["reason"] == "search-engine-blocked", res_blk
    assert "bing" in res_blk["blocked_engines"] and "duckduckgo" in res_blk["blocked_engines"], res_blk

    print("BROWSER_SEARCH_OK")
    return 0


if __name__ == "__main__":  # 离线 selftest: python -m fulltext_fetcher.browser_search
    raise SystemExit(_selftest())
