# 检索成果·角度8:出版商全文/TDM API + Scholar 被引口径 + 路线图未认领项 ROI

> 智库深挖(A3 出版商适配器 / B1 Scholar 被引·版本 / 未认领项 ROI 排序 / 跨成员源码级佐证)。
> 版本 1.0 · 2026-07-01 · 谷歌学术人机认证-157(信息检索-智库专家)
> 配套阅读:`功能优化与新增功能建议.md`、`检索成果-角度2-官方开放API替代路线.md`、`检索成果-角度4-商业抓取与第三方ScholarAPI服务.md`、`fulltext_fetcher资料-各源接口速查.md`、`机构订阅集成设计.md`
> 所有端点/定价/政策均 **2026-07 联网核验**;来源见 §五。

---

## 〇、TL;DR + 与现有代码的关系(先说清"哪些已建、别重复")

先通读了当前仓库,**避免重复造轮子**是本篇第一原则:

| 路线图项 | 仓库现状(实测代码) | 真正的剩余缺口 |
|---|---|---|
| **B1 Scholar 被引/版本口径** | **≈ 已完成并接线**:`scholar_serpapi.py`(SerpApi:cited_by/versions/PDF resources,gated 默认关)+ `citations.py`(免费:OpenAlex `cited_by_count`/locations 版本/related + S2 `citationCount` 回退)+ `scholar/serp.py`(`parse_serpapi` 已捕获 `cluster_id` 供"全部版本")+ `scholar/fetcher.py`(`SerpApiEngine`;mode auto/serpapi/self) | 仅**微增量**:`citations_per_year`(SerpApi 2026-03 新增)、`cites_id`(citing-docs 跟进查) |
| **A3 出版商适配器** | **部分**:`publisher_adapter.py`(Accept 头 + ACS/Springer/Wiley/IOP 模板 + Crossref `link[]` 解析)、`publisher_direct.py`(机构直链,gated `cfg.institutional`) | **都走出版商网站 `/doi/pdf/` 公网路径**(常被 Cloudflare/Akamai/403 拦)。**真正缺口 = 专用 TDM/全文 API 端点 + token/key**(Wiley TDM token、Elsevier Article Retrieval API、IEEE OA/Full-Text API、Springer Nature API)——更稳、且是**合规拿订阅全文的正门** |

**ROI 排序(供总指挥挑;详见 §三)**:
`A3 keyed-TDM 层` ≈ `E1 快照线` > `B1 微增量`(近乎白捡) > `E2 本地全文检索` > `D3 自适应限速` > `B3 代理池`。

---

## 一、A3 深挖:出版商专用全文 / TDM API(合规拿订阅全文的正门)

### 1.1 关键更正:Crossref TDM click-through 已退役(务必订正代码注释)
Crossref 的 **TDM click-through 服务已于 2020-12-31 退役**(历年仅 2–3 家出版商接入、约 80 个用户点选),**不再发放任何 TDM token**。`publisher_adapter.py` 文档串里"我们支持/经 CrossRef 发放 key"的说法**已过时,建议订正**。Crossref 现仅保留三件事,仓库应据此对齐:
1. metadata 里 `link[]` + `intended-application`(**仓库 `pdf_links_from_crossref` 已正确使用**,TDM 链降权保留);
2. `filter=has-full-text:true,license.version:tdm` 可**批量定位**有 TDM 授权的 DOI;
3. `CR-TDM-Rate-Limit / -Remaining / -Reset` 响应头由全文托管方传递限速(异步层应读取,见 §四 -168)。

### 1.2 各社正门(端点 / 认证 / 限速 / 返回 / 合规;2026-07 核验)

| 出版商 | DOI 前缀 | 全文 / TDM 取法(端点) | 认证 | 限速 | 返回 | 合规边界 |
|---|---|---|---|---|---|---|
| **Wiley** ★最干净 | 10.1002 / 10.1111 | `GET https://api.wiley.com/onlinelibrary/tdm/v1/articles/{doi}`,头 `Wiley-TDM-Client-Token: <UUID>`,**须跟随重定向**(curl `-L`) | WOL 账号点选 click-through 领 UUID token;按**公网 IP** 判定机构订阅 | **3 篇/秒、60 次/10 分**(约每 10s 一次可持续) | **直接全文 PDF** | 订阅 + 非商业;官方 `pip install wiley-tdm`(v1.1.0, 2026-05) |
| **Elsevier** | 10.1016 | `GET https://api.elsevier.com/content/article/doi/{doi}?httpAccept=application/pdf`(或 `view=FULL` 取 XML);头 `X-ELS-APIKey` + `Accept`;无权时 `amsRedirect=true` 取作者接受稿(AM) | dev.elsevier.com 自助注册 **APIKey**;订阅机构 IP/token | 机构级 | 全文 PDF / XML;无权→AM | 订阅 + 非商业;TDM 输出分享受限(≤200 字符片段 + DOI) |
| **Springer Nature** | 10.1007 / 10.1140 / 10.1186 | Springer Nature Dev Portal:**OA API**(开放全文,免费)/ **TDM/Meta API**(订阅全文需授权分级);另 `link.springer.com/content/pdf/{doi}.pdf` 对 OA/已授权可直取(**仓库已构造**) | dev.springernature.com **key**(OA 免费;订阅全文需授权) | 分级 | 全文(OA/授权) | OA 免费;订阅需授权 |
| **IEEE** | 10.1109 | 需先由 DOI/检索拿 `arnumber` → `http://ieeexploreapi.ieee.org/api/v1/search/document/{arnumber}/fulltext?apikey=<key>`;`accessType` 区分 `Open Access`/`Locked` | developer.ieee.org **审核发 key**;全文/TDM 需机构订阅 | 机构级 | **OA 全文可取**;订阅全文需订阅 | OA 可取;订阅 + 非商业需订阅 |
| **ACS** | 10.1021 | `/doi/pdf/{doi}` + `Accept: application/pdf`(**仓库已用**);ACS 另有 TDM 计划(需订阅申请) | 机构订阅 / IP;TDM 需申请 | — | PDF | 订阅 + 非商业 |
| **RSC** | 10.1039 | 无公开 TDM API;机构订阅经 `articlepdf` 模板(**`publisher_direct` 已构造**) | 机构订阅 | — | PDF | 订阅 |

> 结论:**Wiley 是最干净的 DOI→PDF TDM 正门**(单请求直吐 PDF、有官方 pip 包);Elsevier 次之(REST + key + `amsRedirect` 兜作者稿);IEEE 需 `arnumber` 二段式;Springer/ACS/RSC 现有公网模板 + Accept 头基本够,补 key 边际收益较小。

### 1.3 集成建议(gated、缺 key 降级、不改 config.py)
- 新增 **keyed-TDM 适配器层**(可并入 `sources/publisher_direct.py` 或新 sibling),按 DOI 前缀路由到**专用 API 端点**,置于现有"公网 `/doi/pdf/` 模板"之前(命中率更高);
- 密钥经 `getattr(cfg, "wiley_tdm_token" / "elsevier_tdm_key" / "ieee_key" / "springer_key", None)` 读取(**建议由 config 负责人加字段**;我用 `getattr` 兜底,不加即恒为关,零副作用);
- 命中链:**专用 API(有 token)→ 现有公网模板 → 落地页解析**;`download.py` 的 `%PDF` 魔数校验兜底——无权返回 401/403/HTML 自动过滤,**绝不产假成功**(与 `publisher_direct` 同哲学);
- **强耦合 A5**:这些 token/key 本质是"机构授权"的 API 形态,应与 EZproxy/Shibboleth/OpenAthens/CARSI **同属机构接入配置层**(与 -153 对齐,见 §四)。

---

## 二、B1 深挖:Scholar 被引 / 版本口径(已建,给验证 + 微增量 + 选型)

### 2.1 已建能力(**别重复**)
- `scholar_serpapi.py`:SerpApi Google Scholar 客户端,解析 `inline_links.cited_by.total`(被引)、`inline_links.versions.total`(版本)、`resources[] file_format=PDF`(直链);**默认关**(无 `SERPAPI_KEY` 不联网),自检 `SCHOLAR_SERPAPI_OK`。
- `citations.py`:**免费合规**被引/版本——OpenAlex `cited_by_count` + `locations[]`(版本)+ `related_works`;回退 Semantic Scholar `citationCount`;自检 `CITATIONS_OK`。
- `scholar/serp.py::parse_serpapi`:已把 SerpApi 结果归一到 `scholar.models.ScholarResult`,**已捕获 `cluster_id`**(取"全部版本"用)。
- `scholar/fetcher.py::SerpApiEngine` + `scholar/config.py`:mode `auto`(有 key 走 serpapi、否则 self)/`serpapi`/`self`;E2E 回归已锁。

### 2.2 三方案对比(真·GS vs 免费近似)

| 方案 | 取被引/版本 | Key | 成本 | 是否"真·Google Scholar 口径" | 合规 |
|---|---|---|---|---|---|
| **SerpApi Google Scholar** | `cited_by.total` + `versions.total/cluster_id`;`cites=`(citing)/`cluster=`(all versions)参数;`citations_per_year`(2026-03 新增) | 需 SerpApi key | 免费 250/月;**$25/1k、$75/5k、$275/3万**;仅成功计费 | **✅ 就是 GS 的被引/版本数** | ✅ SerpApi 代抓 + US Legal Shield |
| **OpenAlex** | `cited_by_count` + `locations`(版本)+ `related_works` | **2026 起需免费 key**($1/天额度;**按 DOI singleton 查近乎免费**,官方例:100 万 DOI 查=Free) | 近免费 | ❌ OpenAlex 自有引文图(数值≠GS、通常偏低) | ✅ |
| **Semantic Scholar** | `citationCount`;`/paper/{id}/citations`、`/references` | 免 key 可用(1000 rps 共享、限流);key→1 rps 保底 | 免费 | ❌ S2 自有引文图 | ✅ |

### 2.3 结论 & 微增量(可选,低优先)
- **默认继续用 `citations.py` 免费口径**;仅当用户明确"要 Google Scholar 的被引数/版本数"时才开 SerpApi(`citations.py` 与 SerpApi 数值不同源,勿混用于同一指标)。
- 可选微增量:`scholar_serpapi.py` 的 `ScholarResult` 补 `citations_per_year` 与 `cites_id`(`cluster_id` 已在 `scholar/serp.py` 捕获)。**收益小、非阻塞**。

---

## 三、路线图"未认领项" ROI 排序(A3 / B1 / B3 / D3 / E1 / E2)

> 依据 `list_sessions`(2026-07-01):A5(-153)、repositories 审计(-156)、搜索引擎找 PDF(-158)、C4 异步(-168)、C3 Zotero(-164)、D2 库(备忘录秘书)、新免费 API(监管者)、文档一致性(-177)、batch7 回收(-141)已各有专人;下表为**当前无人认领**项。

| 项 | 价值 | 工作量 | 合规 | 依赖/现状 | ROI 建议 |
|---|---|---|---|---|---|
| **A3 keyed-TDM 层** | **高**(订阅语料合法回收全文,突破 10.8% 天花板的技术侧抓手) | 中(每社 key/token 插线,gated) | ✅ 订阅+非商业正门 | 与 A5(-153)强耦合;`publisher_direct` 为接线点 | **首选**——尤其 Wiley(最干净)。建议与 -153 合并为"机构接入"一揽子 |
| **E1 快照线** | **高**(超大批量/离线:零限速零成本;OpenAlex CC0 快照、Unpaywall Data Feed) | **极小**(已交付,详见附B) | ✅ 官方快照合法 | **已基本交付**:`snapshot_bootstrap.py`(guide + ingest + `--incremental`/`--since`)+ `snapshot.py`(`INSERT OR REPLACE` upsert)+ `ingest.py` | **改判:已建**——仅余可选 guide 增强(Parquet/DuckDB 直查/changefiles 端点),不必新排建设 |
| **B1 微增量** | 中(仅补 `citations_per_year`/`cites_id`) | **极小** | ✅ | 主体已建(§二) | **白捡**——顺手可做,非阻塞 |
| **E2 本地全文检索** | 中(下完即全文搜,SQLite FTS5) | 中-大 | ✅ | 无 | 中——闭环增值,非急 |
| **D3 自适应限速/熔断** | 中-低(边际提速 + 更礼貌) | 中 | ✅ | `http_client` 现固定间隔 | 中-低 |
| **B3 代理池** | 低-中(**仅**服务 Scholar 自建抓取 B2 / 高频 API) | 中 | ⚠️ 抓 Scholar 灰色 | 仅在推进 B2 时才需要 | **最低**——不建议主线推进 |

---

## 四、跨成员支援(源码级佐证 / 依赖对齐)

- **备忘录秘书(D2:PDF 完整性校验库)**:D2 **已在 `download.py` 实现**(`pdf_defect(deep=)` + `_pdf_page_defect`,缺库降级、默认关、`getattr(cfg,'pdf_verify_deep',False)` 门控,四态确定性 selftest)。经与备忘录秘书**双向复核后已定稿并落地**:①**删除 PyPDF2 回退、只认 pypdf**(PyPDF2 3.0.1 与 pypdf 3.1.0 同源同代码,回退零额外鲁棒性且引入不再维护旧包);②`_pdf_page_defect` 除 `len(pages)>0` 外**强制访问 `pages[0]` 触发惰性解析**(pypdf 惰性,仅 len 会漏掉损坏);③若日后要 deep=True 时**强抓截断/损坏**,二级引擎选 **pypdfium2**(PDFium 内核、对畸形不宽容、许可证干净)而非 pikepdf(QPDF 打开即自动修复→漏报截断)。改动保持默认关、缺库降级,`DOWNLOAD_OK` 全绿。
- **-153(A5:机构订阅访问自动化 EZproxy/Shibboleth/OpenAthens/CARSI)**:§一的 **Wiley TDM token / Elsevier APIKey / IEEE key / Springer key 是"机构授权"的 API 形态**,与代理登录态互补(一个走 API token、一个走会话 cookie),应**同层设计**;`publisher_direct.py`(`cfg.institutional` 门控)是天然接线点。建议 A3 keyed-TDM 与 A5 合并为一揽子"机构接入"能力。
- **-168(C4:大批量异步并发)**:注意各社/各源**限速差异**——Wiley 3/s + 60/10min、NCBI 3/s、arXiv 3s、OpenAlex $1/天预算、SerpApi 按 throughput/hour;异步层须内建 **per-host 令牌桶**并读取 `CR-TDM-Rate-Limit*` 头,否则触发风控/超预算。

---

## 五、来源(2026-07 联网核验)

- Elsevier TDM/Article Retrieval:elsevier.com/about/policies-and-standards/text-and-data-mining、dev.elsevier.com
- Wiley TDM API:onlinelibrary.wiley.com/library-info/resources/text-and-datamining、github.com/WileyLabs/tdm-client、pypi.org/project/wiley-tdm(v1.1.0, 2026-05)
- Crossref TDM 退役:crossref.org/blog/evolving-our-support-for-text-and-data-mining、crossref.org/deprecated、crossref.org/documentation/retrieve-metadata/text-and-data-mining(2025-10 更新)
- IEEE Xplore API:developer.ieee.org/docs、/Allowed_API_Uses、/docs/read/Metadata_API_responses
- Springer Nature:dev.springernature.com
- SerpApi Google Scholar:serpapi.com/google-scholar-api、/pricing、/google-scholar-api/release-notes(至 2026-05)
- OpenAlex:developers.openalex.org/api-reference/authentication(2026 起需免费 key)、/works/list-works
- Semantic Scholar:semanticscholar.org/product/api

> 备注:本篇仅为**检索/选型结论与集成建议**,不改任何生产代码;落地由总指挥按 ROI 排期、指派对应成员(A3 与 A5 建议合并交由机构接入线)。

---

## 附A:keyed-TDM 适配器"即插即用"设计草案(应 -153 之约,待 -145 排波次)

> 目标:波次一到即可秒落地。**本草案不改任何生产代码**,只锁接口/契约/分工,规避 `sources/` 归属与 batch7 撞车。

### A.1 关键架构决策:**逐候选鉴权头(auth headers)的贯通**
keyed-TDM 与现有"公网 `/doi/pdf/` 模板"最大不同:**每条候选 URL 需带专属鉴权头**(Wiley `Wiley-TDM-Client-Token`、Elsevier `X-ELS-APIKey`+`X-ELS-Insttoken`),而当前 `PdfCandidate` 无 headers 字段、`pipeline` 也不向 `download_pdf` 传逐候选头。契约补齐(**最小、向后兼容**):
1. `models.py::PdfCandidate` 增可选 `headers: Optional[dict] = None`(默认 None,不影响任何现有源);
2. `pipeline.py` 下载时把 `c.headers` 透传:`download_pdf(c, ..., headers=getattr(c, "headers", None))`;
3. `download.py::download_pdf` 增可选 `headers` 形参并转交 `_download_pdf_core`(**后者已支持 `headers` 参数**,几乎零改);缺省 None → 逐字节不改现有行为。

> 说明:`_download_pdf_core` 现已有 `headers` 通路(供出版商 Accept / FlareSolverr Cookie 复用),故本链路增量极小。

### A.2 适配器接口(纯构造 + gated,置于 `publisher_direct` 机构分支)
```
build_tdm_candidates(doi, cfg) -> list[PdfCandidate]
  仅当 cfg.institutional=True 且对应出版商 key/token 非空时才产候选;否则 []。
  每条 PdfCandidate: url=专用API端点, source="publisher_tdm:<社>", kind="pdf",
                    confidence≈74(高于公网模板), headers={鉴权头}
```
| 社 | 端点(含 {doi}) | headers(取自 cfg,getattr 兜底) | 置信度 |
|---|---|---|---|
| Wiley | `https://api.wiley.com/onlinelibrary/tdm/v1/articles/{doi}` | `Wiley-TDM-Client-Token: {cfg.wiley_tdm_token}` | 74 |
| Elsevier | `https://api.elsevier.com/content/article/doi/{doi}?httpAccept=application/pdf` | `X-ELS-APIKey: {cfg.elsevier_api_key}`(+可选 `X-ELS-Insttoken: {cfg.elsevier_insttoken}`) | 74 |
| IEEE | 先 DOI→arnumber,再 `.../document/{arnumber}/fulltext?apikey={cfg.ieee_key}` | —(key 在 query) | 70 |
| Springer | Dev Portal 全文/OA 端点(key 在 query) | — | 70 |

### A.3 gating / 降级 / 错误映射(与仓库既有哲学一致)
- **gating**:`cfg.institutional` 总开关 + 逐社 `getattr(cfg,"wiley_tdm_token",None)` 等**非空**才产候选;全缺 → 该社不产候选(零副作用)。
- **降级**:无 key/token、无权(401/403)、返回 HTML → 由 `download.py` 的 **`%PDF` 魔数 + 大小 + `%%EOF`** 校验自动过滤,**绝不产假成功**(沿用 `publisher_direct` 现状)。
- **顺序**:keyed-TDM(conf 74)→ 公网 `/doi/pdf/` 模板(conf 66)→ 落地页解析。**Wiley 须跟随重定向**(client 默认 allow_redirects=True 已满足);Wiley 限速 3/s + 60次/10min 交 `http_client` per-host 限速(与 -168 C4 对齐)。

### A.4 分工(经 -153 对齐,最终以 -145 排期为准)
| 文件 | 归属 | 改动 |
|---|---|---|
| `config.py` | **-153** | 加 `wiley_tdm_token / elsevier_insttoken(+已有 elsevier_api_key) / springer_tdm_key / ieee_key`(默认空、零副作用) |
| `sources/publisher_direct.py` | **-157(实现)** + -153(接线 review) | 机构分支加 `build_tdm_candidates`,keyed-TDM 优先于公网模板 |
| `models.py` / `pipeline.py` | 待 -145 指派(**需先定** A.1 的 headers 契约) | `PdfCandidate.headers` 字段 + pipeline 透传 |
| `download.py` | **-157** | `download_pdf` 增 `headers` 形参转交 `_download_pdf_core`(已支持) |

### A.5 selftest 计划(离线、假 client、不联网)
断言:①`institutional=False` 或缺 key → `build_tdm_candidates`=[];②有 token → 候选带正确 `headers` 且 conf 高于公网模板;③假 client 校验鉴权头确被 `_download_pdf_core` 注入(复用 download.py 现有 `_MapClient`/`captured_hdr` 套路);④无权返回 HTML → `%PDF` 校验拦截、不落盘。打印 `PUBLISHER_TDM_OK`。

---

## 附B:E1 快照线现状复核(**已基本交付**,勿重复建设)+ 2026 增量

> 本节为"全网检索 + 通读本仓源码"的复核结论:E1 **不是待建项**,已由三件套交付,建议 ROI 表据此改判。

### B.1 仓库现状(读源码确认)
| 组件 | 能力 |
|---|---|
| `snapshot_bootstrap.py` | `guide`(打印合法免费获取指引 + `--check-env` 检 aws CLI)、`ingest`(复用入库)、**`--incremental`(跳过库中已有 DOI)+ `--since`(按更新日期过滤)**、离线 selftest `SNAPSHOT_BOOTSTRAP_OK` |
| `snapshot.py` | `build_from_unpaywall/openalex` 流式灌 SQLite;**`INSERT OR REPLACE`(doi PRIMARY KEY)→ 天然 upsert**,应用 changefiles 即增量;`lookup(db,doi)` 零联网查 |
| `ingest.py` | CLI 灌库入口 |

**结论**:路线图 E1「下载引导脚本 + 增量更新」**已完成**。增量甚至"免费"——upsert + `--incremental` 已覆盖;应用 Unpaywall changefiles / OpenAlex 变更即持续同步。

### B.2 与 2026 最新事实对照(现有 guide 基本准确,可补三处)
- ✅ 已准确:OpenAlex `aws s3 sync s3://openalex/data/jsonl --no-sign-request`、`manifest.json` 增量、季度免费/每日付费、~330GB 压缩/~1.6TB 解压、Unpaywall 官方已停半年度快照转荐 OpenAlex。
- **可补①(2026-06 新)**:OpenAlex **Parquet 格式**正随 2026-06 季度版进入免费公开快照(`/data/parquet/`,snappy);guide 目前只提 JSONL,可加一句"列式 Parquet 亦可,分析更快"。
- **可补②**:**DuckDB `httpfs` 直查 S3**(免下 1.6TB,按需拉取)——轻量替代,适合不愿本地存全量者;OSS 参考 `pyalexs3`(S3→DuckDB,无下载)、`chrisgebert/open_alex_snapshot`(dbt-duckdb)。
- **可补③**:Unpaywall Data Feed 增量端点 `GET api.unpaywall.org/feed/changefiles?api_key=&interval=day|week`(付费),下载变更文件后走现有 `--incremental` 即可持续同步。

### B.3 OSS landscape(佐证本仓方案更轻、无需切换)
`pyalexs3`(S3→DuckDB httpfs,免下载)、`chrisgebert/open_alex_snapshot`(dbt-duckdb)、`libris/unpaywallmirror`(DOI 本地镜像)、`naustica/unpaywall_bq`(BigQuery 导入)、`unpywall`(API 客户端)。
本仓"**stdlib + aws CLI + SQLite upsert**"零/极少依赖、最贴合诉求;上述多依赖 DuckDB/BigQuery/dbt,仅在"想免下载直查 S3"时值得引 DuckDB 作**可选**加速路径。

### B.4 建议(可选、低优先、交实现者)
仅需在 `snapshot_bootstrap.GUIDE_TEXT` 增补 B.2 的三句(Parquet + DuckDB 直查 + changefiles 端点)——**纯文本增强、零风险、非阻塞**;E1 主体无需再动。
