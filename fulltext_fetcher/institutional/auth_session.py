"""Auth session 骨架:登录→Cookie→持久化→注入 Config. 联网登录留待 -153 实现."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional

from .cookie_store import CookieStore, StoredCookie
from .credential_store import InstitutionalCredentials, load_credentials, apply_credentials_to_config


class AuthProvider(str, Enum):
    MANUAL = "manual"
    EZPROXY = "ezproxy"
    SHIBBOLETH = "shibboleth"
    OPENATHENS = "openathens"
    CARSI = "carsi"
    WEBVPN = "webvpn"


# SSO 登录成功 URL 信号(借 scansci/SciTeX 思路;机制层待各 provider 子类实现)
_SSO_DONE_HINTS = ("login", "cas", "sso", "wayf", "saml", "idp", "shibboleth", "openathens")


@dataclass
class AuthSession:
    """机制无关会话:凭据 + 可选 CookieStore."""
    provider: AuthProvider = AuthProvider.MANUAL
    credentials: Optional[InstitutionalCredentials] = None
    cookie_store: Optional[CookieStore] = None
    last_verified_ts: Optional[float] = None
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_env(cls, *, config_path: Optional[str] = None) -> "AuthSession":
        cred = load_credentials(config_path=config_path)
        prov = AuthProvider(cred.provider) if cred.provider in AuthProvider._value2member_map_ else AuthProvider.MANUAL
        store = None
        if cred.cookie_store_path:
            store = CookieStore.load(os.path.expanduser(cred.cookie_store_path))
        elif cred.enabled:
            store = CookieStore.load(os.path.join(os.getcwd(), ".ftf_cookies.local.json"))
        sess = cls(provider=prov, credentials=cred, cookie_store=store)
        if store and cred.enabled:
            hdr = store.cookie_header(prov.value)
            if hdr and cred.institution_cookie is None:
                cred.institution_cookie = hdr
                cred.enabled = True
        return sess

    def apply_to_config(self, cfg: Any) -> Any:
        """注入 Config;无凭据零副作用."""
        if not self.credentials or not self.credentials.enabled:
            return cfg
        apply_credentials_to_config(cfg, self.credentials)
        cfg.institutional = True
        return cfg

    def save_cookies(self, cookies: List[StoredCookie]) -> None:
        if not self.cookie_store:
            self.cookie_store = CookieStore.load(
                os.path.join(os.getcwd(), ".ftf_cookies.local.json")
            )
        self.cookie_store.set_cookies(self.provider.value, cookies)
        self.cookie_store.save()
        hdr = self.cookie_store.cookie_header(self.provider.value)
        if hdr and self.credentials:
            self.credentials.institution_cookie = hdr

    def verify_live(self, client: Any = None) -> bool:
        """用前活校验(离线 gate:无 client 时仅检查 Cookie 未过期)."""
        if not self.credentials or not self.credentials.enabled:
            return False
        if self.cookie_store:
            valid = self.cookie_store.get_valid_cookies(self.provider.value)
            if not valid and not self.credentials.institution_cookie:
                return False
        elif not self.credentials.institution_cookie and not self.credentials.ezproxy_prefix:
            return False
        if client is None:
            self.last_verified_ts = time.time()
            return True
        # 联网探针留 -153:对白名单域发 HEAD/GET 判 401 vs 200
        self.notes.append("verify_live: network probe not implemented (gate until credentials)")
        return False

    @staticmethod
    def url_looks_logged_in(url: str) -> bool:
        """可见浏览器登录:URL 脱离 login/cas/sso 中转即判成功(启发式)."""
        low = (url or "").lower()
        return not any(h in low for h in _SSO_DONE_HINTS)

    def open_login_browser(
        self,
        login_url: Optional[str] = None,
        *,
        browser: Any = None,
        headless: bool = False,
        **kwargs: Any,
    ) -> Any:
        """可见浏览器人工 SSO 登录.

        - EZPROXY: 委托 ``ezproxy_login.run_ezproxy_login``(可注入 mock ``browser`` 供离线自检;
          缺省用 nodriver 有头 Chrome),返回登录报告 dict,并把抓到的 Cookie 存 CookieStore
          + 回填 ``credentials.institution_cookie``.
        - 其余 provider(shibboleth/openathens/carsi/webvpn): 机制层待 -153,仍 NotImplementedError.

        注:``ezproxy_login`` 在此**方法内延迟导入**(避免与本模块的模块级循环导入)。
        """
        if self.provider == AuthProvider.EZPROXY:
            from .ezproxy_login import run_ezproxy_login, make_login_browser
            br = browser if browser is not None else make_login_browser(
                self.provider.value, headless=headless)
            return run_ezproxy_login(self, br, login_url=login_url, **kwargs)
        raise NotImplementedError(
            "open_login_browser: 仅 EZproxy 分支已布线(-141/-149);"
            f"provider={self.provider.value} 机制层待 -153. login_url={login_url!r}"
        )


def bootstrap_institutional_config(
    cfg: Any,
    *,
    cli_institutional: bool = False,
    config_path: Optional[str] = None,
) -> AuthSession:
    """CLI / run_all 启动时合并 FTF 凭据与 CookieStore;CLI 已填字段不被覆盖."""
    sess = AuthSession.from_env(config_path=config_path)
    if cli_institutional:
        cfg.institutional = True
    cred = sess.credentials
    if not cred:
        return sess
    if cred.enabled:
        cfg.institutional = True
    if cred.ezproxy_prefix and not cfg.ezproxy_prefix:
        cfg.ezproxy_prefix = cred.ezproxy_prefix
    if cred.institution_cookie and not cfg.institution_cookie:
        cfg.institution_cookie = cred.institution_cookie
    if cred.institution_domains and not cfg.institution_domains:
        cfg.institution_domains = list(cred.institution_domains)
    return sess
