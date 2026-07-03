"""A5 框架层离线 selftest(零网络、零真凭据)."""
from __future__ import annotations

import os
import tempfile
import time


def _selftest() -> int:
    from ..config import Config
    from .auth_session import AuthSession, AuthProvider
    from .cookie_store import CookieStore, StoredCookie
    from .credential_store import load_credentials, apply_credentials_to_config
    from .route_b_bridge import plan_route_b_injection, plan_route_b_injection_from_config

    # ① 无 env/文件 → disabled
    os.environ.pop("FTF_INSTITUTIONAL", None)
    os.environ.pop("FTF_INSTITUTION_COOKIE", None)
    cred0 = load_credentials(config_path="/nonexistent/path.json")
    assert not cred0.enabled, cred0
    cfg0 = Config()
    apply_credentials_to_config(cfg0, cred0)
    assert cfg0.institutional is False

    # ② env 加载 + redact
    os.environ["FTF_INSTITUTIONAL"] = "1"
    os.environ["FTF_EZPROXY_PREFIX"] = "https://login.ezproxy.test.edu/login?url="
    os.environ["FTF_INSTITUTION_COOKIE"] = "ezproxy=SECRETTOKEN123"
    os.environ["FTF_INSTITUTION_DOMAINS"] = "sciencedirect.com,elsevier.com"
    cred1 = load_credentials()
    assert cred1.enabled and cred1.source == "env"
    assert "SECRET" not in repr(cred1)
    cfg1 = Config()
    apply_credentials_to_config(cfg1, cred1)
    assert cfg1.institutional is True
    assert cfg1.ezproxy_prefix.startswith("https://login.ezproxy")
    assert "SECRETTOKEN" in cfg1.institution_cookie
    assert "sciencedirect.com" in cfg1.institution_domains

    # ③ JSON 文件加载
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "inst.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"enabled":true,"provider":"ezproxy","institution_domains":["pubs.acs.org"]}\n')
        os.environ.pop("FTF_INSTITUTIONAL", None)
        os.environ.pop("FTF_INSTITUTION_COOKIE", None)
        os.environ.pop("FTF_EZPROXY_PREFIX", None)
        os.environ.pop("FTF_INSTITUTION_DOMAINS", None)
        cred2 = load_credentials(config_path=path)
        assert cred2.enabled and "pubs.acs.org" in cred2.institution_domains

        # ④ CookieStore 往返
        cpath = os.path.join(d, "cookies.json")
        store = CookieStore(path=cpath)
        store.set_cookies("ezproxy", [
            StoredCookie("ezproxy", "tok", "ezproxy.test.edu", expires=time.time() + 3600),
        ])
        store.save()
        store2 = CookieStore.load(cpath)
        assert store2.cookie_header("ezproxy") == "ezproxy=tok"

        # ⑤ AuthSession + route-B plan
        os.environ["FTF_INSTITUTION_COOKIE"] = "ezproxy=tok"
        sess = AuthSession.from_env(config_path=path)
        sess.cookie_store = store2
        assert sess.verify_live() is True
        cfg2 = Config()
        sess.apply_to_config(cfg2)
        assert cfg2.institutional is True

        url = "https://www.sciencedirect.com/science/article/pii/S123/pdfft"
        plan = plan_route_b_injection(sess, url, user_agent="Mozilla/5.0 test")
        assert plan.cookie_count() >= 1
        assert plan.rewrite_target_host == "www.sciencedirect.com"
        assert "inject" in plan.notes

    # ⑤b route-B 注入计划从 Config 直接生成(download._browser_capture_fallback 兜底用;A5 路线B 断线补齐)
    #     与路线A(http_client.needs_institution_access)同口径:命中白名单→非空 plan,否则 None(零副作用)。
    sd_url = "https://www.sciencedirect.com/science/article/pii/S1/pdfft"
    # (a) 默认 Config(无机构凭据)→ None,与未启用逐字节一致
    assert plan_route_b_injection_from_config(Config(), sd_url) is None
    # (b) 启用机构订阅 + cookie + 命中白名单 → 非空 plan(cookie 全解析 + EZproxy 前缀 + 改写 host)
    cfg_inst = Config(
        institutional=True,
        ezproxy_prefix="https://login.ezproxy.test.edu/login?url=",
        institution_cookie="ezproxy=SECRETTOK; sid=abc",
        institution_domains=["sciencedirect.com"],
    )
    plan_sd = plan_route_b_injection_from_config(cfg_inst, sd_url, user_agent="Mozilla/5.0 test")
    assert plan_sd is not None and plan_sd.cookie_count() == 2, plan_sd
    assert plan_sd.ezproxy_prefix.startswith("https://login.ezproxy"), plan_sd
    assert plan_sd.rewrite_target_host == "www.sciencedirect.com", plan_sd
    assert plan_sd.user_agent == "Mozilla/5.0 test", plan_sd          # UA 透传(与浏览器抓字节同指纹)
    assert {c.name for c in plan_sd.cookies} == {"ezproxy", "sid"}, plan_sd.cookies  # cookie 全解析,供属主注入
    # (c) host 未命中白名单 → None(与 needs_institution_access 同口径,不误改写无关域)
    assert plan_route_b_injection_from_config(cfg_inst, "https://example.org/x.pdf") is None
    # (d) 配了凭据但白名单为空 → 骨架保守 None(未显式白名单不主动改写,零副作用)
    cfg_nowl = Config(
        institutional=True,
        ezproxy_prefix="https://login.ezproxy.test.edu/login?url=",
        institution_cookie="ezproxy=T",
    )
    assert plan_route_b_injection_from_config(cfg_nowl, sd_url) is None
    # (e) 开放 API 域即便被误列白名单也永不经机构通道 → None(防机构会话外泄第三方)
    cfg_oa = Config(
        institutional=True,
        institution_cookie="ezproxy=T",
        institution_domains=["api.crossref.org"],
    )
    assert plan_route_b_injection_from_config(cfg_oa, "https://api.crossref.org/works/x") is None

    # ⑥ SSO URL 启发式
    assert AuthSession.url_looks_logged_in("https://www.sciencedirect.com/science/article/pii/X")
    assert not AuthSession.url_looks_logged_in("https://idp.uni.edu/login?service=shibboleth")

    # ⑦ bootstrap: CLI 字段不被 FTF 覆盖
    from .auth_session import bootstrap_institutional_config
    os.environ["FTF_INSTITUTIONAL"] = "1"
    os.environ["FTF_EZPROXY_PREFIX"] = "https://ezproxy.test/from-env"
    cfg_cli = Config(
        institutional=True,
        ezproxy_prefix="https://ezproxy.test/from-cli",
    )
    bootstrap_institutional_config(cfg_cli, cli_institutional=True)
    assert cfg_cli.ezproxy_prefix == "https://ezproxy.test/from-cli"

    print("A5_FRAMEWORK_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
