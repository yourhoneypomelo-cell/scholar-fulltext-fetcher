"""Docker-free, FlareSolverr-compatible Cloudflare solver backed by nodriver.

Why this exists
---------------
`fulltext_fetcher/download.py` 的 `_flaresolverr_fallback` 在遇到 Cloudflare "Just a
moment" JS 质询时,会 POST 到一个 FlareSolverr `/v1` 端点求解,拿回 **cf_clearance
cookie + 求解时的 User-Agent**,再用 curl_cffi 带着它们重下 PDF(HTML 正文并不使用)。
官方 FlareSolverr 只发行 Docker 镜像;本机无 Docker/WSL,且其源码钉死
undetected-chromedriver 3.5.5,驱动不了本机 Chrome 133。

本脚本用 **nodriver**(undetected-chromedriver 的现代继任者,直连 CDP、无需单独
chromedriver、天然反检测、兼容最新 Chrome)实现一个**最小 FlareSolverr 兼容端点**:
只需实现 `cmd:"request.get"`,返回 `{status:"ok", solution:{response, cookies,
userAgent, url, status}}`,即可让 download.py 的 FlareSolverr 分支正常工作。

用法
----
    python tools/flaresolverr_nodriver.py                 # 默认 127.0.0.1:8191(有头)
    python tools/flaresolverr_nodriver.py --headless      # 无头(CF 通过率略低)
    python tools/flaresolverr_nodriver.py --port 8191

然后让下载流水线指向它:
    $env:FLARESOLVERR_URL = "http://127.0.0.1:8191/v1"
    python -m fulltext_fetcher -f recover_b4_cf_input.txt -o out/recover_b4_cf --email ...

健康检查:GET http://127.0.0.1:8191/  → "FlareSolverr is ready!"

设计要点
--------
* 单一常驻浏览器 + 单一主标签页,所有请求经一个后台 asyncio 事件循环串行求解
  (asyncio.Lock),避免多标签互相干扰。
* **按 origin 缓存 cf_clearance**(默认 20 分钟):80 条 DOI 往往只落在 4~5 个出版商域,
  缓存后同域只需真解一次,其余瞬时命中——大幅提速。
* Windows 必须用 ProactorEventLoop(nodriver 以子进程方式拉起 Chrome,
  SelectorEventLoop 不支持子进程)。
* 任何异常都优雅降级为 `{status:"error"}`,绝不让端点崩溃拖垮下载主流程。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import nodriver as nd
from nodriver import cdp

_CF_COOKIE_NAMES = ("cf_clearance",)
_CHALLENGE_MARKERS = ("just a moment", "checking your browser",
                      "enable javascript and cookies", "cf-chl", "challenge-platform")


def _origin(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url
    return f"{parts.scheme}://{parts.netloc}"


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _cookie_for_host(cookie_domain: str, host: str) -> bool:
    d = (cookie_domain or "").lstrip(".").lower()
    if not d or not host:
        return False
    return host == d or host.endswith("." + d) or d.endswith("." + host)


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _resolve_headless(default: bool) -> bool:
    """CF 解题器无头开关:环境变量 FTF_HEADLESS 优先于调用方默认值。
    FTF_HEADLESS=1/true/yes/on → 强制无头;=0/false/no/off → 强制有头;未设 → 用 default(有头)。

    **本解题器默认【有头】而非无头**:真机实测 pubs.aip.org 等 managed-challenge 站【无头过 CF
    通过率极低】(本机 headless 81.5s 都拿不到 cf_clearance,有头 ~8s 即过)——解题器的本职就是过 CF,
    无头会直接废掉主功能。为"不弹窗打扰办公"又不牺牲 CF 通过率:默认【有头 + 窗口移出屏幕】(见
    _offscreen_args),而非无头。真要无头(如服务器/xvfb)可显式 FTF_HEADLESS=1。"""
    v = os.environ.get("FTF_HEADLESS", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def _offscreen_args(headless: bool) -> List[str]:
    """有头模式下【默认】把窗口移出可视区域:不弹窗打扰办公,又保留有头的 CF 通过率(优于无头)。
    要显示窗口排障/调 CF 时设 FTF_BROWSER_SHOW=1/true/yes/on。无头本就无窗口,返回空。"""
    if headless or _env_true("FTF_BROWSER_SHOW"):
        return []
    return ["--window-position=-2400,-2400"]


class Solver:
    """常驻 nodriver 浏览器 + 后台事件循环;对外暴露线程安全的 solve()。"""

    def __init__(self, headless: bool, cache_ttl: float, page_wait: float) -> None:
        self.headless = headless
        self.cache_ttl = cache_ttl
        self.page_wait = page_wait
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._browser: Optional[nd.Browser] = None
        self._tab = None
        self._lock: Optional[asyncio.Lock] = None
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._ready = threading.Event()
        self._start_err: Optional[str] = None

    def start(self) -> None:
        t = threading.Thread(target=self._run_loop, name="nodriver-loop", daemon=True)
        t.start()
        self._ready.wait(timeout=120)
        if self._start_err:
            raise RuntimeError(self._start_err)
        if not self._browser:
            raise RuntimeError("浏览器启动超时(120s)")

    def _run_loop(self) -> None:
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()  # nodriver 需子进程支持
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._boot())
        except Exception as e:  # noqa: BLE001
            self._start_err = f"{type(e).__name__}: {e}"
            self._ready.set()
            return
        self._ready.set()
        loop.run_forever()

    async def _boot(self) -> None:
        self._lock = asyncio.Lock()
        _hl = _resolve_headless(self.headless)
        self._browser = await nd.start(headless=_hl, browser_args=[
            "--lang=en-US", "--disable-blink-features=AutomationControlled",
            "--window-size=1400,1000", "--no-first-run", "--no-default-browser-check",
            *_offscreen_args(_hl)])
        self._tab = await self._browser.get("about:blank")

    def solve(self, url: str, max_ms: int) -> Dict[str, Any]:
        if self._loop is None:
            return {"status": "error", "message": "loop not running"}
        fut = asyncio.run_coroutine_threadsafe(self._solve(url, max_ms), self._loop)
        try:
            return fut.result(timeout=max_ms / 1000.0 + 30.0)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"{type(e).__name__}: {e}"}

    async def _get_cookies(self, host: str) -> List[Dict[str, Any]]:
        raw: List[Any] = []
        try:
            raw = await self._tab.send(cdp.network.get_all_cookies())
        except Exception:  # noqa: BLE001
            try:
                raw = await self._browser.cookies.get_all()
            except Exception:  # noqa: BLE001
                raw = []
        out: List[Dict[str, Any]] = []
        for c in raw or []:
            domain = getattr(c, "domain", "") or ""
            if host and not _cookie_for_host(domain, host):
                continue
            out.append({
                "name": getattr(c, "name", ""),
                "value": getattr(c, "value", ""),
                "domain": domain,
                "path": getattr(c, "path", "/") or "/",
                "expires": getattr(c, "expires", -1),
                "httpOnly": bool(getattr(c, "http_only", False)),
                "secure": bool(getattr(c, "secure", False)),
            })
        return out

    @staticmethod
    def _has_cf(cookies: List[Dict[str, Any]]) -> bool:
        return any(c.get("name") in _CF_COOKIE_NAMES and c.get("value") for c in cookies)

    async def _solve(self, url: str, max_ms: int) -> Dict[str, Any]:
        assert self._lock is not None
        async with self._lock:
            origin = _origin(url)
            host = _host(url)
            now = time.time()
            cached = self._cache.get(origin)
            if cached and now - cached[0] < self.cache_ttl and self._has_cf(cached[1]["cookies"]):
                sol = dict(cached[1])
                sol["url"] = url
                print(f"[solve] CACHE hit origin={origin} "
                      f"cookies={len(sol['cookies'])}", flush=True)
                return {"status": "ok", "message": "cached", "solution": sol}

            t0 = time.time()
            try:
                await self._tab.get(url)
            except Exception as e:  # noqa: BLE001
                return {"status": "error", "message": f"navigate failed: {e}"}

            deadline = t0 + max(max_ms / 1000.0 * 0.9, 8.0)
            cookies: List[Dict[str, Any]] = []
            html = ""
            await self._tab.sleep(min(self.page_wait, 4.0))
            while time.time() < deadline:
                try:
                    html = (await self._tab.get_content()) or ""
                except Exception:  # noqa: BLE001
                    html = ""
                cookies = await self._get_cookies(host)
                low = html.lower()
                challenged = any(m in low for m in _CHALLENGE_MARKERS)
                if self._has_cf(cookies) and not challenged:
                    break
                if not challenged and len(html) > 2000 and time.time() - t0 > self.page_wait:
                    break  # 无 CF 质询的普通页也可返回(可能本就不需 cf_clearance)
                await self._tab.sleep(2.0)

            try:
                ua = await self._tab.evaluate("navigator.userAgent", return_by_value=True)
            except Exception:  # noqa: BLE001
                ua = None
            try:
                final_url = self._tab.url or url
            except Exception:  # noqa: BLE001
                final_url = url

            sol = {
                "url": final_url,
                "status": 200,
                "response": html or "<html></html>",
                "cookies": cookies,
                "userAgent": ua or "",
                "headers": {},
            }
            has_cf = self._has_cf(cookies)
            if has_cf:
                self._cache[origin] = (time.time(), dict(sol))
            print(f"[solve] origin={origin} cf_clearance={'YES' if has_cf else 'no'} "
                  f"cookies={len(cookies)} elapsed={time.time()-t0:.1f}s", flush=True)
            return {"status": "ok", "message": "Challenge solved!" if has_cf else "no challenge",
                    "solution": sol}


class Handler(BaseHTTPRequestHandler):
    solver: Solver = None  # type: ignore[assignment]

    def log_message(self, *a: Any) -> None:  # 静音默认访问日志(我们自己打 solve 日志)
        return

    def _send(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"FlareSolverr is ready! (nodriver shim)")

    def do_POST(self) -> None:  # noqa: N802
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception as e:  # noqa: BLE001
            self._send(400, {"status": "error", "message": f"bad request: {e}"})
            return
        cmd = (req.get("cmd") or "").lower()
        t0 = time.time()
        if cmd in ("sessions.create", "sessions.destroy", "sessions.list"):
            self._send(200, {"status": "ok", "message": "", "sessions": []})
            return
        if cmd != "request.get":
            self._send(200, {"status": "error", "message": f"unsupported cmd: {cmd}"})
            return
        url = req.get("url") or ""
        max_ms = int(req.get("maxTimeout") or 60000)
        if not url:
            self._send(200, {"status": "error", "message": "missing url"})
            return
        result = self.solver.solve(url, max_ms)
        result.setdefault("startTimestamp", int(t0 * 1000))
        result.setdefault("endTimestamp", int(time.time() * 1000))
        result.setdefault("version", "nodriver-shim-1.0")
        self._send(200, result)


def _free_port() -> int:
    """取一个空闲的本地 TCP 端口(selftest 用,避免与常驻实例/其它进程抢端口)。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def selftest() -> int:
    """**可选联网**自检:起 headless 浏览器 + 临时 /v1 服务,走一次完整 HTTP 往返求解一个
    无 CF 的安全站点(example.com),校验健康检查 + solution 契约齐全,成功打印
    ``FLARESOLVERR_NODRIVER_OK`` 并退出 0;任何失败(含无 Chrome/nodriver)→ 非 0。

    需真实浏览器与出网,故**不纳入默认离线回归**;由 run_all_selftests.py 在
    ``RUN_ONLINE_SELFTESTS=1`` 时才触发(见该文件 ONLINE_CHECKS)。
    """
    import urllib.request

    port = _free_port()
    print(f"[selftest] booting headless nodriver + /v1 on 127.0.0.1:{port} ...", flush=True)
    solver = Solver(headless=True, cache_ttl=1200.0, page_wait=3.0)
    try:
        solver.start()
    except Exception as e:  # noqa: BLE001 - 无 Chrome/无 nodriver 等环境问题
        print(f"[selftest] FAILED: browser start error: {type(e).__name__}: {e}", flush=True)
        return 1

    Handler.solver = solver
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    th = threading.Thread(target=httpd.serve_forever, name="selftest-http", daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"
    try:
        health = urllib.request.urlopen(base + "/", timeout=10).read().decode("utf-8", "replace")
        assert "FlareSolverr is ready" in health, f"unexpected health body: {health!r}"

        payload = json.dumps({"cmd": "request.get", "url": "https://example.com/",
                              "maxTimeout": 15000}).encode("utf-8")
        req = urllib.request.Request(base + "/v1", data=payload, method="POST",
                                     headers={"Content-Type": "application/json"})
        body = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")
        resp = json.loads(body)
        assert resp.get("status") == "ok", f"status != ok: {resp.get('status')} / {resp.get('message')}"
        sol = resp.get("solution") or {}
        assert sol.get("response"), "solution.response 为空"
        assert sol.get("userAgent"), "solution.userAgent 缺失"
        print(f"[selftest] health OK; solve OK (html={len(sol['response'])}B, "
              f"ua={sol['userAgent'][:40]!r})", flush=True)
        print("FLARESOLVERR_NODRIVER_OK", flush=True)
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"[selftest] FAILED: {type(e).__name__}: {e}", flush=True)
        return 1
    finally:
        try:
            httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            if solver._browser:
                solver._browser.stop()
        except Exception:  # noqa: BLE001
            pass


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Docker-free FlareSolverr-compatible endpoint (nodriver).")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8191)
    ap.add_argument("--headless", action="store_true", help="无头模式(默认有头,CF 通过率更高)")
    ap.add_argument("--cache-ttl", type=float, default=1200.0, help="cf_clearance 按 origin 缓存秒数")
    ap.add_argument("--page-wait", type=float, default=6.0, help="每次导航后的基础等待秒(过 CF/渲染)")
    ap.add_argument("--selftest", action="store_true",
                    help="可选联网自检(起 headless+/v1,真解 example.com 校验契约),打印 FLARESOLVERR_NODRIVER_OK")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    print(f"[boot] starting nodriver browser (headless={args.headless}) ...", flush=True)
    solver = Solver(headless=args.headless, cache_ttl=args.cache_ttl, page_wait=args.page_wait)
    solver.start()
    Handler.solver = solver
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[ready] FlareSolverr(nodriver) listening on http://{args.host}:{args.port}/v1", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if solver._browser:
                solver._browser.stop()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
