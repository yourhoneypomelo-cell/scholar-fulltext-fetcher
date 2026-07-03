"""A5 · Tier-0「人在环 + 持久暖档案」辅助认证(assisted auth) —— gated·默认关.

设计依据:《检索成果-两类认证一定能完成方案-CF-Turnstile与RSC-governor-148.md》。
用户诉求:CF Turnstile 与 RSC governor 两道认证「一定要能完成」。二者本质不同:
  - CF Turnstile 是【可过】的人机验证 —— 干净自动化多能自动过,过不了时人点一次即可;
  - RSC `crawlprevention/governor` 弹的是 `Invalid domain for site key` 的【坏 reCAPTCHA】——
    真人/打码平台都解不了(-165 实锤),只能「不触发 + 退避」,绝不硬解。

因此「一定能完成」的保底 = **有头真浏览器 + 持久真实档案 + 需要时叫人过一次**:人在有头窗口
完成机构 SSO / 手点 CF Turnstile / 正规 reCAPTCHA → cf_clearance/SSO/session cookie 落进持久
`user-data-dir` 与 CookieStore → 后续复用暖会话。这正是成熟学术下载生态(ref-downloader /
auto-paper-harvester)对 ACS/RSC 等 browser_only 站的统一做法。

边界与纪律(与 institutional 包一致):
  - **gated·默认关**:未开(`FTF_ASSISTED_AUTH` / `cfg.assisted_auth`)时全部为惰性、零副作用;
  - **不 import / 不改 render_fetch**:route-B 属主(-141/-144/-157)日后 opt-in 调用即可;
  - **不硬解坏 reCAPTCHA**:命中 governor softblock(Invalid domain)→ 返回退避信号,不叫人硬点;
  - **合规**:仅供拥有合法机构访问权者、在已获授权下完成正规人机验证取用有权内容,
    不得用于绕过付费墙或任何访问授权;
  - **可离线自测**:编排核心走可注入的 driver 协议,selftest 用假 driver 全离线跑,打印
    ``ASSISTED_AUTH_OK``。真浏览器后端(zendriver→nodriver)懒导入、best-effort、不进 selftest。

运行:
    python -m fulltext_fetcher.institutional.assisted_auth              # 离线 selftest
    python -m fulltext_fetcher.institutional.assisted_auth --login URL  # 真机人在环登录(best-effort)
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional, Tuple

from .cookie_store import CookieStore, StoredCookie


# ── 认证态分类 ────────────────────────────────────────────────────────────────
class AuthState(str, Enum):
    CLEAR = "clear"                                  # 无质询/登录信号 → 视作已过,可取字节
    CF_CHALLENGE = "cf-challenge"                    # Cloudflare Turnstile / Managed challenge(可人点)
    RSC_GOVERNOR = "rsc-governor"                    # RSC 速率门 + 正规 reCAPTCHA(可人点)
    RSC_GOVERNOR_SOFTBLOCK = "rsc-governor-softblock"  # Invalid-domain 坏码(不可解 → 退避,勿叫人硬点)
    SSO_LOGIN = "sso-login"                          # 机构 SSO 登录页(可人工登录)


# 信号集(全小写子串匹配;URL + 可见文本一起判)
_GOVERNOR_SOFTBLOCK_SIGNALS = ("invalid domain for site key",)
_GOVERNOR_SIGNALS = (
    "crawlprevention/governor", "validate user", "take me to my content",
    "experiencing unusual traffic", "unusual traffic",
)
_CF_SIGNALS = (
    "just a moment", "verifying you are human", "checking your browser",
    "enable javascript and cookies", "attention required", "are you a robot",
    "challenges.cloudflare.com", "cf-challenge", "cf_chl", "turnstile",
)
_SSO_SIGNALS = (
    "shibboleth", "openathens", "/idp/", "wayf", "institutional login",
    "sign in with your institution", "single sign-on", "登录以继续", "机构登录",
)

# 需要「叫人」的态(softblock 不在内:坏码人也解不了 → 退避)
_HUMAN_SOLVABLE = (AuthState.CF_CHALLENGE, AuthState.RSC_GOVERNOR, AuthState.SSO_LOGIN)

# 启动参数里必须去掉的「自动化泄漏」flag(截图顶栏那条 infobar 的元凶,是明信号)
_LEAK_LAUNCH_FLAGS = ("--disable-blink-features=AutomationControlled",)


def classify_auth_state(url: str, html: str) -> AuthState:
    """按 URL + 可见文本判断当前处于哪种认证态;无任何质询/登录信号 → CLEAR。

    优先级:governor softblock(最特异·不可解)> governor > CF > SSO > CLEAR。
    """
    blob = ((url or "") + " \n " + (html or "")).lower()
    if any(s in blob for s in _GOVERNOR_SOFTBLOCK_SIGNALS):
        return AuthState.RSC_GOVERNOR_SOFTBLOCK
    if any(s in blob for s in _GOVERNOR_SIGNALS):
        return AuthState.RSC_GOVERNOR
    if any(s in blob for s in _CF_SIGNALS):
        return AuthState.CF_CHALLENGE
    if any(s in blob for s in _SSO_SIGNALS):
        return AuthState.SSO_LOGIN
    return AuthState.CLEAR


def needs_human(state: AuthState) -> bool:
    """该态是否需要人过一次(softblock 返回 False:坏码不可解,应退避而非硬点)。"""
    return state in _HUMAN_SOLVABLE


# ── 门控 / 档案 / 启动参数(纯函数,离线可测)────────────────────────────────────
def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def is_assisted_enabled(cfg: Any = None) -> bool:
    """gated·默认关:仅当 env FTF_ASSISTED_AUTH 或 cfg.assisted_auth 为真时开启。"""
    if _truthy(os.environ.get("FTF_ASSISTED_AUTH", "")):
        return True
    return bool(getattr(cfg, "assisted_auth", False)) if cfg is not None else False


def resolve_profile_dir(cfg: Any = None) -> str:
    """解析持久 user-data-dir(暖档案)路径。

    优先级:env FTF_ASSISTED_PROFILE_DIR > cfg.assisted_profile_dir > cfg.route_b_user_data_dir
             > 默认 <out_dir>/.assisted_profile。返回绝对路径(不创建目录)。
    """
    cand = (
        os.environ.get("FTF_ASSISTED_PROFILE_DIR")
        or getattr(cfg, "assisted_profile_dir", None)
        or getattr(cfg, "route_b_user_data_dir", None)
    )
    if not cand:
        out_dir = getattr(cfg, "out_dir", None) or "out"
        cand = os.path.join(out_dir, ".assisted_profile")
    return os.path.abspath(os.path.expanduser(str(cand)))


def clean_launch_args(args: Optional[List[str]] = None) -> List[str]:
    """去掉自动化泄漏 flag(尤其 --disable-blink-features=AutomationControlled)。

    该 flag 会触发 Chrome「unsupported command-line flag」infobar,本身就是机器信号
    (两张截图顶栏那条),必须剔除。保序去重,不注入任何新 flag。
    """
    out: List[str] = []
    for a in (args or []):
        s = str(a)
        if any(leak.lower() in s.lower() for leak in _LEAK_LAUNCH_FLAGS):
            continue
        if s not in out:
            out.append(s)
    return out


# ── 结果 / 编排核心(sync,走可注入 driver 协议,离线可测)──────────────────────
@dataclass
class AssistedLoginResult:
    ok: bool
    state: AuthState
    cookie_count: int = 0
    elapsed_s: float = 0.0
    notes: str = ""


# driver 协议(鸭子类型):
#   goto(url)            -> None      导航
#   probe()              -> (url,txt) 取当前 URL 与可见文本(判态用)
#   cookies()            -> List[StoredCookie]  取当前会话 cookie
#   stop()               -> None      关闭
DriverProbe = Callable[[], Tuple[str, str]]


def _assisted_login_core(
    driver: Any,
    landing_url: str,
    *,
    provider: str = "manual",
    cookie_store: Optional[CookieStore] = None,
    notify: Optional[Callable[[AuthState, str], None]] = None,
    poll_interval: float = 3.0,
    timeout: float = 300.0,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> AssistedLoginResult:
    """编排:导航 landing → 轮询判态 → 需人则 notify 并等待人过 → CLEAR 则收 cookie 落档。

    - 命中 CLEAR:收 cookie、(可选)存 CookieStore、ok=True 返回。
    - 命中 softblock(坏 reCAPTCHA):立即退避返回 ok=False(交由上层 per-host 冷却),**不叫人**。
    - 其它需人态:调 notify(叫人),继续轮询直至 CLEAR 或超时。
    driver / sleep / now / notify 均可注入 → 全离线可测。
    """
    t0 = now()
    notified_states: set = set()
    driver.goto(landing_url)
    last_state = AuthState.CLEAR
    while True:
        url, text = driver.probe()
        state = classify_auth_state(url, text)
        last_state = state
        if state == AuthState.CLEAR:
            cookies = list(driver.cookies() or [])
            if cookie_store is not None and cookies:
                cookie_store.set_cookies(provider, cookies)
                cookie_store.save()
            return AssistedLoginResult(
                ok=True, state=state, cookie_count=len(cookies),
                elapsed_s=now() - t0, notes="cleared; warm session harvested",
            )
        if state == AuthState.RSC_GOVERNOR_SOFTBLOCK:
            return AssistedLoginResult(
                ok=False, state=state, elapsed_s=now() - t0,
                notes="governor softblock(Invalid domain 坏码)→ 退避/冷却,不硬解、不叫人",
            )
        if needs_human(state) and notify is not None and state not in notified_states:
            notify(state, url)
            notified_states.add(state)
        if now() - t0 >= timeout:
            return AssistedLoginResult(
                ok=False, state=last_state, elapsed_s=now() - t0,
                notes=f"timeout {timeout:.0f}s waiting human to clear {last_state.value}",
            )
        sleep(poll_interval)


def save_cookies(cookies: List[StoredCookie], provider: str, store_path: str) -> int:
    """把收到的 cookie 落 CookieStore(复用既有持久层);返回落盘条数。"""
    store = CookieStore.load(store_path)
    store.set_cookies(provider, list(cookies))
    store.save()
    return len(cookies)


# ── 真浏览器后端(zendriver→nodriver,懒导入·best-effort·不进 selftest)──────────
def _map_cookie(obj: Any) -> Optional[StoredCookie]:
    """把 zendriver/nodriver/CDP cookie 对象或 dict 映射成 StoredCookie(尽量健壮)。"""
    def g(k: str, *alts: str) -> Any:
        if isinstance(obj, dict):
            for kk in (k, *alts):
                if kk in obj:
                    return obj[kk]
            return None
        for kk in (k, *alts):
            if hasattr(obj, kk):
                return getattr(obj, kk)
        return None
    name = g("name")
    if not name:
        return None
    return StoredCookie(
        name=str(name), value=str(g("value") or ""), domain=str(g("domain") or ""),
        path=str(g("path") or "/"), secure=bool(g("secure")),
        http_only=bool(g("http_only", "httpOnly")), expires=g("expires", "expiry"),
    )


class _ZendriverAdapter:
    """把 async 的 zendriver/nodriver 包成 sync driver 协议(交互节奏够慢,per-call 跑 loop 可接受)。"""

    def __init__(self, profile_dir: str, extra_args: Optional[List[str]] = None):
        import asyncio
        self._asyncio = asyncio
        self._loop = asyncio.new_event_loop()
        self._backend = None
        self._browser = None
        self._tab = None
        self._profile_dir = profile_dir
        self._args = clean_launch_args(extra_args)

    def _run(self, coro: Any) -> Any:
        return self._loop.run_until_complete(coro)

    def start(self) -> None:
        os.makedirs(self._profile_dir, exist_ok=True)
        try:
            import zendriver as zd  # 首选:活跃维护 + verify_cf
            self._backend = "zendriver"
            self._browser = self._run(zd.start(
                headless=False, user_data_dir=self._profile_dir, browser_args=self._args,
            ))
        except Exception:  # noqa: BLE001 - 缺 zendriver → 退回 nodriver
            import nodriver as uc
            self._backend = "nodriver"
            self._browser = self._run(uc.start(
                headless=False, user_data_dir=self._profile_dir, browser_args=self._args,
            ))

    def goto(self, url: str) -> None:
        self._tab = self._run(self._browser.get(url))

    def try_verify_cf(self) -> None:
        """zendriver 内置 verify_cf 自动点 shadow-root Turnstile(有则用,失败忽略,兜底仍靠人)。"""
        tab = self._tab
        if tab is None:
            return
        try:
            self._run(tab.verify_cf())
        except Exception:  # noqa: BLE001 - 无该 API / 失败 → 交给人
            pass

    def probe(self) -> Tuple[str, str]:
        tab = self._tab
        if tab is None:
            return "", ""
        try:
            url = self._run(tab.evaluate("location.href")) or ""
            text = self._run(tab.evaluate(
                "(document.body && document.body.innerText || '').slice(0,4000)"
            )) or ""
            return str(url), str(text)
        except Exception:  # noqa: BLE001
            return "", ""

    def cookies(self) -> List[StoredCookie]:
        try:
            raw = self._run(self._browser.cookies.get_all())
        except Exception:  # noqa: BLE001
            return []
        out: List[StoredCookie] = []
        for c in (raw or []):
            sc = _map_cookie(c)
            if sc:
                out.append(sc)
        return out

    def stop(self) -> None:
        try:
            self._browser.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._loop.close()
        except Exception:  # noqa: BLE001
            pass


def run_assisted_login(
    landing_url: str,
    *,
    cfg: Any = None,
    provider: str = "manual",
    notify: Optional[Callable[[AuthState, str], None]] = None,
    poll_interval: float = 3.0,
    timeout: float = 300.0,
    _driver: Any = None,
) -> AssistedLoginResult:
    """真机「人在环」登录入口(gated·best-effort)。未开启 → 惰性返回 ok=False,零副作用。

    _driver 可注入(测试/属主自带浏览器时用);否则懒起 zendriver→nodriver 有头真 Chrome。
    """
    if _driver is None and not is_assisted_enabled(cfg):
        return AssistedLoginResult(
            ok=False, state=AuthState.CLEAR,
            notes="assisted auth disabled (set FTF_ASSISTED_AUTH=1 or cfg.assisted_auth)",
        )
    profile_dir = resolve_profile_dir(cfg)
    store_path = (
        getattr(cfg, "cookie_store_path", None)
        or os.path.join(getattr(cfg, "out_dir", None) or "out", ".ftf_cookies.local.json")
    )
    cookie_store = CookieStore.load(store_path)

    driver = _driver
    owns_driver = driver is None
    if owns_driver:
        extra = clean_launch_args(list(getattr(cfg, "browser_args", []) or []))
        driver = _ZendriverAdapter(profile_dir, extra_args=extra)
        try:
            driver.start()
        except Exception as e:  # noqa: BLE001 - 无浏览器引擎/显示 → 优雅失败
            return AssistedLoginResult(
                ok=False, state=AuthState.CLEAR,
                notes=f"browser backend unavailable: {type(e).__name__}: {e}",
            )
    try:
        # 有 verify_cf 的后端先自动试过 CF,再进人工轮询(降低叫人频率)
        if owns_driver and hasattr(driver, "try_verify_cf"):
            driver.goto(landing_url)
            driver.try_verify_cf()
            res = _assisted_login_core(
                driver, landing_url, provider=provider, cookie_store=cookie_store,
                notify=notify, poll_interval=poll_interval, timeout=timeout,
            )
        else:
            res = _assisted_login_core(
                driver, landing_url, provider=provider, cookie_store=cookie_store,
                notify=notify, poll_interval=poll_interval, timeout=timeout,
            )
        return res
    finally:
        if owns_driver:
            driver.stop()


# ── 离线 selftest(假 driver,零网络/零浏览器)────────────────────────────────
class _FakeDriver:
    """按预置脚本逐轮返回 (url, text) 的假 driver;probe 用尽后停在最后一帧。"""

    def __init__(self, frames: List[Tuple[str, str]], cookies: List[StoredCookie]):
        self._frames = frames
        self._i = -1
        self._cookies = cookies
        self.goto_url: Optional[str] = None
        self.stopped = False

    def goto(self, url: str) -> None:
        self.goto_url = url

    def probe(self) -> Tuple[str, str]:
        self._i = min(self._i + 1, len(self._frames) - 1)
        return self._frames[self._i]

    def cookies(self) -> List[StoredCookie]:
        return list(self._cookies)

    def stop(self) -> None:
        self.stopped = True


def _selftest() -> None:
    import tempfile

    # ① classify_auth_state:各态命中 + 优先级
    assert classify_auth_state("https://x/crawlprevention/governor",
                               "Invalid domain for site key") == AuthState.RSC_GOVERNOR_SOFTBLOCK
    assert classify_auth_state("https://pubs.rsc.org/crawlprevention/governor",
                               "experiencing unusual traffic. Take me to my Content") == AuthState.RSC_GOVERNOR
    assert classify_auth_state("https://site/x", "Verifying you are human … cloudflare") == AuthState.CF_CHALLENGE
    assert classify_auth_state("https://idp.uni.edu/idp/profile", "Sign in with your institution") == AuthState.SSO_LOGIN
    assert classify_auth_state("https://onlinelibrary.wiley.com/doi/abs/10.1/x",
                               "Research Article Full text") == AuthState.CLEAR

    # ② needs_human:softblock 不叫人
    assert needs_human(AuthState.CF_CHALLENGE) and needs_human(AuthState.RSC_GOVERNOR)
    assert needs_human(AuthState.SSO_LOGIN)
    assert not needs_human(AuthState.RSC_GOVERNOR_SOFTBLOCK)
    assert not needs_human(AuthState.CLEAR)

    # ③ 门控默认关 / 开关
    assert is_assisted_enabled(None) is False
    os.environ["FTF_ASSISTED_AUTH"] = "1"
    assert is_assisted_enabled(None) is True
    os.environ.pop("FTF_ASSISTED_AUTH", None)

    class _Cfg:
        assisted_auth = True
    assert is_assisted_enabled(_Cfg()) is True

    # ④ 启动参数清洗:去掉泄漏 flag
    cleaned = clean_launch_args(["--headless=new", "--disable-blink-features=AutomationControlled", "--lang=en"])
    assert "--disable-blink-features=AutomationControlled" not in cleaned
    assert "--lang=en" in cleaned and "--headless=new" in cleaned

    # ⑤ 档案路径解析
    os.environ["FTF_ASSISTED_PROFILE_DIR"] = os.path.join(tempfile.gettempdir(), "ftf_prof_x")
    assert resolve_profile_dir(None).endswith("ftf_prof_x")
    os.environ.pop("FTF_ASSISTED_PROFILE_DIR", None)

    fake_now = {"t": 0.0}
    slept: List[float] = []

    def _now() -> float:
        return fake_now["t"]

    def _sleep(s: float) -> None:
        slept.append(s)
        fake_now["t"] += s

    # ⑥ 编排:CF 质询 → (人过) → CLEAR,收 cookie 落档
    with tempfile.TemporaryDirectory() as d:
        store = CookieStore.load(os.path.join(d, "ck.json"))
        cookies = [StoredCookie(name="cf_clearance", value="abc", domain=".rsc.org"),
                   StoredCookie(name="sess", value="1", domain=".rsc.org")]
        drv = _FakeDriver(
            frames=[("https://pubs.rsc.org/x", "Just a moment... Verifying you are human"),
                    ("https://pubs.rsc.org/x", "Just a moment..."),
                    ("https://pubs.rsc.org/en/content/articlelanding/x", "Article HTML full text")],
            cookies=cookies,
        )
        notes: List[Tuple[AuthState, str]] = []
        res = _assisted_login_core(
            drv, "https://pubs.rsc.org/x", provider="manual", cookie_store=store,
            notify=lambda st, u: notes.append((st, u)),
            poll_interval=3.0, timeout=100.0, sleep=_sleep, now=_now,
        )
        assert res.ok and res.state == AuthState.CLEAR, res
        assert res.cookie_count == 2, res
        assert drv.goto_url == "https://pubs.rsc.org/x"
        assert notes and notes[0][0] == AuthState.CF_CHALLENGE       # 叫过人
        assert len(notes) == 1                                        # 同态只叫一次
        assert store.get_valid_cookies("manual"), "cookie 应已落 CookieStore"

    # ⑦ 编排:governor softblock → 立即退避,不叫人、不硬解
    drv2 = _FakeDriver(
        frames=[("https://pubs.rsc.org/crawlprevention/governor",
                 "unusual traffic. ERROR for site owner: Invalid domain for site key")],
        cookies=[],
    )
    notes2: List[Any] = []
    res2 = _assisted_login_core(
        drv2, "https://pubs.rsc.org/y", notify=lambda st, u: notes2.append(st),
        poll_interval=1.0, timeout=10.0, sleep=_sleep, now=_now,
    )
    assert (not res2.ok) and res2.state == AuthState.RSC_GOVERNOR_SOFTBLOCK, res2
    assert notes2 == [], "softblock 不应叫人硬点"

    # ⑧ 编排:一直质询 → 超时失败
    drv3 = _FakeDriver(frames=[("u", "just a moment")], cookies=[])
    res3 = _assisted_login_core(
        drv3, "u", poll_interval=5.0, timeout=12.0, sleep=_sleep, now=_now,
    )
    assert (not res3.ok) and "timeout" in res3.notes, res3

    # ⑨ run_assisted_login:默认关 → 惰性返回
    assert run_assisted_login("https://x", cfg=None).ok is False

    # ⑩ run_assisted_login:注入 driver 直接走核心(绕开真浏览器)
    drv4 = _FakeDriver(frames=[("https://ok/", "content")], cookies=[StoredCookie("a", "b", ".ok")])
    res4 = run_assisted_login("https://ok/", _driver=drv4)
    assert res4.ok and res4.cookie_count == 1, res4
    assert drv4.stopped is False  # 注入的 driver 不由本函数关闭(属主自管)

    # ⑪ save_cookies 落盘往返
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "ck2.json")
        n = save_cookies([StoredCookie("k", "v", ".x")], "manual", p)
        assert n == 1 and CookieStore.load(p).get_valid_cookies("manual")

    print("ASSISTED_AUTH_OK")


def main(argv: Optional[List[str]] = None) -> int:
    import sys
    args = list(argv if argv is not None else sys.argv[1:])
    if "--login" in args:
        i = args.index("--login")
        url = args[i + 1] if i + 1 < len(args) else ""
        if not url:
            print("usage: --login <landing_url>  (需 FTF_ASSISTED_AUTH=1)")
            return 2

        def _notify(state: AuthState, u: str) -> None:
            print(f"[需要你] 当前认证态={state.value};请在弹出的浏览器窗口完成人机验证/登录 → {u}")

        res = run_assisted_login(url, notify=_notify)
        print(f"assisted login: ok={res.ok} state={res.state.value} cookies={res.cookie_count} "
              f"elapsed={res.elapsed_s:.1f}s notes={res.notes}")
        return 0 if res.ok else 1
    _selftest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
