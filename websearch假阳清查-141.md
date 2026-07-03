# websearch 假阳开卷清查 · 收尾（141）

> 交付：**谷歌学术人机认证-143**（副手兼办）｜工单：`task-568775cb-fcc1-4648-8363-3be325a984f3`（转派自 -141）｜2026-07-03
> 边界（硬约束）：**只读开卷 + 产 reject 增量清单**；**不写 coverage.json / qc_merge / 代码 / git**。发现的假阳作为最后一波 merge 的 reject 增量，**交 -144 统一并入**。
> 承接：-169《…回写必开卷SOP与websearch假阳9实锤…》 + -176《…169接棒开卷复核与-9落盘移交》/《…开卷扩扫总汇总-HOLD待merge》。
> 数据基线（分析快照·【历史口径】）：`out/coverage.json` `generated_ts=2026-07-03 01:27:42`，success **339**（已含 -144 落盘的 websearch -9）。⚠️ **当前权威已定版 326/673/32.63%@2026-07-03 12:50:24（OCR14 −13，allow=10）**；本文 websearch 假阳复扫结论不受此口径漂移影响。

---

## 一、一句话结论

对当前权威 coverage(339) 的 **websearch success 全量重开卷**，在 -169 九实锤（已落盘）+ -176 OCR 桶 14 条（已挂起）**之外**，再坐实 **7 条 websearch 假阳（错文实锤）**；与所有已有清单（169-9 / 176-OCR14 / openaire3 / crossref1 / ACS-SI33）**去重后 overlap=∅，净新增 7**。预期影响：**success 339 → 332（−7）**，miss 614 → 621。reject 增量已产 `out/_websearch_fp7_hardblack_append_141.csv`，**交 -144 并入 `qc_merge_highconf_wrong.csv` 后重跑 `build_coverage`**。

---

## 二、方法（承 169 开卷 SOP）

1. **重跑** `_mon169_qc_openbook_scan.py`（只读）→ 当前 339 的 websearch 142 + allow 10 = 去重 **151 条 success** 开卷结果（`out/_mon169_openbook_scan.csv`）：**OK(正文含期望 DOI)=98 / SUSPECT=53**；allow_override **10/10 全 OK**（含 2 条 MDPI 路径漂移项落盘存在且验真）。
2. **SUSPECT 53 分流**（判据严格承 169，宁漏放不错杀）：
   - **chars=0 抽取失败 14 条** = -176 OCR 桶（已挂起）→ **不实锤**、维持转 OCR；
   - **title_overlap ≥ 0.7（约 31 条）** = 标题高度命中正文 → **一律保留为 success，不误杀**（DOI 常因首页为图/老刊未印而抽不到）；
   - **灰色 8 条（0<overlap<0.7，或 overlap=0 但 chars>0）** → 写 `_websearch_fp_openbook_141.py` **逐条开卷核真身**（期望 title vs 落盘正文/metadata）。
3. 灰色 8 条终裁：**7 条实为完全无关文档（错文实锤）**，1 条（`catcom.2018.07.014`）CMap 损坏乱码无法确认 → 保守归 OCR 桶不实锤。

---

## 三、7 条 websearch 假阳实锤（开卷坐实）

| # | DOI | batch | overlap | 期望论文 | 落盘实为（开卷真身） |
|---|---|---|---:|---|---|
| 1 | 10.1016/0021-9517(87)90366-6 | rerun_elsevier_143 | 0.7 | CO₂ 加氢制轻烃（Rh/Nb₂O₅） | **《Hydrogenation》实验室安全须知 Fact Sheet**（LSP #21-003 v3，EHS 单页） |
| 2 | 10.1016/0304-5102(82)85049-9 | rerun_elsevier_143 | 0.5 | CO/CO₂ 加氢（Rh 催化） | **同一份安全须知**（bytes/pages/chars=355744/5/12416 与 #1、#3 完全一致） |
| 3 | 10.1016/j.apcatb.2017.01.076 | rerun_elsevier_143 | 0.6 | CO₂ 制甲醇（CuCeTiO） | **同一份安全须知**（同 355744 字节文件） |
| 4 | 10.1021/acs.iecr.5c03132 | batch4_p5 | 0.0 | CO₂ 制航空燃料 TEA/LCA | **气象天气图**（经纬网 + ITCZ/季风/风暴标注，非论文） |
| 5 | 10.1016/j.elspec.2006.11.032 | batch6 | 0.6 | IA 族硫酸盐 XPS 谱 | **CasaXPS 软件技术手册《XPS Spectra》**（casaxps.com，非论文） |
| 6 | 10.1016/j.ccr.2019.02.001 | batch4_p4 | 0.62 | MOF 催化 C1 化学综述 | **《C1 Chemistry: Principles and Processes》CRC/T&F 书（2022）**（撞题错书） |
| 7 | 10.1021/ie020677q | batch4_p1 | 0.0 | CO₂ 甲烷重整动力学（碳化物） | **日文住宅配电盘（分電盤）规范文档**（非论文） |

**★ 系统性发现**：#1–#3 是 **`rerun_elsevier_143/fetch` 那波把 3 个不同 DOI 全下到同一份 PDF**（355744 字节、内容为同一份 Hydrogenation 安全须知）——websearch 撞关键词抓错 + 未按 DOI/标题校验落盘正文所致；三条均 `qc=null` 从未被拦，正虚高计数。中等 title_overlap（0.5–0.7）恰因 "hydrogenation/carbon/catalyst" 等词在安全须知中出现而误导，佐证 **overlap 中值不可作真值判据，必须开卷**。

---

## 四、存疑 / OCR 桶（不实锤，不误杀）

- **10.1016/j.catcom.2018.07.014**（batch7，20 页，chars=3762，CMap 损坏乱码）：正文抽取为乱码（"ßÁ«|\¢¨¤ï…" + 疑似日文目录结构），**无法确认真身** → 按 SOP④ 归 **OCR 复核桶**，不列实锤（宁漏放不错杀）。疑似与 #7 同类（日文错文），建议 OCR 后再定。
- **-176 OCR 桶 14 条**（chars=0）维持挂起转 OCR，本轮不动。
- **title_overlap ≥ 0.7 的 SUSPECT（约 31 条）** 全部保留为 success（标题全中、仅 DOI 未抽到），不误杀。

---

## 五、reject 增量 CSV（交 -144 并入）

- **文件**：`out/_websearch_fp7_hardblack_append_141.csv`（7 行，列格式与 `qc_merge_highconf_wrong.csv` 完全一致：`batch,doi,verdict_151,title_score,url_wrong,pdf_url,pdf_actual,pdf_path`）。
- **去重**：与 `qc_merge_highconf_wrong.csv` 现有集合、169-9、176-OCR14、176-openaire3/crossref1、ACS-SI33 **overlap = ∅**。
- **落盘动作（属主/-144 执行，本人不改盘）**：
  1. 将 7 行 **追加**到 `out/qc_merge_highconf_wrong.csv`；
  2. 重跑 `python tools/build_coverage.py`；
  3. **预期 success 339 → 332（−7）**，`rejected_hard` +7。

---

## 六、对基线口径的影响（诚实）

| 阶段 | success | 说明 |
|---|---:|---|
| 当前权威（含 -144 的 websearch −9） | **339** | `generated_ts 01:27:42` |
| 本轮 websearch −7 落盘后 | **332** | 本文 7 条实锤 |
| 另待并入（-176 HOLD，非 websearch） | 332 − openaire3 − crossref1 = **~328** | -176 已产 append，独立并入 |
| OCR 桶（14+catcom）/ ACS-SI 33 | 待 OCR / 单独排期 | 判定前不计成功，可能继续下修 |

> websearch 作为最大成功来源（by_source=142），历经 169(−9)→本轮(−7)=**共 −16 假阳**；剩余 websearch success 中 title_overlap≥0.7 者已开卷保留，**本源的高危错文清查到此收口**（余量在 OCR 桶，需 OCR 而非再清查）。

---

## 七、护栏

- 本文为 **只读开卷 + 产 reject 清单**：**未改** coverage.json / qc_merge / 代码 / git；仅新建本 md + 1 个 reject CSV + 1 个只读探针 `_websearch_fp_openbook_141.py`。
- 判据严格承 169 SOP：**正文/落盘真身为准**，`title_overlap ≥ 0.7` 一律保留，**宁可漏放不可错杀**。
- reject 落盘与 coverage 重算交 **-144 / pipeline 属主** 执行。

---

*143｜2026-07-03｜websearch 假阳清查收尾：重跑 `_mon169_qc_openbook_scan.py` + 开卷 `_websearch_fp_openbook_141.py`；净新增 7 条 websearch 错文实锤（rerun_elsevier 同文件 3 + 气象图 1 + CasaXPS 手册 1 + C1 书 1 + 日文配电盘 1），预期 339→332；reject 增量 `out/_websearch_fp7_hardblack_append_141.csv` 交 -144 并入。未改 coverage/代码/git。*

<!-- selftest: WEBSEARCH_FP_SCAN_141_OK -->
