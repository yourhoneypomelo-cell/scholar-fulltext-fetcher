"""EZproxy URL 改写(双模式):前缀式 + 主机名改写式。路线A(机构订阅)准备件。

定位:`http_client.rewrite_url_for_proxy` 的**双模式实现体**(纯字符串变换、离线可测)。
已与 143 的 curl_cffi 工单对齐改动区块后,由 http_client.rewrite_url_for_proxy 延迟导入委托
接入主路径(其守卫先行判定 needs_institution_access,本模块内再判一次,双保险幂等)。
路线A 已因「用户无机构订阅凭据」封顶:代码就绪、联网实测永久 gate,待将来凭据到手直接可用。

模式自动识别(与 cli.py --ezproxy-prefix 帮助文案一致):
  - 值含 "://" 或 "=" → **前缀式**(starting point URL):prefix + quote(原URL)
        https://login.ezproxy.uni.edu/login?url=https%3A//www.sciencedirect.com/...
  - 值为裸域名(如 "ezproxy.uni.edu")→ **主机名改写式**(proxy by hostname):
        www.sciencedirect.com → www-sciencedirect-com.ezproxy.uni.edu
    点→连字符;既有连字符**加倍**(EZproxy HttpsHyphens 惯例,防歧义可逆):
        ars.els-cdn.com → ars-els--cdn-com.ezproxy.uni.edu

守卫与边界(与 http_client 现行为对齐、只紧不松):
  - 未配置 ezproxy_prefix,或该 host 不需机构访问(needs_institution_access=False:含默认无凭据、
    OA/开放 API 域名、不在 institution_domains 白名单)→ 恒等返回;
  - URL 带显式端口(含显式写出的 443/80)→ 保守恒等(EZproxy 端口编码各机构部署差异大,骨架不猜);
  - 任何解析异常 → 恒等(绝不因改写毁掉本来可用的 URL)。

离线 selftest:python -m fulltext_fetcher.ezproxy → EZPROXY_OK(零网络、零凭据)。
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from .http_client import needs_institution_access

# 裸域名(主机名改写式的代理域):字母/数字/点/连字符,无路径、无 scheme、无 '='
_BARE_DOMAIN_RE = re.compile(r"^\.?[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")


def is_hostname_mode(prefix: Any) -> bool:
    """ezproxy_prefix 的值是否应按【主机名改写式】处理(裸代理域名)。

    含 "://" 或 "="(典型 login?url=)或 "/" → 前缀式;其余仅当形如裸域名才判主机名式,
    判不出来的一律按前缀式兜底(与既有行为兼容)。
    """
    p = str(prefix or "").strip()
    if not p or "://" in p or "=" in p or "/" in p:
        return False
    return bool(_BARE_DOMAIN_RE.match(p)) and "." in p.lstrip(".")


def proxy_hostname(host: str, proxy_domain: str) -> str:
    """原始 host → 主机名改写式代理 host(点→连字符,既有连字符加倍)。纯字符串变换。"""
    mangled = str(host or "").lower().replace("-", "--").replace(".", "-")
    return f"{mangled}.{str(proxy_domain or '').strip().lstrip('.')}"


def rewrite_url_for_proxy(url: str, cfg: Any) -> str:
    """把出版商 URL 改写为经机构 EZproxy 取用的形式(双模式);不满足条件一律恒等返回。

    契约与 http_client.rewrite_url_for_proxy 一致(前缀式输出逐字节相同),可直接作其函数体的
    drop-in 委托目标。
    """
    prefix = getattr(cfg, "ezproxy_prefix", None)
    if not prefix:
        return url
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if not needs_institution_access(host, cfg):
            return url
        p = str(prefix).strip()
        if is_hostname_mode(p):
            if parts.port is not None:          # 显式端口 → 保守恒等(部署差异大,骨架不猜)
                return url
            netloc = proxy_hostname(host, p)
            return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
        return p + quote(url, safe="")
    except Exception:  # noqa: BLE001 - 改写绝不毁掉本来可用的 URL
        return url


# ────────────────────────── 不联网 selftest ──────────────────────────
def _selftest() -> int:
    from .config import Config
    from .http_client import rewrite_url_for_proxy as _hc_rewrite

    _SD = "https://www.sciencedirect.com/science/article/pii/S0926860X05002504/pdfft"
    _PREFIX = "https://login.ezproxy.uni.edu/login?url="

    # ① 模式识别:前缀式(://、=、/)vs 主机名式(裸域名);畸形值按前缀式兜底
    assert not is_hostname_mode(_PREFIX)
    assert not is_hostname_mode("login?url=")            # 含 =
    assert not is_hostname_mode("ezproxy.uni.edu/login") # 含 /
    assert is_hostname_mode("ezproxy.uni.edu")
    assert is_hostname_mode(".ezproxy.uni.edu")          # 前导点容忍
    assert is_hostname_mode("EZproxy.Uni.EDU")           # 大小写不敏感(域名)
    assert not is_hostname_mode("") and not is_hostname_mode(None)
    assert not is_hostname_mode("localhost")             # 无点 → 不认(避免误判裸词)

    # ② 主机名改写纯函数:点→连字符;既有连字符加倍;代理域前导点剥掉
    assert proxy_hostname("www.sciencedirect.com", "ezproxy.uni.edu") \
        == "www-sciencedirect-com.ezproxy.uni.edu"
    assert proxy_hostname("ars.els-cdn.com", "ezproxy.uni.edu") \
        == "ars-els--cdn-com.ezproxy.uni.edu"
    assert proxy_hostname("Pubs.ACS.org", ".ezproxy.uni.edu") == "pubs-acs-org.ezproxy.uni.edu"

    # ③ 默认零副作用:无前缀 / 无凭据 → 恒等
    assert rewrite_url_for_proxy(_SD, Config()) == _SD

    # ④ 前缀式:与 http_client 现实现【逐字节一致】(drop-in 委托的兼容性证明)
    cfg_p = Config(ezproxy_prefix=_PREFIX, institution_cookie="ezproxy=T",
                   institution_domains=["sciencedirect.com"])
    got = rewrite_url_for_proxy(_SD, cfg_p)
    assert got == _PREFIX + quote(_SD, safe="") == _hc_rewrite(_SD, cfg_p), got

    # ⑤ 主机名式:白名单域名 → host 改写,scheme/path/query/fragment 全保留
    cfg_h = Config(ezproxy_prefix="ezproxy.uni.edu", institution_cookie="ezproxy=T",
                   institution_domains=["sciencedirect.com", "els-cdn.com"])
    assert rewrite_url_for_proxy(_SD, cfg_h) \
        == "https://www-sciencedirect-com.ezproxy.uni.edu/science/article/pii/S0926860X05002504/pdfft"
    assert rewrite_url_for_proxy("http://www.sciencedirect.com/x?a=b&c=d#frag", cfg_h) \
        == "http://www-sciencedirect-com.ezproxy.uni.edu/x?a=b&c=d#frag"
    assert rewrite_url_for_proxy("https://ars.els-cdn.com/content/image/1-s2.0-x.pdf", cfg_h) \
        == "https://ars-els--cdn-com.ezproxy.uni.edu/content/image/1-s2.0-x.pdf"

    # ⑥ 守卫:OA/开放 API 域名恒等;非白名单恒等;显式端口恒等;畸形 URL 恒等
    assert rewrite_url_for_proxy("https://api.unpaywall.org/v2/x", cfg_h) \
        == "https://api.unpaywall.org/v2/x"
    assert rewrite_url_for_proxy("https://pubs.acs.org/doi/pdf/10.1021/x", cfg_h) \
        == "https://pubs.acs.org/doi/pdf/10.1021/x"
    assert rewrite_url_for_proxy("https://www.sciencedirect.com:8443/x", cfg_h) \
        == "https://www.sciencedirect.com:8443/x"
    assert rewrite_url_for_proxy("https://www.sciencedirect.com:443/x", cfg_h) \
        == "https://www.sciencedirect.com:443/x"      # 显式默认端口也保守恒等
    assert rewrite_url_for_proxy("not a url", cfg_h) == "not a url"
    assert rewrite_url_for_proxy("", cfg_h) == ""

    # ⑦ 白名单为空(骨架保守策略)→ 两种模式都恒等
    cfg_e = Config(ezproxy_prefix="ezproxy.uni.edu", institution_cookie="ezproxy=T")
    assert rewrite_url_for_proxy(_SD, cfg_e) == _SD
    cfg_e2 = Config(ezproxy_prefix=_PREFIX, institution_cookie="ezproxy=T")
    assert rewrite_url_for_proxy(_SD, cfg_e2) == _SD

    print("EZPROXY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
