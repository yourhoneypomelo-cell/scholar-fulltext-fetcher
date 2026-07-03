# 第二波 merge 清单 · 155 备料（只读·不落盘）

> 交付：**谷歌学术人机认证-155**（worker）｜任务：`task-6602fcf6-0eef-4ef1-a172-79861b042ef4`｜2026-07-02 24:00  
> 背景：免费回收到顶；**−151 现 offline**，本清单供其上线后**一次** `build_coverage` 重算。  
> 边界：**只读核对 + 只新建本 md + 机器可读 JSON**；**未改** coverage / 黑名单 / `build_coverage`、**未 merge**。  
> 机器可读：`out/_merge_wave2_manifest_155.json`（完整 live 交叉）+ `out/_merge_wave2_manifest_155_compact.json`（摘要）。

---

## 〇、TL;DR（给 −151 一键开工）

| 项 | 值 |
|---|---|
| **live 基线**（投影起点） | **362 / 999 = 36.24%**，miss **637**（`generated_ts` **23:59:39**） |
| 任务背景基线（22:42:59） | 385 / 38.54% / miss 614（**已漂移 −23**，见 §一） |
| **Tier-A 仍虚高**（merge 后还会扣 success） | **37 条**（websearch9 **0** + ACS SI **33** + openaire3 **3** + crossref1 **1**） |
| **Tier-A 投影** | success **325**，miss **674**，净覆盖 **32.53%**（**−3.71pp**） |
| **Tier-B HOLD** | OCR14 **14** 条（不可验证，非实锤错文） |
| 四组 auto 清单 **overlap** | **∅**（两两无交集） |
| 推荐顺序 | websearch9（若仍有 inflated）→ **acs_si33** → openaire3+crossref1 → HOLD ocr14 |

---

## 一、live 基线漂移说明（必读）

| 快照 | success | miss | 备注 |
|---|---:|---:|---|
| 22:42:59（任务背景 / −149 −3 已落） | 385 | 614 | 174 波 ROI/审计引用口径 |
| **23:59:39（live 投影起点）** | **362** | **637** | 中间 **−23 success / +23 miss** 已发生（非本清单 merge） |
| Tier-A merge 后（投影） | **325** | **674** | 仅计 **仍 status=success** 的 37 条 |

> **−151 开工时**：以 **`out/coverage.json` 最新 `generated_ts`** 为起点；若仍 362/637，则 Tier-A 投影 **325/674** 成立。若其间又有回写，重跑 `_tmp_merge_wave2_155.py` 或读 JSON 刷新 `still_inflated` 计数。

---

## 二、增量文件齐备性核对

| # | 组 | 文件 | 期望 | 实测 | 格式 | merge 目标 | live 仍 success |
|:-:|---|---|:---:|:---:|:---:|---|:---:|
| 1 | **websearch −9** | `out/_mon176_websearch9_hardblack_append.csv` | 9 | **9** ✅ | csv 8 列 batch,doi,verdict_151,… | hardblack append | **0/9**（已全部 miss） |
| 2 | **ACS SI 33** | `out/_acs_si33_union_append_145.csv` | 33 | **33** ✅ | 8 列 **与 `qc_merge_union_wrong.csv` 表头一致** ✅ | union soft append | **33/33** ⚠️ |
| 3 | **openaire 3** | `out/_mon176_openaire3_hardblack_append.csv` | 3 | **3** ✅ | csv 8 列 | hardblack append | **3/3** ⚠️ |
| 4 | **OCR 14** | `out/_mon176_ocr_bucket_still_success.txt` | 14 | **14** ✅ | txt 每行 DOI + `# count=14` 头 | **HOLD** | **14/14**（HOLD） |
| 4b | OCR retry 日志 | `out/_mon176_ocr_bucket_retry.txt` | — | ✅ 存在 | 14 条 retry 均 alnum≈0 / 1 加密 | 佐证 HOLD | — |
| 5 | **次级 crossref 1** | 源：`out/_mon176_secondary_openbook_scan.csv` | 1 | **1** ✅ | SUSPECT 共 48；实锤 **10.1252/jcej.38.807** | hardblack append | **1/1** ⚠️ |

**交叉清单**：`out/_mon176_acs_si_still_success.txt` **33 DOI** 与 `_acs_si33_union_append_145.csv` **集合相等** ✅。

---

## 三、live 交叉要点（仍虚高 = merge 还会扣 success）

### 3.1 websearch9 — **已无增量扣减**

9 条在 live coverage **均已 status=miss**（可能已被其他路径/QC 改判）。**append 仍应并入黑名单**以固化审计，但 **对 success 计数增量扣减 = 0**。

### 3.2 ACS SI 33 — **最大仍虚高池**

**33/33 仍 success**，source 多为 `publisher_oa:acs-authorchoice`（SI 封面顶包，−176 Tier-A 铁证）。merge 后预期 **−33**。

### 3.3 openaire3 — **3/3 仍 success**

邻居顶包错 PDF（纤维素/ thesis 等，−176 实锤）。merge 后 **−3**。

### 3.4 crossref1 — **1/1 仍 success**

`10.1252/jcej.38.807` = Browse 帮助页（508 chars）。merge 后 **−1**。

### 3.5 OCR14 — **HOLD，勿自动扣**

14/14 仍 success，但 retry 显示 **扫描件/加密/alnum=0**，属「无法验证」非错文实锤；**不建议第二波 auto merge**（−176 §二）。

---

## 四、overlap 矩阵

| 对 | 交集 |
|---|---|
| websearch9 ∩ acs33 | **∅** |
| websearch9 ∩ openaire3 | **∅** |
| websearch9 ∩ crossref1 | **∅** |
| acs33 ∩ openaire3 | **∅** |
| acs33 ∩ crossref1 | **∅** |
| openaire3 ∩ crossref1 | **∅** |
| Tier-A ∪ Tier-B（ocr14） | **∅** |

**去重后 Tier-A 仍虚高总数 N = 37**（非文件行数 50；websearch9 已不 inflated）。

---

## 五、投影净覆盖（从 live 362 起算）

| 阶段 | success | miss | 净覆盖率 | Δsuccess |
|---|---:|---:|---:|---|
| live 现值（23:59:39） | 362 | 637 | **36.24%** | — |
| **+ Tier-A merge（37 条仍 success）** | **325** | **674** | **32.53%** | **−37** |
| 若再 HOLD 扣 OCR14（14，不推荐 auto） | 311 | 688 | 31.13% | −51 |

> 与 −145 文档「385→~343（−42）」对照：live 已先到 **362**（中间 −23 未在本清单）；再扣 Tier-A **37** → **325**，诚实地板比 22:42 口径 **低 60 条 / −6.0pp**。

---

## 六、推荐 merge 顺序（−151 执行 SOP）

1. **备份**：`coverage.json` + `qc_merge_union_wrong.csv` + hardblack 相关 CSV。  
2. **websearch9 append** → 若仍有 inflated 则 `build_coverage`；**现 live 0 inflated，可只补黑名单**。  
3. **acs_si33** → append `qc_merge_union_wrong.csv`（soft）→ **`build_coverage`（预期 −33）**。  
4. **openaire3 + crossref1** → append hardblack → **`build_coverage`（预期再 −4）**。  
5. **校验**：success ≈ **325**，miss ≈ **674**，`generated_ts` 更新；同步《基线口径冻结说明-388-173.md》。  
6. **HOLD ocr14**：另排 OCR/人核，**勿与本波 auto 混跑**。

**避撞**：coverage 口径属 **−151**；本窗口（−155）**只备料不落盘**。

---

## 七、来源

- live 交叉脚本：`_tmp_merge_wave2_155.py`（只读，可删）→ `out/_merge_wave2_manifest_155.json`  
- 参照：《数据卫生核对-145-ACS_SI假阳未落地缺口与三任务vs174波交叉核对.md》《检索成果-监管者176-开卷扩扫总汇总-HOLD待merge.md》《基线口径冻结说明-388-173.md》  
- 权威：`out/coverage.json`（23:59:39）、`out/qc_merge_union_wrong.csv`

---
*核验 2026-07-02 24:00｜-155｜task-6602fcf6｜只读备料｜Tier-A 仍虚高 37 条→投影 325/674/32.53%；websearch9 已无增量；acs33+openaire3+crossref1 待 merge；ocr14 HOLD 14 条。*
