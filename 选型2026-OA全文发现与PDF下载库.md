# 选型 2026 — OA 全文发现与 PDF 下载库（是否重造轮子核查）

> **任务背景**：项目 `fulltext_fetcher/`（输入 DOI/标题 → 多源发现 OA 全文 → `%PDF` 校验下载入库）已自建 20+ 源（unpaywall/openalex/s2/crossref/core/base/doaj/europe_pmc/pmc/arxiv/biorxiv/hal/osf/zenodo/openaire/scienceopen/publisher_oa/oa_button/websearch/wayback…）+ 分层下载栈。本文核查：**是否有更好的现成库可直接用或借鉴，避免重造轮子**。
> **调研角度⑤**（服务 `sources/` 与 `download.py`）｜整理人：谷歌学术人机认证-151（本组 worker 会话）｜日期：2026-07-01｜联网核验：2026-07-01（WebSearch/WebFetch）
> **结论先行**：项目自建栈在**源覆盖广度、下载分层兜底（curl_cffi 指纹 / 落地页 PDF 抠取 / 出版商适配 / 渲染）、PDF 校验**上已**优于所有现成库**，**不建议整包替换**；但有 **5 处具体手法 / 3 个源**值得**借鉴移植**（见 §三、§四）。

---

## 〇、TL;DR（一页结论）

1. **没有一个现成库能整包替换本项目**。市面项目分两类：①**下载器**（PyPaperBot/scidownl/doi2pdf——Scholar+SciHub 中心、易封、维护弱）；②**OA 聚合发现**（paperscraper/resp/metapub/paper-fetch/doidownloader——源比我方少、下载兜底比我方薄）。本项目已是「聚合发现 + 强下载兜底 + PDF 校验」三合一，**广度与健壮度领先**。
2. **最值得借鉴的两个（Top1-2 已读源码/文档）**：
   - **metapub `FindIt`**（Apache-2.0，157★，2026 活跃）：内置 **68+ 出版商的 PDF 定位注册表**（97.1% 覆盖）——**远超我方 `publisher_adapter.py`/`landing.py` 现有 7 家**。借鉴其出版商→PDF URL 规则表，可系统化补齐我方出版商模板。
   - **paperscraper**（MIT，534★，v1.0.0 / 2026-06，最活跃）：其 **PDF fallback 手法**值得抄——**BioC-PMC XML、eLife XML 全文**、**Wiley/Elsevier TDM API token**、**bioRxiv S3**。这几条正好补我方对**生医 OA / 订阅型语料**的短板（规模化实测订阅型命中仅 ~11%）。
3. **可借鉴的 3 个源**：**ACL Anthology、ACM DL**（来自 `resp`/`respf`——我方缺 NLP/CL 会议录与 ACM）、**eLife XML 仓库**（paperscraper）。
4. **官方/薄封装 SDK（pyalex / semanticscholar / habanero / unpywall）一律不采用**：项目已**直连**各 API 的免费端点，封装库只会**多一层依赖**（unpywall 还强依赖 pandas），且 OpenAlex 单条按 DOI 免费端点我方已用对——封装库无增量价值。
5. **合规红线不变**：借鉴对象一律取其**合法 OA 路线**；SciHub 类（PyPaperBot/scidownl/doi2pdf）只作 DOI 兜底认知，不纳入主线（与角度2 主线判断一致）。

---

## 一、决策总表

> 排序维度：**时效（2026 活跃度）> 适配（能否直接用在 `sources/`/`download.py` 或借鉴其手法）> 维护 > star**。
> star / 更新以 2026-07-01 核验为准；标「~/未核」者为避免过度请求 GitHub 未鉴权 API 而未逐仓核验的估计值。

### A. 强烈建议借鉴（手法级移植，不整包引入）

| 项目 | star | 最近更新 | 许可 | 适配哪个模块 | 采用/跳过 + 理由 | 集成工作量 |
|---|---|---|---|---|---|---|
| **metapub `FindIt`** (nthmost) | 157 | 2026 活跃 (v0.6.4) | Apache-2.0 | `publisher_adapter.py` / `landing.py` | **借鉴（不整包）**：68+ 出版商 PDF 定位注册表 + `UrlReverse`（URL→DOI/PMID），远超我方 7 家出版商模板。整包引入太重（生医偏向、绑 eutils），但其**出版商规则表是最大金矿** | 中 |
| **paperscraper** (jannisborn) | 534 | 2026-06 (v1.0.0) | MIT | `sources/repositories.py`、`download.py`、`config.py` | **借鉴（不整包）**：PDF fallback 手法（BioC-PMC XML / eLife XML / Wiley·Elsevier TDM token / bioRxiv S3）。库本体是「dump 到本地再检索」模型，与我方在线聚合定位不同，不整包用 | 中 |

### B. 可借鉴具体源 / 设计

| 项目 | star | 最近更新 | 许可 | 适配哪个模块 | 采用/跳过 + 理由 | 集成工作量 |
|---|---|---|---|---|---|---|
| **resp / respf** (monk1337) | 487 | 2025-12 (v0.1.2 / PyPI respf 1.3.1) | Apache-2.0 | `sources/`（新增 `acl`/`acm`）、`free_adapters.py` | **借鉴**：**ACL Anthology、ACM DL** 源适配器（我方缺 NLP/CL 会议录、ACM）；其 `direct_url` Springer/Nature 启发式我方已有等价物 | 小-中 |
| **rafguns/doidownloader** | 0 | 2024+（活跃提交） | MIT | `http_client.py`、`pipeline.py` | **借鉴**：**robots.txt `crawl-delay` 自适应限速** + **async 按域并发**（一慢站不拖全局）+ 只走合法源、Version-of-Record 优先。设计参考价值 > 直接用 | 小 |
| **auto-paper-harvester** (Grenzlinie) | 0 | 2026-06 (v0.2.0) | MIT | `publisher_adapter.py` | **借鉴**：**24 个 DOI 前缀 → 出版商 tier 路由表**（`full`/`oa_only`/`partial`/`browser_only`/`unsupported`）。0★ 未经验证，仅借鉴其**表结构与分层思路** | 小 |

### C. 官方 / 薄封装 SDK（可选，**不采用**）

| 项目 | star | 最近更新 | 许可 | 适配哪个模块 | 采用/跳过 + 理由 | 集成工作量 |
|---|---|---|---|---|---|---|
| **pyalex** (J535D165) | ~250 (未核) | 2026-02 (v0.21) | MIT | `sources/aggregators.py` (OpenAlex) | **不采用（可选）**：项目已用 OpenAlex「单条按 DOI 免费」端点。pyalex 便于 bulk/分页/倒排摘要还原，但**多一层依赖**、且内容下载端点收费无益。仅大规模 List/Search 时才值得 | 小 |
| **semanticscholar** (danielnsilva) | ~700 (未核) | 活跃 | MIT | `sources/aggregators.py` (S2) | **不采用（可选）**：项目已直连 S2 `openAccessPdf`。其 async/bulk/typed 是加分项但收益有限，我方已有并发/退避 | 小 |
| **habanero** (sckott) | ~300 (未核) | v2.4.0 活跃 | MIT | `sources/aggregators.py` (Crossref)、`citations.py` | **不采用（可选）**：项目已直连 Crossref。其 `content_negotiation`（取多格式引文）可备 `citations.py` 参考，非全文所需 | 小 |
| **unpywall** (unpywall) | 34 | 2024-02 (Alpha) | MIT | `sources/aggregators.py` (Unpaywall) | **跳过**：强依赖 **pandas**、状态 Alpha；我方 Unpaywall 连接器更轻更专注（直取 `url_for_pdf`） | — |

### D. 跳过（下载器类 / 已被覆盖）

| 项目 | star | 最近更新 | 许可 | 适配哪个模块 | 采用/跳过 + 理由 | 集成工作量 |
|---|---|---|---|---|---|---|
| **PyPaperBot** (ferru97) | 644 | 2024-12 (v1.4.1) | MIT | — | **跳过**：Google Scholar + SciHub/SciDB 中心，易被封、定位与我方不同（角度1 已评）。批量下载场景可作外部工具，非本项目库依赖 | — |
| **scidownl** (Tishacy) | 303 | 2024-02（实测停更） | MIT | `sources/scihub.py` | **跳过**：Issue #32 实测 2025-06 起 403 失效、PR#34 待合；SciHub-only、单人维护。我方已有可选 `scihub`（默认关） | — |
| **doi2pdf** (croumegous / byigitt) | 5 / 13 | 2024 / 2025 | MIT | — | **跳过**：SciHub 中心、star 极低、维护弱；byigitt 版走 undetected-chromedriver 过 SciHub，越界又脆 | — |
| **PyPaperRetriever** (JosephIsaacTurner) | 38 | 2025 (JOSS) | MIT | — | **跳过**：源（Unpaywall/Entrez/Crossref）我方已全覆盖；figure 抽取/引文网络越界。其「每篇 JSON sidecar 记来源」我方 `attempts.jsonl` 已等价 | — |
| **paper-fetch** (Agents365-ai) | 143 | 2026-06 (v0.15.1) | MIT | — | **跳过**：架构（DOI→PDF 7 源 fallback + JSON envelope + `%PDF` 校验 + SSRF 防护 + 50MB 上限）与本项目**高度相似但源更少**、纯 stdlib。**作为设计印证**，无采用价值 | — |

---

## 二、Top1-2 源码 / 文档精读

### Top1 — metapub `FindIt`（最大借鉴价值：出版商 PDF 定位注册表）

- **它怎么拿 PDF**：`FindIt(pmid_or_doi)` → `src.url`（直链）/ `src.reason`（`PAYWALL`/`TXERROR`/`NOFORMAT`）/ `src.backup_url`。核心是一张**内置、随包发布的期刊→出版商注册表**（`JournalRegistry`，声称 **68+ 出版商、97.1% 覆盖**），按出版商各自的 URL 规律**构造** PDF 直链（Highwire/citation_pdf_url、出版商专属路径等）；本身**不下载**，拿到 URL 交 `requests`。
- **附带 `UrlReverse`**：给一个 abstract/pdf/fulltext URL，反解出 DOI/PMID/PMCID（记录 `steps`）——对我方「落地页/搜索命中 URL → 归一到 DOI」有用。
- **我方对照**：`publisher_adapter.py`（按 DOI 前缀出模板）+ `landing.py`（`_is_publisher_pdf` 仅 Elsevier/Springer/Wiley/ACS/RSC/IEEE/MDPI **7 家**）。**metapub 的注册表规模是我方的近 10 倍**。
- **采用建议**：**不整包引入**（重、生医偏向、绑 eutils/Entrez）；**借鉴其出版商 PDF 规则**，把 `publisher_adapter.py` 从 7 家扩到数十家（Apache-2.0 许可允许借鉴其规则思路，落地时以我方独立实现为准）。

### Top2 — paperscraper（最大借鉴价值：OA 全文 fallback 手法）

- **它怎么拿 PDF**：`save_pdf({"doi": ...}, filepath=...)`；`download_pdf_to_path` 流式下载 + **首块 `%PDF` 校验**（与我方一致，但我方更严：`%%EOF` 截断检测 + min/max 体积 + 落地页二次抠取）。
- **关键 fallback 链（这是金矿）**：直链失败后依次尝试——
  1. **BioC-PMC XML**：PMC OA 论文的全文 XML（当渲染 PDF 404 时的可靠替代）；
  2. **eLife XML**：从 eLife 官方 article-XML 仓库取全文；
  3. **出版商 TDM API**（`WILEY_TDM_API_TOKEN` / `ELSEVIER_TDM_API_KEY`，机构学者**免费合规**）；
  4. **bioRxiv S3**（AWS requester-pays 凭据批量取全文）。
- **我方对照**：`europe_pmc` 只取渲染 PDF / `ptpmcrender.fcgi`，**未取 BioC/JATS XML**；无 eLife 专源；`config.py` 无 Wiley/Elsevier TDM key 位。**这几条正对我方规模化实测的痛点**（订阅型语料免费源命中天花板 ~11%，出版商 403 占多数）。
- **采用建议**：**不整包引入**（其「先 dump 全站再本地检索」模型与我方在线定位不同）；**移植其 fallback 手法**（见 §三）。

---

## 三、我们漏掉的源与手法（可回收增量）

### 漏掉的「源」
1. **ACL Anthology**（NLP/CL 会议录，`aclanthology.org` 有稳定 PDF 直链规律）——来自 `resp`。我方 `sources/` 无此源，NLP 语料会漏。
2. **ACM Digital Library**（`10.1145/*`，`dl.acm.org`；OA/Author-ize 链接）——来自 `resp`。
3. **eLife XML 仓库**（生医 OA 全文 XML）——来自 paperscraper。
4. **PMC BioC / JATS 全文 XML 接口**（`.../{PMCID}/fullTextXML` 我方速查表列了但连接器只取 render PDF，未取 XML 兜底）。

### 漏掉的「手法」（按性价比排序）
1. **出版商 PDF 规则表大扩充**（metapub / auto-paper-harvester）：把 `publisher_adapter.py` + `landing.py` 的 7 家扩到 **数十家**，并引入 **DOI 前缀 → 出版商 tier 路由表**（`full`/`oa_only`/`partial`/`browser_only`）。**收益最大**（订阅型 403 大量出在少数几家大出版商）。
2. **Wiley / Elsevier TDM API token**（paperscraper）：机构学者**合规免费**，是提升**订阅型语料**命中率**最合规**的手段；`config.py` 加 key 位，`download.py` 增一档 TDM 尝试（合规守卫：仅持 key 用户启用，对齐既有机构订阅集成设计）。
3. **PMC BioC / eLife JATS XML 全文兜底**（paperscraper）：当 `europe_pmc` render PDF 404 时改取 XML 再转/入库，提高生医命中。
4. **robots.txt `crawl-delay` 自适应限速**（doidownloader）：比现在固定 `per_host_interval=0.34s` 更礼貌稳健，降低被封概率；可在 `http_client.py` 增一层按域 crawl-delay 缓存。
5. **bioRxiv S3 requester-pays 批量取全文**（paperscraper）：大规模生物预印本场景的加速档（可选，需 AWS key）。

> 说明：以上均为**增量优化**，非「重造」——项目主干（多源并发 + 熔断 + curl_cffi 指纹兜底 + 落地页抠取 + PDF 校验 + 断点续跑）本就比这些库更完整，无需替换。

---

## 四、落地建议（优先级）

- **P0（收益最大、低风险）**：借鉴 **metapub 出版商注册表** → 扩 `publisher_adapter.py`/`landing.py` 到数十家 + DOI 前缀 tier 路由表。
- **P1（补订阅型短板、需合规守卫）**：接 **Wiley/Elsevier TDM token**（对齐 `机构订阅集成设计.md` 的合规声明，仅持 key 用户启用）。
- **P2（补生医覆盖）**：`europe_pmc`/`pmc` 增 **BioC/JATS XML 全文兜底** + 新增 **eLife 源**。
- **P3（补学科覆盖）**：新增 **ACL Anthology、ACM DL** 源（参照 `resp` 适配器，纯逻辑 + 离线 selftest，遵循 `free_adapters.py` 集成约定）。
- **P4（稳健性）**：`http_client.py` 引入 **robots.txt crawl-delay** 自适应限速。
- **不做**：整包引入任何库；引入 SciHub 类为主线；引入 pandas 依赖（unpywall）。

> 本文仅做选型结论，**不改任何 `.py` / 他人文档**；上述 P0-P4 建议交由总指挥排期后由相应模块负责人实现（涉及 `publisher_adapter.py`/`landing.py`/`download.py`/`config.py`/`http_client.py`/`sources/` 新增源）。

---

## 五、与已有成果的关系

- **补充角度1（GitHub 载体）**：角度1 侧重「抓 Scholar 的载体」；本文侧重「**OA 全文发现 + PDF 下载库**」，与本项目 `fulltext_fetcher/` 直接对口，是对 `paperscraper`/`resp`/`PyPaperBot` 的**落地适配深评**。
- **印证角度2（开放 API 主线）**：所有值得借鉴的库都走 OA 开放数据（Unpaywall/OpenAlex/S2/PMC/预印本），再次印证「开放 API 主线」；官方 SDK 不采用是因我方已直连主线端点。
- **对齐规模化实测**（`检索成果-00` §十 / `检索成果-数据-规模化验证报告.md`）：本文 §三「漏掉的手法」精准对应实测暴露的「订阅型 403 天花板」问题（TDM token / 出版商规则表 / XML 兜底）。

---

## 六、来源（2026-07-01 联网核验）

- GitHub：metapub/metapub（157★, Apache-2.0）、jannisborn/paperscraper（534★, MIT, v1.0.0）、monk1337/resp + PyPI respf（487★ / v1.3.1）、rafguns/doidownloader（0★, MIT）、Grenzlinie/auto-paper-harvester（0★, 2026-06）、ferru97/PyPaperBot（644★, v1.4.1）、Tishacy/SciDownl（303★, Issue#32 实测失效）、croumegous/doi2pdf（5★）、byigitt/doi2pdf（13★）、JosephIsaacTurner/pypaperretriever（38★, JOSS 2025）、Agents365-ai/paper-fetch（143★, v0.15.1）、J535D165/pyalex（v0.21）、danielnsilva/semanticscholar、sckott/habanero（v2.4.0）、unpywall/unpywall（34★, v0.2.3）、olivettigroup/article-downloader（v9.1.1）
- 文档：metapub.readthedocs.io（FindIt / JournalRegistry / UrlReverse）、jannisborn.github.io/paperscraper（PDF Retrieval fallback：BioC-PMC XML / eLife XML / Publisher TDM / bioRxiv S3）、paperscraper `pdf/utils.py`（`download_pdf_to_path` 首块 `%PDF` 校验、`load_api_keys`）、pypi.org（各库版本/更新时间）、JOSS 08135（PyPaperRetriever）
- 项目内对照：`fulltext_fetcher/sources/*.py`、`download.py`、`landing.py`、`publisher_adapter.py`、`config.py`、`fulltext_fetcher资料-各源接口速查.md`、`检索成果-00-聚合总报告与选型决策.md`、`检索成果-角度1/角度2`
