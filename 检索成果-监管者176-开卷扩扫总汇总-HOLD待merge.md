# 监管者176 · 开卷扩扫总汇总（HOLD 待 −9 落盘后 merge）

> 2026-07-02｜176 接棒 169｜coverage **定版 326/673/32.63%（2026-07-03 12:50:24）** — 全部待并项已落盘  
> **2026-07-03 更新**：websearch −9 已由 -144 落盘 ✅（generated_ts 00:10:44；详见 -144 report_task）
> 纪律：本文档 + append CSV 均为移交包，**未改 qc_merge / coverage**

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

## 五、merge 后 ping 总指挥 checklist

- [ ] `coverage.json` `generated_ts` 更新且 success=376（−9  alone）
- [ ] 13 条实锤 append 并入 `qc_merge_highconf_wrong.csv`
- [ ] 重跑 `build_coverage.py` → 预期 **372**
- [ ] 更新《基线口径冻结说明-388-173.md》
- [ ] ACS SI 33 单独排期

---

*176｜HOLD 态汇总，等 −9 落盘*
