# 选型2026 · C4 异步侧「限速 / 熔断 / 退避」实现者参考骨架（aio.py + openalex-py/PyrateLimiter）

> 交付：**信息检索-智库专家岗**（承 -177，本会话）｜2026-07-02
> 触发：用户点名「深挖 openalex-py 源码 → 给 C4 异步侧(aio.py)限速/熔断的实现者参考骨架」。
> 边界：**只新建本 1 份参考骨架**；**不改任何 .py**（C4 代码活归 -168）。基于：实读本仓 `aio.py` + openalex-py 已公开的 cost-aware 设计 + PyrateLimiter（D3 文档已定的异步首选）+ 本仓 `http_client` 的 D3 同步设计（镜像到异步）。
> 承接：`选型2026-D3自适应限速与熔断`(N6) 的明确风险点——**「C4 异步侧(aio.py)完全无节流是隐患」**（D3↔C4 真依赖）。本骨架把同步 D3 的四件套镜像到异步。

---

## 〇、TL;DR

- **现状缺口（实读 aio.py）**：`fetch_many_async` 只有 `asyncio.Semaphore(max_concurrency)` 一道**全局并发闸**——**无按域限速、无熔断、无退避/Retry-After**。海量「定位」请求打同一 OA API（如 OpenAlex/Unpaywall）时，易触 **429 / 403 burst**，且无自愈。
- **补法（镜像同步 D3）**：新增 `AsyncHostGovernor`（**按域异步令牌桶 + 异步熔断器**）+ `async_polite_get()`（**退避+jitter，尊重 Retry-After，解析限速头**），接进 `_worker`。
- **cost-aware（承 openalex-py）**：解析 `X-RateLimit-*`；区分 **403 burst（退避重试）** vs **429 daily/credits 耗尽（快速失败、别硬刚）**；OpenAlex **100 req/s 硬顶** + **按 DOI 单条查=0 credits**（故本仓主用法瓶颈在 req/s 与礼貌，不在额度）。
- **依赖哲学**：默认**零依赖自研**（把 D3 算法搬来，同 -177 对 pyresilience 的结论）；异步令牌桶若愿纳 1 依赖，**PyrateLimiter**（原生 async、多算法）是首选。

---

## 一、读 openalex-py 提炼的 cost-aware 模式（实读其公开设计）

| openalex-py 能力 | 细节 | 对 aio.py 的借鉴 |
|---|---|---|
| **解析限速头** | 读 `X-RateLimit-*`，每响应暴露 `cost_usd` | → `async_polite_get` 解析响应头，反馈给 governor |
| **区分两类限流** | `CreditsExhaustedError(reset_at)` = 日额度耗尽；`RateLimitError(retry_after)` = 临时限流 | → **429/额度耗尽=快速失败**（记 reset_at、别重试硬刚）；**403 burst=按 retry_after 退避重试** |
| **两步内容下载** | PDF/TEI 重定向时**保留限速头** | → 异步下载若做，保留头以持续自适应 |
| **正确 key 传参** | `api_key` 查询参数（非私有头） | → 与本仓 aggregators 一致（已 OK） |
| **语义检索自动 1 req/s** | search.semantic 限 1 req/s | → 按端点差异化速率（singleton 宽、search/semantic 严） |

> **额度模型（pyalex/官方佐证）**：singleton（`/works/W..` 或 `/works/doi:..`）=**0 credit**；list=1、search=更高；无 key 100 credit/天、有 key 100k/天；**全员 100 req/s 上限**。→ **本仓 aio 主要打 singleton（按 DOI 查）=额度近乎无限**，异步侧真正要守的是 **100 req/s + 礼貌 + 429/403 自愈**。

---

## 二、参考骨架：`AsyncHostGovernor`（按域令牌桶 + 异步熔断）

```python
# fulltext_fetcher/aio_governor.py (新增;纯 asyncio,零第三方依赖)
import asyncio, time, random
from dataclasses import dataclass, field
from typing import Dict

@dataclass
class _HostState:
    # 令牌桶(按域限速)
    rate_per_s: float = 5.0            # 初始每秒许可(可 AIMD 自适应)
    tokens: float = 5.0
    capacity: float = 10.0
    last_refill: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # 熔断器(连续失败 → open;冷却后 half-open 探测)
    fails: int = 0
    open_until: float = 0.0
    # AIMD:成功缓增、限流乘减
    min_rate: float = 0.5
    max_rate: float = 20.0

class AsyncHostGovernor:
    """按域:异步令牌桶限速 + 熔断 + AIMD 自适应。镜像同步 http_client 的 D3 设计。"""
    def __init__(self, default_rate: float = 5.0, fail_threshold: int = 3,
                 open_cooldown: float = 120.0):
        self._hosts: Dict[str, _HostState] = {}
        self._default_rate = default_rate
        self._fail_threshold = fail_threshold
        self._open_cooldown = open_cooldown

    def _st(self, host: str) -> _HostState:
        st = self._hosts.get(host)
        if st is None:
            st = _HostState(rate_per_s=self._default_rate, tokens=self._default_rate)
            self._hosts[host] = st
        return st

    async def acquire(self, host: str, *, _now=time.monotonic, _sleep=asyncio.sleep) -> None:
        """熔断检查 + 令牌桶取 1 许可(不足则异步等)。"""
        st = self._st(host)
        now = _now()
        if now < st.open_until:                      # 熔断 open:快速让路(抛/等到冷却)
            await _sleep(st.open_until - now)
        async with st.lock:
            # 补桶
            elapsed = _now() - st.last_refill
            st.tokens = min(st.capacity, st.tokens + elapsed * st.rate_per_s)
            st.last_refill = _now()
            if st.tokens < 1.0:
                need = (1.0 - st.tokens) / max(st.rate_per_s, 1e-6)
                await _sleep(need)
                st.tokens = 0.0
                st.last_refill = _now()
            else:
                st.tokens -= 1.0

    def on_success(self, host: str) -> None:
        st = self._st(host); st.fails = 0
        st.rate_per_s = min(st.max_rate, st.rate_per_s + 0.5)   # AIMD 加性增

    def on_rate_limited(self, host: str, retry_after: float = 0.0) -> None:
        st = self._st(host)
        st.rate_per_s = max(st.min_rate, st.rate_per_s * 0.5)   # AIMD 乘性减
        # 429/限流不计入熔断失败(是限速信号,不是故障),但收紧速率

    def on_failure(self, host: str) -> None:
        st = self._st(host); st.fails += 1
        if st.fails >= self._fail_threshold:
            st.open_until = time.monotonic() + self._open_cooldown   # 开熔断
            st.fails = 0
```

---

## 三、参考骨架：`async_polite_get`（退避+jitter，尊重 Retry-After，解析限速头）

```python
from urllib.parse import urlparse

_RETRYABLE = (429, 500, 502, 503, 504)   # 403 视站点:OpenAlex 403=burst 可退避重试

async def async_polite_get(client, url: str, governor: "AsyncHostGovernor", *,
                           params=None, headers=None, max_retries: int = 3,
                           base_backoff: float = 0.5, _sleep=asyncio.sleep):
    """礼貌异步 GET:按域令牌桶 + 退避(Full Jitter)尊重 Retry-After + cost-aware 解析。
    返回 httpx.Response(或 None)。绝不外抛(单条降级由上层处理)。"""
    host = (urlparse(url).hostname or "").lower()
    attempt = 0
    while True:
        await governor.acquire(host)
        try:
            r = await client.get(url, params=params, headers=headers)
        except Exception:  # noqa: BLE001 网络异常按失败退避
            governor.on_failure(host)
            if attempt >= max_retries:
                return None
            await _sleep(_full_jitter(base_backoff, attempt)); attempt += 1; continue

        status = getattr(r, "status_code", 0)
        # cost-aware:429/额度耗尽 → 快速失败(别硬刚);其它限流/5xx → 退避重试
        if status == 429 and _is_daily_exhausted(r):
            governor.on_rate_limited(host); return r        # 日额度耗尽:交上层记 reset,别重试
        if status in _RETRYABLE or (status == 403 and _is_burst_403(r)):
            governor.on_rate_limited(host) if status == 429 else governor.on_failure(host)
            if attempt >= max_retries:
                return r
            ra = _retry_after_seconds(r)
            await _sleep(ra if ra > 0 else _full_jitter(base_backoff, attempt))
            attempt += 1; continue
        governor.on_success(host)
        return r

def _full_jitter(base: float, attempt: int) -> float:          # AWS Full Jitter(承 D3 G1)
    return random.uniform(0, base * (2 ** attempt))

def _retry_after_seconds(r) -> float:
    v = (getattr(r, "headers", {}) or {}).get("Retry-After", "")
    try: return float(v)
    except (TypeError, ValueError): return 0.0

def _is_daily_exhausted(r) -> bool:
    h = getattr(r, "headers", {}) or {}
    # OpenAlex:X-RateLimit-Remaining/credits 用尽;或 body 提示 daily
    return str(h.get("X-RateLimit-Remaining", "")).strip() in ("0", "0.0")

def _is_burst_403(r) -> bool:
    return True   # OpenAlex 403 多为 burst;按站点细化(有的 403=真付费墙,应交源判断)
```

---

## 四、接进 `aio.py`（最小侵入，向后兼容）

```python
# fetch_many_async 里,建一个 governor 传给每个 worker;_httpx_locate_fetch 用 async_polite_get
async def _worker(i, raw):
    async with sem:                       # 现有全局并发闸保留
        try:
            results[i] = await fetch(raw, cfg, client, governor)   # 多传 governor
        except Exception as e:  # noqa: BLE001
            results[i] = FetchResult(raw_input=raw, error=f"aio-error: {e}")

# _httpx_locate_fetch 内:
#   r = await async_polite_get(client, f"https://api.unpaywall.org/v2/{doi}",
#                              governor, params={"email": email})
```
> 兼容：`governor` 默认 `AsyncHostGovernor()`；`_fetch` 注入路径（selftest）不受影响。**Semaphore 保留**（全局并发预算），governor 叠加**按域**精细节流——两者正交。

---

## 五、selftest 草案（离线、注入假时钟/假响应）

- **令牌桶节流**：`rate_per_s=2`、连取 5 次 → 断言总耗时 ≈ (5-capacity)/rate（用注入 `_sleep` 累加断言，不真睡）。
- **熔断 open→half-open**：连续 `on_failure` 达阈值 → `acquire` 在 `open_until` 前被挡；冷却后放行。
- **AIMD**：`on_success` 加性增（+0.5，封顶 max_rate）；`on_rate_limited` 乘性减（×0.5，保底 min_rate）。
- **退避尊重 Retry-After**：假响应带 `Retry-After: 3` → 断言等待取 3 而非 jitter。
- **429 日额度耗尽快速失败**：`X-RateLimit-Remaining: 0` → `async_polite_get` 直接返回不重试。
- **Full Jitter 边界**：`_full_jitter(0.5, 2)` ∈ [0, 2.0]。
- 打印 `AIO_GOVERNOR_OK`（并入 aio 的 `_selftest`）。

---

## 六、选型与护栏

1. **默认零依赖自研**（把同步 http_client 的 D3 算法镜像到异步）——合本仓「极少依赖」；与 -177 对 pyresilience「搬算法不整库」的结论一致。
2. **若愿纳 1 依赖**：异步令牌桶用 **PyrateLimiter**（原生 async、令牌桶/漏桶/滑窗多算法，D3 文档已定为异步首选）；熔断仍自研（轻）。
3. **礼貌优先**：OpenAlex 100 req/s 硬顶 + singleton 免额度 → 默认 `rate_per_s` 保守（如 5/域）、Semaphore 并发别拉太高；对公共 OA API 宁慢勿封。
4. **区分限流 vs 故障**：429/限流是**信号**（收紧+退避，不计熔断失败）；连接/5xx 是**故障**（计熔断）——**别把限流误判成故障把源熔断掉**。
5. **下载仍走同步核心**：aio 只做「定位/元数据」高吞吐；PDF 下载留同步（已有 %PDF 校验/落地页二抽）。C4 归 -168。

---

## 七、来源

- 本仓 `aio.py`（实读：`fetch_many_async` 仅 `Semaphore`、无按域限速/熔断/退避；`_httpx_locate_fetch` 裸 `client.get`）。
- **openalex-py**（Luigi Palumbo，MIT，async-first）：cost-aware 解析 `X-RateLimit-*`、`CreditsExhaustedError(reset_at)` vs `RateLimitError(retry_after)`、两步内容下载保留限速头、`api_key` 查询参数。
- **官方/pyalex 额度模型**：singleton=0 credit、list=1、100 req/s 上限、无 key 100/天·有 key 100k/天（`docs.openalex.org` rate-limits-and-authentication）。
- **PyrateLimiter**（异步令牌桶，D3 文档 N6 已定异步首选）；**pyresilience**（-177 已研判：搬其滑窗熔断/half-open/full-jitter 算法而非整库）。
- 本仓 **N6**（`选型2026-D3自适应限速与熔断`）：同步 http_client 已建 60%（按域限速+表头自适应+熔断+Retry-After），三增量 jitter/AIMD/half-open；**明列 aio.py 无节流为隐患**——本骨架即补该隐患。

---

*核验 2026-07-02｜信息检索-智库专家岗（承 -177，本会话）｜工单「C4 异步限速/熔断实现者参考」｜结论：aio.py 现仅全局 Semaphore、缺按域限速/熔断/退避;补法=镜像同步 D3 → AsyncHostGovernor(按域令牌桶+熔断+AIMD)+async_polite_get(Full Jitter+尊重 Retry-After+cost-aware 区分 429 日额度/403 burst);默认零依赖自研,异步桶可选 PyrateLimiter。C4 归 -168。仅新建本 1 份参考,未改任何 .py。*
