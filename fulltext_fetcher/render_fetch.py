"""无头浏览器渲染兜底:仅对少量 OA 落地页,渲染后取最终 PDF 直链(可选、默认关闭)。

路线图 A4「安全 OA 线」:对极少数 `landing.py` 纯 HTML 解析仍拿不到 PDF 的**开放获取
(OA)出版商落地页**(内容由 JS 动态注入),用无头浏览器把页面渲染出来,再复用
`landing.extract_pdf_links` 从渲染后的 DOM 抠出最终 PDF 直链(citation_pdf_url /
a[href$=.pdf] / embed / 出版商模板 等)。

============================ 合规边界(务必先读)============================
* **仅限 OA 落地页**:本模块只应对【你已通过合规途径获取、且有权访问】的 OA 出版商
  落地页做渲染,用于取其正文 PDF 直链。
* **绝不抓 Google Scholar**:本模块**严禁**用于渲染 / 抓取 Google Scholar 或任何
  搜索结果页。对 `scholar.google.*` 等域名会**直接拒绝**(见 `_is_scholar_host`)。
  谷歌学术检索请走合规商业 API(见 `scholar_serpapi.py`),绝不在此自建反爬 / 过验证码。
* **默认关闭**:渲染引擎(Playwright / nodriver)均为**可选依赖**,未安装时
  `render_get_pdf_url` 优雅返回 `{"available": False, "reason": "need playwright/nodriver"}`,
  不做任何事。因此不主动安装可选依赖,本兜底永不激活。
* **强限流**:无头浏览器开销大且更易触发风控,故默认对每次渲染做进程内强制最小间隔限速。
===========================================================================

依赖
====
* 复用同包 `landing.extract_pdf_links`(纯标准库、零第三方依赖)。
* 渲染引擎 Playwright / nodriver 为**可选**依赖,均为**延迟导入**;二者都未安装也能
  正常 import 本模块、跑离线自检。**绝不**把它们列为强制依赖。

CLI
===
    python -m fulltext_fetcher.render_fetch "https://oa-publisher.example/article/1"
    python -m fulltext_fetcher.render_fetch "<url>" --engine playwright --timeout 40
    python -m fulltext_fetcher.render_fetch --selftest   # 不联网/无浏览器自检,打印 RENDER_OK
"""
from __future__ import annotations

import base64
import json
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:  # 以 `python -m fulltext_fetcher.render_fetch` 运行时相对导入成立
    from .landing import extract_pdf_links
except ImportError:  # 兜底:绝对包路径(极端运行环境)
    from fulltext_fetcher.landing import extract_pdf_links

DEFAULT_TIMEOUT = 30.0
DEFAULT_MIN_INTERVAL = 2.0   # 每次渲染最小间隔秒(强限流:无头浏览器更易触发风控)

# 渲染函数签名:render_fn(url, timeout) -> (html, final_url)
RenderFn = Callable[[str, float], Tuple[Optional[str], Optional[str]]]


# ── 合规守卫:永不渲染 Google Scholar / 搜索结果页 ───────────────────────────
def _is_scholar_host(url: str) -> bool:
    """判断 URL 是否指向 Google Scholar(或 google 的 /scholar 路径),命中即拒绝渲染。"""
    try:
        p = urlparse(url or "")
        host = (p.hostname or "").lower()
        path = (p.path or "").lower()
    except Exception:  # noqa: BLE001 - 畸形 URL 保守视为不可判定
        return False
    if "scholar.google" in host:
        return True
    if ("google." in ("." + host)) and "/scholar" in path:
        return True
    return False


def _looks_like_pdf(url: str) -> bool:
    """最终 URL 本身像 PDF(渲染后可能被重定向到 PDF 直链 / 查看器)。"""
    if not url:
        return False
    path = url.split("#", 1)[0].split("?", 1)[0].lower()
    return path.endswith(".pdf") or "/pdf" in path


# ── 进程内强限流 ─────────────────────────────────────────────────────────────
_throttle_lock = threading.Lock()
_last_call_ts = 0.0


def _throttle(min_interval: float) -> None:
    global _last_call_ts
    if not min_interval or min_interval <= 0:
        return
    with _throttle_lock:
        now = time.monotonic()
        wait = _last_call_ts + min_interval - now
        if wait > 0:
            time.sleep(wait)
        _last_call_ts = time.monotonic()


# ── 可选渲染引擎(全部延迟导入;未安装则工厂返回 None)────────────────────────
def _playwright_render_fn() -> Optional[RenderFn]:
    """返回基于 Playwright(同步 API)的渲染函数;未安装 playwright 则返回 None。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    def _render(url: str, timeout: float) -> Tuple[Optional[str], Optional[str]]:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, timeout=int(max(timeout, 1) * 1000), wait_until="domcontentloaded")
                page.wait_for_timeout(1500)  # 给 JS 注入 PDF 链接一点时间
                return page.content(), page.url
            finally:
                browser.close()

    return _render


def _nodriver_render_fn() -> Optional[RenderFn]:
    """返回基于 nodriver(异步)的渲染函数;未安装 nodriver 则返回 None。"""
    try:
        import nodriver  # noqa: F401
    except ImportError:
        return None
    import asyncio

    def _render(url: str, timeout: float) -> Tuple[Optional[str], Optional[str]]:
        import nodriver as nd

        async def _go() -> Tuple[Optional[str], Optional[str]]:
            browser = await nd.start(headless=True)
            try:
                page = await browser.get(url)
                await page.sleep(1.5)
                html = await page.get_content()
                final_url = url
                try:
                    final_url = await page.evaluate("location.href") or url
                except Exception:  # noqa: BLE001 - 取最终 URL 失败退回原 URL
                    pass
                return html, final_url
            finally:
                try:
                    browser.stop()
                except Exception:  # noqa: BLE001
                    pass

        return asyncio.run(_go())

    return _render


# 工厂表:便于自检时临时替换以确定性地验证"无引擎优雅降级"。
_ENGINE_FACTORIES: Dict[str, Callable[[], Optional[RenderFn]]] = {
    "playwright": _playwright_render_fn,
    "nodriver": _nodriver_render_fn,
}


def _select_engine(engine: str = "auto") -> Optional[RenderFn]:
    """按 engine 选择可用渲染函数;都不可用返回 None。engine: auto|playwright|nodriver。"""
    if engine and engine != "auto":
        order = [engine]
    else:
        order = ["playwright", "nodriver"]
    for name in order:
        factory = _ENGINE_FACTORIES.get(name)
        if not factory:
            continue
        try:
            fn = factory()
        except Exception:  # noqa: BLE001 - 引擎初始化异常不应让整个调用崩
            fn = None
        if fn is not None:
            return fn
    return None


def render_get_pdf_url(
    url: str,
    timeout: float = DEFAULT_TIMEOUT,
    engine: str = "auto",
    *,
    min_interval: float = DEFAULT_MIN_INTERVAL,
    _render_fn: Optional[RenderFn] = None,
) -> Dict[str, Any]:
    """渲染一个【OA 落地页】并返回其中的 PDF 直链(可选、默认关闭、强限流)。

    返回统一信封 dict:

    - 无可用引擎(默认关闭)::

        {"available": False, "reason": "need playwright/nodriver", "pdf_url": None, "pdf_links": []}

    - 被合规守卫拒绝(Scholar / 搜索页)::

        {"available": True, "error": "refused: ...", "pdf_url": None, "pdf_links": []}

    - 成功::

        {"available": True, "url": ..., "final_url": ..., "pdf_url": <首选或None>, "pdf_links": [...]}

    - 渲染 / 提取出错::

        {"available": True, "error": "...", "pdf_url": None, "pdf_links": []}

    :param url: OA 出版商落地页 URL(仅限已合法获取、有权访问的 OA 页)。
    :param timeout: 单页渲染超时秒。
    :param engine: auto | playwright | nodriver。
    :param min_interval: 进程内最小渲染间隔(强限流);自检时可传 0 关闭。
    :param _render_fn: 注入的渲染函数(测试用);生产不传,自动选择可用引擎。

    合规:命中 Google Scholar 域名直接拒绝;仅复用 landing 的纯解析逻辑抽链,绝不自建反爬。
    """
    # ① 合规守卫最先执行:即便注入了渲染函数,也绝不渲染 Scholar / 搜索页。
    if _is_scholar_host(url):
        return {"available": True,
                "error": "refused: this module never renders Google Scholar / search pages",
                "pdf_url": None, "pdf_links": []}

    # ② 选择引擎;无引擎即默认关闭(在限流/渲染之前返回,避免无谓等待)。
    render_fn = _render_fn or _select_engine(engine)
    if render_fn is None:
        return {"available": False, "reason": "need playwright/nodriver",
                "pdf_url": None, "pdf_links": []}

    # ③ 强限流后再渲染。
    _throttle(min_interval)
    try:
        html, final_url = render_fn(url, timeout)
    except Exception as exc:  # noqa: BLE001 - 渲染异常优雅降级,绝不外抛
        return {"available": True, "error": f"render failed: {exc}",
                "pdf_url": None, "pdf_links": []}

    final_url = final_url or url
    # ④ 复用 landing 纯解析从渲染后的 DOM 抽 PDF 直链(置信度从高到低)。
    pdf_links: List[str] = extract_pdf_links(html or "", final_url)
    # 渲染后若最终 URL 本身就是 PDF(被重定向到直链),置于最前。
    if _looks_like_pdf(final_url) and final_url not in pdf_links:
        pdf_links = [final_url] + pdf_links

    return {
        "available": True,
        "url": url,
        "final_url": final_url,
        "pdf_url": pdf_links[0] if pdf_links else None,
        "pdf_links": pdf_links,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 路线B「浏览器内直下 PDF 字节」扩展点(可选、默认关闭、强限流)——破 JA3 绑定型强 CF
# ══════════════════════════════════════════════════════════════════════════════
# 死结:RSC/ScienceDirect 把 cf_clearance 绑到 JA3/TLS 指纹。浏览器(nodriver)解出 CF、
# 拿到 cookie 后,`download.py` 交 curl_cffi/requests **回放**下载仍 403(换更强求解器无效)。
# 破法:solve 与 download 用【同一浏览器会话】——不把 PDF URL 交外部 HTTP 客户端,而是
#   在浏览器内经 CDP(Fetch/Network.getResponseBody)截获 PDF 响应字节,或在页面 JS 上下文里
#   fetch().arrayBuffer() 取字节。这样 TLS/JA3 出口天然一致,CF 无从判别。
# 本扩展点与 `render_get_pdf_url` 并列、纯新增,不改任何现有函数与既有运行路径。
# ------------------------------------------------------------------------------

DEFAULT_BYTES_TIMEOUT = 45.0   # 浏览器内直下单篇超时秒(过 CF + 触发下载 + 抓字节,需更大余量)

# JA3 绑定型强 CF 站(仅这些走浏览器内直下重路径;普通 OA 站不必走这条重路径)
_JA3_BOUND_CF_HOSTS = (
    "pubs.rsc.org", "rsc.org",
    "sciencedirect.com", "pdf.sciencedirectassets.com", "sciencedirectassets.com",
    "onlinelibrary.wiley.com", "pubs.acs.org",
)
# 质询/拦截页文本信号(命中说明仍卡在 CF「Just a moment」等质询页)
_BLOCK_SIGNALS = (
    "just a moment", "verify you are human", "enable javascript and cookies",
    "attention required", "checking your browser", "checking if the site connection",
)
# PDF 响应拦截 URL 模式(Fetch.enable 用;命中即在 RESPONSE 阶段抓响应体)
_PDF_URL_PATTERNS = ("*pdfft*", "*sciencedirectassets.com/*", "*/pdf/*", "*/articlepdf/*", "*.pdf*")

# 抓字节函数签名:capture_fn(article_url, timeout) -> (pdf_bytes | None, note)
CaptureFn = Callable[[str, float], Tuple[Optional[bytes], str]]


def is_ja3_bound_cf_host(url: str) -> bool:
    """该 URL host 是否属 JA3 绑定型强 CF 站(需浏览器内直下;curl_cffi 回放会 403)。

    供 `download.py` 接线判断:仅这些 host 命中 cloudflare-challenge 终态时,才走
    `render_download_pdf_bytes` 这条重路径,普通 CF/OA 站继续走既有更轻的兜底。
    """
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except Exception:  # noqa: BLE001 - 畸形 URL 保守视为不匹配
        return False
    return any(h in host for h in _JA3_BOUND_CF_HOSTS)


def _header_get(headers: Any, name: str) -> str:
    """从 CDP 响应头取头值,大小写不敏感。兼容三种形态:

    * ``network.Headers``(dict 子类)——``Network.responseReceived`` 通道;
    * ``list[fetch.HeaderEntry]``(有 ``.name``/``.value`` 属性)——``Fetch.requestPaused`` 通道;
    * ``list[dict]``(``{"name","value"}``)——raw websocket-client 引擎(引擎 B)通道。
    """
    name = name.lower()
    if headers is None:
        return ""
    if isinstance(headers, dict):
        for k, v in headers.items():
            if str(k).lower() == name:
                return str(v)
        return ""
    for h in headers:
        hn = getattr(h, "name", None)
        hv = getattr(h, "value", None)
        if hn is None and isinstance(h, dict):
            hn, hv = h.get("name"), h.get("value")
        if hn is not None and str(hn).lower() == name:
            return str(hv)
    return ""


def _looks_pdf_response(url: str, status: Any, headers: Any) -> bool:
    """响应像不像 PDF:200 + content-type application/pdf,或 URL 形似 pdf 直链。"""
    if status is not None:
        try:
            if int(status) != 200:
                return False
        except (TypeError, ValueError):
            pass
    if "application/pdf" in _header_get(headers, "content-type").lower():
        return True
    u = (url or "").lower().split("#", 1)[0].split("?", 1)[0]
    return u.endswith(".pdf") or "/pdfft" in u or "sciencedirectassets.com" in u


def _decode_cdp_body(body: Any, base64_encoded: bool) -> bytes:
    """把 CDP getResponseBody / data-URL 的 body 解成 bytes(base64 或 latin-1 兜底)。"""
    if base64_encoded:
        try:
            return base64.b64decode(body or "")
        except Exception:  # noqa: BLE001 - 坏 base64 → 空字节,交由 %PDF 校验拒绝
            return b""
    return (body or "").encode("latin-1", "ignore") if isinstance(body, str) else (body or b"")


def _is_pdf_bytes(data: Any) -> bool:
    """首字节 %PDF 兜底校验(与 download.py 的 %PDF 校验同哲学)。"""
    return bool(data) and data[:4] == b"%PDF"


# 页内找 PDF 直链:复用 landing.extract_pdf_links(纯解析);拿不到则由当前 URL 拼 /pdf 兜底。
def _inpage_find_pdf_url_js() -> str:
    return (
        "(function(){var a=document.querySelector(\"a[href*='/pdf'],a[href$='.pdf'],"
        "a[href*='articlepdf'],a[href*='pdfft']\");if(a&&a.href)return a.href;return '';})()"
    )


# 页内 fetch 抓字节(方法 B):在【已过 CF 的文章页上下文】里发起 fetch,继承其 cookie + JA3,
# 用 FileReader 转 data-URL(base64) 回传。对同源 PDF(如 RSC)最稳;跨域被 CORS 拦时返回 ERR,
# 由方法 A(CDP 网络层拦截,无 CORS)兜底。
def _inpage_fetch_pdf_js(pdf_url: str) -> str:
    return (
        "(async()=>{try{"
        "var r=await fetch(%s,{credentials:'include'});"
        "if(!r.ok)return 'ERR:status='+r.status;"
        "var b=await r.blob();"
        "return await new Promise(function(res){var fr=new FileReader();"
        "fr.onloadend=function(){res(''+fr.result);};"
        "fr.onerror=function(){res('ERR:reader');};fr.readAsDataURL(b);});"
        "}catch(e){return 'ERR:'+e;}})()"
    ) % json.dumps(pdf_url)


def _data_url_to_pdf_bytes(data_url: Any) -> Optional[bytes]:
    """把页内 fetch 回传的 data:...;base64,XXXX 转 bytes;非 data-URL/错误 → None。"""
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        return None
    if "," not in data_url:
        return None
    b64 = data_url.split(",", 1)[1]
    data = _decode_cdp_body(b64, True)
    return data or None


def _nodriver_capture_fn(headless: bool = False) -> Optional[CaptureFn]:
    """返回 nodriver 版『浏览器内抓 PDF 字节』函数;未装 nodriver 则 None。

    引擎 A(nodriver 自带 CDP,零新依赖):开 Fetch/Network 拦截 → 导航文章页过 CF →
    页内 fetch 抓字节(方法 B,同会话同 JA3,首选)→ 不成再导航到 PDF 直链让 Fetch RESPONSE
    拦截器抓(方法 A,网络层无 CORS,处理跨域/viewer)。首字节 %PDF 兜底校验。
    headless 默认 False(有头 CF 通过率更高;无头机可传 True 或用 xvfb)。
    """
    try:
        import nodriver  # noqa: F401
    except ImportError:
        return None
    import asyncio

    def _capture(article_url: str, timeout: float) -> Tuple[Optional[bytes], str]:
        import nodriver as nd
        from nodriver import cdp

        async def _go() -> Tuple[Optional[bytes], str]:
            browser = await nd.start(headless=headless, browser_args=[
                "--lang=en-US", "--disable-blink-features=AutomationControlled",
                "--window-size=1600,1000", "--no-first-run", "--no-default-browser-check"])
            got: Dict[str, Optional[bytes]] = {"data": None}
            pdf_rids: set = set()
            try:
                tab = await browser.get("about:blank")
                await tab.send(cdp.network.enable(
                    max_total_buffer_size=120 * 1024 * 1024,
                    max_resource_buffer_size=100 * 1024 * 1024))
                await tab.send(cdp.network.set_cache_disabled(cache_disabled=True))
                await tab.send(cdp.fetch.enable(patterns=[
                    cdp.fetch.RequestPattern(url_pattern=p,
                                             request_stage=cdp.fetch.RequestStage.RESPONSE)
                    for p in _PDF_URL_PATTERNS]))

                async def on_paused(ev: Any) -> None:
                    rid = ev.request_id
                    try:
                        if got["data"] is None and _looks_pdf_response(
                                getattr(ev.request, "url", ""),
                                getattr(ev, "response_status_code", None),
                                getattr(ev, "response_headers", None)):
                            body, b64 = await tab.send(cdp.fetch.get_response_body(request_id=rid))
                            data = _decode_cdp_body(body, b64)
                            if _is_pdf_bytes(data):
                                got["data"] = data
                    except Exception:  # noqa: BLE001 - 抓取异常不外抛,交由兜底
                        pass
                    finally:
                        try:  # 必须放行,否则该请求挂起阻塞页面/后续导航
                            await tab.send(cdp.fetch.continue_request(request_id=rid))
                        except Exception:  # noqa: BLE001
                            pass

                async def on_resp(ev: Any) -> None:
                    try:
                        resp = ev.response
                        if _looks_pdf_response(getattr(resp, "url", ""),
                                               getattr(resp, "status", None),
                                               getattr(resp, "headers", None)):
                            pdf_rids.add(ev.request_id)
                    except Exception:  # noqa: BLE001
                        pass

                async def on_finished(ev: Any) -> None:
                    if got["data"] is None and ev.request_id in pdf_rids:
                        try:
                            body, b64 = await tab.send(
                                cdp.network.get_response_body(request_id=ev.request_id))
                            data = _decode_cdp_body(body, b64)
                            if _is_pdf_bytes(data):
                                got["data"] = data
                        except Exception:  # noqa: BLE001
                            pass

                tab.add_handler(cdp.fetch.RequestPaused, on_paused)
                tab.add_handler(cdp.network.ResponseReceived, on_resp)
                tab.add_handler(cdp.network.LoadingFinished, on_finished)

                async def _eval_str(expression: str, await_promise: bool = False,
                                    t: float = 30.0) -> str:
                    """tab.evaluate 但恒返回 str 且带超时。两个坑一起收敛:
                    ① nodriver 在 JS 结果为假值(空串)时会「回落返回原始 RemoteObject 而非值」,
                       直接拿去做 `in`/字符串操作会抛 `argument of type 'RemoteObject' is not
                       iterable`；② await_promise 的页内 fetch 可能永不 resolve(挂死)。
                    统一:超时/异常/非 str → ''(绝不阻塞、绝不外抛)。"""
                    try:
                        res = await asyncio.wait_for(
                            tab.evaluate(expression, await_promise=await_promise,
                                         return_by_value=True), timeout=t)
                    except Exception:  # noqa: BLE001 (含 asyncio.TimeoutError)
                        return ""
                    return res if isinstance(res, str) else ""

                async def _nav(url: str, t: float) -> None:
                    """带超时导航。导航到 PDF 会打开内置 viewer / 触发下载,tab.get 可能永不返回,
                    故必须包超时——超时后由拦截器/轮询兜底,绝不阻塞整体。"""
                    try:
                        await asyncio.wait_for(tab.get(url), timeout=t)
                    except Exception:  # noqa: BLE001
                        pass

                # ① 导航到「文章页」(不是 md5 短链);nodriver 自动过 CF 质询。
                await _nav(article_url, min(max(10.0, float(timeout)), 40.0))
                deadline = time.monotonic() + max(5.0, float(timeout))
                triggered = False
                last_blocked = False
                while time.monotonic() < deadline and got["data"] is None:
                    await tab.sleep(0.6)
                    if got["data"] is not None:
                        break
                    txt = await _eval_str(
                        "document.body?document.body.innerText.slice(0,1500).toLowerCase():''",
                        t=10.0)
                    last_blocked = any(s in txt for s in _BLOCK_SIGNALS)
                    if last_blocked or triggered:
                        continue  # 仍在质询页(等 nodriver 过盾)或已触发(等拦截器抓字节)
                    # ② CF 已过 → 页内找 PDF 直链并在浏览器内抓字节。
                    try:
                        html = await asyncio.wait_for(tab.get_content(), timeout=10.0)
                    except Exception:  # noqa: BLE001
                        html = ""
                    cur = (await _eval_str("location.href", t=10.0)) or article_url
                    links = extract_pdf_links(html or "", cur)
                    pdf_url = links[0] if links else (await _eval_str(_inpage_find_pdf_url_js(), t=10.0))
                    if not pdf_url:
                        continue
                    triggered = True
                    # 方法 B:文章页上下文内 fetch(同 cookie + JA3),首选(同源最稳)。
                    data_url = await _eval_str(_inpage_fetch_pdf_js(pdf_url), await_promise=True,
                                               t=min(max(10.0, float(timeout)), 40.0))
                    data_b = _data_url_to_pdf_bytes(data_url)
                    if _is_pdf_bytes(data_b):
                        got["data"] = data_b
                        break
                    # 方法 A:导航到 PDF 直链,让 Fetch RESPONSE 拦截器在网络层抓(无 CORS)。
                    await _nav(pdf_url, 15.0)
                    sub_deadline = time.monotonic() + max(5.0, float(timeout) / 2)
                    while time.monotonic() < sub_deadline and got["data"] is None:
                        await tab.sleep(0.6)
                if got["data"] is not None:
                    return got["data"], "ok"
                return None, ("blocked:challenge-page" if last_blocked else "no-pdf-captured")
            finally:
                try:
                    browser.stop()
                except Exception:  # noqa: BLE001
                    pass

        async def _run_bounded() -> Tuple[Optional[bytes], str]:
            """整体硬超时兜底:任何单步意外挂死,也在 timeout + 余量内收敛返回。"""
            try:
                return await asyncio.wait_for(_go(), timeout=max(15.0, float(timeout)) + 30.0)
            except Exception:  # noqa: BLE001 (含 TimeoutError:_go 内 finally 会 stop 浏览器)
                return None, "timeout"

        return asyncio.run(_run_bounded())

    return _capture


def render_download_pdf_bytes(
    article_url: str,
    timeout: float = DEFAULT_BYTES_TIMEOUT,
    *,
    min_interval: float = DEFAULT_MIN_INTERVAL,
    headless: bool = False,
    _capture_fn: Optional[CaptureFn] = None,
) -> Dict[str, Any]:
    """在浏览器内直接抓 PDF 字节(破 JA3 绑定型强 CF)。可选、默认关闭、强限流。

    与 `render_get_pdf_url` 对齐:先合规守卫(永不渲染 Google Scholar)、再强限流、再抓字节。
    统一信封 dict:

    - 无引擎(未装 nodriver,默认关闭)::

        {"available": False, "reason": "need nodriver", "pdf_bytes": None}

    - 被合规守卫拒绝(Scholar / 搜索页)::

        {"available": True, "error": "refused: ...", "pdf_bytes": None}

    - 被 CF 质询页拦住::

        {"available": True, "error": "blocked:...", "pdf_bytes": None}

    - 抓到非 PDF / 未抓到::

        {"available": True, "error": "no-pdf: ...", "pdf_bytes": None}

    - 成功::

        {"available": True, "url": ..., "note": "ok", "pdf_bytes": b"%PDF...", "size": N}

    :param article_url: 【文章页】URL(不要传 pdf 短链;短时签名 URL 脱离活页上下文必 403)。
    :param timeout: 单篇抓取超时秒(过 CF + 触发下载 + 抓字节)。
    :param min_interval: 进程内最小间隔(强限流);自检可传 0。
    :param headless: 是否无头(默认 False=有头,CF 通过率更高)。
    :param _capture_fn: 注入的抓字节函数(测试用);生产不传,自动用 nodriver 引擎。
    """
    # ① 合规守卫最先执行:即便注入了抓字节函数,也绝不渲染/抓取 Scholar。
    if _is_scholar_host(article_url):
        return {"available": True,
                "error": "refused: this module never renders Google Scholar / search pages",
                "pdf_bytes": None}
    # ② 选引擎;无引擎即默认关闭(在限流/抓取之前返回)。
    cap = _capture_fn or _nodriver_capture_fn(headless=headless)
    if cap is None:
        return {"available": False, "reason": "need nodriver", "pdf_bytes": None}
    # ③ 强限流后再抓。
    _throttle(min_interval)
    try:
        data, note = cap(article_url, timeout)
    except Exception as exc:  # noqa: BLE001 - 抓取异常优雅降级,绝不外抛
        return {"available": True, "error": f"capture failed: {exc}", "pdf_bytes": None}
    if isinstance(note, str) and note.startswith("blocked:"):
        return {"available": True, "error": note, "pdf_bytes": None}
    if not _is_pdf_bytes(data):
        return {"available": True, "error": f"no-pdf: {note}", "pdf_bytes": None}
    return {"available": True, "url": article_url, "note": note,
            "pdf_bytes": data, "size": len(data)}


def _selftest() -> int:
    """不联网 / 无浏览器自检:mock 掉渲染引擎,验证降级与 DOM 抽链,打印 RENDER_OK。"""

    def _fake_render(url: str, timeout: float):
        # 模拟渲染后 DOM:强 meta citation_pdf_url + 通用 <a> /pdf
        html = (
            "<html><head>"
            '<meta name="citation_pdf_url" content="/final/paper.pdf">'
            "</head><body>"
            '<a href="/viewer/x.pdf">PDF</a>'
            "</body></html>"
        )
        return html, "https://oa.example.org/article/1"

    # 1) 成功路径:注入 mock 渲染 → 复用 landing 抽出最高置信度 PDF 直链(已绝对化)
    ok = render_get_pdf_url("https://oa.example.org/article/1",
                            _render_fn=_fake_render, min_interval=0.0)
    assert ok["available"] is True, ok
    assert ok["pdf_url"] == "https://oa.example.org/final/paper.pdf", ok
    assert "https://oa.example.org/final/paper.pdf" in ok["pdf_links"], ok
    assert "https://oa.example.org/viewer/x.pdf" in ok["pdf_links"], ok
    assert ok["final_url"] == "https://oa.example.org/article/1", ok

    # 2) 最终 URL 本身即 PDF(被重定向到直链)→ 置于最前
    def _pdf_final(url: str, timeout: float):
        return "<html><body>no links</body></html>", "https://oa.example.org/served/file.pdf"

    r2 = render_get_pdf_url("https://oa.example.org/a", _render_fn=_pdf_final, min_interval=0.0)
    assert r2["pdf_url"] == "https://oa.example.org/served/file.pdf", r2

    # 3) 合规守卫:Scholar 域名即便注入渲染函数也被直接拒绝(绝不渲染)
    for scholar_url in (
        "https://scholar.google.com/scholar?q=deep+learning",
        "https://scholar.google.de/citations?user=x",
        "https://www.google.com/scholar?q=x",
    ):
        ref = render_get_pdf_url(scholar_url, _render_fn=_fake_render, min_interval=0.0)
        assert ref["available"] is True and ref["pdf_url"] is None, ref
        assert str(ref.get("error", "")).startswith("refused"), ref

    # 4) 优雅降级:无任何可用引擎 → available:False, reason 明确(临时清空工厂表以确定性断言)
    saved = dict(_ENGINE_FACTORIES)
    try:
        _ENGINE_FACTORIES["playwright"] = lambda: None
        _ENGINE_FACTORIES["nodriver"] = lambda: None
        off = render_get_pdf_url("https://oa.example.org/article/1", engine="auto", min_interval=0.0)
        assert off == {"available": False, "reason": "need playwright/nodriver",
                       "pdf_url": None, "pdf_links": []}, off
    finally:
        _ENGINE_FACTORIES.clear()
        _ENGINE_FACTORIES.update(saved)

    # 5) 渲染异常 → 优雅降级为 error(不外抛)
    def _boom(url: str, timeout: float):
        raise RuntimeError("navigation timeout")

    err = render_get_pdf_url("https://oa.example.org/a", _render_fn=_boom, min_interval=0.0)
    assert err["available"] is True and err["pdf_url"] is None, err
    assert "render failed" in str(err.get("error", "")), err

    # 6) 渲染出无 PDF 的页面 → pdf_url None、pdf_links 空,但不报错
    def _no_pdf(url: str, timeout: float):
        return "<html><body><a href='/home'>home</a></body></html>", "https://oa.example.org/a"

    none_res = render_get_pdf_url("https://oa.example.org/a", _render_fn=_no_pdf, min_interval=0.0)
    assert none_res["available"] is True and none_res["pdf_url"] is None, none_res
    assert none_res["pdf_links"] == [], none_res

    # 7) 引擎选择器:auto/指定 引擎在无依赖工厂下均返回 None
    saved2 = dict(_ENGINE_FACTORIES)
    try:
        _ENGINE_FACTORIES["playwright"] = lambda: None
        _ENGINE_FACTORIES["nodriver"] = lambda: None
        assert _select_engine("auto") is None
        assert _select_engine("playwright") is None
        assert _select_engine("nodriver") is None
    finally:
        _ENGINE_FACTORIES.clear()
        _ENGINE_FACTORIES.update(saved2)

    _selftest_bytes()
    print("RENDER_OK")
    return 0


def _selftest_bytes() -> None:
    """离线自检『浏览器内直下 PDF 字节』扩展点(不联网、不起浏览器);打印 RENDER_BYTES_OK。

    全部走注入的 mock ``_capture_fn`` 或纯函数,确定性验证信封与守卫,零副作用。
    """
    # 1) 纯函数:JA3 绑定型强 CF 站判定
    assert is_ja3_bound_cf_host("https://pubs.rsc.org/en/content/articlepdf/2011/GC/C1GC15503B")
    assert is_ja3_bound_cf_host("https://www.sciencedirect.com/science/article/pii/X")
    assert is_ja3_bound_cf_host("https://pdf.sciencedirectassets.com/xxx/main.pdf?md5=1")
    assert is_ja3_bound_cf_host("https://onlinelibrary.wiley.com/doi/10.1002/x")
    assert not is_ja3_bound_cf_host("https://www.mdpi.com/x")
    assert not is_ja3_bound_cf_host("")

    # 2) 纯函数:PDF 响应判定(三种 header 形态 + 200 门槛)
    class _HE:  # 模拟 fetch.HeaderEntry(有 .name/.value)
        def __init__(self, n, v):
            self.name, self.value = n, v
    assert _looks_pdf_response("https://x/pdfft?md5=1", 200, [_HE("Content-Type", "application/pdf")])
    assert _looks_pdf_response("https://x/a", 200, {"content-type": "application/pdf; charset=utf-8"})
    assert _looks_pdf_response("https://x/a", 200, [{"name": "Content-Type", "value": "application/pdf"}])
    assert not _looks_pdf_response("https://x/article", 200, [_HE("Content-Type", "text/html")])
    assert not _looks_pdf_response("https://x/a.pdf", 403, [])          # 非 200 不算
    assert _looks_pdf_response("https://x/paper.pdf", None, None)       # 无状态但 URL 形似 pdf
    assert _looks_pdf_response("https://x/sciencedirectassets.com/f", None, None)

    # 3) 纯函数:字节校验 / 解码 / data-URL 还原
    assert _is_pdf_bytes(b"%PDF-1.7 xx") and not _is_pdf_bytes(b"<html>") and not _is_pdf_bytes(b"")
    assert _decode_cdp_body("JVBERi0x", True)[:4] == b"%PDF"           # base64("%PDF-1")
    assert _decode_cdp_body("%PDF-1.7", False)[:4] == b"%PDF"          # 非 base64 → latin-1
    assert _decode_cdp_body("!!bad!!", True) == b""                    # 坏 base64 → 空
    assert _data_url_to_pdf_bytes("data:application/pdf;base64,JVBERi0x")[:4] == b"%PDF"
    assert _data_url_to_pdf_bytes("ERR:status=403") is None
    assert _data_url_to_pdf_bytes(None) is None

    # 4) 头取值:大小写不敏感 + 三形态
    assert _header_get([_HE("Content-Type", "application/pdf")], "content-type") == "application/pdf"
    assert _header_get({"Content-Type": "application/pdf"}, "CONTENT-TYPE") == "application/pdf"
    assert _header_get([{"name": "X", "value": "1"}], "y") == ""
    assert _header_get(None, "content-type") == ""

    # 5) 成功路径:注入 mock capture 返回 %PDF 字节 → 信封成功
    ok = render_download_pdf_bytes("https://pubs.rsc.org/a",
                                   _capture_fn=lambda u, t: (b"%PDF-1.7 hello", "ok"),
                                   min_interval=0.0)
    assert ok["available"] and ok["pdf_bytes"][:4] == b"%PDF" and ok["size"] > 0, ok
    assert ok["url"] == "https://pubs.rsc.org/a" and ok["note"] == "ok", ok

    # 6) blocked:质询页拦住 → error 以 blocked: 开头
    b = render_download_pdf_bytes("https://pubs.rsc.org/a",
                                  _capture_fn=lambda u, t: (None, "blocked:challenge-page"),
                                  min_interval=0.0)
    assert b["pdf_bytes"] is None and str(b["error"]).startswith("blocked:"), b

    # 7) 抓到非 PDF → no-pdf
    n = render_download_pdf_bytes("https://pubs.rsc.org/a",
                                  _capture_fn=lambda u, t: (b"<html>nope", "ok"), min_interval=0.0)
    assert n["pdf_bytes"] is None and "no-pdf" in str(n["error"]), n

    # 8) 未抓到(None + 普通 note)→ no-pdf
    n2 = render_download_pdf_bytes("https://pubs.rsc.org/a",
                                   _capture_fn=lambda u, t: (None, "no-pdf-captured"), min_interval=0.0)
    assert n2["pdf_bytes"] is None and "no-pdf" in str(n2["error"]), n2

    # 9) 合规守卫:Scholar 即便注入 capture 也被直接拒绝(绝不抓取)
    for scholar_url in ("https://scholar.google.com/scholar?q=x",
                        "https://www.google.com/scholar?q=x"):
        r = render_download_pdf_bytes(scholar_url,
                                      _capture_fn=lambda u, t: (b"%PDF", "ok"), min_interval=0.0)
        assert r["pdf_bytes"] is None and str(r["error"]).startswith("refused"), r

    # 10) capture 抛错 → 优雅降级(绝不外抛)
    def _boom(u, t):
        raise RuntimeError("cdp timeout")
    e = render_download_pdf_bytes("https://pubs.rsc.org/a", _capture_fn=_boom, min_interval=0.0)
    assert e["pdf_bytes"] is None and "capture failed" in str(e["error"]), e

    # 11) 无引擎 → available:False, reason need nodriver。
    #     经 globals() 临时把工厂替换为返回 None(robust 于 `-m` 运行时 __main__ 双份导入:
    #     render_download_pdf_bytes 与本函数共享同一 globals,查找到的即被替换的工厂)。
    _g = globals()
    real_factory = _g["_nodriver_capture_fn"]
    try:
        _g["_nodriver_capture_fn"] = lambda headless=False: None
        off = render_download_pdf_bytes("https://pubs.rsc.org/a", min_interval=0.0)
        assert off == {"available": False, "reason": "need nodriver", "pdf_bytes": None}, off
    finally:
        _g["_nodriver_capture_fn"] = real_factory

    print("RENDER_BYTES_OK")


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m fulltext_fetcher.render_fetch",
        description=("无头浏览器渲染兜底(可选、默认关闭、强限流):仅对已合法获取的 OA 落地页"
                     "渲染后取 PDF 直链。严禁用于 Google Scholar / 搜索页。"),
    )
    ap.add_argument("url", nargs="?", help="OA 落地页 URL(仅限已合法获取、有权访问的 OA 页)")
    ap.add_argument("--engine", default="auto", choices=["auto", "playwright", "nodriver"],
                    help="渲染引擎(默认 auto:先 Playwright 再 nodriver)")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="渲染超时秒")
    ap.add_argument("--min-interval", type=float, default=DEFAULT_MIN_INTERVAL,
                    help="进程内最小渲染间隔秒(强限流)")
    ap.add_argument("--capture-bytes", action="store_true",
                    help="走『浏览器内直下 PDF 字节』扩展点(破 JA3 绑定型强 CF);传文章页 URL")
    ap.add_argument("--headless", action="store_true",
                    help="配合 --capture-bytes:无头模式(默认有头,CF 通过率更高)")
    ap.add_argument("--save", metavar="PATH", help="配合 --capture-bytes:把抓到的 PDF 落盘到此路径")
    ap.add_argument("--selftest", action="store_true", help="不联网/无浏览器自检并退出")
    args = ap.parse_args(argv)

    if args.selftest or not args.url:
        return _selftest()

    if args.capture_bytes:
        bytes_timeout = args.timeout if args.timeout != DEFAULT_TIMEOUT else DEFAULT_BYTES_TIMEOUT
        res = render_download_pdf_bytes(args.url, timeout=bytes_timeout,
                                        min_interval=args.min_interval, headless=args.headless)
        data = res.pop("pdf_bytes", None)  # 不把二进制打进 JSON
        res["has_pdf_bytes"] = bool(data)
        res["is_pdf"] = _is_pdf_bytes(data)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        if data and args.save:
            try:
                with open(args.save, "wb") as fh:
                    fh.write(data)
                print("[已落盘] %s (%d bytes)" % (args.save, len(data)), file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                print("[落盘失败] %s: %s" % (args.save, exc), file=sys.stderr)
        if not res.get("available"):
            print("[提示] 浏览器内直下默认关闭:需安装可选依赖 nodriver 才能启用。", file=sys.stderr)
            return 2
        return 0 if res.get("is_pdf") else 1

    res = render_get_pdf_url(args.url, timeout=args.timeout, engine=args.engine,
                             min_interval=args.min_interval)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("available"):
        print("[提示] 渲染兜底默认关闭:需安装可选依赖 playwright(推荐)或 nodriver 才能启用。",
              file=sys.stderr)
        return 2
    if res.get("error"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
