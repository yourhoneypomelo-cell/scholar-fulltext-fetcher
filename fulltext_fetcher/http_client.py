"""带重试/退避、按域限速、礼貌 UA 的 HTTP 客户端。

- 重试:对 429/5xx 指数退避,尊重 Retry-After。
- 限速:每个 host 维护最小请求间隔(线程安全),避免触发风控。
- 并发安全:多个 work 线程共享同一 client,共用限速状态。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

import requests


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
        self._breaker_threshold = 2

    def set_host_interval(self, host: str, interval: float) -> None:
        """为特定 host 设定更严格的最小间隔(如 arXiv API 要求 3s)。"""
        self._host_interval[host] = interval

    def _note_ok(self, host: str) -> None:
        if self._host_fail.get(host):
            self._host_fail[host] = 0

    def _note_fail(self, host: str) -> bool:
        """记录一次连接失败;返回该 host 是否已被熔断。"""
        n = self._host_fail.get(host, 0) + 1
        self._host_fail[host] = n
        if n >= self._breaker_threshold:
            if host not in self._host_down:
                self._host_down.add(host)
                self.log.warning("host %s 连续 %d 次连接失败,本次运行内跳过(熔断)", host, n)
            return True
        return False

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
        if host in self._host_down:
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
                return r
            except requests.RequestException as e:
                self.log.warning("请求异常 %s: %s", url, e)
                if self._note_fail(host):
                    return None  # 该 host 已熔断,不再重试
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
