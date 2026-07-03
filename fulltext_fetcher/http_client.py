"""带重试/退避、按域限速、礼貌 UA 的 HTTP 客户端。

- 重试:对 429/5xx 指数退避,尊重 Retry-After。
- 限速:每个 host 维护最小请求间隔(线程安全),避免触发风控。
- 并发安全:多个 work 线程共享同一 client,共用限速状态。
- 可选 impersonate 取回(默认关):启用后改用 curl_cffi(伪装真实浏览器 TLS/JA3/HTTP2 指纹)
  发起 GET,专治「定位到 OA 副本却因指纹被判机器人而 403/挂断」;复用本类既有的重试/退避/
  限速/熔断逻辑,curl_cffi 的网络异常统一归一到 requests 异常族。开关经 cfg.impersonate_http
  (软读,默认无该字段=关)或环境变量 FTF_IMPERSONATE_HTTP=1 打开;**默认关 + 缺 curl_cffi 时
  优雅降级到普通 requests**,行为与未启用时逐字节一致(可一键回退)。curl_cffi 为可选依赖、
  函数内延迟导入,绝不进父包强制依赖(与 scholar.fetcher / download 的 curl_cffi 用法同栈同哲学)。
"""
from __future__ import annotations

import os
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


# ── 可选 impersonate 取回(curl_cffi,默认关)─────────────────────────────────
# 目的:出版商/CDN 对无浏览器指纹的 requests 直连常以 TLS/JA3/HTTP2 指纹判机器人而 403/挂断
# (「定位到 OA 副本却下不下来」的一大成因)。启用后本客户端改用 curl_cffi 伪装真实浏览器指纹发
# 起 GET,并【复用】本类既有的重试/退避/限速/熔断——curl_cffi 的网络异常统一归一到 requests 异常
# 族(见 _do_get),故上层所有分支(SSL 豁免/退避/熔断/限速头自适应)零改动即生效。
# curl_cffi 为可选依赖:模块级懒探测并缓存(None=未探测 / False=不可用 / 模块=可用),
# 缺库自动降级回普通 requests,默认零副作用、可一键回退(见 __init__ 开关)。
_CURL_CFFI: Any = None


def _curl_cffi_requests() -> Optional[Any]:
    """返回 curl_cffi.requests 模块(可用)或 None(未安装/导入失败)。结果模块级缓存,只探测一次。"""
    global _CURL_CFFI
    if _CURL_CFFI is None:
        try:
            from curl_cffi import requests as _creq  # 延迟导入:可选依赖,不进父包强制依赖
            _CURL_CFFI = _creq
        except Exception:  # noqa: BLE001 - 缺库/导入异常一律视作不可用(降级普通 requests)
            _CURL_CFFI = False
    return _CURL_CFFI or None


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

    EZproxy 两种常见改写形式均已支持,实现委托给 ezproxy.py(纯字符串变换、离线可测,
    按 ezproxy_prefix 的形态自动识别;前缀式输出与旧内联实现逐字节一致):
      1) 前缀式(starting point URL): prefix + quote(原始URL)
           https://login.ezproxy.uni.edu/login?url=https%3A//www.sciencedirect.com/...
      2) 主机名改写式(proxy by hostname): 值为裸代理域(如 "ezproxy.uni.edu")时,
           www.sciencedirect.com → www-sciencedirect-com.ezproxy.uni.edu
    """
    prefix = getattr(cfg, "ezproxy_prefix", None)
    if not prefix:
        return url
    if not needs_institution_access(urlparse(url).netloc, cfg):
        return url
    try:
        from .ezproxy import rewrite_url_for_proxy as _rw  # 延迟导入,避免模块级循环依赖
        return _rw(url, cfg)
    except ImportError:                       # 极端环境缺模块 → 退回旧内联前缀式,主路径不倒
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

        # ── 可选 impersonate 取回开关(默认关,可一键回退)──────────────────────
        # 软读:cfg.impersonate_http(父包 Config 默认无此字段=关) 或 环境变量 FTF_IMPERSONATE_HTTP=1。
        # 目标浏览器指纹软读 cfg.impersonate(缺省 "chrome",与 scholar 子包同名字段对齐)。
        # curl_cffi 底层 libcurl 句柄非线程安全,故每线程独立 Session(threading.local 惰性创建)。
        self._impersonate_http: bool = self._resolve_impersonate_flag(config)
        self._impersonate_target: str = getattr(config, "impersonate", None) or "chrome"
        self._imp_local = threading.local()

        # ── OpenAlex Content API 多 key 轮换池($1/天预算按 key 独立)────────────
        # 池 = cfg.openalex_keys(若给)否则退化为 [cfg.openalex_key](单 key,行为与引入前一致)。
        # _oa_key_idx 单调前进:当前 key 预算耗尽(429+长 Retry-After)即换下一把;全部耗尽才熔断
        # content.openalex.org。跨线程共享,推进受 _host_lock 保护(防并发双跳)。
        _pool = [k.strip() for k in (getattr(config, "openalex_keys", None) or []) if k and k.strip()]
        if not _pool:
            _single = getattr(config, "openalex_key", None)
            _pool = [_single] if _single else []
        self._oa_keys: list = _pool
        self._oa_key_idx = 0

    @staticmethod
    def _resolve_impersonate_flag(cfg: Any) -> bool:
        """impersonate 取回是否启用:cfg.impersonate_http 为真,或 env FTF_IMPERSONATE_HTTP=1。
        两者皆无(默认)→ False(HTTP 行为与未启用逐字节一致)。"""
        if getattr(cfg, "impersonate_http", False):
            return True
        return os.environ.get("FTF_IMPERSONATE_HTTP") == "1"

    def _imp_session(self, creq: Any) -> Any:
        """取当前线程的 curl_cffi Session(惰性创建,impersonate 目标注入构造)。每线程独立,
        规避 libcurl 句柄跨线程共享;失败/无该属性时退回模块级 creq(仍可用,仅少连接复用)。"""
        s = getattr(self._imp_local, "session", None)
        if s is None:
            try:
                s = creq.Session(impersonate=self._impersonate_target)
            except Exception:  # noqa: BLE001 - 构造失败(版本差异)→ 用模块级函数兜底
                s = creq
            self._imp_local.session = s
        return s

    def _do_get(self, url: str, *, params: Any, headers: Any, stream: bool,
                allow_redirects: bool) -> Any:
        """发起一次底层 GET。默认走 requests.Session(既有行为);启用 impersonate 且 curl_cffi
        可用时改走 curl_cffi(伪装浏览器 TLS/JA3/HTTP2 指纹)。curl_cffi 的网络异常统一转成
        requests.RequestException,以复用上层既有 SSL 豁免/退避/熔断判定(不改任何既有分支)。
        缺库 / 关闭时逐字节等价于原 self.session.get。"""
        if self._impersonate_http:
            creq = _curl_cffi_requests()
            if creq is not None:
                try:
                    return self._imp_session(creq).get(
                        url, params=params, headers=headers, timeout=self.cfg.timeout,
                        stream=stream, allow_redirects=allow_redirects)
                except requests.RequestException:
                    raise                          # 已是 requests 异常族:直接上抛,交既有分支处理
                except Exception as e:  # noqa: BLE001 - curl_cffi.*/CurlError → 归一到 requests 异常族
                    # 保留原始类型名与消息:含 "EOF occurred in violation of protocol" 时
                    # _is_ssl_error 仍能据消息识别为瞬时 SSL(不计入熔断),与 requests 路径一致。
                    raise requests.ConnectionError(
                        f"curl_cffi: {type(e).__name__}: {e}") from e
        return self.session.get(
            url, params=params, headers=headers, timeout=self.cfg.timeout,
            stream=stream, allow_redirects=allow_redirects)

    def _oa_current_key(self) -> Optional[str]:
        """当前 OpenAlex Content key:轮换池非空 → 池内当前把(全耗尽 → None);
        池空 → 活读 cfg.openalex_key 单 key 兜底(兼容运行中注入 cfg 的调用方/selftest)。"""
        with self._host_lock:
            if self._oa_keys:
                return self._oa_keys[self._oa_key_idx] if self._oa_key_idx < len(self._oa_keys) else None
        return getattr(self.cfg, "openalex_key", None)

    def _oa_rotate_key(self, spent_key: str) -> bool:
        """把预算耗尽的 spent_key 轮换掉:切到下一把 → True;池已用尽/单 key 无可换 → False。
        CAS 语义:仅当 spent_key 仍是当前把时才前进;另一线程已切过 → 直接 True(不双跳)。"""
        with self._host_lock:
            if not self._oa_keys:
                return False
            if self._oa_key_idx >= len(self._oa_keys):
                return False
            if self._oa_keys[self._oa_key_idx] != spent_key:
                return True                       # 并发下别的线程已轮换
            self._oa_key_idx += 1
            return self._oa_key_idx < len(self._oa_keys)

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
        # OpenAlex Content API 凭据单点注入 + 多 key 轮换(openalex_content 源):候选/日志/产物
        # 里的 URL 一律不带 api_key(防泄密),仅在真正发请求的这一刻对 content.openalex.org 域补上
        # 【轮换池当前把】($1/天预算按 key 独立;当前把耗尽即换下一把,全耗尽才熔断该域)。
        # 调用方已显式给 api_key(params 或 URL 内)则绝不注入/轮换。其它域名零影响。
        _oa_inject = (urlparse(url).netloc == "content.openalex.org"
                      and "api_key=" not in url and "api_key" not in (params or {}))
        host = urlparse(url).netloc
        with self._host_lock:
            down = host in self._host_down
        if down:
            return None  # 已熔断,直接跳过
        for attempt in range(self.cfg.max_retries + 1):
            if _oa_inject:
                _oak = self._oa_current_key()
                if _oak:
                    params = {**(params or {}), "api_key": _oak}
            self._respect_rate(url)
            try:
                r = self._do_get(
                    url,
                    params=params,
                    headers=headers,
                    stream=stream,
                    allow_redirects=allow_redirects,
                )
                if r.status_code in (429, 500, 502, 503, 504):
                    ra = r.headers.get("Retry-After")
                    delay = float(ra) if (ra and ra.isdigit()) else float(2 ** attempt)
                    # 长 Retry-After(>5min)= 本次运行内对当前凭据重试注定徒劳(典型:OpenAlex
                    # Content API 日预算耗尽回 429 + Retry-After≈到 UTC 午夜的秒数)。退避上限才
                    # 30s,死磕只会把批量跑的每条 miss 拖慢 `30s×重试数`。处置:轮换池还有下一把
                    # key → 立即换 key 重试(host 不熔断);无可换 → 熔断该 host,快速失败、其余源
                    # 照常兜底,预算重置后下次运行自愈。
                    if delay > 300:
                        r.close()
                        _spent = (params or {}).get("api_key")
                        if _oa_inject and _spent and self._oa_rotate_key(_spent):
                            self.log.warning("OpenAlex key %s… 日预算耗尽(429, Retry-After=%.0fs)"
                                             "→ 轮换下一把重试", str(_spent)[:6], delay)
                            continue
                        self.log.warning("HTTP %s %s Retry-After=%.0fs(远超退避上限)→ 本次运行内"
                                         "跳过该 host(如为 API 日预算耗尽,次日自动恢复)",
                                         r.status_code, url, delay)
                        with self._host_lock:
                            self._host_down.add(host)
                        return None
                    self.log.warning("HTTP %s %s -> 退避 %.1fs (第%d次)", r.status_code, url, min(delay, 30), attempt + 1)
                    r.close()
                    time.sleep(min(delay, 30))
                    continue
                if _oa_inject and r.status_code in (401, 403):
                    # 池内当前把被拒(撤销/失效/无权限)→ 轮换下一把重试,防一把死 key 卡死整池;
                    # 无可换(池空/已尽/调用方自带 key)→ 照旧把响应交上层按失败处理。
                    _spent = (params or {}).get("api_key")
                    if _spent and self._oa_rotate_key(_spent):
                        self.log.warning("OpenAlex key %s… 被拒(HTTP %d,疑似失效)→ 轮换下一把重试",
                                         str(_spent)[:6], r.status_code)
                        r.close()
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
                     timeout: float = 5.0, impersonate_http: bool = False,
                     impersonate: str = "chrome") -> None:
            self.max_retries = max_retries
            self.per_host_interval = per_host_interval
            self.timeout = timeout
            self.ezproxy_prefix = None          # 机构订阅默认关 → needs_institution_access 恒 False
            self.institution_cookie = None
            self.institution_domains = []
            self.impersonate_http = impersonate_http   # 可选 impersonate 取回开关(默认关)
            self.impersonate = impersonate             # curl_cffi 伪装目标

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
            self.last_kw: Dict[str, Any] = {}   # 最近一次 get 的关键字参数(供注入类断言)

        def get(self, url, **kw):  # noqa: ANN001
            self.calls += 1
            self.last_kw = kw
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

        # ⑥b 429 + 超长 Retry-After(>300s,如 OpenAlex Content API 日预算耗尽给出的"到 UTC 午夜"):
        #     不做注定徒劳的 30s×N 重试,单次即熔断该 host、快速返回 None(其余源照常兜底)
        c6b = _client([_Resp(429)] * 5, max_retries=4)
        c6b.session.script[0].headers = {"Retry-After": "28394"}
        r6b = c6b.get("https://content.openalex.org/works/W1.pdf")
        assert r6b is None and c6b.session.calls == 1, (r6b, c6b.session.calls)
        assert "content.openalex.org" in c6b._host_down, c6b._host_down
        # 同 host 后续请求直接跳过(零请求),不再拖慢批量跑
        assert c6b.get("https://content.openalex.org/works/W2.pdf") is None
        assert c6b.session.calls == 1, c6b.session.calls
        # 常规短 Retry-After(可数秒)仍走既有退避重试路径,行为不变
        c6c = _client([_Resp(429), _Resp(200)], max_retries=3)
        c6c.session.script[0].headers = {"Retry-After": "2"}
        assert c6c.get("https://api.crossref.org/works").status_code == 200
        assert c6c.session.calls == 2, c6c.session.calls

        # ⑥c OpenAlex Content 多 key 轮换:当前把预算耗尽(429+长 Retry-After)→ 换下一把立即
        #     重试(host 不熔断、新 key 注入生效);池全耗尽才熔断
        c6d = _client([_Resp(429), _Resp(200)], max_retries=3)
        c6d.session.script[0].headers = {"Retry-After": "28394"}
        c6d._oa_keys = ["K1", "K2"]; c6d._oa_key_idx = 0
        r6d = c6d.get("https://content.openalex.org/works/W1.pdf")
        assert r6d is not None and r6d.status_code == 200, r6d
        assert (c6d.session.last_kw.get("params") or {}).get("api_key") == "K2", \
            c6d.session.last_kw                      # 轮换后第二把生效
        assert "content.openalex.org" not in c6d._host_down and c6d._oa_key_idx == 1
        c6e = _client([_Resp(429)] * 2, max_retries=3)   # 池仅 1 把再耗尽 → 无可换 → 熔断
        c6e.session.script[0].headers = {"Retry-After": "28394"}
        c6e._oa_keys = ["K1"]; c6e._oa_key_idx = 0
        assert c6e.get("https://content.openalex.org/works/W1.pdf") is None
        assert "content.openalex.org" in c6e._host_down and c6e.session.calls == 1
        c6f = _client([_Resp(200)])                      # 首次请求即注入池内当前把
        c6f._oa_keys = ["P1"]; c6f._oa_key_idx = 0
        c6f.get("https://content.openalex.org/works/W1.pdf")
        assert (c6f.session.last_kw.get("params") or {}).get("api_key") == "P1", c6f.session.last_kw
        # ⑥g 死 key(401/403,如被撤销/失效)→ 轮换下一把重试,防一把坏 key 卡死整池
        c6g = _client([_Resp(403), _Resp(200)], max_retries=3)
        c6g._oa_keys = ["BAD", "GOOD"]; c6g._oa_key_idx = 0
        r6g = c6g.get("https://content.openalex.org/works/W1.pdf")
        assert r6g is not None and r6g.status_code == 200 and c6g._oa_key_idx == 1, r6g
        assert (c6g.session.last_kw.get("params") or {}).get("api_key") == "GOOD", c6g.session.last_kw
        # 非 content 域的 401/403 不触发轮换(该逻辑仅限 openalex_content 注入路径)
        c6h = _client([_Resp(403)], max_retries=3)
        c6h._oa_keys = ["K1", "K2"]; c6h._oa_key_idx = 0
        assert c6h.get("https://api.crossref.org/works").status_code == 403 and c6h._oa_key_idx == 0
        # __init__ 池装配:openalex_keys 优先(裁剪/去空),否则退化单 openalex_key
        _pc = _Cfg(); _pc.openalex_keys = [" A ", "", "B"]         # type: ignore[attr-defined]
        assert HttpClient(_pc, _NullLog())._oa_keys == ["A", "B"]
        _ps = _Cfg(); _ps.openalex_key = "SOLO"                    # type: ignore[attr-defined]
        assert HttpClient(_ps, _NullLog())._oa_keys == ["SOLO"]
        assert HttpClient(_Cfg(), _NullLog())._oa_keys == []

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

        # ⑨b OpenAlex Content API 凭据单点注入(openalex_content 源配套):
        #    仅 content.openalex.org 域、且调用方未自带 api_key 时,请求时刻补注 cfg.openalex_key;
        #    候选/日志里的 URL 因此可以永远不携带 key(防泄入产物)。
        c9 = _client([_Resp(200)] * 4)
        c9.cfg.openalex_key = "SECRET"                       # 动态附加(生产 Config 自有该字段)
        c9.get("https://content.openalex.org/works/W1.pdf")
        assert (c9.session.last_kw.get("params") or {}).get("api_key") == "SECRET", \
            c9.session.last_kw                               # 注入生效
        c9.get("https://api.openalex.org/works/doi:10.1/x")  # 其它域名零影响
        assert "api_key" not in (c9.session.last_kw.get("params") or {}), c9.session.last_kw
        c9.get("https://content.openalex.org/works/W1.pdf", params={"api_key": "CALLER"})
        assert (c9.session.last_kw.get("params") or {}).get("api_key") == "CALLER", \
            "调用方显式 api_key 绝不覆盖"
        c9.get("https://content.openalex.org/works/W1.pdf?api_key=INURL")
        assert "api_key" not in (c9.session.last_kw.get("params") or {}), "URL 已带 key → 不再注入"
        c9nk = _client([_Resp(200)])                         # 未配置 key(getattr→None)→ 不注入
        c9nk.get("https://content.openalex.org/works/W2.pdf")
        assert "api_key" not in (c9nk.session.last_kw.get("params") or {}), c9nk.session.last_kw

        # ── ⑩ 可选 impersonate 取回(curl_cffi,默认关)——不改既有 requests 路径 ──
        # 注:`python -m` 下本文件以 __main__ 执行,与 import 的 fulltext_fetcher.http_client 是两份
        # 拷贝、各自一份模块全局。被测 HttpClient/_do_get 定义在 __main__,读的是 __main__ 的全局,
        # 故须对【当前运行模块自身】打桩(_H = 本模块对象),而非 import 的那份,stub 才生效。
        import sys as _sys
        _H = _sys.modules[__name__]

        class _FakeCurlSession:
            """假 curl_cffi Session:按【共享脚本】逐次吐响应/抛异常;记 impersonate 目标与调用数。"""

            def __init__(self, script, impersonate=None):
                self.script = script            # 共享同一 list(单线程 selftest),便于跨会话累计
                self.impersonate = impersonate
                self.calls = 0

            def get(self, url, **kw):  # noqa: ANN001
                self.calls += 1
                item = self.script.pop(0) if self.script else _Resp(200)
                if isinstance(item, BaseException):
                    raise item
                return item

        class _FakeCreq:
            """假 curl_cffi.requests 模块:Session(impersonate=...) 返回吃共享脚本的假会话。"""

            def __init__(self, script):
                self._script = list(script)
                self.sessions = []

            def Session(self, impersonate=None, **kw):  # noqa: ANN001,N802 - 对齐 curl_cffi API
                s = _FakeCurlSession(self._script, impersonate=impersonate)
                self.sessions.append(s)
                return s

        def _imp_client(script, creq, **cfgkw):
            """构造启用 impersonate 的 client,并注入假 curl_cffi 模块缓存;不替换 self.session。"""
            c = HttpClient(_Cfg(impersonate_http=True, **cfgkw), _NullLog())
            _H._CURL_CFFI = creq                 # 直接置模块级缓存(truthy→_curl_cffi_requests 返回它)
            return c

        _saved_curl = _H._CURL_CFFI
        _saved_env = os.environ.pop("FTF_IMPERSONATE_HTTP", None)
        try:
            # ⑩a 默认关:_impersonate_http False,走 requests(self.session);既有 ①–⑨ 已覆盖等价性
            _H._CURL_CFFI = None
            c_off = HttpClient(_Cfg(), _NullLog())
            assert c_off._impersonate_http is False, c_off._impersonate_http

            # ⑩b 开关经 env 打开:FTF_IMPERSONATE_HTTP=1 → 启用
            os.environ["FTF_IMPERSONATE_HTTP"] = "1"
            assert HttpClient._resolve_impersonate_flag(_Cfg()) is True
            os.environ.pop("FTF_IMPERSONATE_HTTP", None)
            assert HttpClient._resolve_impersonate_flag(_Cfg()) is False
            assert HttpClient._resolve_impersonate_flag(_Cfg(impersonate_http=True)) is True

            # ⑩c 开启但 curl_cffi 不可用(缓存=False)→ 降级 self.session,行为与既有一致
            _H._CURL_CFFI = False
            c_na = HttpClient(_Cfg(impersonate_http=True), _NullLog())
            c_na.session = _Session([_Resp(200)])   # type: ignore[assignment]
            rna = c_na.get("https://api.crossref.org/works")
            assert rna is not None and rna.status_code == 200 and c_na.session.calls == 1, rna

            # ⑩d 开启且 curl_cffi 可用:走 curl_cffi 路径;impersonate 目标注入构造;429 退避后成功
            fake1 = _FakeCreq([_Resp(429), _Resp(200)])
            c1 = _imp_client([], fake1, max_retries=3)
            r_imp = c1.get("https://pubs.acs.org/x")
            assert r_imp is not None and r_imp.status_code == 200, r_imp
            assert fake1.sessions and fake1.sessions[0].impersonate == "chrome", fake1.sessions
            assert fake1.sessions[0].calls == 2, fake1.sessions[0].calls   # 429 → 重试 → 200

            # ⑩e impersonate 目标可软配(cfg.impersonate=safari)
            fake2 = _FakeCreq([_Resp(200)])
            c2 = _imp_client([], fake2, impersonate="safari")
            assert c2.get("https://x.test/a").status_code == 200
            assert fake2.sessions[0].impersonate == "safari", fake2.sessions[0].impersonate

            # ⑩f curl_cffi 抛【自有】网络异常 → 归一为 requests.ConnectionError → 计入熔断(阈值 3)
            class _CurlErr(Exception):   # 模拟 curl_cffi.requests.errors.RequestsError / CurlError
                pass

            fake3 = _FakeCreq([_CurlErr("connect fail")] * 5)
            c3 = _imp_client([], fake3, max_retries=10)
            r3 = c3.get("https://dead.impersonate.test/x")
            assert r3 is None and "dead.impersonate.test" in c3._host_down, (r3, c3._host_down)
            assert fake3.sessions[0].calls == 3, fake3.sessions[0].calls   # 阈值 3 → 第 3 次熔断

            # ⑩g curl_cffi 抛的异常消息含 SSLEOF 特征 → 归一后仍被 _is_ssl_error 识别(不计入熔断)
            fake4 = _FakeCreq([
                _CurlErr("Recv failure: EOF occurred in violation of protocol"),
                _CurlErr("Recv failure: EOF occurred in violation of protocol"),
                _Resp(200)])
            c4 = _imp_client([], fake4, max_retries=3)
            r4 = c4.get("https://zenodo.org/api/records")
            assert r4 is not None and r4.status_code == 200, r4
            assert "zenodo.org" not in c4._host_down and c4._host_fail.get("zenodo.org", 0) == 0, \
                (c4._host_down, c4._host_fail)
        finally:
            _H._CURL_CFFI = _saved_curl
            if _saved_env is not None:
                os.environ["FTF_IMPERSONATE_HTTP"] = _saved_env
            else:
                os.environ.pop("FTF_IMPERSONATE_HTTP", None)

        # ── ⑪ EZproxy 改写钩子:委托 ezproxy.py 双模式(前缀式与旧内联逐字节一致 + 主机名式)──
        _SD = "https://www.sciencedirect.com/science/article/pii/S0926860X05002504/pdfft"
        _cfg11 = _Cfg()
        assert rewrite_url_for_proxy(_SD, _cfg11) == _SD          # 默认三字段空 → 恒等
        _cfg11.ezproxy_prefix = "https://login.ezproxy.uni.edu/login?url="
        _cfg11.institution_cookie = "ezproxy=T"
        _cfg11.institution_domains = ["sciencedirect.com"]
        assert rewrite_url_for_proxy(_SD, _cfg11) \
            == _cfg11.ezproxy_prefix + quote(_SD, safe="")        # 前缀式:与旧实现逐字节一致
        assert rewrite_url_for_proxy("https://api.unpaywall.org/v2/x", _cfg11) \
            == "https://api.unpaywall.org/v2/x"                   # OA 域名恒等
        _cfg11.ezproxy_prefix = "ezproxy.uni.edu"                 # 裸代理域 → 主机名改写式
        assert rewrite_url_for_proxy(_SD, _cfg11) \
            == "https://www-sciencedirect-com.ezproxy.uni.edu/science/article/pii/S0926860X05002504/pdfft"

        print("HTTP_CLIENT_OK")
    finally:
        time.sleep = _real_sleep
