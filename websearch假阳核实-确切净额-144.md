# websearch 假阳核实 + 确切净额（144 · task-707b02e7）

> 交付：**谷歌学术人机认证-144**（秘书·数据/coverage）｜只读核实，**未写 coverage / 未动黑名单**。
> 权威源：`out/coverage.json`（定版 2026-07-03 12:50:24，success=326）、开卷扫描 `_mon157/169/176_*openbook*`、`_ws_openbook_qc_159.json`、假阳黑名单 append CSV。
> 判据：① **doi_in_body = 金判据**（正文含本 DOI → 真全文）；② expected_title vs **pdf_actual 实际内容**词重叠 + 垃圾标记（PPT/newsletter/template/SI/title-page/…）。

## 一、结论（一页）

| 分层 | 条数 | 说明 |
|---|---:|---|
| websearch success（coverage 现值） | **129** | source=websearch & status=success |
| ✅ 金判据真全文（doi_in_body） | **89** | 不可辩驳，净额地板 |
| ✅ 内容匹配真（pdf_actual≈expected, ov≥.5） | **7** | doi 未被提取但正文即该文 |
| ❌ 确认假阳（已知黑名单） | **8** | 143 巡检的 fp7∪mon157w3（同 355744B 错PDF 套3DOI 等） |
| ❌ 确认假阳（本轮新开卷 clear） | **13** | 见下表，pdf_actual 为完全不同文档 |
| ⚠️ 边界（同主题异标题，需人工二次开卷） | **12** | 多数偏假阳 |

- **确切净额（websearch 真全文）= 96（地板：89 金 + 7 内容匹配）～108（边界全真上限）**；边界多偏假阳，**现实 ~96～100**。
- **确认假阳 = 21**（8 已知 + 13 新）；**较 143 的 8 条扩到 21**。
- **coverage 影响（若下一波并入 21 假阳黑名单，144 单写）**：success **326 → 305**（−21）、miss 673 → 694、覆盖 32.63% → **30.53%**；若 12 边界再证伪则最多再 −12。

## 二、确认假阳（13 新 · 建议并入硬黑名单）

| DOI | 期望标题 | 实际PDF内容 |
|---|---|---|
| 10.1007/978-1-4614-8298-7_5 | UV-Vis Spectroscopy(书章) | 课程 Module-6 Unit-4（非该书章） |
| 10.1016/j.apcata.2015.10.041 | strongly bound copper–ceria | tungsten oxide on ceria nanorods（异文） |
| 10.1016/j.cej.2026.174737 | Direct combination of RWGS and FTS | Recent advances in electrocatalytic ORR（异文） |
| 10.1016/j.chemosphere.2010.09.078 | (元数据即)西语谚语 | índice/Alegoría 西语短语学（非化学） |
| 10.1016/j.cherd.2014.03.005 | CO2 hydrogenation to methanol review | "PREPARACION OF FUL PAPER"会议模板 |
| 10.1016/j.ijhydene.2016.08.032 | CO2 reduction microwave | AMPERE-Newsletter 92（简报） |
| 10.1016/j.jcat.2026.116771 | Regulation of CO2 on Cr6+ | Spectroscopic insights…（异文） |
| 10.1016/j.jcou.2017.09.012 | Pd/Cu ratio Pd-Cu-Zn/SiC | greenhouse-gas Emission Trading（经济学异文） |
| 10.1016/j.jpowsour.2015.01.083 | high-temp co-electrolysis | 韩文 [50-54]…홍종섭.fm（异文） |
| 10.1021/acscatal.5b00877 | Zinc-Rich Cu Catalysts | cs-2015-00877g **supporting_information**（仅SI） |
| 10.1039/b918763b | Green Chemistry(书) | PowerPoint Presentation |
| 10.1039/c5ee03649f | Transition metal carbides CO2 | "Template for Electronic Submission to ACS" |
| 10.1504/ijnt.2017.082461 | Methanol via CO2 | IJNT JOURNAL TITLE PAGE（仅题页） |

（8 已知硬黑：10.1016/0021-9517(87)90366-6、10.1016/0304-5102(82)85049-9、10.1016/j.apcatb.2017.01.076、10.1016/j.catcom.2018.07.014、10.1016/j.ccr.2019.02.001、10.1016/j.elspec.2006.11.032、10.1021/acs.iecr.5c03132、10.1021/ie020677q）

## 三、边界 12（需人工二次开卷；DOI 见 `out/_ws_fp_verdict_144.json`）

10.1016/j.apcatb.2022.121640｜10.1016/j.catcom.2017.06.003｜10.1016/j.cej.2024.156577｜10.1016/j.fuel.2022.123707｜10.1016/j.ijhydene.2022.01.021｜10.1016/j.jcis.2017.02.014｜10.1016/j.susc.2005.08.015｜10.1021/acssuschemeng.4c05125(空/不可读)｜10.1021/ie303248q｜10.1021/ja304958u｜10.1088/0957-4484/22/26/265704｜10.3390/catal12121511

> 多为「同主题异标题」——例：Cu review vs DFT-Ho-doped、CuAl2O4 vs amine MEA、oxygen-vacancy vs first-principles-guide，倾向异文（假阳）；ja304958u(Fe 粒径 FT) 倾向同文。建议逐条开卷定谳。

## 四、与全局口径的关系（提示，非本波写盘）

- 本审计 **反向**于 148 的 +59 开卷翻案（rejected→success）。二者均为 **144 单写** 的 coverage 纠偏：
  - +59 翻案（148 gold） − 21 websearch 假阳（本审计） = **净 +38** → success 326 → ~364、覆盖 ~36.4%（含边界不确定 ±12）。
- ⚠️ 口径纪律：以**当前 326** 为准（非 157 旧 01:27 基线）；写盘须 144 单写 + 备份 + 逐条，严防打穿。

*核验 144｜纯只读、未改 coverage/黑名单/git｜数据落 `out/_ws_fp_verdict_144.json`（confirmed_fp 21 + borderline 12 全 DOI）。*
