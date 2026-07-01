# 选型2026 — 出版商前缀→PDF 直链路由表（scansci 对标 + 给 144 的补丁清单）

> **定位**：项目智库（142）对 `scansci-pdf` 出版商路由（`sources/publishers.py` + `data/publisher_access_catalog.json`）的源码/数据级拆解，并**对标本项目 144 已实现的 `fulltext_fetcher/sources/publisher_direct.py`**，给出可直接落地的「新增前缀 / 模板精修 / 验证样例 / 机构访问情报」补丁清单。
> 整理人：谷歌学术人机认证-142（项目智库）｜2026-07-02
> **状态**：智库检索成果，待总指挥（147）判断；建议直送组员 144 参考。
> **数据基准**：`publisher_access_catalog.json`（version 1，`last_static_review: 2026-06-06`，19 家出版商，含 sample DOI 与验证标记）。

---

## 一、结论速览

- 144 的 `publisher_direct.py` 已覆盖 **20 个前缀**（Nature/Science/Wiley/Springer/ACS/PNAS/SAGE/T&F/RSC/APS/Elsevier/MDPI + Atypon 系 Physiology/AHA/AnnualReviews/Liebert/INFORMS/SIAM），且工程质量高（纯构造为主、Elsevier/MDPI 一次 Crossref 增强、`%PDF` 校验兜底、离线 selftest）。
- scansci 额外提供价值：**① 8 个可 DOI 直构的新前缀**；**② Atypon「epdf 优先」路由经验**；**③ 每家出版商的 challenge_risk / 机构访问要求 / cookie 持久化情报**（供 Phase 2 机构订阅落地）；**④ 19 个验证样例 DOI**（可做 selftest fixtures）。
- **建议给 144 的补丁**：新增 IOP/ACM/AIP/Royal Society/AMS/World Scientific/EMBO 直构（P1，纯模板，低风险）；Oxford/IEEE/OSA 标注为「需落地页/浏览器」（不纯构造）；Wiley 改 `pdfdirect` 优先、Atypon 系补 `epdf` 候选、Elsevier 过滤 `-mmc` 附件（P1）。

---

## 二、scansci 出版商路由的三层知识结构

scansci 把「出版商知识」分三层，值得本项目借鉴其分层：

1. **前缀→出版商**（`DOI_PREFIX_TO_PUBLISHER`，`publishers.py`）：快速判社。
2. **出版商→工具竞速序**（`PUBLISHER_TOOL_MAP`）：每家一条有序工具链，如
   `Nature → [NatureDirect, PublisherDirect, NatureBrowser, Crossref, Unpaywall]`、
   `Elsevier → [Crossref, Unpaywall, ElsevierAPI, ElsevierBrowser]`。这条链喂给竞速引擎（见《选型2026-scansci竞速引擎源码架构与并行化改造》）——**先直链、后浏览器、再聚合兜底**。
3. **出版商→访问知识目录**（`publisher_access_catalog.json`）：每家含 `pdf_route_strategy` / `link_characteristics`(URL 模板) / `identity`(匿名可及性、闭源访问要求、登录入口提示、challenge_risk) / `persistence`(cookie 存储) / `verification`(sample DOI + 期望域名/PDF 标记)。这是**机构订阅落地的作战地图**。

> 对本项目的启示：144 的 `publisher_direct.py` 相当于第 1+2 层的「直链构造」部分；第 3 层的「访问情报目录」本项目尚无，建议单独沉淀为一份 JSON（供 Phase 2 机构源与 instsci 桥使用）。

---

## 三、前缀 → 出版商 → PDF 直链 总表（合并对标）

> 覆盖状态：✅=144 已构造；➕=建议新增（可纯 DOI 直构）；🌐=需落地页/浏览器（不纯构造）；🔬=需一次 Crossref。

| DOI 前缀 | 出版商 | PDF 直链模板（推荐） | 144 现状 | challenge |
|---------|--------|----------------------|:----:|:----:|
| 10.1038 | Nature | `nature.com/articles/{suffix}.pdf` | ✅ | medium |
| 10.1126 | Science/AAAS | `science.org/doi/pdf/{doi}`（+`epdf`、`?download=true`）| ✅（建议补 epdf）| high |
| 10.1002 / 10.1111 | Wiley | `/doi/pdfdirect/{doi}` → `/doi/pdf/{doi}` → `/doi/epdf/{doi}` | ✅（建议 pdfdirect 优先）| medium |
| 10.1007 / 10.1140 | Springer | `link.springer.com/content/pdf/{doi}.pdf` | ✅ | medium |
| 10.1021 | ACS | `pubs.acs.org/doi/pdf/{doi}`（+`epdf`）| ✅（建议补 epdf）| medium |
| 10.1073 | PNAS | `pnas.org/doi/epdf/{doi}` → `/doi/pdf/{doi}?download=true` | ✅（建议 epdf/`?download`）| medium |
| 10.1177 | SAGE | `journals.sagepub.com/doi/pdf/{doi}` | ✅ | medium |
| 10.1080 | Taylor & Francis | `tandfonline.com/doi/pdf/{doi}` | ✅ | medium |
| 10.1039 | RSC | 年份+刊代码 `articlepdf/{year}/{jcode}/{suffix}`；备 `/articlelanding/→/articlepdf/` | ✅ | medium |
| 10.1103 | APS | `journals.aps.org/{jcode}/pdf/{doi}`（备 `link.aps.org/pdf/{doi}`）| ✅ | medium |
| 10.1016 | Elsevier | PII→`sciencedirect.com/science/article/pii/{PII}/pdfft`（过滤 `-mmc`）🔬 | ✅（建议过滤 mmc）| **high** |
| 10.3390 | MDPI | Crossref ISSN/卷/期/文号→`mdpi.com/{issn}/{vol}/{iss}/{art}/pdf`🔬；备 landing `+/pdf` | ✅ | low |
| 10.1152/61/46/89/1287/1137 | Atypon 系（Physiology/AHA/AnnualReviews/Liebert/INFORMS/SIAM）| `/doi/pdf/{doi}`（建议补 `epdf`）| ✅ | medium |
| **10.1093** | **Oxford Academic** | `academic.oup.com/doi/pdf/{doi}` → `/doi/epdf/{doi}`（文章页更稳）| 🌐➕ | medium |
| **10.1088 / 10.1143** | **IOP / JJAP** | `iopscience.iop.org/article/{doi}/pdf` | ➕ | **high**(PerfDrive) |
| **10.1145** | **ACM DL** | `dl.acm.org/doi/pdf/{doi}` | ➕ | medium |
| **10.1063 / 10.1116** | **AIP / AVS** | `pubs.aip.org/doi/pdf/{doi}` → `/doi/epdf/{doi}` | ➕ | medium |
| **10.1098** | **Royal Society** | `royalsocietypublishing.org/doi/pdf/{doi}` | ➕ | medium |
| **10.1175** | **AMS（气象）** | `journals.ametsoc.org/doi/pdf/{doi}`（备 `downloadpdf/view/...`）| ➕ | medium |
| **10.1142** | **World Scientific** | `worldscientific.com/doi/pdf/{doi}` | ➕ | medium |
| **10.15252** | **EMBO Press** | `embopress.org/doi/pdf/{doi}`（Atypon）| ➕ | medium |
| 10.1109 | IEEE Xplore | 需 `/document/{arnumber}` → `stamp.jsp?arnumber=` | 🌐（不纯构造）| **high** |
| 10.1364 | Optica/OSA | 需 `opg.optica.org` 文章 URI | 🌐（不纯构造）| medium |
| 10.5194 | Copernicus | `{journal}.copernicus.org/articles/{vol}/{page}/{year}/{suffix}.pdf` | （publisher_oa 已含）| low |
| 10.1371 / 10.3389 / 10.1186 / 10.7717 / 10.7554 / 10.3762 | PLOS/Frontiers/BMC/PeerJ/eLife/Beilstein | 见 `publisher_oa.py`（全 OA）| （publisher_oa 已含）| low |

---

## 四、给 144 `publisher_direct.py` 的补丁清单

### 4.1 可纯 DOI 直构的新增前缀（P1，低风险，直接进 `_SIMPLE`）

以下均为 Atypon/稳定路径、可 `{doi}` 直构，未订阅时返回 401/403 由 `%PDF` 校验过滤，不产假成功：

```python
# 追加到 publisher_direct.py 的 _SIMPLE
"10.1145": ("acm",           64, ("https://dl.acm.org/doi/pdf/{doi}",)),
"10.1098": ("royalsociety",  64, ("https://royalsocietypublishing.org/doi/pdf/{doi}",)),
"10.1142": ("worldsci",      60, ("https://www.worldscientific.com/doi/pdf/{doi}",)),
"10.15252":("embo",          62, ("https://www.embopress.org/doi/pdf/{doi}",)),
"10.1175": ("ams",           60, ("https://journals.ametsoc.org/doi/pdf/{doi}",)),
"10.1063": ("aip",           60, ("https://pubs.aip.org/doi/pdf/{doi}",)),
"10.1116": ("avs",           58, ("https://pubs.aip.org/doi/pdf/{doi}",)),
# IOP：article/{doi}/pdf（注意非 /doi/pdf/ 而是 /article/{doi}/pdf）
"10.1088": ("iop",           58, ("https://iopscience.iop.org/article/{doi}/pdf",)),
"10.1143": ("iop-jjap",      56, ("https://iopscience.iop.org/article/{doi}/pdf",)),
```
> IOP 需用 `/article/{doi}/pdf` 形态（与 Atypon 的 `/doi/pdf/{doi}` 不同），且 challenge 高（PerfDrive），HTTP 直取命中率会低于 Atypon 系——建议 confidence 略低、并在 Phase 2 交浏览器。
>
> **⚠️ 144 实测补充（2026-07-02，batch7 闭环）**：DOI `10.35848/1347-4065/ad280f` 走 `iopscience.iop.org/article/{doi}/pdf` **返回 200 的 HTML 落地页（付费墙），而非错误码**——即该直构模板**只对该刊 OA 文章有效**。故 publisher_direct 对这些订阅社直构结果**必须走 `%PDF` 魔数校验**，且**命中 HTML 即判付费墙下沉**，切勿把 200-HTML 当成功（订阅社普遍会返回 200-HTML 而非 401/403，仅靠状态码不足以判失败）。此规则对全部订阅社直链通用，IOP/OUP 尤甚。144 亦实测确认 Elsevier 过滤 `-mmc/_mmc` 附件正确（websearch/landing 常把 `/pii/…/mmc1.pdf` 当候选）。

### 4.2 Atypon「epdf 优先/兜底」优化（P1）

catalog 反复出现 `atypon_epdf_first`：ACS/AIP/PNAS/Science/AnnualReviews/AMS/RoyalSociety/WorldScientific 等 Atypon 站，`/doi/epdf/{doi}` 常在 `/doi/pdf/{doi}` 之前可取。建议对这些社**同时产出 `epdf` 与 `pdf` 两条候选**（epdf 略高 confidence），竞速/回退各试一次。

### 4.3 既有模板精修（P1）

- **Wiley**：`link_characteristics` 明确 `pdfdirect` 优先，再 `pdf`、`epdf`。建议把 `pdfdirect` 的 confidence 提到最高。
- **PNAS**：补 `pnas.org/doi/epdf/{doi}` 与 `pnas.org/doi/pdf/{doi}?download=true`。
- **Elsevier**：`link_characteristics` 提示忽略 `-mmc/_mmc/content/image` 等**附件 PDF**（附录冒充正文）；建议在候选/下载后按 URL 或 `%PDF` 后再加一层「主文 vs 附件」判别。另注意 `/pdfft` 常遇 ScienceDirect Cloudflare「Are you a robot?」，纯 HTTP 会失败 → 交 Phase 2 浏览器。
- **RSC**：除现有「年份+刊代码」构造外，备 `/articlelanding/→/articlepdf/` 落地路由（构造失败时）。

### 4.4 明确「不纯构造」的社（避免臆造坏候选）

- **IEEE（10.1109）**：PDF 需 `arnumber`，必须先取 `/document/{id}` 落地页解析 → 交 landing/浏览器，不进 `_SIMPLE`。
- **Optica/OSA（10.1364）**：需 `opg.optica.org` 文章 URI，不纯构造。
- **Oxford（10.1093）**：`/doi/pdf/{doi}` 有时可取但文章页路由更稳（`/{journal}/article-pdf/...`）；建议低 confidence 直构 + landing 兜底。

---

## 五、验证样例 DOI 集（可作 publisher_direct selftest fixtures）

来自 catalog `verification.sample_doi`（截至 2026-06-06 复核），可用于回归「构造出的 URL 命中期望域名/PDF 标记」：

| 出版商 | sample DOI | 期望 PDF 标记 |
|--------|-----------|---------------|
| ACS | `10.1021/acs.est.6c00693` | `/doi/pdf/` `/doi/epdf/` |
| AIP | `10.1063/5.0237567` | `/doi/epdf/` `/doi/pdf/` |
| AMS | `10.1175/aies-d-23-0093.1` | `/downloadpdf/view/` `/doi/pdf/` |
| ACM | `10.1145/3448016.3452834` | `/doi/pdf/` |
| Annual Reviews | `10.1146/annurev-phyto-011325-012824` | `/doi/pdf/` |
| APS | `10.1103/PhysRevLett.128.161102` | `/pdf/10.1103/` |
| Copernicus | `10.5194/acp-24-1-2024` | `/articles/` `.pdf` |
| Elsevier | `10.1016/j.watres.2024.121507` | `/pdfft` `main.pdf` |
| Frontiers | `10.3389/fmicb.2026.1831710` | `/pdf` |
| IEEE | `10.1109/jstqe.2026.3687110` | `stampPDF` `arnumber=` |
| IOP | `10.1088/1361-648x/ae72dd` | `/pdf` |
| MDPI | `10.3390/foods10081757` | `/pdf` |
| Oxford | `10.1093/nar/gkaa892` | `/doi/pdf/` `/article-pdf/` |
| PLOS | `10.1371/journal.pone.0000001` | `type=printable` |
| PNAS | `10.1073/pnas.2309123120` | `/doi/epdf/` `/doi/pdf/` |
| Royal Society | `10.1098/rsos.150470` | `/doi/pdf/` |
| RSC | `10.1039/d5cp03829d` | `/content/articlepdf/` |
| Science | `10.1126/sciadv.adp3964` | `/doi/epdf/` `/doi/pdf/` |
| Springer/Nature | `10.1038/s41586-020-2649-2` | `/content/pdf/` `.pdf` |
| Wiley | `10.1002/adfm.202525261` | `/doi/pdfdirect/` `/doi/pdf/` |
| World Scientific | `10.1142/s0218194026500348` | `/doi/pdf/` |

---

## 六、机构访问 / 身份情报（供 Phase 2 与 instsci 桥）

catalog 的 `identity` / `persistence` 是**机构订阅落地的关键输入**，建议本项目沉淀为独立 JSON：

- **challenge_risk 分档**：
  - **high**：Elsevier(Cloudflare)、IEEE、IOP(PerfDrive)、Science(Atypon+Cloudflare)。→ 必走浏览器（CloakBrowser），纯 HTTP 大概率失败。
  - **medium**：ACS/AIP/AMS/ACM/AnnualReviews/APS/Oxford/PNAS/RSC/RoyalSociety/Springer/Wiley/WorldScientific/T&F。→ HTTP 先试，失败转浏览器。
  - **low**：Copernicus/Frontiers/MDPI/PLOS（OA）。→ 纯 HTTP 即可。
- **闭源访问要求**：普遍为 `institutional_ip_or_proxy` / `federated_sso_or_openathens`(Shibboleth/CARSI/OpenAthens) / `personal_or_library_subscription`；Elsevier 另可选 `API + institution token`。
- **登录入口提示**：`Access through your institution` / `OpenAthens` / `Shibboleth`（页面上定位 SSO 入口的锚点词）。
- **Cookie 持久化**：`browser_profile_dir` + `carsi_cookie_dir/{publisher}.json` + `attempt_cache`；**共享 profile 供并行 worker 克隆**（与 141/instsci Cookie 持久化层设计一致）。
- **实测教训（catalog 记录）**：APS 的 `/login_inst_user` 是机构用户名口令、非可复用 SSO，OpenAthens/WebVPN(清华实测)未授权样例 PDF → APS 订阅内容标为「不支持可复用机构登录」，仅对 OA 用直链。IEEE 勿直连 `servlet/wayf.jsp`（丢 SeamlessAccess 上下文，误判 institution_not_registered）。

---

## 七、给总指挥（147）/ 组员 144 的落地建议

1. **P1 直接采纳**：把 §4.1 的 8 个新前缀 + §4.2 epdf 优化 + §4.3 模板精修合入 `publisher_direct.py`（纯构造、低风险、有 %PDF 兜底与 selftest 保护）。建议 144 用 §5 的 sample DOI 扩充离线 selftest（只断言「构造 URL 命中期望标记」，不联网）。
2. **P1**：新建 `fulltext_fetcher/data/publisher_access_catalog.json`（可直接移植/裁剪 scansci 的 19 家目录），供 Phase 2 机构源与 challenge 分档路由使用。
3. **P2（依赖机构订阅落地）**：high-challenge 社（Elsevier/IEEE/IOP/Science）走浏览器（CloakBrowser）+ 按出版商分组一次登录（见竞速引擎文档 §3.6），与 141 的 Cookie 持久化层协同。
4. **协同**：本清单可由 142 通过 `send_to_session` 直送 144（sessionId 见 list_sessions）供其实现参考——待工作组恢复后执行。

---

## 参考

- scansci-pdf @ master：`src/scansci_pdf/sources/publishers.py`（`DOI_PREFIX_TO_PUBLISHER` / `PUBLISHER_TOOL_MAP` / 各 `try_*_direct`）、`src/scansci_pdf/data/publisher_access_catalog.json`（19 家访问目录，`last_static_review: 2026-06-06`）。
- 本项目：`fulltext_fetcher/sources/publisher_direct.py`（144，机构订阅直链源）、`sources/publisher_oa.py`（OA 直链源）。

> 本文档为智库检索成果，模板与判断基于 2026-07-02 的 scansci master 源码/数据与本项目当时代码。所有订阅出版商直链**仅供拥有合法机构订阅、对相应内容有权访问的用户**在授权前提下使用；无有效订阅时直链返回 401/403，由 `download.py` 的 `%PDF` 魔数校验自动过滤，不产假成功。
