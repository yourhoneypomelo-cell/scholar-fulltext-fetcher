# fulltext_fetcher 各免费全文源「输入 → OA PDF 直链」接口速查表

> 用途:为生产级 `fulltext_fetcher`(输入 DOI/标题 → 全自动抓取全网免费全文/PDF 直链)提供各源精确接口规格,供核心程序实现 / 校对。
> 署名:谷歌学术人机认证-141(注:派单文案要求"署名144",但本任务实际由会话 141 执行,如需更正请告知)　日期:2026-07-01　联网核验时间:2026-07(现状)

---

## 0. 2026 年关键变更提示(务必先读)

| 源 | 变更 | 影响 fulltext_fetcher 的动作 |
|---|---|---|
| **OpenAlex** | 2026-02 起 **polite pool 弃用**,`mailto` 参数被忽略,改为 **API key + freemium 计费**。但「按 DOI 取单条实体(singleton)」**永久免费** | 只用 `GET /works/doi:{doi}` 单条查询即可,**免费**;不要用 List+Filter / Search(收费)来做单篇定位 |
| **PMC** | OA Web Service(`oa.fcgi`)与 FTP **2026-08 停用**,迁移到 **AWS S3 开放数据集**(`pmc-oa-opendata`)。2026-02~08 为过渡期,新旧并存 | 现在(2026-07)旧 `oa.fcgi` 仍可用,但**实现时应直接走 Europe PMC 或 AWS S3**,避免 8 月后失效;ID 转换接口已迁到 `pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/` |
| **DOAJ** | API 升级到 **v4**(`/api/v4/`),`bibjson.identifier.type` 归一化为小写 | 端点用 `/api/v4/search/articles/` |
| **Semantic Scholar** | 无 key 时与所有匿名用户**共享**一个限流池(高峰被节流);个人 key 仅 1 req/s | 生产环境**必须申请 key**,并做退避 |

---

## 1. 主速查表(一屏总览)

| # | 源 | 定位端点(输入) | PDF 直链字段路径 | 需 Key/Email | 限速(免费) | 主要坑 |
|---|---|---|---|---|---|---|
| 1 | **Unpaywall** | `GET api.unpaywall.org/v2/{doi}?email=` | `best_oa_location.url_for_pdf`(空则 `.url`);全量看 `oa_locations[].url_for_pdf` | 需 email(免费,无需注册) | 100,000/天,无硬性 QPS | `url_for_pdf` 常为 null(只有落地页);仅按 DOI 查 |
| 2 | **OpenAlex** | `GET api.openalex.org/works/doi:{doi}&api_key=` | `best_oa_location.pdf_url`、`primary_location.pdf_url`、`open_access.oa_url`、`locations[].pdf_url` | 单条查询免费;规模化需免费 key | 单条 singleton 免费/不限;List/Search 收费 | `oa_url` 可能是落地页;`pdf_url` 可能 null;**别用收费端点定位单篇** |
| 3 | **Semantic Scholar** | `GET api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf` | `openAccessPdf.url` | 强烈建议申请免费 key(`x-api-key` 头) | 无 key:共享池易被节流;有 key:1 req/s | `openAccessPdf` 常 null;URL 可能是落地页 |
| 4 | **Crossref** | `GET api.crossref.org/works/{doi}?mailto=` | `message.link[]` 中 `content-type=application/pdf` 的 `URL`(配合 `intended-application`) | 无需 key;`mailto` 进 polite 池 | polite 池约 50 req/s(看返回头) | 多数 link 指向**出版商付费/需 TDM 许可**,非 OA;有 URL ≠ 能下 |
| 5 | **arXiv** | `GET export.arxiv.org/api/query?search_query=ti:"{title}"` 或 `?id_list={id}` | Atom: `entry/link[@rel=related,@type=application/pdf]/@href` → `arxiv.org/pdf/{id}v{n}` | 无 | ≤ 1 req/3s 且单连接;~100k/天/IP | DOI `10.48550/arXiv.X` 可直接取 id=X;标题搜可能多匹配;注意版本号 |
| 6 | **Europe PMC** | `GET ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:{doi}&format=json&resultType=core` | 先取 `result.pmcid`/`isOpenAccess`,PDF= `europepmc.org/articles/{PMCID}?pdf=render`;XML= `.../rest/{PMCID}/fullTextXML` | 无 | 较宽松,建议礼貌限速 | 仅 OA 子集有渲染 PDF;render 偶发 404,需回退 `ptpmcrender.fcgi` |
| 7 | **PubMed Central (PMC)** | DOI→PMCID:`GET pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/?ids={doi}&format=json` | OA 子集:AWS `s3://pmc-oa-opendata/{PMCID}.{v}/{PMCID}.{v}.pdf`(HTTPS 同名);过渡期旧 `oa.fcgi` 仍可用 | 无(E-utilities 建议加免费 `api_key`) | E-utilities:无 key 3 req/s,有 key 10 req/s | **2026-08 旧 OA/FTP 停用**;直接爬 `/articles/PMCxxx/pdf/` 常 403;很多 PMC 文章不在 OA 子集 |
| 8 | **bioRxiv / medRxiv** | `GET api.biorxiv.org/details/{server}/{doi}/na/json`(server=biorxiv\|medrxiv) | 由 `collection[].version` 拼:`www.biorxiv.org/content/{doi}v{version}.full.pdf`;JATS 见 `jatsxml` | 无 | 礼貌限速 | PDF 必须带版本号;Cloudflare 可能拦截自动下载;`published` 字段可转正式版 DOI |
| 9 | **CORE** | `GET api.core.ac.uk/v3/search/works?q=doi:"{doi}"` 或 `/v3/works/{coreId}` | `results[].downloadUrl`(直链 PDF)、`fullText`(纯文本) | **必须**免费 key(`Authorization: Bearer`) | 免费约 150 req/15min(~10/min) | 限流严格,需指数退避;`downloadUrl` 可能是 CORE 缓存副本 |
| 10 | **DOAJ** | `GET doaj.org/api/v4/search/articles/doi:{doi}` | `results[].bibjson.link[]` 中 `type=fulltext` 的 `url`(`content_type∈{PDF,HTML,ePUB,XML}`) | 无 | 礼貌限速 | 多为落地页/HTML,非直链 PDF;仅收录 DOAJ 期刊 |
| 11 | **Zenodo** | `GET zenodo.org/api/records?q=doi:"{doi}"` | `hits.hits[].files[].links.self`(直接下载) | 无(可选 token 提配额) | 礼貌限速 | 多为数据集/软件/附件,非论文 PDF;一条记录可能多文件 |
| 12 | **OpenAIRE** | `GET api.openaire.eu/graph/researchProducts?...&mailto=`(或旧 `/search/publications?doi=`) | `instances[].urls[]`(配合 `instances[].accessRight`=OPEN) | 无(可注册提配额) | 有限流;分页上限 10000 | 聚合源,`urls` 可能是落地页;需挑 accessRight=OPEN |
| 13 | **HAL** | `GET api.archives-ouvertes.fr/search/?q=doiId_s:"{doi}"&fl=doiId_s,fileMain_s,files_s` | `response.docs[].fileMain_s`(主文件/PDF URL)、`files_s[]` | 无 | 礼貌限速 | 以法国科研为主;无文件时 `fileMain_s` 缺失;`linkExtId_s` 可标识 arxiv/pmc 来源 |
| (补) | **DataCite** | `GET api.datacite.org/dois/{doi}` | `data.attributes.contentUrl[]`(主要面向数据/软件) | 无 | 礼貌限速 | 主要是数据集/软件,**很少有论文 PDF**;论文全文优先用上面 1-13 |

> 输入约定:`{doi}` 需做 URL 编码(路径中的 `/` 一般可保留;查询参数中建议编码)。标题检索仅 arXiv / Crossref / S2 / CORE / Unpaywall search 等支持;DOI 命中率与精确度最高。

---

## 2. 推荐编排策略(给核心程序的实现建议)

1. **先做标识归一**:输入若是标题 → 先用 Crossref `?query.bibliographic=` 或 OpenAlex/S2 检索拿到 DOI;输入若是 DOI → 直接进入下一步。
2. **聚合层优先(免费、覆盖广、直给直链)**:并发查 **Unpaywall + OpenAlex(单条免费)**,二者直接给 `url_for_pdf`/`pdf_url`,命中率最高、最省事。
3. **补充层**:未命中再查 **Semantic Scholar `openAccessPdf` → Europe PMC → CORE**。
4. **预印本/学科仓储**:DOI 形如 `10.1101/...` 走 bioRxiv/medRxiv;`10.48550/arXiv...` 或物理/CS 类走 arXiv;法国来源走 HAL;数据/软件走 Zenodo/DataCite。
5. **兜底**:Crossref `link[]`(注意多为付费/TDM)、OpenAIRE 聚合 `instances[].urls`。
6. **统一校验**(关键,见 §3):拿到候选 URL 后,先 `HEAD`/小范围 `GET` 校验 `Content-Type: application/pdf` 且文件头是 `%PDF-`,避免把 HTML 落地页当 PDF 落地。

并发去重建议:同一 DOI 的多源结果按"直链优先级"打分(`url_for_pdf`/`pdf_url`/`downloadUrl`/render-pdf > 落地页),取最高分;命中即短路返回,失败回退下一源。

---

## 3. 通用坑(所有源都要处理)

- **落地页 ≠ PDF**:`oa_url`/`bibjson.link.url`/部分 `best_oa_location.url` 是 HTML 落地页。务必校验响应 `Content-Type` 与文件魔数 `%PDF-`(前 5 字节)。
- **重定向**:多数直链需 `follow redirects`(curl `-L`);出版商常 302 到 CDN。
- **反爬**:bioRxiv/medRxiv(Cloudflare)、PMC 网页 PDF 路径(403)对脚本不友好;优先用 API/镜像端点(Europe PMC render、AWS S3)。
- **限速与退避**:统一加 `User-Agent`(含联系邮箱)、指数退避处理 429、按源设并发上限(CORE 最严)。
- **缓存**:对 DOI→结果做本地缓存,避免重复打同一源。
- **版本**:arXiv / bioRxiv 需带版本号(`v1/v2`),否则可能 404 或拿到旧版。

---

## 4. 各源详解(端点 / 示例 / 字段路径 / Key / 限速 / 坑)

### 1) Unpaywall
- **端点**:`GET https://api.unpaywall.org/v2/{doi}?email=YOUR_EMAIL`
- **示例**:`https://api.unpaywall.org/v2/10.1038/nature12373?email=you@example.com`
- **PDF 字段**:`best_oa_location.url_for_pdf`(直链);为 null 时退 `best_oa_location.url`(可能落地页);全量遍历 `oa_locations[].url_for_pdf`。辅助:`is_oa`、`oa_status`(gold/green/hybrid/bronze/closed)、`.version`、`.host_type`。
- **Key/Email**:仅需 email(免费,无需注册,用于识别调用方)。
- **限速**:100,000 次/天,无硬性 QPS,建议每请求间隔 ~100ms;超限 HTTP 429。海量请改用数据库快照(Data Feed)。
- **坑**:仅支持按 DOI 查(无 DOI 用 `/v2/search?query=`,但精度低);`url_for_pdf` 经常缺失。

### 2) OpenAlex
- **端点(单条,免费)**:`GET https://api.openalex.org/works/doi:{doi}?api_key=YOUR_KEY`(也可 `works/https://doi.org/{doi}`)
- **批量(免费 singleton)**:`works?filter=doi:{doi1}|{doi2}|...&api_key=`(每批最多 100,按 DOI 取单条仍计免费)
- **PDF 字段**:`best_oa_location.pdf_url`、`primary_location.pdf_url`、`open_access.oa_url`(可能落地页)、遍历 `locations[].pdf_url`。`open_access.is_oa` 判断。
- **Key**:2026-02 起 `mailto` 失效,需免费 API key(`openalex.org/settings/api`)。**按 ID/DOI 取单条永久免费**;List+Filter $0.10/1k、Search $1/1k、内容下载 $10/1k。
- **限速**:免费额度 $1/天(有 key);单条查询不限。
- **坑**:别用 Search/List 端点定位单篇(收费);`pdf_url` 可能 null。

### 3) Semantic Scholar (Academic Graph API)
- **端点**:`GET https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf,externalIds,title,isOpenAccess`
- **批量**:`POST https://api.semanticscholar.org/graph/v1/paper/batch?fields=openAccessPdf` body `{"ids":["DOI:10.../","ARXIV:2106.15928"]}`(≤500/批)
- **PDF 字段**:`openAccessPdf.url`(可能直链或落地页);`isOpenAccess`。
- **Key**:多数端点可匿名;生产建议申请免费 key,放 `x-api-key` 请求头。
- **限速**:无 key 与所有匿名用户共享同一限流池(高峰被节流);个人 key 默认 1 req/s(可申请上调)。
- **坑**:`openAccessPdf` 常为 null;ID 前缀支持 `DOI:`、`ARXIV:`、`PMID:`、`CorpusId:` 等。

### 4) Crossref
- **端点**:`GET https://api.crossref.org/works/{doi}?mailto=you@example.com`;批量 `?select=DOI,link&filter=...`
- **PDF 字段**:`message.link[]`,挑 `content-type == "application/pdf"`(或 `unspecified`)的 `URL`;同时看 `intended-application`(`text-mining` / `similarity-checking` / `unspecified`)与 `content-version`(`vor`/`am`)。
- **过滤**:`filter=full-text.type:application/pdf,full-text.application:text-mining`。
- **Key**:无需;`mailto`(参数或 User-Agent)进 polite 池更稳。
- **限速**:polite 池约 50 req/s,以返回头 `X-Rate-Limit-*` 为准。
- **坑**:**link 多指向出版商付费内容或需接受 TDM 许可,不保证可下**;Crossref 只存元数据。适合做兜底与"有无全文线索"判断。

### 5) arXiv
- **端点**:`GET http://export.arxiv.org/api/query?search_query=ti:"{title}"&max_results=10` 或 `?id_list={arxivId}`(可加 `vN`)
- **DOI→id**:DOI 形如 `10.48550/arXiv.2106.15928` → id 直接是 `2106.15928`;其他 DOI 用 `search_query` 或 Unpaywall/OpenAlex 反查。
- **PDF 字段**:Atom feed 中 `entry/link[@rel="related" and @type="application/pdf"]/@href`,即 `https://arxiv.org/pdf/{id}v{n}`;摘要页 `entry/link[@rel="alternate"]/@href`;`entry/arxiv:doi` 为正式 DOI。
- **Key**:无。
- **限速**:每 3 秒 ≤ 1 请求、单连接;另有 ~100,000/天/IP 提及。批量用 OAI-PMH (`export.arxiv.org/oai2`)。
- **坑**:标题搜可能多命中需消歧;注意版本;官方建议链到 arxiv.org 而非直接热链。

### 6) Europe PMC
- **定位**:`GET https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:{doi}&format=json&resultType=core`
- **PDF 字段路径**:`resultList.result[0]`,看 `pmcid`、`isOpenAccess=="Y"`、`fullTextUrlList.fullTextUrl[]`(取 `documentStyle=="pdf"` 且 `availability=="Open access"` 的 `url`)。
- **取 PDF/XML 直链**:
  - 渲染 PDF:`https://europepmc.org/articles/{PMCID}?pdf=render`
  - 回退后端:`https://europepmc.org/backend/ptpmcrender.fcgi?accid={PMCID}&blobtype=pdf`
  - 全文 XML(JATS):`https://www.ebi.ac.uk/europepmc/webservices/rest/{PMCID}/fullTextXML`
- **Key**:无,OA 内容多为 CC 许可。
- **限速**:较宽松,建议礼貌限速(几 req/s)。
- **坑**:仅 OA 子集(8M+)有渲染 PDF;render 偶发 404/403,按上面顺序回退。

### 7) PubMed Central (PMC)
- **DOI→PMCID**:`GET https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/?ids={doi}&format=json`(单次 ≤200 ID;旧 `idtype=doi` 兼容)
- **取 OA PDF(2026 现状)**:
  - 过渡期(至 2026-08)旧 OA Web Service 仍可:`https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={PMCID}`(返回 tgz/pdf 链接,仅 OA 子集)
  - **推荐迁移目标**:AWS 开放数据集 `s3://pmc-oa-opendata/{PMCID}.{ver}/{PMCID}.{ver}.pdf`(HTTPS:`https://pmc-oa-opendata.s3.amazonaws.com/...`),目录分 `oa_comm`/`oa_noncomm`/`phe_timebound`。
  - 元数据 JSON 里字段示例:`pdf_url`(s3 形式)、`xml_url`、`license_code`、`is_pmc_openaccess`。
- **Key**:无;E-utilities 建议加免费 `api_key`(NCBI account)。
- **限速**:E-utilities 无 key 3 req/s、有 key 10 req/s。
- **坑**:**2026-08 起 `oa.fcgi`+FTP 停用,务必走 AWS 或 Europe PMC**;直接 `GET /pmc/articles/PMCxxx/pdf/` 对脚本常 403;大量 PMC 文章只是"免费阅读"不在可再分发 OA 子集。

### 8) bioRxiv / medRxiv
- **端点**:`GET https://api.biorxiv.org/details/{server}/{doi}/na/json`(`{server}`=`biorxiv` 或 `medrxiv`)
- **示例**:`https://api.biorxiv.org/details/biorxiv/10.1101/2020.01.30.927871/na/json`
- **PDF 字段**:响应 `collection[]` 取最新 `version`,拼直链:`https://www.biorxiv.org/content/{doi}v{version}.full.pdf`;`jatsxml` 字段给 JATS XML 全文;`published` 给见刊后的正式 DOI(可回流到出版商/PMC)。
- **Key**:无。
- **限速**:礼貌限速。
- **坑**:PDF 必须带 `v{version}`;`www.biorxiv.org` 有 Cloudflare,自动下载可能需会话/UA 处理;摘要页加 `?versioned=TRUE` 锁版本。

### 9) CORE
- **端点**:`GET https://api.core.ac.uk/v3/search/works?q=doi:"{doi}"&limit=10`;或按 ID `GET https://api.core.ac.uk/v3/works/{coreId}`;按 DOI 取单条 `…/v3/works/doi:{doi}`
- **PDF 字段**:`results[].downloadUrl`(直链 PDF)、`results[].fullText`(纯文本)、`results[].links[]`。
- **Key**:**必须**免费 key,放 `Authorization: Bearer {CORE_API_KEY}`(注册 `core.ac.uk/services/api`)。
- **限速**:免费约 150 请求/15 分钟(≈10/min);各方法另有细分配额(如 `/search/works` 批量 1 次/10s)。
- **坑**:限流最严,务必指数退避 + 缓存;`downloadUrl` 可能是 CORE 缓存副本而非原站。

### 10) DOAJ
- **端点**:`GET https://doaj.org/api/v4/search/articles/doi:{doi}`(`/` 会被转义)
- **PDF 字段**:`results[].bibjson.link[]`,取 `type=="fulltext"` 的 `url`;`content_type ∈ {PDF, HTML, ePUB, XML}`,优先 `PDF`。
- **Key**:无(读取检索免费)。
- **限速**:礼貌限速。
- **坑**:很多是落地页/HTML;仅覆盖 DOAJ 收录的纯 OA 期刊。

### 11) Zenodo
- **端点**:`GET https://zenodo.org/api/records?q=doi:"{doi}"`;或按记录 `GET https://zenodo.org/api/records/{recid}`
- **PDF/文件字段**:`hits.hits[].files[].links.self`(直接下载链接);`files[].key`(文件名)、`files[].type`。
- **Key**:无;可选 personal access token 提升配额。
- **限速**:礼貌限速。
- **坑**:Zenodo 多为数据集/软件/附件,论文 PDF 需看 `files[].type=="pdf"`;一条记录可能含多文件需筛选。

### 12) OpenAIRE
- **端点(Graph API,现行 v11.x)**:`GET https://api.openaire.eu/graph/researchProducts?search={title}&mailto=` 或单条 `GET https://api.openaire.eu/graph/researchProducts/{openaireId}`;旧版仍可 `GET https://api.openaire.eu/search/publications?doi={doi}&format=json`
- **PDF 字段**:`results[].instances[]`,每个 instance 含 `urls[]`(全文/下载 URL)与 `accessRight`(取 `OPEN`)。
- **Key**:无;注册可提配额;`mailto` 进礼貌池。
- **限速**:有限流;传统分页上限 10000,海量用 cursor 或下载全量 dump。
- **坑**:聚合源,`urls` 可能落地页;需按 `accessRight==OPEN` 过滤;v4 beta 在 `api-beta.openaire.eu/graph/v4/research-products`。

### 13) HAL
- **端点**:`GET https://api.archives-ouvertes.fr/search/?q=doiId_s:"{doi}"&fl=doiId_s,fileMain_s,files_s,uri_s,linkExtId_s&wt=json`
- **PDF 字段**:`response.docs[].fileMain_s`(主文件/PDF 直链)、`files_s[]`(全部文件 URL)。判 OA:`fq=(submitType_s:file OR linkExtId_s:(openaccess OR arxiv OR pubmedcentral))`。
- **Key**:无(Solr 语法检索)。
- **限速**:礼貌限速;`rows` 最大约 10000。
- **坑**:以法国科研机构为主,覆盖有偏;无全文时 `fileMain_s` 缺失。

### (补) DataCite
- **端点**:`GET https://api.datacite.org/dois/{doi}`
- **字段**:`data.attributes.contentUrl[]`(内容直链,主要数据/软件);`data.attributes.url`(落地页)。
- **Key**:无(读取免费)。
- **限速**:礼貌限速。
- **坑**:DataCite 主要登记数据集/软件/预印本,**很少有期刊论文 PDF**;论文全文优先走 1–13。

---

## 5. 字段路径速记(供代码直接取值)

```text
Unpaywall      → best_oa_location.url_for_pdf  (fallback best_oa_location.url; all: oa_locations[].url_for_pdf)
OpenAlex       → best_oa_location.pdf_url | primary_location.pdf_url | open_access.oa_url | locations[].pdf_url
SemanticScholar→ openAccessPdf.url
Crossref       → message.link[ content-type=application/pdf ].URL
arXiv          → entry.link[ rel=related, type=application/pdf ].href  (= arxiv.org/pdf/{id}v{n})
EuropePMC      → result.fullTextUrlList.fullTextUrl[ documentStyle=pdf ].url  | europepmc.org/articles/{PMCID}?pdf=render
PMC            → idconv→PMCID → s3://pmc-oa-opendata/{PMCID}.{v}/{PMCID}.{v}.pdf  (过渡期: oa.fcgi)
bioRxiv/medRxiv→ www.biorxiv.org/content/{doi}v{collection[].version}.full.pdf
CORE           → results[].downloadUrl  (fullText: results[].fullText)
DOAJ           → results[].bibjson.link[ type=fulltext, content_type=PDF ].url
Zenodo         → hits.hits[].files[].links.self
OpenAIRE       → results[].instances[ accessRight=OPEN ].urls[]
HAL            → response.docs[].fileMain_s  (all: files_s[])
DataCite       → data.attributes.contentUrl[]
```

---

> 核验来源(2026-07):各源官方文档/开发者页(unpaywall.org、developers.openalex.org、api.semanticscholar.org/api-docs、crossref.org/documentation、info.arxiv.org/help/api、europepmc.org、pmc.ncbi.nlm.nih.gov + NCBI Insights 2026-02 公告、api.biorxiv.org、core.ac.uk/documentation、doaj.org/api/docs、developers.zenodo.org、graph.openaire.eu/docs、api.archives-ouvertes.fr/docs、api.datacite.org)。
