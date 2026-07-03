# 验证 · 173 门③④⑤ 对 recover_b4_cf success 的拦截率 / 必要性 / 误杀

> 交付：谷歌学术人机认证 · worker **-147**｜taskId=`task-bb7bb91e`｜2026-07-02
> 触发：总指挥派单——扫描 recover_b4_cf success 条目，分类 SI/poster/错DOI/真全文，**验证 173 文档门③④⑤必要性与拦截率**。
> 边界：**只读**。仅读 `out/recover_b4_cf*` 的 metadata.jsonl 与落盘 PDF；未改任何 `.py`/metadata/PDF。
> **v2 重要更新**：分析期间 `fulltext_fetcher/download.py` 被并发落地——**门④⑤ + §9.2 源强制 + §9.6 非正文先于 DOI 强正 已实现**。本文数据据**已落地真门 end-to-end** 复跑（非纸面推演）。
> 复现脚本（只读）：`_tmp_verify_gate_live_147.py`（真门 end-to-end）、`_tmp_verify_gates345_147.py`（门规则单测）、`_tmp_verify_escape_mech_147.py`（逃逸机制拆分）。pypdf 3.17.4 / rapidfuzz 3.14.5。
>
> ℹ️ **净覆盖率口径（173 冻结）**：本文为门③④⑤**拦截率/误杀**验证（51 条 SI 假阳等为**批次级**证据，非全局净覆盖）。这些假阳正是净覆盖须扣除的对象。**全局净覆盖唯一权威 = `out/coverage.json`：326 success / 673 miss / 999 = 32.63%**（generated_ts 2026-07-03 12:50:24, allow=10；388/611/38.84% 为【历史】）。见 **《基线口径冻结说明-388-173.md》**。

---

## 〇、TL;DR（给 144 / 161 / 145 / 140）

- **门④⑤ 已落地且有效**：`hard_reject=True` 下对 recover_b4_cf 34 条 success **真实拒盘 25/29 假阳（86%），真全文误杀 0/5**。
- 按 142 干净口径（逃逸门①②的 **9 条 auto-match**）：**门④⑤ 拒 8/9**——SI×5(门④) + citation-report×2(门⑤A) + poster×1(门⑤B) 全收；**唯一漏网 = `cctc.200900261`（同题他刊）= 门③ 的活，门③ 尚未实现**。
- **门③ 仍缺**：且 173 §3.1「首500字 body-DOI」口径**也抓不到** cctc（Beilstein DOI 不在首500字）→ **必须走 §9.4 `meta-doi-mismatch`（读 XMP/Info 的 /doi）**才收得住。
- **默认是 soft（非正文→uncertain，仍落盘+打标 qc_uncertain，不拒盘）**。**145 CF 重跑须置 `content_qc_non_article_hard_reject=True`**，否则 9 条 SI/引用报告/海报仍落盘（仅靠 build_coverage 消费 qc_uncertain 事件才回 miss）。
- **运维铁律（142 §9.3 复核坐实）**：本门全链依赖 pypdf；**运行时缺 pypdf → 门静默 no-op、100% 放行**。本目录历史 12 条错论文 active 即此根因。

---

## 一、success 盘点与逃逸机制拆分（34 唯一 = full-80 27 + smoke10 7）

| 机制 | 条数 | 说明 |
|---|---:|---|
| 真全文（ground truth，142 v2 人工开卷） | 5 | ep.670220410 / apcata.2015.10.041 / iecr.5c04764 / apcatb.2021.120319 / c1gc15503b |
| 门①②可判（含标题他题/跨社异DOI） | 16 | 走 `content-title-mismatch(<50)` 或 `url-doi-conflict`；hard/soft 均拒 |
| **门④⑤ 目标（逃逸①②的非正文 auto-match）** | **9** | SI×5 + citation-report×2 + poster×1 + **同题他刊×1** |
| 整源豁免（`_source_needs_content_qc`=False，门不跑） | 2 | iecr.5c04764(unpaywall,真全文✓) / **1.5053761(crossref, TOC/手册)** |
| 真扫描/中间带 uncertain（非门③④⑤目标） | 2 | jnn.2017.12725(扫描EPS图1) / c5cc01545f(partial 60) |

> 与 **142 口径对齐**：门③④⑤ 净目标是「逃逸门①② 的 auto-match」，**不含**那 16 条门①② 已判、分数 <50 的错论文（勿混入同一「假阳」分母）。

---

## 二、门④⑤ 已落地 · 逐条真实拦截（`hard_reject=True`，end-to-end）

| DOI | 类型 | 源 | soft(默认) | hard_reject | 命中门 |
|---|---|---|---|---|---|
| 10.1021/acsanm.1c00959 | SI-only | acs-authorchoice | pass(uncertain) | **REJECT** | 门④ non-article-si |
| 10.1021/acscatal.0c01253 | SI-only(smoke) | acs-authorchoice | pass(uncertain) | **REJECT** | 门④ |
| 10.1021/acscatal.4c04824 | SI-only | acs-authorchoice | pass(uncertain) | **REJECT** | 门④ |
| 10.1021/acscatal.8b02371 | SI-only | acs-authorchoice | pass(uncertain) | **REJECT** | 门④ |
| 10.1021/nl401568x | SI-only | acs-authorchoice | pass(uncertain) | **REJECT** | 门④ |
| 10.1021/acs.chemrev.7b00776 | citation-report | websearch(exaly) | pass(uncertain) | **REJECT** | 门⑤A |
| 10.1016/j.jcou.2017.08.019 | citation-report | websearch(exaly) | pass(uncertain) | **REJECT** | 门⑤A |
| 10.1016/j.jcou.2018.01.028 | poster(1页) | websearch(zenodo) | pass(uncertain) | **REJECT** | 门⑤B |
| **10.1002/cctc.200900261** | **同题他刊** | websearch(beilstein) | **pass** | **pass** | **漏（门③ 未实现）** |

**门④⑤ 拦截率 = 8/9 = 89%**（干净口径）。唯一漏网 `cctc.200900261` 需门③/§9.4。

**验证要点（对 173 §9.6 排序的实证）**：上 5 条 SI + 2 条 citation-report 的首页**都印着期望 DOI**（`expected-doi-present` 本会短路判 match）。已落地代码把**非正文判识排在 DOI 强正之前**（`download.py:597-602`），故 hard_reject 下正确拒盘——**§9.6 排序已生效且必要**（关掉 `content_qc_non_article` 回退后，这 7 条立即变回 `match/expected-doi-present`，实测可回退）。

---

## 三、拦截率 / 误杀（两种口径）

| 口径 | 分母 | hard_reject 拒盘 | 拦截率 | 真全文误杀 |
|---|---:|---:|---:|---:|
| 全部非真全文 active/success | 29 | 25 | **86%** | **0/5** |
| 142 干净口径（逃逸①②的 auto-match） | 9 | 8 | **89%** | 0 |

**误杀 = 0**：5 条真全文全部 `pass`。已落地 `_content_qc_non_article_reject` 的 `has_body`（首3000字含 Abstract/Introduction/Results）护栏生效——正文含末尾 SI 章节、正文引用「cited by」均不误杀（173 §9.7 不误杀②③ 的实证）。

---

## 四、剩余缺口（给 161 / 145，按优先级）

1. **P0 · 门③ 未实现，且首500字口径抓不到同题他刊**。`cctc.200900261` 落盘 Beilstein `10.3762/bjoc.7.159`，该 DOI 不在首500字（在正文中后段），门③(§3.1 body 口径)命中失败。→ **落 §9.4 `meta-doi-mismatch`**：读 `reader.metadata['/doi']` + `reader.xmp_metadata`(prism:doi)，`norm(meta_doi)!=norm(exp_doi)` 即拒（出版商无关，补门②(b)(c) 未登记前缀盲区）。**注意不误杀**：ACS SI 元数据也带母文 DOI，故 meta-doi 命中不得当放行，门④须独立保留。
2. **P0 · 145 CF 重跑必须开 `content_qc_non_article_hard_reject=True`**。默认 soft 下 9 条非正文仍落盘（仅 uncertain 打标）；不开硬拒 = success 率虚高、净覆盖再污染。**或** build_coverage 增消费 `content_qc` 事件 `verdict=uncertain/reason=non-article-*` 的软黑名单口径。
3. **P1 · `1.5053761`(crossref, 14页手册) 双重逃逸**，两条都要修才收得住：
   - (a) **整源豁免**：`crossref` 不在 `_QC_GATE_SOURCE_MARKERS` → `_content_qc_gate` 第一行 return None，门根本不跑。
   - (b) **门⑤C 页数卡口**：即便强制进门，落地 TOC 门是 `(_QC_NA_TOC_RE 命中 and not has_body and (page_count is None or page_count<=3))`；本件 **14 页 > 3** → 仍不触发（此前口径说"页数放宽"有误，仅 page_count 未知时才放宽）。
   - **建议**：采纳 142 的「门④⑤ 从 `_source_needs_content_qc` 解耦、对所有源统一跑」（解 a）；并**放宽门⑤C 页数卡**——`has_body` 护栏已足以防误杀真正文（真文必含 Abstract/Introduction），`page_count<=3` 对多页手册/目录过严，建议改为「命中 TOC 且 no has_body 即判（去页数上限，或仅在 page_count 极大且含正文时豁免）」（解 b）。
4. **P0 运维 · 确保运行环境装 pypdf**，并在「%PDF 过但抽出空文本」时记 `content_qc verdict=qc_blind`，区分真扫描 vs 缺库致盲（142 §9.3）。

---

## 五、与 173 / 142 §9 的一致性

- 173 附录 A「8 条假 match」+ smoke `0c01253` = 本验证 9 条 auto-match，**逐条命中门与实测一致** ✅；门④⑤ 已按 §9.6 落地并实证有效。
- 印证 142 §9.2（acs-authorchoice 整源豁免已改为强制 QC）、§9.3（pypdf 致盲 no-op）、§9.4（同题他刊须 meta-doi，body 口径不够）、§9.6（非正文先于 DOI 强正）。
- 净口径不变：真全文 **5**（与 142 v2 一致）。门③ + hard_reject 落地后，本目录假阳可从 9 压到 **0**（含 1.5053761 需补源强制 QC）。

---

## 六、广样本不误杀回归（认领自 142 · decouple+hard_reject 翻默认门槛）

> 验收线（142 定）：跨目录已知真全文（重点 publisher_oa/unpaywall/crossref 正式版）过【解耦后的门④⑤ + hard_reject】**0 误杀** + §9.7 的 4 正例全过。
> 「解耦」= 绕过 `_source_needs_content_qc`，对所有源统一跑 `_content_qc_non_article_reject`（142 §9.9/§9.10 设计）。
> 脚本：`_tmp_regress_nofalsekill_147.py`（Part A 广样本）、`_tmp_regress_fixtures_147.py`（Part B §9.7 fixture）。只读。

### Part A · 广样本（DOI-keyed 解耦新暴露面，276 条 active PDF 去重）

| 指标 | 值 |
|---|---:|
| 样本 PDF（抽取失败 0） | 276 |
| 已知真全文（has_body 且 标题≥match_hi 或 DOI命中） | 143 |
| 宽松真实（has_body） | 152 |
| 解耦门④⑤命中（全部 `non-article-si`） | 51 |
| **真全文被误杀** | **0**（验收线 = 0）✅ |
| 命中里 has_body=True（疑似误伤真文） | **0** ✅ |

**关键增益**：51 条命中**全是 SI**（has_body=False），来源分布 `acs-authorchoice 40 + unpaywall/crossref/openalex/semantic_scholar 共 11`。这 51 条**当前靠整源豁免落盘为 success、污染净覆盖**；解耦+hard_reject 后被正确拒——**不仅 0 误杀，还净清 51 条 SI 假阳**。

**提议⑤C放宽（142 §9.10：has_body==False + TOC/user guide/author index/issue of the 主判，页数仅可选）**：额外命中 **2**，均 has_body=False、**0 误杀**：
- `10.1116/1.5053761`（crossref, 14页手册）——**目标件，收** ✅
- `10.1038/s41929-022-00871-7`（publisher_oa:nature, 74页）——经查**是 Nature SI**（"In the format provided by the authors and unedited / Supplementary Information / Table of Contents"），非正文，**收对了** ✅

### Part B · §9.7 四正例（+ 反例）

| fixture | 结果 | 判定 |
|---|---|---|
| ①真全文（Abstract+Introduction） | `match/title-match` | PASS |
| ②正文末含 SI 章节 | `match/title-match` | PASS（has_body 护栏，S-1 不在首500字） |
| ③正文引他文 DOI（参考文献区/1200字后） | `match/title-match` | PASS（门②不反证） |
| ④缺 pypdf 降级 | `gate→None(放行)` | PASS（门 no-op，不误杀） |
| [反例] SI-only（hard_reject） | `mismatch` | PASS（证明门真会拒） |

**四正例全过、SI 反例生效 → 回归通过。**

### 结论 + 一处门④缺口（给 161）

- **decouple + hard_reject + ⑤C放宽 = 安全（0 误杀）且有益（净清 51+ SI）→ 建议采纳**（作为翻默认门槛，已达 142 验收线）。
- **门④ 缺口（新发现，P1）**：现有 SI 文本判识只认 `"supporting information"`，**漏 `"supplementary information"`**（Nature/多家用词）。上文 Nature SI(10.1038/s41929-022-00871-7) 即因此逃过门④、仅靠⑤C兜住。建议门④ SI 标记补 `supplementary information` + `in the format provided by the authors`（保持 `not has_body` 护栏，实测不误杀）。

*核验 2026-07-02｜worker -147｜task-bb7bb91e + 142 派广样本回归｜证据脚本 `_tmp_verify_gate_live_147.py` / `_tmp_regress_nofalsekill_147.py` / `_tmp_regress_fixtures_147.py`（只读，复跑零差异）｜未改任何 .py/metadata/PDF。*
