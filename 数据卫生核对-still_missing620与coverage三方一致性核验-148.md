# 数据卫生核对 · still_missing 620 与 coverage.json / 分片 三方一致性核验（-148）

> 交付：**谷歌学术人机认证-148（worker，sessionId eee59218）** → 总指挥 148（9a1bec34）｜2026-07-02。
> 任务：用户/总指挥选项「对 still_missing 620 分桶做一次数据卫生核对，产出与 coverage.json 一致性的核验报告」。
> 边界：**只读核对 + 只新建本 1 份 md + 1 个可复跑核验脚本 `_datahygiene_audit_148.py`，未改任何 `.py`/产物/coverage**。
> 权威真值源：`out/coverage.json`（`generated_ts` **2026-07-02 18:25:56**，-151 增量回写A 之后的最新快照）。方法：脚本化逐项交叉核对，机器可读输出见脚本 stdout。

---

## 〇、TL;DR（一句话结论）

**全链路数据卫生通过：无重复、无遗漏、无漂移。** `coverage.json`（success 379 / miss 620）、`still_missing.txt`（620 DOI）、分片并集（旧快照 628）三者差异 **100% 可归因** —— 差的 **8 条 = -151 增量回写A 从 still_missing 剔除的净成功**（4 ACS + 4 Elsevier），与 `out/_writeback151_removed_from_still_missing.txt` **逐条完全相等**。当前 620 分桶重算与《本波回收交付汇总》§二完全一致。唯一需知会的是**时序口径差**：分片 `_shard_stats.json` 仍是 628（11:48 旧快照），当前 still_missing 是 620（18:25）——差集已解释，若要分片与当前逐字节对齐需按 620 重产分片（见 §五）。

---

## 一、coverage.json 内部自洽（全部 PASS）

| 校验项 | 值 | 结论 |
|---|---:|:--:|
| total_unique_dois | 999 | — |
| success + miss = total | 379 + 620 = 999 | ✅ |
| success_rate = success/total | 0.3794 = 379/999 | ✅ |
| by_source 求和 = success | Σ=379 | ✅ |
| QC 账：success_before_qc − rejected_total | 508 − 129（硬 4 + 软 125）= 379 | ✅ |
| QC allow_override（白名单免剔） | 4 | ✅（含在 379 内） |
| claimed_success_but_no_pdf | 339 | （cleanup 已移错件，供审计） |

> QC 口径：原始去重成功 508 → 剔抓错论文 129（硬黑名单 4 + 软黑名单/uncertain 125）→ 净成功 **379**；被剔者改判 miss 并进 still_missing，保留 `qc_rejected_source/pdf` 供复核。`success_after_qc = 379`、`success_rate_after_qc = 0.3794` 与顶层一致。

## 二、still_missing.txt 自洽（全部 PASS）

| 校验项 | 值 | 结论 |
|---|---:|:--:|
| 文件总行数 | 622 | — |
| 注释头行（`#`） | 2 | — |
| 数据行（DOI） | 620 | — |
| 去重后唯一 DOI | 620 | ✅ 无重复（duplicates=0） |
| 头注释声称条数 | 620 | ✅ = 数据行数 |
| 数据行数 = coverage.miss | 620 = 620 | ✅ |
| 唯一 DOI = coverage.miss | 620 = 620 | ✅ |

> 坐实了历史文档反复澄清的「行数 vs DOI 数」口径：**622 行 = 620 DOI + 2 注释头**，不再有「差 2」的错觉。

## 三、分片（still_missing_shards）自洽（全部 PASS，但为旧快照）

| 校验项 | 值 | 结论 |
|---|---:|:--:|
| 8 桶计数求和 | 628 | — |
| 并集去重（union） | 628 | ✅ = 求和（无跨桶重复） |
| 桶内重复 | 0 | ✅ |
| 跨桶重复 | 0 | ✅ |
| `_shard_stats.json` total | 628 | ✅ 与实际分片一致 |
| 分片生成时间 | 2026-07-02 **11:48:47** | ⚠ 早于当前 coverage（18:25） |

分片各桶（628 旧版）：elsevier 379 / acs 95 / rsc 67 / other 35 / springer 23 / wiley 22 / iop 4 / aip 3。

## 四、漂移归因：分片 628 → 当前 620（差 8 条，100% 可解释）

| 方向 | 条数 | 明细/归因 |
|---|---:|---|
| 分片有、当前 still_missing **无** | **8** | **完全等于** `_writeback151_removed_from_still_missing.txt` 的 8 条（`removed_matches_diff=true`） |
| 当前 still_missing 有、分片 **无** | **0** | ✅ 无遗漏、无「新增未分片」 |

被剔的 8 条（-151 增量回写A：二级嵌套扫描 + -145 内容 QC 白名单 4 真正文 + Elsevier 回收 4）：

```
10.1016/0021-9517(87)90366-6      10.1021/acs.energyfuels.5c06101
10.1016/0304-5102(82)85049-9      10.1021/acs.langmuir.7b03998
10.1016/j.apcatb.2017.01.076      10.1021/acscatal.0c04429
10.1016/j.jechem.2016.11.023      10.1021/ja509214d
```

**当前 620 按 prefix→bucket 重算分桶**（与《本波回收交付汇总》§二逐桶一致）：

| 桶 | 分片(628 旧) | 当前(620) | Δ | 说明 |
|---|---:|---:|---:|---|
| elsevier | 379 | **375** | −4 | -151 回收 4 篇 Elsevier 真正文 |
| acs | 95 | **91** | −4 | -151 纠黑名单误杀 4 篇 ACS 真正文 |
| rsc | 67 | 67 | 0 | — |
| other | 35 | 35 | 0 | — |
| springer | 23 | 23 | 0 | — |
| wiley | 22 | 22 | 0 | — |
| iop | 4 | 4 | 0 | — |
| aip | 3 | 3 | 0 | — |
| **合计** | **628** | **620** | **−8** | = 4 ACS + 4 Elsevier |

> Δ 结构（−8 = acs −4 + elsevier −4）与 §四被剔清单的社别构成（4×10.1021 ACS + 4×10.1016 Elsevier）**逐条吻合**，交叉印证无误。

## 五、结论与一条建议

1. **数据卫生结论：三方（coverage.json / still_missing.txt / 分片并集）在扣除 -151 回写的 8 条后完全一致，无重复、无遗漏、无口径漂移。** 当前权威净覆盖 **379/999 = 37.9%**、still_missing **620**，可对外/供排工直接引用。
2. **唯一时序缺口（非错误，供总指挥决策）**：`out/still_missing_shards/` 及 `_shard_stats.json` 仍是 **628@11:48 旧快照**，落后于当前 620@18:25 的 still_missing。差集已 100% 归因（8 条），但**若后续分桶 ROI / route-B 发射清单要以分片为输入，建议按当前 620 重产一次分片**（把 acs 95→91、elsevier 379→375 落到 shard 文件与 `_shard_stats.total`），避免下游误用 628 旧计数。这是唯一的「刷新待办」，不影响任何已定稿结论。
3. 口径纪律提醒（承 `_audit149_caliber_drift.md`）：引用净覆盖统一只引 `coverage.json` 的 `summary.qc.success_after_qc` + `generated_ts`，勿再用 448/44.8%（旧快照）或 561/44.2%（含 SI 假阳的 magic+size 上界）。

---

*核验 2026-07-02｜-148 worker（sessionId eee59218）｜承总指挥 148 选项派工｜权威源 `out/coverage.json` 18:25:56｜方法：`_datahygiene_audit_148.py` 脚本化三方交叉核对（只读，可复跑）｜结论：无漂移/无重复/无遗漏，628→620 差 8 条 = -151 回写剔除（4 ACS + 4 Elsevier）逐条吻合｜仅新建本 md + 1 核验脚本，未改任何 .py/coverage/产物。*
