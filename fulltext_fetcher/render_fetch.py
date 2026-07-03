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
import contextlib
import json
import os
import random
import re
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:  # 以 `python -m fulltext_fetcher.render_fetch` 运行时相对导入成立
    from .landing import extract_pdf_links
except ImportError:  # 兜底:绝对包路径(极端运行环境)
    from fulltext_fetcher.landing import extract_pdf_links


# ── nodriver × 新版 Chrome 的 CDP 字段漂移兼容(route-B 前置修复)─────────────────
# Chrome 133 的 Network.ClientSecurityState 不再必带 localNetworkAccessRequestPolicy,
# 而 nodriver(0.50.x)的 CDP 模型按必选字段解析 → requestWillBeSentExtraInfo 等事件
# 抛 KeyError(connection.process_event 会逐条 catch 丢弃:非致命,但刷屏日志且丢该事件)。
# 这里做**仅本进程内存生效**的最小 monkey-patch:该字段缺失时降级为 None,不改 site-packages、
# 不影响其它进程(如在跑的 flaresolverr shim)。幂等;未装 nodriver 时静默跳过。
def _patch_nodriver_cdp_compat() -> None:
    try:
        import nodriver.cdp.network as _net  # 延迟导入:未装 nodriver 即无需 patch
    except Exception:  # noqa: BLE001 - 未装 nodriver / 导入异常 → 跳过
        return
    cls = getattr(_net, "ClientSecurityState", None)
    if cls is None or getattr(cls, "_ff_cdp_compat", False):
        return

    def _enum_or(enum_cls, raw, default):
        """枚举容错解析:未知/新值(如 Chrome 新版 'PreflightWarn')→ default,绝不抛。

        真机核查(-152):字段【存在但值是 nodriver 0.50.3 不认识的新枚举】时,``from_json`` 抛
        ValueError,connection.process_event 逐条 catch 但会刷上千行 listener error 洪水。故这里
        把枚举解析整体 try 住,未知值退 default(对齐探针 _route_b_b2_152.py 的写法)。
        """
        if raw is None:
            return default
        try:
            return enum_cls.from_json(raw)
        except Exception:  # noqa: BLE001 - 未知/新枚举值 → 退 default(不刷屏、不丢整条事件)
            return default

    def _tolerant_from_json(c, json):  # 镜像原 from_json,对漂移字段 + 未知枚举双重容错
        # Chrome 133 发【旧名】privateNetworkRequestPolicy;nodriver 0.50.x 只认【新名】
        # localNetworkAccessRequestPolicy → 两名都取;缺失【或值为未知新枚举】都退 ALLOW(见 152 真机)。
        raw = json.get("localNetworkAccessRequestPolicy") or json.get("privateNetworkRequestPolicy")
        ip_default = getattr(_net.IPAddressSpace, "UNKNOWN", None) or getattr(_net.IPAddressSpace, "PUBLIC", None)
        return c(
            initiator_is_secure_context=bool(json.get("initiatorIsSecureContext", False)),
            initiator_ip_address_space=_enum_or(
                _net.IPAddressSpace, json.get("initiatorIPAddressSpace"), ip_default),
            local_network_access_request_policy=_enum_or(
                _net.LocalNetworkAccessRequestPolicy, raw, _net.LocalNetworkAccessRequestPolicy.ALLOW),
        )

    try:
        cls.from_json = classmethod(_tolerant_from_json)
        cls._ff_cdp_compat = True
    except Exception:  # noqa: BLE001 - patch 失败绝不影响主流程
        pass


_patch_nodriver_cdp_compat()

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


# ── 单头浏览器硬护栏(concurrency=1,route-B)────────────────────────────────────
# 全组共用一台机器、一个有头浏览器出口:路线B「浏览器内直下」必须【单头串行】,多头并发会
# 互相踩 CF 会话/显示/端口,通过率骤降甚至互锁。两层护栏(在 _throttle 最小间隔之上再加):
#   ① 进程内 BoundedSemaphore(1):同进程多线程串行;
#   ② 跨进程文件锁(默认 out/.route_b.lock):同机多进程(不同组员)串行。
# 文件锁用最朴素、跨平台一致的『原子建锁文件 O_CREAT|O_EXCL + 陈旧锁接管』(不依赖 msvcrt/fcntl,
# Windows/POSIX 行为一致);拿不到就轮询等待。lock_path=None → 只用进程内信号量(selftest / 未配
# out_dir 时零副作用)。绝不抛:任何文件系统异常都优雅退化为仅进程内信号量。
_browser_capture_sem = threading.BoundedSemaphore(1)
_SINGLE_HEAD_STALE_SEC = 600.0     # 陈旧锁接管阈值(> 单篇硬超时上限):防死进程永久占锁


def _lock_is_stale(lock_path: str, stale: float) -> bool:
    """锁文件是否陈旧(持锁进程疑似已死):按 mtime 超过 stale 秒判定。读不到 mtime → 视为可重抢。"""
    try:
        return (time.time() - os.path.getmtime(lock_path)) > stale
    except OSError:
        return True


def _acquire_file_lock(lock_path: str, poll: float = 0.5,
                       stale: float = _SINGLE_HEAD_STALE_SEC) -> Optional[str]:
    """跨进程独占:原子创建锁文件(O_CREAT|O_EXCL);被占则轮询等待,陈旧锁自动接管。

    返回 ``lock_path``(已持有)或 ``None``(目录不可写等 → 放弃文件锁,退化为仅进程内信号量)。绝不抛。
    """
    d = os.path.dirname(lock_path)
    try:
        if d:
            os.makedirs(d, exist_ok=True)
    except OSError:
        return None
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _lock_is_stale(lock_path, stale):
                try:
                    os.remove(lock_path)          # 陈旧 → 删掉重抢
                except OSError:
                    pass
                continue
            time.sleep(poll)
            continue
        except OSError:
            return None                            # 目录不可写/路径非法 → 放弃文件锁
        try:
            os.write(fd, str(os.getpid()).encode("ascii", "ignore"))
        except OSError:
            pass
        finally:
            os.close(fd)
        return lock_path


@contextlib.contextmanager
def _single_head_guard(lock_path: Optional[str] = None):
    """单头串行护栏:进程内 BoundedSemaphore(1) +(给了 lock_path 时)跨进程文件锁。

    lock_path=None → 仅进程内信号量(selftest / 未配 out_dir 时零文件副作用)。
    """
    _browser_capture_sem.acquire()
    held: Optional[str] = None
    try:
        if lock_path:
            held = _acquire_file_lock(lock_path)
        yield
    finally:
        if held:
            try:
                os.remove(held)
            except OSError:
                pass
        _browser_capture_sem.release()


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
# 含 Cloudflare 新版文案(Turnstile/Interstitial 2024-2025 改版),避免漏判 CF 未过就误抓。
_BLOCK_SIGNALS = (
    "just a moment", "verify you are human", "enable javascript and cookies",
    "attention required", "checking your browser", "checking if the site connection",
    "performing security verification", "verifies you are not a bot",
    "verifying you are human", "needs to review the security of your connection",
)
# RSC governor 第二道门(-165):应用层 rate-gate + 坏 reCAPTCHA,不可硬解,只能不触发。
_GOVERNOR_SIGNALS = (
    "crawlprevention/governor", "validate user", "invalid domain for site key",
    "take me to my content", "experiencing unusual traffic", "articlepdfhandler",
)
_RSC_HOST_MARKERS = ("pubs.rsc.org", "rsc.org")
# per-host 限速/冷却(进程内;-165 P3)
_HOST_STATE: Dict[str, Dict[str, float]] = {}
_HOST_STATE_LOCK = threading.Lock()
_RSC_MIN_HOST_GAP = 30.0   # 同 host 两次 capture 最小间隔秒
_RSC_GOVERNOR_COOLDOWN = 300.0  # 命中 governor 后冷却秒


def _host_from_url(url: str) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def _is_rsc_host(url: str) -> bool:
    host = _host_from_url(url)
    return any(m in host for m in _RSC_HOST_MARKERS)


def _looks_governor(url: str, html: str) -> bool:
    low = ((url or "") + " " + (html or "")).lower()
    return any(s in low for s in _GOVERNOR_SIGNALS)


def _looks_governor_softblock(url: str, html: str) -> bool:
    low = ((url or "") + " " + (html or "")).lower()
    return "invalid domain for site key" in low


def _rsc_articlepdf_to_landing(pdf_url: str) -> Optional[str]:
    """articlepdf 直链 → articlelanding 预热 URL(-165 P2:别直怼 PDF handler)。"""
    u = pdf_url or ""
    if "/articlepdf/" not in u.lower():
        return None
    try:
        parts = u.split("/articlepdf/", 1)[1].split("/")
        if len(parts) < 3:
            return None
        year, jcode, suffix = parts[0], parts[1].upper(), parts[2].split("?", 1)[0]
        base = u.split("/en/content/", 1)[0]
        return f"{base}/en/content/articlelanding/{year}/{jcode}/{suffix}"
    except Exception:  # noqa: BLE001
        return None


def _host_capture_gate(url: str) -> Optional[str]:
    """RSC per-host 冷却/限速;返回 deferred/blocked note 或 None 表示可继续。"""
    if not _is_rsc_host(url):
        return None
    host = _host_from_url(url) or "rsc.org"
    with _HOST_STATE_LOCK:
        st = _HOST_STATE.setdefault(host, {})
        now = time.monotonic()
        if st.get("cooldown_until", 0) > now:
            return "deferred:rsc-governor-cooldown"
        last = st.get("last_capture", 0.0)
        gap = _RSC_MIN_HOST_GAP + random.uniform(0, 30.0)
        wait = last + gap - now
    if wait > 0:
        time.sleep(wait)
    with _HOST_STATE_LOCK:
        _HOST_STATE.setdefault(host, {})["last_capture"] = time.monotonic()
    return None


def _host_register_governor(url: str, soft: bool = False) -> None:
    if not _is_rsc_host(url):
        return
    host = _host_from_url(url) or "rsc.org"
    with _HOST_STATE_LOCK:
        st = _HOST_STATE.setdefault(host, {})
        st["cooldown_until"] = time.monotonic() + _RSC_GOVERNOR_COOLDOWN
        st["last_governor"] = time.monotonic()
        st["last_softblock"] = 1.0 if soft else 0.0


def _cfg_for_injection_plan(plan: Any) -> Any:
    """RouteBInjectionPlan → 最小 Config 形态,供 ezproxy 改写复用 http_client 守卫。"""
    from .config import Config

    host = getattr(plan, "rewrite_target_host", None) or ""
    domains = [host] if host else list(getattr(plan, "institution_domains", None) or [])
    return Config(
        ezproxy_prefix=getattr(plan, "ezproxy_prefix", None),
        institution_cookie="injected" if getattr(plan, "cookie_count", lambda: 0)() else None,
        institution_domains=domains,
    )


def rewrite_url_for_injection_plan(url: str, plan: Any) -> str:
    """A5 注入计划下的 EZproxy URL 改写(离线可测;与 http_client 守卫一致)。"""
    if not plan or not getattr(plan, "ezproxy_prefix", None):
        return url
    from .http_client import rewrite_url_for_proxy

    return rewrite_url_for_proxy(url, _cfg_for_injection_plan(plan))


async def inject_institutional_session(tab: Any, plan: Any, *, cdp: Any) -> None:
    """route-B 导航前向 nodriver tab 注入机构 Cookie(+可选 UA),与 B1 同 tab 同 JA3。

    契约见 ``fulltext_fetcher.institutional.route_b_bridge.ROUTE_B_INJECT_HOOK_DOC``。
    调用方在注入后应 ``navigate`` 到 ``rewrite_url_for_injection_plan(url, plan)``。
    """
    if not plan:
        return
    for spec in getattr(plan, "cookies", None) or []:
        try:
            kwargs: Dict[str, Any] = {
                "name": spec.name,
                "value": spec.value,
                "domain": spec.domain or "",
                "path": getattr(spec, "path", None) or "/",
                "secure": bool(getattr(spec, "secure", False)),
                "http_only": bool(getattr(spec, "http_only", False)),
            }
            exp = getattr(spec, "expires", None)
            if exp is not None:
                kwargs["expires"] = float(exp)
            await tab.send(cdp.network.set_cookie(**kwargs))
        except Exception:  # noqa: BLE001 - 单条 cookie 失败不阻断其余
            pass
    ua = getattr(plan, "user_agent", None)
    if ua:
        try:
            await tab.send(cdp.emulation.set_user_agent_override(user_agent=str(ua)))
        except Exception:  # noqa: BLE001
            pass


# PDF 响应拦截 URL 模式(Fetch.enable 用;命中即在 RESPONSE 阶段抓响应体)
# 注:`*/pdf*`(-149 MDPI 实证补入)——MDPI 的 `/pdf?version=` 直链不含 `.pdf` 也非 `/pdf/`,
# 旧模式漏网;加宽后覆盖 MDPI 这类 `/pdf?…` attachment 直链。实际抓取仍由 `_looks_pdf_response`
# (content-type=application/pdf 或 URL 形似 pdf)二次把关,过宽命中不会误抓非 PDF。
_PDF_URL_PATTERNS = ("*pdfft*", "*sciencedirectassets.com/*", "*/pdf/*", "*/pdf*",
                     "*/articlepdf/*", "*.pdf*")

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


def _headless_env_override() -> Optional[bool]:
    """全局『办公不被弹窗打扰』总开关 ``FTF_HEADLESS`` 的解析:
    ``1/true/yes/on`` → True(无头);``0/false/no/off`` → False(有头);未设 / 其它 → None(不覆盖)。
    供 route-B 与 Akamai 有头下载统一尊重同一环境变量,做一处总开关。"""
    v = os.environ.get("FTF_HEADLESS", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return None


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _resolve_headless(default: bool = False) -> bool:  # noqa: ARG001 - default 仅留作 API 兼容
    """route-B「浏览器内直下」无头开关。**默认【有头】(headed) + 靠窗口移出屏幕不弹窗**(见 _offscreen_args)。

    2026-07 纠偏(-157 真机证据 + -146 定标):此前曾改「默认纯无头」以求不弹窗,但真机实测 managed-challenge
    站(AIP/ACS 等)【纯无头过 CF 通过率极低】(本机 headless 81.5s 拿不到 cf_clearance,有头+移屏外 15.7s 即过)
    ——纯无头会废掉过盾主功能。故默认改回【有头】,用「窗口移出屏幕」达成"不弹窗打扰办公"又不牺牲 CF。覆盖:
    ``FTF_HEADLESS=1/true/yes/on`` → 强制纯无头(无显示环境/服务器 opt-in);``=0/false/no/off`` 或【未设】→ 有头。
    参数 ``default`` 已不再影响结果(保留仅为 API 向后兼容:旧调用 ``_resolve_headless(headless)`` 仍合法)。"""
    ov = _headless_env_override()
    return ov if ov is not None else False


def _offscreen_args(headless: bool) -> List[str]:
    """有头模式下【默认】把窗口移出可视区域:不弹窗打扰办公,又保留有头的 CF 通过率(优于纯无头)。
    要显示窗口排障/调 CF 时设 FTF_BROWSER_SHOW=1/true/yes/on。无头本就无窗口,返回空。"""
    if headless or _env_true("FTF_BROWSER_SHOW"):
        return []
    return ["--window-position=-2400,-2400"]


def _route_b_user_data_dir() -> Optional[str]:
    """(-165 P4)route-B 持久化浏览器档案目录:让 CF/Turnstile 看到「回访人类」(复用历史 cookie/信誉)。
    由 ``FTF_ROUTE_B_USER_DATA_DIR`` 提供;未设 → None(nodriver 用临时档案,默认行为不变)。"""
    d = (os.environ.get("FTF_ROUTE_B_USER_DATA_DIR") or "").strip()
    return d or None


# ── CF Turnstile 硬解题(-146:攻克 image1 的「Verify you are human」交互式验证)──────────
# 与 RSC governor 坏 reCAPTCHA(不可解、只冷却)不同:CF Turnstile 有合法 sitekey,capsolver/2captcha
# 可出 token。真浏览器(nodriver)多数能自动过;仅【硬 Turnstile / 无头 / 被盯上】时才需打码兜底。
# 全 gated:仅当 env 打码三件套(FTF_CAPTCHA_ENABLED=1 + FTF_CAPTCHA_PROVIDER + FTF_CAPTCHA_KEY)齐备
# 才启用;默认关 → 下面 hook 完全短路,route-B 行为逐字节不变。下列纯函数离线可测。
_TURNSTILE_MARKERS = ("cf-turnstile", "challenges.cloudflare.com/turnstile", "turnstile.render")
_TURNSTILE_SITEKEY_RE = re.compile(
    r"""(?:data-sitekey|sitekey)\s*[=:]\s*["']?(0x[0-9A-Za-z_\-]{6,})["']?""")


def _extract_turnstile_sitekey(html: str) -> Optional[str]:
    """从 HTML 抽 Cloudflare Turnstile 的 sitekey;无则 None。纯解析、离线可测。

    与 reCAPTCHA(``6L`` 开头、``g-recaptcha``)区分:优先认 ``0x`` 前缀(生产 Turnstile);
    仅在明确 ``cf-turnstile`` / turnstile 标记上下文里才回退接受其它前缀(测试/自定义 key),
    避免把 reCAPTCHA 的 sitekey 误当 Turnstile。
    """
    if not html:
        return None
    m = _TURNSTILE_SITEKEY_RE.search(html)
    if m:
        return m.group(1)
    low = html.lower()
    if any(mk in low for mk in _TURNSTILE_MARKERS):
        m2 = re.search(r"""(?:data-sitekey|sitekey)\s*[=:]\s*["']?([0-9A-Za-z_\-]{8,})["']?""", html)
        if m2:
            return m2.group(1)
    return None


def _inject_turnstile_token_js(token: str) -> str:
    """把解出的 Turnstile token 填入页面隐藏域并尝试触发回调,便于表单提交/质询通过(best-effort)。"""
    return (
        "(function(t){try{var n=0;"
        "var els=document.querySelectorAll("
        "'[name=\"cf-turnstile-response\"],#cf-chl-widget-response,"
        "textarea.cf-turnstile-response,input.cf-turnstile-response');"
        "for(var i=0;i<els.length;i++){els[i].value=t;n++;}"
        "try{if(typeof window.tsCallback==='function')window.tsCallback(t);}catch(e){}"
        "return 'set:'+n;}catch(e){return 'ERR:'+e;}})(%s)"
    ) % json.dumps(token)


def _env_captcha_cfg() -> Any:
    """route-B 用:从 env 读打码配置(默认关),返回 ScholarConfig-like 轻量对象。"""
    import types
    return types.SimpleNamespace(
        captcha_enabled=_env_true("FTF_CAPTCHA_ENABLED"),
        captcha_provider=(os.environ.get("FTF_CAPTCHA_PROVIDER") or "").strip() or None,
        captcha_key=(os.environ.get("FTF_CAPTCHA_KEY") or "").strip() or None,
    )


def _captcha_solving_enabled() -> bool:
    """route-B Turnstile 打码是否启用:env 三件套齐备才 True(默认关)。"""
    c = _env_captcha_cfg()
    return bool(c.captcha_enabled and c.captcha_provider and c.captcha_key)


def _solve_turnstile_token(site_key: str, page_url: str) -> Optional[str]:
    """gated:仅 env 打码齐备时调 scholar.captcha.solve_turnstile 取 token;默认关→None。绝不抛。"""
    if not _captcha_solving_enabled():
        return None
    solve_turnstile: Any = None
    try:
        from .scholar.captcha import solve_turnstile as _st  # type: ignore
        solve_turnstile = _st
    except Exception:  # noqa: BLE001 - 兜底绝对包路径
        try:
            from fulltext_fetcher.scholar.captcha import solve_turnstile as _st2  # type: ignore
            solve_turnstile = _st2
        except Exception:  # noqa: BLE001
            return None
    try:
        res = solve_turnstile(site_key, page_url, _env_captcha_cfg())
    except Exception:  # noqa: BLE001 - 打码异常一律降级为不可用
        return None
    tok = res.get("token") if isinstance(res, dict) else None
    return tok or None


# ── 三条 Turnstile 攻克路(-146:用户「三条路都配置,后续看哪条最有效」)──────────────────
# 全部独立 env-gated、默认关(default 行为逐字节不变),便于 A/B 对照哪条通过率最高:
#   Path1 免费:nodriver 原生 verify_cf()(浏览器内 opencv 点选 checkbox)—— FTF_ROUTE_B_VERIFY_CF=1
#   Path2 自托管免费:EzSolver / Turnstile-Solver HTTP API(真浏览器出 token)—— FTF_TURNSTILE_SOLVER_URL=<base>
#   Path3 引擎:nodriver → zendriver(修 CDP schema 漂移 / Chrome146 cookie / headless CF)—— FTF_ROUTE_B_ENGINE=zendriver
#   (+ 付费兜底 capsolver/2captcha:FTF_CAPTCHA_ENABLED=1 + PROVIDER + KEY,前已接)
def _route_b_verify_cf_enabled() -> bool:
    """Path1:是否启用 nodriver 原生 verify_cf() 免费点选 Turnstile(env,默认关)。"""
    return _env_true("FTF_ROUTE_B_VERIFY_CF")


def _ezsolver_url() -> Optional[str]:
    """Path2:自托管 Turnstile 求解器(EzSolver/Turnstile-Solver)base URL;未设→None。"""
    u = (os.environ.get("FTF_TURNSTILE_SOLVER_URL") or "").strip()
    return u.rstrip("/") if u else None


def _solve_turnstile_via_ezsolver(site_key: str, page_url: str) -> Optional[str]:
    """Path2:调自托管 Turnstile 求解器取 token。兼容两类常见 OSS API:
    ① 同步:``GET {base}/turnstile?url=&sitekey=`` 直接返回 ``{token|value}``(EzSolver 类);
    ② 异步:先返回 ``{task_id}``,再轮询 ``GET {base}/result?id=`` 到 ``{value|token}``(Theyka Turnstile-Solver 类)。
    纯标准库 urllib,零新依赖;未设 URL / 任何异常 → None(绝不抛、绝不拖垮流水线)。"""
    base = _ezsolver_url()
    if not base or not site_key:
        return None
    import urllib.parse
    import urllib.request

    def _get_json(url: str, timeout: float) -> Dict[str, Any]:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "fulltext_fetcher/route-b"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 本地自托管求解器
            return json.loads(resp.read().decode("utf-8", "ignore") or "{}")

    def _pick_token(d: Dict[str, Any]) -> Optional[str]:
        for k in ("token", "value", "solution", "gRecaptchaResponse"):
            v = d.get(k)
            if isinstance(v, str) and v and v.upper() != "CAPTCHA_NOT_READY":
                return v
        inner = d.get("result") if isinstance(d.get("result"), dict) else None
        return _pick_token(inner) if inner else None

    try:
        q = urllib.parse.urlencode({"url": page_url, "sitekey": site_key})
        first = _get_json(f"{base}/turnstile?{q}", 30.0)
        tok = _pick_token(first)
        if tok:
            return tok
        task_id = first.get("task_id") or first.get("id") or first.get("taskId")
        if not task_id:
            return None
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            time.sleep(3.0)
            r = _get_json(f"{base}/result?id={urllib.parse.quote(str(task_id))}", 20.0)
            tok = _pick_token(r)
            if tok:
                return tok
            if str(r.get("status", "")).lower() in ("failed", "error"):
                return None
        return None
    except Exception:  # noqa: BLE001 - 求解器不可达/超时/坏 JSON → 优雅降级
        return None


def _turnstile_solving_available() -> bool:
    """是否有任一 token 求解通道可用:自托管 EzSolver(Path2) 或 付费 capsolver/2captcha。"""
    return bool(_ezsolver_url() or _captcha_solving_enabled())


def _acquire_turnstile_token(site_key: str, page_url: str) -> Optional[str]:
    """token 求解编排:先 EzSolver 自托管(免费)→ 再 capsolver/2captcha(付费)。默认全关→None。"""
    return _solve_turnstile_via_ezsolver(site_key, page_url) or _solve_turnstile_token(site_key, page_url)


def _route_b_engine() -> str:
    """Path3:route-B 浏览器引擎(env FTF_ROUTE_B_ENGINE);默认 nodriver。仅 nodriver|zendriver 合法。"""
    e = (os.environ.get("FTF_ROUTE_B_ENGINE") or "").strip().lower()
    return e if e in ("nodriver", "zendriver") else "nodriver"


def _import_route_b_engine() -> Tuple[Any, Any, Optional[str]]:
    """按 FTF_ROUTE_B_ENGINE 导入引擎并返回 (module, cdp, name);首选失败回退另一个;都无 → (None,None,None)。

    zendriver 是 nodriver 的活跃分叉,API/CDP 镜像(nd.start / from <mod> import cdp),故可参数化切换。绝不抛。
    """
    pref = _route_b_engine()
    order = [pref] + [x for x in ("nodriver", "zendriver") if x != pref]
    for name in order:
        try:
            mod = __import__(name)
            cdp = __import__(name + ".cdp", fromlist=["cdp"])
            return mod, cdp, name
        except Exception:  # noqa: BLE001 - 未装该引擎 → 试下一个
            continue
    return None, None, None


def _nodriver_capture_fn(headless: bool = False,
                         pdf_url_fallbacks: Optional[List[str]] = None,
                         injection_plan: Any = None) -> Optional[CaptureFn]:
    """返回 nodriver 版『浏览器内抓 PDF 字节』函数;未装 nodriver 则 None。

    引擎 A(nodriver 自带 CDP,零新依赖):开 Network 域监听 → 导航文章页过 CF →
    页内 fetch 抓字节(方法 B/B1,同会话同 JA3,首选)→ 不成再导航到 PDF 直链,由 Network
    域 LoadingFinished → network.get_response_body 抓(方法 A/B2,处理跨域/viewer)。
    首字节 %PDF 兜底校验。导航【前】绝不 enable Fetch 域(真机核查 -154:过盾前 enable 落到会被 CF
    换掉的 session,命令报 'Fetch domain is not enabled',反把方法B卡死);**仅对 JA3 绑定型强 CF 站,
    在过盾(cf_clearance)后、同一 tab 追加方法 C(Fetch RESPONSE 拦截)**——A/B 真机实锤(-152)RSC
    articlepdf 唯有此路能落 %PDF(B1 报 CSP/跨源、Network 域拿不到 body)。**headless 默认【有头】+ 窗口移出
    屏幕不弹窗(-157 纠偏:纯无头过 CF 通过率极低)**:由 _resolve_headless()/_offscreen_args() 统一裁决,
    FTF_HEADLESS=1 可强制纯无头(无显示环境),FTF_BROWSER_SHOW=1 显示窗口排障。

    :param pdf_url_fallbacks: DOI 构造的 PDF 直链兜底(-152:方法A 页内抽链失败时用
        ``publisher_direct.build_static_candidates`` 构造的 articlepdf 直链兜底;RSC 文章页常
        不暴露直链)。空 → 仅靠页内抽链。
    """
    _fallbacks = [u for u in (pdf_url_fallbacks or []) if u]
    _plan = injection_plan
    # Path3(-146):按 FTF_ROUTE_B_ENGINE 选 nodriver / zendriver(API 镜像);都没装 → None(默认关,优雅降级)。
    _eng_mod, _eng_cdp, _eng_name = _import_route_b_engine()
    if _eng_mod is None:
        return None
    import asyncio

    def _capture(article_url: str, timeout: float) -> Tuple[Optional[bytes], str]:
        nd = _eng_mod
        cdp = _eng_cdp

        async def _go() -> Tuple[Optional[bytes], str]:
            _hl = _resolve_headless(headless)
            _start_kw: Dict[str, Any] = {"headless": _hl, "browser_args": [
                "--lang=en-US",
                "--window-size=1600,1000", "--no-first-run", "--no-default-browser-check",
                *_offscreen_args(_hl)]}
            _udd = _route_b_user_data_dir()      # (-165 P4)持久档案 → CF/Turnstile 视作回访人类(默认 None)
            if _udd:
                _start_kw["user_data_dir"] = _udd
            browser = await nd.start(**_start_kw)
            # how: 哪条子路径最终拿到字节——"b1"=页内 fetch(方法B,同源同 JA3),
            # "b2"=导航 PDF 直链后 Network 域抓(方法A,处理跨域/viewer)。供冒烟报 B1/B2(-142)。
            got: Dict[str, Any] = {"data": None, "how": None}
            pdf_rids: set = set()
            try:
                tab = await browser.get("about:blank")
                await tab.send(cdp.network.enable(
                    max_total_buffer_size=120 * 1024 * 1024,
                    max_resource_buffer_size=100 * 1024 * 1024))
                await tab.send(cdp.network.set_cache_disabled(cache_disabled=True))
                # 注:导航【前】绝不启用 cdp.fetch.enable。真机核查(-154)证实:过盾前 / about:blank 上 enable,
                # CF 质询期的跳转会把 target 换掉,之后 fetch.get_response_body / continue_request 抛
                # ProtocolException 'Fetch domain is not enabled [-32000]'(命令落到没 enable 过的新 session),
                # 被 paused 的 PDF 请求永不放行 → 全站 no-pdf-captured。故:主用方法B(页内 fetch)+ 方法A
                # (Network 域 ResponseReceived + LoadingFinished → get_response_body);仅对 JA3 绑定型强 CF 站,
                # 在【过盾(cf_clearance)后、同一 tab】才追加方法C(_enable_fetch_capture 的 Fetch RESPONSE 拦截,
                # 见下方 on_paused)——A/B 真机实锤(-152)RSC 唯有此路能落 %PDF,且过盾后同 tab enable 不再报错。

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
                                got["how"] = "b2"      # Network 域抓(方法A/B2:导航 PDF 直链)
                        except Exception:  # noqa: BLE001
                            pass

                tab.add_handler(cdp.network.ResponseReceived, on_resp)
                tab.add_handler(cdp.network.LoadingFinished, on_finished)

                # ── 方法 C(b2-fetch):RSC/JA3 绑定型强 CF 专用【过盾后】Fetch.enable RESPONSE 兜底 ──
                # A/B 真机实锤(-152):RSC articlepdf 的 B1 页内 fetch 报 TypeError(CSP/跨源)、Network 域
                # get_response_body 也拿不到 body(导航 PDF 触 viewer/下载)→ size=0。唯有在【过盾后】的
                # 同一 tab 上开 Fetch RESPONSE 拦截 + 导航 PDF 直链能落字节(_route_b_b2_152 实证 484KB)。
                # 必须【过盾(cf_clearance)后才 enable、且用同一 tab】——否则命中 -154 的
                # 'Fetch domain is not enabled'(enable 落到 about:blank / 过盾前被 CF 换掉的 session)。
                # 保留上面的 Network 域方法A 不动(-152 口径);此为 JA3 host 上 B1 失败后的额外兜底。
                fetch_cap = {"enabled": False}

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
                                got["how"] = "b2-fetch"    # 过盾后 Fetch.enable RESPONSE 抓(RSC 专用)
                    except Exception:  # noqa: BLE001
                        pass
                    finally:
                        try:  # 必须放行,否则该请求挂起阻塞后续导航
                            await tab.send(cdp.fetch.continue_request(request_id=rid))
                        except Exception:  # noqa: BLE001
                            pass

                async def _enable_fetch_capture() -> bool:
                    """过盾后在【同一 tab】开 Fetch RESPONSE 拦截(RSC/JA3 专用,-152 实证写法)。幂等;失败不外抛。"""
                    if fetch_cap["enabled"]:
                        return True
                    try:
                        tab.add_handler(cdp.fetch.RequestPaused, on_paused)
                        await tab.send(cdp.fetch.enable(patterns=[
                            cdp.fetch.RequestPattern(url_pattern=p,
                                                     request_stage=cdp.fetch.RequestStage.RESPONSE)
                            for p in _PDF_URL_PATTERNS]))
                        fetch_cap["enabled"] = True
                        return True
                    except Exception:  # noqa: BLE001 - enable 失败 → 退回仅 Network 域方法A
                        return False

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

                async def _has_cf_clearance() -> Optional[bool]:
                    """是否已拿到 ``cf_clearance`` cookie——CF 过盾的【权威信号】(-152:勿用
                    cf-chl / challenge-platform 脚本标记判过盾,会假阳)。读不到 cookie(CDP 差异 /
                    异常)→ ``None``,调用方回退用 ``_BLOCK_SIGNALS`` 文案做双保险。绝不抛。

                    读法与 -152 working probe(_route_b_cfwait_152/_route_b_b2_152)对齐:优先
                    ``get_all_cookies``(-152 实证拿到 cf_clearance 的口径,覆盖父域 .rsc.org 等),
                    差异环境退回 ``get_cookies``(当前页)。"""
                    cookies: Any = None
                    for _getter in (getattr(cdp.network, "get_all_cookies", None),
                                    getattr(cdp.network, "get_cookies", None)):
                        if _getter is None:
                            continue
                        try:
                            cookies = await asyncio.wait_for(tab.send(_getter()), timeout=8.0)
                        except Exception:  # noqa: BLE001 (含 TimeoutError / CDP 不支持)
                            cookies = None
                        if cookies:
                            break
                    if cookies is None:
                        return None
                    try:
                        for c in cookies or []:
                            name = getattr(c, "name", None)
                            if name is None and isinstance(c, dict):
                                name = c.get("name")
                            val = getattr(c, "value", None)
                            if val is None and isinstance(c, dict):
                                val = c.get("value")
                            if str(name or "").lower() == "cf_clearance" and val:
                                return True
                        return False
                    except Exception:  # noqa: BLE001
                        return None

                # ① 导航到「文章页」(不是 md5 短链);nodriver 自动过 CF 质询。
                nav_url = article_url
                if _plan:
                    if getattr(_plan, "cookies", None) or getattr(_plan, "user_agent", None):
                        await inject_institutional_session(tab, _plan, cdp=cdp)
                    nav_url = rewrite_url_for_injection_plan(article_url, _plan)
                await _nav(nav_url, min(max(10.0, float(timeout)), 40.0))
                deadline = time.monotonic() + max(5.0, float(timeout))
                triggered = False
                last_blocked = False
                while time.monotonic() < deadline and got["data"] is None:
                    await tab.sleep(0.6)
                    if got["data"] is not None:
                        break
                    # 同时查 title 与 body:CF 新版质询常把文案放在 <title>Just a moment</title>,
                    # 只看 body.innerText 会漏判(见 152 冒烟)。
                    txt = await _eval_str(
                        "((document.title||'')+' '+(document.body?document.body.innerText.slice(0,1500):''))"
                        ".toLowerCase()",
                        t=10.0)
                    cur_href = (await _eval_str("location.href", t=8.0)) or ""
                    if _looks_governor(cur_href, txt):
                        soft = _looks_governor_softblock(cur_href, txt)
                        clicked = await _eval_str(
                            "(function(){var as=Array.from(document.querySelectorAll('a,button'));"
                            "for(var i=0;i<as.length;i++){var t=(as[i].innerText||'').toLowerCase();"
                            "if(t.indexOf('take me to my content')>=0||t.indexOf('my content')>=0)"
                            "{as[i].click();return 'clicked';}}return '';})()",
                            t=8.0)
                        if clicked:
                            await tab.sleep(3.0)
                            continue
                        _host_register_governor(cur_href or article_url, soft=soft)
                        note = "blocked:rsc-governor-softblock" if soft else "blocked:rsc-governor"
                        return None, note
                    blocked_by_text = any(s in txt for s in _BLOCK_SIGNALS)
                    # (-146 Path1)免费:nodriver/zendriver 原生 verify_cf() 浏览器内点选 Turnstile checkbox。
                    # env FTF_ROUTE_B_VERIFY_CF=1 才走;默认关→短路。真浏览器多数能自动过,此为交互式 checkbox 兜底。
                    if blocked_by_text and _route_b_verify_cf_enabled() and not got.get("vcf_tried"):
                        got["vcf_tried"] = True
                        for _m in ("verify_cf", "cf_verify"):
                            _vfn = getattr(tab, _m, None)
                            if _vfn is not None:
                                try:
                                    await asyncio.wait_for(_vfn(), timeout=20.0)
                                except Exception:  # noqa: BLE001 - 该引擎版本无此法/超时 → 忽略
                                    pass
                                await tab.sleep(2.0)
                                break
                        continue
                    # (-146 Path2/付费)token 求解:抓 HTML 找 Turnstile sitekey → EzSolver(自托管免费)
                    # → capsolver/2captcha(付费)出 token → 注入页面 → 下一轮重判。gated:任一通道可用才走;
                    # 默认全关→短路,route-B 行为逐字节不变。RSC governor 坏码走 _looks_governor(不到这),绝不打码。
                    if blocked_by_text and _turnstile_solving_available() and not got.get("ts_tried"):
                        got["ts_tried"] = True
                        try:
                            _full_html = await asyncio.wait_for(tab.get_content(), timeout=8.0)
                        except Exception:  # noqa: BLE001
                            _full_html = ""
                        _sk = _extract_turnstile_sitekey(_full_html)
                        if _sk:
                            _cur = (await _eval_str("location.href", t=6.0)) or article_url
                            _tok = _acquire_turnstile_token(_sk, _cur)
                            if _tok:
                                await _eval_str(_inject_turnstile_token_js(_tok), t=8.0)
                                await tab.sleep(3.0)
                                continue
                    has_clear = await _has_cf_clearance()
                    # RSC 等走 CF→SSO(/connect/authorize)授权回跳:cf_clearance 可能在【仍停在 SSO 中转页】
                    # 时就置上,此时"偷跑"会在 SSO 页上找不到 PDF。故 JA3 站额外要求 href 已回落到非 SSO 中转页
                    # (-141 真机核实:d5ra08493h 走 pubs.rsc.org→sso.rsc.org/connect/authorize→回 pubs.rsc.org)。
                    cur_href = (await _eval_str("location.href", t=8.0)) or ""
                    on_interstitial = any(s in cur_href.lower()
                                          for s in ("/connect/authorize", "sso.", "/login", "/idp"))
                    # 过盾判定:
                    #   · JA3 绑定型强 CF 站 → 【AND 判据】(-152/-146 真机核实):必须 cf_clearance 已置
                    #     【且】质询文案(title+body)已消失【且】已离开 SSO 中转页才算过盾。仅 cookie 命中
                    #     【不算】——cf_clearance 可能在跳回真文章页前一瞬就置上,此时"偷跑"会落到尚未渲染的
                    #     质询/SSO 页、找不到 PDF。cookie 读不到(None)时退回仅文案(双保险,不因读不到而永久卡死)。
                    #   · 非 JA3 host(一般不会走这条重路径)→ 沿用文案信号,cookie 命中可提前放行。
                    if is_ja3_bound_cf_host(article_url):
                        last_blocked = (blocked_by_text if has_clear is None else (
                            blocked_by_text or has_clear is not True)) or on_interstitial
                    else:
                        last_blocked = False if has_clear is True else blocked_by_text
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
                    if not pdf_url and _fallbacks:
                        # 页面没暴露 PDF 直链(RSC articlepdf 常见)→ 用 DOI 构造的直链兜底(-152)。
                        pdf_url = _fallbacks[0]
                    if pdf_url and _plan:
                        pdf_url = rewrite_url_for_injection_plan(pdf_url, _plan)
                    if not pdf_url:
                        continue
                    triggered = True
                    # 方法 B(B1):文章页上下文内 fetch(同 cookie + JA3),首选(同源最稳)。
                    data_url = await _eval_str(_inpage_fetch_pdf_js(pdf_url), await_promise=True,
                                               t=min(max(10.0, float(timeout)), 40.0))
                    data_b = _data_url_to_pdf_bytes(data_url)
                    if _is_pdf_bytes(data_b):
                        got["data"] = data_b
                        got["how"] = "b1"              # 页内 fetch(方法B/B1:同源同 JA3)
                        break
                    # B1(页内 fetch)失败 → 【过盾后】在同一 tab 开 Fetch RESPONSE 拦截(方法C/b2-fetch)再导航。
                    # 触发放宽(-149 MDPI 发现 + -141):不再仅限 is_ja3_bound_cf_host——凡 B1 失败即开,覆盖
                    # 『过盾后 PDF 走跨域 CDN attachment(MDPI /pdf?version=)/ inline viewer(RSC silverchair)』
                    # 同类站。仍是【过盾后·同 tab】enable,不违反"过盾期绝不开拦截"铁律;非 route-B 站不受影响
                    # (本函数仅 render_download_pdf_bytes 的 opt-in 路径可达)。
                    await _enable_fetch_capture()
                    # (-165 P2) RSC:先 articlelanding 预热,勿直怼 ArticlePdfHandler。
                    if _is_rsc_host(pdf_url) and "/articlepdf/" in pdf_url.lower():
                        landing = _rsc_articlepdf_to_landing(pdf_url)
                        if landing:
                            await _nav(landing, 20.0)
                            await tab.sleep(random.uniform(2.0, 5.0))
                            try:
                                html = await asyncio.wait_for(tab.get_content(), timeout=10.0)
                            except Exception:  # noqa: BLE001
                                html = ""
                            if _looks_governor(landing, html or ""):
                                _host_register_governor(landing, soft=False)
                                return None, "blocked:rsc-governor"
                            # 预热页上再抽一次 PDF 链(可能比 fallback 更稳)
                            cur2 = (await _eval_str("location.href", t=10.0)) or landing
                            links2 = extract_pdf_links(html or "", cur2)
                            if links2:
                                pdf_url = links2[0]
                    # 方法 A/C:导航到 PDF 直链;Network 域(on_finished)与(JA3 时)Fetch 域(on_paused)双抓。
                    await _nav(pdf_url, 15.0)
                    # 方法 D(-141 实证,RSC 签名 CDN 专用):RSC 的 articlepdf 会 302 到【签名 CDN 直链】
                    # (rscj.silverchair-cdn.com/...pdf?Expires=)并被 Chrome 内联 viewer 打开
                    # (contentType=application/pdf)——既不触发下载、get_response_body(Network 域与 Fetch 域)
                    # 也读不到 body → 方法 A/B/C 全 0 字节。但导航后 tab 已【同源落在该 CDN .pdf 页】,故在其
                    # 上下文内 fetch(location.href)(同源 + 带 cookie)可直接拿字节(-141 真机实证 d5ra08493h
                    # 484KB %PDF-1.6,与 -152 记录吻合)。轮询等页面 302 落定到 PDF,期间 A/C 拦截器并行兜底。
                    sub_deadline = time.monotonic() + max(5.0, float(timeout) / 2)
                    d_tried: set = set()
                    while time.monotonic() < sub_deadline and got["data"] is None:
                        cur_pdf = await _eval_str("location.href", t=8.0)
                        ctype = await _eval_str("document.contentType||''", t=6.0)
                        if (cur_pdf and cur_pdf.startswith("http") and cur_pdf not in d_tried
                                and ("application/pdf" in (ctype or "") or ".pdf" in cur_pdf.lower())):
                            d_tried.add(cur_pdf)
                            durl = await _eval_str(_inpage_fetch_pdf_js(cur_pdf), await_promise=True,
                                                   t=min(max(10.0, float(timeout)), 45.0))
                            d_b = _data_url_to_pdf_bytes(durl)
                            if _is_pdf_bytes(d_b):
                                got["data"] = d_b
                                got["how"] = "b2-viewerfetch"  # 落 CDN viewer 页后页内 fetch(RSC 签名CDN,-141)
                                break
                        await tab.sleep(0.6)
                if got["data"] is not None:
                    return got["data"], ("ok:%s" % got["how"] if got.get("how") else "ok")
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
    pdf_url_fallbacks: Optional[List[str]] = None,
    injection_plan: Any = None,
    lock_path: Optional[str] = None,
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
    :param headless: (已被全局开关覆盖)实际由 ``FTF_HEADLESS`` 裁决:默认无头(不弹窗),``FTF_HEADLESS=0`` 才有头。
    :param pdf_url_fallbacks: DOI 构造的 PDF 直链兜底(-152:方法A 页内抽链失败时用);空 → 仅靠页内抽链。
    :param injection_plan: A5 ``RouteBInjectionPlan``;导航前 CDP 注入 Cookie + EZproxy 改写(同 tab 同 JA3)。
    :param lock_path: 单头串行护栏的跨进程锁文件路径(如 ``out/.route_b.lock``);None → 仅进程内信号量。
    :param _capture_fn: 注入的抓字节函数(测试用);生产不传,自动用 nodriver 引擎。
    """
    # ① 合规守卫最先执行:即便注入了抓字节函数,也绝不渲染/抓取 Scholar。
    if _is_scholar_host(article_url):
        return {"available": True,
                "error": "refused: this module never renders Google Scholar / search pages",
                "pdf_bytes": None}
    # ② 选引擎;无引擎即默认关闭(在限流/抓取之前返回)。
    cap = _capture_fn or _nodriver_capture_fn(
        headless=headless, pdf_url_fallbacks=pdf_url_fallbacks, injection_plan=injection_plan)
    if cap is None:
        return {"available": False, "reason": "need nodriver", "pdf_bytes": None}
    # ③ 强限流 + 单头串行护栏(concurrency=1:全组共一机单头浏览器)后再抓。
    #    注入 mock ``_capture_fn``(selftest/测试路径)时【跳过真实等待】:``_throttle`` 与
    #    ``_host_capture_gate``(RSC per-host 冷却/限速,对 ``pubs.rsc.org`` 每次 ``time.sleep`` 30~60s)
    #    都是「真起浏览器抓取」才有意义的现实限速,对 mock 毫无意义;离线自检多次打同一 rsc host 会
    #    累计 sleep 触顶 ``run_all_selftests`` 的 180s PER_CHECK_TIMEOUT(实测二次调用即 sleep ~56s、
    #    5 次 rsc mock 调用 → exit=124 TIMEOUT)。**生产(不传 ``_capture_fn``)行为完全不变**。
    if _capture_fn is None:
        _throttle(min_interval)
        gate = _host_capture_gate(article_url)
        if gate:
            return {"available": True, "error": gate, "pdf_bytes": None}
    try:
        with _single_head_guard(lock_path):
            data, note = cap(article_url, timeout)
    except Exception as exc:  # noqa: BLE001 - 抓取异常优雅降级,绝不外抛
        return {"available": True, "error": f"capture failed: {exc}", "pdf_bytes": None}
    if isinstance(note, str) and (note.startswith("blocked:") or note.startswith("deferred:")):
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
    # 0) RSC governor 信号与 landing 转换(-165)
    assert _looks_governor("https://pubs.rsc.org/crawlprevention/governor", "")
    assert _looks_governor("", "invalid domain for site key")
    assert not _looks_governor("https://pubs.rsc.org/en/content/articlelanding/2011/GC/C1GC15503B", "abstract")
    landing = _rsc_articlepdf_to_landing(
        "https://pubs.rsc.org/en/content/articlepdf/2011/GC/C1GC15503B")
    assert landing == "https://pubs.rsc.org/en/content/articlelanding/2011/GC/C1GC15503B", landing

    # 0c) CF Turnstile 硬解题助手(-146):sitekey 抽取 / token 注入 JS / gated 默认关(全离线)
    assert _extract_turnstile_sitekey(
        '<div class="cf-turnstile" data-sitekey="0x4AAAAAAABkMYinukE8nzY"></div>'
    ) == "0x4AAAAAAABkMYinukE8nzY"
    assert _extract_turnstile_sitekey('turnstile.render("#x",{sitekey:"0x4AAAAAAABxxxx"})') \
        == "0x4AAAAAAABxxxx"
    # reCAPTCHA(6L 前缀、无 cf-turnstile 标记)不应被误判为 Turnstile
    assert _extract_turnstile_sitekey(
        '<div class="g-recaptcha" data-sitekey="6LcAAAAAAAAAAAAAAAAA"></div>') is None
    assert _extract_turnstile_sitekey("") is None
    assert _extract_turnstile_sitekey("<div>no challenge here</div>") is None
    # cf-turnstile 上下文里的测试 key(非 0x 前缀)可回退命中
    assert _extract_turnstile_sitekey(
        '<div class="cf-turnstile" data-sitekey="1x00000000000000000000AA"></div>'
    ) == "1x00000000000000000000AA"
    _tsjs = _inject_turnstile_token_js("TOK_abc123")
    assert "TOK_abc123" in _tsjs and _tsjs.startswith("(function"), _tsjs
    # gated 默认关:env 未设 → 不启用、solve 短路为 None(不导库、不联网)
    for _k in ("FTF_CAPTCHA_ENABLED", "FTF_CAPTCHA_PROVIDER", "FTF_CAPTCHA_KEY"):
        os.environ.pop(_k, None)
    assert _captcha_solving_enabled() is False
    assert _env_captcha_cfg().captcha_enabled is False
    assert _solve_turnstile_token("0xkey", "https://pubs.rsc.org/a") is None
    # env 齐备但缺打码库时:启用判定 True,但 solve 优雅降级为 None(need <dep>,不联网)
    import importlib.util as _ilu
    if _ilu.find_spec("capsolver") is None:
        os.environ["FTF_CAPTCHA_ENABLED"] = "1"
        os.environ["FTF_CAPTCHA_PROVIDER"] = "capsolver"
        os.environ["FTF_CAPTCHA_KEY"] = "K"
        try:
            assert _captcha_solving_enabled() is True
            assert _solve_turnstile_token("0xkey", "https://pubs.rsc.org/a") is None
        finally:
            for _k in ("FTF_CAPTCHA_ENABLED", "FTF_CAPTCHA_PROVIDER", "FTF_CAPTCHA_KEY"):
                os.environ.pop(_k, None)
    # P4:持久档案目录 env 未设 → None(默认行为不变)
    _saved_udd = os.environ.pop("FTF_ROUTE_B_USER_DATA_DIR", None)
    try:
        assert _route_b_user_data_dir() is None
        os.environ["FTF_ROUTE_B_USER_DATA_DIR"] = "/tmp/ftf_profile"
        assert _route_b_user_data_dir() == "/tmp/ftf_profile"
    finally:
        os.environ.pop("FTF_ROUTE_B_USER_DATA_DIR", None)
        if _saved_udd is not None:
            os.environ["FTF_ROUTE_B_USER_DATA_DIR"] = _saved_udd

    # 0d) 三条 Turnstile 攻克路(-146)gating(全离线、默认关):verify_cf / EzSolver / zendriver
    _saved_env3 = {k: os.environ.get(k) for k in (
        "FTF_ROUTE_B_VERIFY_CF", "FTF_TURNSTILE_SOLVER_URL", "FTF_ROUTE_B_ENGINE",
        "FTF_CAPTCHA_ENABLED", "FTF_CAPTCHA_PROVIDER", "FTF_CAPTCHA_KEY")}
    for _k in _saved_env3:
        os.environ.pop(_k, None)
    try:
        # Path1 verify_cf 开关(默认关)
        assert _route_b_verify_cf_enabled() is False
        os.environ["FTF_ROUTE_B_VERIFY_CF"] = "1"
        assert _route_b_verify_cf_enabled() is True
        os.environ.pop("FTF_ROUTE_B_VERIFY_CF", None)
        # Path2 EzSolver URL 解析 + 求解通道可用性(默认关→短路,不联网)
        assert _ezsolver_url() is None
        assert _turnstile_solving_available() is False
        assert _acquire_turnstile_token("0xk", "https://pubs.rsc.org/a") is None
        os.environ["FTF_TURNSTILE_SOLVER_URL"] = "http://localhost:5033/"
        assert _ezsolver_url() == "http://localhost:5033"
        assert _turnstile_solving_available() is True
        os.environ.pop("FTF_TURNSTILE_SOLVER_URL", None)
        # Path3 引擎选择(默认 nodriver;非法值回退)+ 导入不抛、名字合法
        assert _route_b_engine() == "nodriver"
        os.environ["FTF_ROUTE_B_ENGINE"] = "zendriver"
        assert _route_b_engine() == "zendriver"
        os.environ["FTF_ROUTE_B_ENGINE"] = "garbage"
        assert _route_b_engine() == "nodriver"
        os.environ.pop("FTF_ROUTE_B_ENGINE", None)
        _em, _ec, _en = _import_route_b_engine()
        assert _en in (None, "nodriver", "zendriver"), _en
    finally:
        for _k, _v in _saved_env3.items():
            if _v is None:
                os.environ.pop(_k, None)
            else:
                os.environ[_k] = _v

    # 0b) A5 route-B 注入:ezproxy 改写 + inject hook(离线 mock tab)
    from fulltext_fetcher.institutional.route_b_bridge import BrowserCookieSpec, RouteBInjectionPlan
    from urllib.parse import quote

    _sd = "https://www.sciencedirect.com/science/article/pii/X/pdfft"
    _pfx = "https://login.ezproxy.uni.edu/login?url="
    plan = RouteBInjectionPlan(
        cookies=[BrowserCookieSpec("ezproxy", "TOK", "ezproxy.uni.edu")],
        ezproxy_prefix=_pfx,
        rewrite_target_host="www.sciencedirect.com",
        user_agent="Mozilla/5.0 inject-test",
    )
    assert rewrite_url_for_injection_plan(_sd, plan) == _pfx + quote(_sd, safe="")
    assert rewrite_url_for_injection_plan(_sd, RouteBInjectionPlan()) == _sd

    import asyncio

    class _Sent:
        def __init__(self):
            self.calls: List[Any] = []

    class _MockTab:
        def __init__(self):
            self.sent = _Sent()

        async def send(self, cmd):
            self.sent.calls.append(cmd)

    class _MockCdp:
        class network:
            @staticmethod
            def set_cookie(**kw):
                return ("set_cookie", kw)

        class emulation:
            @staticmethod
            def set_user_agent_override(**kw):
                return ("set_ua", kw)

    async def _run_inject():
        tab = _MockTab()
        await inject_institutional_session(tab, plan, cdp=_MockCdp())
        assert len(tab.sent.calls) == 2
        assert tab.sent.calls[0][0] == "set_cookie"
        assert tab.sent.calls[0][1]["name"] == "ezproxy"
        assert tab.sent.calls[1][0] == "set_ua"

    asyncio.run(_run_inject())

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
        _g["_nodriver_capture_fn"] = lambda headless=False, pdf_url_fallbacks=None, injection_plan=None: None
        off = render_download_pdf_bytes("https://pubs.rsc.org/a", min_interval=0.0)
        assert off == {"available": False, "reason": "need nodriver", "pdf_bytes": None}, off
    finally:
        _g["_nodriver_capture_fn"] = real_factory

    # 12) 单头串行护栏(concurrency=1):进程内信号量顺序 acquire/release 不死锁;
    #     文件锁在给定路径【持锁期间存在、释放后删除】;陈旧锁(mtime 超阈)自动接管。
    import tempfile as _tmp
    with _single_head_guard(None):
        pass                                               # lock_path=None → 仅信号量,零文件副作用
    with _tmp.TemporaryDirectory() as _d:
        _lp = os.path.join(_d, ".route_b.lock")
        with _single_head_guard(_lp):
            assert os.path.exists(_lp), "持锁期间应存在锁文件"
        assert not os.path.exists(_lp), "释放后应删除锁文件"
        with open(_lp, "w", encoding="ascii") as _fh:
            _fh.write("999999")                            # 预置陈旧锁(伪 pid)
        _old = time.time() - (_SINGLE_HEAD_STALE_SEC + 60)
        os.utime(_lp, (_old, _old))
        with _single_head_guard(_lp):                      # 应接管陈旧锁并成功持有
            assert os.path.exists(_lp)
        assert not os.path.exists(_lp)
    # 13) 直链兜底注入:pdf_url_fallbacks 经工厂进入闭包(无 nodriver 时工厂返回 None,仅验证不抛)
    _ = _nodriver_capture_fn(pdf_url_fallbacks=["https://pubs.rsc.org/en/content/articlepdf/x"])

    # 13b) 离线快速判定回归(防「selftest 空等 RSC per-host 限速」再犯):
    #   ① 注入 mock _capture_fn 时,render_download_pdf_bytes 【跳过 _host_capture_gate】——多次打
    #      同一 rsc host 也【绝不 sleep】(此前 5 次 rsc mock 调用累计 sleep >180s → exit=124 TIMEOUT)。
    #   ② _host_capture_gate 本身对非 rsc host 秒回 None;rsc host 预置冷却 → 秒回 deferred(不 sleep)。
    _t0 = time.monotonic()
    _f_pdf = lambda u, t: (b"%PDF-1.7 x", "ok")  # noqa: E731 - 测试内联 mock capture
    for _ in range(5):  # 复现自检里对同一 rsc host 的多次调用;有 gate skip 则总耗 ~0s
        _r = render_download_pdf_bytes("https://pubs.rsc.org/a", _capture_fn=_f_pdf, min_interval=0.0)
        assert _r["available"] and _r["pdf_bytes"][:4] == b"%PDF", _r
    assert (time.monotonic() - _t0) < 5.0, "mock 路径必须跳过 RSC per-host 限速、绝不 sleep"
    assert _host_capture_gate("https://www.mdpi.com/x") is None            # 非 rsc → 立即放行
    _HOST_STATE["pubs.rsc.org"] = {"cooldown_until": time.monotonic() + 9999.0}
    try:
        assert _host_capture_gate("https://pubs.rsc.org/en/content/x") == "deferred:rsc-governor-cooldown"
    finally:
        _HOST_STATE.pop("pubs.rsc.org", None)                             # 清理,避免污染后续/生产状态

    # 14) item6 门控在线冒烟:默认(未设 RUN_ROUTE_B_SMOKE)必须 SKIP、零副作用、不联网、不抛
    _saved_smoke = os.environ.pop("RUN_ROUTE_B_SMOKE", None)
    try:
        assert _route_b_smoke_enabled() is False
        _sm = run_route_b_smoke()
        assert _sm.get("skipped") is True and _sm.get("results") == [], _sm
    finally:
        if _saved_smoke is not None:
            os.environ["RUN_ROUTE_B_SMOKE"] = _saved_smoke

    print("RENDER_BYTES_OK")


# ── item6:route-B 门控【在线】冒烟(默认 SKIP)──────────────────────────────
# 离线 selftest 证不了真 CF/JA3 路径(RENDER_BYTES_OK 全走注入 mock)。这里给一条【门控】在线冒烟:
# 仅当环境变量 RUN_ROUTE_B_SMOKE ∈ {1,true,yes} 时才真起浏览器过 CF 抓字节,否则一律 SKIP(零副作用)。
# 样本(与 -152 真机取证一致):ACS-OA(B1 页内 fetch 已证 13.7MB)+ RSC(Network 域拓 articlepdf,-152 待证)。
# 直链由 publisher_direct.build_static_candidates 按 DOI 构造(与生产同源)。仅供有权访问的 OA 内容取证。
_ROUTE_B_SMOKE_SAMPLES: Tuple[Tuple[str, str], ...] = (
    ("acs-oa", "10.1021/acsomega.6c04195"),     # ACS Omega 金 OA:B1 页内 fetch 已证
    ("rsc", "10.1039/d5ra08493h"),              # RSC Advances 金 OA:Network 域方法A 待证(-152 A/B)
)


def _route_b_smoke_enabled() -> bool:
    return os.environ.get("RUN_ROUTE_B_SMOKE", "").strip().lower() in ("1", "true", "yes")


def run_route_b_smoke(headless: bool = False, timeout: float = DEFAULT_BYTES_TIMEOUT) -> Dict[str, Any]:
    """item6:route-B 在线冒烟(需 RUN_ROUTE_B_SMOKE=1 + nodriver + 有头显示环境)。

    对每个样本 DOI 用 ``publisher_direct.build_static_candidates`` 构直链、``render_download_pdf_bytes``
    浏览器内抓字节,断言首字节 %PDF。返回 ``{"skipped":bool, "results":[{sample,doi,url,ok,size,error}...]}``。
    绝不抛;门控关闭 → ``{"skipped": True}``。**内容 QC 由 download 层负责**,此处只验真 CF/JA3 字节可达性。
    """
    if not _route_b_smoke_enabled():
        return {"skipped": True, "reason": "RUN_ROUTE_B_SMOKE!=1", "results": []}
    try:
        from .sources.publisher_direct import build_static_candidates
    except Exception as exc:  # noqa: BLE001
        return {"skipped": True, "reason": f"need publisher_direct: {exc}", "results": []}
    results: List[Dict[str, Any]] = []
    for sample, doi in _ROUTE_B_SMOKE_SAMPLES:
        cands = build_static_candidates(doi)
        url = cands[0].url if cands else ""
        if not url:
            results.append({"sample": sample, "doi": doi, "url": "", "ok": False,
                            "error": "no-static-candidate"})
            continue
        res = render_download_pdf_bytes(url, timeout=timeout, headless=headless,
                                        pdf_url_fallbacks=[c.url for c in cands])
        data = res.get("pdf_bytes")
        results.append({"sample": sample, "doi": doi, "url": url,
                        "ok": _is_pdf_bytes(data), "size": (len(data) if data else 0),
                        "error": res.get("error") or res.get("reason")})
    return {"skipped": False, "results": results}


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
                    help="(默认已无头不弹窗)配合 --capture-bytes;要有头调 CF 通过率请设环境变量 FTF_HEADLESS=0")
    ap.add_argument("--save", metavar="PATH", help="配合 --capture-bytes:把抓到的 PDF 落盘到此路径")
    ap.add_argument("--route-b-smoke", action="store_true",
                    help="item6:route-B 在线冒烟(ACS-OA + RSC 样本);需 RUN_ROUTE_B_SMOKE=1 + nodriver + 显示,否则 SKIP")
    ap.add_argument("--selftest", action="store_true", help="不联网/无浏览器自检并退出")
    args = ap.parse_args(argv)

    if args.route_b_smoke:
        res = run_route_b_smoke(headless=args.headless)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        if res.get("skipped"):
            print("[SKIP] route-B 在线冒烟未启用:设 RUN_ROUTE_B_SMOKE=1 且装 nodriver + 有头显示环境后重跑。",
                  file=sys.stderr)
            return 0
        return 0 if all(r.get("ok") for r in res.get("results", [])) else 1

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
