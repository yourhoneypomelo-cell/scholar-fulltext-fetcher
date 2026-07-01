"""分层取回 Google Scholar 结果页 —— 反爬核心(ARCH §3.5 + §4)。

⚠️ 合规声明
  直抓 Google Scholar 属灰色行为,违反其 ToS 与 robots.txt。本模块奉行「**默认最安全、
  避免触发优先**」:代理默认关(直连)、打码默认关(不硬刚验证码)、Scholar 抓取默认串行 +
  强限速/退避/冷却。能走正门(角度2 开放 API / 商业合规 SerpApi)就别自建直抓。使用者自负
  合规与法律责任;对外提供服务前须过法务(注意 nodriver=AGPL 等许可证传染)。默认路径下所有
  第三方反爬库均**函数内延迟导入**,缺失即优雅降级,绝不进父包强制依赖。

分层与降级(§4.2):
  ① curl_cffi 静态(L1,impersonate;无 curl_cffi 时降级普通 requests 并标注低隐蔽)
  ② 命中风控/需 JS → 升级浏览器 nodriver(L3)/ patchright(备选)
  ③ 仍弹 reCAPTCHA 且 captcha_enabled → captcha.solve_recaptcha 注入重试;默认关 → 记
     blocked 事件、跳过(不硬刚)
  翼A 每次升级前 proxy.rotate + 指数退避 +(命中风控)冷却;翼B 限速/行为。

引擎适配器契约(§3.5):FetchEngine.name / available() / get(target, ctx) -> FetchOutcome。
编排入口:
  fetch_serp(q, ctx) -> FetchOutcome     # 按 cfg.mode + engine_order 逐层取回一页 SERP
  fetch_html(url, ctx, *, allow_browser) # 通用单页取回(供 download 落地页兜底复用)

依赖(均为已就绪同包/父包,无新增强制依赖):models(FetchOutcome)、config、
serp.detect_captcha、proxy(可选)、captcha(可选)、logsetup 事件名。
"""
from __future__ import annotations

import importlib.util
import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlsplit

from .logsetup import EVENT_BLOCK, EVENT_CAPTCHA, EVENT_PROXY_ROTATE, EVENT_SERP_FETCH
from .models import FetchOutcome
from .serp import detect_captcha

_SCHOLAR_URL = "https://scholar.google.com/scholar"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
_SITEKEY_RE = re.compile(r'data-sitekey="([^"]+)"', re.I)


# ─────────────────────────── 小工具 ───────────────────────────
def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


def _sleep(sec: float) -> None:
    if sec and sec > 0:
        time.sleep(sec)


def _proxies(proxy_url: Optional[str]) -> Optional[Dict[str, str]]:
    return {"http": proxy_url, "https": proxy_url} if proxy_url else None


def _split_proxy(proxy_url: Optional[str]) -> tuple:
    """把代理 URL 拆成 ``(server, username, password)``。

    ``server`` 为 ``scheme://host[:port]``(**剥除内嵌凭据**),供 Chrome 命令行
    ``--proxy-server``(nodriver)与 Playwright ``proxy.server``(patchright)使用;
    ``username``/``password`` 单独返回,供原生支持代理鉴权的引擎(Playwright)填充。
    无代理或无法解析出 host → ``(None, None, None)``。
    注:Chrome 命令行 ``--proxy-server`` **不支持**内嵌账号密码,含鉴权的代理需引擎层
    单独处理(patchright 已支持;nodriver 仅注入 server,鉴权留待上层扩展)。
    """
    if not proxy_url:
        return None, None, None
    parts = urlsplit(proxy_url if "://" in proxy_url else "http://" + proxy_url)
    host = parts.hostname or ""
    if not host:
        return None, None, None
    scheme = parts.scheme or "http"
    server = f"{scheme}://{host}" + (f":{parts.port}" if parts.port else "")
    return server, parts.username, parts.password


def _cfg_get(ctx: Any, attr: str, default: Any) -> Any:
    cfg = getattr(ctx, "cfg", None)
    return getattr(cfg, attr, default) if cfg is not None else default


def _ua(ctx: Any) -> str:
    """取回用 User-Agent:优先 cfg.user_agent,缺省/空值回退模块内置 _UA。

    仅用于 curl_cffi 缺库时降级的普通 requests 路径(curl_cffi 自身用 impersonate 携带匹配
    指纹,不用此 UA)。UA 提为 ScholarConfig 字段后可按需覆盖;默认值与 _UA 一致、行为不变。
    """
    return _cfg_get(ctx, "user_agent", None) or _UA


def _current_proxy(ctx: Any) -> Optional[str]:
    pool = getattr(ctx, "proxy", None)
    try:
        return pool.current() if pool is not None and pool.available() else None
    except Exception:  # noqa: BLE001
        return None


def _emit(ctx: Any, event: str, **fields: Any) -> None:
    events = getattr(ctx, "events", None)
    if events is not None:
        try:
            events.emit(event, **fields)
        except Exception:  # noqa: BLE001 - 日志失败绝不影响主流程
            pass


def _warn(ctx: Any, msg: str) -> None:
    """best-effort 警告日志(无 log 或异常一律静默,绝不影响取回主流程)。"""
    log = getattr(ctx, "log", None)
    if log is not None:
        try:
            log.warning(msg)
        except Exception:  # noqa: BLE001
            pass


def _is_blocked(out: FetchOutcome) -> bool:
    """判断一次取回是否被风控/验证码拦截。

    统一交给 serp.detect_captcha 判定，覆盖：状态码 403/429/503（Google 对机器人的
    典型阻断/限流码）、``/sorry/`` 重定向、以及验证码/风控页 HTML 标志。
    （此前遗漏 403——Scholar 对数据中心 IP 常直接 403——会把「被拦」误判为普通失败，
    从而跳过冷却/换代理/升级浏览器的应对路径。）
    """
    if out is None:
        return False
    if out.blocked or out.captcha:
        return True
    return detect_captcha(out.html, out.final_url, out.status)


# ─────────────────────────── 引擎适配器 ───────────────────────────
class FetchEngine:
    """引擎适配器统一契约。子类实现 available()/get();全部第三方库函数内延迟导入。"""
    name: str = "base"

    def available(self) -> bool:
        return False

    def get(self, target: str, ctx: Any) -> FetchOutcome:  # noqa: ARG002
        raise NotImplementedError


class CurlCffiEngine(FetchEngine):
    """L1 静态取回:curl_cffi(TLS 指纹 impersonate);缺库 → 降级普通 requests(低隐蔽)。"""
    name = "curl_cffi"

    def available(self) -> bool:
        return _has_module("curl_cffi") or _has_module("requests")

    def get(self, target: str, ctx: Any) -> FetchOutcome:
        t0 = time.time()
        proxy = _current_proxy(ctx)
        impersonate = _cfg_get(ctx, "impersonate", "chrome")
        timeout = _cfg_get(ctx, "timeout", 30.0)
        try:
            try:
                from curl_cffi import requests as creq  # 延迟导入
                r = creq.get(target, impersonate=impersonate, timeout=timeout,
                             proxies=_proxies(proxy), allow_redirects=True)
                engine = "curl_cffi"
            except ImportError:
                import requests as rq  # 父包既有依赖;降级为普通 requests(低隐蔽)
                r = rq.get(target, timeout=timeout, proxies=_proxies(proxy),
                           headers={"User-Agent": _ua(ctx)}, allow_redirects=True)
                engine = "requests(low-stealth)"
            html = getattr(r, "text", None)
            status = getattr(r, "status_code", None)
            final = str(getattr(r, "url", target))
            return FetchOutcome(ok=(status == 200), html=html, final_url=final, status=status,
                                engine=engine, proxy_used=proxy, elapsed_ms=_ms(t0))
        except Exception as e:  # noqa: BLE001 - 网络异常降级为失败信封
            return FetchOutcome(ok=False, engine="curl_cffi", error=f"request failed: {e}",
                                proxy_used=proxy, elapsed_ms=_ms(t0))


class NodriverEngine(FetchEngine):
    """L3 浏览器取回:nodriver(直连 CDP,asyncio.run 包装)。缺库 → 不可用。"""
    name = "nodriver"

    def available(self) -> bool:
        return _has_module("nodriver")

    def get(self, target: str, ctx: Any) -> FetchOutcome:
        t0 = time.time()
        try:
            import asyncio

            import nodriver as nd  # 延迟导入
        except ImportError:
            return FetchOutcome(ok=False, engine="nodriver", error="nodriver not installed",
                                elapsed_ms=_ms(t0))

        proxy = _current_proxy(ctx)
        server, _user, _pwd = _split_proxy(proxy)   # Chrome --proxy-server 不接受内嵌凭据
        if server and (_user or _pwd):
            # --proxy-server 不支持内嵌账号密码:仅注入 host:port;鉴权留待上层扩展(TODO)。
            _warn(ctx, "nodriver: 代理鉴权(user:pass)不被 --proxy-server 支持,"
                       "已只传 host:port,账号密码未生效(TODO:经扩展/认证代理注入)。")

        async def _go():
            args = [f"--proxy-server={server}"] if server else None
            browser = await nd.start(headless=True, browser_args=args)
            try:
                page = await browser.get(target)
                await page.sleep(2)
                html = await page.get_content()
                final = target
                try:
                    final = await page.evaluate("location.href") or target
                except Exception:  # noqa: BLE001
                    pass
                return html, final
            finally:
                try:
                    browser.stop()
                except Exception:  # noqa: BLE001
                    pass

        try:
            html, final = asyncio.run(_go())
            # nodriver 走浏览器渲染、拿不到可靠 HTTP 状态码;不臆造 200(否则会把渲染出来的
            # 403/验证码页误判为成功),诚实置 status=None,是否被拦交由 serp.detect_captcha
            # 按 HTML 标志 + final_url(/sorry/)判定。
            return FetchOutcome(ok=bool(html), html=html, final_url=final,
                                status=None, engine="nodriver",
                                proxy_used=proxy, elapsed_ms=_ms(t0))
        except Exception as e:  # noqa: BLE001
            return FetchOutcome(ok=False, engine="nodriver", error=f"nodriver failed: {e}",
                                proxy_used=proxy, elapsed_ms=_ms(t0))


class PatchrightEngine(FetchEngine):
    """L2/L3 浏览器取回备选:patchright(Playwright drop-in)。缺库 → 不可用。"""
    name = "patchright"

    def available(self) -> bool:
        return _has_module("patchright")

    def get(self, target: str, ctx: Any) -> FetchOutcome:
        t0 = time.time()
        try:
            from patchright.sync_api import sync_playwright  # 延迟导入
        except ImportError:
            return FetchOutcome(ok=False, engine="patchright", error="patchright not installed",
                                elapsed_ms=_ms(t0))
        timeout = _cfg_get(ctx, "timeout", 30.0)
        proxy = _current_proxy(ctx)
        server, user, pwd = _split_proxy(proxy)
        launch_kw: Dict[str, Any] = {"headless": True, "channel": "chrome"}
        if server:                                   # Playwright 原生支持代理(含鉴权)
            proxy_opt: Dict[str, str] = {"server": server}
            if user:
                proxy_opt["username"] = user
            if pwd:
                proxy_opt["password"] = pwd
            launch_kw["proxy"] = proxy_opt
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(**launch_kw)
                try:
                    page = browser.new_page()
                    page.goto(target, timeout=int(max(timeout, 1) * 1000),
                              wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    return FetchOutcome(ok=True, html=page.content(), final_url=page.url,
                                        status=200, engine="patchright",
                                        proxy_used=proxy, elapsed_ms=_ms(t0))
                finally:
                    browser.close()
        except Exception as e:  # noqa: BLE001
            return FetchOutcome(ok=False, engine="patchright", error=f"patchright failed: {e}",
                                proxy_used=proxy, elapsed_ms=_ms(t0))


class SerpApiEngine(FetchEngine):
    """商业合规路径:调 B1 scholar_serpapi.search_scholar,旁路 HTML 直接产出结构化。

    约定:target 为**检索词**(ScholarQuery.q),非 URL。成功时把 SerpApi 响应 JSON 串
    放入 FetchOutcome.html(engine='serpapi'),下游 pipeline 用 serp.parse_serpapi(
    json.loads(outcome.html)) 解析。
    """
    name = "serpapi"

    def available(self) -> bool:
        # 客户端在本仓内,永远可导入;是否真正可用取决于运行时是否有 key(get 内判定)。
        return _has_module("fulltext_fetcher.scholar_serpapi")

    def get(self, target: str, ctx: Any) -> FetchOutcome:
        t0 = time.time()
        try:
            from ..scholar_serpapi import search_scholar  # 延迟导入(B1)
        except ImportError as e:
            return FetchOutcome(ok=False, engine="serpapi", error=f"serpapi client missing: {e}",
                                elapsed_ms=_ms(t0))
        cfg = getattr(ctx, "cfg", None)
        key = None
        if cfg is not None:
            key = cfg.serpapi_key_effective() if hasattr(cfg, "serpapi_key_effective") \
                else getattr(cfg, "serpapi_key", None)
        num = _cfg_get(ctx, "num", 10)
        resp = search_scholar(target, api_key=key, num=num)
        if not resp.get("available"):
            return FetchOutcome(ok=False, engine="serpapi",
                                error=resp.get("reason") or "serpapi unavailable", elapsed_ms=_ms(t0))
        if resp.get("error"):
            return FetchOutcome(ok=False, engine="serpapi", error=resp["error"], elapsed_ms=_ms(t0))
        return FetchOutcome(ok=True, html=json.dumps(resp, ensure_ascii=False),
                            final_url="serpapi://google_scholar", status=200,
                            engine="serpapi", elapsed_ms=_ms(t0))


def default_engines() -> Dict[str, FetchEngine]:
    """构造默认引擎实例表(构造不导入任何重库;导入均在 available()/get() 内延迟)。"""
    return {
        "curl_cffi": CurlCffiEngine(),
        "nodriver": NodriverEngine(),
        "patchright": PatchrightEngine(),
        "serpapi": SerpApiEngine(),
    }


# ─────────────────────────── 运行上下文(独立/测试用)───────────────────────────
@dataclass
class FetchContext:
    """fetcher 运行上下文(pipeline 的 ScholarContext 亦鸭子兼容:提供 cfg/proxy/log/events/engines)。"""
    cfg: Any
    proxy: Any = None                       # ProxyPool 或 None(直连)
    log: Any = None
    events: Any = None
    engines: Optional[Dict[str, FetchEngine]] = None


# ─────────────────────────── 限速 / 退避 / 冷却(§4.3)───────────────────────────
def _throttle(ctx: Any) -> None:
    """两次 Scholar 页请求之间的随机抖动(避免触发)。默认 45–90s;测试传 0 即不睡。"""
    low = float(_cfg_get(ctx, "page_interval_low", 45.0) or 0.0)
    high = float(_cfg_get(ctx, "page_interval_high", 90.0) or 0.0)
    if high <= 0:
        return
    _sleep(random.uniform(min(low, high), high))


def _backoff(ctx: Any, attempt: int) -> None:
    base = float(_cfg_get(ctx, "backoff_base", 2.0) or 0.0)
    cap = float(_cfg_get(ctx, "backoff_cap", 60.0) or 0.0)
    if cap <= 0 or base <= 0:
        return
    _sleep(min(base ** max(attempt, 1), cap))


def _cooldown(ctx: Any) -> None:
    _sleep(float(_cfg_get(ctx, "cooldown_after_block", 900.0) or 0.0))


def _rotate_proxy(ctx: Any) -> None:
    """命中风控:拉黑当前代理并轮换到下一个(默认无代理=直连,则无操作)。"""
    pool = getattr(ctx, "proxy", None)
    if pool is None:
        return
    try:
        if not pool.available():
            return
        old = pool.current()
        pool.report_block(old)
        new = pool.rotate()
        _emit(ctx, EVENT_PROXY_ROTATE, **{"from": old, "to": new, "reason": "blocked"})
    except Exception:  # noqa: BLE001
        pass


def _try_captcha(out: FetchOutcome, ctx: Any) -> Optional[str]:
    """默认关;开启且能取到 sitekey 时调 captcha.solve_recaptcha,返回 token 或 None。"""
    if not _cfg_get(ctx, "captcha_enabled", False):
        return None
    if not out or not out.html:
        return None
    m = _SITEKEY_RE.search(out.html)
    if not m:
        return None
    try:
        from .captcha import solve_recaptcha  # 同包(已就绪)
    except ImportError:
        return None
    res = solve_recaptcha(m.group(1), out.final_url or _SCHOLAR_URL, getattr(ctx, "cfg", None))
    ok = bool(res.get("available") and res.get("token"))
    _emit(ctx, EVENT_CAPTCHA, provider=_cfg_get(ctx, "captcha_provider", None), ok=ok)
    return res.get("token") if ok else None


# ─────────────────────────── URL 构造 ───────────────────────────
def build_scholar_url(q: Any) -> str:
    """由 ScholarQuery 组装 Scholar 结果页 URL。若 serp 提供同名实现则优先复用。"""
    try:
        from .serp import build_scholar_url as _serp_build  # 若 serp 后续补上则以其为准
        if _serp_build is not build_scholar_url:  # 防自引用
            return _serp_build(q)
    except Exception:  # noqa: BLE001
        pass
    params: Dict[str, Any] = {"q": getattr(q, "q", "") or "", "hl": getattr(q, "lang", "en") or "en"}
    start = getattr(q, "start", 0) or 0
    if start:
        params["start"] = start
    if getattr(q, "year_low", None):
        params["as_ylo"] = q.year_low
    if getattr(q, "year_high", None):
        params["as_yhi"] = q.year_high
    params["as_sdt"] = "0,5"
    return _SCHOLAR_URL + "?" + urlencode(params)


# ─────────────────────────── 编排入口 ───────────────────────────
def fetch_serp(q: Any, ctx: Any) -> FetchOutcome:
    """取回一页 Scholar SERP:按 cfg.mode + engine_order 逐层降级 + 反爬(§4.2)。"""
    cfg = getattr(ctx, "cfg", None)
    engines = getattr(ctx, "engines", None) or default_engines()
    mode = cfg.resolved_mode() if (cfg is not None and hasattr(cfg, "resolved_mode")) \
        else getattr(cfg, "mode", "self")

    # —— 商业合规路径:SerpApi 旁路 HTML —— 
    if mode == "serpapi":
        eng = engines.get("serpapi")
        if eng is None or not eng.available():
            return FetchOutcome(ok=False, engine="serpapi", error="serpapi engine unavailable")
        out = eng.get(getattr(q, "q", "") or "", ctx)
        _emit(ctx, EVENT_SERP_FETCH, url="serpapi", engine="serpapi", ok=out.ok,
              blocked=out.blocked, error=out.error, ms=out.elapsed_ms)
        return out

    # —— 自建分层路径 —— 
    url = build_scholar_url(q)
    order: List[str] = list(getattr(cfg, "engine_order", None) or ["curl_cffi", "nodriver"])
    last = FetchOutcome(ok=False, engine=None, error="no engine available")
    n = 0
    for name in order:
        eng = engines.get(name)
        if eng is None or not eng.available():
            _emit(ctx, EVENT_SERP_FETCH, url=url, engine=name, ok=False, error="engine unavailable")
            continue
        if n > 0:
            _throttle(ctx)                     # 仅在升级到后续引擎前限速
        out = eng.get(url, ctx)
        n += 1
        out.blocked = _is_blocked(out)
        _emit(ctx, EVENT_SERP_FETCH, url=url, engine=name, ok=out.ok, blocked=out.blocked,
              status=out.status, proxy=out.proxy_used, ms=out.elapsed_ms, error=out.error)
        if out.ok and not out.blocked:
            return out                          # 成功且未被拦 → 短路
        last = out
        if out.blocked:
            _emit(ctx, EVENT_BLOCK, url=url, engine=name, reason="captcha/consent/429")
            _rotate_proxy(ctx)
            _cooldown(ctx)
        else:
            _backoff(ctx, n)
        # 升级到下一层引擎

    # —— 全部引擎耗尽仍未成功:默认 captcha 关 → 记 blocked 跳过(不硬刚)——
    if last is not None and last.blocked:
        token = _try_captcha(last, ctx)         # 默认关 → None
        if token:
            last.captcha = True                 # 结构位:已求解(重投由带浏览器上下文的引擎在后续迭代实现)
    return last


def fetch_html(url: str, ctx: Any, *, allow_browser: bool = True) -> FetchOutcome:
    """通用单页取回(供 download 对 OA 落地页兜底复用)。先 L1 静态,失败可升级浏览器。

    不做 Scholar 风控升级/打码语义(面向已合法获取的 OA 页);返回首个 ok 的 FetchOutcome。
    """
    engines = getattr(ctx, "engines", None) or default_engines()
    order = ["curl_cffi"]
    if allow_browser:
        order += ["nodriver", "patchright"]
    last = FetchOutcome(ok=False, engine=None, error="no engine available")
    for name in order:
        eng = engines.get(name)
        if eng is None or not eng.available():
            continue
        out = eng.get(url, ctx)
        _emit(ctx, EVENT_SERP_FETCH, url=url, engine=name, ok=out.ok, status=out.status,
              ms=out.elapsed_ms, error=out.error)
        if out.ok:
            return out
        last = out
    return last


# ────────────────────────── 不联网 selftest ──────────────────────────
def _selftest() -> int:
    from .config import ScholarConfig
    from .models import ScholarQuery

    # 零睡眠配置(限速/退避/冷却全 0),默认自建模式
    def _cfg(**kw: Any) -> ScholarConfig:
        base = dict(mode="self", page_interval_low=0.0, page_interval_high=0.0,
                    backoff_base=0.0, backoff_cap=0.0, cooldown_after_block=0.0,
                    captcha_enabled=False, engine_order=["curl_cffi", "nodriver"])
        base.update(kw)
        return ScholarConfig(**base)

    class _FakeEngine(FetchEngine):
        def __init__(self, name: str, outcome: Optional[FetchOutcome] = None, avail: bool = True):
            self.name = name
            self._out = outcome
            self._avail = avail
            self.calls = 0

        def available(self) -> bool:
            return self._avail

        def get(self, target: str, ctx: Any) -> FetchOutcome:  # noqa: ARG002
            self.calls += 1
            # 复制一份,避免跨用例共享同一 FetchOutcome 实例被就地改 blocked
            o = self._out
            return FetchOutcome(ok=o.ok, html=o.html, final_url=o.final_url, status=o.status,
                                engine=o.engine, blocked=o.blocked, captcha=o.captcha,
                                proxy_used=o.proxy_used, error=o.error)

    _BLOCK_HTML = "<html><body>Our systems have detected unusual traffic from your network</body></html>"
    _OK_HTML = ("<div class='gs_r gs_or gs_scl' data-cid='X'><div class='gs_ri'>"
                "<h3 class='gs_rt'><a href='http://x/p'>T</a></h3></div></div>")
    block_out = FetchOutcome(ok=True, html=_BLOCK_HTML, status=200, engine="curl_cffi")
    ok_out = FetchOutcome(ok=True, html=_OK_HTML, status=200, engine="nodriver")
    q = ScholarQuery(raw="attention", kind="title", q="attention")

    # ① 降级路径:L1(curl_cffi)命中验证码 → 升级 L3(nodriver)成功
    e_block = _FakeEngine("curl_cffi", block_out)
    e_ok = _FakeEngine("nodriver", ok_out)
    ctx1 = FetchContext(cfg=_cfg(), engines={"curl_cffi": e_block, "nodriver": e_ok})
    out1 = fetch_serp(q, ctx1)
    assert out1.ok and out1.engine == "nodriver" and not out1.blocked, out1
    assert e_block.calls == 1 and e_ok.calls == 1, (e_block.calls, e_ok.calls)

    # ② 首层即成功 → 短路,不调用后续引擎
    e_ok1 = _FakeEngine("curl_cffi", ok_out)
    e_never = _FakeEngine("nodriver", ok_out)
    ctx2 = FetchContext(cfg=_cfg(), engines={"curl_cffi": e_ok1, "nodriver": e_never})
    out2 = fetch_serp(q, ctx2)
    assert out2.ok and e_never.calls == 0, (out2, e_never.calls)

    # ③ 全引擎不可用 → 优雅降级 ok=False
    ctx3 = FetchContext(cfg=_cfg(), engines={"curl_cffi": _FakeEngine("curl_cffi", ok_out, avail=False),
                                             "nodriver": _FakeEngine("nodriver", ok_out, avail=False)})
    out3 = fetch_serp(q, ctx3)
    assert out3.ok is False, out3

    # ④ 全部被拦(captcha 默认关)→ 返回最后一个 blocked、不抛
    ctx4 = FetchContext(cfg=_cfg(), engines={"curl_cffi": _FakeEngine("curl_cffi", block_out),
                                             "nodriver": _FakeEngine("nodriver", block_out)})
    out4 = fetch_serp(q, ctx4)
    assert out4.blocked is True and out4.captcha is False, out4

    # ⑤ 商业 SerpApi 模式:注入 fake serpapi 引擎 → 命中、旁路 HTML(JSON 串)
    serp_out = FetchOutcome(ok=True, engine="serpapi", html='{"available": true, "results": []}',
                            final_url="serpapi://google_scholar", status=200)
    ctx5 = FetchContext(cfg=ScholarConfig(mode="serpapi"),
                        engines={"serpapi": _FakeEngine("serpapi", serp_out)})
    out5 = fetch_serp(q, ctx5)
    assert out5.ok and out5.engine == "serpapi" and json.loads(out5.html)["available"] is True, out5

    # ⑥ fetch_html:首个可用引擎 ok 即返回(供 OA 落地页兜底)
    ctx6 = FetchContext(cfg=_cfg(), engines={"curl_cffi": _FakeEngine("curl_cffi", ok_out)})
    out6 = fetch_html("https://oa.example.org/p", ctx6)
    assert out6.ok, out6

    # ⑦ build_scholar_url:本地兜底构造含 q/hl/as_sdt(+分页/年份)
    u = build_scholar_url(ScholarQuery(raw="x", kind="title", q="deep learning",
                                       start=10, year_low=2018))
    assert u.startswith("https://scholar.google.com/scholar?") and "q=deep+learning" in u
    assert "start=10" in u and "as_ylo=2018" in u and "hl=en" in u, u

    # ⑧ 引擎构造不触发重库导入(缺库时 available 应为 False,不抛)
    assert NodriverEngine().available() in (True, False)
    assert PatchrightEngine().available() in (True, False)

    # ⑨ 代理 URL 解析:server 去内嵌凭据、user/pass 分离(供浏览器引擎接入代理)
    assert _split_proxy(None) == (None, None, None)
    assert _split_proxy("") == (None, None, None)
    assert _split_proxy("http://h:8080") == ("http://h:8080", None, None)
    assert _split_proxy("http://u:p@h:8080") == ("http://h:8080", "u", "p")
    assert _split_proxy("h:3128") == ("http://h:3128", None, None)   # 无 scheme 默认 http
    _s, _u, _p = _split_proxy("socks5://u2:p2@px.example:1080")
    assert (_s, _u, _p) == ("socks5://px.example:1080", "u2", "p2"), (_s, _u, _p)

    # ⑩ 浏览器引擎接入代理(P1 反爬):mock 注入 nodriver/patchright,断言"启用代理 →
    #    引擎把代理参数真正传给浏览器";直连不传;鉴权按引擎能力分别处理。
    import sys as _sys
    import types as _types

    class _FakeProxyPool:
        def __init__(self, url):
            self._u = url

        def available(self):
            return bool(self._u)

        def current(self):
            return self._u

        def rotate(self):
            return self._u

        def report_block(self, _u):
            pass

    class _RecLog:
        def __init__(self):
            self.warnings: List[str] = []

        def warning(self, msg, *a, **k):
            self.warnings.append(str(msg))

        def info(self, *a, **k):
            pass

    def _run_nodriver(proxy_url, log=None, content="<html>ok</html>"):
        """注入假 nodriver,跑 NodriverEngine.get,捕获 nd.start 收到的 browser_args。"""
        cap: Dict[str, Any] = {}

        class _P:
            async def sleep(self, _s):
                pass

            async def get_content(self):
                return content

            async def evaluate(self, _e):
                return "https://final/x"

        class _B:
            async def get(self, _u):
                return _P()

            def stop(self):
                pass

        async def _start(headless=True, browser_args=None):  # noqa: ARG001
            cap["browser_args"] = browser_args
            return _B()

        fake = _types.ModuleType("nodriver")
        fake.start = _start
        saved = _sys.modules.get("nodriver")
        _sys.modules["nodriver"] = fake
        try:
            pool = _FakeProxyPool(proxy_url) if proxy_url else None
            ctx = FetchContext(cfg=_cfg(), proxy=pool, log=log)
            out = NodriverEngine().get("https://scholar.example/x", ctx)
        finally:
            if saved is None:
                _sys.modules.pop("nodriver", None)
            else:
                _sys.modules["nodriver"] = saved
        return out, cap

    # 启用无鉴权代理 → browser_args 含 --proxy-server=host:port,proxy_used 正确
    o_np, cap_np = _run_nodriver("http://px.example:8080")
    assert o_np.ok and o_np.proxy_used == "http://px.example:8080", o_np
    assert cap_np["browser_args"] == ["--proxy-server=http://px.example:8080"], cap_np
    # 直连(无代理)→ browser_args 为 None,行为不变
    o_direct, cap_direct = _run_nodriver(None)
    assert o_direct.ok and cap_direct["browser_args"] is None, cap_direct
    # 带鉴权代理 → 仅注入 host:port(剥除 user:pass),且日志标注鉴权未生效
    rec = _RecLog()
    o_auth, cap_auth = _run_nodriver("http://u:p@px.example:8080", log=rec)
    assert cap_auth["browser_args"] == ["--proxy-server=http://px.example:8080"], cap_auth
    assert any("host:port" in w for w in rec.warnings), rec.warnings

    # nodriver status(P2 修正):浏览器渲染拿不到可靠 HTTP 码 → 一律 status=None,不臆造 200;
    # 拿到内容 ok=True、拿不到 ok=False;是否被拦交由 _is_blocked/detect_captcha 依 html/final_url 判断。
    assert o_np.status is None and o_np.ok is True, o_np
    o_empty, _ = _run_nodriver("http://px.example:8080", content="")
    assert o_empty.ok is False and o_empty.status is None, o_empty

    def _run_patchright(proxy_url):
        """注入假 patchright,跑 PatchrightEngine.get,捕获 chromium.launch 的 proxy 参数。"""
        cap: Dict[str, Any] = {}

        class _Page:
            url = "https://final/x"

            def goto(self, _u, timeout=None, wait_until=None):
                pass

            def wait_for_timeout(self, _ms):
                pass

            def content(self):
                return "<html>ok</html>"

        class _Br:
            def new_page(self):
                return _Page()

            def close(self):
                pass

        class _Chr:
            def launch(self, **kw):
                cap["launch_kw"] = kw
                return _Br()

        class _PW:
            chromium = _Chr()

        class _SPCtx:
            def __enter__(self):
                return _PW()

            def __exit__(self, *a):
                return False

        mod_root = _types.ModuleType("patchright")
        mod_sync = _types.ModuleType("patchright.sync_api")
        mod_sync.sync_playwright = lambda: _SPCtx()
        s_root, s_sync = _sys.modules.get("patchright"), _sys.modules.get("patchright.sync_api")
        _sys.modules["patchright"] = mod_root
        _sys.modules["patchright.sync_api"] = mod_sync
        try:
            pool = _FakeProxyPool(proxy_url) if proxy_url else None
            ctx = FetchContext(cfg=_cfg(), proxy=pool)
            out = PatchrightEngine().get("https://oa.example/x", ctx)
        finally:
            for _k, _v in (("patchright", s_root), ("patchright.sync_api", s_sync)):
                if _v is None:
                    _sys.modules.pop(_k, None)
                else:
                    _sys.modules[_k] = _v
        return out, cap

    # 带鉴权代理 → launch(proxy={server,username,password})(Playwright 原生支持鉴权)
    op_auth, capp_auth = _run_patchright("http://u:p@px.example:8080")
    assert op_auth.ok and capp_auth["launch_kw"].get("proxy") == {
        "server": "http://px.example:8080", "username": "u", "password": "p"}, capp_auth
    # 无鉴权代理 → 仅 server
    _op_np, capp_np = _run_patchright("http://px.example:8080")
    assert capp_np["launch_kw"]["proxy"] == {"server": "http://px.example:8080"}, capp_np
    # 直连 → 无 proxy 参数,行为不变
    _op_d, capp_d = _run_patchright(None)
    assert "proxy" not in capp_d["launch_kw"], capp_d

    # ⑪ UA 可配置(P2):默认回退内置 _UA;cfg.user_agent 覆盖;空值回退 _UA(requests 降级路径用)
    assert _ua(FetchContext(cfg=_cfg())) == _UA
    assert _ua(FetchContext(cfg=_cfg(user_agent="MyScholarUA/9.9"))) == "MyScholarUA/9.9"
    assert _ua(FetchContext(cfg=_cfg(user_agent=""))) == _UA

    print("FETCHER_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
