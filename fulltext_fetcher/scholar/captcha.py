"""§3.7 captcha.py — reCAPTCHA 打码适配器(翼B,默认关,优雅降级)。

⚠️ 合规声明
  直抓 Google Scholar 属灰色行为,违反其 ToS 与 robots.txt;而「自动求解验证码(打码)」更是
  灰色 + 持续付费 + 随 reCAPTCHA 升级可能失效,**仅作可选的最后手段**,默认关闭
  (ScholarConfig.captcha_enabled=False)。使用者须自负合规与法律责任,对外提供服务前务必过
  法务。本模块的**默认路径不联网、不导入任何第三方库**。见《谷歌学术爬虫-架构与选型.md》§3.7/§6。

信封契约(冻结,见 §3.7 与 §5.3「不可用信封」):
  - 开关关闭             → {"available": False, "reason": "captcha disabled"}
  - 无 provider/key      → {"available": False, "reason": "need captcha key"}
  - provider 未知 / 缺库 → {"available": False, "reason": "need ..."}
  - 求解成功             → {"available": True, "token": "..."}
  - 求解失败(已尝试)     → {"available": True, "error": "..."}

第三方库(2captcha-python / python3-capsolver)一律【函数内延迟导入】,缺库即优雅降级为
不可用信封,绝不进父包强制依赖(见 §5.3 硬规则)。
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _unavailable(reason: str) -> Dict[str, Any]:
    """统一的「不可用」信封(开关关 / 缺 key / 缺库 / 未知 provider 都走此形态)。"""
    return {"available": False, "reason": reason}


def solve_recaptcha(site_key: str, page_url: str, cfg: Any,
                    *, version: str = "v2", action: Optional[str] = None) -> Dict[str, Any]:
    """求解 reCAPTCHA,返回统一信封(见模块 docstring)。默认关 → 不联网、不导库。

    参数:
      site_key : 目标页 reCAPTCHA 的 data-sitekey
      page_url : 出现验证码的页面 URL
      cfg      : ScholarConfig(读 captcha_enabled / captcha_provider / captcha_key)
      version  : 'v2' | 'v3'
      action   : v3 的 action 名(可选)
    """
    if not getattr(cfg, "captcha_enabled", False):
        return _unavailable("captcha disabled")

    provider = (getattr(cfg, "captcha_provider", None) or "").strip().lower()
    key = getattr(cfg, "captcha_key", None)
    if not provider or not key:
        return _unavailable("need captcha key")

    if provider in ("2captcha", "twocaptcha"):
        return _solve_2captcha(site_key, page_url, key, version=version, action=action)
    if provider == "capsolver":
        return _solve_capsolver(site_key, page_url, key, version=version, action=action)
    return _unavailable(f"need known captcha provider (got {provider!r})")


def _solve_2captcha(site_key: str, page_url: str, key: str,
                    *, version: str = "v2", action: Optional[str] = None) -> Dict[str, Any]:
    """2captcha-python 适配器(延迟导入)。缺库 → 不可用信封;联网求解异常 → {available:True,error}。"""
    try:
        from twocaptcha import TwoCaptcha  # type: ignore
    except ImportError:
        return _unavailable("need 2captcha-python")
    try:
        solver = TwoCaptcha(key)
        if version == "v3":
            res = solver.recaptcha(sitekey=site_key, url=page_url,
                                   version="v3", action=action or "verify")
        else:
            res = solver.recaptcha(sitekey=site_key, url=page_url)
        token = res.get("code") if isinstance(res, dict) else res
        if token:
            return {"available": True, "token": token}
        return {"available": True, "error": "2captcha: empty token"}
    except Exception as e:  # noqa: BLE001 — 打码 SDK 任何异常一律吞成失败信封,绝不外抛拖垮流水线
        return {"available": True, "error": f"2captcha: {e}"}


def _solve_capsolver(site_key: str, page_url: str, key: str,
                     *, version: str = "v2", action: Optional[str] = None) -> Dict[str, Any]:
    """python3-capsolver 适配器(延迟导入)。缺库 → 不可用信封;异常 → {available:True,error}。"""
    try:
        import capsolver  # type: ignore
    except ImportError:
        return _unavailable("need python3-capsolver")
    try:
        capsolver.api_key = key
        task_type = "ReCaptchaV3TaskProxyLess" if version == "v3" else "ReCaptchaV2TaskProxyLess"
        payload: Dict[str, Any] = {
            "type": task_type,
            "websiteURL": page_url,
            "websiteKey": site_key,
        }
        if version == "v3" and action:
            payload["pageAction"] = action
        sol = capsolver.solve(payload)
        token = (sol or {}).get("gRecaptchaResponse") if isinstance(sol, dict) else None
        if token:
            return {"available": True, "token": token}
        return {"available": True, "error": "capsolver: empty token"}
    except Exception as e:  # noqa: BLE001 — 同上,异常降级为失败信封
        return {"available": True, "error": f"capsolver: {e}"}


# ── Cloudflare Turnstile 硬解题器(-146:攻克 CF「Verify you are human」交互式验证)──────
# 与 reCAPTCHA 同信封契约、同「默认关/缺 key/缺库优雅降级」哲学。Turnstile 与 reCAPTCHA 是两套
# 不同验证:reCAPTCHA 走 solve_recaptcha;CF Turnstile(data-sitekey 以 0x 开头)走本函数。
# ⚠️ 注意:RSC governor 那种【坏 reCAPTCHA(Invalid domain for site key)】不可解,不应调用任何打码,
# 由 render_fetch 直接判 blocked:rsc-governor 冷却(见《选型2026-route-B反RSC-governor补丁方案-165.md》)。
def solve_turnstile(site_key: str, page_url: str, cfg: Any,
                    *, action: Optional[str] = None, cdata: Optional[str] = None) -> Dict[str, Any]:
    """求解 Cloudflare Turnstile,返回统一信封(见模块 docstring)。默认关 → 不联网、不导库。

    参数:
      site_key : 目标页 Turnstile 的 data-sitekey(通常 ``0x`` 开头)
      page_url : 出现 Turnstile 的页面 URL
      cfg      : ScholarConfig(读 captcha_enabled / captcha_provider / captcha_key)
      action   : Turnstile 自定义 action(可选)
      cdata    : Turnstile cData(可选)
    """
    if not getattr(cfg, "captcha_enabled", False):
        return _unavailable("captcha disabled")

    provider = (getattr(cfg, "captcha_provider", None) or "").strip().lower()
    key = getattr(cfg, "captcha_key", None)
    if not provider or not key:
        return _unavailable("need captcha key")

    if provider in ("2captcha", "twocaptcha"):
        return _turnstile_2captcha(site_key, page_url, key, action=action, cdata=cdata)
    if provider == "capsolver":
        return _turnstile_capsolver(site_key, page_url, key, action=action, cdata=cdata)
    return _unavailable(f"need known captcha provider (got {provider!r})")


def _turnstile_2captcha(site_key: str, page_url: str, key: str,
                        *, action: Optional[str] = None, cdata: Optional[str] = None) -> Dict[str, Any]:
    """2captcha-python Turnstile 适配器(延迟导入)。缺库 → 不可用信封;异常 → {available:True,error}。"""
    try:
        from twocaptcha import TwoCaptcha  # type: ignore
    except ImportError:
        return _unavailable("need 2captcha-python")
    try:
        solver = TwoCaptcha(key)
        kwargs: Dict[str, Any] = {"sitekey": site_key, "url": page_url}
        if action:
            kwargs["action"] = action
        if cdata:
            kwargs["data"] = cdata
        res = solver.turnstile(**kwargs)
        token = res.get("code") if isinstance(res, dict) else res
        if token:
            return {"available": True, "token": token}
        return {"available": True, "error": "2captcha: empty token"}
    except Exception as e:  # noqa: BLE001 — 打码 SDK 任何异常一律吞成失败信封,绝不外抛拖垮流水线
        return {"available": True, "error": f"2captcha: {e}"}


def _turnstile_capsolver(site_key: str, page_url: str, key: str,
                         *, action: Optional[str] = None, cdata: Optional[str] = None) -> Dict[str, Any]:
    """python3-capsolver Turnstile 适配器(延迟导入,AntiTurnstileTaskProxyLess)。缺库 → 不可用信封。"""
    try:
        import capsolver  # type: ignore
    except ImportError:
        return _unavailable("need python3-capsolver")
    try:
        capsolver.api_key = key
        payload: Dict[str, Any] = {
            "type": "AntiTurnstileTaskProxyLess",
            "websiteURL": page_url,
            "websiteKey": site_key,
        }
        meta: Dict[str, Any] = {}
        if action:
            meta["action"] = action
        if cdata:
            meta["cdata"] = cdata
        if meta:
            payload["metadata"] = meta
        sol = capsolver.solve(payload)
        token = (sol or {}).get("token") if isinstance(sol, dict) else None
        if token:
            return {"available": True, "token": token}
        return {"available": True, "error": "capsolver: empty token"}
    except Exception as e:  # noqa: BLE001 — 同上,异常降级为失败信封
        return {"available": True, "error": f"capsolver: {e}"}


if __name__ == "__main__":  # 不联网 selftest: python -m fulltext_fetcher.scholar.captcha
    import importlib.util

    class _Cfg:
        def __init__(self, **kw: Any):
            self.captcha_enabled = kw.get("captcha_enabled", False)
            self.captcha_provider = kw.get("captcha_provider", None)
            self.captcha_key = kw.get("captcha_key", None)

    SK, URL = "6LxxxxSITEKEY", "https://scholar.google.com/sorry/index"

    # ① 默认关 → available False & reason=captcha disabled(不联网、不导库)
    assert solve_recaptcha(SK, URL, _Cfg()) == {"available": False, "reason": "captcha disabled"}

    # ② 开了但缺 provider / key → need captcha key(任缺其一都算)
    assert solve_recaptcha(SK, URL, _Cfg(captcha_enabled=True)) == \
        {"available": False, "reason": "need captcha key"}
    assert solve_recaptcha(SK, URL, _Cfg(captcha_enabled=True, captcha_provider="2captcha")) == \
        {"available": False, "reason": "need captcha key"}          # 有 provider 无 key
    assert solve_recaptcha(SK, URL, _Cfg(captcha_enabled=True, captcha_key="K")) == \
        {"available": False, "reason": "need captcha key"}          # 有 key 无 provider

    # ③ 未知 provider → 不可用信封(need ...),不联网
    r3 = solve_recaptcha(SK, URL, _Cfg(captcha_enabled=True, captcha_provider="foobar", captcha_key="K"))
    assert r3["available"] is False and r3["reason"].startswith("need "), r3

    # ④ 已知 provider + key:缺库时优雅降级为 need <dep>(保证不联网:库存在则跳过真实求解)
    for prov, mod, dep in (("2captcha", "twocaptcha", "2captcha-python"),
                           ("capsolver", "capsolver", "python3-capsolver")):
        if importlib.util.find_spec(mod) is None:
            rr = solve_recaptcha(SK, URL,
                                 _Cfg(captcha_enabled=True, captcha_provider=prov, captcha_key="K"))
            assert rr == {"available": False, "reason": f"need {dep}"}, rr

    # ⑤ 契约:不可用信封统一形态恰为 {available:False, reason:...}
    assert set(solve_recaptcha(SK, URL, _Cfg()).keys()) == {"available", "reason"}

    # ── Turnstile 硬解题器(-146)镜像同样的信封契约(默认关/缺 key/未知 provider/缺库优雅降级)──
    TSK = "0x4AAAAAAAAselftest"
    # ⑥ 默认关 → captcha disabled(不联网、不导库)
    assert solve_turnstile(TSK, URL, _Cfg()) == {"available": False, "reason": "captcha disabled"}
    # ⑦ 开了但缺 provider / key → need captcha key
    assert solve_turnstile(TSK, URL, _Cfg(captcha_enabled=True)) == \
        {"available": False, "reason": "need captcha key"}
    assert solve_turnstile(TSK, URL, _Cfg(captcha_enabled=True, captcha_provider="capsolver")) == \
        {"available": False, "reason": "need captcha key"}
    assert solve_turnstile(TSK, URL, _Cfg(captcha_enabled=True, captcha_key="K")) == \
        {"available": False, "reason": "need captcha key"}
    # ⑧ 未知 provider → 不可用信封(need ...),不联网
    rt = solve_turnstile(TSK, URL, _Cfg(captcha_enabled=True, captcha_provider="foobar", captcha_key="K"))
    assert rt["available"] is False and rt["reason"].startswith("need "), rt
    # ⑨ 已知 provider + key:缺库时优雅降级为 need <dep>(库存在则跳过真实求解,保证不联网)
    for prov, mod, dep in (("2captcha", "twocaptcha", "2captcha-python"),
                           ("capsolver", "capsolver", "python3-capsolver")):
        if importlib.util.find_spec(mod) is None:
            rr = solve_turnstile(TSK, URL,
                                 _Cfg(captcha_enabled=True, captcha_provider=prov, captcha_key="K"))
            assert rr == {"available": False, "reason": f"need {dep}"}, rr
    # ⑩ 契约:不可用信封统一形态恰为 {available:False, reason:...}
    assert set(solve_turnstile(TSK, URL, _Cfg()).keys()) == {"available", "reason"}

    print("CAPTCHA_OK")
