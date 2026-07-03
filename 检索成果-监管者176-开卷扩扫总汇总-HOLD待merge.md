# 监管者176 · 开卷扩扫总汇总（✅ HOLD 关闭 · 全部子项已并入 368 定版）

> 2026-07-02｜176 接棒 169｜coverage **定版 326/673/32.63%（2026-07-03 12:50:24）** — 全部待并项已落盘  
> **2026-07-03 更新**：websearch −9 已由 -144 落盘 ✅（generated_ts 00:10:44；详见 -144 report_task）
> 纪律：本文档 + append CSV 均为移交包，**未改 qc_merge / coverage**
>
> **✅ HOLD 关闭（2026-07-03 23:40 · -145 巡检核对）**：对照当前权威 `out/coverage.json`（368/631/36.84% @ 22:07:22），本汇总全部子项**逐 DOI 复核已并入**：ws9→硬黑 9/9·miss 9/9 ✓｜oa3→硬黑 3/3·miss ✓｜crossref1→硬黑·miss ✓｜ACS SI33→软黑(union) 33/33·miss 33/33 ✓｜OCR13 WRONG→硬黑 13/13·miss 13/13 ✓｜OCR1 TRUE(`10.1021/acssuschemeng.4c05125`)→留 success ✓。§五 checklist 中 376/372 预期为 326 定版前旧推算，已被 writeback149 后的 **368 定版**取代（见《基线口径冻结说明-388-173.md》）。本文档降格为【历史快照·移交包存档】。

---

## 一、待 merge 实锤假阳（−9 稳定后批量并入）

| 波次 | 条数 | append / 清单 | overlap 与 −9 |
|---|---:|---|---|
| websearch（169→176 复验） | 9 | `out/_mon176_websearch9_hardblack_append.csv` | ✅ **-144 已落盘** 00:10:44 |
| openaire 邻居顶包 | 3 | `out/_mon176_openaire3_hardblack_append.csv` | ∅ · ✅已落盘 |
| crossref Browse 帮助页 | 1 | ✅已并入总 append | ∅ · ✅已落盘 |
| **小计（实锤错文）** | **13** | 历史预期 385→372；实并入已 done | — |

crossref 1 条：`10.1252/jcej.38.807`（Browse 帮助页，508 chars）

---

## 二、已并入 / 已收口（原挂起项）

| 波次 | 条数 | 清单 | 说明 |
|---|---:|---|---|
| batch6 ACS SI_COVER | 33 | `out/_mon176_acs_si_still_success.txt` | ✅已并入 union（done） |
| OCR 不可验证 | 14 | `out/_mon176_ocr_bucket_still_success.txt` | ✅已收口：13 WRONG硬黑 + 1 TRUE 10.1021/acssuschemeng.4c05125 留success |

---

## 三、扩扫覆盖与 OK 率

| 扫描 | 范围 | total | OK | SUSPECT | 高危 |
|---|---|---:|---:|---:|---:|
| mon169 刷新 | websearch+allow 160 | 160 | 98 | 62 | 9 实锤 |
| agg | openaire+epmc+zenodo 35 | 35 | 29 | 6 | 3 实锤 |
| secondary | unpaywall+s2+openalex+crossref 136 | 136 | 88 | 48 | 1 实锤 |
| ACS SI | batch6+recover 57 | 57 | 1 ARTICLE | 47 SI | 33 仍 success |

---

## 四、交付文档索引

- `检索成果-监管者176-169接棒开卷复核与-9落盘移交.md`
- `检索成果-监管者176-ACS-SI假阳复核174波.md`
- `检索成果-监管者176-OCR桶与聚合源扩扫.md`
- `经验记录-增补-监管者169-回写必开卷SOP与websearch假阳9实锤-2026-07-02.md`（169 原文）

---

## 五、merge 后 ping 总指挥 checklist（✅ 全部核销 · -145 巡检 2026-07-03 23:40）

- [x] `coverage.json` `generated_ts` 更新（22:07:22；376 旧预期已被 writeback149 路径取代，实际定版 **368**）
- [x] 13 条实锤 append 并入 `qc_merge_highconf_wrong.csv`（ws9+oa3+cr1 逐 DOI 复核在硬黑 ✓）
- [x] 重跑 `build_coverage.py`（372 旧预期同上作废；现行定版 368/631/36.84%）
- [x] 更新《基线口径冻结说明-388-173.md》（368 定版 footer 已回填）
- [x] ACS SI 33 处置归入 A5 订阅通道范围（33/33 在软黑·miss；SI 封面非正文，免费路线不再投工程）

---

*176｜HOLD 态汇总，等 −9 落盘*
*-145 巡检核销 2026-07-03 23:40｜六子项逐 DOI 对照 coverage.json(22:07:22) 全部确认并入｜HOLD 关闭，降格历史快照存档。*
