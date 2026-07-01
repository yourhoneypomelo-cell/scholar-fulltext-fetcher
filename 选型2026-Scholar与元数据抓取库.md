# 选型 2026 · Scholar 与元数据抓取库(服务 `scholar/` 子包 + `query`/`resolve`)

> 目的:为 `fulltext_fetcher` 的 **Scholar 抓取(`scholar/`)** 与 **标题→DOI / 元数据(`query`、`resolve`)** 环节,评估是否有现成库可避免重造轮子;给出时效(2026 活跃)/适配/维护/star/许可 的决策表与采用建议。
> 整理人:谷歌学术人机认证-146 ｜ 日期:2026-07-01 ｜ 联网核验:2026-07-01(PyPI/GitHub/官方文档)
> 边界:本文只做**选型调研**,只新建本 md,不改任何 `.py` 与他人文档。反爬工具栈(curl_cffi/nodriver/代理)见角度3/6;商业 Scholar API 横评见角度4;Scholar 抓取/CAPTCHA/PDF 下载**项目本体**见《谷歌学术爬虫-调研-Scholar抓取与CAPTCHA与下载》(R2);官方开放 API 路线见《检索成果-角度2》。本文聚焦**「库/客户端」层面**,与上述不重复。

---

## 〇、一句话结论(TL;DR)

1. **元数据 / 标题→DOI(`query`/`resolve`)**:本项目已用 `requests` 直连 Crossref / OpenAlex / S2 / Unpaywall(见 `sources/aggregators.py` + `http_client` 的按域限速/退避/熔断),**够用且零额外依赖、可控性最好**。现成客户端(`habanero`/`pyalex`/`semanticscholar`)**不解决我们没有的问题、还会绕过我们的礼貌限速器**,故 **默认保持自建**;仅把它们作为**查询构造/字段路径的参考**(尤其 `habanero.query_bibliographic` 做标题→DOI、`pyalex` 的 filter/semantic-similar)。若确需「相似作品」发现,`pyalex` 的语义检索是唯一低成本增量。
2. **Scholar 原生字段抓取(`scholar/`)**:`scholarly` 是事实标准、解析比我们手写 `serp.py` 更全(作者档/`citedby`/版本/BibTeX),**建议作为可选后端「增强」而非「替换」**我们的 `fetcher`(curl_cffi→nodriver)+`proxy`+`captcha` 反爬栈——因为 `scholarly` **不自带过人机**(高频 `search_pubs`/`citedby` 仍封 IP、需付费代理),且 **PyPI 停在 v1.7.11(2023-01)**、只能 pin git。**只在「要 GS 被引/版本/h-index」这条次要路径上引入**;主线(OA PDF)按失败数据几乎碰不到 reCAPTCHA,无需它。
3. **免费 SERP / SerpApi 替代**:除 **`DDGS`(免费开源、多引擎)** 外,2026 的「SerpApi 替代」几乎全是**付费**(Serper/SearchApi/ScraperAPI/ScrapeBadger…,归角度4)。`DDGS` 值得评估用来**替换 `sources/websearch.py` 手写的 DDG 解析**(库维护、能吸收 DDG markup 变更)。

---

## 一、评估口径与「与本项目现状」的关系

评估维度:**时效**(2026 是否活跃)· **适配**(能否用于 `scholar` SERP / `query`·`resolve` 标题→DOI / 元数据)· **维护**(版本节奏、发布渠道)· **star / 许可**。

本项目现状(决定「买不买轮子」的关键):

| 环节 | 现有实现 | 是否已满足 |
|---|---|---|
| 标题→DOI(`resolve`) | `requests` 直连 Crossref/OpenAlex/S2 检索 | ✅ 基本满足 |
| 元数据 + OA 直链 | `sources/aggregators.py`(Unpaywall/OpenAlex/S2/Crossref/CORE…)+ `http_client`(按域限速/退避/熔断) | ✅ 满足,且**限速受控** |
| Scholar SERP 解析 | `scholar/serp.py`(纯解析)+ `scholar/fetcher.py`(curl_cffi→nodriver 分层)+ `proxy`/`captcha` | ⚠️ 解析仅覆盖搜索结果;**作者档/citedby 未覆盖** |
| 免费网页搜索兜底 | `sources/websearch.py`(手写 DDG html + Bing SERP) | ⚠️ 手写解析,markup 变更需自维护 |

> 结论前提:**能自建的元数据直连已自建**,轮子的价值主要在 ①Scholar 原生字段解析(`scholarly`)②免费 SERP 库(`DDGS`)。

---

## 二、主决策表(2026-07 核验)

| 库 | 类别 | 许可 | 版本 / 时效 | 适配本项目 | 建议 |
|---|---|---|---|---|---|
| **scholarly** | GS 抓取 | Unlicense | PyPI **v1.7.11(2023-01,停)**;git `main` 有补丁;~1.9k★ | GS 作者档/`search_pubs`/`citedby`/版本;内置 `ProxyGenerator` | **整合(可选后端)**:增强 GS 原生字段,不替换 fetcher;pin git |
| **DDGS**(原 duckduckgo-search) | 免费 SERP | MIT | 活跃(2026 持续发版) | 多引擎免费检索,可替代 `websearch.py` 的 DDG 手写解析 | **评估采用**(免费 SERP 兜底) |
| **habanero** | 元数据(Crossref) | MIT | **v2.x(2026 活跃,sckott 维护)**,Py≥3.10 | 标题→DOI(`query_bibliographic`)、polite pool、cursor 深分页、内容协商 | **参考/可选**(自建已覆盖) |
| **pyalex** | 元数据(OpenAlex) | MIT | **v0.21(2026-02-23)**,~391★,活跃 | 标题→DOI、filter/select/分页、**语义找相似**;⚠️2026-02-13 起需免费 key | **参考/可选**(相似作品是唯一增量) |
| **semanticscholar** | 元数据(S2) | MIT | **v0.12.0(2026-03-29)**,志愿维护,Py≥3.10 | S2 图谱、`openAccessPdf`、TLDR、推荐 | **参考/可选**(自建已覆盖) |
| **crossref-commons** | 元数据(Crossref) | MIT(Crossref 官方) | 维护一般,社区不及 habanero | Crossref 访问 | **不用**(优先 habanero,或自建) |
| **crossrefapi (Python)** | 元数据(Crossref) | MIT | 老牌、更新慢 | Crossref works 对象 | **不用** |
| Publish or Perish | GUI 工具 | 免费(闭源) | 活跃 | 桌面端 GS 引文分析,非库 | **参考**(非程序化集成) |
| Google Scholar MCP Server | 封装 | MIT | 新 | 把 `scholarly` 包成 MCP 工具 | **观望**(AI 工作流) |
| Serper/SearchApi/ScraperAPI/ScrapeBadger/ScaleSERP/Scrapingdog/BrightData/Apify | 商业 SERP | 商业 | 活跃 | 付费 GS SERP(过人机外包) | **归角度4**(付费逃生,本项目已有 `scholar_serpapi` 位) |

---

## 三、分类详解

### A. Google Scholar 抓取库

**scholarly(事实标准,但不自带过人机)**
- 能力:`search_author` / `search_pubs` / `citedby` / 作者档(h-index、i10)/ 单篇 / 导出 BibTeX;内置 `ProxyGenerator`(支持 ScraperAPI、Bright Data、FreeProxies、Tor〔v1.5 起弃用〕)。
- 反爬:**不解决**。README 与 PyPI 明确:`citedby`/`search_pubs` 高频会封 IP,**必须挂代理**;`FreeProxies` 对「搜论文/引文网络」基本不可用,规模化需付费代理。即「without CAPTCHAs」是营销话术,天花板仍由代理决定(与 R2 一致)。
- 维护/许可:**PyPI v1.7.11 停在 2023-01**,git `main` 有零星补丁;Unlicense(公有领域,许可最宽松,可自由 vendor)。
- **对本项目**:解析成熟度高于手写 `serp.py`(尤其作者档/citedby/版本);但**不带反爬**,且我们已有更现代的 `nodriver` 分层 fetcher。→ **作为 `scholar/fetcher.py` 的一个可选引擎(ScholarlyEngine)整合**,专供「GS 被引/版本/作者档」次要路径;主线不依赖。引入方式:可选依赖 `extras=[scholar]`、函数内延迟导入、pin git commit。

**free 谷歌学术客户端(其余)**:`scholar.py`(2022 停更,选择器老化)、`sort-google-scholar`(轻量找高引)、`scrape-google-scholar-py`(自建/SerpApi 双后端)、`ScholarDock`(Web 可视化)、`resp`/`paper-search-cli`(多源、GS 走 SerpApi)——**均已在 R2 覆盖**,本项目用不到「再引入一个 GS 抓取器」,`scholarly` 足以充当底座。

### B. 元数据 API 客户端(Crossref / OpenAlex / S2)

- **habanero(Crossref,最推荐的 Crossref 客户端)**:polite pool(`mailto`)、`works(query_bibliographic=...)` 做标题→DOI、cursor 深分页、内容协商(取 BibTeX/CSL)。是 Crossref 官方博客点名、社区最主流的客户端。但**本项目已用 `requests` 直连 `api.crossref.org/works` 并做了 mailto/限速**,habanero 的净增量主要是「idiomatic 查询构造 + cursor 封装」。
- **pyalex(OpenAlex)**:filter/search/select/分页/group、**`Works().similar()` 语义找相似作品**;⚠️ **2026-02-13 起 OpenAlex 全量需免费 API key**(本项目 `config.openalex_key` 已预留,领先一步)。语义相似是我们自建没有的唯一增量。
- **semanticscholar(S2,非官方)**:图谱 + `openAccessPdf` + TLDR + 推荐;志愿维护、活跃。功能与我们自建 S2 连接器重叠。
- **crossref-commons / crossrefapi**:替代 Crossref 客户端,维护与社区均不及 habanero → 不选。
- **对本项目**:`query`/`resolve` 与 `sources/aggregators.py` 已用 `requests` 覆盖,且**统一走 `http_client` 的按域限速/退避/熔断**(第三方库自带 HTTP 会绕过这套礼貌策略,反而是减分项)。→ **保持自建**;把 habanero/pyalex 当**查询构造与字段路径的参考**。仅在需要「语义找相似」时可选引入 `pyalex`。

### C. 免费 SERP / SerpApi 替代

- **DDGS(原 `duckduckgo-search`,MIT,活跃)**:免费、开源、多引擎(DuckDuckGo 等)Python 检索库。**直接对口 `sources/websearch.py`**:可替换我们手写的 DDG html 解析,交给库吸收 markup/端点变更。→ **值得评估采用**(作为 websearch 的 DDG 后端;仍保留我方 Bing 与 158 的浏览器版分工)。
- 其余「SerpApi 替代」(Serper、SearchApi、ScraperAPI、ScrapeBadger、Scale SERP、Scrapingdog、Bright Data、Apify、WebScrapingAPI)**全部付费**(多有免费试用额度),属**角度4**;本项目已有 `scholar_serpapi` 作为付费逃生位,不在本文重复横评。
- **Publish or Perish**:免费桌面工具、非库,适合人工引文分析,不做程序化集成。

---

## 四、Top1–2 源码/实现要点(是否内置过验证/代理、维护、许可)

**① scholarly(GS 抓取 Top1)**
- 过验证:**无自动过 reCAPTCHA**;`_navigator` 检测到验证/封锁即抛异常,靠切代理规避。
- 代理:内置 `ProxyGenerator`,支持 `ScraperAPI()` / `luminati/BrightData` / `FreeProxies()` / `SingleProxy()` / `Tor(已弃用)`;「知道哪些查询需要代理」。
- 维护/许可:git `main` 微维护、**PyPI 未再发版(v1.7.11/2023-01)**;Unlicense(可自由 vendor/pin commit)。
- 结论:**增强不替换**——它的价值是「成熟的 GS 字段解析」,不是「过人机」;过人机仍归我们的 `fetcher`(nodriver)+`proxy`+`captcha`。

**② pyalex(元数据 Top1,若要引库)**
- 过验证:**不涉及**(官方 OpenAlex REST,无反爬)。
- 代理/key:2026-02-13 起需免费 API key;`pyalex.config.api_key = ...`、`email = ...`(polite)。
- 维护/许可:MIT、~391★、v0.21(2026-02)、双人维护、19 个 release,**活跃**。
- 结论:轻薄、贴合官方设计;**唯一增量是语义相似**,其余我们自建已覆盖。

---

## 五、针对本项目的采用建议(分环节)

- **`resolve` / `query`(标题→DOI + 元数据)**:**保持自建 `requests` 直连**(零依赖、统一限速)。把 `habanero`(Crossref 标题查询、cursor)、`pyalex`(filter/相似)当**参考**;仅「语义找相似作品」需求出现时,把 `pyalex` 作为**可选**依赖引入。
- **`scholar/`(GS 原生字段)**:把 `scholarly` 作为**可选后端引擎**整合进 `fetcher` 的引擎序(与 `SerpApiEngine`/`nodriver` 并列),仅服务「被引/版本/作者档」次要路径;**不替换**现有反爬栈;可选依赖 + 延迟导入 + pin git commit。
- **`sources/websearch.py`(免费 SERP 兜底)**:评估用 **`DDGS`** 替换手写 DDG 解析(维护更省心);与 158 的浏览器版 Bing 分工不变。
- **付费逃生**:规模化过人机仍走 `scholar_serpapi`(SerpApi)或角度4 商业 API + 打码(`captcha.py` 已就位),不自解 reCAPTCHA 硬刚。

---

## 六、关键结论:`scholarly` 能否取代 / 增强我们自建的 Scholar SERP 解析?

- **不能「取代」我们的反爬栈**:`scholarly` 不自带过人机(高频必封、需付费代理),我们的 `fetcher`(curl_cffi→nodriver)+`proxy`+`captcha` 才是过人机主体,更现代。
- **可以「增强」字段解析**:`scholarly` 对**作者档 / citedby / 版本 / BibTeX** 的解析比手写 `serp.py` 成熟得多。→ **最佳姿态 = 把 `scholarly` 当一个可选「解析后端/引擎」**,在需要 GS 原生字段时启用,底层取回仍可复用我们的反爬会话(或用其 `ProxyGenerator` 接住宅代理)。
- **主线不需要它**:按失败数据,拿全文 PDF 的主线几乎不碰 reCAPTCHA、也不需要 GS 字段;`scholarly` 属「目标B(GS 原生字段)」的次要增强,**不进强制依赖**。

---

## 七、来源(2026-07-01 核验)
- PyPI/GitHub:`scholarly`(v1.7.11/2023-01、Unlicense、~1.9k★、ProxyGenerator/ScraperAPI)、`habanero`(v2.x、MIT、Crossref polite/cursor/内容协商)、`pyalex`(v0.21/2026-02-23、MIT、~391★、语义相似、2026-02 起需 key)、`semanticscholar`(v0.12.0/2026-03-29、MIT)、`DDGS`(MIT、免费多引擎)。
- Crossref 官方博客/文档:Python 客户端清单(habanero、crossref-commons、crossrefapi)、polite pool 用法。
- 选型对照:第三方评测(ScraperAPI/ScrapingBee/ScrapeBadger《2026 Google Scholar API/SerpApi 替代》,结论:无官方 API、规模化需付费 SERP 或代理;免费程序化仅 DDGS/Publish or Perish)。
- 本仓交叉:《谷歌学术爬虫-调研-Scholar抓取与CAPTCHA与下载》(R2)、《检索成果-角度2/角度4》、`fulltext_fetcher/sources/aggregators.py`、`fulltext_fetcher/scholar/*`、`fulltext_fetcher/sources/websearch.py`。
