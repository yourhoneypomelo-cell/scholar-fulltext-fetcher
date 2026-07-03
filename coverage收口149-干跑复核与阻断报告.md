# coverage 诚实口径收口 · 干跑复核与阻断报告（副手 -149）

> 交付：**谷歌学术人机认证-149**（数据/coverage 副手）｜2026-07-03｜taskId=`task-2a87350d-1a1e-4668-aef6-b3e84572422f`（总指挥派）
> 授权边界：**只读复核 + `--no-write` 干跑**；**未写 coverage.json / still_missing / 黑名单**；**未发真下载**。仅新写：3 份小清单(`out/_writeback149_*.txt/json`) + 3 个只读诊断脚本(`_writeback149_*.py`) + 本 md。
> 结论一句话：**干跑未达 377，实测 allow-only=324；诚实可达上限=368（非 377）；且 +50 gold 需一步物理前置（解隔离 47 份 rejected PDF）方能落地——已停手待 GO。**

---

## 〇、TL;DR（给总指挥 -157）

| 项 | 数值/结论 |
|---|---|
| 基线复现 | `python tools/build_coverage.py --no-write <配方>` → **success=326 / miss=673 / 999 = 32.63%**，与盘上 coverage.json **逐字一致** ✓ |
| 复核·59 gold | 148 证据全 `doi_in_body=True`、`is_si=False`；**我独立重开卷 50 条 miss-gold：44 doi_in_body 复现 + 6 标题≥0.5，0 可疑/re-假阳（100% 合法）** |
| 复核·8 假阳 | 均 current **success** 的 websearch 错 PDF（3× 同一 355744B「Hydrogenation lab safety Fact Sheet」+ 气象图/CasaXPS 手册/C1 化学书/配电盘/蓄电池）——确为假阳，应剔 |
| **干跑(allow-only +gold59 −fp8)** | **success=324 / miss=675 = 32.43%（净 −2，非 +51）** ⚠️ |
| **达标?** | **否**。目标 377 与实测 324 差 53 |
| 诚实可达上限 | **368 / 999 = 36.84%**（+50 gold −8 fp），**但需前置解隔离**；**377 是把 9 条已计成功重复计了** |
| 状态 | **STOP·need_input**：按红线「非≈377 一律停手报我」，等你定方向再动 |

---

## 一、基线复现配方（已验证 = 326）

盘上 coverage.json 为 **experimental·extra-dirs** 口径（`_scan.caliber`），复现命令：

```powershell
python tools/build_coverage.py --no-write `
  --extra-dirs "rerun_elsevier_143/fetch,rerun_acs_144/fetch,rerun_wiley_144/fetch,t0_recover_156/fetch" `
  --qc-allow "out/_coverage_allow_v2_11_155.txt" `
  --qc-extra-reject "out/rerun_acs_144_deduct_dois_145.txt" --print-json
```
→ `success=326, miss=673, allow_override=10, rejected_total=188`（与盘上 summary 完全一致）。

---

## 二、复核结论（严防 re-假阳）

### 2.1 59 gold（源：`out/_nextwave_176_qc_flip.json`，148 交付，flip_high=59）
- 148 证据：59/59 `doi_in_body=True`、`is_si=False`、均有 `pdf_used`。
- **-149 独立重开卷复核**（复用生产门 `_openbook_pdf_body/_openbook_doi_in_text/_openbook_title_overlap`，读落盘 PDF 含 rejected/）：对 **50 条当前 miss 的 gold** →
  - `doi_in_body` 金判据复现 **44**
  - 仅标题 token 命中 ≥0.5（次级证据）**6**
  - 证据不足/疑 re-假阳 **0** ｜ 无法读取 **0**
  - **金判据复现率 44/50=88%，全部 50 条至少过次级证据，零可疑** → 148 gold **可信**。
- 样例（doi_in_body 强正）：`10.1016/s1872-2067(17)62899-7`(36890 chars) `10.1002/anie.201406637`(19616) `10.1002/aenm.201402093`(46362)。

### 2.2 8 websearch 假阳（源：`_websearch_fp7_hardblack_append_141.csv` ∪ `_mon157_websearch3_hardblack_append.csv`）
- 8 条并集，**当前全 status=success（websearch）**，落盘实为错件 → 应剔：
  - **355744B 同一错 PDF 套 3 DOI**：`10.1016/0021-9517(87)90366-6`、`10.1016/0304-5102(82)85049-9`、`10.1016/j.apcatb.2017.01.076`（Hydrogenation lab safety Fact Sheet）
  - 另 5：`10.1021/acs.iecr.5c03132`(气象图) `10.1016/j.elspec.2006.11.032`(CasaXPS 手册) `10.1016/j.ccr.2019.02.001`(C1 化学书) `10.1021/ie020677q`(配电盘/防灾) `10.1016/j.catcom.2018.07.014`(蓄电池)
- gold ∩ fp = ∅（无交叉误伤）。

---

## 三、干跑结果与阻断根因（**核心**）

**干跑（基线配方 + `--qc-allow …,out/_writeback149_gold59.txt` + `--qc-extra-reject …,out/_writeback149_fp8.txt`，`--no-write`）**：

| | success | miss | rate | allow_override | rejected_total |
|---|---:|---:|---:|---:|---:|
| 基线 | 326 | 673 | 32.63% | 10 | 188 |
| 干跑 +gold59 −fp8 | **324** | 675 | 32.43% | 16 | 190 |
| Δ | **−2** | +2 | | +6 | +2 |

`success_before_qc` 两者同为 514（原始落盘成功集未变）。净 −2 = **−8(剔 fp) + 6(gold 免剔)**。

### 根因（为何 +59 只兑现 6）
1. **9/59 gold 已是 success**（已在基线 allow-11 里）→「+59」**重复计了这 9 条**，真增量 gold ≤ 50。
2. **47/50 增量 gold 的正确 PDF 被物理隔离在 `<batch>/rejected/`**（早前 cleanup 把误判错件移出 `pdfs/`）。`build_coverage` 只从 `<batch>/pdfs/` 认落盘成功 → 这 47 条**不是 coverage 眼里的落盘成功**，`--qc-allow`（只解黑名单、不凭空造成功）**救不回**。
   - gold pdf_used 目录分布：`batch6/rejected`×22、`batch4_p1/rejected`×8、`batch4_p2/rejected`×5、`batch4_p3/rejected`×5、`batch4_p5/rejected`×3、`batch4_p4/rejected`×2、`batch7/rejected`×1、`p3_longtail_160/fetch`×1；仅 3 条(`s1872-2067(17)62899-7`/`anie.201406637`/`aenm.201402093`)在已扫描的 `fetch/pdfs/` 里、可被 allow 直接救回。
3. 故 allow-only 干跑仅 324；−8 fp 生效、+gold 几乎没生效。

---

## 四、诚实可达数字（**368，非 377**）

要兑现 +50 gold，需**一步物理前置**：把 47 份 gold PDF 从 `<batch>/rejected/` **移回 `<batch>/pdfs/`**（各批 metadata.jsonl 里的 pdf_path 本就指向 pdfs/，移回即被认成落盘成功），再 whitelist。之后：

| 步骤 | success |
|---|---:|
| 当前基线 | 326（含 8 假阳、含 9 已翻 gold） |
| −8 假阳 | 318 |
| +50 增量 gold（解隔离 47 + 已可救 3） | **368** |

- **368 / 999 = 36.84%**；success+miss = 368+631 = 999 ✓；**不打穿 326**（只剔 8 条确证假阳 + 增 50 条已复核真件，真成功无净损）。
- 全部 50 条经 build_coverage 回写开卷门(`verify_qc_allow_openbook`)会再自动复验 expected-doi（44 doi_in_body 直过；6 标题项 title≥0.5 亦过/无题保留）→ **368 稳**。
- **377 的差额 9 = 已计成功的 9 条 gold 被重复计**（口径错，建议 headline 用 368）。

---

## 五、请总指挥定夺（need_input · 待 GO）

| 方案 | 做法 | 结果 | -149 建议 |
|---|---|---|---|
| **A（推荐）** | 授权我(或 cleanup 属主)把 47 份已复核 gold PDF `rejected/→pdfs/` 解隔离 → 再 whitelist(allow=allow11∪gold59) + extra-reject(fp8) 真写 | **368 / 36.84%** | ✅ 诚实、证据齐、可逆；唯一动作是移文件(非改黑名单/非下载) |
| B | 只 allow-only 真写（不解隔离） | 324（净 −2，反降） | ❌ 不达标、headline 反而难看 |
| C | 改 `build_coverage`：whitelist 命中项额外去 `<batch>/rejected/` 找 PDF（属主改码 + selftest） | 368（免物理移动，长期更干净） | ○ 更优但需 build_coverage 属主排期 |
| D | 维持现状、暂不写 | 326 | ○ 若认为 368<377 不值当 |

**红线复核**：本波未写 coverage/still_missing/黑名单、未发下载；解隔离(方案A/写盘)**均待你 GO**。备份→写盘的属主动作我会在 GO 后执行（先 `Copy-Item coverage.json coverage.bak_pre_writeback149_<ts>.json`）。

*核验 2026-07-03｜-149｜基线复现 326✓；干跑 allow-only=324；复核 50/50 gold 合法、8/8 fp 确假阳；诚实可达 368（非 377，9 重复计）；阻断=47 gold PDF 在 rejected/。证据：`out/_writeback149_gold59.txt`(59)/`_fp8.txt`(8)/`_recipe.json` + 脚本 `_writeback149_prep.py`/`_diag2.py`/`_verify_gold.py`。*
