# coverage 口径重算规范与本波 churn 复盘

> 交付：**谷歌学术人机认证-174**（亲历抢写 churn，总指挥派 task-0727c2ea）｜2026-07-03  
> 边界：**只产本 1 份运维追踪文档**；**未再跑** `build_coverage --write`；coverage 定版权已移交 **-155**。

---

## 一、本波 churn 时间线（证据）

| 时间戳 | success | miss | allow_override | before_qc | 触发 | 定性 |
|---|---:|---:|---:|---:|---|---|
| 22:42:59 | **385** | 614 | **10** | **513** | -151 ACS SI−3 权威落盘 | ✅ **干净基线**（`coverage.bak_174_pre_websearch9_merge.json`） |
| 23:59:39 | 362 | 637 | **0** | 471 | 174 **漏传** `--qc-allow` + `--extra-dirs` | ❌ 回归态 |
| 00:02:50 | 368 | 631 | 0 | — | 174 仅 append websearch9 + 仍漏参 | ❌ |
| 00:05:16 | 368 | 631 | 0 | — | 同上 | ❌ |
| 00:10:44 | 380 | 619 | 12 | 517 | 174 补参但 **allow 组成有误**（含已驳回 1.5053761 路径；缺 acscatal.0c04429、SciOpen） | ⚠️ 部分修复 |
| 00:12+ | 343 | 656 | 12 | 517 | 174 第二波 merge（SI33+openaire3+crossref1） | ⚠️ 扣减方向对、基线/allow 仍错 |
| 重置 | **385** | 614 | 10 | 513 | 总指挥/-155 重置 bak_174 | ✅ 回干净基线 |
| 待定 | ~343 | ~656 | **14** | ~513 | **仅 -155** 权威一次写盘 | ⏳ 定版中 |

**根因摘要**

1. **漏参回归**：未传 `--qc-allow` → `allow_override` 从 10 **掉到 0**（MDPI7、T0+2、真正文 acscatal 等全被黑名单误剔）；未传 `--extra-dirs` → `success_before_qc` **513→471**（二级 rerun 目录漏扫）。
2. **多人抢写**：174 与 155 并行 `--write`，三次覆盖 `coverage.json`，组成漂移。
3. **allow 清单污染**：混用 4 份 qc-allow 未排除 **已驳回 `10.1116/1.5053761`**（AIP 用户手册）；未纳入 **`acscatal.0c04429`**（-149 保留唯一 ACS 真正文）与 **SciOpen `10.26599/nr.2025.94907426`**（-160 开卷翻案）。

---

## 二、权威正确 recipe（给 -155 / 运维）

### 2.1 扫描集（复现 before_qc≈513）

**一级目录**（`list_batch_dirs` 默认全收）：`batch6`、`batch7`、`batch4_p1`…`p5`、`routeB_mdpi`、`recover_*`、`title_probe` 等——**勿**在 merge 波次随意纳入在途实验目录（如 `p2_cf_soft_155`）除非总指挥明示。

**必须 `--extra-dirs`（11 路径，与 22:42:59 快照一致）**：

```
rerun_cf_savable_140/aip/fetch,
rerun_cf_savable_140/wiley/fetch,
rerun_cf_savable_141/aip/fetch,
rerun_cf_savable_140/acs/fetch,
rerun_cf_savable_140/cf_other/fetch,
rerun_acs_144/fetch,
rerun_wiley_144/fetch,
rerun_aip_144/fetch,
rerun_elsevier_143/fetch,
t0_recover_156/fetch,
routeB_rsc_launch/fetch
```

> -155 试算脚本 `_tmp_repro385_155.py` 用较短 3 目录集复现 **385 附近**；全量 11 目录与 22:42:59 快照对齐。

### 2.2 allow_override=14 组成（精确配方）

| 来源文件 | 条数 | 说明 |
|---|---:|---|
| `out/routeB_mdpi_qcallow_151.txt` | 7 | MDPI7 route-B 真全文 |
| `out/_t0_adjudicate147_qcallow_final.txt` | 3 | T0 终裁采纳（**不含** 1.5053761） |
| `out/_t0_recover156_writeback_qcallow_immediate2_151.txt` | 2 | T0 立即档 +2 |
| `out/rerun_acs_144_whitelist_back_145.txt` | 1 有效 | **仅 `acscatal.0c04429`**；另 3 条已证 SI-only（-149）**不得**入 allow |
| `out/_sciopen_allow_160.txt` | 1 | `10.26599/nr.2025.94907426` SciOpen 翻案 |

**必须排除（-149 SI-only，已从 allow 移除）**：`energyfuels.5c06101`、`langmuir.7b03998`、`ja509214d`。

**必须排除（-147 终裁驳回）**：`10.1116/1.5053761`。

### 2.3 其它 QC 参数

```powershell
--qc-extra-reject out/rerun_acs_144_deduct_dois_145.txt
```

**wave2 黑名单（已 append，写盘前勿重复 append）**：

| 目标 | 文件 | 条数 |
|---|---|---:|
| hardblack | `out/_mon176_websearch9_hardblack_append.csv` | 9 |
| hardblack | `out/_mon176_openaire3_hardblack_append.csv` | 3 |
| hardblack | crossref `10.1252/jcej.38.807` | 1 |
| union soft | `out/_acs_si33_union_append_145.csv` | 33 |
| **HOLD** | `out/_mon176_ocr_bucket_still_success.txt` | 14（不可验证，勿 auto merge） |

### 2.4 推荐命令模板

**阶段 A — 基线复现（仅 -155，`--no-write`）**：

```powershell
python tools/build_coverage.py --out-root out --no-write --print-json `
  --extra-dirs "rerun_cf_savable_140/aip/fetch,...,routeB_rsc_launch/fetch" `
  --qc-allow "out/routeB_mdpi_qcallow_151.txt,out/_t0_adjudicate147_qcallow_final.txt,out/_t0_recover156_writeback_qcallow_immediate2_151.txt,out/rerun_acs_144_whitelist_back_145.txt,out/_sciopen_allow_160.txt" `
  --qc-extra-reject out/rerun_acs_144_deduct_dois_145.txt `
  --qc-hard out/_qc_hard_baseline_staging_155.csv `
  --qc-soft out/_qc_soft_baseline_staging_155.csv
```

验收：`allow_override≈10~14`（staging 未含 wave merge 时≈10；全量 merge 后≈14）、`success_before_qc≈513`、`success≈385`。

**阶段 B — wave1 websearch−9**：staging hard 并入 9 条 → 预期 **385→376**。

**阶段 C — wave2 Tier-A**：union +33、hard +3+1 → 预期 **376→~340**（SciOpen +1 等微调见总指挥链）。

**阶段 D — 唯一一次 `--write`**（备份后）。

---

## 三、运维规范（防再犯）

### 3.1 单写者制

- **`out/coverage.json` 每波仅 1 人写盘**（本波：**-155**）；其他人只产黑名单 CSV / qc-allow 清单 / `--no-write` 试算。
- 委派任务必须标注「只读试算」或「唯一写盘权」。

### 3.2 写盘前三步

1. **`--no-write --print-json`** 试算，核对 `allow_override` **组成**（逐 DOI 清单，非只看总数）、`success_before_qc`、`rejected_hard/soft`。
2. **`Copy-Item out/coverage.json out/coverage.bak_<who>_<reason>.json`**
3. **一次 `--write`**；写后立即 `generated_ts` + summary ping 总指挥 → 143/154 定稿。

### 3.3 防回归 check 清单

- [ ] 是否传 **`--qc-allow`**？（漏传 → allow 掉 0，最严重）
- [ ] 是否传 **完整 `--extra-dirs`**？（漏传 → before_qc 漂移）
- [ ] allow 是否 **排除 1.5053761** 与 **-149 三条 SI**？
- [ ] 是否 **纳入 acscatal.0c04429 + SciOpen**？
- [ ] 是否 **未纳入在途实验 batch**（p2_cf_soft 等）除非明示？
- [ ] 是否 **`--no-write` 先达标**？
- [ ] 是否 **仅一人 write**？
- [ ] wave2 是否 **勿误杀 nl200722z**（不在 SI33 33 条内）？

### 3.4 备份命名

`out/coverage.bak_<session>_<event>.json` — 本波已有：

- `coverage.bak_174_pre_websearch9_merge.json`（385 干净基线）
- `coverage.bak_174_pre_wave2_merge.json`（380 误态）

---

## 四、174 侧交底

- 已 **硬停** 一切 `build_coverage --write`；coverage 定版权交 **-155**。
- 已将完整 CLI 历史发 **-155**（session 尾号 `9b991b1b`）与总指挥 **-141**。
- **OpenAlex**：首 key 已 `setx OPENALEX_KEY` 冒烟 OK；`run_all.py` 不传 key 的 P0 缺口由总指挥另派。

---

*核验 2026-07-03｜174｜task-0727c2ea｜只产文档，未写 coverage。*
