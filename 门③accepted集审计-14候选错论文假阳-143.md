# 门③ accepted 集审计 · 14 条候选错论文假阳（-143）

> 交付：谷歌学术人机认证-143 ｜ 2026-07-03 ｜ **纯读审计**（未改 coverage/黑名单/PDF；仅新建本报告 + 候选清单 `out/_gate3_accepted_candidates_143.csv`）。
> 触发：用户请求「用门③ 在 accepted 集扫出现存错论文假阳、逐条复核、（可能）回写 coverage」。
> 方法：对 `out/coverage.json` 中 **status=success 的 368 条**逐条跑门③（`_extract_pdf_meta_dois`：PDF 自述 XMP `prism:doi`/`dc:identifier` + `/Info` *doi* 键）+ 开卷读正文首部；仅当**期望 DOI 不在正文/URL（强正①未命中）且 PDF 自述 DOI 全部 ≠ 期望**时列为候选。数字源 `out/coverage.json`（368/631/36.84% @ 22:07:22）。

---

## 〇、TL;DR

- **368 条 accepted 逐条门③**：113 条能抽出自述 DOI，其中 **99 条自述含期望 DOI（门③ 不动，正证据）**、**14 条候选**（自述 DOI 全 ≠ 期望、且期望不在正文）。全部候选 `source=websearch`（与 L 节「websearch 系统性抓错论文」一致）。
- **14 候选全部 CROSS_PREFIX（跨出版商）**，开卷正文首部逐条确认**确系他篇**（题名/期刊/年份均对不上期望），**无一 SAME_PREFIX 需犹豫**——门③ 命中即高置信「错论文假阳」。
- **但分两类、处置不同**：
  - **6 条非白名单**（当前自然计 success）→ **可安全拉黑**，回写后净成 **368 → 362**。
  - **8 条与 gold/allow 白名单冲突**（writeback149 gold59 / 155 allow 已「免死」判真正文）→ **门③ 与既有 gold 裁定矛盾**。开卷证据强烈指向「gold 当时把同题他刊误判真正文」或「盘上文件已被并发重跑覆盖」；**回写它们 = 推翻 writeback149 的 gold 免死判定**，须先裁定。若确认，再 −8 → **354**。
- **结论**：门③ 不仅是下载期新门，还**回溯揪出了 368 里至少 6 条（可能 14 条）既有 websearch 同题他刊假阳**——**36.84% 仍偏高**，诚实净成应下修到 **~36.2%（362/999）** 乃至 **~35.4%（354/999）**。

---

## 一、6 条非白名单 · 高置信错论文假阳（可安全拉黑 → 368→362）

| 期望 DOI | 期望题名（前缀） | PDF 自述 DOI | 开卷正文首部（实为他篇） | batch |
|---|---|---|---|---|
| `10.1002/er.4082` | CO₂ methanation over Ni and Rh… | 10.1016/j.renene.2025.123248 | "biochar-based catalyst for methanation…"（Renew. Energy 2025） | batch4_p4 |
| `10.1016/j.apcata.2015.10.041` | Effect of strongly bound copper species… | 10.1016/j.jre.2019.12.015 | "tungsten oxide on ceria nanorods… CO oxidation"（J. Rare Earths 2019） | recover_b4_cf |
| `10.1016/j.cej.2026.174737` | Direct combination of RWGS and FTS… | 10.1016/j.jechem.2021.10.013 | "electrocatalytic oxygen reduction… H2O2"（J. Energy Chem 2021） | batch6 |
| `10.1016/j.ijhydene.2014.12.035` | Review… hydrogen production methods… | 10.1016/j.jclepro.2019.02.046 | "Review… hydrogen production options for better environment"（J. Clean. Prod 2019，另篇综述） | batch6 |
| `10.1016/j.jcat.2026.116771` | Regulation mechanism of CO2 on Cr6+… | 10.1016/j.apcata.2023.119260 | "Applied Catalysis A 661 (2023) 119260"（Appl. Catal. A 2023） | batch6 |
| `10.1016/j.jcis.2017.02.014` | Effect of cobalt loading… ethyl acetate ox… | 10.1002/jctb.5868 | "cerium incorporation… acetone oxidation"（J. Chem. Technol. Biotechnol） | batch6 |

处置：追加 `out/qc_merge_highconf_wrong.csv`（硬黑）→ `python tools/build_coverage.py`（消费黑名单重建）→ 净成 362。

---

## 二、8 条与 gold/allow 白名单冲突（门③ 判错 vs 已免死；须裁定）

| 期望 DOI | 期望题名（前缀） | PDF 自述 DOI | 开卷正文首部（实为他篇） | 白名单来源 |
|---|---|---|---|---|
| `10.1016/j.apcatb.2010.02.034` | …N2O decomposition（apcatb 2010） | 10.1007/s44442-025-00035-9 | "J. Saudi Chem. Soc. (2025)… Mo-triamidoamine… N2O reduction" | gold59/allow |
| `10.1016/j.fuel.2017.09.114` | …iron-based FT catalyst（Fuel 2017） | 10.1007/s10562-019-03074-1 | "Catalysis Letters (2020)… Sonochemical Pd nanoparticles" | gold59/allow |
| `10.1016/j.jcou.2018.05.022` | Advances in CO₂ utilization patent… | 10.1016/j.petsci.2021.11.002 | "proppant pumping schedule… CO2 fracturing"（Petrol. Sci 2021） | gold59/allow |
| `10.1016/j.jcou.2020.101413` | review… CO2 using H2 → CO/methane… | 10.1038/s41598-026-47757-3 | "Laser-generated X/InxOy/ZrO2 composite catalysts" | gold59/allow |
| `10.1021/acs.chemrev.0c00083` | 3D Graphene Materials… | 10.1016/j.cej.2025.159963 | "Polyethyleneimine graphene oxide aerogels… direct air capture"（short comm.） | gold59/allow |
| `10.1023/a:1023555415577` | Fundamentals of Methanol Synthesis… | 10.1016/j.cej.2025.164562 | "sorption-enhanced reactor… green methanol production" | gold59/allow |
| `10.1039/c3ee44078h` | Recent progress on N/C structures… | 10.1038/s41598-020-62638-z | "Sci. Rep. (2020)… Helium Adsorption in N-Doped Graphitic" | gold59/allow |
| `10.1039/d0gc00095g` | …CO2-assisted/catalyzed biomass… | 10.1016/j.ijbiomac.2023.125051 | "General rights… public portal…"（仓库封面页，实为 ijbiomac 2023） | gold59/allow |

**冲突含义**：这 8 条被 writeback149 的 `_writeback149_gold59.txt` / `_coverage_allow_v2_11_155.txt` 列入「免死金牌」（内容 QC 核实真正文、纠黑名单假阳），故即便拉黑也**不会被剔除**（allow > black）。但门③ + 开卷正文首部显示它们**确系跨社他篇**。二选一为真：
1. **gold 当时误判**（当时靠 expected-doi-present / 标题吻合，未查 PDF 自述元数据 DOI；同题他刊标题重叠高 → 误免死）；或
2. **盘上文件在 gold 之后被并发重跑覆盖**（本仓有大量并发 route-B/recover 写 pdfs/）。
无论哪种，**若确认这 8 条现盘文件是他篇**，则 writeback149 的 gold59（+50 中含这 8）**高估了净成 ~8**——需从 allow 白名单移除 + 拉黑，net 再 −8 → **354/999 ≈ 35.4%**。

---

## 二·补、回写执行结果（-143，用户裁定「只拉黑 6 非白名单」）

- **已执行**：6 条非白名单追加进 `out/qc_merge_highconf_wrong.csv`（硬黑）→ 备份 `out/coverage.bak_pre_gate3wb_143_20260704_012550.json` → `python tools/build_coverage.py`（复刻权威口径：`--extra-dirs rerun_elsevier_143/fetch,rerun_acs_144/fetch,rerun_wiley_144/fetch,t0_recover_156/fetch,p3_longtail_160/fetch --qc-allow out/_coverage_allow_v2_11_155.txt,out/_writeback149_gold59.txt`，verify_allow 开）重建。
- **验证**：6 条现全部 `status=miss, qc=hard_reject, error=qc_hard_reject:wrong-paper(...)`；**rejected_hard 30→36（恰 +6，即我这 6 条）**，`success_before_qc` 558 不变、`allow_override` 60 不变。
- **⚠️ headline 净数漂移（并发 churn，非我所致）**：新 `out/coverage.json`（ts 2026-07-04 01:29:51）**success = 371 / miss 628 / 37.14%**，而非预期的 362。拆解：`rejected_total 190→187`——我 **hard +6**，但**并发会话同时把 soft 名单 160→151（−9）**（改了 `qc_merge_union_wrong.csv`/`qc_uncertain_reject.csv`，非本波），两者叠加 = 558−187 = 371。**我的 −6 已确定性生效且持久**（在硬黑 CSV，任何后续重建都会剔除）；headline 上行是并发放宽 soft 盖过所致。这正是 V.1/T.2「coverage churn 需单写者」的实况——本次回写与并发单写者叠加，最终以 `out/coverage.json` 为唯一真相源。
- **口径连带**：`基线口径冻结说明-388-173.md` 的 368 已滞后（现 371），属**单写者 159 维护的文档**，本波未改，交属主对齐。

## 三、建议处置（分级、防误伤 gold）

1. **P0 安全**：6 条非白名单 → 追加硬黑 → 重建 coverage（368→362）。低风险、门③ 直接证据。
2. **P1 需裁**：8 条 gold 冲突 → **先逐条开卷全文复核**（非仅首部）确认现盘文件确系他篇；确认后**从 `_writeback149_gold59.txt`/`allow_v2` 移除 + 拉黑**（368→354），并在《基线口径冻结说明》与经验记录记「writeback149 gold59 含 ~8 同题他刊误免死，门③ 回溯纠正」。
3. **纪律**：coverage 是单写者共享文件（V.2）且本仓有并发提交，回写须与单写者/属主对齐、加写锁、`--verify` 自证；数字唯 `out/coverage.json`（U.3）。

---

## 四、来源与复现

- 候选清单：`out/_gate3_accepted_candidates_143.csv`（14 行，含 doi/cls/meta_doi/batch/source/title/body_head/pdf_path）。
- 复现：门③ 全扫脚本（本波一次性、纯读）逐条 `_extract_pdf_meta_dois` + `_extract_pdf_text_meta` 开卷；判据同生产门③（`download._content_qc_verdict` meta-doi-mismatch）。
- 关联：经验记录 **L**（websearch 系统性假阳）、**R**（回写强制前置门=开卷复核）、**W.4**（门③ 落地）、`基线口径冻结说明-388-173.md`（writeback149/gold59 口径）。

---

*审计 2026-07-03 ｜ -143 ｜ 纯读、未改 coverage/黑名单/PDF；14 候选全 CROSS_PREFIX 开卷确认他篇；6 非白名单可安全拉黑(→362)、8 gold 冲突须裁(确认后→354)；数字唯 out/coverage.json。*
