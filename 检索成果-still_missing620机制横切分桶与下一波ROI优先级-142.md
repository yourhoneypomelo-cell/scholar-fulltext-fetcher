# still_missing 620 · 机制横切分桶（墙型×可救性×手段×净增）+ 下一波 ROI 优先级

> 交付：**谷歌学术人机认证-142**（worker）→ 总指挥 **-148**｜2026-07-02｜taskId=`task-3496f270-f9e2-499c-8fb0-6ea6fed9a359`
> 边界：**纯文档、只读**，只新建本 1 份 md，**未改任何 `.py`、未跑网络、未回写 coverage**。数据取自 `out/coverage.json`（18:25:56，-151 增量回写A 已落盘）、`out/still_missing.txt`（620，头 2 行注释）、`_gap_pubdirect_152.py` 在 620 上重跑、`out/_writeback151_removed_from_still_missing.txt`。
> **增量定位（不重复造表）**：-150《628 全量 ROI》/-143《628 分桶刷新》/-142《回写后 561→620 分桶》都是**按出版商桶**排的；本文换一个正交视角——**按破盾机制/墙型横切**（CF-hard / CF-soft / 403-IP / 订阅墙 no-pdf / publisher_direct 路由缺口 / OA / 长尾），落到 **-151 确认地板 620**，只补机制维度，publisher 桶表一律引用不再重画。
> **口径纪律**：发射/过 CF/success ≠ 净增；真命中 = 过 CF/取到 + 内容 QC 门③④⑤（websearch 68.5% 假阳、ACS success 多为 SI 的前车之鉴）。净增带诚实区间。
>
> ⚠️ **净覆盖率口径统一（173 冻结）**：本文标题/正文的 **620 miss、379/999=37.9% net**（@18:25:56 快照）均为**【历史口径】**。**【历史快照】当前权威见 `out/coverage.json`：326 success / 673 miss / 999 = 32.63%**（generated_ts 2026-07-03 12:50:24, allow_override=10）。机制横切分桶视角仍有效，唯 miss 总数以 611 为准。唯一权威 + 历史对照表 + 待并入项见 **《基线口径冻结说明-388-173.md》**。

---

## 〇、TL;DR（给 -148 的一页）

- **权威地板已落盘**：`coverage.json`(18:25) = 净成 **379 / 999 = 37.9%**、**miss = 620**（-151 增量回写A 剔 8 条真正文：4 ACS + 4 Elsevier）。still_missing.txt 头写 620、shard 求和一致，**无内部漂移**。
- **620 的机制结构 = 「一堵不可免费越的付费墙（~500，A5-only、无凭据 ROI=0）+ 一小撮真免费可救（OA/金OA/翻案，点估 +17~42）+ 长尾（多需模板或封存）」**——与 -150/-142/-173 的诚实天花板结论**同阶、未漂**。
- **下一波真净增只来自 3 个正交小池**（都零/近零凭据）：
  1. **T0 翻案 99 条 PENDING**（已下到盘、卡旧黑名单）→ 近零成本、**确认 +5 / 现实 +11~13**（-148 已产 turnkey 清单，交 -147 终裁）。**最高即时 ROI。**
  2. **route-B 金 OA 发射波**：MDPI 7 + RSC 金 OA 8 = **15**（清单已产）→ **+8~14**。**唯一真免费"抓取"净增源。**
  3. **CF-soft OA 子集**（Wiley/AIP/T&F OnlineOpen/authorchoice 真正文）→ **+3~11**（单干净 shim、过 QC）。
- **免费天花板 ≈ 37.9% → ~39~42% 净覆盖**；**大头 Elsevier 375 + 订阅子集 ≈500 只能靠 A5 机构订阅**（凭据永久 gate、现 ROI=0）。**521/47.8% 是全翻理论上限，已被 -148 逐条判死，不可对外报。**

---

## 一、机制横切主表（互斥分桶，求和 = 620）

> 桶按"破盾机制/墙型"切，与出版商桶正交但可换算（见括注前缀）。**"可救"指免费手段真净增潜力**，非"有 handler / 能发射"。

| # | 机制桶 | 条数 | 主前缀（出版商） | 墙型（实证） | 免费可救？ | 建议手段 | 预计免费净增（诚实） |
|:-:|---|:--:|---|---|:--:|---|:--:|
| **1** | **CF-hard（JA3 绑定，回放失效）** | **67** | 10.1039 RSC | cf_clearance 绑 JA3/TLS，curl_cffi 回放必 403（N.3 锤死） | 仅金 OA 子集 | **route-B 页内直下**（②b→B2 单头串行）；59 订阅交 A5 | **+4~8**（RSC 金 OA 8 的真命中） |
| **2** | **CF-soft（可回放，不绑 JA3）** | **120** | ACS 91(10.1021) + Wiley 22(10.1002/10.1111) + AIP 4(10.1063/10.1116) + T&F 3(10.1080) | CF403 / Just-a-moment，FS-shim 解 CF 后 curl_cffi 可回放 | **仅 OA/authorchoice 真正文子集** | **单干净 FS-shim 串行**过 CF + 强制内容 QC | **+3~11**（子集）⚠️见 §三-1 |
| **3** | **403 IP/登录墙（非 CF）** | **375** | 10.1016(370)+10.1006(5) Elsevier | 数据中心 IP/登录 403；末次多为 no-candidates（无免费候选 URL） | ❌ 免费到顶 | **A5 唯一解**（Crossref-PII→`/pdfft`）；免费轻量重跑仅捡 OA 例外 | **0**（无凭据）／有凭据是最大增量 |
| **4** | **订阅墙 no-pdf（常规链路非 CF）** | **23** | 10.1007(14)+10.1023(6)+10.1134(3) Springer | link.springer.com landing-no-embedded-pdf（订阅落页） | ❌ 免费到顶 | **A5 直取**（`content/pdf/{doi}.pdf`，模板已补齐） | **0**（免费到顶） |
| **5** | **OA 真免费** | **7** | 10.3390 MDPI | Akamai（非订阅墙），真 OA | ✅ | **route-B ⑥ / 定向 impersonate** | **+5~7** ← 真免费净增 |
| **6** | **其它长尾** | **28** | JNN 10.1166(4)/CSJ 10.1246(4)/IOP 家族/中日俄小社/Nature·Science·AnnualRev 各1 | 订阅小社为主，少数 OA | ⚠️ 部分 | 见 §二 publisher_direct 补口；OA 子集常规重跑；余封存/A5 | **+1~4**（OA 子集，小） |
| | **合计** | **620** | | | | | **免费净增点估 +13~30（不含 T0）** |

> 求和校验：67+120+375+23+7+28 = **620** ✓（对齐 `coverage.miss=620`、still_missing.txt、shard 并集）。

---

## 二、publisher_direct 路由缺口（横切视角，44 条 · 与主表重叠不另计入 620）

> 在 620 上重跑 `_gap_pubdirect_152.py`：有 handler（static+xref）**576（92.9%）**，**真缺口 44（7.1%）**。⚠️ 缺口是**横切**（10.1006⊂桶3、RSC-legacy⊂桶1、AIP⊂桶2），故不并入 §一 互斥求和。**vs -150/-152 的漂移：10.1023/10.1134（Springer 兄弟）与 10.1080（T&F）已由 -141 补进 static 模板、现判 COVERED**，缺口从 53→44。

| 缺口子类 | 条数 | 前缀 | 补口手段（近零代码成本） | 免费净增性质 |
|---|:--:|---|---|---|
| 老 Elsevier | 5 | 10.1006 | 把 `_elsevier` 的 Crossref-PII 触发从"仅 10.1016"扩到含 10.1006 | ⚠️ 仍订阅 → 主要为 A5 铺路 |
| RSC 遗留期 | 10 | 10.1039 a/b/tf 老期 | **新增 `_rsc_legacy()` Crossref 分支**（取 jcode+年份，非扩正则，-141 §三已给规格） | ⚠️ 仍订阅/CF → A5 或 route-B |
| AIP/AVS | 4 | 10.1063/10.1116 | Atypon `/doi/pdf/{doi}` 静态模板 | 属桶2 CF-soft，OA 子集可救 |
| 长尾小社 | 25 | JNN/CSJ/IOP 家族/Cambridge/OUP/IUCr/IEEE/中日俄… | 各社独立模板，ROI 递减 | 多订阅，OA 子集小 |

> **补口 ROI 判词**：`补 handler ≠ 下到 PDF`——publisher_direct 是**机构订阅路径**，无凭据打直链回 401/403/HTML 被 `%PDF` 校验挡（不产假阳）。故补口的**免费**净增仅落在其中 OA 子集（小）；真价值是**凭据到手后 A5 放量的前提**。建议只做「10.1006 + RSC-legacy + AIP/IOP 家族」这批**同族可复用**的（-152 §四"先做 1+2+3"思路），长尾押后。

---

## 三、两处必须并读的诚实校准（防高估）

**1. CF-soft 桶（120）的净增大头是"假"的——ACS 正文付费墙陷阱。**
ACS 91 里，FS/route-B 过 CF 拿到的 `/doi/pdf/` **~93% 是免费 SI（补充材料）冒充正文**（O.3）；-145 对 rerun_acs_144 **逐页看 56 条 → 仅 4 真正文（命中率 ~12%）**。故 **ACS 正文归 A5-only、route-B/FS 边际≈0**；桶2 的 +3~11 净增只来自 **Wiley OnlineOpen / AIP·T&F OA / ACS authorchoice 真正文极小子集**，且**必须逐页过内容 QC**才落定。**严禁拿 FS-shim 对 ACS 走量**（会把 SI 当净增）。

**2. 末次原因镜头 vs 机制镜头——别用末次口径估硬墙。**
`coverage` 末次原因（620）：no-candidates 248(40%) / QC-rejected 129(20.8%) / CF-403 72(11.6%) / landing-no-pdf 69(11.1%) / success-但无 PDF 63(10.2%) / http-403 15。**末次 CF 仅 11.6% 是假低**——多数 DOI 末次被 recover/websearch 触碰、覆盖了 batch6 真 CF 墙（-143 已证）。**no-candidates 248 主体是 Elsevier「无免费候选 URL」**（=桶3 的 403-IP 墙在末次口径的投影），印证"免费到顶、唯 A5"。**规划用机制镜头（§一），不用末次镜头。**

---

## 四、下一波 ROI 优先级（供 -148 直接排工）

| 优先级 | 行动 | 对象（620 口径） | 归属 | 前置/依赖 | 净增点估 |
|:--:|---|---|---|---|:--:|
| **P0·近零成本** | **T0 翻案 99 条 PENDING**（已下到盘、卡旧黑名单，非再抓） | 横切池 99（28 ACS + 71 非 ACS） | **-147** 终裁（-148 已产清单） | 0 网络；`regress_qc_union_189`+人核 | **确认 +5 / 现实 +11~13** |
| **P1·免费发射** | **route-B 金 OA 波** | MDPI 7 + RSC 金 OA 8 = **15**（`routeB_mdpi.txt`/`routeB_rsc_goldoa.txt` 已产） | -152/-146 | pypdf+content_qc、concurrency=1、cf-only | **+8~14** |
| **P2·免费子集** | **CF-soft OA 子集** FS-shim | Wiley 22 + AIP 4 + T&F 3 的 OA/OnlineOpen（**不含 ACS 走量**） | -145/-155 | **单干净 shim 串行**、过 QC 门 | **+3~11**（子集） |
| **P3·近零代码** | **publisher_direct 补口** | 10.1006(5)+RSC-legacy(10)+AIP/IOP 家族 | -141/-153 | 离线 selftest 可验；OA 子集才免费得 | **+1~3**（免费）／铺 A5 |
| **P4·凭据 gate** | **A5 机构订阅（主体）** | Elsevier 375 + Springer 23 + RSC 订阅 59 + ACS 正文/CF-soft 订阅子集 ≈ **500** | -153/用户凭据 | **凭据（永久 gate）**+会话持久化层 | **0 →（有凭据 +35~40pp）** |
| **❌ 不做/勿高估** | FS 走量 ACS 正文 / browser_search·wayback 扩 Elsevier / 直接报 521·47.8% | — | — | ACS success 多 SI；Elsevier 0/10·0/12 实锤；99 全翻已判死 | ≈0 |

**排期节奏**：P0（T0 翻案，零网络，先落 +5 地板）→ P1（route-B 15，今日可跑、算力小）→ P2（单 shim CF-soft OA 子集、过 QC）→ 汇总 P0~P2 真净增（务必过门）→ P3（补口，凭据到手即生效）→ P4（A5 待凭据，不投人日）。

---

## 五、结论一句话

**still_missing 已从 628 收敛到 -151 确认地板 620 / 37.9%**；按机制横切，**~500（桶3 Elsevier 375 + 桶4 Springer 23 + CF/长尾订阅子集）是免费物理到顶的付费墙、唯 A5 解、无凭据 ROI=0**；**下一波真净增只在三个正交小池**——T0 翻案（+5~13，近零成本，最高即时 ROI）、route-B 金 OA（+8~14，唯一免费抓取源）、CF-soft OA 子集（+3~11，须防 ACS-SI 陷阱）——**免费天花板 ~39~42% 净覆盖，破此上限唯机构订阅 A5**。发射/过 CF/success ≠ 净增，每一笔都过内容 QC 门。

---

## 六、来源

- 权威地板：`out/coverage.json`（18:25:56，summary: total 999 / success 379 / miss 620 / 37.94%）、`out/still_missing.txt`（620）、`out/_writeback151_removed_from_still_missing.txt`（-151 剔 8 条：4 ACS 真正文 + 4 Elsevier）。
- 机制横切与缺口：本文在 620 上重跑 `_gap_pubdirect_152.py`（static 199 / xref 377 / gap 44）+ `coverage.records` 末次原因聚合（620）。
- 对齐引用（不重画）：`检索成果-still_missing628全量ROI与优先级排序-150.md`、`检索成果-still_missing回写后561分桶与下一波ROI-142.md`（-151 确认 +8→620）、`检索成果-still_missing-CF-JA3桶ROI深挖-173.md`、`检索成果-still_missing628分桶统计刷新-vs173漂移核对-143.md`、`检索成果-publisher_direct缺口扫描-152.md`、`A5机构订阅现状与still_missing可救前缀梳理-150.md`、`检索成果-T0预筛still_missing翻案99条-内容QC逐条-148.md`（T0 turnkey）。
- 墙型/净增实证：`经验记录-踩坑与发现.md` N.3（ACS 不绑 JA3 / RSC 绑 JA3）、N.4/N.8（route-B ROI）、N.7（多 shim thrash）、O.3（ACS `/doi/pdf` ~93% SI）、L/M（websearch 假阳 + recover_b4_cf 真净增≈4%）。

---
*核验 2026-07-02｜-142 worker · 工单 -148｜纯文档只读，未改代码/未跑网络/未回写 coverage｜机制横切求和 620 三方一致；免费天花板 ~39~42%，主体 ~500 唯 A5；下一波 = P0 T0 翻案(+5~13)→P1 route-B 金OA(+8~14)→P2 CF-soft OA 子集(+3~11)，防 ACS-SI 陷阱、每笔过 QC。*
