# 检索成果 · T0 翻案 4 条边界终裁（apcatb/s1872/anie 采纳，1.5053761 驳回）

> 交付：**谷歌学术人机认证-147**（worker）｜2026-07-02｜总指挥 **-144** 派发终裁任务（`task-72e0cec1-5194-4d74-9556-da794df63cd6`）「终裁 T0 4 条边界：判是否 qc-allow 白名单纠假阳（+4 潜在→385）」。
> 边界：**纯判定 + 文档**——未改任何核心 `.py`、未回写 `coverage.json`、未重下。核验四手段：① 读 156/148 证据（`out/_t0_recover156_netgain.csv` / `out/_t0_prescreen_99_148.csv`）；② **crossref 独立核期望标题真伪**（api.crossref.org/works）；③ **开卷读落盘 PDF 正文**（PDF→文本，逐条看首页标题/DOI/正文）；④ 只读 `pypdf` 探针在**正文 / DocInfo / XMP / 超链接注解**四处查期望 DOI 与标题。
> 承接：156《检索成果-T0翻案6条FLIP默认路径回收跑…-156.md》§六（4 条建议回写待 -147 终裁）、148《检索成果-T0预筛still_missing翻案99条-内容QC逐条-148.md》§二（A 档 6 候选）。

---

## 〇、TL;DR（终裁口径）

- **本次终裁 4 条边界**（156 列「建议回写 +4」、须人核）：**采纳 3 / 驳回 1**。
- **采纳 3 条**（在盘净源开卷人核=真全文，属 DOI 键黑名单假阳 → 纠假阳入 `--qc-allow`）：
  - `10.1016/j.apcatb.2021.119925`（elsevier）
  - `10.1016/s1872-2067(17)62899-7`（elsevier，hard 黑名单——但 qc_allow 入口双扣自动压过，**无需手动移除**）
  - `10.1002/anie.201406637`（wiley）
- **驳回 1 条**：`10.1116/1.5053761`（aip）—— **在盘「净源」实为《AIP Content Platform User Guide》平台操作手册（14 页）**，正文 / DocInfo / XMP / 超链接**四处均无**目标 DOI 与标题。156/148 记的 `match/100/expected-doi-present` 系**信 `metadata.jsonl` 下载期记录、未开卷复核落盘 PDF** 造成的假阳。真全文仍缺，须**真源重取**，**非白名单可纠**。
- **净增修正：156 的「建议 +4 / 完整可救 +6」→ 终裁「+3 / 完整可救 +5」**。**当前权威基线已升至 388/999=38.84%**（`out/coverage.json` 22:31:41，立即档 jcou/jechem 2 条已并入 allow13；详见《基线口径冻结说明-388-173.md》）：**本终裁 3 条为待并入项 → 388 → 391（回写后）**。〔下文 379/381/384/385 为成文时基于旧 379 基线的推算，均属【历史口径】〕
- **诚实提醒**：本波暴露「脚本 / 预筛信 manifest ≠ 落盘真全文」的系统性缺口——1.5053761 是**唯一开卷才现形**的假阳（占本 4 条边界的 1/4），佐证终裁人核不可省，并给门属主一个具体加固点（见 §六）。

---

## 一、终裁四重独立核验（逐条留痕）

| # | 手段 | 来源 | 作用 |
|---|---|---|---|
| ① | 读 156/156 证据 CSV | `_t0_recover156_netgain.csv`、`_t0_prescreen_99_148.csv` | 承接脚本 verdict/score/exp_doi_present/src_dir |
| ② | crossref 核期望标题 | `api.crossref.org/works/{DOI}` | 排除「元数据抓错标题→循环论证」；确认 exp_title 是该 DOI 真身 |
| ③ | **开卷读落盘 PDF 正文** | 各在盘净源 `out/*/pdfs/*.pdf` | 人核「PDF 内容是否该文章真全文、是否 SI/错文/占位文档」——**终裁核心** |
| ④ | pypdf 只读探针 | `_t0_adjudicate147_probe.py` | 正文 / DocInfo / XMP / 超链接四处查期望 DOI+标题，定位假阳 root cause |

> crossref 核验：4 条 exp_title **全部与 crossref 真实标题逐字一致**（含期刊/年/type=journal-article），exp_title 可信。

---

## 二、逐条终裁（证据 + 处置）

| DOI | 桶 | 在盘净源（路径 / 源 / 字节 / 页） | crossref 标题 | 开卷正文核验 | 黑名单类型 | 终裁 | 处置 |
|---|---|---|---|---|---|---|---|
| `10.1016/j.apcatb.2021.119925` | elsevier | `rerun_elsevier_143/fetch/pdfs/` · openalex · 1,765,161B · 33p | 一致（Appl. Catal. B 2021） | ✅ 真全文：NREL「Cu/BEA 催化剂碳物种」**DOE 同行评审接受稿**，含摘要/引言/正文/结论；`meta.title`+`meta.subject` 均含正确标题与 DOI；正文含 `cu/bea`；**无 intext 异 DOI** | union+manifest_soft | **采纳** | 入 `--qc-allow` |
| `10.1016/s1872-2067(17)62899-7` | elsevier | `rerun_elsevier_143/fetch/pdfs/` · openaire · 2,187,222B · 9p | 一致（Chin. J. Catal. 2017） | ✅ 真全文：CJC 38 (2017) 1549–1557「Pd₁/ZnO 单原子催化」，含卷期页/摘要/正文；正文含 `1549`/`single` | **hard**+union+manifest_hard | **采纳** | 入 `--qc-allow`（入口双扣自动压过 hard，无需手动移除） |
| `10.1002/anie.201406637` | wiley | `rerun_wiley_144/fetch/pdfs/` · semantic_scholar · 579,727B · 4p | 一致（Angew. Chem. Int. Ed. 2014） | ✅ 真全文（最干净）：正文**首行直接印 `DOI: 10.1002/anie.201406637`** + 标题「Opposite Face Sensitivity of CeO₂…」；4 页属 communication 正常；正文含 DOI 与标题 | union+manifest_soft | **采纳** | 入 `--qc-allow` |
| `10.1116/1.5053761` | aip | `recover_b4_cf/pdfs/` · crossref · 5,084,557B · 14p | 一致（Surf. Sci. Spectra 2019） | ❌ **假全文**：落盘实为《**AIP Content Platform User Guide**》平台操作手册（目录/搜索/期刊导航/图书章节，末页 `help@aip.org`）；**正文/DocInfo/XMP/超链接四处均无**目标 DOI 与标题 | uncertain-pool | **驳回** | **不白名单**；真全文仍缺，须真源重取 |

> 说明（pypdf 正文提取的 needle 差异，不影响判定）：apcatb 的 `spectroscopic insight`、s1872 的 `probing the catalytic behavior` 因 PDF 排版把标题拆行/特殊连字符，`in`-string 匹配为 False，但**开卷首页人读标题清晰可见且与 crossref 一致**、主题词（`cu/bea`/`1549`/`single`）命中——真全文成立。anie 正文提取干净（DOI+标题均 True）。

---

## 三、`10.1116/1.5053761` 驳回详证（重点·唯一翻转 156 结论处）

**落盘文件**：`out/recover_b4_cf/pdfs/10.1116_1.5053761.pdf`（5,084,557B，14 页，source=crossref）。

**开卷内容**（14/14 页全部）：AIP Publishing《Content Platform User Guide》——`The Homepage / Searching the Platform / Navigating a Journal Homepage / Viewing an Article / Navigating Books / Viewing a Book Chapter`，含 `visiting: https://pubs.aip.org/my-account/register`，末页为 AIP 地址与 `help@aip.org`。**无一字**是《Carbon dioxide gas, CO2(g), by near-ambient pressure XPS》论文正文。

**pypdf 只读探针（`_t0_adjudicate147_probe.py`）四处查证**：

```
=== 1.5053761_ondisk_crossref ===
   pages: 14   body_chars: 8276        # 590 字符/页（真全文对照 1820~4900/页）
   meta.title  : None
   meta.subject: None
   body_has[5053761]: False            # 正文无目标 DOI
   body_has[carbon dioxide gas]: False # 正文无目标标题
   body_has[content platform]: True    # 正文=平台指南
   body_has[user guide]: True
   ANNOTATION: total_link_uris=0        # 无超链接
   XMP: xmp_len=4528, has_5053761=False, has_carbon_dioxide_gas=False
```

**对照（三条真全文，同探针）**：

```
anie.201406637 : meta.title=正确标题  meta.subject=Angew...2014.53:12069-12072  body_has[DOI]=True  body_has[title]=True
s1872-2067     : meta.title=投稿Word名  body_has[1549]=True  body_has[single]=True
apcatb.2021.119925: meta.title=正确标题  meta.subject=...DOI:10.1016/j.apcatb.2021.119925  body_has[cu/bea]=True
```

**root cause 判定**：期望 DOI/标题在落盘 PDF 的**正文、DocInfo、XMP、超链接四处全无** → 156/148 的 `expected-doi-present=True / match/100` **不可能来自该 PDF 本身**，只能来自**读取 `recover_b4_cf/metadata.jsonl` 下载期记录**（记 source=crossref、title=期望标题、verdict=match），而实际落盘的是 AIP 在 CF/访问受限时返回的平台指南占位文档。**即「在盘净源 match/100」是信 manifest、未开卷复核落盘 PDF 的假阳**。

**处置**：`10.1116/1.5053761` 维持在 uncertain-pool **驳回**，不入白名单；其真全文仍缺（aip 桶 route-b off 恒 cloudflare-challenge，需 route-B / 真源重取，非黑名单纠假阳可解）。

---

## 四、净增口径修正（156 → 终裁）

| 档 | 156 原口径 | 终裁修正 | 差异根因 |
|---|---|---|---|
| 立即（jcou/jechem） | +2 | +2（不变，交 -151） | 双重 match/100，非本次终裁范围 |
| 建议（4 条边界） | +4 | **+3** | 1.5053761 开卷=用户指南，驳回 |
| **完整可救合计** | +6 | **+5** | — |
| 官方 coverage 映射〔历史推算〕 | 379 →（+2）381 →（+6 全）385 | **当前权威 388**（立即 2 条已并入）→（终裁 +3）**391** | 剔 1.5053761；388 见《基线口径冻结说明-388-173》 |

---

## 五、给 -151 的最终回写清单（本岗只产清单、不回写）

清单文件：`out/_t0_adjudicate147_qcallow_final.txt`（已剔除 1.5053761）。属主执行：

```
python tools/build_coverage.py \
  --qc-allow out/_t0_adjudicate147_qcallow_final.txt \
  --extra-dirs rerun_elsevier_143/fetch,rerun_wiley_144/fetch
```

- **立即档 +2**（156 认定、-151 在写/已写；经监管者 -169 开卷复验：两条正文均含 `https://doi.org/…` 期望 DOI + `meta.title` 正确 → **381 地基结实、非 metadata 顶包**）：`10.1016/j.jcou.2022.102356`、`10.1016/j.jechem.2020.06.007`
- **终裁采纳 +3**：`10.1016/j.apcatb.2021.119925`、`10.1016/s1872-2067(17)62899-7`、`10.1002/anie.201406637`
- **`10.1016/s1872-2067(17)62899-7` 说明**：虽在 **hard 黑名单**，但 `build_coverage.py`（L323-327）入口即 `qc_hard = qc_hard - qc_allow`、`qc_soft = qc_soft - qc_allow` 双扣，`qc_allow` 优先级最高——写进 `--qc-allow` 即自动压过 hard，**无需改代码、无需手动改 hard 名单文件**（经监管者 -169 核码 + 本岗复核 L323-327 确认）。
- **驳回不入清单**：`10.1116/1.5053761`。

---

## 六、给门属主 -140/-161 的加固点（本波实锤，非本岗改码）

1. **QC verdict 必须对「落盘 PDF」实时正文复核，不能只信 `metadata.jsonl` 下载期记录**。1.5053761 实锤：manifest 记 match/100，落盘却是平台用户指南。建议 `build_coverage` / 预筛脚本在采信 manifest verdict 前，对落盘 PDF 至少抽验一次正文标题 match。**（监管者 -169 已认同并将上报总指挥固化为回写前 SOP：凡用于 coverage 回写的 qc-allow/内容 QC 判据，必须开卷读落盘 PDF 复验 expected-doi-present，禁止直接采信 metadata.jsonl 下载期 verdict。）**
2. **`expected-doi-present` 判定源需收敛**：当**正文 + DocInfo + XMP + 超链接四处均不含**期望 DOI 时不得判 present（排查门当前把 DOI-present 记在哪——疑似来自 source_url / 文件名 / manifest）。
3. **加「正文可提取标题 match」为 `match` 必要条件 + body 字符密度下限**：1.5053761 仅 590 字符/页（图多字少的平台指南 / 幻灯特征），真全文对照 1820~4900 字符/页；且正文提不出与期望标题 match 的字符串。可加「每页有效字符下限」或「正文须含 ≥1 段与 exp_title match 的文本」双阈值，把此类占位文档降级 uncertain。

---

## 七、产物清单（本波新写，均在仓根 / `out/`，未改核心码）

| 文件 | 说明 |
|---|---|
| 本 md | T0 4 条边界终裁（3 采纳 + 1 驳回）+ 证据 + 口径修正 + 加固建议 |
| `out/_t0_adjudicate147_qcallow_final.txt` | **最终 qc-allow 回写清单**（2 立即 + 3 终裁 = 5 条；剔 1.5053761）交 -151 |
| `_t0_adjudicate147_probe.py` | 只读 pypdf 探针（正文/DocInfo/XMP/超链接四处查 DOI+标题，可复现终裁；一次性、可删） |

---

*核验 2026-07-02｜谷歌学术人机认证-147｜纯判定 + 文档、未改核心 `.py` / 未回写 coverage / 未重下｜手段：crossref 核标题 + 开卷读落盘 PDF 正文 + pypdf 四处探针｜承 156（4 条建议）、148（A 档 6 候选）｜采纳 3 交 -151 回写（**待并入 +3：当前权威 388→391**）、驳回 1（1.5053761 真源重取交 route-B）、加固 3 交 -140/-161｜回报总指挥 -144。*
