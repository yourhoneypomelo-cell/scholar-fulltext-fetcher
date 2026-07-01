# 谷歌学术爬虫 · 调研 · Scholar 抓取 / CAPTCHA 处理 / PDF 下载(开源项目 · 2026 时效核验)

> 工作组目标:绕过谷歌学术(Google Scholar)人机认证,抓取元数据并下载 PDF。
> 本文聚焦**三类可直接 clone 的开源项目**:① Google Scholar 抓取;② CAPTCHA / reCAPTCHA 处理(**角度1 未展开、本文重点补齐**);③ 按 DOI/标题下载学术 PDF。
> 每项核验:**仓库 / 最近更新 / star / 许可 / 能力 / 当前反爬下是否仍可用 / 优缺点 / 建议(采用·整合·不用)**。
> 数据来源:GitHub / PyPI / JOSS,按 **2026-07-01** 核验;并对《检索成果-角度1-GitHub开源项目直检》(2026-06-30)、《检索成果-角度4-商业抓取与第三方ScholarAPI服务》(2026-06/07)做**时效更新对照**。
> 整理人:谷歌学术人机认证-141 · 2026-07-01

---

## 〇、方法、边界与一句话结论

- **去重边界**:反爬**工具栈**(curl_cffi / nodriver / Camoufox / 住宅代理)见**角度3/6**;**商业 Scholar API / 打码服务的横评与报价**见**角度4**。本文只列"**开源项目本体**",尤其补齐角度1 略过的 **CAPTCHA 求解开源库**。
- **与本项目数据的关系**:本仓《检索成果-数据-失败原因分析》显示,当前 500 样本失败**几乎全是出版商 403 付费墙 / 免费源无候选,并非 reCAPTCHA 拦截**。因此——
  - **②CAPTCHA 处理**只在"**直抓 Google Scholar 拿被引/版本等原生字段**"这条路上才需要;若目标只是"拿全文 PDF",走 **③ 的 OA 下载器**即可,基本碰不到 reCAPTCHA。
- **一句话结论**:**"过人机"能力开源项目本身几乎都不自带**——GS 抓取靠外接代理 / SerpApi;reCAPTCHA 靠打码服务或"音频求解"(可用性正快速下降);PDF 下载靠多源 OA 回退(+ Sci-Hub 灰色兜底)。

---

## 一、① Google Scholar 抓取类

> 负责"搜论文 + 拿标题/作者/被引/版本/链接"。本表在角度1 基础上做 **2026-07 复核**(变化见第四节)。

| 项目 | 许可 | star | 最近更新 | 核心能力 | 当前反爬下可用性 | 建议 |
|---|---|---|---|---|---|---|
| **scholarly-python-package/scholarly** | Unlicense | ~1,871 | **PyPI v1.7.11 停在 2023-01**;GitHub `main` 仍有补丁 | 事实标准底座:作者档/单篇/`search_pubs`/`citedby`;内置 `ProxyGenerator` | ⚠️ 低频作者/单篇可用;**高频 `search_pubs`/`citedby` 必封 IP**,须挂住宅代理 | **整合**(元数据底座 + 代理) |
| **ckreibich/scholar.py** | 无明示 | ~2,170 | **2022-09 停更** | 单文件查询/解析,导出 BibTeX/EndNote/CSV | ❌ 选择器老化,极易 429/验证 | **不用**(仅临时小量) |
| **WittmannF/sort-google-scholar** | MIT | ~983 | 2024-12 | 按被引排序 → CSV,含逐年被引 | ⚠️ 量大触发验证;`requests`→Selenium 回退 | **采用**(轻量找高引) |
| **dimitryzub/scrape-google-scholar-py** | MIT | ~132 | 2025-07 | 双后端:自建(selenium-stealth)/ SerpApi | ⚠️ 自建后端靠 stealth,规模化仍需切 SerpApi | **整合**(要规模化切 SerpApi) |
| **JessyTsui/ScholarDock** | MIT | ~114 | 2025-07 | 全栈 Web(FastAPI+React):检索/排序/导出/图表 | ⚠️ 无强反爬,中小量 | **采用**(要可视化交付) |
| **dr-dumpling/paper-search-cli** | MIT | ~75 | 2026-06 | 多源 CLI(Crossref/OpenAlex/S2/GS/PubMed…) | ✅ GS 仅作广撒;主路径官方 API | **整合**(多源发现) |
| **monk1337/resp** | Apache-2.0 | ~487 | 2025-12 | 10+ 源统一检索;GS 路径强制走 SerpAPI | ✅ GS 外包 SerpApi,其余官方源 | **整合**(免斗法) |

> 说明:star 为 2026-07 量级核验;`scholarly` 的"without solving CAPTCHAs"是**营销话术**——指常规单篇/作者查询,高频批量仍会被封,天花板由代理/角度4 决定。

---

## 二、② CAPTCHA / reCAPTCHA 处理类(角度1 缺口,本文重点)

> Google Scholar 用的是 **reCAPTCHA v2/v3**。开源方案分两支:**(2.1) 付费打码服务的开源客户端 SDK**(稳定但持续付费)、**(2.2) 本地/开源自解**(免费但可用性递减)。

### 2.1 打码服务客户端 SDK(付费服务 + 开源客户端)

| 项目 | 许可 | star | 最近更新 | 对应服务 / 模型 | 能力 | 建议 |
|---|---|---|---|---|---|---|
| **2captcha/2captcha-python** | MIT | ~769 | **v2.0.9(2026-06-22,很活跃)** | 2Captcha(人工+AI 混合) | reCAPTCHA v2/v3、Turnstile、FunCaptcha、GeeTest 等**覆盖最广**;`pip install 2captcha-python` | **采用**(兜底首选,覆盖最全) |
| **AndreiDrang/python3-capsolver** | MIT | ~84 | v1.2.0(2026-01),push 2026-06 | CapSolver(纯 AI,快) | reCAPTCHA/Turnstile/DataDome/GeeTest;async+重试;`pip install python3-capsolver` | **采用**(token 类快、社区活跃) |
| **capsolver/capsolver-python** | MIT | ~67 | push 2024-11(较旧) | CapSolver 官方 | `pip install capsolver`,`solve({type:ReCaptchaV2TaskProxyLess…})` | **整合备选**(官方但更新慢,优先上面社区版) |
| **AndreiDrang/python3-anticaptcha** | MIT | ~164 | v2.2.2(2026-02) | Anti-Captcha | reCAPTCHA v2/v3、hCaptcha、Turnstile、AWS WAF… | **备选**(Anti-Captcha 生态) |
| **anti-captcha/anticaptcha-python** | 官方 | ~60 | 2023+ | Anti-Captcha 官方 | `pip install anticaptchaofficial`,$0.0005/token 起 | **备选** |
| **ad-m/python-anticaptcha** | MIT | ~230 | 老牌(2017+) | Anti-Captcha | 经典社区客户端 | 备选(老牌但更新慢) |
| **CapMonsterCloudTeam/capmonstercloud-client-python** | MIT | ~2 | push 2026-05 | CapMonster Cloud(AI,>1000/min) | 全 async、高吞吐;`pip install capmonstercloudclient` | **备选**(高吞吐场景) |

### 2.2 本地 / 开源自解(不依赖付费服务)

| 项目 | 语言/许可 | star | 最近更新 | 机制 | 当前可用性 | 建议 |
|---|---|---|---|---|---|---|
| **Xewdy444/Playwright-reCAPTCHA** | Python / MIT | ~551 | 活跃 | reCAPTCHA v2/v3:**音频挑战→Google 语音转写**(免费);图像挑战可接 CapSolver(付费)。需 FFmpeg | ⚠️ **音频路仅低频可用**(Google 收紧音频 + 单 IP 速封) | **整合**(唯一成熟的开源本地 reCAPTCHA 求解) |
| **dessant/buster** | JS 扩展 / GPL-3.0 | **~9,151** | **v3.4.0(2026-06-20,活跃)** | 浏览器扩展:点按钮用语音识别解 reCAPTCHA v2 **音频** | ⚠️ 面向**人工/半自动**,非无头批量;需配 client app | **采用**(人在环/手动场景) |
| **QIN2DIM/hcaptcha-challenger** | Python | ~2,000 | 活跃 | 多模态 LLM 解 **hCaptcha**(非 reCAPTCHA) | ✅ hCaptcha 强;**GS 用的是 reCAPTCHA,非直接适用** | **不用于本项目**(留意,非 Scholar 场景) |
| **k19-sudo/recaptcha-v2-resolver-free** | TS / Apache-2.0 | ~1 | 2026-02 新建 | Playwright + **Whisper** 本地音频求解 | ❌ 过新、1★、未验证 | **不用**(不成熟,观望) |

> **本地自解的现实**:reCAPTCHA 的"音频挑战求解"曾是开源主力路径,但 2026 年 Google 持续收紧(音频挑战限流、单 IP 高频立即 `Your computer or network may be sending automated queries`)。**低频、配住宅代理**尚可;**规模化稳定仍需打码服务(2.1)+ 住宅代理(角度6),或直接买 SerpApi(角度4)把这关整包外包**。

---

## 三、③ 按 DOI/标题下载学术 PDF 类

> 负责"给 DOI/标题 → 落地 PDF"。本表在角度1 基础上**新增 2 个角度1 未收录的项目**(`pypaperretriever`、`paper-fetch`)。

| 项目 | 许可 | star | 最近更新 | 源 / 能力 | 当前可用性 | 建议 |
|---|---|---|---|---|---|---|
| **JosephIsaacTurner/pypaperretriever** ⭐新 | MIT | ~38 | **v1.0.1(2026-06-24)** · **JOSS 2025 发表**(DOI 10.21105/joss.08135) | **OA 优先**(Unpaywall)+ 可选 Sci-Hub(**默认关**);DOI/PMID、引用网络、PDF 图像抽取、JSON sidecar、去重 | ✅ OA 部分稳定;学术级、可引用 | **采用**(OA 优先、可引用、功能全) |
| **h120750572/paper-fetch**（`4Born/paper-fetch`）⭐新 | 开源 | 新/小 | 2026 新(Agent Skill) | **纯 OA、零依赖**(仅标准库):Unpaywall→S2→arXiv→PMC→bioRxiv→[Sci-Hub];批量、JSON schema、稳定退出码 | ✅ 与本项目 `fulltext_fetcher` **回退链高度一致** | **采用/参考**(可直接借鉴回退设计) |
| **ferru97/PyPaperBot** | MIT | ~644 | v1.4.1(维护中) | GS/Crossref/**SciHub/SciDB(Anna's Archive)**;BibTeX、按年/刊/被引过滤 | ⚠️ GS 迭代下载会被拉黑;配镜像小批量 | **整合**(批量 + SciDB 兜底) |
| **jannisborn/paperscraper** | MIT | ~534 | **v1.0.0(2026-06,最活跃)** | PubMed/arXiv/bioRxiv/medRxiv/chemRxiv 元数据+全文;GS 取被引 | ✅ 反爬暴露面最低 | **整合**(预印本/生物医学元数据+全文) |
| **Tishacy/SciDownl** | MIT | ~303 | **2023 后停更** | Sci-Hub 按 DOI/PMID/TITLE,域名可配 | ⚠️ 选择器/域名易失效 | **备选**(精确单篇,先验证域名) |
| **zaytoun/scihub.py** | MIT | ~1,028 | 停滞 | 非官方 Sci-Hub API + GS 搜索 | ❌ 年久失修、域名漂移 | **不用**(仅库级参考) |

> **共性**:所有下载器的免费天花板都由 **OA 覆盖**决定(与本项目 `fulltext_fetcher` 一致);付费墙全文只能靠 **Sci-Hub(灰色)/ 机构订阅 / 商业服务(角度4)**。

---

## 四、时效更新对照(vs 角度1 / 角度4)

| 变化点 | 结论(2026-07 核验) |
|---|---|
| **新增 PDF 下载器 ×2**(角度1 未收录) | `pypaperretriever`(JOSS 发表、OA 优先)、`paper-fetch`(零依赖 OA-only,回退链≈本项目) → **建议补进角度1 第二节** |
| **CAPTCHA 求解开源库**(角度1 归到角度3、未列具体库) | 本文 2.1/2.2 补齐 7+ 客户端 SDK 与 4 个本地/开源求解,给出 star/更新/建议 |
| `scholarly` 版本 | **PyPI 仍停 v1.7.11(2023-01)**;GitHub `main` 有零星补丁 → 角度1"维护中 v1.7.x"应细化为"**git 微维护、PyPI 未再发版**" |
| `2captcha-python` | **v2.0.9(2026-06-22)**,非常活跃(角度1/角度4 均未列客户端库) |
| `dessant/buster` | **v3.4.0(2026-06-20)**,~9.1k★,仍是最大开源 reCAPTCHA 音频求解扩展 |
| `PyPaperBot` / `paperscraper` | 与角度1 一致(v1.4.1 / v1.0.0-2026-06),维护正常 |
| `SciDownl` / `scihub.py` | 与角度1 一致:**停更/停滞**,可用性风险高 |
| 商业打码服务报价(2Captcha reCAPTCHA v2 ≈$1–3/1k) | 归口**角度4**,本文只列开源客户端,不重复横评 |

---

## 五、选型建议(按本项目目标分层)

**目标 A:只要全文 PDF(本项目主线,已由 `fulltext_fetcher` 覆盖)**
- **参考/整合**:`paper-fetch`(回退链与本项目一致,可对照补源)、`pypaperretriever`(OA 优先 + 引用网络 + 图像抽取);批量兜底用 `PyPaperBot`(+SciDB)。**基本不触发 reCAPTCHA**,无需 ②。

**目标 B:要 Google Scholar 原生字段(被引/版本/作者 h-index)**
- **整合** `scholarly` + 住宅代理(低频);或**直接** SerpApi / resp(角度4,把过人机整包外包)——**性价比通常优于自解 reCAPTCHA**。

**目标 C:确实要自解 reCAPTCHA(不想付 SerpApi、又要自抓 GS)**
- **整合** `Playwright-reCAPTCHA`(音频,低频)→ 失败**兜底** `2captcha-python` / `python3-capsolver`(付费)→ 全程配**住宅代理**(角度6)。人在环场景可用 `buster` 扩展。

**采用 / 整合 / 不用 速查**
- **采用**:`2captcha-python`、`python3-capsolver`、`pypaperretriever`、`paper-fetch`、`buster`(人工场景)、`sort-google-scholar`/`ScholarDock`(按需)
- **整合**:`scholarly`、`resp`/`paper-search-cli`、`Playwright-reCAPTCHA`、`PyPaperBot`、`paperscraper`
- **不用/观望**:`scholar.py`、`scihub.py`(停滞);`recaptcha-v2-resolver-free`(不成熟);`hcaptcha-challenger`(非 reCAPTCHA 场景);`SciDownl`(先验证域名)

---

## 六、风险与合规(clone 前必读)

1. **reCAPTCHA 本地求解可用性递减**:音频挑战被 Google 持续限流,单 IP 高频立即触发 "automated queries" 硬封;**开源自解只适合低频**,规模化必须打码服务 + 住宅代理或商业 API。
2. **打码服务=灰色 + 持续付费**:2Captcha/CapSolver/Anti-Captcha/CapMonster 皆为第三方付费;客户端库开源,**服务本身按量计费**,且随 reCAPTCHA 升级可能失效。
3. **直抓 Google Scholar 违反 ToS 与 robots.txt**:几乎所有 GS 抓取库都会被封 IP/弹验证,**必须住宅代理 + 限速退避**(角度3)。
4. **Sci-Hub 类**:法律风险 + 域名漂移 + 内容不全;`pypaperretriever`/`paper-fetch` 默认关或末位兜底是较稳妥的合规姿态;下载后务必核对元数据一致。
5. **"零依赖/免费"要看有效成本**:`paper-fetch` 零依赖但只覆盖 OA;真要付费墙全文,成本仍在机构订阅/商业服务(角度4)。

---

## 七、来源(2026-07-01 逐仓/逐页核验)

- GitHub:`scholarly-python-package/scholarly`、`ckreibich/scholar.py`、`WittmannF/sort-google-scholar`、`dimitryzub/scrape-google-scholar-py`、`JessyTsui/ScholarDock`、`dr-dumpling/paper-search-cli`、`monk1337/resp`
- GitHub(CAPTCHA):`2captcha/2captcha-python`、`AndreiDrang/python3-capsolver`、`capsolver/capsolver-python`、`AndreiDrang/python3-anticaptcha`、`anti-captcha/anticaptcha-python`、`ad-m/python-anticaptcha`、`CapMonsterCloudTeam/capmonstercloud-client-python`、`Xewdy444/Playwright-reCAPTCHA`、`dessant/buster`、`QIN2DIM/hcaptcha-challenger`、`k19-sudo/recaptcha-v2-resolver-free`
- GitHub(PDF):`JosephIsaacTurner/pypaperretriever`、`h120750572/paper-fetch`(`4Born/paper-fetch`)、`ferru97/PyPaperBot`、`jannisborn/paperscraper`、`Tishacy/SciDownl`、`zaytoun/scihub.py`
- PyPI:`scholarly` v1.7.11、`2captcha-python` v2.0.9、`python3-capsolver` v1.2.0、`python3-anticaptcha` v2.2.2、`capmonstercloudclient`、`PyPaperBot` v1.4.1、`pypaperretriever` v1.0.1、`paperscraper` v1.0.0
- JOSS:《PyPaperRetriever》10.21105/joss.08135(Turner & Turner, 2025)
- 本仓交叉:《检索成果-角度1-GitHub开源项目直检》《检索成果-角度4-商业抓取与第三方ScholarAPI服务》《检索成果-角度3-反爬与反reCAPTCHA技术深度》《检索成果-数据-失败原因分析》
