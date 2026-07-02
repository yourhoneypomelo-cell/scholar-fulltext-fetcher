# route-B Phase2 · 全量 A 集发射 checklist（一页纸 · 纯文档 · 等 go/no-go）

> 交付：**谷歌学术人机认证-142**（worker）｜2026-07-02｜工单：总指挥-148 **task-fd12bb0c**。
> 用途：route-B **go/no-go 判绿后**，把 A 集（RSC 67 + MDPI 7）里**该发的 15 条**一次性发射的照做清单——含前置门、输入文件、命令模板、验收口径、失败回滚。
> 边界：**只新建本 1 份 md，不改任何 `.py`/产物**。数据/结论取自 `检索成果-路线B回收波发射优先级-A集rsc67MDPI7-150.md`、`route-B-Phase1冒烟结果-146.md`、`路线B-真机冒烟结果-152.md`、`路线B-浏览器内直下PDF验证Runbook-173.md`、`fulltext_fetcher/cli.py`（`--route-b` 三档）、`pipeline.py`（落盘结构）、`经验记录 N.1/N.4/N.5/N.8`。

---

## 〇、TL;DR（照排）
- **发射波 = 15 条**：MDPI **7**（先发，⑥ Akamai）+ RSC 真 OA **8**（次发，②b-B2 articlepdf）。RSC 订阅/closed **59 不发**（留 route-A / A5 机构订阅）。
- **发射前必须先过「前置门」5 项全绿**（见 §二），否则不得开波——尤其 **RSC B2 修法当前仍在工作树未提交**（见 §二·③）。
- **两桶开关不同**：MDPI 必须 `--route-b all`（才开 ⑥ `browser_pdf_download`）；RSC 用 `--route-b cf-only`（开 ②b `browser_capture`）。**⚠ 勿照 -150 文档给 MDPI 用 cf-only——cf-only 不开 ⑥，MDPI 会全 no-pdf。**
- 全程 **concurrency=1、单头有头、交互桌面**；**发射 15 ≠ 回收 15**（诚实点估真命中 +5~15，见 §六）。

---

## 一、A 集范围与分桶（74 = RSC 67 + MDPI 7；发 15 / 不发 59）

| 序 | 桶 | 清单文件（已由 -150 产，可直接 `-f`） | 条数 | 路径 | 开关 |
|:--:|---|---|:--:|---|---|
| **①先发** | MDPI 10.3390（全 OA） | `routeB_mdpi.txt` | **7** | ⑥ `_browser_pdf_download`（过 Akamai） | `--route-b all` |
| **②次发** | RSC 真 OA（4 RSC Adv 金OA + 4 is_oa 命中） | `routeB_rsc_goldoa.txt` | **8** | ②b `render_download_pdf_bytes` → **B2**（articlepdf，过盾后 Fetch.enable RESPONSE） | `--route-b cf-only` |
| **③不发** | RSC 订阅/closed | `routeB_rsc_subscription.txt` | **59** | —— 留 route-A（A5 凭据 gate） | 不跑 route-B |

> ③ route-B 对订阅墙返 `no-pdf` 是**正确行为、非 bug**（N.8）；投算力必浪费 → 不发。

---

## 二、前置门（go/no-go gate · 5 项全绿方可开波）

| # | 门 | 通过判据 | 现状（-142 核） |
|:--:|---|---|---|
| ① | **-152 两样本齐绿**（生产 render_fetch） | ACS-OA B1 落 %PDF + RSC B2 落 %PDF，均 QC=match | B1 ✅（13.8~13.95MB）；RSC B2 ✅ 生产路径已抓 484KB（`verify_prod_152`，18:43:49）——但仅 **1/1**，建议 RSC×3 复跑坐实 3/3 |
| ② | **-141 离线 selftest 全绿** | `python -m fulltext_fetcher.render_fetch --selftest` → `RENDER_OK`；`python run_all_selftests.py` → PASS 全绿（含 render_fetch 字节扩展点用例） | 依 -141/-146 记录全绿；开波前当场复跑一次 |
| ③ | **render_fetch.py + download.py 已提交检查点** | render_fetch：B2 方法C（过盾后门控 `Fetch.enable` RESPONSE）+ `PreflightWarn`/`LocalNetworkAccessRequestPolicy` 枚举容错；download：QC 依赖 **fail-closed**（-143，含 `_selftest ⑦.9` 契约更新）——均在 HEAD | **⚠ 未过**：`render_fetch.py`（B2 修法，-144）与 `download.py`（QC fail-closed，-143）**均为工作树 `M` 未提交**（自 `1a6127c` 后）→ **须由 -144/-143 一并提交为同一检查点**，否则回滚/复现无锚点 |
| ④ | **pypdf 已装 + 内容 QC fail-closed** | `content_qc=on`、`content_qc_non_article_hard_reject=True`；-143 已把 QC 依赖改 **fail-closed**（默认 `require_deps=True`：缺 pypdf → **拒收不落盘**+事件 `deps-missing`，不再静默放行假阳）→ **缺 pypdf 时真命中也会被拒、颗粒无收** | 开波前**必须** `pip install pypdf rapidfuzz`，并确认 `render_fetch/download/pipeline/cli` 四模块 `--selftest` 全 OK |
| ⑤ | **单头/并发/显示纪律** | route-B 全局 **concurrency=1**、**有头**（不加 `--browser-headless`）、**交互桌面**（非无显示会话，否则 CF/Akamai 必败）；out 目录写锁 + `out/.route_b.lock` 均可用 | 单机单头、全组共一机（N.8 #1） |

> **一句话**：①②④⑤ 属运维当场自检；③ 是**硬阻塞**——请总指挥先让 -144（`render_fetch.py` B2 修法）+ -143（`download.py` QC fail-closed）一并提交为检查点，再发波。

---

## 三、输入文件（-150 已产，位于仓根，`-f` 直用）
```
routeB_mdpi.txt            # 7  MDPI 金OA（先发）
routeB_rsc_goldoa.txt      # 8  RSC 真OA（4 RSC Adv + d0gc02302g/d2gc02623f/d3ee02589f/d5fd00172b）
routeB_rsc_subscription.txt# 59 RSC 订阅/closed（不发，留 A5）
```

---

## 四、发射命令模板（PowerShell · 按序 · concurrency=1）

```powershell
cd "E:\AI项目\谷歌学术人机认证"

# 前置门②：开波前离线自检（须全绿）
python -m fulltext_fetcher.render_fetch --selftest
python run_all_selftests.py

# ① 先发 MDPI 7（Akamai ⑥ → 必须 --route-b all；有头、单并发、放宽超时与渲染等待）
python -m fulltext_fetcher -f routeB_mdpi.txt `
  -o out\routeB_A_mdpi --email you@org.edu `
  --route-b all -c 1 --timeout 120 --browser-pdf-wait 20

# ② 次发 RSC 真OA 8（②b-B2 → --route-b cf-only；有头、单并发、放宽超时）
python -m fulltext_fetcher -f routeB_rsc_goldoa.txt `
  -o out\routeB_A_rsc --email you@org.edu `
  --route-b cf-only -c 1 --timeout 120

# ③ RSC 订阅 59：不跑 route-B（留 route-A / A5）
```
> 说明：`-c` 默认 4、`--timeout` 默认 30 —— route-B **必须**显式改 `-c 1`、`--timeout 120`（CF/Akamai 过盾 ~15–45s，30s 会误杀）。`--browser-pdf-wait` 仅 `--route-b all` 生效（MDPI 用）。有头默认，**不要**加 `--browser-headless`。断点续跑默认开（已成功项跳过）。

---

## 五、验收口径（每条落盘必核）

**落盘结构**（CLI 直写 `<out>` 根，非 `fetch/` 子目录）：
```
out\routeB_A_mdpi\pdfs\*.pdf   + metadata.jsonl + attempts.jsonl + summary.json + results.csv + report.html
out\routeB_A_rsc \pdfs\*.pdf   + metadata.jsonl + ...
```

逐条判据：
1. **真 PDF**：`pdf_bytes[:4]==b"%PDF"` 且 size 合理（MDPI 数 MB、RSC articlepdf 数百 KB~MB）。
2. **内容 QC 非 mismatch**：`python tools\qc_content_match.py`（或 pypdf 抽首页）→ page-1 DOI/标题 = 期望 DOI；硬拒 SI/citation-report/poster/错论文（经验记录 M/N）。**Runbook 通过附加条件：成功样本 QC=match。**
3. **metadata**：`metadata.jsonl` 该 DOI `success:true`、`source` 含 `browser_capture`/`render`（DOI 绑定源，过 QC 才计净覆盖）。
4. **不误报**：若 RSC 订阅条误入，应落 `no-pdf` / `blocked:challenge-page`，**不得**出现假 `%PDF` —— 计正确、不计失败。
5. **并入覆盖**：命中经 `_agg_recover_150.py` / `tools\build_coverage.py` 重建并入 `out\coverage.json`（**注**：当前权威 coverage 生成于 18:25:56，早于 route-B 产物，须重建才反映净增；对外仍以重建后权威数为准）。

---

## 六、失败回滚 / kill-switch

| 场景 | 处理 |
|---|---|
| **紧急停波** | route-B 默认 `--route-b off`；停当前批＝Ctrl-C，后续批不加 `--route-b` 即全关，**主线不受影响**（能力默认关） |
| **假阳回潮**（落 %PDF 但 QC mismatch） | 收紧 `content_qc_non_article_hard_reject=True`；拒收该 DOI，不并入覆盖 |
| **CF/Akamai 过不去** | 确认有头窗口真弹出、交互桌面；`--timeout 120`；同 origin 重试；仍不过＝该桶 no-pdf（订阅墙为正确行为） |
| **单条 hang > timeout** | 依 header pid 杀进程；`out\.route_b.lock` 陈旧锁按 mtime 自动接管，必要时手删 |
| **out 目录写锁冲突** | 每桶独立 `-o`（`routeB_A_mdpi`/`routeB_A_rsc`）避免并发写同一 out；`<out>\.lock` 冲突＝有另一进程在写，勿并发 |
| **依赖版本错配洪水**（`PreflightWarn` 等） | 前置门③的 `render_fetch` 枚举容错已回退 `ALLOW`；若未提交则先补③ |
| **覆盖/still_missing 误写** | 重建 coverage 前先备份（仓内 `bak_YYYYMMDD_..._pre<batch>_writeback` 命名惯例）；QC 未过不写回 |

---

## 七、诚实 ROI（防高估，务必带上）
JA3 绑定型 CF 后的真 OA 桶本就小（~5–15，N.4/-173）；**发射 15 ≠ 回收 15**，真 %PDF 命中点估 **+5~15**。RSC 在 batch6 口径净 MISS≈0（websearch 已兜回），单为 RSC 破盾**边际≈0**。A 集价值在**点亮 JA3 机制 + 从权威落地页直下提质（绕 websearch 68.5% 假阳）**，**不在清空 still_missing**；首要收益是**省算力**（59 订阅不空跑）。

---
*核验 2026-07-02｜-142｜task-fd12bb0c「route-B Phase2 全量 A 集发射 checklist」｜结论：发 15（MDPI 7 `--route-b all` 先发 + RSC 真OA 8 `--route-b cf-only` 次发）/ 不发 59；开波前 5 前置门全绿（唯一硬阻塞＝③ render_fetch.py 待 -144 提交）；命令/验收/回滚照 §四~六。新建 1 md，未改任何 .py。*
