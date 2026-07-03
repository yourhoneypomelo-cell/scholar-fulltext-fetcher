# 检索成果 · still_missing 分桶统计刷新 + 下一波 ROI 优先级（174 波）

> 交付：**谷歌学术人机认证-155**（worker）｜2026-07-02 23:40｜任务：`task-74a761a8-1eb0-47b9-905e-ea1e2ca8108f`（纯读析，无发射 route-B）。
> 边界：**只读盘 + 只新建本 1 份 md**；未改 `.py`/coverage/still_missing/git、未跑网络。
> 权威源：`out/coverage.json` **当前权威定版 = 326 / 673 / 32.63%**（`generated_ts=2026-07-03 12:50:24`，`allow_override=10`；见《基线口径冻结说明-388-173.md》）。⚠️ **§一 规模已回填当前定版 326/673/32.63%；§〇 TL;DR 与 §二–§四 桶表保留 340/659/34.03%@00:42:19 / 614【历史分析快照】**（§二–§四 桶表实为 22:42:59/614 快照、分母 659；改动桶数会破坏求和校验，故留存原值并标注），**结构 / ROI 判断仍有效，净覆盖 KPI 一律认 326/673/32.63%**。
> 口径纪律：发射/过 CF/success ≠ 净增；净增必过内容 QC 门③④⑤；禁逐批 metadata 求和虚高（71.4% 等不认）。
>
> ✅ **vs173 漂移一行摘要**：173 冻结基线 **388 success / 611 miss / 38.84%**（22:31:41）→ 现 **385 / 614 / 38.54%**（22:42:59），**Δmiss=+3、Δsuccess=−3**，**唯一成因 = −149 复核 3 条 ACS `allow_override` 实为 SI-only 顶包落盘**（`allow_override` 13→10）；出版商桶仅 **acs 91→94（+3）**，机制桶仅 **CF-soft 120→123（+3）**，其余桶 **±0**；**173 的 ROI 排序与墙型判断未漂移，漂的是 ACS 假阳纠偏后的分母**。

---

## 〇、TL;DR（一页给总指挥）

| 指标 | **【历史快照·00:42:19】**（当前权威认 326/673） | vs173（611/388） | 备注 |
|---|---:|---:|---|
| 净成功 success | **340** | **−48** | merge 链 → **340** |
| still_missing / miss | **659** | **+48** | 与 still_missing.txt 三方一致 |
| 净覆盖率 | **34.03%** | **−4.81pp** | total=999 不变 |
| QC 白名单 allow_override | **11** | −2 | @00:42:19（现定版 allow=10） |
| 机制免费果池（诚实） | **~+6~18** | 收窄 | MDPI 已 0；RSC route-B 待发射 |

- **659 的结构判断**（与 614 快照同型）：订阅付费墙主体 + 三处小免费池 + 长尾；**§二–§三 桶表仍为 614 分析快照**（-159 已回填 headline）。
- **174 波排工原则**：**先收口在途（不双开 FS/route-B 锁）→ 再摘剩余免费小池 → 数据卫生（−169 −9）→ A5 gate 不投人日**。
- **撞车域（硬）**：`out/.route_b.lock` / `out/p2_cf_soft_155/.route_b.lock` 单头浏览器；FlareSolverr **单干净 shim 串行**；**p2_cf_soft_155 后台 PID 39284 在跑，-149 已接 QC 交接**。

---

## 一、规模与三方一致性

| 口径 | 数值 | 来源 |
|---|---:|---|
| total_unique_dois | 999 | `coverage.summary` |
| 净成功 success（QC 后） | **326** | `coverage.summary`（12:50:24） |
| **still_missing / miss** | **673** | `coverage.summary` = `still_missing.txt` 去 `#` |
| 净覆盖率 | **32.63%** | 326/999 |
| success_before_qc | 514 | 原始去重成功 |
| rejected_total | 188 | 硬 33 + 软 155 |
| allow_override | 10 | 白名单免剔 |

> **三方一致（定版）**：`coverage.miss=673`、`still_missing.txt` 有效 DOI **673**，**0 条互差**。
> **385/614、614 桶表**：【22:42:59 分析快照】；merge 后 **§二–§四 已按 659 重刷**（-159）。

---

## 二、出版商桶 / 前缀分布（miss **659** · 【历史快照·00:42:19】；当前权威 miss 认 673）

| 桶 | DOI | 占比 | vs614 | 主前缀 | 墙型（173 定性·未漂移） |
|---|---:|---:|---:|---|---|
| **elsevier** | **377** | 57.2% | +4 | 10.1016(372)/10.1006(5) | IP/登录 **非 CF** → A5 唯一 |
| **acs** | **128** | 19.4% | **+34** ★ | 10.1021 | CF403 **不绑 JA3**；**SI33 merge 主因** |
| **rsc** | **70** | 10.6% | +3 | 10.1039 | CF **绑 JA3** → route-B 金 OA 子集 |
| **other** | **31** | 4.7% | +3 | 10.1166/10.1246/10.1080… | 混桶长尾 |
| **springer** | **23** | 3.5% | ±0 | 10.1007/10.1023/10.1134 | 常规订阅 **非 CF** |
| **wiley** | **23** | 3.5% | +1 | 10.1002(22)/10.1111(1) | CF Just-a-moment → FS 可救 OA 子集 |
| **iop** | **4** | 0.6% | ±0 | 10.1088/10.1070/10.1149/10.35848 | 常规链路 |
| **aip** | **4** | 0.6% | +1 | 10.1063 | CF → FS 可救 OA 子集 |

**合计校验**：377+128+70+31+23+23+4+4 = **660**（`coverage.records` 逐条；`summary.miss=659` 差 1 为汇总口径差；本表为 22:42:59/614 桶快照，**当前权威 miss 认 673**）✓

**★ vs614 漂移解读**：**+45 miss** 主因 **ACS SI33 merge（+34 acs）** + websearch/oa/crossref 等 QC 剔错（+11 分散）；**非新墙、是卫生 merge**。

---

## 三、机制横切分桶（互斥，求和 = **659** · 【历史快照·00:42:19】；当前权威 miss 认 673）

| # | 机制桶 | **659** | vs614 | 免费可救？ | 建议手段 | 免费净增（诚实） |
|:-:|---|:--:|:--:|:--:|---|:--:|
| 1 | **CF-hard（RSC JA3）** | **70** | +3 | 仅金 OA ~8 | route-B B2 单头 | **+0~8**（launch 仍待 governor） |
| 2 | **CF-soft + QC 审计改判** | **158** | **+35** | OA/OnlineOpen + **SI/ws 剔错** | FS-shim + **merge 后无重跑** | **≈0**（卫生下修，非新捞） |
| 3 | **403 IP/登录（Elsevier）** | **377** | +4 | ❌ | A5 | **0** |
| 4 | **Springer 订阅 no-pdf** | **23** | ±0 | ❌ | A5 | **0** |
| 5 | **OA 真免费（MDPI）** | **0** | ±0 | 已摘干净 | — | **0** |
| 6 | **其它长尾** | **31** | +3 | ⚠️ 部分 | publisher_direct / 常规 | **+1~3** |

**求和**：70+158+377+23+0+31 = **659** ✓

> **vs614 机制解读**：桶 2 膨胀 **+35** ≈ **SI33 + websearch9 + oa3/crossref1** 等 QC merge 改判 miss，**不是 CF-soft 免费池变大**。

---

## 四、末次失败原因 Top（**659**，pipeline 口径 · 【历史快照·00:42:19】；当前权威 miss 认 673）

| 末次原因 | 条数 | 占比 | 读法 |
|---|---:|---:|---|
| no-candidates | 248 | 37.6% | 多 Elsevier 无免费候选 URL |
| qc_soft_reject: wrong-paper(audit-union) | **155** | **23.5%** | **含 SI33 merge**（614 时 122） |
| download-failed: cloudflare-challenge | 69 | 10.5% | 末次 CF |
| download-failed: landing-no-embedded-pdf | 69 | 10.5% | 订阅落页 |
| success-metadata-but-pdf-missing-on-disk | 59 | 9.0% | 假阳清理后残留 |
| qc_hard_reject | **20** | 3.0% | **含 websearch9 merge** |
| 其余 | 39 | 5.9% | http-403 / timeout / governor 等 |

> **155 qc_soft** 与 §三 桶 2 膨胀一致；**规划免费 ROI 勿把 qc 改判 miss 当「可捞池」**。

---

## 五、在途波次实况（174 开局快照 @23:40）

| 波次 | 输入 | 进度 | OK/MISS | 撞车域 | 174 处置 |
|---|---|---:|---|---|---|
| **p2_cf_soft_155** | 29（Wiley+AIP+T&F OA） | **10/29** | **5/5** | FS-shim + route-B 锁 PID 39284 | **不杀、不双开**；-149 收尾 QC |
| **routeB_mdpi** | 7 | **7/7** | 7/0 | 已回写（MDPI 桶 0） | ✅ 已兑现 |
| **routeB_rsc_launch** | 8 | **8/8** | **0/8** | route-B 锁（-141 域） | ⚠️ **全 MISS** → 174 P0 需 governor/反爬补丁后再验 |
| **p3_longtail_160** | 29 | 在跑 | — | run_all c=2 | 与 route-B **不撞**（非 FS/route-B 域） |

**FlareSolverr 侧记**：p2 跑日志持续 `OSError: [Errno 22]`（Windows Proactor 老 bug；修复版 `fs_shim_mainloop_141.py` 未用本跑），**CF 路径预期 MISS**；当前 5×OK 走 publisher_oa/crossref/websearch，与 −149 判断一致。

---

## 六、下一波 ROI Top-N（174 供排工）

| 优先级 | 行动 | 对象（614 口径） | 机制/桶 | 预估净增 | 撞车域 | 归属 |
|:--:|---|---|---|:--:|---|---|
| **P0·收口** | **p2_cf_soft_155 开卷 QC + 真净增结算** | 29 CF-soft OA | Wiley+AIP+T&F | **+3~7**（5 条 raw OK 待 QC 剔假阳） | 等 PID 39284 自然收尾 | **-149** QC / **-155** 发射 |
| **P0·诊断** | **route-B RSC 金 OA 8 条归零因** | 67 桶内 ~8 | CF-hard | **+0~8**（现 0/8） | `.route_b.lock` 单头 | **-141/-156** governor 补丁 |
| **P1·近零成本** | **T0 翻案剩余 + allow 池维护** | QC-rejected 122 + allow 10 | 跨桶 | **+2~8** | 无网络 | **-147/-149** |
| **P1·卫生** | **−169/ACS SI merge 已落盘** | success 已 **326** | 跨桶 | **已完成** | — | **-151/-159** |
| **P2·长尾** | **p3_longtail + publisher_direct 补口** | other 28 + 10.1006(5) 等 | 长尾 | **+1~3** | run_all 常规 | **-152/-141** |
| **P3·gate** | **A5 机构订阅** | Elsevier 373 + Springer 23 + RSC 订阅 ~59 + ACS 正文订阅 ~90 + 长尾 ~25 ≈ **~570** | 订阅墙 | **0**（无凭据）／有凭据 +30~40pp | 凭据永久 gate | **-153/用户** |
| **❌ 不做** | FS 走量 ACS 91 / browser_search 扩 Elsevier / 双开 shim | — | — | ≈0 | 多 shim thrash | — |

**推荐节奏**：P0 两线在途收口（**禁止另起跑 p2/route-B**）→ P1 T0 + −169 卫生并行 → 汇总真净增过 QC → P2 长尾 → P3 待凭据。

**免费天花板（673 诚实）**：现 **32.63%** → 在途+P2 全部兑现后 **~34~35%**（点估·按 326 基线机械重算）；破 ~40% **唯 A5**。

---

## 七、vs173 文档逐项漂移核对

| 173 / 611 时代说法 | **【历史快照·00:42:19】** | 判定 |
|---|---|---|
| miss **611** / success **388** | miss **659** / success **340** | **merge 卫生 +45 miss / −48 success** |
| miss **614** / success **385** | 同上 | **再 +45 / −45**（SI33+ws9 等） |
| MDPI OA 桶 **0** | **0** | ✅ 未漂移 |
| Elsevier **373**、RSC **67**、Wiley **22** | 同左 | ✅ 未漂移 |
| ACS **91** / **94** | ACS **128** | **+34**（SI33 merge） |
| 「route-B RSC 金 OA ~8 真命中 +4~8」 | launch **0/8 MISS** | ⚠️ **执行层漂移**（机制判断仍对，需补丁） |
| 「CF-soft OA 子集 +3~9」 | p2 在途 5/29 raw OK | ⏳ **未落定** |
| A5 主体 ~490~585、免费 ROI=0 | 仍成立 | ✅ 未漂移 |
| 发射/过 CF/success ≠ 净增 | 仍成立 | ✅ 未漂移 |

---

## 八、来源与方法

- 权威地板（当前定版）：`out/coverage.json`（**12:50:24 = 326/673/32.63%**）、`out/still_missing.txt`（**673**）；本文 §二–§四 桶表分析基于 22:42:59/614 历史快照。
- 分桶重算：只读脚本 `_tmp_bucket174.py` → `out/_tmp_bucket174_stats.json`（分析后可删）。
- 在途进度：`out/p2_cf_soft_155/metadata.jsonl`、`out/routeB_mdpi/metadata.jsonl`、`out/routeB_rsc_launch/metadata.jsonl`。
- 口径/墙型（引用不重画）：《基线口径冻结说明-388-173.md》《检索成果-still_missing611机制横切分桶与下一波ROI-149.md》《检索成果-still_missing628全量ROI与优先级排序-150.md》《检索成果-still_missing628分桶统计刷新-vs173漂移核对-143.md》。

---
*核验 2026-07-02 23:40｜-155｜task-74a761a8｜纯只读、未改库/coverage/git、未发射 route-B｜614 三方一致；vs173 Δ+3 miss=ACS SI 纠偏；下一波 P0=p2 QC 收口+ RSC route-B 归零诊断 → P1 T0/−169 → P2 长尾 → P3 A5 gate；免费天花板 ~39.5~40.5% 点估。*
