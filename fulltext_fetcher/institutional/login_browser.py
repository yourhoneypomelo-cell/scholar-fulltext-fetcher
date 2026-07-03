"""登录浏览器公共层(A5·-141 抢跑)：三机制(EZproxy/Shibboleth/CARSI)共享的浏览器适配。

- **LoginBrowser 鸭子接口**(真实实现见 NodriverLoginBrowser;测试用 mock):
    browser.open(url: str) -> None            # 打开(或导航到)url
    browser.current_url -> str                # 当前地址(判断是否脱离登录/中转页)
    browser.get_cookies() -> List[dict]       # [{name,value,domain,path,expires,secure,httpOnly}]
    browser.close() -> None                   # 关闭(幂等)

- 各机制的登录流程(run_ezproxy_login / run_saml_login)只依赖上面接口,故驱动可替换、易单测。
- 安全:cookie 转换/持久化不回显明文;真实驱动懒加载,未装 nodriver 不影响其余 A5 功能与 mock 单测。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .cookie_store import StoredCookie


def to_stored_cookies(raw: Optional[List[Dict[str, Any]]]) -> List[StoredCookie]:
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


class NodriverLoginBrowser:
    """LoginBrowser 的 nodriver 实现(有头/可见 Chrome,反检测)。

    注:nodriver 为 async API,这里用独立事件循环做同步包装,契合各 run_*_login 的同步流程。
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


def _selftest() -> None:
    # cookie 转换:会话/过期/驼峰 httpOnly 兼容
    cs = to_stored_cookies([
        {"name": "A", "value": "1", "expires": -1, "httpOnly": True},
        {"name": "B", "value": "2", "expires": 4102444800, "secure": False},
        {"name": "", "value": "skip"},  # 无 name → 跳过
    ])
    assert [c.name for c in cs] == ["A", "B"], cs
    assert cs[0].expires is None and cs[0].http_only is True, cs[0]
    assert cs[1].expires == 4102444800.0 and cs[1].secure is False, cs[1]
    # make_login_browser 未装 nodriver 时抛 ImportError(带指引);装了则返回实例
    try:
        import nodriver  # noqa: F401
        _has = True
    except Exception:
        _has = False
    if not _has:
        try:
            make_login_browser("ezproxy")
            raise AssertionError("未装 nodriver 应抛 ImportError")
        except ImportError as e:
            assert "nodriver" in str(e)
    print("  [login_browser] selftest OK")


if __name__ == "__main__":
    _selftest()
