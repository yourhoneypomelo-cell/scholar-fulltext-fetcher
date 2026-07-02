# still_missing 628 分桶统计刷新（publisher / 失败reason / CF桶）· vs 173 ROI 漂移核对

> 交付：**谷歌学术人机认证-143（worker）** → 总指挥 144｜2026-07-02
> 任务：P1 still_missing 630 分桶统计刷新（publisher/CF/403），与 `检索成果-still_missing-CF-JA3桶ROI深挖-173.md` 对照是否漂移。
> 边界：**只新建本 1 份 md，未改任何 `.py`**。数据源：`out/coverage.json`（@2026-07-02 12:13:09，权威口径）、`out/still_missing.txt`、`out/still_missing_shards/*`、全仓 `metadata.jsonl` + `attempts.jsonl` 并集。

---

## 〇、TL;DR（给 144 的一页）

1. **口径已可实测**：173 当时 `coverage.json` 不在仓内、只能沿用**假设值 448/999=44.8%**；现仓内已有权威 `coverage.json` → **真净覆盖 371/999 = 37.1%，still_missing = 628**。
2. **两处显著漂移（173 偏乐观）**：净覆盖 **44.8% → 37.1%（−7.7pp）**；still_missing **≈551 → 628（+77）**。+77 = audit156 漏派清单并入（与 `_shard_stats.delta_vs_old_551` 一致）。
3. **“630” = 口径差**：`still_missing.txt` 630 行含 2 行 `#` 注释头 → **实际 628 个 DOI**，与 `coverage.miss=628`、shard 并集 628 **三方一致、无内部漂移**。
4. **CF 桶要去伪**：跨批“曾命中 CF 挑战”有 307 条（48.9%），**但其中 133 条 Elsevier 的 CF 来自 ResearchGate/Academia 镜像候选，不是 ScienceDirect 本体** → 剔除镜像后**真出版商 CF 墙 ≈ 187 条（29.8%）= ACS95+RSC67+Wiley22+AIP3**。**173“Elsevier 非 CF”的定性结论被证实，未漂移。**
5. **173 的定性 ROI 结论仍成立**（ACS 可回放救 / RSC JA3 难越 / Elsevier 非CF 到顶 / QC 必须先做），**漂的是“分母与规模”，不是“路线判断”**。

---

## 一、规模与三方一致性（无内部漂移）

| 口径 | 数值 | 来源 |
|---|---:|---|
| total_unique_dois | 999 | `coverage.summary` |
| 净成功 success（去重+PDF落盘+剔QC） | **371** | `coverage.summary` |
| **still_missing / miss** | **628** | `coverage.summary` = shard并集 = still_missing.txt(去#) |
| 净覆盖率 | **37.1%** | 371/999 |
| still_missing.txt 原始行数 | 630 | =628 DOI + 2 行 `#` 注释头 |

> **“630”澄清**：任务标题的 630 是行数口径；去掉 2 行注释头即 628 DOI。shard 各文件亦各含 4 行注释头（如 elsevier 383−4=379），八桶 DOI 求和=628。**still_missing.txt / shards / coverage.miss 三方 DOI 集合完全相等（0 条互差）**，故当前 still_missing 内部**无漂移**。

---

## 二、出版商桶 / 前缀分布（miss 628）

| 桶 | DOI 数 | 占比 | 主前缀 | 墙类型（沿用 173 定性） |
|---|---:|---:|---|---|
| **elsevier** | **379** | **60.4%** | 10.1016(374)/10.1006(5) | IP/登录墙 **非CF**（最低ROI，主力交机构订阅） |
| **acs** | 95 | 15.1% | 10.1021 | CF403 **不绑JA3**（可回放，FS 可救 OA/authorchoice 子集） |
| **rsc** | 67 | 10.7% | 10.1039 | CF **绑JA3**（回放失效，唯路线B 页内直下） |
| other | 35 | 5.6% | 10.3390/10.1166/10.1246/10.1080… | 混桶（T&F/OUP=CF；MDPI=OA；中日俄长尾） |
| springer | 23 | 3.7% | 10.1007/10.1023/10.1134 | 常规链路 **非CF** |
| **wiley** | 22 | 3.5% | 10.1002 | CF Just-a-moment（候选齐、FS 可救） |
| iop | 4 | 0.6% | 10.1088/10.1070/10.1149/10.35848 | 常规链路 **非CF** |
| **aip** | 3 | 0.5% | 10.1063 | CF Just-a-moment（FS 可救） |

**长尾前缀**：除上表 12 个主前缀外，另有 23 个前缀各 1 条（中日俄小社 + 单篇 Nature/Science/AIP/T&F 等），合计 25 条落 `other/springer/iop`。

---

## 三、失败原因分布 — **双镜头**（同一 628，两种口径必须并读）

### 3.1 镜头 A：权威“末次原因”（`coverage.records[].error`，pipeline 自身口径）

| 末次原因 | 条数 | 占比 | 含义 |
|---|---:|---:|---|
| success-metadata-but-pdf-missing-on-disk | **320** | 51.0% | 曾标 success 但 PDF 未落盘/被 cleanup 清（多为假阳清理后残留） |
| qc_soft_reject: wrong-paper(audit-union) | **92** | 14.6% | QC 判抓错论文、改判 miss |
| no-downloadable-pdf(无候选直链) | 72 | 11.5% | 有候选但无可下 PDF |
| no-candidates(0 source) | 58 | 9.2% | 所有源 0 候选 |
| cloudflare-challenge(403) | 50 | 8.0% | 末次即撞 CF |
| landing-no-pdf | 21 | 3.3% | 落地页无内嵌 PDF |
| 其余(http-403/412/418/405/202/timeout…) | 15 | 2.4% | 长尾 |

> **要点**：末次原因里 CF 仅 8%、真墙类偏低，**因为多数 DOI 最后一次是被 recover/websearch 跑触碰**（末次写成“假阳成功/无候选”），**覆盖掉了 batch6 里真正的 CF/403 墙**。故末次口径**低估硬墙**，须配镜头 B。
> 65.6%（320+92）末次是**“假阳成功 / 抓错论文”**，这正是 173 P0（QC 闸门）指向的问题 —— **数据侧已证实其为 still_missing 第一大成因**。

### 3.2 镜头 B：跨批“曾命中最硬墙”（全量 attempts 并集，每 DOI 取最硬）

| 最硬墙 | 条数 | 占比 | 备注 |
|---|---:|---:|---|
| CF-challenge | 307 | 48.9% | **含 133 条 Elsevier 的 RG/Academia 镜像 CF（非本体）** |
| never-attempted-download | 159 | 25.3% | 从未产生任何 download 尝试（157 条是 Elsevier：无免费候选URL） |
| http-403(paywall/IP) | 85 | 13.5% | 真订阅/IP 墙 |
| landing-no-pdf | 55 | 8.8% | — |
| other-http-4xx/2xx | 12 | 1.9% | 412/418/405/202/404 等 |
| no-response / shadow-lib | 10 | 1.6% | — |

---

## 四、CF 桶占比 — 去伪后的诚实值

| 口径 | 数值 | 用途 |
|---|---:|---|
| 候选级“曾命中 CF 挑战” | 307（48.9%） | ⚠️ 上界，**含 Elsevier RG/Academia 镜像 CF 133 条**，不可用作出版商 CF 规模 |
| **真出版商 CF 墙（去镜像）** | **187（29.8%）** | = ACS95 + RSC67 + Wiley22 + AIP3；**规划用此值** |
| ├ 可回放可救（非JA3）ACS+Wiley+AIP | 120 | FS shim → curl_cffi 回放（ACS 已实测落 PDF；authorchoice 净成功已收 42） |
| └ JA3 硬绑（难越）RSC | 67 | 回放失效，唯路线B 页内直下 |
| 末次原因=CF（`coverage`） | 50（8.0%） | ⚠️ 下界，被后续跑覆盖，低估 |

**Elsevier CF 核查（关键）**：37 条“末次=CF”/133 条“曾命中 CF”的 Elsevier DOI，其 CF 事件域名为 `www.researchgate.net`(218 次) + `www.academia.edu`(8 次) —— **全部是二级镜像候选，ScienceDirect 本体是 IP/登录 403，非 CF**。→ **173“Elsevier = IP/登录墙非CF”结论成立，无漂移**；把 Elsevier 计入“CF 可救”会误判 ROI。

---

## 五、与 173 ROI 文档逐项漂移核对

| 173 的说法 | 现权威实测 | 漂移判定 |
|---|---|---|
| 净覆盖 **448/999 = 44.8%**（自述“假设值，coverage.json 未在仓内”） | **371/999 = 37.1%** | **漂移 −7.7pp**（173 偏乐观；今有权威口径） |
| still_missing **≈551~553** | **628** | **漂移 +77**（audit156 漏派并入，非覆盖倒退） |
| “真订阅付费墙 403 ~300” | ACS+RSC 全在墙(162) + Elsevier 379 主体订阅/IP | 量级同阶，**Elsevier 占比被 173 低估**（见下行） |
| “Elsevier IP/登录墙 ~40~80（子桶）” | **Elsevier = 379（60.4%，第一大桶）** | **规模显著漂移**（173 把 Elsevier 拆小了）；但**“非CF”定性正确** |
| “Elsevier 非 CF” | RG/Academia 镜像 CF ≠ 本体 CF，**证实** | **无漂移 ✅** |
| val500 “ACS80+RSC41=121 http-403，121/149=81%” | still_missing 内 **ACS+RSC=162，403/CF 命中 100%** | 一致并放大（still_missing 口径更严） |
| batch4 “cloudflare-challenge 519 次（事件）” | 跨批曾命中 CF 的**DOI**=307（含镜像）；真出版商 CF=187 | 事件↔DOI 口径不同，**去镜像后 CF 规模比 519 事件小得多**，符合 173“CF 走量有限” |
| P0 QC 闸门“防假阳，必须先做” | 假阳/抓错 = still_missing **第一大成因（65.6%）** | **强化 173 判断 ✅** |
| ROI 排序（路线B / FS / A5机构订阅 / 不做websearch-Elsevier） | 桶结构未变，Elsevier 更大 → A5 权重更高 | **路线判断不漂**，A5 收益上修 |

---

## 六、给 144 的可执行结论（数据侧）

1. **更新决策卡分母**：把 173 的 `44.8% / 551` 全部改为 **`37.1% / 628`**；诚实天花板相应下修（免费路线净增边际不变，但基数更低）。
2. **QC 优先级被数据坐实**：`success-metadata-but-pdf-missing 320 + qc剔错 92 = 412（65.6%）` 是 still_missing 最大成因 → **P0 QC/落盘校验闸门应优先于走量回收**（否则继续制造假阳）。
3. **CF 走量按 187 规划、不是 307**：可回放可救 **120（ACS/Wiley/AIP）** 上 FS shim；RSC 67 交路线B；**Elsevier 不进 CF 计划**。
4. **新可执行点（173 未列）**：**159 条“从未真下载尝试”（157 条 Elsevier）** —— 这些是“无免费候选URL”而非“撞墙”，属 audit156 漏派尾巴，**先补一次带 publisher 直链/机构 Cookie 的首次抓取**即可分流，成本低于破盾。
5. **websearch 双刃**：净成功来源 websearch=146（第一）**同时**是假阳主源 → **保留 websearch 但强制走 QC union 门**（与 173/149 一致）。

---

*核验 2026-07-02｜谷歌学术人机认证-143｜数据源 out/coverage.json(12:13:09) + 全仓 jsonl 并集｜未改任何 .py*
