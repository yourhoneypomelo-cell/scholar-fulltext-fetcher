# 数据卫生核对 · 145 · ACS SI 假阳未落地缺口 + 三任务 vs 174 波交叉核对（独立复核，不重画已存交付）

> 交付：**谷歌学术人机认证-145**（信息检索-智库专家）｜2026-07-02 ｜承用户「直接开工」三任务（① ACS SI 假阳复核+重分类 ② still_missing 分桶+ROI ③ 工作树三分类收口）。
> **落地即发现**：三任务均已被并发的 **174/176 波**产出对应交付（-176 / -155 / -159）。故本文**不重画那三份**，只做 **独立复核交叉核对（3/3 一致）+ 一处对我方旧清单的纠偏 + 唯一未落地缺口的合并结论 + 可重跑校验工具**。
> **边界**：纯读盘 `out/coverage.json`（`generated_ts=2026-07-02 22:42:59`）+ 新建本 1 份 md + 1 只读校验脚本 `_qc_reverify_acs_si_145.py`。**未改任何 .py/coverage/黑名单/PDF、未提交 git**；未碰 Wiley/AIP CF-soft（-149 域）、route-B（-141 域）、154 sweep（-154 域）。

---

## 〇、一句话

三任务的 174/176 波交付**独立复核 3/3 一致**；**唯一仍开口的实事** = 权威 `coverage.json`（385/999=38.54%，22:42:59）**至今仍虚高**：batch6 ACS `acs-authorchoice` SI 铁证 **33** + -169 websearch 假阳 **9**（overlap=∅）**均未落盘**，`extra_reject` 现只消费了 `rerun_acs_144_deduct_dois_145.txt`（52，已核实全部转 miss ✓）。**建议 -151 一次重算并入这两组 → 385 → ~343（34.33%，−4.2pp）**；另 7 条 DOUBT 待开卷。**⚠️ 纠偏：不要整份吞我方旧清单 `batch6_acs_si_reject_145.txt`(41)**——它比 -176 的 33 多含 7 DOUBT + **1 条真正文 `nl200722z`（误列）**，正确自动扣减名单应用 -176 的 `_mon176_acs_si_still_success.txt`(33)。

---

## 一、三任务 vs 174/176 波 — 独立复核交叉核对（3/3 一致）

| 我方任务 | 174/176 波已有交付 | 我方独立复核方法 | 结论 |
|---|---|---|:--:|
| ① ACS SI 假阳复核+重分类 | 《检索成果-监管者176-ACS-SI假阳复核174波.md》(-176) | 重跑 `_batch6_acs_si_scan_145.py`（读盘真 PDF）+ 新写 `_qc_reverify_acs_si_145.py` 对 live coverage 交叉 | **一致**（见 §二，并纠偏 1 条） |
| ② still_missing 分桶 + ROI | 《检索成果-still_missing分桶统计刷新与下一波ROI-174.md》(-155) | 独立重算 `coverage.json` miss=614 机制六桶 | **逐格一致**（见 §三） |
| ③ 工作树命名审计 + 三分类收口 | 《工作树三分类收口清单-174.md》(-159) | 独立 `git status` 盘点分类 | **一致**（见 §四） |

---

## 二、任务① 复核：batch6 SI 假阳仍虚高 coverage（含对我方旧清单的纠偏）

**真 PDF 重扫（`_batch6_acs_si_scan_145.py`）**：batch6 acs-authorchoice success=52 → **SI_COVER 42 / DOUBT 9 / ARTICLE 1**；recover_b4_cf 5 全 SI_COVER（**均已是 miss**，不虚高）——与 -176 表一致。

**对 live `coverage.json`(22:42:59) 交叉（`_qc_reverify_acs_si_145.py`）**：

| 复验项 | 结果 | 判定 |
|---|---|:--:|
| `batch6_acs_si_reject_145.txt`(41) 当前状态 | **41/41 仍 status=success**（无一进黑名单） | ⚠️ 仍虚高 |
| `rerun_acs_144_deduct_dois_145.txt`(52) 当前状态 | **52/52 已 miss**（`extra_reject` 已消费） | ✅ 已落 |
| 「真正文4」复验（-149 主张下修为1） | `acscatal.0c04429`=success+allow；`ja509214d`/`energyfuels.5c06101`/`langmuir.7b03998`=miss | ✅ -149 −3 已落 |

**⚠️ 纠偏（我方旧清单 41 vs -176 的 33，逐条对账）**：`集合(41) ⊇ 集合(33)`，交集=33、`MON176−MINE=0`；**多出的 8 条 = 7 DOUBT + 1 条 `nl200722z`**。其中 `nl200722z` 在我方 -145 清单里被标 SI，但 **-176 稳健判定器 + 本次真 PDF 重扫均判 ARTICLE（真正文）**。→ **自动扣减务必用 -176 的 `_mon176_acs_si_still_success.txt`(33)，勿整份吞 41**（否则误杀 1 真正文 + 混入 7 条未裁 DOUBT）。

**分层处置（与 -176 Tier 对齐）**：
- **Tier-A 可自动扣（33 铁证 SI_COVER）** → 并入 `qc_merge_union_wrong.csv`（soft）交 -151 重算。
- **Tier-B 开卷终裁（7 DOUBT）**：`acssuschemeng.6b00644 / acscatal.7b01827 / acscatal.8b04720 / acs.jpcc.6b07849 / acscatal.4c07622 / jp807906e / acscatal.8b00216`（首页多含 S1/S-1 信号，倾向 SI）。
- **Tier-C 保留（1 真正文）**：`nl200722z`（勿扣）。

---

## 三、任务② 复核：still_missing 614 机制六桶（逐格一致）

独立重算 `coverage.json` status≠success 的 614 条，按 DOI 前缀映射互斥机制桶：

| 机制桶 | 我方独立重算 | -155/-174 doc | 一致 |
|---|:--:|:--:|:--:|
| CF-hard（RSC JA3, 10.1039） | 67 | 67 | ✅ |
| CF-soft（ACS 94/Wiley 21/AIP 3/T&F 3…） | 123 | 123 | ✅ |
| 403 IP/登录（Elsevier 10.1016/10.1006） | 373 | 373 | ✅ |
| Springer 订阅 no-pdf（10.1007/10.1023/10.1134） | 23 | 23 | ✅ |
| OA 真免费（MDPI 10.3390） | **0** | 0 | ✅ |
| 其它长尾 | 28 | 28 | ✅ |
| **求和** | **614** | 614 | ✅ |

- **vs 611（-149）漂移 +3 全落在 ACS**（91→94），成因 = -149 把 3 条 ACS SI-only 从 allow 改判 miss；**ROI 排序与墙型判断不漂**（免费天花板 ~40~42%、主体 ~490~585 唯 A5）。
- **诚实地板提醒**：现值 385 尚含未落地假阳；扣掉本文 §二 的 SI 33 + -169 websearch 9 后，**真实地板 ≈ 343（34.33%）**，miss ≈ 656；分桶结构不变、仅分母下修。

---

## 四、任务③ 复核：工作树三分类（一致）

独立 `git status --porcelain` 盘点，与 -159/-174 口径一致：

| 档 | 我方盘点 | -159/-174 | 处置口径（沿用 152/173） |
|---|:--:|:--:|---|
| A 可提交代码（tracked `M` .py） | 6（cli/download/render_fetch/publisher_direct/publisher_oa/build_coverage） | 6 | 自测绿随 checkpoint 入库，与 -144/-151 对齐 |
| B 正式文档（.md） | tracked 34 + untracked ~12+ | ≈41 | 全保留入仓 |
| C 临时探针/数据（untracked `_*.py`/数据件） | `_*.py` ~90 + 数据件 ~18 | 87 py + 28 数据 | 按 152/173/174 三表合并归档/清库 |

- **本文新增 2 件按 C 档处置**：`_qc_reverify_acs_si_145.py`（**归档**：SI 假阳 live 交叉校验工具，可重跑、结论已入本文）、`数据卫生核对-145-…md`（**B 档保留**）。
- **命名审计**（-159 已跑）：`out/*/pdfs/` 契约目录 544/544 硬合规 100%，零覆盖风险；本文无新增命名问题。

---

## 五、唯一未落地缺口（合并结论 · 交 -151/-169/总指挥）

| # | 缺口 | 现态 | 建议动作 | 落定后 |
|:--:|---|---|---|---|
| 1 | batch6 ACS SI 铁证 33 仍计 success | 未入黑名单（41/41 success 实测） | -151 并入 `_mon176_acs_si_still_success.txt`(33) 重算 | 385 → 352 |
| 2 | -169 websearch 假阳 9 仍计 success | 未落盘（overlap 与①=∅） | -169 单独重跑 `build_coverage` | 叠加 → 343 |
| 3 | 7 条 DOUBT 待开卷 | success，未裁 | 开卷终裁后再定扣/留 | 343 → ~336~343 |
| — | `nl200722z`（真正文） | success（正确） | **保留、勿扣** | — |

**合并净预测**：385（现）→ **343（34.33%，−4.2pp）**（并 33 SI + 9 websearch）→ DOUBT 裁后至多再 −7 ≈ 336。**免费天花板结论不变（~40~42%，破此唯 A5）**。

---

## 六、证据与工具

- Live 交叉校验：`_qc_reverify_acs_si_145.py`（纯读 `out/coverage.json` × `batch6_acs_si_reject_145.txt`/`rerun_acs_144_deduct_dois_145.txt`，幂等可重跑；-151 落盘前后可用它验证）。
- 真 PDF 重扫：`_batch6_acs_si_scan_145.py`（复用生产门重分类）。
- 已存交付（本文所校对象）：`检索成果-监管者176-ACS-SI假阳复核174波.md`、`检索成果-still_missing分桶统计刷新与下一波ROI-174.md`、`工作树三分类收口清单-174.md`、`基线口径冻结说明-388-173.md`。
- 安全扣减名单：`out/_mon176_acs_si_still_success.txt`(33)（**优先于**我方旧 `out/batch6_acs_si_reject_145.txt`(41)）。

---

## 七、落地交接（承总指挥 144 拍板 · 2026-07-02）

144 拍板：**我不直接改 coverage/黑名单**（口径归 -151 一次权威重算）；**只产出增量文件**，等 websearch −9（task-02bdd988）落盘稳定后，由 144 统一定序排 -151 第二波 merge（33 + openaire3 + OCR14）。已据此产出：

| 产物 | 内容 | 处置 |
|---|---|---|
| `out/_acs_si33_union_append_145.csv` | 33 铁证 ACS SI（8 列对齐 `qc_merge_union_wrong.csv`：`batch,doi,verdict_151(non-article-si),title_score,url_wrong=False,pdf_url,pdf_actual,pdf_path`；已核 33/33 仍 success） | **交 -151 第二波 merge（待 144 定序）**，勿自行 merge |
| `out/_acs_si_doubt_appendix_145.csv` | 8 条 DOUBT-success（7 在我方41 + 1 mon176独有 energyfuels.5c05523）+ 首页信号 | **不入硬黑**，供 -176 开卷终裁 |
| `_gen_acs_si_union_append_145.py` | 上两文件的幂等生成器（纯读） | 归档 |

- **勿扣清单**：`nl200722z`（真正文，已排除）；`energyfuels.5c06101`（已 miss，不重复列）。
- **DOUBT 处置**：7~8 条暂 hold，-176 开卷后再定扣/留（至多再 −7 success）。

---

*核验 2026-07-02 ｜ -145 ｜ 纯读 + 新建本 md + 只读校验/生成脚本 + 2 增量数据件；未改码/coverage/黑名单/PDF/git、未自行 merge；未碰 Wiley/AIP·route-B·154 域。三任务 vs 174/176 波独立复核 3/3 一致；纠偏 1 条（nl200722z 真正文误列）；唯一未落地缺口 = SI 33 + websearch 9 未并入 coverage（→343）；承 144 拍板已产 union 增量 CSV(33) + DOUBT 附录(8)，待 -151 定序 merge。*
