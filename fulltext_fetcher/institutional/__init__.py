"""A5 机构订阅 · 机制无关框架层(凭据 gate:默认离线、零网络).

子模块:
  credential_store  从 env / 本地 JSON 安全加载(严禁硬编码、严禁日志泄露)
  cookie_store      Cookie 持久化(JSON + 过期)
  auth_session      登录会话骨架(加载→注入 Config→供 route-B 使用)
  route_b_bridge    与 render_fetch 属主对齐的注入接口契约(本包只定义、不改 render_fetch)
  assisted_auth     Tier-0「人在环 + 持久暖档案」辅助认证(gated·默认关;不改 render_fetch)
"""
from .auth_session import AuthSession, AuthProvider, bootstrap_institutional_config
from .credential_store import InstitutionalCredentials, load_credentials, apply_credentials_to_config
from .route_b_bridge import BrowserCookieSpec, RouteBInjectionPlan, plan_route_b_injection

# 注:assisted_auth 走 `python -m ...assisted_auth` 跑内置 selftest(与 selftest_a5_framework 同款),
# 故【不在此 eager import】以免 runpy 的双导入 RuntimeWarning;消费方用显式子模块路径:
#   from fulltext_fetcher.institutional.assisted_auth import run_assisted_login, classify_auth_state, ...

__all__ = [
    "AuthSession",
    "AuthProvider",
    "bootstrap_institutional_config",
    "InstitutionalCredentials",
    "load_credentials",
    "apply_credentials_to_config",
    "BrowserCookieSpec",
    "RouteBInjectionPlan",
    "plan_route_b_injection",
]
