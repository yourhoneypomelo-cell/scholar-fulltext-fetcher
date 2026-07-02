"""机构订阅(路线A)离线 mock 自检:不联网、不需要任何真实凭据。

覆盖(全部用假 session/client 注入,零网络):
  ① 默认零副作用:三字段全空 → needs_institution_access 恒 False、URL 不改写、不注入 Cookie,
     与未启用逐字节一致;
  ② 白名单分流:Cookie 只注入白名单域名;OA/开放 API 域名永不改写、永不带机构 Cookie(防泄露);
  ③ EZproxy 前缀式改写:白名单域名 URL → prefix + quote(url);
  ④ 凭据缺失/无效时的"不产假阳"纪律:出版商直链回 401 → download_pdf 优雅判失败(http-401)、
     不落盘、绝不记 success;回 200 登录页 HTML → 同样判失败(landing/not-pdf)、不落盘;
  ⑤ publisher_direct 源门:institutional=False 绝不产候选(默认关)。

通过打印 INSTITUTIONAL_OK(run_all_selftests.py 依此判 PASS)。
运行:python -m fulltext_fetcher.selftest_institutional
"""
from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, Optional
from urllib.parse import quote

from .config import Config
from .download import download_pdf
from .http_client import HttpClient, needs_institution_access, rewrite_url_for_proxy


class _NullLog:
    def info(self, *a: Any, **k: Any) -> None: ...
    def warning(self, *a: Any, **k: Any) -> None: ...


class _Resp:
    """最小 requests.Response 替身(status/headers/iter_content/close)。"""

    def __init__(self, status: int = 200, data: bytes = b"",
                 ct: str = "text/html; charset=utf-8"):
        self.status_code = status
        self._data = data
        self.headers: Dict[str, str] = {"Content-Type": ct} if ct else {}

    def iter_content(self, n: int):
        for i in range(0, len(self._data), n):
            yield self._data[i:i + n]

    def close(self) -> None: ...


class _CaptureSession:
    """记录 HttpClient 实际发出的 (url, headers) 的假 requests.Session。"""

    def __init__(self):
        self.headers: Dict[str, str] = {}
        self.calls: list = []

    def get(self, url: str, params: Any = None, headers: Optional[dict] = None,
            timeout: Any = None, stream: bool = False, allow_redirects: bool = True):
        self.calls.append({"url": url, "headers": dict(headers or {})})
        return _Resp(200, b"ok", ct="")


def _mk_client(cfg: Config) -> HttpClient:
    c = HttpClient(cfg, _NullLog())
    c.session = _CaptureSession()  # type: ignore[assignment]
    return c


class _401Client:
    """所有 GET 一律 401(模拟无凭据打订阅直链);兼容 download 契约。"""

    def __init__(self):
        self.calls = 0

    def get(self, url: str, headers: Optional[dict] = None, stream: bool = True):
        self.calls += 1
        return _Resp(401, b"", ct="text/html")


class _LoginPageClient:
    """所有 GET 回 200 登录页 HTML(模拟 Cookie 过期被重定向到登录页)。"""

    def get(self, url: str, headers: Optional[dict] = None, stream: bool = True):
        return _Resp(200, b"<html><body>Institutional Login required</body></html>")


class _DlCfg:
    """download_pdf 所需的最小 cfg(离线:关闭 curl_cffi/render 等联网兜底)。"""
    min_pdf_bytes = 8
    max_pdf_bytes = 80 * 1024 * 1024
    use_curl_cffi = False
    render_fallback = False
    content_qc = True
    enable_scihub = False


class _Paper:
    doi = "10.1016/j.apcata.2005.04.024"
    arxiv_id = None
    title = "institutional selftest paper"


class _Cand:
    def __init__(self, url: str):
        self.url, self.source, self.kind = url, "publisher_direct:elsevier", "pdf"
        self.version = self.license = None
        self.confidence = 72


_SD_PDF = "https://www.sciencedirect.com/science/article/pii/S0926860X05002504/pdfft"


def _selftest() -> int:
    log = _NullLog()

    # ── ① 默认零副作用:三字段全空(真实默认 Config)→ 恒等、无 Cookie ──
    cfg0 = Config()
    assert cfg0.institutional is False
    assert cfg0.ezproxy_prefix is None and cfg0.institution_cookie is None
    assert cfg0.institution_domains == []
    assert not needs_institution_access("www.sciencedirect.com", cfg0)
    assert rewrite_url_for_proxy(_SD_PDF, cfg0) == _SD_PDF
    c0 = _mk_client(cfg0)
    c0.get(_SD_PDF)
    assert c0.session.calls[0]["url"] == _SD_PDF, c0.session.calls          # URL 未改写
    assert "Cookie" not in c0.session.calls[0]["headers"], c0.session.calls  # 未注入 Cookie

    # ── ② 白名单分流 + OA 域名豁免(Cookie 绝不泄给第三方/开放 API)──
    cfg2 = Config(institutional=True,
                  institution_cookie="ezproxy=TOK123; session=abc",
                  institution_domains=["sciencedirect.com"])
    assert needs_institution_access("www.sciencedirect.com", cfg2)
    assert needs_institution_access("sciencedirect.com", cfg2)              # 裸域也命中
    assert not needs_institution_access("pubs.acs.org", cfg2)               # 不在白名单
    assert not needs_institution_access("api.unpaywall.org", cfg2)          # OA 豁免
    assert not needs_institution_access("api.crossref.org", cfg2)
    c2 = _mk_client(cfg2)
    c2.get(_SD_PDF)                                                          # 白名单域 → 注入
    assert c2.session.calls[0]["headers"].get("Cookie") == "ezproxy=TOK123; session=abc"
    c2.get("https://api.unpaywall.org/v2/10.1016/x?email=a@b.c")             # OA → 不注入
    assert "Cookie" not in c2.session.calls[1]["headers"], c2.session.calls[1]
    c2.get("https://pubs.acs.org/doi/pdf/10.1021/x")                         # 非白名单 → 不注入
    assert "Cookie" not in c2.session.calls[2]["headers"], c2.session.calls[2]
    # 凭据配了但白名单为空 → 骨架保守:不改写任何域名(防误导流量进代理)
    cfg2b = Config(institution_cookie="k=v")
    assert not needs_institution_access("www.sciencedirect.com", cfg2b)

    # ── ③ EZproxy 前缀式改写(白名单内改写;调用方显式 headers 优先级不破坏)──
    prefix = "https://login.ezproxy.uni.edu/login?url="
    cfg3 = Config(institutional=True, ezproxy_prefix=prefix,
                  institution_cookie="ezproxy=TOK",
                  institution_domains=["sciencedirect.com"])
    assert rewrite_url_for_proxy(_SD_PDF, cfg3) == prefix + quote(_SD_PDF, safe="")
    assert rewrite_url_for_proxy("https://api.openalex.org/works/x", cfg3) \
        == "https://api.openalex.org/works/x"                                # OA 恒等
    c3 = _mk_client(cfg3)
    c3.get(_SD_PDF)
    sent = c3.session.calls[0]
    assert sent["url"].startswith(prefix) and quote(_SD_PDF, safe="") in sent["url"], sent
    assert sent["headers"].get("Cookie") == "ezproxy=TOK", sent

    # ── ④ 不产假阳:401 / 登录页 HTML 都优雅判失败、不落盘、不记 success ──
    with tempfile.TemporaryDirectory() as d:
        cli401 = _401Client()
        p, n, err = download_pdf(_Cand(_SD_PDF), _Paper(), d, cli401, _DlCfg(), log, "i1")
        assert p is None and err == "http-401", (p, n, err)                  # 明确失败原因
        assert os.listdir(d) == [], "401 绝不落盘"
        assert cli401.calls >= 1

        p2, n2, err2 = download_pdf(_Cand(_SD_PDF), _Paper(), d, _LoginPageClient(),
                                    _DlCfg(), log, "i2")
        assert p2 is None and err2, (p2, n2, err2)                           # 登录页≠PDF → 失败
        assert "landing" in err2 or "not-pdf" in err2, err2
        assert os.listdir(d) == [], "登录页 HTML 绝不落盘"

    # ── ⑤ publisher_direct 源门:institutional=False 绝不产候选(默认关)──
    from .models import Paper
    from .sources.publisher_direct import PublisherDirectSource

    class _Ctx:
        client = None
        log = None
        events = None

        def __init__(self, inst: bool):
            self.cfg = Config(institutional=inst)

    src = PublisherDirectSource()
    assert src.find_candidates(Paper(doi="10.1038/s41586-020-2649-2"), _Ctx(False)) == []
    on = src.find_candidates(Paper(doi="10.1038/s41586-020-2649-2"), _Ctx(True))
    assert on and all(c.url.startswith("https://") for c in on), on

    print("INSTITUTIONAL_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
