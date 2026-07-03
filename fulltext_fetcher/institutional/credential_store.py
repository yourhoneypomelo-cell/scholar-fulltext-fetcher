"""凭据安全加载:env var + 本地 JSON 文件. 严禁硬编码、严禁写入日志/chat."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional

_ENV_ENABLED = "FTF_INSTITUTIONAL"
_ENV_EZPROXY = "FTF_EZPROXY_PREFIX"
_ENV_COOKIE = "FTF_INSTITUTION_COOKIE"
_ENV_DOMAINS = "FTF_INSTITUTION_DOMAINS"
_ENV_CONFIG_PATH = "FTF_INSTITUTION_CONFIG_PATH"
_DEFAULT_LOCAL = ".ftf_institutional.local.json"


def _redact(s: Optional[str]) -> str:
    if not s:
        return "<empty>"
    if len(s) <= 8:
        return "***"
    return s[:4] + "…" + s[-2:]


@dataclass
class InstitutionalCredentials:
    """机制无关凭据容器(不含密码字段;Cookie 串由用户自行导出)."""
    enabled: bool = False
    provider: str = "manual"  # manual | ezproxy | shibboleth | openathens | carsi | webvpn
    ezproxy_prefix: Optional[str] = None
    institution_cookie: Optional[str] = None
    institution_domains: List[str] = field(default_factory=list)
    cookie_store_path: Optional[str] = None
    source: str = "none"  # none | env | file

    def __repr__(self) -> str:
        return (
            f"InstitutionalCredentials(enabled={self.enabled}, provider={self.provider!r}, "
            f"ezproxy={self.ezproxy_prefix!r}, cookie={_redact(self.institution_cookie)}, "
            f"domains={len(self.institution_domains)}, source={self.source!r})"
        )


def _parse_domains(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def _load_json_file(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("institutional config must be a JSON object")
    return data


def load_credentials(
    *,
    config_path: Optional[str] = None,
    cwd: Optional[str] = None,
) -> InstitutionalCredentials:
    """加载凭据:优先 env(覆盖 file 同名字段),其次本地 JSON. 缺失则返回 disabled."""
    cred = InstitutionalCredentials()
    base = cwd or os.getcwd()
    path = config_path or os.environ.get(_ENV_CONFIG_PATH) or os.path.join(base, _DEFAULT_LOCAL)

    file_data: dict = {}
    if os.path.isfile(path):
        try:
            file_data = _load_json_file(path)
            cred.source = "file"
        except (OSError, json.JSONDecodeError, ValueError):
            file_data = {}

    env_on = os.environ.get(_ENV_ENABLED, "").strip().lower() in ("1", "true", "yes")
    cred.enabled = env_on or bool(file_data.get("enabled"))

    cred.provider = os.environ.get("FTF_INSTITUTION_PROVIDER") or str(file_data.get("provider") or "manual")
    cred.ezproxy_prefix = os.environ.get(_ENV_EZPROXY) or file_data.get("ezproxy_prefix")
    cred.institution_cookie = os.environ.get(_ENV_COOKIE) or file_data.get("institution_cookie")
    dom_env = os.environ.get(_ENV_DOMAINS)
    dom_file = file_data.get("institution_domains")
    if dom_env:
        cred.institution_domains = _parse_domains(dom_env)
        cred.source = "env" if cred.source == "none" else cred.source
    elif isinstance(dom_file, list):
        cred.institution_domains = [str(x).strip().lower() for x in dom_file if str(x).strip()]
    elif isinstance(dom_file, str):
        cred.institution_domains = _parse_domains(dom_file)

    cred.cookie_store_path = file_data.get("cookie_store_path") or os.environ.get("FTF_COOKIE_STORE_PATH")

    if os.environ.get(_ENV_EZPROXY) or os.environ.get(_ENV_COOKIE) or env_on:
        cred.source = "env" if cred.source == "file" else ("env" if cred.source == "none" else cred.source)

    if cred.institution_cookie or cred.ezproxy_prefix:
        cred.enabled = True
    return cred


def apply_credentials_to_config(cfg: Any, cred: Optional[InstitutionalCredentials] = None) -> Any:
    """把凭据写入 Config(就地修改). 无凭据时零副作用."""
    cred = cred or load_credentials()
    if not cred.enabled:
        return cfg
    cfg.institutional = True
    if cred.ezproxy_prefix:
        cfg.ezproxy_prefix = cred.ezproxy_prefix
    if cred.institution_cookie:
        cfg.institution_cookie = cred.institution_cookie
    if cred.institution_domains:
        cfg.institution_domains = list(cred.institution_domains)
    return cfg
