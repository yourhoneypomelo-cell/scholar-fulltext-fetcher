# 检索成果 · still_missing **673** 分桶刷新 + 次波 ROI 排序（176 波）

> 交付：**谷歌学术人机认证-144**（秘书·数据/coverage）｜2026-07-03 21:08｜聚合 187/146/142/148 四桶 → **一张** ROI 排序表。
> 纪律：**只读盘 + 只新建本 1 份 md**；未改 coverage/still_missing/黑名单/`.py`(除只读分析脚本)/git、未发射 route-B、未跑真下载。
> 权威源：`out/coverage.json`（**定版 2026-07-03 12:50:24**：**326/673/32.63%**）、`out/still_missing.txt`（673）、`out/_nextwave_176_backbone_144.json`。
> 口径纪律：发射/过 CF/success ≠ 净增；净增必过内容 QC 门③④⑤；表中『诚实净增』为 owner 规划折算(过QC/实测前)，非承诺。

> 四桶到齐：187 CF/Turnstile=✅ ｜ 142 聚合源/OA=✅ ｜ 146 订阅墙/A5(spine)=✅ ｜ 148 QC-flip=✅

---

## 〇、TL;DR（一页给总指挥）

| 指标 | 定版值 | 备注 |
| --- | ---: | --- |
| 净成功 success（QC后） | **326** | merge 链定版 |
| still_missing / miss | **673** | 三方一致 |
| 净覆盖率 | **32.63%** | total=999 |
| **唯 A5 可救（定版·严口径）** | **529**（78.6%） | 无凭据净增=0；乐观上界 602 |
| (A) 免费下载捞取净增 | **+3**（0~21） | CF 2(扣p2在途)+非CF-OA 2 |
| (B) **QC翻案纠偏**(148·待144写盘) | **+59** gold（+15待复→74） | 开卷 doi_in_body 金判据；examined 346 |
| 覆盖率天花板（点估） | 下载~32.9% ｜ +高置信翻案 **~38.8%** ｜ +全翻案 ~40.3% | (success+净增)/999 |

- **一句话（修订）**：miss 主体 **529/673=79% 唯 A5**（订阅墙，无凭据净增 0）；纯**免费下载**天花板仅 **~32.9%**，但 **148 开卷翻案纠偏 +59~74** 可把覆盖推至 **~39~40%**——**若翻案经 144 复核落盘，则不靠 A5 亦可逼近/破 40%**（修订 174 波『破40%唯A5』结论）。
- **⚠️ 翻案是 coverage 纠偏（miss→success），须 144 单写 + 开卷逐条复核 + 备份，严防打穿 326；本波只读未写盘**。
- **排工**：**P0=144 复核 148 高置信翻案 59 → 写盘**（最大杠杆）→ Wiley route-B/OA 长尾下载捞取(+3) → A5 gate 不投人日（唯凭据破局）。
- **撞车域（硬）**：`out/.route_b.lock` / `out/p2_cf_soft_155/.route_b.lock` 单头浏览器；FlareSolverr 单干净 shim 串行。

---

## 一、规模与三方一致性（定版）

| 口径 | 数值 | 来源 |
| --- | ---: | --- |
| total_unique_dois | 999 | coverage.summary |
| 净成功 success | **326** | coverage.summary |
| still_missing / miss | **673** | summary = still_missing.txt |
| 净覆盖率 | **32.63%** | 326/999 |

> **三方一致**：still_missing.txt=673 = summary.miss=673；backbone publisher 求和=673；146 分类 tier_sum=673=673 ✓。

---

## 二、出版商桶 × 唯A5 占比（miss **673**）

| 出版商 | miss | 占比 | 唯A5(146严) | A5占比 | 墙型 |
| --- | ---: | ---: | ---: | ---: | --- |
| **elsevier** | 380 | 56.5% | 357 | 94% | IP/登录 **非CF** → A5 |
| **acs** | 132 | 19.6% | 99 | 75% | CF403不绑JA3；authorchoice子集免费 |
| **rsc** | 71 | 10.5% | 18 | 25% | CF绑JA3+governor→route-B≈0 |
| **wiley** | 28 | 4.2% | 14 | 50% | CF→route-B pdfdirect子集 |
| **other** | 27 | 4.0% | 12 | 44% | 混桶长尾 |
| **springer** | 24 | 3.6% | 24 | 100% | 常规订阅**非CF**→A5 |
| **aip** | 4 | 0.6% | 1 | 25% | 非JA3 CF→FS |
| **iop** | 4 | 0.6% | 4 | 100% | 常规/摘要→A5 |
| **taylor_francis** | 3 | 0.4% | 0 | 0% | 非JA3 CF→FS |
| **合计** | **673** | 100% | **529** | **79%** |  |

---

## 三、146 机构-A5 MECE 分区（互斥·求和=529+73+59+11+1=673）

| 分区 | 条数 | 净增 | 读法/归属 |
| --- | ---: | :--: | --- |
| **唯A5可救**（严口径·定版） | 529 | **0** | 订阅墙确证(no-oa/abstract/403/qc-wrong)；凭据 gate |
| CF-uncertain | 73 | 见§四 | = 187 CF 池(ACS免费/Wiley route-B/SD-A5/RSC-cf) |
| dataqc-recheck | 59 | 见§四 | claimed-no-pdf/qc-wrong → 148 开卷翻案池 |
| network-other | 11 | ~0 | 瞬时网络错，常规重试 |
| free-OA | 1 | ~+1 | Hindawi 等纯OA(已在CF免费/OA桶) |

> **146 政策问询→144 定版**：Elsevier/Springer 是否『整社计入A5』?
> - 严口径（**定版采用**）：Elsevier 357 / Springer 24 → A5-only **529**。
> - 整社上界（仅参考）：Elsevier 380 / Springer 24 → 乐观上界 **602**。
> - **144 裁定**：headline 认**严口径 529**（剔 Elsevier 15CF+8网络，留 route-B 抽验与卫生复核后再谈），A5 上界 602 仅作凭据到位潜力参考。

---

## 四、次波 ROI 排序表（**核心** · owner 净增 · 按行动优先级）

| 优先级 | 行动/桶 | 归属 | 候选DOI | 诚实净增(owner) | is_A5 | 手段 | 状态 |
| :--: | --- | :--: | :--: | :--: | :--: | --- | :--: |
| **P0·纠偏** | **QC-rejected 开卷翻案** | 148 | 62(+15复) | **+59** gold(+15待复) |  | 开卷doi_in_body→**144写盘**(无网络) | ✅ |
| P0·免费 | CF 免费可救(非JA3/authorchoice/OA) | 187 | 40 | CF池 **+2**(0~5) |  | FS-shim curl_cffi 回放(多与p2重叠) | ✅ |
| P1·免费 | 聚合非CF-OA长尾(IOP/中文/JM…) | 142 | 16 | +0~16(点2) |  | OA route-B-B1/publisher_direct | ✅ |
| P1·免费 | Wiley route-B pdfdirect(唯一新杠杆) | 187 | 14 | ↑并入CF池 +2 |  | route-B 页内直下(nodriver) | ✅ |
| P2·抽验 | CF-SD-A5 抽验 + RSC route-B | 187 | 86 | ≈0(-160实测RSC net≈0) | ≈✅ | route-B抽验(SD-OA/RSC governor) | ✅ |
| P2·卫生 | network-other 重试 | 146 | 11 | ~0 |  | 常规重试 | ✅ |
| P3·gate | 唯A5可救(订阅墙) | 146 | 529 | **0**（无凭据） | ✅ | A5 机构订阅(EZproxy/CARSI/SSO) | ✅ |

**净增合计**：(A) 免费下载捞取 **+3**（0~21；CF 2+OA 2，去Hindawi重复1） ｜ (B) **QC翻案纠偏 +59~74**（高置信59/全候选62，无网络，待144写盘）。
> A 属真下载新增（扣 p2 在途双计后偏低）；B 属数据卫生纠偏（open-book 已验，落盘即得），**两者机制不同、可叠加**。

> ⚠️ **诚实折损/冲突（务必读）**：
> 1. **CF免费 与在途 `p2_cf_soft_155`(-145/-155) 重叠**：187『免费可救 40』含 ACS authorchoice，为技术可救上界；本波新增取低端（-173 recover_b4_cf 27→真5）。
> 2. **142 非CF-OA point=2** 已扣 RSC金OA8(governor-gated,新增≈0)；`high=16` 勿当点估。
> 3. **跨worker冲突**：142 判 IOP `10.1149/1945-7111/acc6f7`、`10.35848/1347-4065/ad280f` 为免费OA可救；146 归其 **iop A5-only(abstract-only)**。差异 2 条(net≈±2)，**建议次波 route-B-B1 实测定谳**。
> 4. **Hindawi `10.1155/2014/690514`** 同时被 187(CF免费) 与 142(OA) 认领，净增只计 1。

---

## 五、覆盖率天花板与 A5 占比（修订）

| 情形 | 覆盖率 | 说明 |
|---|---:|---|
| 现状（定版） | 32.63% | 326/999 |
| + 纯免费下载捞取 | ~32.93% | +3（CF+OA+Wiley route-B，扣 p2 在途） |
| **+ 高置信 QC 翻案** | **~38.84%** | +59（148 gold doi_in_body，待 144 写盘） |
| + gold + needs_review | ~40.34% | +74（gold 59+待复核 15，**过40%**） |

- **唯 A5 可救 529**（占 miss 78.6%；乐观上界 602=89.5%）：无凭据净增=0。
- **翻案×A5 交集**：148 翻案候选中有 **34** 条落在 146 的 A5-only 529 内 → 若翻案落盘，这些直接离开 miss，**A5-only 实际收敛到 ~495**（73.6%），二者不可重复计。
- **待写盘净数据卫生（144 单写下一波·双向）**：**+59 翻案**（148 gold）**− 8 websearch 假阳**（143 巡检：`_websearch_fp7_hardblack_append_141.csv`∪`_mon157_websearch3_hardblack_append.csv`，含同一 355744B 错PDF 套 3 DOI）= **净 +51**；叠免费下载 +3 → success 326→~380、**覆盖 ~38.04%**。⚠️ 口径：以**当前 326** 为准（非 157 文档 01:27 旧基线 339→336）。
- **结论修订**：174 波『破 40% 唯 A5』**部分翻案**——纯下载确到顶(~32.9%)，但 **QC 开卷翻案纠偏（数据卫生，非新下载）可把覆盖推到 ~38.8~40.3%**，高置信 59 逼近 39%、含待复核 15 触 40%。**再往上仍唯 A5**。

---

## 六、来源与方法

- 权威地板：`out/coverage.json`（定版）、`out/still_missing.txt`（673）、`out/_nextwave_176_backbone_144.json`（144 backbone）。
- 四桶：`_nextwave_176_cf_turnstile.json`(187) / `_aggregator_oa.json`(142) / `_subscription_a5.json`(146,spine) / `_qc_flip.json`(148)。
- 聚合：`_nextwave176_aggregate_144.py`（本 md 确定性生成，146 MECE 分区为骨、187/142/148 net 叠加，可复跑）。
- 净增口径：采 owner `net_gain_expect`（过内容QC后诚实新增，非 raw success）；A5=0（凭据 gate）。
- 沿用（不重画）：《检索成果-still_missing分桶统计刷新与下一波ROI-174.md》《A5机构订阅现状与still_missing可救前缀梳理-150.md》《基线口径冻结说明-388-173.md》。

*核验 2026-07-03 21:08｜-144｜纯只读、未改库/coverage/git、未发射 route-B｜三方一致 326/673/32.63%｜四桶 全齐✅。*
