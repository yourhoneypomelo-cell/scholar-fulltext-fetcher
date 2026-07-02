# 验证 · 门③（异 DOI 反证）落地前实测——99 PENDING 池 meta-doi vs body 窗口效力

> 交付：**信息检索-专家智库 · 谷歌学术人机认证-148**（worker，session 1f26d41c）｜2026-07-02
> 定位：**不重述规格**。门③ 规格已定于 `选型2026-QC并集门增强建议-recover_b4_cf假阳-173.md` **§3.1 / §9.4（meta-doi-mismatch）/ §9.6（判定顺序）**，实现归 **-161**、门属主 **-140**。本文只做**一件事**：用 T0 预筛的 **99 条 PENDING 池**（远宽于 -173/-147 所用 recover_b4_cf 13 条）**实测各门③变体的抓取力与不误杀**，给 -161 选「信号 + body 窗口」提供数据背书，并扩充 `tools/regress_qc_union_189.py` 的负/正样本。
> 边界：**纯读实测**，复用 `download._extract_pdf_text_meta / _qc_matchers / _QC_DOI_RE / _pdf_reader`；只写 `out/_t0_gate3_probe_148.csv`；**未改核心 `.py`、未回写 coverage、未跑网络**。承 `检索成果-T0预筛still_missing翻案99条-内容QC逐条-148.md`（同批 A/B/C/D 分档）。

---

## 〇、一句话结论（**修正 -147 §9.9**）

- **-147 §9.9 结论「门③首选 = meta-doi-mismatch」需修正**：实测 **meta-doi-mismatch 抓不到 cctc.200900261**（该 Beilstein PDF 的 Info/XMP 未抽出 DOI）；**唯一稳抓 cctc 的是 body-embeds 且窗口放到 ~1500 字**（§9.9 测的 body@500 确实漏、我方 body@1500 命中 `10.3762/bjoc.7.159`）。
- **落地建议：门③ = `meta-doi-mismatch` ∪ `body-embeds-different-doi(窗口≈1500，非 500)`**（两者互补：meta 抓面最广、body@1500 补 meta 抽不到的老/小社 PDF 如 Beilstein）。
- **零真正文误杀**：T0 的 6 条真正文候选在门③-union 下 `catch=False`（全安全）；其中 `apcatb.2021.119925` 元数据甚至**含期望 DOI**（`meta_has_exp=True`）→ 佐证其为真正文（同时说明 meta-doi 可作**正**信号，但须配 `has_body`，因 SI 也带母文 DOI，见 §四）。

---

## 一、门③ 各变体抓取力（99 PENDING 逐条实测；证据 `out/_t0_gate3_probe_148.csv`）

| 门③ 变体 | 全 99 命中 | 76 条 WRONG+UNCERTAIN「逃逸池」命中 |
|---|---:|---:|
| meta-doi-mismatch（Info+XMP） | 28 | 27 / 76 |
| body-embeds-different-doi @500 | 13 | 13 / 76 |
| body-embeds-different-doi @1500 | 19 | 19 / 76 |
| **UNION（meta ∪ b500 ∪ b1500）** | **42** | **41 / 76** |

> 判据（与 -173 §9.6 一致）：某信号源里出现「≠ 期望」的完整 DOI **且期望 DOI 不在该源** → 该变体「会拒」。`catch=True` = 命中错文信号。
> 口径提醒：这 76 条本已在黑名单（不影响当前 coverage）。门③ 加固的价值是**前向**——防 route-B/CF 重跑把这类「异 DOI 错文」再记 success；对 -147 则是**把 65 待核里 ~30 条『含异 DOI』标出来**（union 命中 41 − 已知 WRONG/cctc 11 ≈ 30），眼核集从 65 收到 ~35，现实净增区间进一步收紧。

---

## 二、关键案 cctc.200900261（同题 Beilstein 双发，M.1④）

| 信号 | 结果 |
|---|---|
| meta-doi-mismatch | **miss**（`meta_diff=False`：Info/XMP 未抽出 DOI；注意抽取完整性 caveat，见 §五） |
| body-embeds @500 | **miss**（`10.3762/bjoc.7.159` 不在首 500 字，复现 -147 §9.9） |
| **body-embeds @1500** | **命中**（`10.3762/bjoc.7.159` 在首 1500 字内）→ **门③ 唯一稳抓路径** |

> ⇒ 若 -161 只实现 meta-doi-mismatch（-147 §9.9 首选），**cctc 仍逃逸**；必须**叠加 body-embeds 且窗口 ≥1500**。这是本实测对 -173/-147 的**净增修正**。

---

## 三、不误杀验证（T0 的 6 条真正文候选，门③-union 必须放行）

| DOI | meta_has_exp | 门③-union catch | 结论 |
|---|:--:|:--:|---|
| `10.1116/1.5053761` | False | **False** | 安全 |
| `10.1016/j.apcatb.2021.119925` | **True** | **False** | 安全 + 元数据含期望 DOI（真正文强佐证） |
| `10.1016/j.jcou.2022.102356` | True | **False** | 安全 |
| `10.1016/j.jechem.2020.06.007` | True | **False** | 安全 |
| `10.1016/s1872-2067(17)62899-7` | False | **False** | 安全 |
| `10.1002/anie.201406637` | True | **False** | 安全 |

> **真正文误杀 = 0/6**。护栏机理：门③ 要求「期望 DOI 不在该源」；真正文首部印**自己**的 DOI（= 期望）→ 期望存在 → 不触发。cctc 被抓正因其首部印的是 Beilstein（≠期望）而无 cctc DOI。故 body@1500 的「参考文献噪声」风险被此护栏压住（6 条真正文实证不误杀）。

---

## 四、给 -161 的落地建议（承 -173 §9.4/§9.6，只补实测选择）

1. **门③ = meta-doi-mismatch ∪ body-embeds-different-doi**；**body 窗口取 ~1500**（500 漏 cctc；1500 抓 cctc、且 6 真正文不误杀）。
2. **meta-doi 双向用**：`norm(meta_doi) != norm(exp)` → mismatch（§9.4）；`norm(meta_doi) == norm(exp)` **仅在 `has_body=True` 时**作正信号（apcatb 实证元数据含期望 DOI，但 SI 也带母文 DOI，故 `==exp` 不能单独放行，须配 `has_body`）。
3. **判定顺序**照 -173 §9.6：非正文（门④⑤）→ 异 DOI 反证（门③：meta ∪ body@1500）→ 均先于 `expected-doi-present` 短路。
4. **meta 抽取要稳**：本实测用 pypdf `metadata`(Info) + `xmp_metadata`(dc_identifier/dc_source + rdf_root XML) 扫 DOI，cctc 未得 → 建议生产实现补 `prism:doi`/`pdfx:doi` 命名空间直取（§9.4 已列），别只靠 Info。

---

## 五、回归 fixture 扩充（并入 `tools/regress_qc_union_189.py`）

- **must-catch（门③-union 必拒）**：`10.1002/cctc.200900261`（**body@1500 专项断言**：Beilstein `10.3762` 在 500~1500 字区，证明窗口须 ≥1500）；另从 `out/_t0_gate3_probe_148.csv` 取 `catch_union=True` 且 label∈{WRONG,UNCERTAIN} 者作批量负样本（41 条）。
- **must-not-kill（门③-union 必放）**：§三 6 条真正文候选（尤其 `apcatb.2021.119925` meta_has_exp=True、`s1872-2067(17)62899-7` 曾被 hard 误杀）。
- **caveat 样本**：meta 抽取完整性——cctc `meta_diff=False`，若生产用更全的 XMP 解析得到 Beilstein DOI，则 meta 分支亦应命中；回归里对 cctc 同时保留 body@1500 断言以防 meta 抽取平台差异。

---

## 六、待办 / 依赖（交接）

- [ ] **-161 实现门③**（承 -173 §9.4/§9.6 + 本文 §四：body 窗口 ~1500 + meta union）；**-161 不在本协同组名单**，经 **-140（门属主，本组）** 转交/落地。
- [ ] **-140 收编回归**：§五 fixtures 并入 `regress_qc_union_189`，改门后 `RUN_DATA_REGRESS=1` 跑（-173 §9.7）。
- [ ] **-147**：可用 `out/_t0_gate3_probe_148.csv` 的 `catch_union` 把 65 待核里 ~30 条「含异 DOI」先判错文，眼核集缩到 ~35（与 `检索成果-T0预筛...-148.md` §4.2 合看）。

---

*核验 2026-07-02｜信息检索-专家智库 · -148｜纯读实测、复用生产原语、未改 `.py`/未回写/未跑网络｜证据 `out/_t0_gate3_probe_148.csv`（99 逐条）+ `_t0_gate3_probe_148.py`｜**承 -173 §3.1/§9.4/§9.6（门③规格，不重述）、-147 §9.9（本文修正其「meta-doi 唯一」结论）**；实现交 -161（经 -140 转交）｜已同步总指挥。*
