# 谷歌学术过人机认证开源项目检索 — 角度2：官方开放 API 替代路线

> 工作组目标：绕过谷歌学术（Google Scholar）的人机检测认证，直接抓取元数据并下载 PDF。
> 本文件为「角度2（官方开放 API 替代路线）」的检索汇总，供多角度成果聚合使用。
> 整理人：谷歌学术人机认证-144（本组总指挥会话）｜日期：2026-06-30
> 数据现状均按 2026-06 最新核验（OpenAlex 计费、Semantic Scholar bulk、Unpaywall 限额）。

---

## 〇、本角度的核心思路（为什么这是最优解）

角度7（中文社区与镜像站）的结论里已明确建议「另开角度评估官方开放 API」。本角度正是对它的展开。

**关键认知**：与谷歌学术「斗法」（stealth 指纹 + 住宅代理 + 打码）本质是一场**永无止境的军备竞赛**——Google 从未提供公开 Scholar API，`robots.txt` 明令禁止自动化抓取，任何绕过都处于灰色地带且随时被封。

而 Crossref / OpenAlex / Semantic Scholar / Unpaywall 这四家是**专门为程序化访问而生的开放学术基础设施**：它们提供官方 REST API、有稳定的限额与文档、数据多为 CC0/CC-BY、**根本不存在人机验证（CAPTCHA）这一关**。用它们替代 Scholar，等于把问题「从绕墙改为走正门」。

| 维度 | 抓 Google Scholar（角度1/3/6/7） | 开放 API（本角度） |
| --- | --- | --- |
| 人机验证 | 有 reCAPTCHA，需持续对抗 | **无，根本不存在** |
| 合规性 | 灰色，违反 ToS/robots.txt | **白色，官方鼓励调用** |
| 稳定性 | 随反爬升级随时失效 | 有 SLA/文档，版本化 |
| 元数据质量 | HTML 解析、字段易缺 | 结构化 JSON，字段齐全 |
| 直链 PDF | 需二跳（Sci-Hub 等） | OpenAlex/S2/Unpaywall 直给 OA PDF |
| 被引/引文网络 | Scholar 强项 | OpenAlex/S2 同样提供 |
| 唯一短板 | —— | 不含**付费墙内**全文（仅开放获取） |

---

## 一、四大开放 API 总览

| API | 运营方 | 覆盖量 | 认证 / 费用（2026） | 元数据 | 开放 PDF 直链 | 核心端点 |
| --- | --- | --- | --- | --- | --- | --- |
| **Crossref** | Crossref（非营利） | 1.6 亿+ DOI 记录 | 免费、**无需 key**；建议 `mailto` 进礼貌池；Plus 付费保 SLA | 标题/作者/期刊/年份/被引/license/资助 | ❌（仅偶含 `link`，多需授权） | `GET api.crossref.org/works` |
| **OpenAlex** | OurResearch（非营利） | **4.8 亿+** works | **需免费 key**（30 秒申请）；用量计费，每 key 每天 **$1 免费额度**；全量 snapshot CC0 免费下载 | 全字段 + 主题/机构/SDG/FWCI | ✅ `open_access.oa_url` / `best_oa_location.pdf_url` | `GET api.openalex.org/works` |
| **Semantic Scholar** | Allen AI (Ai2) | 2 亿+ 论文 | 免费；**建议申请免费 key** 提速率 | 标题/摘要/作者/被引/引文网络/**TLDR AI 摘要** | ✅ `openAccessPdf` 字段 | `GET api.semanticscholar.org/graph/v1/paper/search/bulk` |
| **Unpaywall** | OurResearch（非营利） | 4000 万+ 免费全文 | 免费、**仅需 email**；非商用；**10 万次/天** | OA 状态/版本/license | ✅✅ `best_oa_location.url_for_pdf`（专做这件事） | `GET api.unpaywall.org/v2/{doi}` |

> 角色分工一句话：**Crossref/OpenAlex/S2 负责「找到论文 + 拿元数据」，Unpaywall（及 OpenAlex/S2 的 OA 字段）负责「把这篇论文的免费 PDF 直链找出来」。**

---

## 二、逐个详解

### 1. Crossref REST API —— DOI 与元数据的「户口本」
- **定位**：几乎所有正式出版物的 DOI 注册方，元数据最权威、最全的「索引层」。
- **端点**：`https://api.crossref.org/works?query=...`；按 DOI：`/works/{doi}`。
- **费用**：完全免费、无需注册 key。强烈建议在请求里带 `mailto=you@example.com`（或 User-Agent 注明），即进入 **polite pool（礼貌池）**，比匿名 pool 更稳更快；预算充足可买 **Metadata Plus** 拿到保证速率与快照。
- **能力**：关键词/作者/期刊/时间/类型过滤、按被引排序、`select` 裁字段、`cursor` 深分页（适合百万级批量拉取）。
- **短板**：**基本不提供可下载 PDF**（`link` 字段多指向出版社落地页，需订阅）。→ 必须与 Unpaywall 配合补 OA 全文。
- **示例**：

```bash
curl "https://api.crossref.org/works?query.bibliographic=large+language+model&filter=from-pub-date:2025-01-01&rows=20&mailto=you@example.com"
```

### 2. OpenAlex —— 覆盖最广、最适合「替代 Scholar 做学术发现」
- **定位**：MAG（微软学术图谱）停服后的开放继任者，**覆盖约 Scholar 量级且对非英语/全球南方更好**，含作者消歧、机构、主题、SDG、FWCI 等丰富图谱。
- **端点**：`https://api.openalex.org/works`，支持 `search=`（全文检索）、`filter=`（精确过滤）、`group_by=`（聚合统计）。
- **2026 计费变化（重要）**：现已**强制需要免费 API key**（`openalex.org/settings/api` 30 秒申请），改为**用量计费**——
  - 按 DOI/ID 单条查询：**免费、无限**；
  - list+filter：$0.10/千次（每天**免费 1 万次调用 / 100 万结果**）；
  - search：$1/千次（每天免费 1000 次 / 10 万结果）；
  - PDF/XML 下载（content API 缓存全文）：$10/千次（每天免费 100 篇）。
  - 每个 key **每天送 $1 免费额度**，日常科研（几十次搜索 + 几百次过滤）一般完全免费覆盖。
- **拿 PDF**：work 对象的 `open_access.oa_url`、`primary_location.pdf_url`、`best_oa_location.pdf_url` 直接给开放获取 PDF。
- **大批量推荐**：与其疯狂打 API，不如直接下载**全量 snapshot（CC0、季度更新、免费）**到本地建库——这是最省钱、最快、彻底无限额的方式。
- **示例**：

```bash
curl "https://api.openalex.org/works?search=graph+neural+network&filter=publication_year:2025,is_oa:true&per_page=50&api_key=YOUR_KEY"
```

### 3. Semantic Scholar Academic Graph API —— 引文网络 + AI 摘要
- **定位**：Allen AI 出品，2 亿+ 论文，强在**引文上下文、influential citations、TLDR（AI 一句话摘要）、论文推荐**。
- **两个检索端点**：
  - **bulk search（推荐）** `GET /graph/v1/paper/search/bulk`：支持布尔语法（`+` AND / `|` OR / `-` NOT / `"短语"` / `*` 通配 / `()` 分组），**token 分页，单次 1000、最多可翻 1000 万条**，可按 `citationCount/publicationDate/paperId` 排序；
  - relevance search `GET /graph/v1/paper/search`：offset/limit，最多 1000，相关度排序更细。
- **拿 PDF**：`fields` 里加 `openAccessPdf` 即返回开放获取 PDF 直链；还可加 `tldr,abstract,externalIds` 等。
- **批量取详情**：`POST /graph/v1/paper/batch` 一次拿多篇详情，省调用。
- **限额**：匿名有较低共享速率；**申请免费 API key**（放 `x-api-key` 头）显著提速。
- **示例**：

```bash
curl "https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=\"diffusion model\"&fields=title,year,openAccessPdf,tldr&year=2024-"
```

### 4. Unpaywall —— 「给我一个 DOI，我还你免费 PDF」
- **定位**：OurResearch 出品，4000 万+ 合法 OA 全文索引（来自机构库、预印本、出版社等），**专职解决「这篇有没有免费 PDF、在哪下」**。
- **端点**：`GET https://api.unpaywall.org/v2/{doi}?email=you@example.com`（仅需 email，非商用免费）。
- **返回关键字段**：`is_oa`（是否有 OA）、`oa_status`（gold/green/hybrid/bronze/closed）、`best_oa_location.url_for_pdf`（**最佳免费 PDF 直链**）、`oa_locations[]`（全部 OA 来源）。
- **限额**：**10 万次/天**（约 1.15 req/s 持续，可短时突发），超限 429；更大规模请用官方 **Data Feed / snapshot**。
- **注意**：① **邮箱必须真实有效**——占位邮箱（如 `you@example.com`）会被拒、返回 **422 Unprocessable Entity**（〔98复核 2026-07-01 实测确认〕，下方示例请替换为真实邮箱）；② 其 search 端点自 2026-03 起常返回 500、疑似弃用——**正确姿势是先从 OpenAlex/S2/PubMed/Crossref 拿到 DOI，再逐 DOI 查 Unpaywall**。
- **示例**：

```bash
curl -s "https://api.unpaywall.org/v2/10.1145/3292500.3330672?email=you@example.com" | jq '.best_oa_location.url_for_pdf'
```

---

## 三、补充开放数据源（按需扩展）

| 源 | 特点 | 是否给全文 |
| --- | --- | --- |
| **arXiv API** | 物理/数学/CS/AI 预印本，`export.arxiv.org/api/query` | ✅ 直接 PDF，无墙 |
| **PubMed / NCBI E-utilities** | 生物医学权威，`eutils.ncbi.nlm.nih.gov` | 元数据；全文经 **PMC** OA 子集 |
| **Europe PMC** | 生医，含全文检索与 OA 全文 | ✅ 大量 OA 全文/XML |
| **CORE** | 聚合全球 2 亿+ OA 论文，需免费 key | ✅ 提供 OA PDF |
| **DOAJ** | 开放获取期刊目录 | ✅ OA 期刊 |
| **OpenAIRE / BASE / Lens.org** | 欧盟/全球聚合、专利+论文 | 部分 OA 全文 |

> 工具层：`Publish or Perish` 软件可同时查 Scholar/Crossref/OpenAlex/S2 等多后端；Python 侧 `pyalex`(OpenAlex)、`semanticscholar`、`habanero`(Crossref)、`pyunpaywall`/`unpywall` 等封装库可直接用。

---

## 四、推荐落地工作流（三段式流水线）

```
①发现 & 元数据            ②定位免费全文           ③下载 & 入库
─────────────────       ─────────────────      ─────────────────
OpenAlex /search   ──►   每条记录已带 oa_url     ──► requests 下 PDF
  或 S2 bulk search       │（缺则用 DOI）          ──► 校验/去重/存 Zotero
  或 Crossref query       └─► Unpaywall(DOI)          或本地库 + 元数据JSON
        │
   统一抽出 DOI 列表
```

- **元数据主力**：OpenAlex（覆盖广）或 Semantic Scholar bulk（引文+TLDR），二者直接带 OA PDF 字段；Crossref 作 DOI 权威补全。
- **全文兜底**：凡元数据未直接给 PDF 的，拿 DOI 批量问 Unpaywall。
- **礼貌与合规**：所有请求带 `mailto/email/api_key` 进礼貌池；遵守各自每日限额；超大规模直接用 OpenAlex/Unpaywall **官方 snapshot** 本地建库（彻底无限额、无 IP 封禁、无人机验证）。
- **与 Scholar 的差距弥补**：唯一拿不到的是**付费墙内未开放**的全文——这部分本就无法合法绕过；其元数据与被引仍可从 OpenAlex/S2 取得。

---

## 五、对工作组目标的结论与建议

1. **这是从根上「免战」的方案**：开放 API 没有人机验证，无需代理/打码/stealth，工程量、合规风险、长期维护成本都最低，**强烈建议作为工作组首选主线**。
2. **覆盖足够**：OpenAlex（4.8 亿）+ S2（2 亿）在「发现 + 元数据 + 被引网络」上已基本对标 Scholar；OA 全文经 Unpaywall/OpenAlex 直链获取，**对开放获取文献是降维打击**。
3. **明确边界**：付费墙内全文开放 API 拿不到——这是合理边界，应通过机构订阅/馆际互借等合法途径解决，而非回到「抓 Scholar + Sci-Hub」的灰色路线。
4. **建议架构**：`元数据(OpenAlex/S2/Crossref) → OA 定位(Unpaywall) → 下载入库`，大规模场景直接落地官方 snapshot 本地库。
5. **与其他角度的关系**：本角度可作为「主线」；角度1（GitHub 爬虫）、角度3/6（反爬/代理）、角度7（镜像站）作为「确需抓 Scholar 时的备线」，二者互补而非替代。

---

## 六、来源
- OpenAlex Developers《API Overview / Authentication & Pricing / List works》developers.openalex.org；OpenAlex Blog《New Features and Usage-Based Pricing》blog.openalex.org
- Semantic Scholar《Academic Graph API Tutorial / API Docs（paper search bulk、openAccessPdf、TLDR）》api.semanticscholar.org、webflow.semanticscholar.org
- Unpaywall《API Reference（/v2/{doi}、best_oa_location、限额 10 万/天、search 端点 2026-03 起异常）》unpaywall.readme.io、roadoi 文档
- Crossref REST API 文档（polite pool / mailto / cursor 深分页 / Metadata Plus）api.crossref.org
- 补充源：arXiv API、NCBI E-utilities、Europe PMC、CORE、DOAJ、OpenAIRE、BASE、Lens.org 官方文档；封装库 pyalex / semanticscholar / habanero / unpywall
