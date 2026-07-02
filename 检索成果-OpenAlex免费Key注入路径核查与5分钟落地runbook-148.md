# OpenAlex 免费 Key · 注入路径核查 + 5 分钟落地 Runbook

> 交付:P2·只读工单「OpenAlex 免费 key 注入路径核查 + 落地 runbook」｜会话 -148｜2026-07-02
> 边界:**纯只读源码 + 文档,不改任何 .py**。核查=读 `sources/aggregators.py` / `config.py` / `cli.py` / `run_all.py` 源。
> 承接:与《检索成果-OpenAlex强制APIKey核查与免费Key落地清单.md》同题,但**本文实证订正其 §三.4 一处错误结论**(见 §4)。

---

## 〇、TL;DR(30 秒)

1. **动作只在运营层**:去 `openalex.org/settings/api` 申请免费 key(30s)→ 设 `OPENALEX_KEY` 环境变量 → 冒烟验证。本仓 OpenAlex 用法是「按 DOI 单条查」,在免费档≈无限、成本≈0。
2. ✅ **CLI 路径已通、可直接用**:`python -m fulltext_fetcher …`(含 `-f 清单.txt` 批量)会从 `OPENALEX_KEY` 读 key 并以 `api_key` 查询参注入请求,**读源确认全链闭合**。
3. ⚠️ **关键缺口(实证)**:一键批量脚本 **`run_all.py` 当前不读 `OPENALEX_KEY`**——它构造 `Config` 时压根没传 `openalex_key`,`Config`/`Pipeline` 又都不自读 env。**即便设了环境变量,`run_all.py` 批量流的 OpenAlex 仍走「无 key·$0.10/天」**。两条出路见 §3。

---

## 一、注入路径核查(读源逐段,结论:CLI 通、run_all 断)

**① 请求端(注入方式正确)** — `fulltext_fetcher/sources/aggregators.py` L42–46:

```python
params = {"mailto": ctx.cfg.email}
if ctx.cfg.openalex_key:
    params["api_key"] = ctx.cfg.openalex_key          # 官方指定的 api_key 查询参
data = ctx.client.get_json(f"https://api.openalex.org/works/doi:{paper.doi}", params=params)
```
- ✅ 仅在 `cfg.openalex_key` 非空时加 `api_key`,缺 key 优雅降级(不报错);字段用 `best_oa_location/primary_location/locations/open_access.oa_url`,**无 deprecated 字段**。

**② 配置端(默认 None,不自读 env)** — `fulltext_fetcher/config.py` L43:

```python
openalex_key: Optional[str] = None
```
- `Config` 数据类**无 `__post_init__`**、无任何读 `OPENALEX_KEY` 的逻辑;`Pipeline` 亦不读(grep 无匹配)。→ **`cfg.openalex_key` 完全依赖构造方显式传入**。

**③ 两条构造路径对比(链路成败的分水岭):**

| 入口 | 是否把 `OPENALEX_KEY` 接进 `Config` | 结论 |
|---|---|---|
| `python -m fulltext_fetcher …`(单条 / `-f` 文件批量) | `cli.py:128` `--openalex-key` 缺省回落 `os.environ.get("OPENALEX_KEY")` → `cli.py:190` `Config(openalex_key=args.openalex_key)` | ✅ **env→args→cfg→api_key 全链闭合,真实生效** |
| `run_all.py`(北极星一键批量) | `run_all.py:260–270` `Config(email=…, out_dir=…, …)` **未传 `openalex_key`** → 取默认 `None` → `Pipeline(cfg)`(L283) | ❌ **api_key 不注入**;设了 env 也无效 |

> 旁证:`run_all.py` 同样**未透传** `s2_key` / `core_key` / `snapshot_db` / `institutional` 等(只接了 email / 并发 / route-b 等)。即凡靠环境变量/CLI 提供的凭据,在一键批量流里目前都被丢弃——OpenAlex 只是其中最要命的一个(它是主线源、且 2026-02 起无 key 仅 $0.10/天)。

---

## 二、5 分钟 Runbook(CLI 路径,已核实可用)

- [ ] **1. 申请免费 key(约 30s)**:登录/注册 `openalex.org` → 打开 `openalex.org/settings/api` → 复制 key。
- [ ] **2. 设环境变量**(本机是 PowerShell):
  ```powershell
  $env:OPENALEX_KEY="你的key"           # 仅当前终端会话
  setx OPENALEX_KEY "你的key"           # 永久(需新开终端才生效)
  ```
  或每次跑显式加 `--openalex-key 你的key`。
- [ ] **3. 验 key 有效(可选,10s)**:
  ```powershell
  curl "https://api.openalex.org/rate-limit?api_key=你的key"     # 期望返回 daily_budget_usd:1
  ```
- [ ] **4. 单条冒烟**(看 OpenAlex 源恢复命中、不再 401/403/429):
  ```powershell
  python -m fulltext_fetcher "10.1371/journal.pone.0000217" --email you@uni.edu
  ```
- [ ] **5. 文件批量(仍走已验证的 CLI 路径,吃 env ✅)**:
  ```powershell
  python -m fulltext_fetcher -f dois.txt --email you@uni.edu
  ```

> 5 分钟内即可让 OpenAlex 恢复到免费 key 档。**注意:这条 runbook 走的是 `python -m fulltext_fetcher`;若你用 `run_all.py` 一键批量,先看 §3。**

---

## 三、run_all.py 一键批量:两条出路

**出路 A — 零改、立即可用(推荐先用):** 批量改用 CLI 入口(它读 env):
```powershell
python -m fulltext_fetcher -f 清单.txt --email you@uni.edu -o out/run
```
放弃 `run_all.py` 的跨批去重/续跑/QC 一页式总结等编排能力,但 OpenAlex key 立即生效。

**出路 B — 实现者 1 行改(长期正解,超出本只读工单):** 在 `run_all.py:260` 的 `Config(...)` 补一行(与核心 CLI 口径一致):
```python
import os
cfg = Config(
    email=args.email or "anonymous@example.com",
    openalex_key=os.environ.get("OPENALEX_KEY"),   # ← 补这一行(顺带可加 s2_key/core_key/snapshot_db)
    ...
)
```
本文属只读工单,**不代改**;已将此缺口 + 1 行修复回报总指挥转交代码活实现者。

---

## 四、订正既有文档(实证)

《检索成果-OpenAlex强制APIKey核查与免费Key落地清单.md》**§三.4** 称:
> 「run_all.py 走的是 Pipeline,同样吃 OPENALEX_KEY 环境变量——设好环境变量即全流程生效,无需改 run_all.py。」

**——实证不成立。** `run_all.py:260–270` 构造 `Config` 时未传 `openalex_key`,`Config`/`Pipeline` 也不自读 env,故一键批量流不会注入 api_key。以本文 §1 表格与 §3 为准。该文其余结论(注入方式正确、未用 deprecated 字段、按 DOI 单条查免费档≈无限、mailto 礼貌池 2026-02 已废)均复核无误。

---

## 五、验收自检

- [ ] 明白「设 `OPENALEX_KEY` 后用 `python -m fulltext_fetcher …` 立即生效」。
- [ ] 明白「直接用 `run_all.py` 时 key **当前不生效**」,并已在出路 A / 出路 B 中择一。
- [ ] (可选)`curl …/rate-limit?api_key=…` 返回 `daily_budget_usd:1`,确认 key 真有效。

---

## 六、来源(本仓读源,行号 2026-07-02 核验)

- `fulltext_fetcher/sources/aggregators.py` L38–62(OpenAlex 源;L42–46 注入 `api_key` 查询参、字段未 deprecated)。
- `fulltext_fetcher/config.py` L37–165(`Config` 数据类;L43 `openalex_key: Optional[str] = None`;无 `__post_init__`/不读 env)。
- `fulltext_fetcher/cli.py` L128(`--openalex-key` 缺省回落 `OPENALEX_KEY`)、L190(`Config(openalex_key=args.openalex_key)`)。
- `run_all.py` L260–270(`Config(...)` 未传 `openalex_key`)、L283(`Pipeline(cfg)`)。
- 官方政策与免费额度(2026):见同题《…免费Key落地清单》§一/§六(OpenAlex blog《Usage-Based Pricing》「API keys are now required」、developers.openalex.org 认证/弃用页)。

---

*核验 2026-07-02｜P2 只读工单「OpenAlex 免费 key 注入路径核查 + runbook」｜结论:CLI 路径 env→api_key 全链已通(零改可用);**发现并实证 `run_all.py` 一键批量流不注入 api_key** 的缺口(既有文档 §三.4 结论被订正),给出出路 A(改用 CLI 批量,零改)与出路 B(run_all.py 补 1 行,转实现者)。仅新建本 1 份文档,未改任何 .py。*
