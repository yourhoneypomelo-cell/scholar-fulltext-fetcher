# 谷歌学术过人机认证开源项目检索 — 角度1：GitHub 开源项目关键词直检

> 工作组目标：绕过谷歌学术（Google Scholar）的人机检测认证，直接抓取元数据并下载 PDF。
> 本文件为「角度1（GitHub 开源项目关键词直检）」的检索汇总，定位为**「GitHub 上可直接 clone 使用的爬取/下载类项目总目录」**——逐个核验 star 热度、维护活跃度、核心能力与「过人机/反爬」机制。
> 整理人：谷歌学术人机认证-152（本组成员会话）｜日期：2026-06-30
> 所有 star 数 / 最近更新 / 许可均按 2026-06-30 GitHub 现状逐仓核验。

---

## 〇、检索方法与边界说明

- **检索关键词**：`google scholar crawler` / `google scholar scraper` / `scholarly` / `publish or perish` / `scholar captcha bypass` / `serpapi scholar` / `paper downloader` / `scihub download` / `research paper search framework` 等，在 GitHub 系统检索后按 star、活跃度、可直接 clone 运行三条标准筛选。
- **聚焦范围**：GitHub 上**可直接 clone 即用**的爬取/下载类项目（库 / CLI / 框架 / 全栈应用）。
- **去重约定**（避免与兄弟文档重复）：
  - **官方开放 API**（Crossref / OpenAlex / Semantic Scholar / Unpaywall）见**角度2**——本文只列「以 GitHub 项目形态封装/调用它们」的载体，不展开 API 本身。
  - **反爬 / 反 reCAPTCHA 的工具级实现**（curl_cffi / nodriver / Camoufox / 打码服务）见**角度3**——本文只标注各项目「把过人机能力外接到哪里」，不展开对抗细节。
  - **中文社区项目与镜像站**见**角度7**——其已详述的 `Liwu-di/PaperCrawlerUtil`、`SyncrexWen/EZScholarSearch`、`ssemerikov/scholarextractor` 本文仅补 GitHub 量化数据、不重复描述。
- **一句话定性**：GitHub 这些项目绝大多数只解决「**驱动浏览器 + 解析页面 + 串下载源**」；**真正的「过人机」能力来自外接**——要么外接代理/打码（角度3），要么外接 SerpApi 云端，要么干脆换官方 API（角度2）。

---

## 一、Google Scholar 元数据检索 / 解析类

> 负责「搜到论文 + 拿标题/作者/被引/链接」，本身不管 PDF 下载。

| 项目 | 语言 / 许可 | 核心能力 | 过人机 / 反爬策略 | star | 最近更新 |
| --- | --- | --- | --- | --- | --- |
| **scholarly-python-package/scholarly** | Python / Unlicense | 事实标准底座库：取作者档案、单篇/检索元数据、`citedby`、`search_pubs`，Pythonic 接口 | **内置 `ProxyGenerator`**（FreeProxies / ScraperAPI / Luminati / Bright Data；Tor v1.5 起弃用）；官方明确警告 `search_pubs`/`citedby` 会封 IP，**必须挂代理**；自身不解 CAPTCHA，靠代理规避 | ~1.87k | 维护中（v1.7.x） |
| **ckreibich/scholar.py** | Python / 无明示许可 | 经典**单文件**查询器+解析器：标题/链接/PDF链接/被引/版本/cluster ID/摘录，导出 BibTeX/EndNote/CSV | 仅 **cookie 持久化**提升配额；**无内置代理/打码**，现代极易被 429/CAPTCHA，需自行挂代理 | ~2.17k | **2022-09 停更**（选择器老化） |
| **WittmannF/sort-google-scholar**（sortgs） | Python / MIT | 按**被引数排序** GS 结果 → CSV，含「每年被引」列，适合快速找领域高引 | 先 `requests`，失败**回退 Selenium**；无专门反爬，量大易触发验证 | ~983 | 2024-12（v1.0.7） |
| **dimitryzub/scrape-google-scholar-py** | Python / MIT | **双后端**：自定义 backend（organic/profiles/author/cite/mandates）与 SerpApi backend；导出 CSV/JSON | 自定义后端用 **`selenium-stealth` 过 CAPTCHA** + `selectolax` 快解析；或切 **SerpApi 后端**由云端解决 | ~132 | 2025-07 |
| **JessyTsui/ScholarDock**（原 google_scholar_spider） | TS + Python / MIT | **全栈 Web 应用**（FastAPI+React）：检索 GS、按年过滤、按被引排序、单次至 1000 条、导出 CSV/JSON/Excel/BibTeX、SQLite 历史、被引图表 | 后端 spider 基础请求，**无强反爬**，适合中小量；交付/可视化友好（中/英/日 UI） | ~114 | 2025-07 |
| **ian-kerins/google-scholar-scrapy-spider** | Python / Scrapy | **Scrapy 工程化**：按关键词搜 GS、自动翻页、抽取结构化字段 | 依赖 **ScraperAPI** 做代理池（免费 1000 次/月起步），本身不处理指纹/打码 | ~44 | 旧（~2020） |

---

## 二、论文 PDF 下载类（Sci-Hub / 多源）

> 负责「给 DOI/标题/链接 → 落地 PDF」，过人机压力主要在 Sci-Hub 域名漂移与 GS 迭代下载封禁。

| 项目 | 语言 / 许可 | 核心能力 | 过人机 / 反爬策略 | star | 最近更新 |
| --- | --- | --- | --- | --- | --- |
| **zaytoun/scihub.py** | Python / MIT | 非官方 **Sci-Hub API**：可搜 GS + 从 Sci-Hub 下载；CLI 与库两用，支持标识符文件批量 | `-p` 代理参数；**无 CAPTCHA 处理**；Sci-Hub 域名/可用性漂移，**年久失修** | ~1.03k | 旧（停滞） |
| **ferru97/PyPaperBot** | Python / MIT | **多源下载主力**：经 GS / Crossref / Sci-Hub / SciDB(Anna's Archive) 下 PDF+BibTeX；按年/期刊/被引过滤 | `--proxy`/`--single-proxy` + `--scihub-mirror`（自动选镜像）；**已知 GS 迭代下载会被拉黑**→建议小批量、配镜像 | ~644 | 2024+ 复活（v1.4.1） |
| **Tishacy/SciDownl** | Python / MIT | 按 **DOI / PMID / TITLE** 从 Sci-Hub 下载；把 SciHub 变化封装为**可配置**，便于跟域名 | 支持代理；易更新最新 SciHub 域名；不解 CAPTCHA | ~303 | 2024-02 |

---

## 三、多源科研抓取框架 / 元数据+全文一体

> 「把 GS 当其中一路、再叠加官方 API/预印本源」的聚合型——与角度2 主线天然衔接。

| 项目 | 语言 / 许可 | 核心能力 | 过人机 / 反爬策略 | star | 最近更新 |
| --- | --- | --- | --- | --- | --- |
| **jannisborn/paperscraper** | Python / MIT | PubMed/arXiv/bioRxiv/medRxiv/chemRxiv **元数据+全文(PDF/XML)**；从 GS 取被引计数；期刊影响因子；本地 dump 可复现检索 | GS 仅用于取**被引**（底层 `scholarly`），主路径走官方源/本地 dump→**反爬暴露面最低**；维护最活跃 | ~534 | **2026-06（v1.0.0，活跃）** |
| **monk1337/resp** | Python / Apache-2.0 | 10+ 源统一检索：Arxiv/Semantic Scholar/**Google Scholar**/ACM/ACL/PMLR/NeurIPS/IJCAI/OpenReview/CVF/Connected Papers；取被引、找相关论文 | **GS 路径强制走 SerpAPI key**（服务端过人机），其余走官方/免费 API；Connected Papers 需 Selenium | ~487 | 2025-12（v0.1.2） |
| **dr-dumpling/paper-search-cli** | TS / MIT | **2026 新秀** 多源 CLI：Crossref/OpenAlex/S2/**Google Scholar**/PubMed/arXiv/DBLP… 广搜 + 期刊分区(EasyScholar) | GS 走**页面解析**做广撒发现；PDF 走各源，**Sci-Hub 作 DOI 兜底**（可开关） | ~75 | 2026-06（v0.3.0） |
| **ssemerikov/scholarextractor** | Python / 无明示许可 | GS 元数据提取 + PDF 下载、断点续传（**角度7 已详述**，此处仅补量化数据） | 默认 **8s 限速** + UA 轮换 + **CAPTCHA 检测** + 尊重 robots.txt；遇验证建议等 30–60min / 加大 `--delay` / `--resume` | ~2 | 2025-11（新、AI 辅助开发） |

---

## 四、商业 SerpApi 客户端（把过人机转嫁给云端，付费）

| 项目 | 语言 / 许可 | 核心能力 | 过人机 / 反爬策略 | star | 最近更新 |
| --- | --- | --- | --- | --- | --- |
| **serpapi/google-search-results-python** | Python / MIT | SerpApi 官方客户端，`GoogleScholarSearch` 类直返结构化 JSON（organic/author/cite/profiles） | **反爬全在云端**：全球 IP 池 + 整套浏览器集群 + **自动解 CAPTCHA**，本地零对抗；**按量付费** | ~734 | 维护中（将迁移至 `serpapi-python`） |

> 角度7 已详述的中文项目，本表仅补 GitHub 数据：`Liwu-di/PaperCrawlerUtil`（Python/MIT，**18★**，GS 爬虫+Sci-Hub+PDF/代理工具组，需配可访问 Google 的代理）；`SyncrexWen/EZScholarSearch`（Python/MIT，**1★**，基于 `scholarly`+AI 工作流/MCP，`delay` 降速）。

---

## 五、选型结论（按需求一句话给方案）

| 你的需求 | 首选项目 | 理由 |
| --- | --- | --- |
| 只要 GS **元数据**（生态最广） | **scholarly** | 事实标准、被无数项目当底座；配住宅代理即用 |
| 轻量、单文件、临时用 | scholar.py | 经典，但 2022 停更、选择器老化，**仅短期小量** |
| **批量下 PDF** | **PyPaperBot** | 一站式多源 + 自动选镜像 + BibTeX/过滤，已复活维护 |
| 按 DOI/标题**精确下单篇** | SciDownl（库级用 scihub.py） | DOI/PMID/TITLE 直达，域名可配置 |
| **省心/合规/规模化、不想斗法** | **SerpApi 客户端** 或 **resp** | 过人机外包给云端；与角度2 思路衔接 |
| **多源元数据+全文**聚合 | paperscraper | 生物医学/预印本最强、维护最活跃、反爬暴露面低 |
| 要**可视化/可交付**成品 | ScholarDock | 全栈 Web、导出全格式、带历史与图表 |
| 要 **Scrapy 工程化**管线 | scrapy-spider + ScraperAPI | 翻页/字段抽取规范，代理外接 |

**最小可用组合推荐**：元数据底座 `scholarly` → 下载主力 `PyPaperBot`（+`SciDownl` 精确补刀）；要规模化免斗法直接上 `SerpApi`/`resp`；要交付成品用 `ScholarDock`；多源聚合用 `paperscraper`。

---

## 六、风险提示（clone 前必读）

1. **维护活跃度分化极大**：最活跃是 `paperscraper`(2026-06)、`PyPaperBot`(已复活)、`paper-search-cli`(2026-06)、`resp`(2025-12)；而 `scholar.py`(2022 停)、`scihub.py`(停滞)、`SciDownl`(2024) 的选择器/域名**易失效**。**clone 前先看 last commit + open issues**。
2. **「无需处理 CAPTCHA」是话术**：`scholarly` 等所谓「无需解 CAPTCHA」指**常规作者/单篇查询**；高频 `search_pubs`/`citedby` 仍会被封 IP——天花板由角度2/角度3 决定，**库本身解决不了**。
3. **合规灰色**：直抓 GS 违反其 ToS 与 `robots.txt`；几乎所有项目都警告会被封 IP/弹验证，**必须配住宅代理 + 限速退避**（参见角度3 分层对抗）。
4. **Sci-Hub 类**：法律风险 + 域名漂移 + 内容不全；下载后**务必核对元数据一致**（参见角度7）。
5. **免费代理不可靠**：`scholarly` 的 FreeProxies 实测低可用、慢；认真用需住宅代理或付费 SerpApi。
6. **过人机能力靠外接**：这些项目大多只做「驱动+解析」，真正的过人机来自外接——代理 / SerpApi / 打码，即**角度3 的分层对抗**。

---

## 七、与其他角度的衔接

- **→ 角度2（开放 API 主线）**：`resp` / `paperscraper` / SerpApi 客户端已大量内置 OpenAlex / S2 / Crossref / 预印本源，是角度2 主线的**现成 GitHub 载体**。
- **→ 角度3（反爬技术备线）**：`scholarly` / `scrapy-spider` 等把「代理/指纹/打码」留作外接口，正好对接角度3 的 `curl_cffi` / `nodriver` / 住宅代理 / CapSolver。
- **→ 角度4（商业服务）**：本文「商业 SerpApi 客户端」一类（`serpapi` 客户端、`resp` 的 GS 路径）正是角度4 服务的**客户端载体**——把过人机整包外包给云端；服务商横评、报价与合规盾详见角度4。
- **→ 角度6（代理基础设施）**：本文项目的「外接代理」正是角度6 的**消费方**——`scholarly` 的 `ProxyGenerator`、`PyPaperBot --proxy`、`scrapy-spider` 的 ScraperAPI 都需喂入角度6 的住宅/移动代理（或自建 `proxy_pool`）。
- **→ 角度7（中文社区与镜像站）**：`PaperCrawlerUtil` / `EZScholarSearch` / `scholarextractor` 已在角度7 描述，本表仅补 GitHub 量化数据，互补不重复。

---

## 八、来源（均逐仓核验，截至 2026-06-30）

- GitHub：scholarly-python-package/scholarly、ckreibich/scholar.py、WittmannF/sort-google-scholar、dimitryzub/scrape-google-scholar-py、JessyTsui/ScholarDock（原 google_scholar_spider）、ian-kerins/google-scholar-scrapy-spider
- GitHub：zaytoun/scihub.py、ferru97/PyPaperBot、Tishacy/SciDownl
- GitHub：jannisborn/paperscraper、monk1337/resp、dr-dumpling/paper-search-cli、ssemerikov/scholarextractor
- GitHub：serpapi/google-search-results-python、Liwu-di/PaperCrawlerUtil、SyncrexWen/EZScholarSearch
- PyPI：scholarly、PyPaperBot、scidownl、sortgs、paperscraper、respsearch、PaperCrawlerUtil
- 官网：serpapi.com（Google Scholar API / CAPTCHA-solving 说明）
