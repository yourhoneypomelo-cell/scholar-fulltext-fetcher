# still_missing 611 · 机制横切分桶刷新 + 下一波 ROI 排序（喂最终交付『诚实剩余面』）

> 交付：谷歌学术人机认证-149（worker）→ 总指挥｜任务：`task-2f200009-671f-4ab7-a3b4-66e070d0c8ad`（still_missing 611 机制分桶刷新 + ROI，只读）｜2026-07-02
> 边界：**纯只读盘、未改库/未改 coverage/未提交 git、未跑网络**。数据一律取自当前权威 `out/coverage.json`（`generated_ts=2026-07-02 22:19:05`）与 `out/still_missing.txt`（611），用只读脚本 `_tmp_still_missing_bucket_149.py` 重算（分析后即删，不留仓根 cruft）。
> 口径纪律：机制桶互斥、求和=611；**逐批求和虚高一律不用**；发射/过 CF/success ≠ 净增（websearch 68.5% 假阳、ACS `/doi/pdf` ≈93% SI 的前车之鉴，净增带诚实区间）。
> 增量说明：沿用 -142《still_missing620 机制横切》互斥六桶口径，仅**刷新到当前 611**并标注 vs-620 漂移；出版商桶表引用 -150/-142 不重画。
>
> ⚠️ **口径核对（【历史快照】）**：本文 **miss=611 / net=388/999=38.84%**（22:19:05／22:31:41 快照）为**【历史口径】**。**当前权威见 `out/coverage.json`：326 / 673 / 32.63% @2026-07-03 12:50:24, allow=10**（OCR14 −13 已并入；611/388 机制结构分析仍有效、数字勿当当前）。唯一权威 + 历史对照表（620/628/561/388/340/339 等均【历史】）见 **《基线口径冻结说明-388-173.md》**。

---

## 〇、TL;DR（一页给总指挥 · 喂『诚实剩余面』）

- **当前权威地板**：`coverage.json`(22:19:05) = 净成 **388 / 999 = 38.84%**、**miss = 611**（records=611、still_missing.txt=611，**三方一致无漂移**）。QC：原始去重成功 512 → 剔抓错 124（硬 4 + 软 120）+ 白名单免剔 13 → 净 388。
- **611 的机制结构 = 「一堵不可免费越的付费墙（~490~585，A5-only、无凭据 ROI=0）+ 一小撮真免费可救（点估 +13~33，且在收窄）+ 长尾（多需模板/封存）」**——与 -142/-150/-173 诚实天花板**同阶**。
- **最关键漂移信号**：**MDPI 真 OA 桶 7 → 0（已摘干净）**。即 -142/-150 里"唯一真免费抓取净增源"的 route-B 金 OA，**现只剩 RSC 金 OA ~8**（MDPI 7 已回收/回写）。→ **免费果越摘越少，天花板在逼近**。
- **下一波真净增只剩三个正交小池**（都零/近零凭据），且总量比上一波更小：
  1. **T0 翻案池（QC-rejected 124，已下到盘、卡黑名单）** → 现实 **+5~13**（近零成本、最高即时 ROI；但 ACS 58 多为 SI 不可翻、Elsevier 37 多 websearch 错论文，且 allow 已从 4→13 = 已翻 9）。
  2. **route-B RSC 金 OA ~8** → **+4~8**（唯一真免费"抓取"净增，MDPI 已清空）。
  3. **CF-soft OA 子集**（Wiley OnlineOpen 21 + AIP 3 + T&F 3 的真正文，**不含 ACS 91 走量**）→ **+3~9**。
- **免费天花板 ≈ 38.84% → ~40~42% 净覆盖**；**大头 ~490~585（Elsevier 373 + Springer 23 + RSC 订阅 ~59 + ACS 正文/CF-soft 订阅子集 ~100 + 长尾订阅 ~25）唯 A5 机构订阅解，无凭据 ROI=0**。

---

## 一、机制横切主表（互斥分桶，求和 = 611）

| # | 机制桶 | 611 | vs 620(-142) | 主前缀（计数） | 墙型（实证） | 免费可救？ | 建议手段 | 免费净增（诚实） |
|:-:|---|:--:|:--:|---|---|:--:|---|:--:|
| **1** | **CF-hard（JA3 绑定，回放失效）** | **67** | ±0 | 10.1039 RSC=67 | cf_clearance 绑 JA3/TLS，curl_cffi 回放必 403（N.3 锤死） | 仅金 OA 子集 | **route-B 页内直下**（B2 单头串行）；~59 订阅交 A5 | **+4~8**（RSC 金 OA ~8 真命中） |
| **2** | **CF-soft（可回放，不绑 JA3）** | **120** | ±0 | ACS 10.1021=91 / Wiley 10.1002=21·10.1111=1 / AIP 10.1063=3·10.1116=1 / T&F 10.1080=3 | CF403 / Just-a-moment，FS-shim 解 CF 后 curl_cffi 可回放 | **仅 OA/OnlineOpen 真正文子集** | **单干净 FS-shim 串行** + 强制内容 QC | **+3~9**（子集）⚠️见 §二-3 |
| **3** | **403 IP/登录墙（非 CF）** | **373** | −2 | Elsevier 10.1016=368 + 10.1006=5 | 数据中心 IP/登录 403；末次多 no-candidates（无免费候选 URL） | ❌ 免费到顶 | **A5 唯一**（Crossref-PII→`/pdfft`）；免费重跑仅捡 OA 例外 | **0**（无凭据）／有凭据是最大增量 |
| **4** | **订阅墙 no-pdf（常规链路非 CF）** | **23** | ±0 | Springer 10.1007=14 + 10.1023=6 + 10.1134=3 | link.springer.com landing-no-embedded-pdf（订阅落页） | ❌ 免费到顶 | **A5 直取**（`content/pdf/{doi}.pdf` 模板已补齐） | **0**（免费到顶） |
| **5** | **OA 真免费** | **0** | **−7** ★ | 10.3390 MDPI = **0** | Akamai（非订阅墙），真 OA | ✅（已摘干净） | route-B ⑥/定向 impersonate（**本桶已回收清空**） | **0（剩余）**；本波已兑现 |
| **6** | **其它长尾** | **28** | ±0 | JNN 10.1166=4 / CSJ 10.1246=4 / 余 20 前缀各 1（Cambridge/Nature/IOP 家族/OUP/IUCr/IEEE/Science/AnnualRev/Hindawi/SciOpen/中日俄…） | 订阅小社为主，少数 OA | ⚠️ 部分 | publisher_direct 补口；OA 子集常规重跑；余封存/A5 | **+1~3**（OA 子集，小） |
| | **合计** | **611** | −9 | | | | | **免费净增点估 +8~20（不含 T0 翻案）** |

> 求和校验：67+120+373+23+0+28 = **611** ✓（对齐 `coverage.miss=611`、`still_missing.txt=611`）。
> **vs 620 漂移解读**：−9 = **MDPI OA 桶 7 全回收（−7）** + Elsevier −2；且 QC 白名单 allow_override 4→13（+9 翻案/纠误杀已落）、净成 379→388。**净数字仍在动（620→628→611），本表以 22:19:05 快照为准。**

---

## 二、三处诚实校准（防高估，务必并读）

**1. 「免费真 OA」已基本摘干净——MDPI 7→0 是本波最强信号。**
-142/-150 把 route-B 金 OA（MDPI 7 + RSC 8 = 15）列为"唯一真免费抓取净增源、最高 ROI"。**现 MDPI 桶已 0**，route-B 净增只剩 **RSC 金 OA ~8**。→ 免费"抓取"净增的绝对上限已从 ~+15 降到 **~+8**。

**2. 末次原因镜头 ≠ 机制镜头，别用末次口径估硬墙。**
`coverage.records` 末次原因（611）：**claimed-success-no-pdf 288(47.1%)** / no-candidates 130(21.3%) / QC-rejected 124(20.3%) / landing-no-pdf 31(5.1%) / **cloudflare 仅 17(2.8%)** / http-403 7(1.1%)。
- **末次 CF 仅 2.8% 是假低**——多数真 CF 墙 DOI 末次被 recover/websearch 触碰覆盖（-143 已证）；真 CF 结构量看机制桶（桶1+桶2 = 187）。
- **claimed-success-no-pdf 288 + QC-rejected 124 高度重叠**：cleanup 已把抓错论文 PDF 物理移出 `pdfs/`，故这些 DOI 末次转为"声称成功无盘"。**它们不是新的免费机会，是同一批错论文/付费墙人口**，勿当可复下净增走量。

**3. CF-soft 桶（120）的净增大头是"假"的——ACS 正文付费墙陷阱。**
ACS 91 里 FS/route-B 过 CF 拿到的 `/doi/pdf/` **≈93% 是免费 SI 冒充正文**（O.3；-145 逐页 56 条仅 4 真正文，命中 ~12%）。故 **ACS 正文归 A5-only、route-B/FS 边际≈0**；桶2 的 +3~9 只来自 **Wiley OnlineOpen / AIP·T&F OA 真正文极小子集**，且**必须逐页过内容 QC 门③④⑤**才落定。**严禁拿 FS-shim 对 ACS 走量**（会把 SI 当净增）。

> **T0 翻案池画像（QC-rejected 124，按前缀）**：ACS 10.1021=**58** / Elsevier 10.1016=**37** / RSC 10.1039=**12** / Wiley 10.1002=5 / 余（Springer/Nature/IUCr/Science 等）各 1~2。→ 主体 ACS(58) 多 SI 不可翻、Elsevier(37) 多 websearch 错论文；**现实翻案率低（~10~15%）**，交 -147 终裁，点估 +5~13。

---

## 三、下一波 ROI 优先级（供总指挥直接排工）

| 优先级 | 行动 | 对象（611 口径） | 归属 | 前置/依赖 | 净增点估 |
|:--:|---|---|---|---|:--:|
| **P0·近零成本** | **T0 翻案 QC-rejected 池**（已下到盘、卡黑名单，非再抓） | 124（ACS 58 + Elsevier 37 + RSC 12 + 余） | **-147** 终裁（-148 已产 turnkey 清单） | 0 网络；`regress_qc_union_189`+人核；allow 已翻 9 | **+5~13** |
| **P1·免费发射** | **route-B 金 OA 波**（MDPI 已清空，只剩 RSC 金 OA） | RSC 金 OA ~8（`routeB_rsc_goldoa.txt`） | -144/-152 | pypdf+content_qc、concurrency=1、cf-only、B2 单头串行 | **+4~8** |
| **P2·免费子集** | **CF-soft OA 子集** FS-shim | Wiley 21 + AIP 3 + T&F 3 的 OnlineOpen/OA（**不含 ACS 91 走量**） | -145/-155 | **单干净 shim 串行**、过 QC 门 | **+3~9** |
| **P3·近零代码** | **publisher_direct 补口 + 长尾 OA** | 10.1006(5)+RSC-legacy(10.1039 老期)+长尾 OA（Hindawi 10.1155/SciOpen 10.26599 等）| -141/-153 | 离线 selftest 可验；仅 OA 子集免费得 | **+1~3** |
| **P4·凭据 gate** | **A5 机构订阅（主体）** | Elsevier 373 + Springer 23 + RSC 订阅~59 + ACS 正文/CF-soft 订阅子集~100 + 长尾订阅~25 ≈ **~490~585** | -153/用户凭据 | **凭据（永久 gate）** + 会话持久化层 | **0 →（有凭据 +30~40pp）** |
| **❌ 不做/勿高估** | FS 走量 ACS 正文 / browser_search·wayback 扩 Elsevier / 直接报逐批求和 71.4% | — | — | ACS success 多 SI；Elsevier 0/10·0/12 实锤；MDPI 已清空 | ≈0 |

**排期节奏**：P0（T0 翻案，零网络，先落地板）→ P1（route-B RSC 金 OA ~8，算力小）→ P2（单 shim CF-soft OA 子集，过 QC）→ 汇总 P0~P2 真净增（务必过门）→ P3（补口，凭据到手即生效）→ P4（A5 待凭据，不投人日）。

---

## 四、结论一句话（喂『诚实剩余面』）

**still_missing 现 611 / 净覆盖 38.84%（coverage.json 22:19:05，三方一致无漂移）；按机制横切，~490~585（Elsevier 373 + Springer 23 + RSC 订阅 ~59 + ACS 正文/CF-soft 订阅子集 ~100 + 长尾 ~25）是免费物理到顶的付费墙、唯 A5 机构订阅解、无凭据 ROI=0；本波最强信号是 MDPI 真 OA 桶 7→0 已摘干净，免费"抓取"净增只剩 route-B RSC 金 OA ~8；下一波真净增仅在三个正交小池——T0 翻案（+5~13，近零成本、最高即时 ROI）、route-B RSC 金 OA（+4~8）、CF-soft OA 子集（+3~9，须防 ACS-SI 陷阱）——免费天花板 ~40~42% 净覆盖，破此上限唯机构订阅 A5。发射/过 CF/success ≠ 净增，每一笔过内容 QC 门。**

---

## 五、来源与方法

- 权威地板：`out/coverage.json`（`generated_ts=2026-07-02 22:19:05`；summary: total 999 / 净成 388 / miss 611 / 38.84%；qc: before 512 / 剔 124(硬4+软120) / allow 13 / after 388）、`out/still_missing.txt`（611，三方一致）。
- 机制横切重算：只读脚本 `_tmp_still_missing_bucket_149.py`（载 coverage.json → 按 DOI 注册前缀映射机制桶 → 互斥求和 611 → 末次原因/QC-rejected/claimed-no-pdf/长尾前缀交叉），**分析后即删、不留仓根 cruft、不提交 git**。
- 桶口径/墙型实证（引用不重画）：`检索成果-still_missing620机制横切分桶与下一波ROI优先级-142.md`、`检索成果-still_missing628全量ROI与优先级排序-150.md`、`检索成果-still_missing-CF-JA3桶ROI深挖-173.md`、`本波回收交付汇总.md`、`回收实测结论-CF与免费路线到顶.md`；`经验记录-踩坑与发现.md` N.3（ACS 不绑 JA3 / RSC 绑 JA3）、N.4/N.8（route-B ROI）、O.3（ACS `/doi/pdf` ≈93% SI）、L/M（websearch 假阳）。

---
*核验 2026-07-02｜-149｜任务 task-2f200009｜纯只读、未改库/coverage/git、未跑网络｜机制六桶求和 611 三方一致；MDPI OA 桶 7→0（本波最强信号）；免费天花板 ~40~42% 净覆盖，主体 ~490~585 唯 A5；下一波 = P0 T0 翻案(+5~13)→P1 route-B RSC 金OA(+4~8)→P2 CF-soft OA 子集(+3~9)，防 ACS-SI 陷阱、每笔过 QC。*
