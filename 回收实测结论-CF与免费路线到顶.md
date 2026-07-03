# 回收实测结论 · Cloudflare 与免费路线到顶（本轮沉淀）

> 交付：组员 **-149**｜2026-07-02｜工单来源：总指挥 **-156**「新建《回收实测结论-CF与免费路线到顶》（沉淀）」（taskId=`task-3c8609ee-4216-40bb-97ce-3db5d4a56a93`）。
> 边界：**只新建本 1 个文件**，不改他人文档 / 任何 `.py`；证据均引自已提交文档与本人实测产物（引用见文末「证据索引」）。
> 定位：把本轮「CF 破盾 + 免费兜底到顶」的实测结论集中固化一处，供总指挥/接手者直接引用，避免散落各处重复踩坑。
>
> ⚠️ **净覆盖率口径（定版 2026-07-03）**：**唯一权威 = `out/coverage.json` `summary`：326 success / 673 miss / 999 = 32.63%**（`generated_ts=2026-07-03 12:50:24`，`allow_override=10`）。已剔 batch6 ACS SI 33 + websearch 假阳 9 + OCR13 等。本文内 **340/659/34.03%（00:42:19）**、**339/660（01:27:42）**、**448/44.8%**、**388/38.84%**、逐批求和 **71.4%** 均属**【历史口径 / 理论上限】**。对照表见 **《基线口径冻结说明-388-173.md》**（已 re-freeze 至 326）。

---

## 〇、TL;DR（一句话）

**免费手段的主矛盾已从「定位不到候选」转成「定位到候选却下不动」——墙集中在 Cloudflare JS 质询与出版商 403/登录墙上。** 破法分两类：
- **Cloudflare「Just a moment」桶**（ACS-authorchoice / AIP / Wiley / OUP / T&F，连 ResearchGate·ChemRxiv 逃生口也进了 CF）→ **FlareSolverr / nodriver-shim 真解 `cf_clearance` 可救**（ACS 已实测可下到 PDF；**但 authorchoice 桶 ~93% 为 SI，QC 净增真正文 ≈1**）。**RSC：FS+curl_cffi 回放 ROI≈0**；**route-B 浏览器内直下对金 OA 子集仍有 +N**（与 FS 破盾是两条线）。
- **Elsevier（ScienceDirect）IP/登录墙（非 CF）** 与 **纯订阅 403 付费墙（ACS/RSC 订阅刊）** → **免费路线已到顶**：`browser_search` 0/10、`wayback` 0/12 双双 0，唯一干净出路是机构订阅。

> 🔴 **同等重要的质量警报（详见 §〇补）**：websearch 系统性「错论文」假阳。**当前权威净覆盖 = 326/999 = 32.63%**（`coverage.json` 12:50:24，已剔 SI 33 + ws9 + OCR13 等）。〔历史：340/659（00:42:19）、339/660（01:27:42）、448/44.8%、388/38.84% 为演进快照〕**websearch 主线可信率点估 ≈33%**。故「CF/免费路线到顶」与「内容闸门去伪」**两件事叠加**才是诚实现状。

---

## 〇补、内容级质量审计：websearch 假阳（错论文）+ 净覆盖率修正（本轮最大发现，150 沉淀）

> 沉淀者 **-150**｜工单来源：总指挥 **-156**「沉淀本轮最大发现：websearch 错论文假阳 QC 全过程 + JA3/straggler/免费天花板」（taskId=`task-8cbd3c65…`）。证据均引自本仓已产出的 `out/qc_content_report.{json,md}`、`out/qc_uncertain_sample_verify.{csv,md}`、`out/qc_merge_*_wrong.csv`、`out/coverage.json` 与经验记录 **L 节**（可检索详版）。

**为什么它和「CF/免费到顶」一样重要**：前面几节讲的是「还有多少下不到」；这一节讲「已经下到的里有多少是**错的**」。二者叠加才是诚实的项目现状。

### 1. 假阳规模（`tools/qc_content_match.py` 内容级复扫）
- 复扫 **645 条 websearch success**：match **166** / mismatch(错论文) **361** / uncertain **88** / scanned **29** / unreadable **1**。
- **假阳率 A（mismatch / 可判定 527）= 68.5%**；**假阳率 B（/ 全部 645）= 56.0%**（下界）。→ 可判定的 websearch 命中里**约 2/3 是错论文**。
- **uncertain 带 = 漏网假阳，非误杀**：-153 抽 40 条人校（seed=42）→ **match 0 / mismatch 40 = 100% 错**；据此主线可信率由区间 33–43% **收窄为点估 ≈ 33%**（下沿）。
- **DOI-keyed 源全 0% 假阳、干净**（unpaywall/openalex/europe_pmc/crossref/s2/publisher_oa）——链接由 DOI 权威解析，天然不会错配；假阳是 websearch「搜索引擎取首个 PDF」独有的病。

### 2. 四类系统性错误模式（`systematic_patterns`）
| 模式 | 条数 | 含义 / 实例 |
|---|---:|---|
| ① junk_domain 垃圾域 | 40 | 同一域被塞给 ≥3 种 DOI 前缀且 0 命中：`escholarship.org`(13/4前缀)、`pubs.acs.org`(11/4)、`patentimages…googleapis`(8/4)；`frontiersin.org` 通配一个 public PDF 给多个不相干 DOI |
| ② same_pub_wrong_doi 同社错论文 | 155 | 正文含同前缀异后缀 DOI（同社另一篇） |
| ③ cross_pub_wrong_doi 跨社错论文 | 193 | 正文含他社前缀 DOI（物理 DOI→PNAS/NEJM/皮肤病学 JAAD） |
| ④ future_year 未来年份 | 92 | served 年份 > 目标 DOI 年份（2025/26 DOI 配旧文，物理不可能） |

经典铁证：`10.1002/cssc.201601217`(ChemSusChem) 落盘成 `jaad.org` 皮肤病学论文（正是 §一里 FlareSolverr「救回」的那条——**FS 会忠实地把错候选也下载成功，FS 成功 ≠ 正确全文**）。

### 3. 双法定案（交集→并集返工，precision 优先）
- **法A｜151 内容标题法**（pypdf 抽正文比标题/DOI，mismatch 精确率 ~100%）：独揪**同域错论文**——publisher 桶 **62** + repository 桶 **129**（≈189–191 条，审计域法判不了的同社/仓库托管错论文）。
- **法B｜审计 URL 域×DOI 前缀 / 嵌入 DOI 法**：揪**跨社**铁证（下限）。
- **产物（供 `build_coverage` 消费）**：`out/qc_merge_highconf_wrong.csv`（**54** 硬黑，两法都判错）∪ `qc_merge_union_wrong.csv`（**391** 并集）；`qc_merge_151match_url_conflict.csv`（**16** 条 151 判 match 但下载域与 DOI 冲突的假匹配，需人核）；`qc_rejected_manifest.csv`（**391** 已物理移入各批 `rejected/` 的地面真相）。
- ⚠️ 教训：早期「两法**交集**」漏检太多，**140 已返工为并集**并补同社错论文 selftest。

### 4. 净覆盖率修正（`tools/build_coverage.py` → `out/coverage.json`）
- **当前权威净成功 = 326 / 999 ≈ 32.63%**（`generated_ts 2026-07-03 12:50:24`：`success_before_qc=514` 剔 **188**〔硬 33 + 软 155〕+ allow **10** → **326**；OCR14 −13 已并入）。〔340/34.03%@00:42:19 为【历史中途】〕
- **对比**：逐批 metadata 求和 ≈ **71.4%** 为**【理论上限·虚高】**。**读报告认 326/32.63%，不认 71.4%/448/388/340/339**。
- **已落盘卫生下修**：batch6 ACS SI **33** + websearch 假阳 **9**（-176/-169）等并入黑名单；推翻旧口径「ACS 4 真正文」→ **≈1**（`acscatal.0c04429`）。
- **MDPI7 route-B 已回写**（`browser_pdf_download`×7），非「待救」。

---

## 一、FlareSolverr 实测：ACS-authorchoice 的 CF403 可真解为 PDF；RSC articlepdf 仍 403

**机制已端到端验证（本仓、免 Docker）**：`tools/flaresolverr_nodriver.py` 是一个免 Docker、FlareSolverr `/v1` 逐字段兼容的求解端点，用 `nodriver`（uc 继任者、连真 Chrome）实现；本机 `nodriver 0.50.3 + curl_cffi` 已装，**健康检查 + 端到端真解全通过（`SOLVE_OK`）**，链路「仓库客户端 → nodriver shim → 真 Chrome → 目标站 → HTML+cookies+UA 回传」全打通。启用只需 `set FLARESOLVERR_URL`，`config.py`/命令行不用改。（证据：`选型2026-FlareSolverr免Docker-仓内nodriver-shim实测与落地-179.md` §0–§3）

**可救桶（ACS-authorchoice）**：batch4「A 类 + Cloudflare 拦截」子桶里 **ACS 12 条**属 `cloudflare-challenge(http-403)`，候选齐全、只差过 CF；解法即「浏览器/FlareSolverr 解一次挑战拿 `cf_clearance`+UA → 交现有 `http_client` 同域直下 PDF」（`flaresolverr.solve()` 已返回 `cookies`(含 cf_clearance)+`user_agent`，`download.py._flaresolverr_fallback()` L540 已接）。
- **-145 实测（`out/recover_b4_cf/`，run 进行中 total=20/success=13）确证**：ACS-authorchoice 的 CF403 **经 FlareSolverr（仓内 nodriver shim）真解为 PDF**。
  - DOI `10.1021/acscatal.0c01253`；`flaresolverr_recovered` 事件 url=`https://pubs.acs.org/doi/pdf/10.1021/acscatal.0c01253`、**bytes=4,410,578（≈4.41MB）**；落盘 `out/recover_b4_cf/pdfs/10.1021_acscatal.0c01253.pdf`，`source_used=publisher_oa:acs-authorchoice`。
  - **机理**：ACS 的 pdf 直链先中 CF403 → nodriver shim 解 CF 拿 `cf_clearance`+UA → `curl_cffi` **带其回放成功**（关键：**ACS 不把 cf_clearance 绑 JA3/TLS 指纹**，故 curl_cffi 回放可用）。
  - 该 run 另有 3 条 `flaresolverr_recovered`（共 4）是 websearch 候选被 CF 挡后由 FS 救回：`iris.unito.it/...S0926337321004458-main.pdf` 3.50MB（对应 `10.1016/j.apcatb.2021.120319`)、ACS suppl `cs1c01504_si_001.pdf` 1.90MB(对应 `10.1016/0920-5861(95)00246-4`)、以及 `jaad.org/...S0190-9622(17)32530-6/pdf` 450KB（**对应 `10.1002/cssc.201601217`**）。
  > ⚠️ **交叉印证(与本轮 QC 内容比对连上)**：上面最后一条 FS「救回」的 `jaad.org`(皮肤病学 JAAD) 正是 QC 复扫里 `10.1002/cssc.201601217`(ChemSusChem) 的**确凿假阳(错论文)**样例 → **FlareSolverr 会忠实地把 websearch 的『错候选』也下载成功**，即 FS 成功 ≠ 正确全文。这再次指向「下载校验层需加 DOI/标题内容闸门」(见 `out/qc_content_report.md`、本轮 QC 任务)。

**难越桶（RSC）——FS 回放仍 403；route-B 是另一条线**：`pubs.rsc.org` 整站 Cloudflare。-145 FS run 里 RSC `articlepdf` 均 `flaresolverr_failed`（**cf_clearance 绑 JA3**，curl_cffi 回放仍 403）。
- **限定表述**：**FS+curl_cffi 对 RSC ROI≈0**（不值得单独上 FS 破盾链）；**不等于「RSC 全无免费增量」**——**route-B 浏览器内直下**对金 OA 子集仍有 +N（N.8 机制通；MDPI7 已兑现；RSC 待 governor/A 集）。
（证据：`选型2026-RSC-Cloudflare挑战绕行方案.md` TL;DR / §二；`检索成果-batch4-失败分桶与可回收分析.md` A 类桶；-145 `out/recover_b4_cf/` FS 日志 `flaresolverr_failed` × 3 RSC）

---

## 二、长尾 / ChemRxiv / ResearchGate / OUP / T&F 现多在 Cloudflare 后

batch6「非 Elsevier 长尾 9 条」经 -143 实跑核验（`out/recover_b6_tail/`），**桶画像更正：这是 Cloudflare 桶，不是 arXiv/wayback 桶**：
- 命中墙的出版商 = **AIP（pubs.aip.org）、Wiley（onlinelibrary/chemistry-europe/aces）、Oxford Academic（academic.oup.com，OUP）、Taylor & Francis（tandfonline.com，T&F）**；
- **更关键：连自存稿/预印本逃生口也进了 Cloudflare** —— 实见 **ResearchGate、ChemRxiv（chemrxiv.org）返 `cloudflare-challenge(403)`**。
- **杠杆更正**：此桶真实回收杠杆是 **FlareSolverr（解 CF JS 质询）**，而非 arXiv/wayback；候选齐全、只差过 CF。

这把 `经验记录` H.3「Cloudflare 是免费手段主矛盾」的结论**扩大**：免费逃生口（RG/ChemRxiv）亦被 CF 封。跨批看，batch4 `cloudflare-challenge(http-403)` 达 **519 次**（RSC/ACS/Elsevier/Wiley 均高发）。（证据：`经验记录-踩坑与发现.md` K 节、H.3；`检索成果-batch4-失败分桶与可回收分析.md`）

---

## 三、Elsevier = IP/登录墙（非 CF）；browser_search 对冷门 DOI 召回≈0；wayback 亦 0

**Elsevier（ScienceDirect，10.1016）这一桶的瓶颈是「定位到候选却下不动」的下载环 403，属 IP/登录墙，而非 Cloudflare JS 质询：**
- **-143 browser_search 探针 = 0/5（两轮合计 0/10）**，reason 一律 `no-pdf-candidates`（浏览器渲染 Bing 成功、没吃验证码，问题在**召回=0**）；这 5 条在 batch6 里 websearch 本有候选（n=3~8），但候选几乎全是 **ResearchGate 落地页→403（数据中心 IP/需登录）+ ScienceDirect AM（`/article/am/pii/…`）→403**。架构性要害：`browser_search` **只渲染「搜索引擎结果页」抽候选、不渲染/不下载「落地页」**，故救不了长在下载/落地页上的墙。（证据：`经验记录-踩坑与发现.md` J 节）
- **-149 wayback 探针 = 0/12（本人实测，新增）**：对同桶 12 条 Elsevier A 类（5 条复用 -143 同 DOI 做跨方法对照 + 7 条由 `out/batch6` A 类 MISS 补齐）跑 `--sources wayback`，**全部 `no-candidates`、`pdfs/` 空、`%PDF` 命中 0**。根因：wayback 适配器对 Elsevier `10.1016` **仅查 `doi.org/<doi>`**（PII/ScienceDirect PDF 直链不可由纯 DOI 推导，见 `wayback.py._doi_candidate_urls`），而 archive.org 对 doi.org 只存 HTML 跳转页、无 `application/pdf` 快照 → `pdf_only` 过滤返回空 → 0 候选。与 browser_search 0 属**同源问题**（都拿不到可下载的 ScienceDirect PDF 直链）。（证据：`out/recover_b6_els_wayback/summary.json` success=0/12、by_source={}；`recover_b6_els_wayback_input.txt`）

**拍板**：**browser_search 0/10 + wayback 0/12 → Elsevier A 免费路线确认到顶**，wayback 不值得扩量。跨口径亦印证：`仅 http-403` 里 **ACS 80 + RSC 41 = 121 条(81%)** 为订阅刊真付费墙，不应再投免费源工程，应交机构订阅 / 商业 ScholarAPI。（证据：`检索成果-数据-失败原因分析.md` 结论 5）

> 后续（非本探针范围，供裁决）：若仍想让 wayback 对 Elsevier 有机会，须改造 wayback 源，对 `10.1016` 补「PII→ScienceDirect PDF 直链」再查存档，否则纯 DOI 路对 Elsevier 结构性为 0。

---

## 四、本机无 Docker → 源码起 byparr / nodriver-FS 的可行法

**结论：别急着为 CF 破盾装 Docker——本仓已自带一个免 Docker 的 FlareSolverr `/v1` 兼容变体。**

| 路径 | 做法 | 安装成本 | 引擎/UA | 何时用 |
|---|---|---|---|---|
| **① 仓内 nodriver shim（首选）** | `python tools/flaresolverr_nodriver.py --port 8191`（建议有头，CF 通过率更高）→ `set FLARESOLVERR_URL=http://127.0.0.1:8191` | **零**：`nodriver 0.50.3 + curl_cffi` 本机已装、脚本在仓里 | nodriver（真 Chrome / CDP 直连、无 uc3.5.5）→ Chrome UA | 默认首选；-145 uc3.5.5/Chrome 卡点的「零安装、零改码」解 |
| **② byparr（升级项）** | `pip install uv` + `git clone` + `uv sync`（拉 Camoufox/Firefox），独立进程起 `/v1` | 中：需拉 Camoufox | Camoufox/Firefox（C++ 级指纹）→ Firefox UA | ① 的 nodriver headed 仍被特定 Turnstile 识别时再上 |
| **③ 住宅代理** | cf_clearance 绑 IP，量大时的独立信号 | 高 | — | ①② 都不行、且需规模化时 |

**免 Docker 关键点（实测记录）**：
- shim 只在 `download.py` **已检测到 CF 质询后**才被兜底调用，**按 origin 缓存**（默认 1200s）→ 80 条 DOI 通常只落 4~5 个域，每域首条付一次解题成本。
- 回传的 `cf_clearance` **绑 IP+UA**，`solve()` 一并返回 `user_agent`、`download.py` 重下时会带上 → **别自己另换 UA**；①=Chrome UA、②=Firefox UA，各自跟随一致、勿混。
- 许可证：`nodriver = AGPL-3.0`（内部批量回收/个人研究无碍；对外服务须开源或过法务）。
- 端口冲突：-145 的 FlareSolverr 回收可能已占 `8191`，多人同机各用不同端口（如 `--port 8199`）并相应改 `$env:FLARESOLVERR_URL`。
- Windows 子进程：shim 已处理 `ProactorEventLoop`；停服务后如端口残留，`Get-NetTCPConnection -LocalPort <port> -State Listen` 找 `OwningProcess` 再 `taskkill /PID <pid> /T /F` 连子树清掉。

（证据：`选型2026-FlareSolverr免Docker-仓内nodriver-shim实测与落地-179.md` §2/§4/§6；`选型2026-FlareSolverr免Docker变体-给145.md`；`选型2026-RSC-Cloudflare挑战绕行方案.md` §一）

---

## 五、一页汇总：桶 × 墙类型 × 免费可救性

| 桶 / 出版商 | 墙类型 | 免费手段实测 | 可救性 / 杠杆 |
|---|---|---|---|
| **ACS-authorchoice**（10.1021 OA） | Cloudflare JS 质询(403) | FS 可下到 PDF；**QC 净增真正文 ≈1**（≈93% SI 陷阱） | ⚠️ **机制可救 ≠ 正文净增** |
| **AIP / Wiley / OUP / T&F 长尾** | Cloudflare(403) | 候选齐全、只差过 CF | ✅ **可救**：FlareSolverr（OA 子集） |
| **ResearchGate / ChemRxiv（逃生口）** | Cloudflare(403) | 自存稿/预印本兜底亦被 CF 封 | ⚠️ 需 FlareSolverr |
| **RSC**（10.1039） | Cloudflare「Just a moment」 | FS 回放 403（绑 JA3）；**route-B 金 OA +N** | ⚠️ **FS ROI=0**；route-B 另线 |
| **Elsevier / ScienceDirect**（10.1016） | IP/登录墙（**非 CF**） | browser_search 0/10、wayback 0/12 | ❌ **免费到顶** |
| **ACS/RSC 纯订阅刊 403** | 真付费墙 | http-403 订阅主体 | ❌ A5 / 商业 API |
| **MDPI**（10.3390） | Akamai | **route-B 已回写 7** | ✅ **已兑现** |

---

## 六、证据索引（均为已提交文档 / 本人实测产物）

1. `选型2026-FlareSolverr免Docker-仓内nodriver-shim实测与落地-179.md` —— 免 Docker nodriver-shim 端到端 `SOLVE_OK`、runbook、升级阶梯、坑（-179）。
2. `选型2026-RSC-Cloudflare挑战绕行方案.md` —— RSC 100% CF、HTTP 层过不了、nodriver/patchright/FlareSolverr 对比、RSC 净收益≈0（-176）。
3. `选型2026-FlareSolverr免Docker变体-给145.md` —— 外部克隆型 byparr/FlareBypasser、cookie 复用正确性（-177）。
4. `经验记录-踩坑与发现.md` —— **H.2**（straggler 看门狗 + 149 的 CF/浏览器感知超时放大 ≥900s 修复）、**H.3**（Cloudflare 主矛盾 + `download.py` 识别/回退）、**J**（browser_search 对 Elsevier 0/10）、**K**（batch6 长尾=CF 桶：AIP/Wiley/OUP/T&F/RG/ChemRxiv）、**L**（websearch 假阳错论文大规模审计 + 双法定案 + 净覆盖率修正——本轮最大发现的可检索详版）。
5. `检索成果-batch4-失败分桶与可回收分析.md` —— A 类+CF 桶（Elsevier55/ACS12/Wiley7/RSC4）、`cloudflare-challenge(403)` 519 次。
6. `检索成果-数据-失败原因分析.md` —— http-403 里 ACS80+RSC41=121(81%) 真付费墙；免费源不应硬刚部分。
7. **本人实测（-149）**：`out/recover_b6_els_wayback/`（wayback Elsevier A 0/12）、`recover_b6_els_wayback_input.txt`（12 条清单）；`tools/qc_content_match.py` + `out/qc_content_report.{json,md}`（websearch 假阳 A=68.5% / B=56.0%，见 §〇补）。
9. **内容审计产物**：`qc_content_report.*`、`coverage.json`（**当前 326/999=32.63% @12:50:24**；340/34.03%@00:42:19 为历史）。
8. **-145 实测（`out/recover_b4_cf/`）**：ACS FS 机制样本；RSC FS 回放 403（绑 JA3）；**FS 成功 ≠ 正确全文**（cssc→jaad 铁证）。

---

*定版回填 2026-07-03｜-154 原稿 340/659@00:42:19 → 已 re-align 至 **326/673@12:50:24**（169 承总指挥 (a)）｜对齐《回收交付定稿核对-154》四项缺口｜免费物理到顶 ~33%。*

*补记 2026-07-02｜-150｜§〇补 websearch 假阳 QC 全过程；straggler 见 H.2。*
