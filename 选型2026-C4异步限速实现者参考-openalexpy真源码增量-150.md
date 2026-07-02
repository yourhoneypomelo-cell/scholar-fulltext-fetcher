# 选型2026 · C4 异步限速实现者参考 — openalex-py 真源码 + OpenAlex 官方 2026 口径增量

> 交付：**谷歌学术人机认证-150**（worker · 信息检索-专家智库岗）｜2026-07-02｜用户点名「定向读 openalex-py 的异步限速 / cost-aware 源码 → 出 C4 aio.py 节流增量设计参考」。
> 边界：**只新建本 1 份增量参考，未改任何 `.py`**。C4 代码活归 -168。
> 关系：本文是 `选型2026-C4异步限速熔断实现者参考-openalex-py与PyrateLimiter.md`（-177 骨架）的**真源码 + 官方口径增量**——本轮实读 openalex-py **v0.1.0** README/API 与 **OpenAlex 官方 2026 rate-limit 文档 + pyalex README**，补 -177 骨架里**猜测/过时**的三处口径。**-177 骨架的 AsyncHostGovernor / async_polite_get 主体仍成立**，本文只订正口径 + 加 1 个新能力。

---

## 〇、TL;DR — 真源码/官方比 -177 骨架订正的 3 点 + 新增 1 能力

| # | -177 骨架里的说法 | 真源码 / 官方 2026 口径 | 影响 |
|:--:|---|---|---|
| **订正1·限速头** | `_is_daily_exhausted` 只猜 `X-RateLimit-Remaining` | **官方确切 4 头**：`X-RateLimit-Limit`（日额度上限）/ `X-RateLimit-Remaining`（今日剩余）/ `X-RateLimit-Credits-Used`（**本请求**耗credit）/ `X-RateLimit-Reset`（**距重置秒数**，午夜 UTC） | governor 可读**确切剩余 + 重置秒数**算 `reset_at`，不再靠猜 |
| **订正2·singleton 额度** | 增补 M.4 / -177：**"singleton = 0 credit、按 DOI 单条查永久无限"** | **官方 credit_costs 现列 `singleton:1`**（list:10 / content:100 / vector:1000 / text:1000）；**pyalex README 仍称 singleton=Free(0)** —— 两权威源不一致 | 口径收严：**别写死"0 credit"**；无论 0 还是 1，**免费 key 100k/天 ≫ 本仓 999 DOI 用量 → 成本≈0 结论不变**，但措辞要带出处 |
| **订正3·免费额度** | 表述含混 | **无 key = 100 credit/天（仅 demo）**；**免费 key = 100,000 credit/天**；**全员 100 req/s 硬顶**（超则 429）。官方另有"$1/天"表述（计价口径） | 主守 = **100 req/s + 礼貌**，额度对本仓非瓶颈（承 M.4） |
| **新增能力** | 无 | **`get_rate_limit_status()` / `GET /rate-limit?api_key=`** 返回结构化 `credits_limit/used/remaining/resets_at/resets_in_seconds/credit_costs` | governor **批前主动查一次**播种预算，而非只被动等 429 |

> 一句话增量：真源码给了**确切的限速头字段 + 一个可主动查余额的端点**，让 -177 的「被动 429 退避」升级为「**批前播种 + 运行时自适应**」；同时**订正**了「singleton=0 credit」这个可能过时/源相关的口径（改为带出处、结论不变）。

---

## 一、现状缺口（实读 aio.py，与 -177 一致，复核确认）

`fetch_many_async` 只有一道 `asyncio.Semaphore(max_concurrency)` 全局并发闸；`_httpx_locate_fetch` 内 `client.get(...)` **裸调**——**无按域限速、无熔断、无退避 / Retry-After、无限速头解析**。海量「定位」打同一 OA API 易 429/403 burst 且无自愈。**这与 -177 判断一致，本文不重复其 `AsyncHostGovernor` / `async_polite_get` 主体骨架**（那部分仍照用），只补下面的真源码口径。

---

## 二、订正1 — 用官方确切限速头（替换 -177 的猜测实现）

openalex-py **cost-aware** 的核心＝解析这 4 个头（OpenAlex 每响应都带）：

| 头 | 含义 | governor 用途 |
|---|---|---|
| `X-RateLimit-Limit` | 今日 credit 总上限（免费 key=100000） | 播种 `daily_limit` |
| `X-RateLimit-Remaining` | 今日剩余 credit | `<=0` → 判日额度耗尽（快速失败，别硬刚） |
| `X-RateLimit-Credits-Used` | **本请求**消耗 credit | 累计观测真实成本；singleton 实测是 0 还是 1 一看便知 |
| `X-RateLimit-Reset` | **距重置的秒数**（午夜 UTC 归零） | 算 `reset_at = now + reset_seconds`，`CreditsExhaustedError` 记之 |

订正 -177 的 `_is_daily_exhausted` / reset 逻辑：
```python
def _rate_headers(r) -> dict:
    h = getattr(r, "headers", {}) or {}
    def _f(k, d=None):
        try: return float(h.get(k)) if h.get(k) is not None else d
        except (TypeError, ValueError): return d
    return {"limit": _f("X-RateLimit-Limit"), "remaining": _f("X-RateLimit-Remaining"),
            "used": _f("X-RateLimit-Credits-Used"), "reset_s": _f("X-RateLimit-Reset")}

def _is_daily_exhausted(r) -> bool:
    rem = _rate_headers(r).get("remaining")
    return rem is not None and rem <= 0            # 官方语义:剩余<=0 即耗尽

def _reset_at(r):                                   # 供 CreditsExhaustedError(reset_at)
    import time
    s = _rate_headers(r).get("reset_s")
    return (time.time() + s) if s else None
```

**两类限流分治（承 openalex-py `CreditsExhaustedError(reset_at)` vs `RateLimitError(retry_after)`）**：
- **429 且 `Remaining<=0`（日额度耗尽）** → **快速失败**，记 `reset_at`，**别重试硬刚**（重试也只会继续 429 到午夜）。
- **429/403 burst（Remaining 尚有）或 5xx** → **按 `Retry-After` 或 Full-Jitter 退避重试**（这才是 -177 governor 的自适应场景）。

---

## 三、订正2/3 — credit 口径带出处（防"别被数字骗"复发）

**权威源不一致，必须都记、按用量下结论**：
- **OpenAlex 官方 `ourresearch/openalex-docs`**（rate-limits-and-authentication.md）：`credit_costs = {singleton:1, list:10, content:100, vector:1000, text:1000}`；免费 key **100,000 credit/天**、全员 **100 req/s**。
- **pyalex README**：**Singleton requests（`/works/W123`）= Free (0 credits)**；无 key 100 credit/天、有 key 100k/天。
- **OpenAlex Web 概览**：免费 key "**$1/天**免费额度"（计价口径，与 credit 口径并存）。

→ **口径收严（订正 M.4 的"按 DOI 单条查在免费档无限"）**：本仓按 DOI 走 **singleton**（`/works/doi:<DOI>`），单条成本 = **0 或 1 credit（视权威源）**。**无论取哪个：免费 key 100k credit/天 ≫ 本仓 999 DOI（≤999 或 ≤~999 credit）→ 成本≈0、不是瓶颈的结论不变**，但**别再写"0 credit / 永久无限"死话**，写"singleton=1 credit（pyalex 记 0），100k/天免费 key 下本仓用量成本≈0"。真正要守的是 **100 req/s 硬顶 + 礼貌**（承 M.4，不变）。

> 教训（并入"外部 API 口径有时效、同类不可类推"）：**同一事实两个官方源给不同数**（singleton 0 vs 1）——引用必带出处 + 时间戳，结论落到"对本仓用量的实际影响"而非抠单价。

---

## 四、新增能力 — `get_rate_limit_status()`：批前播种预算（-177 没有）

openalex-py 暴露 `await client.get_rate_limit_status()`；对应官方端点 `GET https://api.openalex.org/rate-limit?api_key=YOUR_KEY`，返回：
```json
{"rate_limit": {"credits_limit":100000,"credits_used":1234,"credits_remaining":98766,
                "resets_at":"...","resets_in_seconds":43200,
                "credit_costs":{"singleton":1,"list":10,"content":100,"vector":1000,"text":1000}}}
```
**用途（给 governor 的增量）**：大批「定位」**开跑前查一次**，把 `credits_remaining` / `resets_in_seconds` 播种进 `AsyncHostGovernor`：
```python
async def seed_from_rate_limit(governor, client, api_key):
    """批前主动查余额播种(仅 OpenAlex 有此端点;失败静默降级,不阻断)。"""
    if not api_key:
        return                                  # 无 key:走保守默认速率(M.4:无 key 只 demo)
    try:
        st = (await client.get(f"https://api.openalex.org/rate-limit",
                               params={"api_key": api_key})).json()["rate_limit"]
    except Exception:  # noqa: BLE001
        return
    if st.get("credits_remaining", 1) <= 0:     # 已耗尽 → 本批 OpenAlex 直接快速失败/降级到别的源
        governor.mark_exhausted("api.openalex.org", reset_s=st.get("resets_in_seconds"))
```
> 价值：从"撞到 429 才知道没额度"升级为"**开跑前就知道该不该用 OpenAlex**"——耗尽时直接把定位让给 unpaywall/crossref 等其它源，省掉一整批必然 429 的空跑。仅 OpenAlex 有此端点；其它源无、走 -177 的被动退避。

---

## 五、接进 aio.py（承 -177 §四，最小侵入、向后兼容）

- `fetch_many_async` 建 1 个 `AsyncHostGovernor` 传各 `_worker`（-177 已给）；`_httpx_locate_fetch` 内 `client.get` 换 `async_polite_get`（-177 已给）。
- **本文新增两处接线**：① `_worker`/定位实现用**本文 §二 的确切头解析**（替换 -177 猜测版）；② 批前调**本文 §四 `seed_from_rate_limit`**（有 key 才生效）。
- **兼容**：Semaphore 保留（全局并发预算）；governor/seed 叠加按域精细节流；`_fetch` 注入路径（selftest）不受影响；无 key / 无 `/rate-limit` → 静默走保守默认，不阻断。

selftest 增量（离线、注入假响应，并入 aio `_selftest`）：
- `_rate_headers` 解析 4 头齐全；缺头 → None 不崩。
- `Remaining=0` → `_is_daily_exhausted=True` → `async_polite_get` **不重试**直接返回。
- `Reset=43200` → `_reset_at` ≈ now+43200。
- `seed_from_rate_limit`：注入 `credits_remaining=0` → `governor.mark_exhausted` 被调；无 key → 直接 return 不查。
- 打印 `AIO_GOVERNOR_OK`。

---

## 六、选型与护栏（承 -177，不变）

1. **默认零依赖自研**（同步 D3 算法镜像到异步）；异步桶若纳 1 依赖用 **PyrateLimiter**。
2. **礼貌优先**：OpenAlex 100 req/s 硬顶 → 默认 `rate_per_s` 保守（如 5/域）、Semaphore 别拉太高。
3. **区分限流 vs 故障**：429/限流是**信号**（收紧+退避、不计熔断）；连接/5xx 是**故障**（计熔断）。别把限流误判成故障熔断掉源。
4. **下载仍走同步核心**（aio 只做定位/元数据高吞吐）；C4 归 -168。
5. **口径纪律**：credit 数字带出处+时间戳，结论落"对本仓用量的影响"。

---

## 七、来源

- **openalex-py v0.1.0**（Luigi Palumbo，MIT，async-first，实读 PyPI/README）：cost-aware 解析 `X-RateLimit-*`、`cost_usd` on every response、`CreditsExhaustedError(reset_at)` vs `RateLimitError(retry_after)`、`await client.get_rate_limit_status()`、`api_key` 查询参数、两步内容下载保留限速头、semantic 自动 1 req/s。
- **OpenAlex 官方 2026**（`ourresearch/openalex-docs` rate-limits-and-authentication.md + `developers.openalex.org` `/rate-limit` 端点 OpenAPI）：确切 4 头（Limit/Remaining/Credits-Used/Reset）、`credit_costs{singleton:1,list:10,content:100,vector:1000,text:1000}`、免费 key 100k/天、100 req/s 硬顶、`GET /rate-limit` 结构。
- **pyalex README**（J535D165）：API key 自 **2026-02-13 必需**（免费）；**singleton=Free(0 credits)**（与官方 credit_costs 的 1 不一致——本文按用量下结论）；`max_retries/retry_backoff_factor/retry_http_codes` 配置模式。
- 本仓：`aio.py`（实读：仅 Semaphore、无节流）、`选型2026-C4异步限速熔断实现者参考-openalex-py与PyrateLimiter.md`（-177 骨架）、`经验记录-增补-本轮五大定论 M.4`（OpenAlex mailto 已废、key 唯一动作）、`sources/aggregators.py`（OpenAlex 已注入 api_key）。

---
*核验 2026-07-02｜-150｜工单「定向读 openalex-py → C4 aio.py 节流增量」｜结论：-177 的 AsyncHostGovernor/async_polite_get 主体成立；真源码/官方订正三处口径（确切 4 限速头、singleton 额度 0 vs 1 带出处、免费额度 100k/天+100req/s 硬顶）+ 新增 `get_rate_limit_status` 批前播种预算能力。成本对本仓用量≈0 结论不变但措辞收严。C4 归 -168。仅新建本 1 份参考，未改任何 .py。*
