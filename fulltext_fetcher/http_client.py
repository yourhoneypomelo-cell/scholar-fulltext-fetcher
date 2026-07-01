"""带重试/退避、按域限速、礼貌 UA 的 HTTP 客户端。

- 重试:对 429/5xx 指数退避,尊重 Retry-After。
- 限速:每个 host 维护最小请求间隔(线程安全),避免触发风控。
- 并发安全:多个 work 线程共享同一 client,共用限速状态。
"""
from __future__ import annotations

import ssl
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

import requests


# Crossref 等礼貌池会用响应头 X-Rate-Limit-Limit / X-Rate-Limit-Interval 通告配额。
# 据此自适应收紧该 host 的最小请求间隔时,留 20% 安全裕度(实际间隔 = 建议间隔 / 0.8),
# 让聚合请求速率稳稳落在配额内,显著降低 429。
_RATE_SAFETY = 0.8


def _is_ssl_error(exc: BaseException) -> bool:
    """是否为(通常瞬时的)SSL 失败,如 SSLEOFError('EOF occurred in violation of protocol')。

    这类错误在流量高峰/长连接复用下常瞬时出现,值得退避重试,且**不应计入主机熔断**——
    否则健康的 OA 源(openaire / base-search / zenodo / osf / unpaywall / semanticscholar 等)
    会被连续 2 次 SSL 抖动误判为故障、本次运行内被剔除,白白丢掉可回收的命中。
    """
    if isinstance(exc, (requests.exceptions.SSLError, ssl.SSLError)):
        return True
    s = f"{type(exc).__name__}: {exc}"
    return "SSLEOFError" in s or "EOF occurred in violation of protocol" in s


# ── 机构订阅 / EZproxy 接入钩子(可插拔,默认关闭)──────────────────────────
# 合规声明:以下逻辑仅供拥有【合法机构订阅】的用户、对其【有权访问】的内容使用,
# 用于在已获授权前提下经机构 EZproxy/SSO 正常取用全文;不得用于绕过付费墙或任何访问
# 授权。当 cfg 未配置 ezproxy_prefix / institution_cookie(默认)时,以下函数全部退化为
# 恒等变换,HTTP 行为与未启用时逐字节一致。详见项目根 机构订阅集成设计.md。

# 开放 API / OA 域名永不经机构代理:既避免破坏免费正门路径,也避免把机构会话 Cookie
# 泄露给与订阅无关的第三方服务。
_OPEN_ACCESS_HOSTS = (
    "api.unpaywall.org", "api.openalex.org", "api.crossref.org",
    "www.ebi.ac.uk", "export.arxiv.org", "arxiv.org", "api.biorxiv.org",
    "api.semanticscholar.org", "www.ncbi.nlm.nih.gov", "eutils.ncbi.nlm.nih.gov",
    "api.core.ac.uk", "doaj.org", "api.openaire.eu", "hal.science", "zenodo.org",
)


def _host_in(host: str, domains) -> bool:
    """host 是否等于某域名或为其子域(大小写不敏感,容忍前导点)。"""
    host = (host or "").lower()
    for d in domains or ():
        d = (d or "").lower().lstrip(".")
        if d and (host == d or host.endswith("." + d)):
            return True
    return False


def needs_institution_access(host: str, cfg) -> bool:
    """判断对某【原始目标 host】是否应走机构订阅通道(代理重写 + Cookie 注入)。

    - 未配置任何机构凭据(默认)→ 永远 False(零副作用)。
    - 开放 API / OA 域名 → 永远 False(免费正门路径绝不改写)。
    - 配置了 institution_domains 白名单 → 仅命中白名单的域名为 True。
    - 配置了凭据但白名单为空 → 骨架阶段保守返回 False(见 TODO)。
    """
    if not getattr(cfg, "ezproxy_prefix", None) and not getattr(cfg, "institution_cookie", None):
        return False
    h = (host or "").lower()
    if _host_in(h, _OPEN_ACCESS_HOSTS):
        return False
    allow = getattr(cfg, "institution_domains", None)
    if allow:
        return _host_in(h, allow)
    # TODO(机构订阅): 未显式给出白名单时的默认策略。生产实现可在此返回 True
    #   (即「凡非 OA 域名一律经机构通道」),但需先充分灰度,避免把无关请求误导入代理。
    #   骨架阶段一律保守返回 False,确保默认零副作用。
    return False


def rewrite_url_for_proxy(url: str, cfg) -> str:
    """URL 重写钩子:把出版商 URL 改写为经机构 EZproxy 取用的形式。

    这是「可插拔」的核心扩展点。默认(未配置 ezproxy_prefix,或该 host 无需机构访问)
    时返回原 url(恒等变换)。
    """
    prefix = getattr(cfg, "ezproxy_prefix", None)
    if not prefix:
        return url
    if not needs_institution_access(urlparse(url).netloc, cfg):
        return url
    # EZproxy 两种常见改写形式(按机构实际部署二选一):
    #   1) 前缀式(starting point URL): prefix + 原始URL
    #        https://login.ezproxy.uni.edu/login?url=https://www.sciencedirect.com/...
    #   2) 主机名改写式(proxy by hostname): host 内嵌机构后缀
    #        www.sciencedirect.com → www-sciencedirect-com.ezproxy.uni.edu
    # 下面给出形式 1 的最小可用骨架(最通用);形式 2 留作 TODO 按机构需要扩展。
    return prefix + quote(url, safe="")


class HttpClient:
    def __init__(self, config: Any, logger: Any):
        self.cfg = config
        self.log = logger
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.ua()})
        self._host_lock = threading.Lock()
        self._host_last: Dict[str, float] = {}
        self._host_interval: Dict[str, float] = {}
        # 熔断器:某 host 连接类错误连续达到阈值后,本次运行内直接跳过,避免反复超时拖慢整体。
        self._host_fail: Dict[str, int] = {}
        self._host_down: set = set()
        # 熔断阈值:连续 N 次「非 SSL」连接类失败才熔断。原为 2,过敏(高峰易误熔);提到 3。
        # SSL 瞬时失败(见 _is_ssl_error)一律不计入本计数,只退避重试。
        self._breaker_threshold = 3

    def set_host_interval(self, host: str, interval: float) -> None:
        """为特定 host 设定更严格的最小间隔(如 arXiv API 要求 3s)。"""
        self._host_interval[host] = interval

    def _note_ok(self, host: str) -> None:
        # 熔断计数为跨线程共享状态(多 work 线程共用同一 client),须在 _host_lock 下改写。
        with self._host_lock:
            if self._host_fail.get(host):
                self._host_fail[host] = 0

    def _note_fail(self, host: str) -> bool:
        """记录一次连接失败;返回该 host 是否已被熔断。"""
        # 读-改-写计数 + 首次熔断判定必须原子,否则并发下会丢增量或重复告警。
        with self._host_lock:
            n = self._host_fail.get(host, 0) + 1
            self._host_fail[host] = n
            tripped = n >= self._breaker_threshold
            newly_down = tripped and host not in self._host_down
            if tripped:
                self._host_down.add(host)
        if newly_down:  # 日志放到锁外,避免持锁期间被日志 handler 拖慢
            self.log.warning("host %s 连续 %d 次连接失败,本次运行内跳过(熔断)", host, n)
        return tripped

    def _respect_rate(self, url: str) -> None:
        host = urlparse(url).netloc
        interval = self._host_interval.get(host, self.cfg.per_host_interval)
        with self._host_lock:
            last = self._host_last.get(host, 0.0)
            now = time.time()
            wait = last + interval - now
            if wait > 0:
                time.sleep(wait)
            self._host_last[host] = time.time()

    @staticmethod
    def _parse_interval_seconds(raw: Any) -> float:
        """把限速头的 interval(如 '1s' / '1')解析成秒;无法解析返回 0。"""
        if not raw:
            return 0.0
        s = str(raw).strip().lower()
        if s.endswith("s"):
            s = s[:-1].strip()
        try:
            return float(s)
        except ValueError:
            return 0.0

    def _maybe_adapt_rate(self, host: str, r: Any) -> None:
        """尊重服务端限速头(Crossref 礼貌池会回 X-Rate-Limit-Limit / -Interval):
        据其把该 host 的最小请求间隔自适应【收紧】(留安全裕度),显著降低 429。
        只收紧、不放宽(绝不低于既有配置/默认),对不回该头的其它源零副作用。
        """
        try:
            headers = getattr(r, "headers", None) or {}
            limit = float(headers.get("X-Rate-Limit-Limit") or 0)
            secs = self._parse_interval_seconds(headers.get("X-Rate-Limit-Interval"))
            if limit <= 0 or secs <= 0:
                return
            interval = (secs / limit) / _RATE_SAFETY
            with self._host_lock:
                cur = self._host_interval.get(host, self.cfg.per_host_interval)
                if interval > cur:
                    self._host_interval[host] = interval
                    self.log.info("按限速头自适应:%s 最小间隔 → %.3fs (limit=%d/%.0fs)",
                                  host, interval, int(limit), secs)
        except Exception:  # noqa: BLE001 - 自适应限速绝不影响主请求
            return

    def get(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        stream: bool = False,
        allow_redirects: bool = True,
    ) -> Optional[requests.Response]:
        # 机构订阅接入(可选,默认关闭):基于【原始目标域名】判断是否走机构通道。
        # 默认未配置凭据时 needs_institution_access 恒为 False,以下两步均为空操作,行为不变。
        if needs_institution_access(urlparse(url).netloc, self.cfg):
            cookie = getattr(self.cfg, "institution_cookie", None)
            if cookie:
                # 仅对需机构访问的域名注入会话 Cookie(不外泄给 OA/第三方);调用方显式 headers 优先。
                headers = {"Cookie": cookie, **(headers or {})}
            url = rewrite_url_for_proxy(url, self.cfg)
        host = urlparse(url).netloc
        with self._host_lock:
            down = host in self._host_down
        if down:
            return None  # 已熔断,直接跳过
        for attempt in range(self.cfg.max_retries + 1):
            self._respect_rate(url)
            try:
                r = self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.cfg.timeout,
                    stream=stream,
                    allow_redirects=allow_redirects,
                )
                if r.status_code in (429, 500, 502, 503, 504):
                    ra = r.headers.get("Retry-After")
                    delay = float(ra) if (ra and ra.isdigit()) else float(2 ** attempt)
                    self.log.warning("HTTP %s %s -> 退避 %.1fs (第%d次)", r.status_code, url, min(delay, 30), attempt + 1)
                    r.close()
                    time.sleep(min(delay, 30))
                    continue
                self._note_ok(host)
                self._maybe_adapt_rate(host, r)
                return r
            except requests.RequestException as e:
                if _is_ssl_error(e):
                    # 瞬时 SSL 失败(如 SSLEOFError):指数退避重试,且【不计入熔断计数】,
                    # 避免高峰期把健康 OA 源因 2 次 SSL 抖动误熔、本次运行内被剔除而丢命中。
                    self.log.warning("SSL 瞬时失败 %s: %s -> 退避重试 (第%d次)", url, e, attempt + 1)
                    time.sleep(min(float(2 ** attempt), 8))
                    continue
                self.log.warning("请求异常 %s: %s", url, e)
                if self._note_fail(host):
                    return None  # 该 host 连续(非SSL)失败已熔断,不再重试
                time.sleep(min(float(2 ** attempt), 8))
        return None  # 重试耗尽,优雅返回 None(由调用方按"无候选"处理)

    def get_json(self, url: str, **kw: Any) -> Optional[Any]:
        r = self.get(url, **kw)
        if r is None or r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None


if __name__ == "__main__":  # 不联网 selftest: python -m fulltext_fetcher.http_client
    # 用假 session 注入「先抛 SSLError / ConnectionError 再成功」的脚本,验证重试与熔断策略。
    _real_sleep = time.sleep
    time.sleep = lambda *a, **k: None          # 关闭真实退避睡眠,selftest 秒过;末尾还原

    class _NullLog:
        def warning(self, *a: Any, **k: Any) -> None: ...
        def info(self, *a: Any, **k: Any) -> None: ...

    class _Cfg:
        def __init__(self, max_retries: int = 3, per_host_interval: float = 0.0,
                     timeout: float = 5.0) -> None:
            self.max_retries = max_retries
            self.per_host_interval = per_host_interval
            self.timeout = timeout
            self.ezproxy_prefix = None          # 机构订阅默认关 → needs_institution_access 恒 False
            self.institution_cookie = None
            self.institution_domains = []

        def ua(self) -> str:
            return "selftest-ua/1.0"

    class _Resp:
        def __init__(self, status: int = 200) -> None:
            self.status_code = status
            self.headers: Dict[str, str] = {}

        def close(self) -> None: ...

    class _Session:
        """按脚本逐次 返回响应 / 抛异常;记录调用次数与最终 headers(供 UA 检查)。"""

        def __init__(self, script) -> None:
            self.script = list(script)
            self.headers: Dict[str, str] = {}
            self.calls = 0

        def get(self, url, **kw):  # noqa: ANN001
            self.calls += 1
            item = self.script.pop(0) if self.script else _Resp(200)
            if isinstance(item, BaseException):
                raise item
            return item

    def _client(script, **cfgkw):
        c = HttpClient(_Cfg(**cfgkw), _NullLog())
        c.session = _Session(script)   # type: ignore[assignment]
        return c

    _SSL = requests.exceptions.SSLError("EOF occurred in violation of protocol (_ssl.c:1000)")
    _host = "api.openaire.eu"

    try:
        # ① SSL 瞬时失败 → 退避重试直到成功;SSL 不计入熔断,host 未被剔除
        c1 = _client([_SSL, _SSL, _Resp(200)], max_retries=3)
        r1 = c1.get(f"https://{_host}/search/publications")
        assert r1 is not None and r1.status_code == 200, r1
        assert c1.session.calls == 3, c1.session.calls
        assert _host not in c1._host_down and c1._host_fail.get(_host, 0) == 0, c1._host_fail

        # ② SSL 次数超过旧阈值(2)也绝不熔断(核心修复:高峰不误熔健康源)
        c2 = _client([_SSL, _SSL, _SSL, _Resp(200)], max_retries=5)
        r2 = c2.get("https://zenodo.org/api/records")
        assert r2 is not None and r2.status_code == 200, r2
        assert "zenodo.org" not in c2._host_down, c2._host_down

        # ③ SSL 重试耗尽 → 返回 None,但仍不熔断(下条输入还会再试该 host)
        c3 = _client([_SSL, _SSL, _SSL], max_retries=2)   # max_retries=2 → 3 次尝试全 SSL
        r3 = c3.get("https://api.osf.io/v2/nodes")
        assert r3 is None and "api.osf.io" not in c3._host_down, (r3, c3._host_down)
        assert c3.session.calls == 3, c3.session.calls

        # ④ SSLEOFError 按消息识别(即便被包成非 SSLError 类型)
        assert _is_ssl_error(requests.exceptions.ConnectionError(
            "('Connection aborted.', SSLEOFError(8, 'EOF occurred in violation of protocol'))"))
        assert _is_ssl_error(_SSL) and _is_ssl_error(ssl.SSLError("x"))
        assert not _is_ssl_error(requests.exceptions.ConnectionError("Connection refused"))
        assert not _is_ssl_error(requests.exceptions.Timeout("read timed out"))

        # ⑤ 非 SSL 连接错仍会按阈值(3)熔断(保护:真故障主机不反复空转)
        c5 = _client([requests.exceptions.ConnectionError("refused")] * 10, max_retries=10)
        r5 = c5.get("https://dead.example.test/x")
        assert r5 is None and "dead.example.test" in c5._host_down, (r5, c5._host_down)
        assert c5.session.calls == 3, c5.session.calls        # 阈值 3 → 第 3 次即熔断

        # ⑥ 429 退避后成功(既有行为保持)
        c6 = _client([_Resp(429), _Resp(200)], max_retries=3)
        r6 = c6.get("https://api.crossref.org/works")
        assert r6 is not None and r6.status_code == 200, r6
        assert c6.session.calls == 2, c6.session.calls

        # ⑦ 首次即成功 → 单次调用、host 记 ok
        c7 = _client([_Resp(200)])
        assert c7.get("https://api.unpaywall.org/v2/x").status_code == 200
        assert c7.session.calls == 1

        # ⑧ 尊重 Crossref 限速头 X-Rate-Limit-*:自适应【收紧】该 host 最小间隔(只收紧不放宽)
        c8 = _client([_Resp(200)])
        c8.session.script[0].headers = {"X-Rate-Limit-Limit": "1", "X-Rate-Limit-Interval": "2s"}
        r8 = c8.get("https://api.crossref.org/works")
        assert r8 is not None and abs(c8._host_interval.get("api.crossref.org", 0.0) - 2.5) < 1e-9, \
            c8._host_interval                      # interval = (2/1)/0.8 = 2.5
        # 宽松预算(50/1s → 0.025s)绝不放宽默认 0.34s(只收紧)
        c8b = _client([_Resp(200)], per_host_interval=0.34)
        c8b.session.script[0].headers = {"X-Rate-Limit-Limit": "50", "X-Rate-Limit-Interval": "1s"}
        c8b.get("https://api.crossref.org/works")
        assert "api.crossref.org" not in c8b._host_interval, c8b._host_interval

        # ⑨ interval 解析:'1s'/'1'/空/畸形
        assert HttpClient._parse_interval_seconds("1s") == 1.0
        assert HttpClient._parse_interval_seconds("2") == 2.0
        assert HttpClient._parse_interval_seconds("") == 0.0
        assert HttpClient._parse_interval_seconds("abc") == 0.0

        print("HTTP_CLIENT_OK")
    finally:
        time.sleep = _real_sleep
