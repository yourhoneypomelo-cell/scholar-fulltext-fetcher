# task-d996038f「真实净增回写 coverage」· Step1 只验核验报告（诚实口径）

> 交付：**谷歌学术人机认证-143（worker，coverage/rerun 属主）**｜2026-07-02｜来源：总指挥 81fcf213 delegate。
> 边界：**Step1 = 只读 dry-run 核验，未改任何 `.py`、未写 coverage.json/still_missing.txt、未动他人产物**。Step2（真回写）**按任务要求押后**（须等 rerun_elsevier 跑完 + 过 -147 QC 并集门）。

---

## 〇、TL;DR（给总指挥，先看结论）

1. **`build_coverage.py` 无需修——二级扫描早已实现**：docstring 明写「历史 bug 只扫一级已修」，`list_batch_dirs` 已 `os.walk` 递归收录任意深度 `out/<dir>/fetch/metadata.jsonl`，默认 `include_nested=True`，带 `--no-nested` 逃生门 + demo/smoke 夹具剔除 + `--extra-dirs` 定向纳入。**`--selftest` 全绿（COVERAGE_OK，含嵌套翻转用例）**。Step1「修扫描」这一步**其实是已完成态**。
2. **任务简报「+71 → 371→442 / 628→561」在 QC 口径下不成立、严重偏乐观**。现场 dry-run 实测（QC 并集门开启）：**含嵌套 = 376 / still_missing 623**，仅比现仓 `coverage.json`（371/628，一级口径）**净增 +5**，不是 +71。
3. **+71 的真相 = 大头是 websearch 抓错论文假阳**：`_audit149_netgain_unmerged.csv` 的 71 行，经 QC 口径拆解 = **62 条被 QC 判假阳（wrong-paper）+ 5 条翻成 success + 4 条 route-B 裸 PDF（无 metadata 不计）**。若按 `--no-qc` 硬凑，含嵌套会虚报到 **506（50.7%）**——那是把 websearch 错论文全算进来的污染值，**绝不可当净覆盖**。
4. **连这 +5 都要打问号（已用项目 QC 工具 `judge()` 复判，非目测）**：5 条里 **3 条共用同一个假 PDF**（同 md5、内容是某高校 EHS《氢化反应安全须知》，`judge` 判 uncertain 但靠 md5 碰撞定性为假阳）、**1 条是 SI 支撑材料**（`acsami.9b14097`，SI 策略由 QC 定）、**1 条 `j.jechem.2016` 是真全文**。→ QC 并集门**漏掉这几条**（rerun 新产、未进黑名单）。
5. **反向也有坑：4 条真·正确全文被 QC 误杀（false kill）——已由 `judge()` 铁证**：`j.jechem.2020.06.007 / j.apcatb.2021.119925 / j.jcou.2022.102356 / j.jece.2025.119153` 现盘 PDF 全被 `judge` 判 **match（89.1~100，2 条 DOI 在正文）**，却因 stale SOFT 黑名单被算作 miss。→ **应解救、计入净增（+4）**。
6. **结论**：naive 含嵌套 376 里**同时含 3~4 条假阳 + 漏掉 4 条真全文**，两错部分抵消才凑成"+5"，逐条都是错的。真回写前**必须先按当前盘上文件重跑内容 QC**——补黑 §三 假阳、解救 §四 误杀。**诚实净增（工具确认的真 match）≈ +5（j.jechem.2016 + 解救的 4 条），即 371→~376**，与"+71→442"天壤之别；`acsami` SI 另议。

---

## 一、Step1 核验方法（全部只读）

```
python tools/build_coverage.py --selftest                 # → COVERAGE_OK
python tools/build_coverage.py --no-write --no-nested --print-json   # 一级+QC（复现现仓口径）
python tools/build_coverage.py --no-write --print-json              # 含嵌套+QC（默认）
python tools/build_coverage.py --no-write --no-qc --print-json      # 含嵌套+不QC（污染上界）
```

| 口径 | success | still_missing | success_rate | QC 剔除 |
|---|---:|---:|---:|---|
| 一级 + QC（≈现仓 coverage.json） | **371** | 628 | 37.14% | before 463 → 剔 92（硬0+软92） |
| **含嵌套 + QC（默认，正解口径）** | **376** | **623** | **37.64%** | before 506 → 剔 130（硬5+软125） |
| 含嵌套 + 不QC（污染上界，**勿用**） | 506 | 493 | 50.65% | 0（含全部 websearch 错论文） |

> 现仓 `out/coverage.json`(12:37:20)=371/628，其 `by_success_batch` 无任何 `*/fetch` 项 → **确认是 `--no-nested` 一级口径生成**。含嵌套默认口径应为 **376/623**。

---

## 二、+71「未并入」清单的真实拆解（QC 口径）

对 `out/_audit149_netgain_unmerged.csv`（71 行）逐条比对「一级成功集 / 含嵌套QC成功集 / 黑名单」：

| 分类 | 条数 | 说明 |
|---|---:|---|
| 已在一级即成功（跨批重复，非净增） | 0 | — |
| **二级新增且过 QC（计入 376）** | **5** | 见 §三，含 4 条存疑 |
| 二级新增但被 QC 判假阳（仍 miss） | 62 | QC 并集门**正确拦截**的 websearch 错论文 |
| route-B 裸 PDF（runbook_b，无 metadata） | 4 | 未走 pipeline metadata，不进 coverage 口径 |

**→ 任务简报的「71 条真净增」= 把 62 条 QC 假阳 + 4 条无 metadata 裸 PDF 全当成了净增**。真按 QC 口径只翻了 5 条，且其中仅 1 条可信。

---

## 三、翻成 success 的 5 条 —— 逐条甄别（3 假阳 + 1 SI + 1 真）

| DOI | 盘上 PDF 首页实测 | 判定 |
|---|---|---|
| `10.1016/0021-9517(87)90366-6` | md5=2c640d6a…、355744B，内容=某高校 EHS《HYDROGENATION FACT SHEET》安全须知 | ❌ **假阳** |
| `10.1016/0304-5102(82)85049-9` | **同一个** md5=2c640d6a…（同 355744B 安全须知） | ❌ **假阳（同文件）** |
| `10.1016/j.apcatb.2017.01.076` | **同一个** md5=2c640d6a…（同 355744B 安全须知） | ❌ **假阳（同文件）** |
| `10.1021/acsami.9b14097` | 首页 = "Supporting Information S-1…"（SI 支撑材料，非正文） | ⚠️ **SI，QC 存疑** |
| `10.1016/j.jechem.2016.11.023` | 首页 = J Energy Chem 26(2017) "Enhanced effect of plasma on catalytic reduction of CO₂…"（题/刊吻合） | ✅ **真·正确全文** |

> **铁证**：前 3 条 DOI 共用一个 355744 字节、md5 相同的 PDF，且内容是安全教育资料——典型 websearch「一个碰运气链接喂给多个 DOI」的假阳。QC 并集门当前**未收录**这 4 条 → 应补进黑名单，否则含嵌套口径会把它们误计入 376。

---

## 四、反向发现 —— 疑似 4 条真全文被 QC 误杀（stale blacklist）

| DOI | 现盘 PDF 首页实测 | raw口径 | QC口径 | 黑名单来源（精确，供定点改） |
|---|---|---|---|---|
| `10.1016/j.jechem.2020.06.007` | "Nickel nanoparticles…CO₂ methanation"（J Energy Chem 2020，吻合） | success | **miss** | `qc_merge_union_wrong.csv` + `qc_rejected_manifest.csv`(SOFT) |
| `10.1016/j.apcatb.2021.119925` | "Spectroscopic insight…Cu/BEA catalyst"（Appl Catal B，吻合） | success | **miss** | `qc_merge_union_wrong.csv` + `qc_rejected_manifest.csv`(SOFT) |
| `10.1016/j.jcou.2022.102356` | "Spinel ferrite catalysts for CO₂ reduction via RWGS"（J CO₂ Util 2022 OA，吻合） | success | **miss** | `qc_merge_union_wrong.csv` + `qc_rejected_manifest.csv`(SOFT) |
| `10.1016/j.jece.2025.119153` | "Carbon nitride boosts CO₂ methanation…Ni/CeO₂"（J Env Chem Eng，吻合） | success | **miss** | `qc_uncertain_reject.csv`（uncertain 整池拒收） |

> **精确定位（供 QC 属主定点改）**：前 3 条被 `qc_merge_union_wrong.csv` 收录、且 `qc_rejected_manifest.csv` 记为已物理移出 pdfs/（基于**早期错版**）；第 4 条在 `qc_uncertain_reject.csv`（153「uncertain 池抽样 40/40 全错 → 整池拒收」的连坐，非逐条判错）。rerun 重下的**新副本**在 `rerun_elsevier_143/fetch/pdfs/`，与被移出的旧错版不是同一文件 → 黑名单条目指向旧错版，对新副本即**误杀**。§三 的 3 条共享假PDF 则**不在任何黑名单**（仅在审计 CSV），故会漏进 376。

> 这 4 条现盘 PDF 首页题名/期刊与 DOI **看着是对的**，却被 SOFT 黑名单判 miss。**最可能：黑名单是基于早期错版建的，而 rerun_elsevier_143 已重下正确版**（stale）。

### 四.5 用项目 QC 工具 `tools/qc_content_match.judge()` 对当前盘上文件复判（权威、非目测）

阈值 MATCH_HI=70 / MISMATCH_LO=50 / BORDER=8；对 §三+§四 共 9 条跑 `judge()`：

| DOI | judge verdict | title_score | doi_in_text | 真相 |
|---|---|---:|:--:|---|
| `10.1016/0021-9517(87)90366-6` | **uncertain** | 52.1 | 否 | 共享假PDF（md5碰撞）—实为假阳，title-only 因"hydrogenation"词重叠误判 uncertain |
| `10.1016/0304-5102(82)85049-9` | **uncertain** | 64.9 | 否 | 同上（同一假PDF） |
| `10.1016/j.apcatb.2017.01.076` | **uncertain** | 69.0 | 否 | 同上（同一假PDF） |
| `10.1021/acsami.9b14097` | match | 96.3 | 否 | 首页是 SI；title-match 命中但属支撑材料 → SI 策略由 QC 定 |
| `10.1016/j.jechem.2016.11.023` | **match** | 100.0 | 是 | 真正确全文 ✅ |
| `10.1016/j.jechem.2020.06.007` | **match** | 98.5 | 是 | 真正确全文（现 SOFT 黑名单 → 误杀）✅ |
| `10.1016/j.apcatb.2021.119925` | **match** | 100.0 | 否 | 真正确全文（现 SOFT 黑 → 误杀）✅ |
| `10.1016/j.jcou.2022.102356` | **match** | 100.0 | 是 | 真正确全文（现 SOFT 黑 → 误杀）✅ |
| `10.1016/j.jece.2025.119153` | **match** | 89.1 | 否 | 真正确全文（现 SOFT 黑 → 误杀）✅ |

**工具取证铁实**：§四 的 4 条全被 `judge` 判 **match（89.1~100，2 条 DOI 在正文）** → **确为真正确全文、却被 stale SOFT 黑名单误杀**，应解救（+4）。§三 的 3 条共享假PDF 被判 **uncertain**（非 match，但也未被当前并集门拒）→ 靠 **md5 碰撞**定性为假阳，应补入黑名单。→ **「uncertain 池整池拒收」策略只对已建快照生效，rerun 新产的 uncertain 未被盖到**——这是并集门对新回收波的盲区。

---

## 五、Step2 回写门控（rerun 已完成，剩黑名单修正 + 用户拍板）

- **✅ rerun_elsevier_143 已跑完**（终端 pid=40844，exit_code=0，elapsed≈57min，ended 17:42）。跑完后重跑 dry-run：**含嵌套+QC 仍 = 376/623**（elsevier 8 件里净新增仅 4，余为跨批重复或 QC 拒）。Step2「等 rerun_elsevier 完」这一门已清。
- **剩余门控**：① §三 的 3 条共享假PDF 未入黑名单、§四 的 4 条 stale 误杀未修 → 直接回写要么引假阳、要么误杀真全文；② 黑名单 CSV 归 QC 属主，须先修正或授权我出 diff；③ 发布口径（376 vs 442）待用户/总指挥拍板。
- **四方已对齐**（143 union+QC / 140 内容QC / 149 复现 / 我 re-run）：权威回写数 = build_coverage 含嵌套+QC 重算（当前 **376**，解救 4 条误杀、补黑 3 条假阳后 **≈377~380**），**绝非 442/561**。-149 已转只读待命，回写后做三点复核（success/miss 一致、补黑3不计success、解救4回success）。

---

## 六、给总指挥的可执行建议

1. **不要用 +71/442**，也不要用 `--no-qc` 的 506；**当前诚实口径 = 含嵌套+QC = 376/623**（vs 现仓 371）。工具复判后**真净增 ≈ +5**（j.jechem.2016 + 解救的 4 条 false-kill），但需先做黑名单增删修正 376 的成分。
2. **「rerun 重下候选内容 QC 重判」我已用项目 `judge()` 对 9 条核心候选跑完**（见 §四.5）；剩余动作是**改 QC 黑名单 CSV**（补 §三 3 条 md5-假阳、解救 §四 4 条 false-kill）——这些 CSV 归 QC 属主 -147/-151/-153，**建议你把「黑名单增删」派给他们**（或授权我提 diff 给他们审），我不单方改他人 QC 产物。
3. **待 rerun_elsevier_143 跑完** → 我重跑 `--no-write` dry-run 出最终 delta → 过 QC 门确认后，我再执行 Step2 真回写（`run_coverage(include_nested=True, write=True)` 或定向 `--extra-dirs`），并同步刷新 `still_missing.txt` + 分片。
4. `build_coverage.py` 本身**无需改**（二级扫描 + selftest 已就绪）；若要现仓 `coverage.json` 立刻切到含嵌套口径（371→376），我可在你点头后单独重生成（属改产物，非改码）。

---

## 七、来源与复现

- 代码：`tools/build_coverage.py`（`list_batch_dirs` 递归 + `--no-nested`/`--extra-dirs`/`--selftest`）。
- 数据：现仓 `out/coverage.json`(371/628)、`out/_audit149_netgain_unmerged.csv`(71)、`out/still_missing.txt`(628)、rerun_elsevier_143/rerun_acs_144 的 `fetch/metadata.jsonl`+`pdfs/`。
- 复现：§一 四条命令 + 对 §三/§四 DOI 的 md5 去重 + `pypdf` 首页抽词（均只读，产物已清理，未留临时件）。

---

*核验 2026-07-02｜谷歌学术人机认证-143｜task-d996038f Step1 只验｜未改 .py / 未写 coverage / 未动他人产物｜结论：扫描已就绪无需修；QC 口径真净增 376/623(+5，仅+1可信)，非任务简报的 442/561(+71)；先重 QC 再回写。*
