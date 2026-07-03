# 检索成果 · T0 预筛 still_missing 翻案 99 条（逐条内容 QC，供 -147 turnkey）

> 交付：**信息检索-专家智库 · 谷歌学术人机认证-148**（worker，session 1f26d41c）｜2026-07-02
> 触发：用户「接入信息检索-专家智库记忆 → 继续其工作」；决策授权自决，采推荐项 **T0 预筛**（现实最高 ROI、近零成本）。
> 边界：**纯读审计**——只读 `out/_qc_union_translate_candidates_151.csv` + 各 `out/*/metadata.jsonl` + `out/*/pdfs/*.pdf`；**复用生产内容 QC 门**（`download._extract_pdf_text_meta / _pdf_page_count / _qc_matchers / _content_qc_verdict / _content_qc_non_article_reject`，O.5 模式，绝不重造判定）；**只新写** `out/_t0_prescreen_99_148.csv` + 本 md，**未改任何核心 `.py`、未回写 coverage、未跑网络**。
> 定位：**预筛 ≠ 终裁**。终裁归 **-147**（`tools/regress_qc_union_189.py` + 人核）；本文把 99 条按生产门证据分档，给 -147 一份可直接执行的清单 + 诚实预期净增。承 `检索成果-still_missing回写后561分桶与下一波ROI-142.md` §三（129 待裁池 = 30 ACS confirmed_bad + 99 PENDING）。
> 环境：pypdf 3.17.4 + rapidfuzz 3.14.5（门全活、非 no-op）；qc backend=rapidfuzz，match_hi=70 / mismatch_lo=50。
>
> ⚠️ **净覆盖率口径统一（173 冻结）**：本文基线 **379/999** 及推算 **384/391（39.1%）** 均为**【历史口径】**（早于 388 重建）。**【历史快照】当前权威见 `out/coverage.json`：326 success / 673 miss / 999 = 32.63%**（generated_ts 2026-07-03 12:50:24, allow_override=10）。99 条逐条 QC 分档与预期净增仍有效；**T0 终裁以 -147 为准（采纳 3 条、驳回 1.5053761）**，见冻结说明 §三。唯一权威见 **《基线口径冻结说明-388-173.md》**。

---

## 〇、TL;DR（诚实口径）

- **99 条 PENDING 逐条过生产门后分档**：**真正文候选（可翻）6** ｜ **SI/非正文（维持拒）17** ｜ **错文（维持拒）11** ｜ **待人核（uncertain）65**。
- **确认净增地板 = +5**（`expected-doi-present` 强正 + 非 SI，高置信真正文）；**+1 高概率**（apcatb.2021.119925，openalex DOI-keyed 源 + 标题 100，疑旧黑名单误杀）→ **高置信 +5~6**。
- **现实预期净增 ≈ +11~13**（65 待核里去掉 ~12 条「文内 DOI 指向他文」的疑似错文 + 4 条扫描件后，约 49 条真·边界候选按 ~10~15% 翻案率 → +5~7）；**诚实区间 +5（地板）~ +15（顶）**。
- **⚠️「99 全翻 → 521 / 47.8%」理论上限已被逐条证据判死**：99 里 **≥28 条已是硬确认错件**（17 SI + 11 错文）+ ~12 条待核疑错 + 4 条扫描件，**可翻面本就 ≤ ~55**，再乘翻案率 → 池子给不出接近 99 的净增。
- **落地口径**：若 -147/总指挥确认 5 条强正 → coverage **379 → 384（37.9% → 38.4%）**；现实 +12 → **391 / 39.1%**。与 -142「T0 现实 +10~15」同阶、且给出**可执行的 +5 确认地板**。

---

## 一、四档结果（证据：`out/_t0_prescreen_99_148.csv` 逐条）

| 档 | 条数 | 判据（生产门 verdict / na_reason） | 处置建议 |
|---|---:|---|---|
| **A. 真正文候选（可翻）** | **6** | `expected-doi-present`(5) + DOI-keyed 源标题 100(1) 且非非正文 | 入 `--qc-allow` 白名单（-147 人核后） |
| **B. SI / 非正文（维持拒）** | **17** | `non-article-si/citation-report/poster/toc` | 保留黑名单；13 SI 建议同 -145 移 `rejected/` |
| **C. 错文（维持拒）** | **11** | `content-title-mismatch(<50)` 或 `url-doi-conflict` | 保留黑名单；cctc 需从 PENDING 改判 confirmed_bad |
| **D. 待人核（uncertain）** | **65** | `partial-title-overlap`(50~69) / `scanned` / `no-expected-title` | -147 逐条人核；见 §四优先级 |

---

## 二、A 档 · 真正文候选（可翻，直接给 -147 白名单）

**A1 · 强正 5 条（`expected-doi-present`，期望 DOI 印在正文/URL + 非 SI，高置信真正文）**：

| DOI | 桶 | 页 | 源 | 备注 |
|---|---|---:|---|---|
| `10.1116/1.5053761` | aip | 14 | crossref | CO2(g) near-ambient XPS |
| `10.1016/j.jcou.2022.102356` | elsevier | 6 | unpaywall（DOI-keyed 净源） | Spinel ferrite RWGS |
| `10.1016/j.jechem.2020.06.007` | elsevier | 9 | websearch（DOI 已在正文核实） | Ni/N-CNT CO2 甲烷化 |
| `10.1016/s1872-2067(17)62899-7` | elsevier | 9 | openaire | **qc_kind=hard 误杀**（硬黑名单也翻），高价值 |
| `10.1002/anie.201406637` | wiley | 4 | semantic_scholar | ANIE communication（4 页属正常） |

**A2 · 高概率 1 条（标题 100 + DOI-keyed 源，但 DOI 未印在首 2 页 → 人核）**：

| DOI | 桶 | 页 | 源 | 备注 |
|---|---|---:|---|---|
| `10.1016/j.apcatb.2021.119925` | elsevier | 33 | **openalex（DOI-keyed 净源，L 节 0 假阳）** | 标题分 100；openalex 天然不错配 → 疑旧 union 黑名单误杀（同 -145 翻正 4 ACS 的模式） |

> 清单文件（可直接喂 `build_coverage --qc-allow`，**-147 人核后**）：见 `out/_t0_prescreen_99_148.csv` 中 `label=FLIP` 6 行（cctc 已剔，见 §三）。

---

## 三、C 档 · 错文 11 条（维持拒；含 1 条从 A 档纠正）

| DOI | 桶 | 判据 | 真身/佐证 |
|---|---|---|---|
| `10.1002/cctc.200900261` | wiley | **本文从 FLIP 纠正为错文** | 文内 DOI=`10.3762/bjoc.7.159`（Beilstein 同题他刊，M.1④已实锤）；生产门**漏判**——Beilstein 前缀 `10.3762` 不在门② `_QC_PREFIX_LABELS`，标题又 100% 同题 → 假 match（见 §五 门加固） |
| `10.1021/acscatal.6b00397` | acs | url-doi-conflict | 文内 `10.1016/j.xcrp...`（elsevier≠acs） |
| `10.1039/d5gc03584h` | rsc | url-doi-conflict | 文内 `10.1016/j.cej...`（elsevier≠rsc） |
| `10.3390/catal15111028` | mdpi | url-doi-conflict | 文内 `10.1038/s41929...`（nature≠mdpi） |
| `10.1016/j.jechem.2025.06.073` | elsevier | title-mismatch(<50) | 文内 `10.1016/j.jechem.2021.10.013`（同刊他文） |
| `10.1021/acs.energyfuels.4c02020` | acs | title-mismatch(<50) | — |
| `10.1021/acscatal.4c07685` | acs | title-mismatch(<50) | — |
| `10.1021/acssuschemeng.5c10863` | acs | title-mismatch(<50) | — |
| `10.1039/c0gc00516a` | rsc | title-mismatch(<50) | — |
| `10.1107/s0108768194013327` | other(IUCr) | title-mismatch(<50) | 文内 iForest（林学，跨领域） |
| `10.3390/catal10070741` | mdpi | title-mismatch(<50) | — |

---

## 四、B 档 SI 17 + D 档待核 65（给 -147 的优先级）

### 4.1 B 档 · SI/非正文 17（维持拒，勿翻）
- **SI 13**（全 `publisher_oa:acs-authorchoice`，印正确标题+DOI 却是补充材料 → 门④ `non-article-si` 命中，坐实 O.3/O.1 「ACS `/doi/pdf/` ≈93% SI」）：`acs.jpcc.8b12085` `acsami.0c11576` `acsami.5c25106` `acsami.8b05411` `acscatal.1c05582` `acscatal.5b01044` `acscatal.5c02307` `acscatal.8b04821` `acsanm.1c00959` `acscatal.4c04824` `acscatal.8b02371` `nl401568x` `acscatal.0c01253`。
- **citation-report 2**：`j.jcou.2017.08.019`、`acs.chemrev.7b00776`（242 页引用报告）。
- **poster 1**：`j.jcou.2018.01.028`（1 页）。 **TOC 1**：`j.joei.2025.102331`（3 页目录）。
> 这 13 SI 与 -145 的 51 SI 同源同理，建议一并 `qc_move_rejected` 物理隔离（目录卫生，不影响 coverage 口径）。

### 4.2 D 档 · 待核 65（-147 逐条，按翻案概率排序）
- **D1 · 先跳过（~12 条，文内 DOI 指向他文/未来年，疑错文，翻案率低）**：`aenm.201600501`(→japc.2026) `j.joei.2026.102449`(→stemcr) `j.ijhydene.2011.02.133`(→ijhydene.2021) `s1872-5813(12)60002-4`(→cpe-2013) `j.ijhydene.2023.01.102`(→ijhydene.2026) `j.ces.2020.115803`(→ijpest) `s10563-014-9179-6`(→preprint/s41467-026) `j.renene.2013.10.002`(→es) `cr2000114`(→ijee.2024) `d3ee02589f`(→sct) `science.1192449`(→science.aah4321) `1521-4095(200110)13:20`(→jmsr)。
- **D2 · 扫描件 4 条（抽不出正文，须开卷/按域判）**：`d1cy00550b` `d2se01512a` `jnn.2017.12725`(1 页) `1.1647050`。
- **D3 · 真·边界 ~49 条**（`partial-title-overlap` 50~69、无冲突文内 DOI）：翻案主要来自此档，经验命中率 ~10~15% → 预期 +5~7。分数≥67 的偏正样本优先看：`j.ijhydene.2024.01.188`(67.3) `s1002-0721(12)60305-6`(69.1) `htj.22453`(69.4) `d0gc02302g`(69.4) `cr2000114`(69.6，但 D1) `s41565-020-00799-8`(68.5) `cs400132a`(68.4) `science.1192449`(67.4，但 D1) `s1566-7367(03)00110-9`(66.7) `j.ijhydene.2013.11.089`(66.7)。

> 全部 65 条逐条 `score/reason/na_reason/intext_other_doi/exp_title` 见 `out/_t0_prescreen_99_148.csv`（`label=UNCERTAIN`）。

---

## 五、门加固发现（给门属主 -140/-161，非本岗改码）

预筛复用生产门时暴露 3 个可低成本收敛的漏口（均有本波实锤，回归可加断言）：

1. **同题他刊 + 未知出版商前缀 → 门② 漏判**（cctc.200900261 实锤）：`expected-doi-present=False` + 标题 100% 同题，而文内真身 DOI 前缀（Beilstein `10.3762`、Hans `10.12677`、CCSE `10.5539`…）**不在 `_QC_PREFIX_LABELS`** → 门② 的 `header-doi-cross-publisher` 不触发 → 假 match。**修法二选一**：① 扩 `_QC_PREFIX_LABELS`（补 10.3762/10.12677/10.5539/10.30919/10.5829/10.69997/10.34343/10.2478/10.21203…）；② **规则：`title-match` 但 `expected-doi-present=False` 且正文/URL 含任一「异于期望」的完整 DOI → 从 match 降级为 uncertain（并集门更严）**。②更稳、覆盖未来未知社。
2. **未来年份未做硬门**（L.2④）：D1 多条文内 DOI 年份 > 目标 DOI 年份（2026 配旧文，物理不可能）。当前仅作 `intext_other_doi` 呈现，未硬拒；可加 `served_year > target_year → mismatch`。
3. **门④ SI 判识已验证有效**：8 条 batch6 `acs-authorchoice` SI（印正确标题+DOI）全被 `non-article-si` 正确命中 → O.3 修复在生产门生效，非回归。

---

## 六、待办 / 依赖（交接）

- [ ] **-147 终裁（关键）**：以本清单为输入跑 `regress_qc_union_189` + 人核；A 档 6 条确认后入 `--qc-allow`、C 档 11 条确认 confirmed_bad（尤其 cctc 从 PENDING 改判）、D 档按 §4.2 优先级人核。**-147 现 offline**（已 send_to_session 入队）。
- [ ] **coverage 回写**（-151/-140）：A 档确认后 `build_coverage --qc-allow`；确认 +5 → 379→384（38.4%），现实 +12 → 391（39.1%）。**本岗不回写**（纯读预筛）。
- [ ] **门加固**（-140/-161）：§五 三项，改后开 `RUN_DATA_REGRESS=1` 跑 `regress_qc_union_189` 防退化。
- [ ] **目录卫生**（cleanup）：§4.1 的 13 SI 建议 `qc_move_rejected` 隔离。

---

*核验 2026-07-02｜信息检索-专家智库 · -148｜纯读预筛、复用生产门（O.5）、未改核心 `.py`/未回写 coverage/未跑网络｜证据 `out/_t0_prescreen_99_148.csv`（99 逐条）+ `_t0_prescreen_99_148.py`（一次性审计脚本）｜承 -142/-140（129 待裁池）、-145（ACS 逐页 SI）、-151（候选 CSV）；终裁交 -147｜已同步总指挥 148。*
