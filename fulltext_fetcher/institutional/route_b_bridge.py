"""route-B / download 注入接口契约 — 只定义、不改 render_fetch 实现.

属主:render_fetch (-141, session af23d422). 本模块供 A5 产出注入计划,由属主在 nodriver tab 内执行.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse

from .auth_session import AuthSession
from .cookie_store import StoredCookie


@dataclass
class BrowserCookieSpec:
    """CDP Network.setCookie 兼容字段子集."""
    name: str
    value: str
    domain: str
    path: str = "/"
    secure: bool = False
    http_only: bool = False
    expires: Optional[float] = None

    @classmethod
    def from_stored(cls, c: StoredCookie) -> "BrowserCookieSpec":
        return cls(
            name=c.name, value=c.value, domain=c.domain, path=c.path,
            secure=c.secure, http_only=c.http_only, expires=c.expires,
        )


@dataclass
class RouteBInjectionPlan:
    """render_fetch 属主消费:在【同一 nodriver 真 Chrome 会话】内注入后再页内 fetch."""
    cookies: List[BrowserCookieSpec] = field(default_factory=list)
    user_agent: Optional[str] = None
    ezproxy_prefix: Optional[str] = None
    rewrite_target_host: Optional[str] = None
    provider: str = "manual"
    notes: str = ""

    def cookie_count(self) -> int:
        return len(self.cookies)


# ── 属主须实现的 hook(文档契约;不在此文件 import render_fetch) ──
ROUTE_B_INJECT_HOOK_DOC = """
async def inject_institutional_session(tab, plan: RouteBInjectionPlan, *, cdp) -> None:
    '''在 route-B 过 CF 之前或导航前,向 nodriver tab 注入机构 Cookie.

    参数:
        tab: nodriver Tab (与 render_fetch 现有 capture 同会话)
        plan: 本模块 plan_route_b_injection() 产出
        cdp: tab 的 CDP 命名空间 (Network.setCookie / get_all_cookies)

    纪律:
        - 必须与页内 fetch(B1) 同一浏览器上下文(JA3 一致)
        - 注入后 navigate 到 ezproxy 改写 URL 或出版商落地页
        - 禁止把 Cookie 回放到 curl_cffi(强 CF/JA3 站必 403)
    '''
"""


def plan_route_b_injection(
    session: AuthSession,
    target_url: str,
    *,
    user_agent: Optional[str] = None,
) -> RouteBInjectionPlan:
    """从 AuthSession 生成 route-B 注入计划(纯数据、离线)."""
    cred = session.credentials
    plan = RouteBInjectionPlan(provider=session.provider.value, user_agent=user_agent)
    if not cred or not cred.enabled:
        plan.notes = "institutional disabled; no injection"
        return plan

    plan.ezproxy_prefix = cred.ezproxy_prefix
    host = urlparse(target_url).hostname or ""
    plan.rewrite_target_host = host

    if session.cookie_store:
        for sc in session.cookie_store.get_valid_cookies(session.provider.value):
            plan.cookies.append(BrowserCookieSpec.from_stored(sc))

    if not plan.cookies and cred.institution_cookie:
        # 解析 "k=v; k2=v2" → 按 target host 注入(域缺省用 host)
        plan.cookies.extend(_cookie_specs_from_header(cred.institution_cookie, host))

    plan.notes = (
        f"inject {plan.cookie_count()} cookie(s) for {host}; "
        "render_fetch owner implements inject_institutional_session()"
    )
    return plan


def _cookie_specs_from_header(cookie_header: str, host: str) -> List[BrowserCookieSpec]:
    """把 "k1=v1; k2=v2" Cookie 头串解析为 BrowserCookieSpec 列表(域缺省用 host)。"""
    specs: List[BrowserCookieSpec] = []
    for part in (cookie_header or "").split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        specs.append(BrowserCookieSpec(
            name=name.strip(), value=value.strip(), domain=host or ".",
        ))
    return specs


def plan_route_b_injection_from_config(
    cfg,
    target_url: str,
    *,
    user_agent: Optional[str] = None,
) -> Optional[RouteBInjectionPlan]:
    """从 ``Config``(机构订阅字段)直接生成 route-B 注入计划(纯数据、离线、零副作用)。

    供 ``download._browser_capture_fallback`` 在 route-B 兜底浏览器抓字节前构造:命中机构白名单时
    把机构 Cookie/EZproxy 前缀装进 ``RouteBInjectionPlan``,随 ``render_download_pdf_bytes(injection_plan=)``
    在【同一 nodriver 会话】内注入(与 B1 同 JA3),从而让 RSC/ACS/Wiley/ScienceDirect 等 JA3 绑定型
    强 CF 站在 route-B 上也能带机构会话取用全文。

    与路线A(``http_client``)口径一致:仅当配置了机构凭据(``ezproxy_prefix`` 或 ``institution_cookie``)
    且 target host 命中 ``institution_domains`` 白名单(``needs_institution_access``)时产出非空 plan;
    否则返回 ``None``——与未启用机构订阅时逐字节一致(浏览器路径不注入任何 Cookie/不改写 URL)。
    """
    if cfg is None:
        return None
    ezproxy_prefix = getattr(cfg, "ezproxy_prefix", None)
    institution_cookie = getattr(cfg, "institution_cookie", None)
    if not ezproxy_prefix and not institution_cookie:
        return None
    host = urlparse(target_url).hostname or ""
    # 复用路线A 的机构白名单守卫:未配置/OA 域/未命中白名单 → 恒 False,不注入(零副作用、与 http_client 同口径)。
    try:
        from ..http_client import needs_institution_access
    except ImportError:
        return None
    if not needs_institution_access(host, cfg):
        return None

    plan = RouteBInjectionPlan(
        provider="manual", user_agent=user_agent,
    )
    plan.ezproxy_prefix = ezproxy_prefix
    plan.rewrite_target_host = host
    if institution_cookie:
        plan.cookies.extend(_cookie_specs_from_header(institution_cookie, host))
    plan.notes = f"cfg-derived inject {plan.cookie_count()} cookie(s) for {host}"
    return plan
