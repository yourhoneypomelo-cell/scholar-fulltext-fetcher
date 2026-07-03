"""EZproxy 可见浏览器登录(A5·-141 抢跑骨架,为 -153 联网落地布线)。

设计要点:
- **驱动无关**:核心流程 `run_ezproxy_login(session, browser, ...)` 只依赖一个鸭子类型的
  `LoginBrowser`(见下),不绑定具体自动化库 → 便于 mock 单测、也便于换 nodriver/playwright。
- **不改既有契约**:不动 RouteBBridge/AuthSession 其它方法/字段;只新增本模块 + 由
  AuthSession.open_login_browser 的 EZproxy 分支委托进来。
- **安全**:全程不含真实凭据;返回报告不回显 cookie 明文(只报数量/是否登录)。

LoginBrowser 鸭子接口(真实实现见 NodriverLoginBrowser;测试用 mock):
    browser.open(url: str) -> None            # 打开(或导航到)url
    browser.current_url -> str                # 当前地址(用于判断是否脱离登录页)
    browser.get_cookies() -> List[dict]       # [{name,value,domain,path,expires,secure,httpOnly}]
    browser.close() -> None                   # 关闭(幂等)

流程(EZproxy):打开 ezproxy_prefix(或显式 login_url)→ 轮询 current_url 直到脱离
login/cas/sso(AuthSession.url_looks_logged_in)→ 抓 cookie 存 CookieStore(经 session.save_cookies,
同时回填 credentials.institution_cookie)→ 返回登录报告。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .cookie_store import StoredCookie


def _to_stored_cookies(raw: Optional[List[Dict[str, Any]]]) -> List[StoredCookie]:
    """把浏览器 cookie dict 列表转 StoredCookie;expires<=0 视为会话 cookie(None)。"""
    out: List[StoredCookie] = []
    for c in (raw or []):
        name = c.get("name")
        if not name:
            continue
        exp = c.get("expires")
        try:
            exp = None if (exp is None or float(exp) <= 0) else float(exp)
        except (TypeError, ValueError):
            exp = None
        out.append(StoredCookie(
            name=str(name),
            value=str(c.get("value", "")),
            domain=str(c.get("domain", "")),
            path=str(c.get("path", "/")),
            expires=exp,
            secure=bool(c.get("secure", True)),
            http_only=bool(c.get("httpOnly", c.get("http_only", False))),
        ))
    return out


def run_ezproxy_login(
    session: Any,
    browser: Any,
    login_url: Optional[str] = None,
    *,
    max_polls: int = 120,
    interval_s: float = 1.0,
    sleep_fn: Optional[Any] = None,
) -> Dict[str, Any]:
    """驱动无关的 EZproxy 登录核心(browser 为注入的 LoginBrowser;可 mock)。

    返回报告(不含敏感明文):
      {provider, logged_in, polls, final_url, n_cookies, cookie_header_set, [error]}
    """
    sleep_fn = sleep_fn or time.sleep
    cred = getattr(session, "credentials", None)

    # login_url 缺省用 ezproxy_prefix(EZproxy 登录入口本身即前缀页)
    if not login_url:
        login_url = getattr(cred, "ezproxy_prefix", None) if cred else None

    report: Dict[str, Any] = {
        "provider": "ezproxy", "logged_in": False, "polls": 0,
        "final_url": None, "n_cookies": 0, "cookie_header_set": False,
    }
    if not login_url:
        report["error"] = "no-login-url(缺 ezproxy_prefix / 未显式传 login_url)"
        return report

    try:
        browser.open(login_url)
        logged_in = False
        for i in range(1, max(1, max_polls) + 1):
            report["polls"] = i
            url = browser.current_url or ""
            report["final_url"] = url
            # 脱离 login/cas/sso/... 中转即判登录完成(复用 AuthSession 启发式)
            if url and session.url_looks_logged_in(url):
                logged_in = True
                break
            sleep_fn(interval_s)
        report["logged_in"] = logged_in

        if logged_in:
            stored = _to_stored_cookies(browser.get_cookies())
            report["n_cookies"] = len(stored)
            if stored and hasattr(session, "save_cookies"):
                session.save_cookies(stored)  # 存 CookieStore + 回填 institution_cookie
                report["cookie_header_set"] = bool(
                    getattr(cred, "institution_cookie", None)) if cred else False
        return report
    finally:
        try:
            browser.close()
        except Exception:
            pass


# ── 真实驱动适配(nodriver)：结构就位,E2E 联网细节待 -153 核验 ──────────────
class NodriverLoginBrowser:
    """LoginBrowser 的 nodriver 实现(有头/可见 Chrome,反检测)。

    注:nodriver 为 async API,这里用独立事件循环做同步包装,契合 run_ezproxy_login 的同步流程。
    个别 API 细节(cookies.get_all / stop 签名)以 -153 联网实测为准;未装 nodriver 时由
    make_login_browser 抛 ImportError(带安装指引),不影响 mock 单测与其余 A5 功能。
    """

    def __init__(self, *, headless: bool = False) -> None:
        self._headless = headless
        self._browser: Any = None
        self._page: Any = None
        self._loop: Any = None

    def _run(self, coro: Any) -> Any:
        import asyncio
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(coro)

    def open(self, url: str) -> None:
        import nodriver as uc  # 懒加载

        async def _o() -> None:
            if self._browser is None:
                self._browser = await uc.start(headless=self._headless)
            self._page = await self._browser.get(url)

        self._run(_o())

    @property
    def current_url(self) -> str:
        if self._page is None:
            return ""

        async def _u() -> str:
            try:
                return await self._page.evaluate("window.location.href")
            except Exception:
                return getattr(self._page, "url", "") or ""

        return self._run(_u()) or ""

    def get_cookies(self) -> List[Dict[str, Any]]:
        if self._browser is None:
            return []

        async def _c() -> List[Dict[str, Any]]:
            cookies = await self._browser.cookies.get_all()
            out: List[Dict[str, Any]] = []
            for c in cookies:
                out.append({
                    "name": getattr(c, "name", None),
                    "value": getattr(c, "value", ""),
                    "domain": getattr(c, "domain", ""),
                    "path": getattr(c, "path", "/"),
                    "expires": getattr(c, "expires", None),
                    "secure": getattr(c, "secure", True),
                    "httpOnly": getattr(c, "http_only", getattr(c, "httpOnly", False)),
                })
            return out

        return self._run(_c())

    def close(self) -> None:
        if self._browser is None:
            return
        try:
            async def _s() -> None:
                try:
                    self._browser.stop()
                except TypeError:
                    await self._browser.stop()  # 兼容 async stop
                except Exception:
                    pass
            self._run(_s())
        finally:
            if self._loop is not None:
                try:
                    self._loop.close()
                except Exception:
                    pass
                self._loop = None
            self._browser = None
            self._page = None


def make_login_browser(provider: str, *, headless: bool = False) -> "NodriverLoginBrowser":
    """工厂:返回真实 nodriver 浏览器;未装 nodriver → ImportError(带指引)。"""
    try:
        import nodriver  # noqa: F401
    except Exception as e:  # noqa: BLE001
        raise ImportError(
            "open_login_browser 需要 nodriver(有头浏览器登录):pip install nodriver。"
            f" provider={provider};原始错误={e}"
        ) from e
    return NodriverLoginBrowser(headless=headless)


# ── 离线自检(mock 浏览器,无真实凭据/不联网)──────────────────────────────
def _selftest() -> None:
    import os
    import tempfile

    # 延迟 import 避免模块级循环(auth_session 在方法内 import 本模块)
    if __package__ in (None, ""):
        import sys
        _root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        if _root not in sys.path:
            sys.path.insert(0, _root)
        from fulltext_fetcher.institutional import auth_session, credential_store, cookie_store  # type: ignore
    else:
        from . import auth_session, credential_store, cookie_store

    class _MockBrowser:
        """按预置 URL 序列模拟登录跳转;记录 open/close 与 cookie 下发。"""
        def __init__(self, urls: List[str], cookies: List[Dict[str, Any]]):
            self._urls = list(urls)
            self._cookies = cookies
            self.opened: Optional[str] = None
            self.closed = False
            self._i = -1

        def open(self, url: str) -> None:
            self.opened = url

        @property
        def current_url(self) -> str:
            self._i = min(self._i + 1, len(self._urls) - 1)
            return self._urls[self._i]

        def get_cookies(self) -> List[Dict[str, Any]]:
            return list(self._cookies)

        def close(self) -> None:
            self.closed = True

    def _mk_session(cookie_path: str) -> Any:
        cred = credential_store.InstitutionalCredentials(
            enabled=True, provider="ezproxy",
            ezproxy_prefix="https://login.ezproxy.demo.edu/login?url=",
            institution_domains=["onlinelibrary.wiley.com"],
            cookie_store_path=cookie_path,
        )
        store = cookie_store.CookieStore.load(cookie_path)
        return auth_session.AuthSession(
            provider=auth_session.AuthProvider.EZPROXY, credentials=cred, cookie_store=store)

    _noop = lambda _s: None  # noqa: E731

    with tempfile.TemporaryDirectory() as d:
        # 场景1:多跳登录(login→cas→脱离)→ 成功抓 cookie,回填 institution_cookie
        sess = _mk_session(os.path.join(d, "c1.json"))
        br = _MockBrowser(
            urls=["https://login.ezproxy.demo.edu/login?url=x",
                  "https://login.ezproxy.demo.edu/cas/login",
                  "https://onlinelibrary-wiley-com.ezproxy.demo.edu/doi/10.1/x"],
            cookies=[{"name": "ezproxy", "value": "SESS1", "domain": ".ezproxy.demo.edu",
                      "path": "/", "expires": -1, "secure": True, "httpOnly": True}],
        )
        rep = run_ezproxy_login(sess, br, max_polls=10, sleep_fn=_noop)
        assert rep["logged_in"] is True, rep
        assert rep["polls"] == 3, rep                       # 第3跳才脱离
        assert rep["n_cookies"] == 1, rep
        assert rep["cookie_header_set"] is True, rep
        assert sess.credentials.institution_cookie == "ezproxy=SESS1", sess.credentials.institution_cookie
        assert br.opened and br.closed, (br.opened, br.closed)
        # 落盘可复读:CookieStore 里 ezproxy 桶有 1 条有效
        assert sess.cookie_store.cookie_header("ezproxy") == "ezproxy=SESS1"

        # 场景2:超时(始终停在登录页)→ 未登录、不抓 cookie
        sess2 = _mk_session(os.path.join(d, "c2.json"))
        br2 = _MockBrowser(urls=["https://login.ezproxy.demo.edu/login?url=x"],
                           cookies=[{"name": "x", "value": "y"}])
        rep2 = run_ezproxy_login(sess2, br2, max_polls=3, sleep_fn=_noop)
        assert rep2["logged_in"] is False and rep2["polls"] == 3, rep2
        assert rep2["n_cookies"] == 0, rep2
        assert sess2.credentials.institution_cookie is None, sess2.credentials.institution_cookie
        assert br2.closed is True

        # 场景3:无 login_url 且无 prefix → 明确报错、不崩
        cred3 = credential_store.InstitutionalCredentials(enabled=True, provider="ezproxy")
        sess3 = auth_session.AuthSession(
            provider=auth_session.AuthProvider.EZPROXY, credentials=cred3)
        rep3 = run_ezproxy_login(sess3, _MockBrowser(urls=["x"], cookies=[]),
                                 max_polls=2, sleep_fn=_noop)
        assert rep3["logged_in"] is False and "no-login-url" in rep3.get("error", ""), rep3

        # 场景4:经 AuthSession.open_login_browser 端到端路由(mock 注入,首跳即脱离,无 sleep)
        sess4 = _mk_session(os.path.join(d, "c4.json"))
        br4 = _MockBrowser(
            urls=["https://onlinelibrary-wiley-com.ezproxy.demo.edu/doi/10.1/y"],
            cookies=[{"name": "ezproxy", "value": "SESS4", "expires": 0}],
        )
        rep4 = sess4.open_login_browser(browser=br4)
        assert rep4["logged_in"] is True and rep4["n_cookies"] == 1, rep4
        assert sess4.credentials.institution_cookie == "ezproxy=SESS4", sess4.credentials.institution_cookie

        # 场景5:非 EZproxy provider 仍 NotImplementedError(其它分支留 -153)
        sess5 = auth_session.AuthSession(provider=auth_session.AuthProvider.SHIBBOLETH)
        try:
            sess5.open_login_browser("https://idp.demo.edu/")
            raise AssertionError("shibboleth 分支应尚未实现")
        except NotImplementedError:
            pass

    print("  [ezproxy_login] selftest OK")


if __name__ == "__main__":
    _selftest()
    print("EZPROXY_LOGIN_OK")
