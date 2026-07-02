# 选型2026 · D3 实现者可照抄骨架 — `http_client.py` 增量补丁（G1/G2/G3 + selftest）

> 智库交付（信息检索-智库专家 **-177**）｜2026-07-02｜配套《选型2026-D3自适应限速与熔断-开源选型与增量设计》。
> **性质**：给实现者的**参考骨架/设计**，非生产改动——本文不改 `.py`；由 -156 排定的实现者据此整合进 `http_client.py` 并跑 selftest。算法借鉴 AWS Full Jitter / TCP-AIMD / Nygard 半开熔断 / pyresilience(MIT 参考实现)。
> **恪守既有不变量**：① SSL 瞬时失败不计入熔断（`_is_ssl_error`）；② 限速「只在 [floor, ceil] 内自调、floor=配置/表头」；③ 跨线程状态一律 `_host_lock` 下改写；④ 默认行为可回退（新增开关，灰度）。

---

## 0. 改动总览（3 处增量，全部零依赖，仅用 `random`/`time`/`threading`）

| 增量 | 改动点 | 新增状态/配置 |
|---|---|---|
| **G1 Full Jitter** | `get()` 里两处 `2**attempt` → `_backoff_delay()` | 无（仅 `import random`） |
| **G2 按域 AIMD** | `_respect_rate` 保持；新增 `_aimd_penalize/_aimd_relax`；`get()` 命中 429/成功时调用 | `_host_ok_run: dict`；配置 `rate_ceiling/aimd_step/aimd_success_run/adaptive_rate` |
| **G3 半开熔断** | `_host_down:set`+`_host_fail:dict` → 合并为 `_host_cb:dict` 状态机；`get()` 入口做状态判定 | 配置 `breaker_reset_timeout` |

> 建议新增 `config.py` 字段（默认值给「与现网等价或安全」）：
> ```python
> adaptive_rate: bool = True        # G2 AIMD 总开关（可灰度关）
> rate_ceiling: float = 8.0         # 按域间隔上限（秒），防无限变慢
> aimd_step: float = 0.05           # 成功后加性减小步长（秒）
> aimd_success_run: int = 20        # 连续成功多少次后放宽一档
> breaker_reset_timeout: float = 120.0  # 熔断 open→half_open 冷却（秒）
> ```

---

## 1. G1 · Full Jitter（AWS 标准，防惊群）

```python
import random  # 文件顶部新增

def _backoff_delay(attempt: int, cap: float, base: float = 1.0) -> float:
    """AWS Full Jitter: 在 [0, min(cap, base*2**attempt)] 均匀取样，打散多线程同拍退避。"""
    return random.uniform(0.0, min(cap, base * (2 ** attempt)))
```

在 `get()` 中替换两处（**有 `Retry-After` 时仍优先尊重服务端、不加抖动**）：
```python
# 429/5xx 分支：
ra = r.headers.get("Retry-After")
if ra and ra.isdigit():
    delay = min(float(ra), 30.0)          # 尊重服务端，不抖动
else:
    delay = _backoff_delay(attempt, cap=30.0)   # ← 原 float(2**attempt)
...
# 连接错 / SSL 瞬时失败分支：
time.sleep(_backoff_delay(attempt, cap=8.0))     # ← 原 min(float(2**attempt), 8)
```

---

## 2. G2 · 按域 AIMD（从 429 学习可持续速率；只在 [floor, ceil] 内自调）

```python
# __init__ 内新增：
self._host_ok_run: Dict[str, int] = {}      # 每 host 连续成功计数
# floor 取「配置 per_host_interval 与 _maybe_adapt_rate 表头收紧」的较大者（既有 _host_interval 即含表头结果）

def _rate_floor(self, host: str) -> float:
    """该 host 的间隔下限：不低于配置默认（表头收紧写入 _host_interval 时作为更高的硬下限另存亦可）。"""
    return float(self.cfg.per_host_interval)

def _aimd_penalize(self, host: str) -> None:
    """遇 429/限速（即使无表头）：乘性增大间隔（×2），封顶 ceil。须在 _host_lock 下调用。"""
    ceil = float(getattr(self.cfg, "rate_ceiling", 8.0))
    cur = self._host_interval.get(host, self.cfg.per_host_interval)
    self._host_interval[host] = min(ceil, max(cur, self._rate_floor(host)) * 2.0)
    self._host_ok_run[host] = 0

def _aimd_relax(self, host: str) -> None:
    """连续成功达阈值：加性减小间隔（-step），不破 floor。须在 _host_lock 下调用。"""
    if not getattr(self.cfg, "adaptive_rate", True):
        return
    run = self._host_ok_run.get(host, 0) + 1
    if run < int(getattr(self.cfg, "aimd_success_run", 20)):
        self._host_ok_run[host] = run
        return
    step = float(getattr(self.cfg, "aimd_step", 0.05))
    cur = self._host_interval.get(host, self.cfg.per_host_interval)
    self._host_interval[host] = max(self._rate_floor(host), cur - step)
    self._host_ok_run[host] = 0
```

接线（在 `get()` 内）：
- 命中 `429`（及可判定为限速的 503）时，除退避外：`with self._host_lock: self._aimd_penalize(host)`。
- 请求成功（`_note_ok(host)` 之后）：`with self._host_lock: self._aimd_relax(host)`。
- 说明：既有 `_maybe_adapt_rate`（表头收紧）保留，作为**初始/硬下限**；AIMD 只在 `[floor, ceil]` 内动态调，**对不回表头、只会 429 的出版商尤为关键**。

---

## 3. G3 · 半开熔断（长批跑内自愈瞬断主机）

把 `_host_fail:dict` + `_host_down:set` 合并为一个状态机 dict：
```python
# __init__ 内替换：
self._host_cb: Dict[str, Dict[str, Any]] = {}   # host -> {"state","fails","opened_at","probing"}
self._breaker_threshold = 3
# self._reset_timeout 取 cfg.breaker_reset_timeout

def _cb_allow(self, host: str) -> bool:
    """入口判定：closed/half_open 放行；open 到冷却则转 half_open 放一个探针，否则拦。须在锁内。"""
    st = self._host_cb.get(host)
    if not st or st["state"] == "closed":
        return True
    if st["state"] == "open":
        if _now() - st["opened_at"] >= float(getattr(self.cfg, "breaker_reset_timeout", 120.0)):
            if not st.get("probing"):
                st["state"] = "half_open"; st["probing"] = True
                return True          # 放行唯一探针
            return False             # 已有探针在飞，其余拦住
        return False                 # 冷却未到
    # half_open：只允许探针那一个（probing 标记），其余拦
    return False

def _note_ok(self, host: str) -> None:
    with self._host_lock:
        st = self._host_cb.get(host)
        if st:
            st.update(state="closed", fails=0, probing=False)   # 探针成功→闭合；正常成功→清零

def _note_fail(self, host: str) -> bool:
    """记一次(非SSL)连接失败；返回是否已 open。"""
    newly_open = False
    with self._host_lock:
        st = self._host_cb.setdefault(host, {"state": "closed", "fails": 0, "opened_at": 0.0, "probing": False})
        if st["state"] == "half_open":
            st.update(state="open", opened_at=_now(), probing=False)   # 探针失败→重新 open
        else:
            st["fails"] += 1
            if st["fails"] >= self._breaker_threshold:
                if st["state"] != "open":
                    newly_open = True
                st.update(state="open", opened_at=_now())
    if newly_open:
        self.log.warning("host %s 连续失败已熔断(open)，%.0fs 后半开重试", host,
                         float(getattr(self.cfg, "breaker_reset_timeout", 120.0)))
    return st["state"] == "open"
```
`get()` 入口（替换原 `if host in self._host_down: return None`）：
```python
with self._host_lock:
    allowed = self._cb_allow(host)
if not allowed:
    return None      # open 且未到冷却 / 已有探针在飞 → 跳过
```
> `_now = time.monotonic`（比 `time.time()` 稳，免受系统时钟跳变；建议文件顶部 `_now = time.monotonic`）。

---

## 4. selftest 草案（沿用本文件既有 `_Session` 脚本注入法，不联网、秒过）

```python
# 追加到 http_client.py 的 __main__ selftest（关闭真实 sleep 后）：

# G1 Jitter：连续 429 → 退避落在 [0, cap]、且不恒等 2**n（抽样多次有方差）
c = _client([_Resp(429), _Resp(429), _Resp(200)], max_retries=3)
delays = []
_orig = time.sleep; time.sleep = lambda d: delays.append(d)
try: c.get("https://api.crossref.org/works")
finally: time.sleep = _orig
assert all(0.0 <= d <= 30.0 for d in delays) and len(set(delays)) > 1, delays  # 有抖动

# G2 AIMD：注入 429 → interval 乘性升；注入连续成功×N → 加性降但不破 floor
c = _client([_Resp(429), _Resp(200)], per_host_interval=0.34, max_retries=3)
c.get("https://pubs.acs.org/x")
assert c._host_interval["pubs.acs.org"] >= 0.68, c._host_interval          # ×2 penalize
c2 = _client([_Resp(200)] * 25, per_host_interval=0.34)
for _ in range(25): c2.get("https://api.openalex.org/works")
assert c2._host_interval.get("api.openalex.org", 0.34) >= 0.34             # 不破 floor

# G3 half-open：3 次连接错→open(拦)；快进时钟过 reset_timeout→放 1 探针；探针成功→closed
_t = [1000.0]; import fulltext_fetcher.http_client as H
H._now = lambda: _t[0]                                                     # mock monotonic
c = _client([ConnErr] * 3 + [_Resp(200)], max_retries=0, breaker_reset_timeout=120.0)
for _ in range(3): c.get("https://dead.test/x")                            # 触发 open
assert c.get("https://dead.test/x") is None                               # open 且冷却未到→拦
_t[0] += 121.0                                                             # 冷却已过
assert c.get("https://dead.test/x").status_code == 200                    # 半开探针成功→closed
```
> selftest 断言点：`RATE_JITTER_OK` / `AIMD_OK` / `HALF_OPEN_OK`；均不联网，用假 `_Session` 与 mock 时钟。

---

## 5. 落地检查清单（给实现者）
- [ ] `import random`、`_now = time.monotonic` 置文件顶部。
- [ ] `config.py` 加 5 个字段（§0），默认与现网等价/安全；`adaptive_rate` 可先默认 True 灰度，出问题可关。
- [ ] 两处 `2**attempt` → `_backoff_delay`；`Retry-After` 仍优先。
- [ ] `_host_down/_host_fail` → `_host_cb` 状态机；`_cb_allow/_note_ok/_note_fail` 三方法同步改。
- [ ] 429 分支加 `_aimd_penalize`；成功分支加 `_aimd_relax`。
- [ ] 扩 selftest 三断言；`python -m fulltext_fetcher.http_client` 打印 `HTTP_CLIENT_OK`。
- [ ] 回收执行期**勿动**（-156 定：避免 mid-recovery 破稳定）；排在回收后波次。

---
*核验 2026-07-02｜信息检索-智库专家 -177｜实现者参考骨架，非生产改动。零依赖、恪守既有不变量(SSL 豁免/锁/floor)；算法借鉴 AWS Full Jitter·TCP-AIMD·Nygard 半开·pyresilience(MIT)。*
