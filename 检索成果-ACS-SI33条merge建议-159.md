# 检索成果 · ACS SI 33 条 merge 建议（174 波 · 只读评估）

> 交付：**谷歌学术人机认证-159**（worker）｜2026-07-02  
> **✅ 已执行（2026-07-03 12:50:24）**：merge 已落盘；定版 **326/673/32.63%**。下文保留决策记录（历史定版 340/659/34.03%@00:42:19，非推算 343）。
> 依据：`检索成果-监管者176-ACS-SI假阳复核174波.md`、现盘 `out/coverage.json` / `qc_merge_*`  
> 边界：**只读评估 + 建议**；**未改**黑名单 / coverage / 任何 `.py`；merge 执行属 **-151**

---

## 一、一句话结论

**建议并入 `qc_merge_union_wrong.csv`（soft 软黑），33 条全部 batch6、`overlap=∅`（与 websearch −9、现有 hard/union 均无交集）。**

**执行顺序（硬约束）**：须先完成 **-151 websearch −9 落盘**（385→376），再并 SI 33 条 → **376→343**。若跳过 Step 1 直接并 SI，则为 **385→352**。

**拍板建议：✅ 同意 merge**（Tier-A 自动扣减；DOUBT 9 条不在此批、不误杀）。

---

## 二、前置条件核验（-151 websearch −9）

| 检查项 | 现盘状态 | 判定 |
|---|---|---|
| `out/_mon176_websearch9_hardblack_append.csv` | ✅ 存在（9 行） | 交接包就绪 |
| 9 条是否已在 `qc_merge_highconf_wrong.csv` | **0/9** | ⏳ **尚未 merge** |
| `coverage.json` success | **385**（`generated_ts` 22:42:59） | 与 −9 待并口径一致 |
| SI 33 与 ws9 交集 | **0** | 可叠加 |

**结论**：本建议**不替代** −9 落盘；属主应先执行 176 移交 §三 Step 1–2，再执行本表 Step 2。

---

## 三、SI 33 条 merge 建议（Tier-A）

### 3.1 清单与现态

| 指标 | 值 |
|---|---|
| 来源清单 | `out/_mon176_acs_si_still_success.txt` |
| 条数 | **33** |
| 分类 | 全部 **SI_COVER**（`_batch6_acs_si_scan_145.py`） |
| source 特征 | `publisher_oa:acs-authorchoice` |
| batch | **batch6 ×33**（无其它 batch） |
| 现 coverage 态 | **33/33 仍 `status=success`** |
| 现 qc 态 | **33/33 `qc=null`**（未进任何黑名单） |
| 与 `qc_merge_highconf_wrong.csv` 交集 | **0** |
| 与 `qc_merge_union_wrong.csv` 交集 | **0** |
| 与 `qc_allow` / allow_override 交集 | **0** |

### 3.2 并入目标：**union 软黑（推荐）**

| 方案 | 目标文件 | 理由 |
|---|---|---|
| **✅ 推荐** | `out/qc_merge_union_wrong.csv` | 176 Tier-A 首选；SI-only 属内容 QC / 开卷 SI_COVER 判定，非「两法都错」高置信 hard；与 -149 中 `energyfuels.5c06101` 走 soft 一致 |
| 备选 | `out/qc_merge_highconf_wrong.csv` | 若总指挥要求 SI 与 websearch 9 条同级 hard 处置；**功能上等价下修 success**，但 `rejected_hard` 计数不同 |

**不推荐**只写 manifest 不更 CSV：`build_coverage` 权威消费 `qc_merge_*`，manifest 为冗余印证。

### 3.3 建议 append 行格式

与现有 union CSV 同 schema（`batch,doi,verdict_151,title_score,url_wrong,pdf_url,pdf_actual,pdf_path`）：

- `batch` = `batch6`
- `doi` = 清单 33 条（见 §五）
- `verdict_151` = `si_cover`（或 `mismatch`，与审计脚本口径对齐即可）
- `title_score` = 空或 `0.0`
- `url_wrong` = `False`（非 URL 冲突，是 SI 内容）
- `pdf_actual` = `ACS authorchoice SI cover (SI_COVER, mon176)`
- `pdf_path` = `out/batch6/pdfs/<doi_sanitized>.pdf`（可从 metadata 回填）

属主可让 -151 用脚本从 `out/batch6/metadata.jsonl` 批量生成 append CSV，文件名建议：`out/_mon176_acs_si33_union_append.csv`。

---

## 四、预期 `build_coverage` 下修（供总指挥拍板）

基线：`coverage.json` **385 / 999 / 614**（22:42:59）。

| 阶段 | 动作 | success | miss | rejected 变化 |
|---|---|---:|---:|---|
| 现值 | — | **385** | 614 | hard 6 + soft 122 = 128 |
| **Step 1** | 并 websearch −9 → hard | **376** | 623 | rejected_hard **+9** → 15 |
| **Step 2** | 并 SI 33 → union | **343** | 656 | rejected_soft **+33** → 155 |
| **合计** | −9 + −33 | **−42** | **+42** | rejected_total **128→178** |

**success_rate**：385→343 时 **0.3854 → 0.3433（34.33%）**。

**未计入（DOUBT 桶）**：176 §2.3 另 **9 条 DOUBT**（8 条仍 success）——**本 merge 不含**；若后续开卷终裁为 SI，还可再下修最多 **8**（理论下限 **343→335**，不含 Tier-C 保留的 1 条 ARTICLE `nl200722z`）。

**batch6 局部**：现 disk success 247；33 条全在 batch6 且仍计全局 success → merge 后 batch6 在 coverage 净成功中减 33（PDF 仍在盘，仅 QC 改判 miss）。

---

## 五、33 条 DOI 全表

```
10.1021/acs.jpclett.0c01038
10.1021/acscatal.6c00142
10.1021/acs.iecr.3c04537
10.1021/acssuschemeng.1c07897
10.1021/acscatal.5c01375
10.1021/acscatal.7b03251
10.1021/acsami.1c06979
10.1021/acscatal.6c00590
10.1021/acsami.7b04432
10.1021/acscatal.1c05994
10.1021/acscatal.8b00294
10.1021/ef060389x
10.1021/acs.jpclett.1c03342
10.1021/acsami.3c03256
10.1021/acscatal.0c03324
10.1021/ja504753g
10.1021/es802853g
10.1021/acsaem.8b00798
10.1021/acscatal.5c09278
10.1021/acscatal.2c02535
10.1021/ja00136a029
10.1021/acsami.2c09347
10.1021/acs.jpcc.9b08359
10.1021/acscatal.1c00747
10.1021/jacs.7b00058
10.1021/acscatal.5c01699
10.1021/acsami.2c01959
10.1021/acscatal.2c00671
10.1021/acs.jpcc.9b04122
10.1021/acs.iecr.5c05325
10.1021/acs.jpcc.5c03318
10.1021/jacs.3c13355
10.1021/jacs.8b12763
```

---

## 六、属主执行清单（-151 · 本文不执行）

```powershell
Set-Location "e:\AI项目\谷歌学术人机认证"

# Step 1 · websearch −9（须先于 SI 33）
# 追加 out/_mon176_websearch9_hardblack_append.csv → out/qc_merge_highconf_wrong.csv
python tools/build_coverage.py
# 预期 success 385 → 376

# Step 2 · SI 33（生成 append CSV 后）
# 追加 out/_mon176_acs_si33_union_append.csv → out/qc_merge_union_wrong.csv
python tools/build_coverage.py
# 预期 success 376 → 343

# Step 3 · 文档
# 更新《基线口径冻结说明-388-173.md》§三 −9 与 SI33 行状态 + 新 generated_ts
```

---

## 七、风险与护栏

1. **不误杀 DOUBT 9**：本批仅 Tier-A 33 条；DOUBT 须人工开卷后再议（176 §2.3）。
2. **保留 1 条 ARTICLE**：`10.1021/nl200722z` 不在 33 清单内，维持 success。
3. **recover_b4_cf 5 条 SI**：已是 miss，无需 merge。
4. **生产 SI 门**：merge 只修 coverage 诚实度；长期仍须 -145 §三 硬化 SI 门 + acs-authorchoice 源降级（176 §四）。

---

*159｜2026-07-02｜只读评估；未改盘/黑名单/代码。建议：先 −9 落盘，再 union 并 33 条 → success 343。*
