# OpenAlex-key 净增探针 -140 复验：返回 X / 真下 Y / 过 QC 净增 Z + 样例 DOI

> 工单：`task-6bcfc22c`（原指派 -155，已由 -155/-176 交付；本篇为 **-140 当前 still_missing 复验**）
> 执行：-140｜2026-07-03｜边界：**只读探针，未改 `coverage.json`（340 定版）/ 未跑批量回收 / 全程不开浏览器·不撞单头锁**
> 脚本：`_openalex_key_probe_140.py`｜产物：`out/openalex_key_probe_140/`（`summary.json` + `openalex_scan.jsonl`）

---

## 〇、TL;DR

| 指标 | 值 | 说明 |
|---|---:|---|
| **OPENALEX_KEY** | ✅ 已设（User env，len=22） | `OPENALEX_KEY` = `OPENALEX_API_KEY` |
| **still_missing 基数** | **660** | `out/still_missing.txt` @ 探针前（去 2 注释行） |
| **coverage 既有 openalex success** | **31** | 全库并集基线，非 miss 子集 |
| **X — API 返回 pdf_url** | **26 / 660（3.9%）** | 带 key 全量单条查，0 次 429，api_fail=4 |
| **无 key 对照（X 子集）** | **26 / 26 同样返回** | **key-only 增量 = 0** |
| **Y — 直连 HTTP 真下 %PDF** | **0 / 26** | 纯浏览器无关直连（无 route-B、无 landing 抽取） |
| **Z — 过内容 QC 净增** | **0 / 26** | 无候选可下 → 无净增 |

**一句话结论**：在**当前** still_missing 上，**OpenAlex key 的净增杠杆 = 0**。key 不解锁任何“新” `pdf_url`（26/26 无 key 也返回），唯一价值是**解除 $0.10/天限速**，让 660 条一次扫完。26 条命中 100% 落在**订阅/CF 付费墙或缩略图/落地页**，纯直连一条都下不动——真回收必须靠 **route-B / A5 机构订阅**，与 -155/-176 结论一致且更收紧。

---

## 一、诚实三层（返回 ≠ 可下 ≠ 净增）

| 层级 | 符号 | 结果 | 口径 |
|------|------|------|------|
| API 返回 OA `pdf_url` | **X** | **26 / 660** | `best_oa_location`/`primary_location`/`locations` 任一有 `pdf_url` |
| 真下到 `%PDF` | **Y** | **0 / 26** | 直连 HTTP GET（浏览器 UA、跟随跳转、超时 30s），魔数校验 `%PDF` |
| 过内容 QC 净增 | **Z** | **0 / 26** | 无 PDF 落地 → 无可判 |

> **本篇口径 = “OpenAlex + key 本身”的上限**：刻意**不开浏览器 / 不走 route-B / 不做 landing 内嵌 PDF 抽取**，测的就是「key 解锁 API + 直链能不能白嫖」的真实天花板。

---

## 二、关键发现：key 增量 = 0（带 key vs 无 key 对照）

对 X=26 的 DOI **逐条无 key 再查**（仅 `mailto` polite pool）：**26/26 同样返回 `pdf_url`**。

→ **`key_only_increment = 0`**：OpenAlex 的 `pdf_url` 元数据面对 **有无 key 完全一致**；key 不新增任何可下条目。key 的价值**仅**在 **1) 解除限速**（660 条一次扫完、全程 0 次 429）、**2) 稳定性**，与“净增文献”无关。

---

## 三、26 条命中分桶（下载层，全失败）

### 3.1 失败桶（`summary.json` 精确计数）

| 失败模式 | 条数 | 含义 |
|---|---:|---|
| `http-403-paywall/CF` | **15** | Cloudflare / 付费墙拦截（RSC / ScienceDirect / Wiley） |
| `not-pdf` | **9** | 返回 JPG 缩略图 / HTML 落地页，非 PDF 魔数 |
| `http-400` | **1** | 请求被拒 |
| `http-none(RemoteDisconnected)` | **1** | 连接被断 |

### 3.2 按域名 / OA 状态（精确，26 条全列）

| 域名 | 条数 | OA 状态 | 直连结局 |
|---|---:|---|---|
| `pubs.rsc.org`（RSC） | 11 | hybrid/bronze | 403 / CF |
| `ars.els-cdn.com`（Elsevier 缩略图） | 5 | bronze | not-pdf（JPG） |
| `www.sciencedirect.com` | 3 | bronze | 403 |
| `iopscience.iop.org`（IOP/ECS） | 2 | hybrid/bronze | not-pdf / 400 |
| `onlinelibrary.wiley.com` | 1 | bronze | 403 / CF |
| `downloads.hindawi.com` | 1 | hybrid | 403 |
| `www.repositorio.ufc.br`（绿色仓储） | 1 | green | not-pdf（落地 HTML） |
| `www.journal.csj.jp`（CSJ） | 1 | bronze | not-pdf |
| `sciopen.com` | 1 | hybrid | none / not-pdf |

**要点**：命中里 **bronze/hybrid 占 25/26**，green 仅 1 条。bronze = “出版商站可读、但无开放许可 / 无干净 PDF 直链”，OpenAlex 给的 `pdf_url` 常是**落地页或缩略图**，天然过不了直连——这正是 **X≠Y** 的根因。

---

## 四、与 -155 / -176 对账（为何本篇 Y=0 而它们 Y=1）

| 波次 | 输入 | X | Y | Z | 净增样例 | 下载口径 |
|---|---:|---:|---:|---:|---|---|
| -155（执行 -174） | 659 | 25 | 1 | 1 | `10.1039/c4ra14572k` | **全 Pipeline**：落地页→内嵌 PDF（repositorio.ufc.br） |
| -176 | 660 | 26 | 1 | 1 | `10.35848/1347-4065/ad280f` | 项目 `download_pdf` 硬化取（IOP 直链） |
| **-140（本篇）** | **660** | **26** | **0** | **0** | — | **纯直连 HTTP**，无浏览器 / 无 landing 抽取 |

**对账结论**：三波 **X 一致（25–26）**、**key 增量都 = 0**。-155/-176 的那 **1 条净增来自下游下载机制**（Pipeline 落地页抽取 / 硬化 `download_pdf`），**不是 OpenAlex key 或 API 的功劳**；一旦剥离下游机制、只看“key + 直链”本身，净增就归零。故：
- 面向“**OpenAlex key 到底带来多少净增**”这一问，**诚实答案 ≈ 0**；
- 那 1 条（`c4ra14572k` / `ad280f`）若要回收，走的是 **landing 抽取 / 硬化下载**，属既有下游能力，可另计，不应记在 key 头上。

---

## 五、与 run_all 缺口（-148/-176 已文档化，本波未改代码）

- `python -m fulltext_fetcher -f still_missing.txt`：env→Config 闭合，**key 生效** ✅
- `run_all.py` 批量：仍**不透传** `openalex_key` ❌（若要一键路径用 key，需在其 Config 构造补 `openalex_key=os.environ.get("OPENALEX_KEY")`）。
- 因 key 增量已实测 = 0，此缺口**不影响净增结论**，仅影响“批量扫描是否被限速”，优先级低。

---

## 六、建议（供总指挥裁决）

1. **回写**：本波净增 **0**，`coverage.json`（340）**无需改**；-155/-176 的 1 条如要入库，按“下游下载能力回收”另行裁决，勿归为 OpenAlex-key 净增。
2. **ROI 定性**：**OpenAlex key 不是 still_missing 的净增杠杆**。26 条命中 100% 属订阅/CF/缩略图/落地页，二次转化必须走 **route-B（CF/JA3）或 A5 机构订阅**。
3. **运营**：保留 User 级 `OPENALEX_KEY`（免限速利于全量扫描）；批量 miss 扫描用 CLI `-f`，勿依赖 run_all 直到缺口修补。
4. **可选 follow-up**：对这 26 条（RSC×11 为主）跑 `route-B cf-only` 子集探针，估「key 命中 + route-B」组合 Y/Z（须另开工单，避免与“key 本身”口径混淆）。

---

## 七、自检 / 复跑

```bash
python -X utf8 _openalex_key_probe_140.py     # 扫描(带key,避429)+无key对照+直连下载+QC，约 21min
#   → out/openalex_key_probe_140/summary.json  (X/Y/Z/key增量/分桶/rows)
#   → out/openalex_key_probe_140/openalex_scan.jsonl (660 条 API 快照)
```

**实测输出**：`X=26/660  无key同样=26/26(增量0)  Y=0/26  Z=0/26  桶={403/CF:15, not-pdf:9, 400:1, none:1}  用时 1248.5s  0×429`
