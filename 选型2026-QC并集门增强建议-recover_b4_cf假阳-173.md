# 选型2026 · QC 并集门增强建议（recover_b4_cf 假阳模式）

> 交付：**信息检索-专家智库 · -173**｜taskId=`task-e2535a16`｜2026-07-02  
> 触发：总指挥 144 直派——强化 145 本轮 CF 重跑所依赖的内容 QC 门；重点收 **SI / poster / citation-report / 目录页** 等同社同 DOI 但**非正文**假阳。  
> 边界：**只新建本 1 份建议 md，不改 `.py`**（实现交 **161** / `download.py` `_content_qc_*` 组）。  
> 权威口径：**净覆盖 371/999 ≈ 37.1%**，**still_missing ≈ 630**（142 M 节复核后；勿再用 448/551 旧值）。

---

## 〇、TL;DR（给 144 / 145 / 140）

| 优先级 | 增强项 | 拦什么 | 实现量 | 145 CF 重跑依赖 |
|:--:|---|---|:---:|:---:|
| **P0** | **门③ 文内 DOI 反证** | 标题+期望 DOI 都在首页，但**正文首部另有一个完整 DOI ≠ 期望**（同题他刊双发） | ~20 行 | ✅ 必做 |
| **P0** | **门④ SI 附件判识** | `publisher_oa:acs-authorchoice` 等落盘 **Supporting Information** 非正文 | ~25 行 | ✅ 必做（recover_b4_cf 5/5 SI） |
| **P0** | **门⑤ 非正文版式** | citation-report / poster / 目录页(index) | ~40 行 | ✅ 必做 |
| **P1** | **垃圾域黑名单** | `exaly.com` 等 citation-report 域 | ~10 行 | 建议 |
| **P1** | **页数启发式** | 1 页 + poster 关键词 | ~15 行 | 建议 |

**一句话**：现有并集门（门①标题 + 门②跨社 URL/嵌入 DOI）**对 recover_b4_cf 自动 match 的 13 条零免疫**——13 条人工开卷仅 **5 条真全文**；补门③–⑤ 后预期把该目录假阳压到 **≤1 条 uncertain**。

---

## 一、问题背景（recover_b4_cf 实锤）

来源：`经验记录-踩坑与发现.md` **M 节**（142 深核 `out/recover_b4_cf_qc.md` v2）。

| 指标 | 数值 |
|---|---|
| full-80 processed | 73 |
| summary success | 27（37%） |
| **人工 QC 后真全文** | **5**（smoke10 +2） |
| **真净增益率** | **≈4%**（3/73） |
| flaresolverr_recovered 真救 CF | **0** |

**根因**：`_content_qc_gate` 现有逻辑在下列场景仍 **match / 放行**：

1. PDF 首页印着**正确标题 + 正确 DOI**（citation-report）→ 触发 `expected-doi-present` 短路  
2. PDF 是**同题 SI**，metadata/首页含母文标题 → 标题分高  
3. **同作者同题他刊双发** → 标题 100% match，文内 DOI 是**他刊**但期望 DOI 也可能出现在 citation 区  
4. **1 页 poster** → 标题 match，非全文  

这与 L/M 节 websearch 假阳**不同病**：后者是「完全另一篇」；这里是「**像这篇、但不是正文 PDF**」。

---

## 二、现有 `_content_qc_gate` 能力边界（已读 `download.py`）

| 已有 | 行为 | 缺口 |
|---|---|---|
| 门① 标题分 < mismatch_lo | mismatch | citation-report **标题对** → 不触发 |
| 门② URL 异 DOI / 跨社 host / 首部异社 DOI | mismatch | **同社 SI**、**同社 citation-report** 不触发 |
| `expected-doi-present` 强正 | **直接 match** | citation-report **首页含期望 DOI** → **误放行** |
| DOI-keyed 源豁免 | 不 QC | 正确；但 **publisher_oa:acs-authorchoice** 虽 DOI 构造仍可能下到 SI URL |
| uncertain | 放行 + 标 `qc_uncertain` | poster/scanned 仍可能 match 后不进 uncertain |

**结论**：需在 **`expected-doi-present` 短路之前或之后** 增加 **「非正文版式」硬拒**，并增加 **「文内 DOI 反证」** 独立于标题分。

---

## 三、四类假阳模式 × 建议闸门（实现规格）

### 3.1 门③ · 文内 DOI 反证（P0）

**模式 M.1④ same_title_other_journal**  
实例：期望 `10.1002/cctc.200900261`(ChemCatChem)，落盘 Beilstein `10.3762/bjoc.7.159`，标题完全一致。

**规则**（在 `_content_qc_verdict` 内，**紧接** `expected-doi-present` 判定之后、标题分之前）：

```
在正文 meta + 前 2000 字内找所有完整 DOI（复用 _QC_DOI_RE）
若存在任一 norm(doi) != norm(exp_doi) 且该 DOI 是「完整 suffix」（非仅前缀片段）
  → mismatch, reason=body-embeds-different-doi:<found>
```

**注意**：

- 参考文献区噪声：仍用 **前 2000 字**（与门② 1200 可统一为 2000）  
- 期望 DOI 在首页出现 **不能** 单独压过反证——若 **另有一个更 prominent 的文内 DOI**（如 meta `/doi/` 或首页大号 DOI）≠ 期望 → 拒  
- **可选加强**：解析 PDF metadata 的 `/doi` 字段，若 ≠ exp_doi → 硬拒（pypdf `metadata.get('/doi')`）

**selftest 负样本**：M 节 `10.1002/cctc.200900261` → Beilstein PDF fixture。

---

### 3.2 门④ · SI（Supporting Information）判识（P0）

**模式 M.1③ si_only**  
recover_b4_cf 内 **publisher_oa:acs-authorchoice 5/5 全部为 SI**；URL 形如 `pubs.acs.org/doi/pdf/...` 却服务 SI 文件。

**规则**（在 `%PDF` 校验通过后、记 success 前；可与 `_content_qc_verdict` 并列函数 `_content_qc_non_article_reject`）：

```
首 2 页文本（或前 3000 字符）命中任一 → mismatch:
  - 行首/页首匹配 (?i)^\s*S-\d+\s*[\.\)]  或  "Supporting Information"
  - 且 未 命中 (?i)(abstract|introduction|results and discussion)\b  （排除真文含 SI 附录的极少数）
  - 或 URL/path 含 /suppl/ /supporting /_si_ /si_001
```

**publisher_oa:acs-authorchoice 特判（P0）**：

```
若 source 含 acs-authorchoice 且 pdf_url 含 /doi/pdf/ 但正文以 S-1 开头
  → 强制 mismatch, reason=si-not-main-text
```

**正例放行**：正文 PDF 末尾含 SI 章节 **不应** 误杀——要求 **S-1 在首页前 500 字** 且 **无 Abstract**。

**selftest**：M 节五条 ACS SI DOI（acscatal.4c04824 等）。

---

### 3.3 门⑤ · 非正文版式（citation-report / poster / 目录页）（P0）

#### A. citation-report（P0）

```
URL host 命中黑名单: exaly.com, (可扩展 semanticscholar.org/citations)
  或 路径含 /citation-report
  或 首页前 1500 字同时含:
      (?i)cited by|references cited|citation report
      且 不含 (?i)^abstract\b
→ mismatch, reason=non-article-citation-report
```

**黑名单域（P1 登记）**：`exaly.com`（M 节实锤 2 条：chemrev.7b00776、jcou.2017.08.019）。

#### B. poster（P0/P1）

```
pypdf 页数 == 1
且 (
  meta_title 含 (?i)poster
  或 首页含 (?i)poster session|conference poster|poster template
)
→ mismatch, reason=non-article-poster
```

实例：`10.1016/j.jcou.2018.01.028`（Zenodo 海报）。

#### C. 目录页 / index（P0，145 依赖）

```
首页前 1000 字命中 (?i)(table of contents|contents|index to volume|author index)
且 无 abstract
且 页数 <= 3
→ mismatch, reason=non-article-index-or-toc
```

**动机**：websearch 常抓到期刊 **卷期目录 PDF**（含多个 DOI 列表），标题分可能撞某篇子标题。

---

### 3.4 调整 `expected-doi-present` 短路（P0）

**现状问题**：citation-report 首页印期望 DOI → 直接 `match`。

**建议**：

```python
# 伪代码：在判定 expected-doi-present 之前先跑 _content_qc_non_article_reject
rej = _content_qc_non_article_reject(data, url, source, ...)
if rej:
    return mismatch, ..., rej

# 然后再做 expected-doi-present / 门①②
```

即：**非正文版式硬拒优先于 DOI 强正**。

---

## 四、与现有并集门的关系（勿回退交集）

| 门 | 关系 |
|---|---|
| 门① 标题 | 保留 |
| 门② URL/跨社 | 保留 |
| **门③ 文内 DOI 反证** | **新增**，与门② 互补（同社他刊） |
| **门④ SI** | **新增**，专堵 publisher_oa SI |
| **门⑤ 版式** | **新增**，专堵「像这篇但不是文」 |

**仍用 union**：任一命中 → mismatch。**禁止**改回交集。

---

## 五、实现落点（给 140）

| 函数 | 文件 | 说明 |
|---|---|---|
| `_content_qc_non_article_reject()` | `download.py` | 门④⑤ + 域黑名单；返回 `(reject: bool, reason)` |
| `_content_qc_verdict()` | 同上 | 插入门③；调整短路顺序 |
| `_source_needs_content_qc()` | 同上 | **建议**：`publisher_oa:acs-authorchoice` 即使 DOI-keyed 构造也 **强制 QC**（SI 风险；recover_b4_cf 5/5 全 SI） |
| selftest | `download.py` + `run_all_selftests.py` | 每模式 ≥1 负样本 fixture |
| 数据回归 | `tools/regress_qc_union_189.py` | 扩展 recover_b4_cf 8 假 match 为 **必拒 8/8** |

**配置开关**：`cfg.content_qc_non_article=True`（默认开）；与 `cfg.content_qc` 并列，可单独回退。

---

## 六、145 CF 重跑前检查清单

145 开 `--use-flaresolverr` 或 CF 回收批前，确认：

- [ ] 门③–⑤ 已合并 + selftest 绿  
- [ ] `exaly.com` 入 URL 黑名单或门⑤  
- [ ] ACS-authorchoice SI 特判启用  
- [ ] `attempts.jsonl` 可见 `content_qc` 事件 `verdict=mismatch` + `reason=si-not-main-text` 等  
- [ ] 负样本回归：`recover_b4_cf` 8 条原假 match **全部拒收**  

**未做上述增强前**：FS 会「成功」下载 citation-report / SI / 错刊——**success 率虚高、净覆盖口径再被污染**。

---

## 七、预期收益（保守）

| 范围 | 效果 |
|---|---|
| recover_b4_cf 目录 | 13 自动 match → **≤5 真全文**，其余变 mismatch |
| 全局 still_missing 630 | 不直接增覆盖；**防止 CF 重跑假阳回灌** |
| 净覆盖 371/999 | 稳态 **不被假阳抬高**；cleanup 后可微降（更诚实） |

---

## 附录 A · recover_b4_cf full-80 的 12 条 mismatch 模式清单

来源：`out/recover_b4_cf_qc.md` 逐条表 + 142 v2 深核（人工开卷 13 条 auto-match 仅 5 条真全文）。

| DOI | score | 来源 | PDF 实际片段 | 模式标签 | 门③–⑤ 哪条应拦 |
|---|---:|---|---|---|---|
| 10.1002/aic.690481123 | 5.6 | websearch | Heriot-Watt Research Gateway… | 完全他题 | 门① |
| 10.1002/ange.202203836 | 45.6 | websearch | SrTiO3 photocatalytic panels… | 完全他题 | 门① |
| 10.1016/j.carbon.2018.01.015 | 38.6 | websearch | Small molecule transcription-replication… | 完全他题 | 门① |
| 10.1016/j.jechem.2025.06.073 | 49.8 | websearch | electrocatalytic oxygen reduction… | 完全他题(边界带) | 门① |
| 10.1016/j.joei.2025.102331 | 30.7 | websearch | Aug 2025 Issue of the JOE | **期刊目录/index** | **门⑤C** |
| 10.1021/acs.energyfuels.4c02020 | 48.2 | websearch | Ethanol via eCO2R… | 完全他题 | 门① |
| 10.1021/acscatal.4c07685 | 46.0 | websearch | Facet-Dependent Cu eCO2R… | 同社他篇 | 门②/门① |
| 10.1021/acssuschemeng.5c10863 | 37.9 | websearch | Ethylene oligomerization COF… | 完全他题 | 门① |
| 10.1039/c0gc00516a | 25.3 | websearch | Dielectric TDS-SMD MLCC specs | **非论文(规格书)** | 门⑤ + 页数 |
| 10.1107/s0108768194013327 | 34.1 | websearch | Dawalibi V, Monteverdi MC…(他文引文) | 完全他题 | 门① |
| 10.1116/1.5053761 | 25.9 | websearch | Content Platform User Guide TOC | **目录/手册** | **门⑤C** |
| 10.3390/catal10070741 | 35.0 | websearch | CeO2 photocatalytic H2… | 完全他题 | 门① |

**另：13 条 auto-match 中 8 条假命中（142 深核）——现有门①② + `expected-doi-present` 全漏：**

| DOI | 假阳模式 | 门 |
|---|---|---|
| 10.1021/acs.chemrev.7b00776 | exaly.com citation-report | 门⑤A + 域黑名单 |
| 10.1016/j.jcou.2017.08.019 | exaly.com citation-report | 门⑤A |
| 10.1016/j.jcou.2018.01.028 | Zenodo 1 页 poster | 门⑤B |
| 10.1002/cctc.200900261 | 同题 Beilstein 他刊双发 | **门③** |
| 10.1021/acsanm.1c00959 | ACS SI-only | **门④** |
| 10.1021/acscatal.4c04824 | ACS SI-only | **门④** |
| 10.1021/acscatal.8b02371 | ACS SI-only | **门④** |
| 10.1021/nl401568x | ACS SI-only | **门④** |

**难例（任务点名）**：`10.1021/acscatal.0c01253`（smoke10，`publisher_oa:acs-authorchoice`，score 21.4，首页 "Supporting Information"）——标题分已 mismatch，但若走 DOI-keyed 豁免或 `expected-doi-present` 短路仍会漏；**门④ + acs-authorchoice 强制 QC** 必拦。

---

## 附录 B · selftest 构造思路（给 161，每模式 ≥1 负样本）

| 模式 | mock PDF 首 2 页文本 fixture | 期望 verdict | reason 前缀 |
|---|---|---|---|
| 门③ 同题他刊 | 标题=期望标题 + 正文 DOI `10.3762/bjoc.7.159` | mismatch | `body-embeds-different-doi` |
| 门④ SI | `S-1\nSupporting Information\n…` 无 Abstract | mismatch | `si-not-main-text` |
| 门④ acs-authorchoice | source=`publisher_oa:acs-authorchoice` + 上 fixture | mismatch | `si-not-main-text` |
| 门⑤ citation-report | `Cited by … citation report` + 期望 DOI 在首页 | mismatch | `non-article-citation-report` |
| 门⑤ poster | 1 页 + `POSTER SESSION` + meta title 含 poster | mismatch | `non-article-poster` |
| 门⑤ TOC | `Table of Contents` + 3 页 + 无 abstract | mismatch | `non-article-index-or-toc` |
| 正例放行 | 8 页正文 + Abstract + Introduction | match | `title-match` |
| 正例 SI 附录 | 正文 6 页 + 末页 Supporting Information | match | 不误杀 |

回归集：`tools/regress_qc_union_189.py` 扩展 recover_b4_cf **8 假 match + 12 mismatch 中 active 未隔离项** → 并集门 **必拒 ≥18/20**。

---

## 八、证据索引

- `经验记录-踩坑与发现.md` **M 节**（四类模式 + 5/73 真全文）  
- `fulltext_fetcher/download.py` `_content_qc_gate` / `_content_qc_verdict` / `_qc_doi_publisher_conflict`  
- `回收实测结论-CF与免费路线到顶.md` §〇补（FS 成功 ≠ 正确全文）  
- `检索成果-still_missing-CF-JA3桶ROI深挖-173.md`（CF 回收须联 QC）  

---

*核验 2026-07-02｜智库 -173（-140 复核补附录）｜task-e2535a16 交付：`选型2026-QC并集门增强建议-recover_b4_cf假阳-173.md` — 门③–⑤ + 附录 A/B，待 **161** 实现、145 CF 重跑前启用。*

---

## 九、142 独立复核 + 落地增补（2026-07-02｜task-e2535a16 改派复核）

> 142 对本文件门③–⑤ 逐条回核 `fulltext_fetcher/download.py`（`_content_qc_gate` / `_content_qc_verdict` / `_qc_doi_publisher_conflict` / `_extract_pdf_text_meta` / `_source_needs_content_qc`）与 `out/recover_b4_cf_qc.md` 数据。**结论：方向与优先级(门③–⑤ + acs-authorchoice 强制 QC)全部成立**。以下 8 处是把它"能直接落到 161 代码"的精修/补强与勘误，纯读、未改任何 `.py`。

### 9.1 复核核验表（门 × 源码/数据佐证）

| 门 | 173 建议 | 142 回核源码/数据 | 结论 |
|---|---|---|---|
| 门① 标题<50 | 保留 | `_content_qc_verdict` 门①已实现；recover_b4_cf 12 条 mismatch 分数(5.6/45.6/38.6/49.8/30.7/48.2/46.0/37.9/25.3/34.1/25.9/35.0)**全 <50** | ✅ 属实 |
| 门② 跨社 URL/DOI | 保留 | `_qc_doi_publisher_conflict` (a)URL异DOI /(b)首部异社DOI /(c)host跨社 已实现；**(b)(c) 需出版商"已知"**（在 `_QC_PREFIX_LABELS`/`_QC_HOST_LABELS`） | ✅ 有盲区（见 9.4） |
| 门③ 文内异 DOI | 新增 | (b) 对 Beilstein `10.3762` **不在** `_QC_PREFIX_LABELS` → 不触发 → cctc.200900261 漏 | ✅ 必做 |
| 门④ SI 判识 + acs-authorchoice 强制 QC | 新增 | `acs-authorchoice` **不在** `_QC_GATE_SOURCE_MARKERS=("websearch","wayback","browser_search","landing")` → 现被**整源豁免** | ✅ 必做（见 9.2） |
| 门⑤ 非正文版式 | 新增 | poster 需页数，但 `_extract_pdf_text_meta` **只回 (meta_title, text)、不回页数** | ✅ 必做 + 接口补（见 9.5） |

### 9.2 根因精修：0c01253 漏网 = **DOI-keyed 整源豁免**，不是"双信号门放过"

任务点名的难例 `10.1021/acscatal.0c01253`：`source_used=publisher_oa:acs-authorchoice`（见 `recover_b4_cf_qc.md` 第 33 行）。该 source 不含任何 `_QC_GATE_SOURCE_MARKERS`，故 `_source_needs_content_qc()` 返回 **False**，`_content_qc_gate` 在**第一行就 return None**——**门根本没跑**。它的 score 21.4 是 `qc_content_match.py` 事后离线判的，并非实时门看到的。

- **精确结论**：现有"URL-DOI 双信号门"**没机会放过**它——是**整源豁免**让它直接落盘。若强制进门，凭 21.4<50 门①即可拒。
- **两段式修复**（比 §五 更精确）：① 在 `_source_needs_content_qc` 对 `acs-authorchoice`（乃至所有 `publisher_oa:*` 但 URL 落到 `/doi/pdf/` 者）**强制进 QC**；② 进门后 SI 首页常印**母文 DOI**，会触发 `expected-doi-present` 短路→match，故门④必须**先于** DOI 强正（见 9.6）。仅做①不做②仍漏。

### 9.3 目标澄清 + 运维铁律：门③④⑤ 真正收的是 **8 条 auto-match**；且**运行时无 pypdf → 门是 no-op**

**勘误附录 A**：附录 A 把 `joei.2025.102331`(30.7)、`c0gc00516a`(25.3)、`5053761`(25.9) 等标给"门⑤C"，但它们分数 **<50、门① 在 verdict 层已判 mismatch**——不需门⑤。**门③④⑤ 的净目标是逃逸的 8 条 auto-match**（高标题分 or DOI 命中：SI×4/citation-report×2/poster×1/同题他刊×1）。门⑤ 的价值**仅在标题分高的非正文**（poster/citation-report/SI 带母文标题），低分非正文门①已收。

**为何 12 条 mismatch 仍 active/success？**（重要运维根因，本文件此前未点出）
`_extract_pdf_text_meta` 依赖 pypdf；缺库/抽取失败 → 返回 `(None, None)` → `is_unextractable(None)=True` → verdict 走 `scanned → uncertain` → **`_content_qc_gate` 返回 None（放行）**。即：

> **运行时无 pypdf（或正文抽不出），整个内容 QC 门静默变成 no-op，门①②③④⑤ 全部失效、100% 放行。** recover_b4_cf 10 条本该被门①拒的 mismatch 落盘为 active，最可能即此（run 时 pypdf 缺位/抽取空）。

**建议（P0，先于任何门增强）**：① 145 CF 重跑环境**确保装 pypdf**；② 当 `%PDF`+`pdf_defect` 已过、但 `_extract_pdf_text_meta` 抽出空文本时，`_emit_event(content_qc, verdict="qc_blind", reason="empty-text/no-pypdf")`，把"盲放行"写进 `attempts.jsonl`，区分**真扫描件** vs **缺库致盲**；③ 可选：`_qc_matchers()` 成功但 `_pdf_reader() is None` 时 `log.info("QC degraded: no pypdf")`。

### 9.4 补强门②/门③：PDF **元数据 DOI**（XMP/Info）反证（扩展 §3.1 的"可选加强"）

§3.1 已提 `metadata.get('/doi')`；142 建议扩为**独立强证信号**并补 XMP：

- 读 `reader.metadata`（Info 字典）**与** `reader.xmp_metadata`（`prism:doi` / `dc:identifier` / `pdfx:doi`）；ACS/Wiley/Elsevier 正式 PDF 普遍内嵌 article DOI。
- 规则：**元数据里存在 DOI 且 `norm(meta_doi) != norm(exp_doi)` → mismatch, reason=`meta-doi-mismatch`**。这是**出版商无关**的（任何异完整 DOI 即错），正好补门②(b)(c) 的"须已知出版商"盲区——Beilstein `10.3762` 这类未登记前缀也能拦。
- **关键不误杀**：`meta_doi == exp_doi` **不能**证明是正文——**ACS SI 的元数据也带母文 DOI**！故元数据 DOI 命中**不得**当作"放行/门④豁免"，门④(SI 文本判识)须**独立保留**。

### 9.5 接口变更提示给 161（门⑤/门④ 的落点契约）

1. **`_extract_pdf_text_meta` 需回传页数**：现签名 `-> (meta_title, text)`；门⑤ poster(页数==1)/TOC(页数<=3) 需要它。建议扩为 `-> (meta_title, text, page_count)` 或加姊妹函数 `_pdf_page_count(data)`；沿用**延迟 pypdf + 缺库降级**纪律（page_count=None 时门⑤跳过页数子判、不误杀）。
2. **抽取窗口无需扩大**：`S-1`/`Supporting Information`/`POSTER`/`Table of Contents`/citation-report 标记**均在首 1–2 页**出现，现 `max_pages=2, max_chars=6000` 足够；勿为此加大窗口（避免性能/内存回归）。
3. **复用已抽文本**：新增 `_content_qc_non_article_reject(url, source, meta_title, text, page_count)` 应在 `_content_qc_gate` 内、**`_content_qc_verdict` 之前**调用，复用同一次抽取，**不重复解析 PDF**。
4. **开关**：`cfg.content_qc_non_article`（默认 True），与 `cfg.content_qc` 并列、可单独回退（与 §五一致）。

### 9.6 统一判定顺序（整合版；消除 §3.1"紧接 expected-doi-present 之后" 与 §3.4"硬拒先于 DOI 强正"的顺序歧义）

**铁律：SI / citation-report / 同题他刊 三类都可能在首页印期望 DOI**，故"非正文硬拒 + 异 DOI 反证"必须**全部先于** `expected-doi-present` 短路：

```
# _content_qc_gate 内，%PDF + pdf_defect 通过后：
meta_title, text, npages = _extract_pdf_text_meta(data)   # 扩展回传页数(9.5)

# ── 第0步(新)·非正文版式硬拒 —— 必须先于 DOI 强正 / 标题命中 ──
#   门④ SI:  首页前~500字含 (行首 S-\d | "supporting information") 且 无 (abstract|introduction|results and discussion)
#   门⑤A citation-report: host∈黑名单{exaly.com,…} 或 含 (citation report|cited by|references cited) 且无 abstract
#   门⑤B poster: npages==1 且 (meta_title|首页 含 poster|poster session|poster template)
#   门⑤C TOC/手册: npages<=3 且首页含 (table of contents|issue of the|user guide|author index) 且无 abstract
if _content_qc_non_article_reject(...): return mismatch

# ── 第0.5步(新)·异 DOI 反证(门③ + 9.4) —— 也先于 expected-doi-present ──
if meta_doi and norm(meta_doi)!=norm(exp_doi):           return mismatch  # meta-doi-mismatch(最干净)
if 首(meta_title+text[:500]) 含 完整DOI d 且 norm(d)!=norm(exp_doi): return mismatch  # body-embeds-different-doi
#   注:body 异 DOI 只认"首500字/与标题同处"，参考文献区(500字后)不反证 → 不误杀正常引文

# ── 既有链(此时已排除 SI/citation/他刊)──
# expected-doi-present → match; 门① 标题<50 → mismatch; 门② 跨社 → mismatch; 标题>=70 → match; 余 uncertain
```

### 9.7 selftest 具体 fixture（补附录 B：给出可直接照抄的首2页文本 + 期望）

| # | mock (meta_title, 首2页text, npages, url, source) | 期望 verdict / reason |
|---|---|---|
| 门④ SI | ("Supporting Information", "S-1 Supporting Information for <期望标题> Figure S1 …", 16, ".../doi/pdf/10.1021/x", **"websearch"**) | mismatch / `si-not-main-text` |
| 门④ 源豁免回归 | 同上但 source=**"publisher_oa:acs-authorchoice"** | mismatch（证明 9.2 强制 QC 生效，不再豁免） |
| 门③/9.4 同题他刊 | ("<期望标题>", "<期望标题> … doi 10.3762/bjoc.7.159 …", 8, "…beilstein…", "websearch")，meta_doi="10.3762/bjoc.7.159" | mismatch / `meta-doi-mismatch`（或 `body-embeds-different-doi`） |
| 门⑤A citation | ("Citation report", "<期望标题> Cited by 42 References cited … doi:<**期望DOI**>", 242, "https://exaly.com/…citation-report.pdf", "websearch") | mismatch / `non-article-citation-report`（**须先于** expected-doi-present） |
| 门⑤B poster | ("Free research poster template", "POSTER ICheap Napoli <期望标题>", 1, "https://zenodo.org/…", "websearch") | mismatch / `non-article-poster` |
| 门⑤C TOC | ("", "Table of Contents Volume 5 …", 2, "…", "websearch") | mismatch / `non-article-index-or-toc` |
| 不误杀① 真全文 | ("<期望标题>", "<期望标题> Abstract … Introduction …", 12, "…", "websearch") | match / `title-match` |
| 不误杀② 正文含 SI 章节 | ("<期望标题>", "<期望标题> Abstract … (6 页后) Supporting Information", 8, …) | match（S-1 不在首500字且有 Abstract → 门④不触发） |
| 不误杀③ 正文引他文 DOI | ("<期望标题>", "<期望标题> Abstract … [12] … 10.1038/xxx", 10, …) | match（异 DOI 在参考文献区/500字后 → 不反证） |
| 不误杀④ 缺 pypdf 降级 | monkeypatch `_pdf_reader→None`，任意输入 | 放行（门 no-op；且应记 `qc_blind` 事件，见 9.3） |

回归集：并入 `tools/regress_qc_union_189.py`，把 recover_b4_cf **8 条 auto-match 假阳 → 必拒 8/8**，并加**不误杀 4 例 → 必放 4/4**（防门③④⑤ 过判）。

### 9.8 与 161 的接口对齐（协同动作）

**已识别真依赖**（下游 161 消费我的规格 + 需锁定函数契约）：门③④⑤ 落点在 161 的 `download.py` `_content_qc_*` 组；`_extract_pdf_text_meta` 回传页数(9.5)；`_source_needs_content_qc` 对 `acs-authorchoice` 特判(9.2)；判定顺序(9.6)。按协同规则，已 `send_to_session` 向 161 对齐上述接口/顺序/命名；若 161 不在线则在 `report_task` 点名请 144 排期/改派。

### 9.9 落地实测回灌（147 end-to-end 复跑）+ 门④⑤ 去「源门耦合」精修

147 用**已并发落地的真门** end-to-end 复跑（`_tmp_verify_gate_live_147.py`，另见 `验证-门③④⑤拦截率-recover_b4_cf-147.md`）实测：

- `hard_reject=True` 下门④⑤ 拒 **8/9** auto-match（SI×5 门④ / citation-report×2 门⑤A / poster×1 门⑤B **全收**），真全文**误杀 0/5**（`has_body` 护栏生效）。**验证了门④⑤ + §9.6 排序 + §9.2 强制 QC 的有效性与不误杀性。**
- 剩 1 条 `cctc.200900261`（同题 Beilstein）仍逃逸：实测 §3.1 的 body 首 500 字口径**也抓不到**（`10.3762/bjoc.7.159` 不在首 500 字）→ **确认门③ 首选实现 = §9.4 `meta-doi-mismatch`（读 XMP/Info `/doi` + `prism:doi`/`dc:identifier`）**。注意 `meta_doi==exp` **不能**当"是正文"证据（SI 也带母文 DOI），**仅 `meta_doi!=exp` 时硬拒**。
- `1.5053761`（crossref）与 acs-authorchoice **同属整源豁免逃逸**：门⑤C/门④ 逻辑本能收，但源不进门。

**精修（优于 §9.2 的"逐源特判"）**：门④⑤（SI/citation/poster/TOC）是**内容内在**判识、带 `has_body`+无 Abstract+页数 护栏、误杀实测 0 → 建议**从 `_source_needs_content_qc` 源门解耦，对所有源（含 DOI-keyed）统一运行**；门①②③（标题/跨社/文内 DOI，误杀风险稍高）保持源门约束。如此 **acs-authorchoice SI、crossref TOC、及未来任何 DOI-keyed 非正文一网打尽，无需枚举源**。（该解耦为设计决策，待 161/总指挥 140 拍板；142 倾向采纳。）

**默认档位铁律（给 145，补 §六）**：真门默认 **soft**（非正文→uncertain 仍落盘打标）；**145 CF 重跑必须置 `content_qc_non_article_hard_reject=True`**，否则 9 条非正文仍落盘（或让 `build_coverage` 消费 `non-article-*` 软黑名单）。

### 9.10 147 二轮实测追加（门⑤C 页数卡放宽 + 翻默认前广样本不误杀回归）

147 二轮旁证与修正（`验证-门③④⑤拦截率-recover_b4_cf-147.md` 已同步）：

- **解耦获数据背书**：`iecr.5c04764`（unpaywall 真全文 15 页）解耦后仍凭 `has_body`（Abstract/Introduction）判 match、**不误杀**；acs SI 纯文本判识无页数依赖 → **`has_body` 护栏足以支撑门④⑤ 对所有源统一跑**（解耦定案，142+147 一致）。
- **门⑤C 页数卡需放宽（修正 §9.6）**：`1.5053761` 是 **14 页手册**（Content Platform User Guide），`page_count<=3` 卡口 14>3 **不触发** → 单靠解耦仍抓不住。**须双修**：① 解耦（进门）+ ② 门⑤C **去掉 `<=3` 硬上限**，改以 `has_body==False`（无 Abstract/Introduction/Results）+（`table of contents`|`user guide`|`author index`|`issue of the`）关键词为**主判据**（`has_body` 已防误杀真正文；页数卡对多页目录/手册过严）；可选保留"页数>3 时需 ≥2 个 TOC/手册信号"作稳妥。
- **翻 `hard_reject` 默认前须过广样本不误杀回归（P0 前置）**：解耦后 DOI-keyed 源（unpaywall/publisher_oa/crossref）真文也进门④⑤，147 的 0/5 仅本目录 5 条。**在把 decouple + `hard_reject=True` 设为默认前**，须跑一轮**跨目录广样本不误杀回归**（尤其 publisher_oa 正式版 PDF）+ §9.7 的 4 条不误杀正例全过（**0 误杀**）。**147 认领该回归（只读跨目录跑 `_content_qc_verdict`），结果报总指挥 140 作为翻默认的门槛。**

- **配置已存在、但 CLI 未暴露开关（145 实测发现）**：`config.py` 已有 `content_qc_non_article_hard_reject`（默认 `False`=soft），但 `cli.py`/`run_all.py` **未暴露对应命令行开关**。建议 161 补 `--qc-non-article-hard-reject`（同时让 `build_coverage` 可顺带消费 `non-article-*` 软黑名单、口径统一）；145 CF 重跑临时做法 = 小 runner 直接 `Pipeline(Config(..., content_qc_non_article_hard_reject=True))`。

### 9.11 147 广样本回归 PASS（解耦+hard_reject 达翻默认门槛）+ 门④ 关键词缺口（P1）

147 跨目录广样本不误杀回归结果（`验证-门③④⑤拦截率-recover_b4_cf-147.md §六`，已报 140）：

- **Part A（DOI-keyed active）**：276 条、其中已知真全文 143 条 → 解耦门④⑤ + `hard_reject` **误杀 0**；额外拒 **51 条全为 SI**（acs-authorchoice 40 + unpaywall/crossref/openalex/semantic_scholar 11）→ **解耦顺带净清这 51 条现靠整源豁免落盘的 SI 假阳**（decouple 的增益，远超 recover_b4_cf 单目录）。
- **门⑤C 放宽（§9.10）**：额外拒 2 条均非正文、**0 误杀**（`1.5053761` 手册 + 1 条 Nature SI）。
- **Part B**：§9.7 四正例全过；SI 反例 `hard_reject` 确拒。
- **结论**：**decouple + `hard_reject=True` + 门⑤C 放宽 已达翻默认门槛（143 已知真全文 0 误杀）**，可由 140 拍板设默认；净收益 = recover_b4_cf 8/9 + 广样本 51 SI + 2 非正文。

**新缺口（P1）· 门④ SI 关键词漏 `supplementary information`**：门④ 现只认 `supporting information`，漏 `supplementary information`（Nature/多家用词）——实测 `10.1038/s41929-022-00871-7`（Nature SI，74 页，首页 "In the format provided by the authors and unedited"）**逃过门④、仅靠门⑤C 兜住**。建议门④ 判识关键词补 `supplementary information` + `in the format provided by the authors`（保留 `not has_body` 护栏，147 实测不误杀）。

*核验 2026-07-02｜142 独立复核（改派自 task-e2535a16）｜纯读 `download.py`+`recover_b4_cf_qc.md`，未改任何 .py/PDF/metadata｜增补 9.1–9.11：pypdf 致盲运维铁律、整源豁免精修、门序整合、元数据 DOI 反证、页数接口、可照抄 selftest、147 实测回灌(8/9 拒、0 误杀)、门④⑤ 去源门解耦、门⑤C 页数卡放宽收 14 页手册、广样本回归 PASS(143 真全文 0 误杀 + 净清 51 SI，达翻默认门槛)、门④ 补 supplementary information 关键词(P1)、CLI 开关缺口(145 发现)。全部落地项归 161/140。*
