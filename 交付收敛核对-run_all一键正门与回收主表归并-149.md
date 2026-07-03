# 交付收敛核对 · run_all 一键正门指向 + 回收文档归并《回收结论主表》建议

> 核对/建议者：谷歌学术人机认证-149（worker）｜任务：`task-fb04a5d7-8012-4e3b-8000-3f9785e12f02`（总指挥「交付收敛核对：最终交付清单指向 run_all 一键正门 + 回收文档归并建议」，P2·只读）｜2026-07-02
> 边界：**纯只读核对 + 只新建本 1 份建议 md**；不改 `最终交付清单.md`/`程序使用说明.md`/任何他人文档、不动任何 `.py`。所有「补丁建议」均为**待属主采纳**的草案片段，非既成修改。
> 证据基线（本机实测 2026-07-02）：`run_all.py --selftest`→`RUN_ALL_OK`、`tools/build_coverage.py --selftest`→`COVERAGE_OK`、`python run_all_selftests.py`→**`SUMMARY: PASS=44 FAIL=0 SKIP=2 (total=46)`**（run_all/build_coverage 均已 `[PASS]`）、`python tools/build_coverage.py --no-write --print-json`→**净成功 371/999 = 37.1%**（实时 `out/`，未落盘）。
>
> ✅ **口径（定版 2026-07-03）**：净覆盖唯一权威 = **`out/coverage.json` 326/673/32.63%**（`generated_ts` 2026-07-03 12:50:24）。本文内 **371/37.1%** 等为**【历史/理论口径】**。统一见 **《基线口径冻结说明-388-173.md》**。

---

## 〇、一句话结论

1. **run_all 未写进交付文档**：`最终交付清单.md` 与 `程序使用说明.md` **都没有**把 `run_all.py` 写成「一键批量」正门入口——两者当前仍以 `python -m fulltext_fetcher …` 为主入口，且清单里出现的是**回归自检器** `run_all_selftests.py`（与一键正门 `run_all.py` **仅一词之差、极易混淆**）。建议按 §二 的最小补丁补齐。
2. **一键正门本身已就绪且已入回归**：`run_all.py` + `tools/build_coverage.py` 双离线 selftest 本机复跑通过，且**已被并发成员接线进 `run_all_selftests.py`**（第 99–100 行），实测一键回归 `PASS=44/total=46`。→ 文档滞后于代码，不是能力缺口。
3. **《回收结论主表》尚不存在**（仓内 `*主表*.md` 命中 0），**batch7 无独立回收 md**；且更严重的是**头条成功率数字四代漂移**（`最终交付清单`≈82% / `北极星汇总`71.4% / `回收实测结论`44.8% / `本波回收交付汇总`定稿37.9% / **实时口径 37.1%**）。归并《回收结论主表》时必须**先统一口径阶梯、锁定单一权威数字**（见 §三）。〔✅ **已收口（173 冻结）**：单一权威已锁定 = **388/999 = 38.84%**，四代旧数字均标【历史/理论】，详见《基线口径冻结说明-388-173.md》〕
4. **交付前「可直接执行」的收敛清单见 §四**（含要改哪份文档、改哪几行、以谁为准）。

---

## 一、核对结果 A：两份交付文档是否把 run_all 写清为「一键批量」正门？

### A1. `最终交付清单.md` —— ❌ 未写清（缺 run_all 正门）

| 位置 | 现状 | 问题 |
|---|---|---|
| §〇 一句话结论 | 「一键回归 `python run_all_selftests.py`」 | 这是**自检器**，非一键批量正门；读者会误以为 `run_all_selftests.py` 就是「一键跑全量下载」 |
| §一 怎么跑 | 只有 `python -m fulltext_fetcher …`（单条/批量）+ `python -m fulltext_fetcher.scholar …` + `python run_all_selftests.py`（自检） | **完全没有** `python run_all.py -f inputs.txt …` 这条一键批量正门；也没有「跨批去重/续跑 → coverage/still_missing → 一页式总结」闭环 |
| §二 交付物清单 C.工程化/QA | 列了 `run_all_selftests.py` | **未列** `run_all.py`（北极星一键编排器）与 `tools/build_coverage.py`（跨批 coverage 主库）——两个北极星核心产物在清单里缺席 |
| §〇/§一 数字 | 「一键回归 …PASS=36 / total=36」 | **已 stale**：实时 `run_all_selftests.py` = **PASS=44 / FAIL=0 / SKIP=2（total=46）** |

> **命名混淆是这里最大的可用性坑**：`run_all.py`（一键批量出全文 + 覆盖报告，正门）vs `run_all_selftests.py`（一键回归自检）。交付文档只提后者、不提前者，交付对象很可能"跑了自检以为跑了下载"。

### A2. `程序使用说明.md` —— ❌ 未写（全篇无 run_all）

- 全文主入口为 `python -m fulltext_fetcher "<DOI/标题>" --email …`（单条/标题/arXiv/批量 `-f`），**通篇未出现** `run_all.py`。
- 无「跨批续跑（`--resume` 跨 `out/` 剔已成功）→ `coverage.json`/`still_missing.txt` → 一页式总结 → `still_missing.txt` 作下一轮 `-f` 输入」这一北极星闭环工作流；而这正是 run_all 相对裸 `-m fulltext_fetcher` 的**唯一增量价值**。

### A3. 地面真相（本机实测，证明是"文档滞后"而非"能力缺失"）

```
$ python run_all.py --selftest
RUN_ALL_OK
$ python tools/build_coverage.py --selftest
COVERAGE_OK
$ python run_all_selftests.py
[PASS] run_all              RUN_ALL_OK via `run_all --selftest` (0.8s)
[PASS] build_coverage       COVERAGE_OK via `tools.build_coverage --selftest` (0.3s)
SUMMARY: PASS=44  FAIL=0  SKIP=2  (total=46)
SKIPPED (WIP): flaresolverr_nodriver, regress_qc_union_189
```

- `run_all.py` docstring 与 `--selftest` 已明确其定位＝北极星一键正门（读清单→去重→跨批续跑→下载→coverage/still_missing→一页式总结→`run_all_summary.json`），且**只包装 `Pipeline`/`cli`/`build_coverage`、不改核心码**。
- **`run_all` / `build_coverage` 已接线进一键回归**（`run_all_selftests.py` 第 99–100 行），即 -153《北极星…汇总》§七 的 P1「把两者 selftest 纳入 `run_all_selftests.py`（36→38）」**已被执行并落地**（实测 total 已到 46）。→ 交付文档应同步反映此现状。

---

## 二、给两份文档的最小补丁建议（只建议、待属主采纳；均为可直接粘贴草案）

> 以下片段仅供属主（`最终交付清单.md`/`程序使用说明.md` 的维护者）取用；本人不代改。

### B1. `最终交付清单.md` 建议改 3 处

**(1) §一 怎么跑 —— 顶部新增「一键批量正门」小节（置于 `-m fulltext_fetcher` 之前）：**

```markdown
# —— 一键批量正门（North Star：清单→去重→跨批续跑→下载→覆盖报告）——
python run_all.py -f inputs.txt --email you@uni.edu -o out/run_all   # 标题/DOI 混排；--resume 默认开
#   → 产 out/run_all/fetch/pdfs/ + coverage.json + still_missing.txt + run_all_summary.json（一页式总结）
#   → 续跑：把上轮 still_missing.txt 作下一轮 -f 输入即可（已成功自动跳过）
python tools/build_coverage.py            # 跨批 out/ 聚合 → coverage.json + still_missing.txt（净口径，剔 QC 抓错）
```

**(2) §二 交付物清单 C. 工程化/QA —— 增列两个北极星核心产物：**

```markdown
`run_all.py`（北极星一键编排正门：去重/跨批续跑/下载/覆盖报告，含 --selftest→RUN_ALL_OK）、
`tools/build_coverage.py`（跨批 coverage/still_missing 主库，黑名单感知净口径，含 --selftest→COVERAGE_OK）、
`run_all_selftests.py`（一键回归，现 PASS=44/FAIL=0/SKIP=2，total=46）
```

**(3) 全局数字勘误**：所有「`PASS=36 / total=36`」→ **`PASS=44 / FAIL=0 / SKIP=2（total=46）`**（并注明 SKIP 2 项为可选联网/数据回归，默认不跑）。

### B2. `程序使用说明.md` 建议新增一章「§0 一键批量正门 run_all（推荐首选）」

```markdown
## 0. 一键批量正门 run_all（推荐首选：批量 + 续跑 + 覆盖报告）

python run_all.py -f inputs.txt --email 你@xx.edu -o out/run_all

它在裸 `-m fulltext_fetcher` 之上多做四件事：输入内去重 → 跨批续跑（扫既有 out/ 剔已真实成功）
→ 下载 → 末尾生成 coverage.json / still_missing.txt / 一页式总结。闭环续跑：
把上一轮 out/run_all/still_missing.txt 作下一轮 -f 输入（已成功者自动跳过），换策略反复跑。
（单条/临时查仍可用 `python -m fulltext_fetcher "<DOI/标题>" --email …`，见 §2。）
```

---

## 三、核对结果 B：回收文档归并《回收结论主表》建议

### B0. 现存相关文档盘点（归并输入清单）

| 现有文档 | 批/主题 | 核心数字 | 归并去向建议 |
|---|---|---|---|
| `检索成果-batch4-语料B成功率.md` | batch4 权威成功率 | 348/500=69.6%（by_source/分片明细） | → 主表「§各批明细·batch4」 |
| `检索成果-batch4-失败分桶与可回收分析.md` | batch4 失败分桶 | A101/B8/C42；CF 桶 | → 主表「§各批明细·batch4」+「§可回收 ROI」 |
| `检索成果-batch6-失败分桶与可回收分析.md` | batch6 失败分桶（已刷新82%版） | 410/500=82.0%；A73/B1/C16 | → 主表「§各批明细·batch6」 |
| `分析-batch6-源配置对比.md` | batch6 源配置 | 源顺序/接线状态 | → 主表附录 or 保留为选型支撑 |
| `分析-batch6-metadata解析.md` / `-attempts详细错误.md` / `-运行日志模式.md` | batch6 细粒度 | 明细 | → 主表附录「数据与方法」引用（不必全并入） |
| `北极星一键批量下载-主流程与回收结论汇总.md`（-153） | 三批 + 主流程 | core 866/1213≈71.4% | → **候选主表基座之一**（但数字口径需降级，见 B2） |
| `回收实测结论-CF与免费路线到顶.md`（-149/-150） | CF/免费到顶 + QC 假阳 | 净 448/999≈44.8% | → 主表「§墙类型与免费天花板」+「§QC 净口径」 |
| `本波回收交付汇总.md`（-148 定稿 18:25） | still_missing 620 波 | **净 379/999=37.9%** | → **推荐作《回收结论主表》基座**（最新、口径最诚实） |

> **batch7 无独立回收 md**：结论仅散落在 `北极星…汇总`（108/213）、`build_coverage` docstring、`coverage.json`（batch7 多为 batch6 已成功项重跑、去重净增个位数）。归并时须**为 batch7 补一小节**，明确"batch7 不是新语料、是 batch6 重跑，勿把 213 当独立分母"。

### B1. 归并要解决的三个问题

1. **无《回收结论主表》**（`*主表*.md` = 0 命中）：三批结论 + 回收实测 + 净口径分散在 8+ 份文档，交付对象无单一入口。
2. **batch7 缺独立落点** + 分母陷阱（1213 里含 batch7 的 213 重跑，逐批求和虚高）。
3. **头条成功率四代漂移（最致命）**——同一项目在不同文档给出互相矛盾的"成功率"：

| 文档 | 头条数字 | 口径 | 是否应作交付头条 |
|---|---:|---|---|
| `最终交付清单.md` | **~82%** | batch6 单批、**QC 前盲口径** | ❌ 会误导（单批 + 含 websearch 抓错假阳） |
| `北极星…汇总.md`（-153） | **71.4%** | core 三批**逐批 metadata 求和**、未去重未 QC | ❌ 仅作审计交叉核对；**虚高约 1.6–1.9×** |
| `回收实测结论`（-149/-150） | **44.8%** | 净（去重+落盘+剔 QC 12） | ⚠️ 已被更晚快照取代 |
| `本波回收交付汇总`（-148 定稿） | **37.9%** | 净（剔 QC 129），coverage.json 18:25 | ✅ 口径正确，但数字随盘漂移 |
| **本机实时（-149 复跑）** | **37.1%** | 净（剔 QC 92），`--no-write` 实时扫 | ✅ 口径正确，**证明净数字仍在动**（371 vs 379 vs 448） |

> 净数字自身还在漂（448→379→371），根因：`out/qc_merge_*_wrong.csv`/`qc_uncertain_reject.csv`/`coverage.json` 在多成员工作区**实时变化**，谁在什么时刻跑就得什么数。**交付前必须冻结一次**（见 §四）。

### B2. 《回收结论主表》建议结构（单一权威入口）

建议**以 `本波回收交付汇总.md` 为基座升格**为《回收结论主表》（它最新、口径最诚实、已含 620 分桶与 A5 结论），或新建一份并把上表文档降为"明细/支撑"。骨架：

```
# 回收结论主表（单一权威入口）
## 〇 权威口径与单一头条数字
   - 头条 = 净覆盖率（coverage.json：去重 + PDF 落盘 + 剔 QC 抓错）；生成时间戳必须写明
   - 口径阶梯（务必三行并列，杜绝再被单引某一个）：
       净覆盖（交付头条）      = <success>/999 ≈ <x>%     ← 认这个
       落盘实证逐批求和        = 484（会随 cleanup 变）    ← 参考
       metadata 逐批求和(审计) = 866/1212 ≈ 71.4%（虚高）  ← 仅交叉核对，勿作头条
## 一 各批明细：batch4(348/500=69.6%) / batch6(410/500=82.0%) / batch7(重跑、去重净增个位数，非独立分母)
## 二 still_missing 分桶 × 墙类型（elsevier/acs/rsc/other/springer/wiley/iop/aip）
## 三 免费天花板与 A5：免费净≈39–41% 封顶，主体 ~515 靠机构订阅
## 四 QC 净口径：websearch 假阳双法定案（硬黑/并集/manifest/uncertain）
## 五 下一波 ROI：T0 翻案 / T1 route-B 金OA / T2 publisher_direct / T3 A5
## 附录 数据与方法（引 batch4/6 明细、分析-batch6-*、经验记录 L/M/N/O 节）
```

**归并原则**：主表只放"单一权威数字 + 结论 + 索引"，把 `检索成果-batch4/6-*`、`分析-batch6-*`、`回收实测结论`、`北极星…汇总` 降级为**被主表引用的明细**（保留原文、只在主表建索引），避免"多份都像总表、数字各异"。

---

## 四、交付前收敛清单（可直接执行）

- [ ] **锁定单一头条数字**：交付前跑一次 `python tools/build_coverage.py`（落盘），以该 `out/coverage.json` 的 `summary.success_rate` 为**唯一**交付头条净覆盖率；记录生成时间戳；此后冻结 `qc_merge_*`/`qc_uncertain`。
- [ ] **`最终交付清单.md`**：按 §B1 补「一键批量正门 run_all」小节 + 交付物清单增列 `run_all.py`/`tools/build_coverage.py` + 数字 `36`→`44/46`；并把 §〇 头条 `~82%` 改标为"batch6 单批盲口径"，交付头条改用净覆盖率。（属主：清单维护者 / 总指挥）
- [ ] **`程序使用说明.md`**：按 §B2 新增「§0 一键批量正门 run_all」章（含闭环续跑）。（属主：说明维护者）
- [ ] **建《回收结论主表》**：以 `本波回收交付汇总.md` 升格或新建，按 §三-B2 骨架归并 batch4/6/7；**补 batch7 小节**（重跑非独立分母）；口径阶梯三行并列。（属主：-148/-142 + 总指挥）
- [ ] **命名去混淆**：在两份文档首次出现处显式注明 `run_all.py`（正门）≠ `run_all_selftests.py`（自检）。

---

## 五、边界与协作

- 本文**只读核对 + 只新建本 1 份建议 md**，未改任何 `.py`/他人文档；§二/§三 的补丁与骨架均为**待采纳草案**。
- 建议知会：`最终交付清单.md`/`程序使用说明.md` 属主（-141/-145）、`本波回收交付汇总.md` 属主（-148）、`北极星…汇总` 作者（-153），由总指挥统筹采纳与写锁协调。
- 已核实的实时数字（371/999=37.1%，PASS=44/46）随工作区实时变动，交付前须按 §四第 1 项**重新冻结生成**为准。

---

*核验 2026-07-02｜-149｜任务 task-fb04a5d7｜结论：两份交付文档均未把 run_all 写成一键批量正门（run_all_selftests 命名易混淆），但正门代码已就绪且已入一键回归（PASS=44/46）；《回收结论主表》尚不存在、batch7 无独立 md、头条成功率四代漂移且净数字实时漂移——归并前须先统一口径阶梯并冻结单一权威数字。纯只读 + 只新建本 1 份建议 md。*
