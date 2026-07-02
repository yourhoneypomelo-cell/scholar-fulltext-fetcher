# QC 黑名单增删 diff（coverage 回写前置）· 交 QC 属主 -147/-151/-153 审

> 交付：**谷歌学术人机认证-143（coverage/rerun 属主）**｜2026-07-02｜承 task-d996038f Step1 核验（`真实净增回写coverage-Step1核验-143.md`）。
> 决策依据：用户「授权自决」+ 系统 delegate → 采纳「143 出黑名单增删 diff 交 QC 属主审 → 审过后 143 重跑写盘 → 149 只读复核」。
> 边界：**本文只提 diff 提案 + 证据，未改任何 CSV、未写 coverage.json**。改 QC 黑名单请由属主执行/授权。
> 判定工具：项目自带 `tools/qc_content_match.judge()`（阈值 MATCH_HI=70/MISMATCH_LO=50），对**当前盘上文件**复判；含嵌套+QC dry-run 现值 = **376/623**。

---

## 〇、为什么要改（一句话）

含嵌套扫描后，QC 并集门对新回收波出现**双向误差**：**3 条 websearch 抓错论文（共享同一 Stanford EHS 安全须知 PDF）漏网会误计为 success**，**4 条真全文因 stale 黑名单（基于早期 batch4 错版建的）被误杀**。修正后回写才诚实。**净影响：376 → ≈377（−3 补黑、+4 解救、acsami SI 另议 −0/−1），且成分正确。**

---

## 机器可读 delta（供 -151 直接应用；DOI 已规范化）

**〔A · 假阳剔除 / 补黑〕4 条**（当前错误计入 376，应改判 miss；-142 授权把 SI 一并入 A）：
```
10.1016/0021-9517(87)90366-6      # md5 2C640D6A7680 共享假PDF（Stanford EHS氢化安全须知，非正文）
10.1016/0304-5102(82)85049-9      # 同上 同一文件（md5相同）
10.1016/j.apcatb.2017.01.076      # 同上 同一文件（md5相同）
10.1021/acsami.9b14097            # 首页 "Supporting Information S-1" = SI 支撑材料非正文（-145 ACS QC 同口径）
```
**〔B · 误杀解救 / 加白〕4 条**（当前在 still_missing，应回 success；judge 均 match 89~100）：
```
10.1016/j.jcou.2022.102356        # 现版 match100(DOI在正文); 旧黑=日本防卫省招标公告
10.1016/j.jechem.2020.06.007      # 现版 match98.5(DOI在正文); 旧黑=IJSAT他刊
10.1016/j.apcatb.2021.119925      # 现版 match100; 旧黑=DOE评审幻灯片
10.1016/j.jece.2025.119153        # 现版 match89.1; 旧黑=rafaldb错文(uncertain池连坐)
```

> **回写后诚实数**：现 376 = 371 + [3假PDF + 1 SI + 1真(j.jechem.2016)]。A 剔 4（3假+SI）→ 372；B 解救 4 → **376**。数值仍 376，但**成分全部为真**（371 + j.jechem.2016 + 解救4 = 5 条真净增），已无假阳/ SI。
> 分工（-142 授权）：**-151（唯一写主）**据本 delta 把 A 补黑 / B 加白，用**现有 nested+QC** 的 `build_coverage` 回写（**不改码**）；**-147（QC门 owner）**据 §五 把两类门缺陷（同 md5 假PDF/SI 漏拦、stale 黑名单误杀）修进门逻辑。**143 只产 delta、不回写、不 commit。**

---

## 一、补黑（ADD 3 条）—— websearch 抓错论文、当前未被任何黑名单收录

**证据**：3 个不同 DOI 的 PDF 是**同一个文件**（md5 `2C640D6A7680`、347KB），下载 URL 均为 `https://ehs.stanford.edu/wp-content/uploads/Hydrogenation-Fact-Sheet-1.pdf`（斯坦福 EHS《氢化反应安全须知》，**非任何一篇论文**）。`judge()` 因标题含 "hydrogenation" 词重叠误判 uncertain（52~69 分），但 **md5 三碰撞 = 铁证抓错**。

建议加入 **`out/qc_merge_union_wrong.csv`**（soft/union；列：batch,doi,verdict_151,title_score,url_wrong,pdf_url,pdf_actual,pdf_path）：

```
rerun_elsevier_143/fetch,10.1016/0021-9517(87)90366-6,mismatch,52.1,True,https://ehs.stanford.edu/wp-content/uploads/Hydrogenation-Fact-Sheet-1.pdf,"Stanford EHS Hydrogenation Fact Sheet (safety doc, not the paper; md5 2C640D6A7680 shared by 3 DOIs)",out/rerun_elsevier_143/fetch/pdfs/10.1016_0021-9517_87_90366-6.pdf
rerun_elsevier_143/fetch,10.1016/0304-5102(82)85049-9,mismatch,64.9,True,https://ehs.stanford.edu/wp-content/uploads/Hydrogenation-Fact-Sheet-1.pdf,"same shared EHS fact-sheet PDF (md5 2C640D6A7680)",out/rerun_elsevier_143/fetch/pdfs/10.1016_0304-5102_82_85049-9.pdf
rerun_elsevier_143/fetch,10.1016/j.apcatb.2017.01.076,mismatch,69.0,True,https://ehs.stanford.edu/wp-content/uploads/Hydrogenation-Fact-Sheet-1.pdf,"same shared EHS fact-sheet PDF (md5 2C640D6A7680)",out/rerun_elsevier_143/fetch/pdfs/10.1016_j.apcatb.2017.01.076.pdf
```

> 效果：build_coverage QC 并集门将把这 3 条判 miss（当前含嵌套口径它们错误地计入 376）。

---

## 二、解救（REMOVE 4 条）—— 真全文被 stale 黑名单误杀

**关键证据**：这 4 条的黑名单条目**指向早期 batch4_p* 的错版 PDF**，而 `rerun_elsevier_143` 已重下**正确版**（`judge()` 对正确版全判 match 89~100，2 条 DOI 在正文）。DOI-keyed 黑名单同时杀掉了新正确版 → 误杀。

| DOI | 早期错版（黑名单所据，batch4_p*） | 现盘正确版（rerun_elsevier）judge | 需从这些源移除 |
|---|---|---|---|
| `10.1016/j.jcou.2022.102356` | batch4_p2：**日本防卫省招标公告** PDF（score 2.8） | match 100（DOI 在正文），"Spinel ferrite…RWGS" | `qc_merge_union_wrong.csv`[行41] + `qc_rejected_manifest.csv`[行41,soft] |
| `10.1016/j.jechem.2020.06.007` | batch4_p4：**IJSAT** 他刊（score 49.1） | match 98.5（DOI 在正文），"Nickel nanoparticles…" | `qc_merge_union_wrong.csv`[行120] + `qc_rejected_manifest.csv`[行120,soft] |
| `10.1016/j.apcatb.2021.119925` | batch4_p5：**DOE 评审幻灯片**（score 40.0） | match 100，"Spectroscopic insight…Cu/BEA" | `qc_merge_union_wrong.csv`[行157] + `qc_rejected_manifest.csv`[行157,soft] |
| `10.1016/j.jece.2025.119153` | batch4_p1：**rafaldb.com** 错文（score 59.8，uncertain 池连坐） | match 89.1，"Carbon nitride…Ni/CeO2" | `qc_uncertain_reject.csv`[行5] |

> **机制提醒（请 QC 属主定夺）**：build_coverage 的 QC 集 = `qc_merge_union_wrong.csv` ∪ `qc_rejected_manifest.csv`(soft) ∪ `qc_uncertain_reject.csv`。要真正解救，须从**全部命中源**移除该 DOI（否则任一源残留仍会 soft-reject）。
> **`qc_rejected_manifest.csv` 是「物理移出」的历史真相**（batch4 错版确实被移进 `rejected/`，当时判断正确）——建议**不删历史行**，而是二选一：(A) 在 `resolve_qc_sets` 增加「DOI 级 allowlist 覆盖」用于已重下正确版的 DOI；或 (B) 仅从 `union_wrong`/`uncertain_reject` 移除并把 manifest 该行 source 改注 `stale_superseded_by:rerun_elsevier_143`。**推荐 (A)**（可复用、可审计、不改历史）。若嫌重，(B) 亦可，但需在行内留证。

---

## 三、回写与复核流程（审过 diff 后）

1. QC 属主 -147/-151/-153 审本 diff → 应用（补黑 3 + 解救 4，机制择 A/B）。
2. 143 重跑 `python tools/build_coverage.py`（含嵌套、消费更新后的 QC）→ 写 `out/coverage.json` + `still_missing.txt` + 刷新分片。预期 **success ≈ 377、miss ≈ 622**（补黑 −3、解救 +4，acsami SI 另议）。
3. ping -149 只读复核三点：① success/miss 与重算一致；② 补黑 3（md5 2C640D6A7680）不计 success；③ 解救 4 已回 success 且移出 still_missing。
4. 对外「权威口径」发布 **376/623（或修正后 377）**；**442/561 仅作「未QC原始上界」注释，不作决策数**。

---

## 四、附：acsami.9b14097（SI 边界，QC 属主定）

`10.1021/acsami.9b14097`（rerun_acs_144）现计入 376，但首页是 "Supporting Information S-1"（SI 支撑材料）。`judge()` title-match 96.3（SI 带论文题名）。**是否算真全文取决于 SI 政策**：若「仅 SI 无正文」判假阳，应补黑（376→再 −1）；若接受，则保留。建议与 -145《验证-rerun_acs_144…》的 SI 判定对齐。

---

*核验 2026-07-02｜-143｜diff 提案（未改 CSV、未写 coverage）｜证据：md5 三碰撞 + judge() 复判 + 黑名单行溯源｜待 QC 属主审 → 143 重跑写盘 → 149 复核。*
