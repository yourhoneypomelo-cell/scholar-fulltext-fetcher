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

    print("RENDER_OK")
    return 0


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
    ap.add_argument("--selftest", action="store_true", help="不联网/无浏览器自检并退出")
    args = ap.parse_args(argv)

    if args.selftest or not args.url:
        return _selftest()

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
