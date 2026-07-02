# 检索成果 · OpenAlex 强制 API Key 政策核查 + 免费 Key 落地清单

> 交付：**信息检索-智库专家岗**（承 -177，本会话）｜2026-07-02
> 触发：本轮全网扫描发现「OpenAlex 2026-02 起强制 API key」→ 用户/自决拍板「现在核查下游接线 + 出免费 key 申请/注入清单」。
> 边界：**只新建本 1 份文档**；核查=读 `sources/aggregators.py`/`config.py`/`cli.py` 源码 + 官方文档实检；**不改任何 .py**（若需改，附「给实现者的可选微清理」供其执行）。

---

## 〇、TL;DR（三句话）

1. **代码已就绪、无需改**：`sources/aggregators.py` 的 OpenAlex 源**已正确**在 `cfg.openalex_key` 存在时注入 `api_key` **查询参数**（官方文档指定的正确方式），且用的是**未废弃字段**（`primary_location` 等）。`config.openalex_key`+`cli --openalex-key`/`OPENALEX_KEY` 全链已通。
2. **唯一动作是运营层**：去 `openalex.org/settings/api` **申请免费 key（30 秒）→ 设 `OPENALEX_KEY` 环境变量**。不设：主线源 OpenAlex 只剩 **$0.10/天**（仅够 demo）、批量必 429/降级。
3. **好消息**：本仓 OpenAlex 用法＝**按 DOI 单条查（single work lookup）＝免费额度内「无限」**；免费 key 的 $1/天预算对本仓这种「逐 DOI 查」几乎永远用不完（只受 100 req/s 限，本仓按域限速已守）。**→ 免费 key 足矣，成本≈0。**

---

## 一、政策事实（官方，2026 实检）

| 项 | 事实 | 来源 |
|---|---|---|
| **是否强制** | **是**。API key 现为**所有请求必需**（2026-01 公告、约 2026-02-13 生效）；「无 key 仍可少量调用作 demo，但**不适合任何生产用途**」 | OpenAlex blog《New Features and Usage-Based Pricing》「API keys are now required」 |
| **免费额度** | 无 key：**$0.10/天**；免费 key：**$1/天**（10×）；超出走用量计费 | developers.openalex.org/api-reference/authentication |
| **关键：本仓用法成本** | **按 DOI/ID 单条查 = 每日免费调用「无限」**（list/filter 10k/天、search 1k/天、PDF/XML 下载 100/天） | OpenAlex blog 定价表（single work lookup by DOI = unlimited） |
| **申请方式** | 建账号 → `openalex.org/settings/api` 复制 key（~30 秒） | 官方 |
| **传参方式** | `?api_key=YOUR_KEY` **查询参数**（本仓正是此法 ✅） | 官方 curl 示例 |
| **限流** | >100 req/s 或超日预算 → **429**；用量在响应头 `X-RateLimit-*` 或 `/rate-limit` 端点查 | 官方 |
| ⚠️ **mailto 礼貌池已废** | **2026-02 起 `mailto` 参数被忽略**，礼貌池「被 API key 取代」 | developers.openalex.org/guides/deprecations「Polite pool → Replaced by API keys」 |

---

## 二、本仓代码现状核查（读源码，结论：已正确，无需改）

**`fulltext_fetcher/sources/aggregators.py` · OpenAlex.find_candidates（L42–46）**：
```python
params = {"mailto": ctx.cfg.email}
if ctx.cfg.openalex_key:
    params["api_key"] = ctx.cfg.openalex_key           # ✅ 官方指定的 api_key 查询参数
data = ctx.client.get_json(f"https://api.openalex.org/works/doi:{paper.doi}", params=params)
```
- ✅ **注入方式正确**：`api_key` 作查询参数（与官方一致）；仅在 key 存在时加（缺 key 不报错、优雅降级）。
- ✅ **用的是未废弃字段**：`best_oa_location` / `primary_location` / `locations` / `open_access.oa_url`——**未用**已移除的 `host_venue`（官方已 `host_venue→primary_location`），无 deprecation 雷。
- ✅ **端点是按 DOI 单条查** `works/doi:{doi}` → 命中免费「无限」档。

**插线（config/cli）已通**：
- `config.py:43` `openalex_key: Optional[str] = None`
- `cli.py:128` `--openalex-key`，缺省回落环境变量 `OPENALEX_KEY`
- `cli.py:167` `openalex_key=args.openalex_key` 注入 cfg

**结论**：**代码零改**。缺的只是「运营上没有一把 key」。

---

## 三、落地清单（运营，按顺序）

- [ ] **1. 申请免费 key**：登录/注册 `openalex.org` → 打开 `openalex.org/settings/api` → 复制 key。
- [ ] **2. 设环境变量**（PowerShell，注意本机是 PowerShell 非 cmd）：
  ```powershell
  $env:OPENALEX_KEY="你的key"      # 当前会话
  # 永久：setx OPENALEX_KEY "你的key"   （新开终端生效）
  ```
  或每次跑加 `--openalex-key 你的key`。
- [ ] **3. 冒烟验证**（任取一 DOI 跑 pipeline，看 OpenAlex 源是否恢复命中/不再 401-403-429）：
  ```powershell
  python -m fulltext_fetcher "10.1371/journal.pone.0000217" --email you@uni.edu
  ```
  或直接验 key 有效：`curl "https://api.openalex.org/rate-limit?api_key=你的key"`（应返回 `daily_budget_usd:1`）。
- [ ] **4. 北极星批量流程带上**：`run_all.py` 走的是 `Pipeline`，同样吃 `OPENALEX_KEY` 环境变量——设好环境变量即全流程生效，无需改 `run_all.py`。
- [ ] **5.（可选）多机/多会话**：回收/QC 多会话同机跑时，各自终端都要有 `OPENALEX_KEY`（环境变量或统一 `setx`）。

---

## 四、附带口径修订（本轮实检新增，供母表/⑤ 并入）

1. **OpenAlex `mailto` 礼貌池已废（2026-02）**：`mailto` 现被**忽略**、礼貌池由 key 取代。→ 本仓 aggregators.py 给 OpenAlex 同时传 `mailto`+`api_key` **无害**（mailto 被忽略、api_key 生效），但**不设 key 就真的只剩 $0.10/天**（旧「靠 mailto 进礼貌池」的隐含预期对 OpenAlex 已失效）。**注意：Crossref 的 mailto 礼貌池仍有效**（本仓 crossref/preprints 的 mailto 保留正确）——别把两者混改。
2. **E1 快照线口径微调**：`ingest.py` 读**本地** OpenAlex JSONL（离线）→ **不需 key**；但官方现口径「**免费快照＝季度更新**；**月度快照 / 每日 change files 需付费plan**」。→ E1「changefiles 增量」若要自动同步需付费，季度全量 bulk 仍免费（承 `检索成果-E2…E1快照增量补丁` 的 changefiles 注记，精确化为「季度免费/日更付费」）。
3. **其它 OpenAlex deprecation（本仓已规避，登记备查）**：`host_venue→primary_location`（本仓已用 primary_location ✅）、`has_ngrams→has_fulltext`、`Concepts→Topics`、`/text` 端点弃用。本仓 OpenAlex 源均未踩。

---

## 五、给实现者的可选微清理（非必须，代码活转实现者）

- `cli.py:113` help 文本「OpenAlex/Crossref 礼貌池」**已部分过时**：OpenAlex 礼貌池已废、改为 key；Crossref 礼貌池仍在。建议改为「Unpaywall 必需真实邮箱；**Crossref 礼貌池**；OpenAlex 需 `--openalex-key`（礼貌池已废）」。
- （可选）当批量跑且 `openalex_key` 为空时，`config`/启动处打一条 **warning**（「OpenAlex 无 key，仅 $0.10/天，建议设 OPENALEX_KEY」），把「静默降级」变「显式告警」。默认行为不变（不强制），仅提示。

---

## 六、来源

- 官方：`docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication`、`developers.openalex.org/api-reference/authentication`、`developers.openalex.org/guides/deprecations`、OpenAlex blog《API New Features and Usage-Based Pricing》。
- 佐证：`J535D165/pyalex` v0.21 README（「API Key Required starting February 13, 2026」）。
- 本仓 grep/读源码：`sources/aggregators.py:39-62`（OpenAlex 源已注入 api_key 查询参数、用 primary_location）、`config.py:43`、`cli.py:113/128/167`、`ingest.py`（OpenAlex 快照离线导入，无需 key）。

---

*核验 2026-07-02｜信息检索-智库专家岗（承 -177，本会话）｜工单「OpenAlex 强制 key 核查+落地清单」｜结论：代码已正确注入 api_key（零改），唯一动作＝申请免费 key 并设 `OPENALEX_KEY`；本仓「按 DOI 单条查」在免费档「无限」、成本≈0；附带订正 mailto 礼貌池已废、季度快照免费/日更付费。仅新建本 1 份文档，未改任何 .py。*
