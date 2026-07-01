# 免费搜索引擎 / 网络找 PDF 方法与开源项目调研（2026 最新）

> 工作组目标:自建谷歌学术爬虫,抓元数据 + **可及 PDF**,文件名标准化,一键批量。
> 本文件聚焦"**不花钱、不碰付费墙**地把论文 PDF 找到"的方法与开源生态,是对 `检索成果-角度1(GitHub 项目)` / `角度2(官方开放 API)` / `角度5(即用型工具)` 的**专题增量**:补齐"通用搜索引擎找 PDF 技巧 + 各引擎可抓性"、`unpywall`/`oa.works`/`scidownl`/`respf` 等库的 **2026 最新维护态**,并给出**面向本项目(Wiley/Elsevier/ACS 化工催化文献)的命中率排序**。
> 整理人:谷歌学术人机认证-153(worker)｜数据核验:**2026-07-01**(GitHub/PyPI/官网,星数取整到十位)。

---

## 〇、一页速览(TL;DR)

- **主力永远是"走正门 API"**:`Unpaywall`(`best_oa_location.url_for_pdf`)+ `OpenAlex`(`open_access.oa_url`)+ `Semantic Scholar`(`openAccessPdf`)+ `CORE v3`(37M+ **全文** 可直下)。免费、无验证码、按 DOI/标题即取——这是免费拿 PDF 的**性价比天花板**。
- **⚠️ 重大变更**:**Open Access Button / oa.works 已于 2025-11-18 永久关停**(网站/API/浏览器扩展/InstantILL 全部下线),官方明确让迁移到 **OpenAlex/Unpaywall**。任何旧方案里引用它的都要删掉。
- **预印本是化学/催化的关键免费源**:`ChemRxiv`(Cambridge Open Engage)+ `arXiv`/`bioRxiv` 等;`paperscraper`(2026-06 活跃)原生支持 chemRxiv,是化学场景最值得吸收的库。
- **通用搜索引擎兜底**:`filetype:pdf` + 标题精确匹配 + `site:`(researchgate/机构库/作者主页)。**Google 难抓(验证码)**,**Bing / DuckDuckGo 易抓且索引不同**,适合交叉补漏——但只作最后一档,产出噪声高。
- **开源项目**:值得吸收 `respf`(多源 OA-first 下载 + `%PDF` 校验,思路与本项目 pipeline 几乎一致)、`paperscraper`(预印本/化学)、`scholarly`(GS 元数据底座);`PyPaperBot` 可作下载载体(注意其 Sci-Hub 部分合规)。**不用** `unpywall`(2024-02 停更)、`scidownl`(停更且 2025+ 实测下不动)、`oa.works`(已关停)。
- **本项目(Wiley/Elsevier/ACS 催化)诚实结论**:订阅重灾区,免费全文天花板本就低(本仓 A.9 实测约 11%)。命中率排序见 §四:**绿色 OA(Unpaywall/OpenAlex/CORE)> 预印本(ChemRxiv)> 出版商 OA 直链(A3 已做)> 作者自存/搜索引擎兜底**。

---

## 一、免费拿"付费墙论文"的全景(合法途径)

核心认知:**同一篇付费论文,往往存在合法免费副本**——作者自存稿(green OA)、预印本、机构库、金色 OA。找 PDF = 把这些副本挖出来。按可编程性与产出稳定度排序:

| 途径 | 代表源 | 覆盖 / 说明 | 取 PDF 方式 | 对化学/催化 |
| --- | --- | --- | --- | --- |
| **OA 聚合 API(首选)** | **Unpaywall** | 4000万+ 免费全文,专做"给 DOI 找 OA PDF" | `GET api.unpaywall.org/v2/{doi}?email=` → `best_oa_location.url_for_pdf`;免费、10万/天 | ★★★ 首选 |
| | **OpenAlex** | 2.5亿+ 作品,带 `open_access.oa_url` | `GET api.openalex.org/works/doi:{doi}?mailto=`;免费(可选 key) | ★★★ |
| | **Semantic Scholar** | 2亿+,`openAccessPdf` 字段 + TLDR | `graph/v1/paper/...`;免费、建议申请免费 key | ★★ |
| | **CORE v3** | **37M+ 全文**、260M+ 元数据,聚合 1万+ 机构库 | `api.core.ac.uk/v3`,**需免费 key**;全文下载 `/v3/outputs/{id}/download`(需鉴权,~10 req/min) | ★★★(绿色 OA 全文最全) |
| **预印本服务器** | **ChemRxiv** | 化学预印本(Cambridge Open Engage) | 官网/Open Engage API;`paperscraper` 有 chemrxiv 模块 | ★★★(化学专属) |
| | arXiv / bioRxiv / medRxiv | 物理/CS / 生物医学 | 各自 API;`paperscraper`/`respf` 支持 | ★(催化偶有) |
| **DOI 兜底聚合** | Crossref `link[]` | DOI 权威库,含全文链 | `api.crossref.org/works/{doi}`;**但 link[] 多为 TDM 链、噪声高**(本仓 A.9 已降权) | ★(低,配合出版商适配器) |
| **机构库 / 作者自存** | 大学 IR、作者主页、Google Scholar "[PDF]" 侧链 | green OA 主体;催化组常自存 accepted manuscript | 需落地页解析(本仓 `landing.py` A2 已增强)/搜索引擎定位 | ★★ |
| **学术社交** | ResearchGate / Academia.edu | 作者上传副本(版权状态不一) | 页面反爬强;经搜索引擎 `site:researchgate.net` 命中后人工/半自动取 | ★(合规存疑,慎用) |
| **Europe PMC / PMC** | 生物医学开放全文 | 化学交叉少 | REST API | ☆ |

> 要点:**先查 Unpaywall/OpenAlex 的 OA 字段**(一次 API 命中就省掉后面所有折腾);未果再上 CORE 全文库与预印本;再未果才落到搜索引擎兜底与出版商直取。

---

## 二、通用搜索引擎找 PDF:技巧 + 各引擎"可抓性"

当结构化 API 都没命中(常见于订阅论文的作者自存稿散落在个人/机构页),**通用搜索引擎**是低成本兜底。

### 2.1 高命中查询算子
- `filetype:pdf` —— 只返回 PDF 直链(Google/Bing/DuckDuckGo 语法一致)。
- **标题精确匹配**:整标题加引号 `"Exact Paper Title Here" filetype:pdf`。
- `site:` 定向:`site:researchgate.net`、`site:*.edu`、`site:*.ac.uk`、作者机构域;或某出版商 OA 子站。
- **DOI 直搜**:把 DOI 当关键词(有的自存稿页/仓库页会带 DOI)。
- 追加意图词:`"title" filetype:pdf (open access OR "accepted manuscript" OR postprint)`。
- 排除干扰:`-sample -preview -supporting`(滤掉样章/预览/补充材料)。

### 2.2 各引擎可抓性(自动化视角,2026)
| 引擎 | 支持算子 | 程序化可抓性 | 说明 |
| --- | --- | --- | --- |
| **Google** | filetype/site/精确 最强、索引最大 | **难**:高频即验证码/`sorry` 页(与抓 Scholar 同一套风控);需 curl_cffi/nodriver + 住宅代理(见 角度3) | 覆盖最广,但自动化成本最高;适合人工/低频 |
| **Bing** | 支持 filetype/site | **较易**:反爬弱于 Google;曾有 Web Search API(2025 起微软调整/收紧,注意时效) | 索引与 Google 不同,**适合交叉补漏** |
| **DuckDuckGo** | 支持 filetype/site,注重隐私 | **较易**:`html.duckduckgo.com/html/` 轻量端点历史上好抓(会限速,需退避);有社区库 | 无强用户画像;结果来自 Bing 系索引 |
| 垂直 PDF 搜索站 | 各自语法 | 视站而定 | 噪声大、质量参差,不建议作主路径 |

> 结论:**别用 Google 做自动化 PDF 挖掘**(风控等同抓 Scholar);要程序化兜底优先 **Bing / DuckDuckGo**,并对结果做 `%PDF` 魔数 + 体积 + 标题相似度校验(本仓 `download.py` 已具备前两者)。搜索引擎兜底**永远是最后一档**:产出噪声高、需二次校验,且抓取本身也可能触发风控。

---

## 三、开源项目对比(2026-07-01 核验)

### 3.1 "找/下 PDF"类库

| 项目 | 仓库 | ⭐ | 许可 | 最新 & 维护 | 功能 | 对本项目 | 裁决 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **respf** | PyPI `respf`(v1.3.x) | 新 | — | 2026,活跃 | 多源 OA-first 下载(Unpaywall/OpenAlex/PubMed/bioRxiv/arXiv/PLOS/HAL/OSF/Crossref/Springer 启发式/S2/GS 兜底);**按标识符路由 + `%PDF` 校验 + difflib 标题匹配(<0.62 拒收)** | 思路与本项目 pipeline **高度一致**,含 Springer/Crossref/GS 兜底 | **直采/重点吸收** |
| **paperscraper** | jannisborn/paperscraper | ~530 | MIT | **v1.0.0(2026-06,活跃)** | PubMed/arXiv/bioRxiv/medRxiv/**chemRxiv** 元数据+全文;GS 仅取被引;期刊 IF;本地 dump 可复现 | **化学(chemRxiv)友好**、反爬暴露面低、维护最活跃 | **吸收(预印本/化学)** |
| **scholarly** | scholarly-python-package/scholarly | ~1,900 | Unlicense | 维护中(v1.7.x) | GS 元数据事实标准底座(作者/单篇/`search_pubs`/`citedby`);内置 `ProxyGenerator` | GS 元数据载体(需住宅代理;高频仍封 IP) | **吸收(元数据)** |
| **PyPaperBot** | ferru97/PyPaperBot | ~640 | MIT | v1.4.1(2024 复活) | 多源下 PDF+BibTeX:GS/Crossref/**Sci-Hub/SciDB**;按年/期刊/被引过滤 | 批量下载载体;**Sci-Hub 部分有合规风险** | **谨慎吸收(禁用 Sci-Hub 部分)** |
| **paper-search-cli** | dr-dumpling / Sevenprogram | 新 | — | 2026,活跃 | agent-facing 多源:OA-first fallback(CORE/OpenAIRE/Unpaywall)、Wiley DOI 取用、Sci-Hub 可选;JSON 输出 | agent/CLI 设计思路可参考 | **参考** |
| **unpywall** | unpywall/unpywall | ~30 | MIT | **v0.2.3(2024-02,停更)** | Unpaywall API 的 pandas 封装 | Unpaywall 直接调 REST 即可,本项目已用 | **不用**(停更;裸调 API) |
| **scidownl** | Tishacy/SciDownl | ~300 | MIT | v1.0.2(2023);**推送停 2024-02** | 经 Sci-Hub 按 DOI/PMID/title 下 PDF | 用户报 **2025+ 实测下不动**(Sci-Hub 变更);+合规风险 | **不用**(停更+失效+合规) |
| **Open Access Button / oa.works** | oaworks/api | — | — | **2025-11-18 永久关停** | 曾按 DOI 找免费副本 API/扩展 | 官方让迁 OpenAlex/Unpaywall | **不用(已死)** |

### 3.2 "官方开放 API 封装"(见 角度2,免费无验证码,应作主用)
- 直接调 REST 最省心:Unpaywall `/v2/{doi}`、OpenAlex `/works`、Semantic Scholar `graph/v1`、CORE `v3`。
- Python 封装:`pyalex`(OpenAlex)、`semanticscholar`、`habanero`(Crossref)——按需,不必强依赖。
- 桌面无代码:`Publish or Perish`(多后端检索,不直接下 PDF,给链接)。

---

## 四、面向本项目(Wiley/Elsevier/ACS 化工催化)的命中率排序

> 前提(本仓 A.9 / 规模化验证报告实测):Wiley/Elsevier/ACS 的化学/催化文献是**订阅重灾区**,多数无免费全文;硬 403 是付费墙、不是程序 bug;免费手段实测天花板约 **11%**(landing 解析后升到 ~13.8%)。因此策略是"**把能免费拿到的那部分尽量榨干**",而非追求全覆盖。

**建议按此顺序试(前面命中就停):**

1. **绿色 OA 直取 API**:`Unpaywall(best_oa_location) → OpenAlex(oa_url) → Semantic Scholar(openAccessPdf)`。一次 API 命中即拿作者自存稿/金色 OA。**投入产出比最高**。
2. **CORE v3 全文库**:按 DOI/标题查 `has_full_text=true`,直下 `/outputs/{id}/download`(37M+ 全文,富含机构库自存的 accepted manuscript)。
3. **预印本**:`ChemRxiv`(催化预印本渐多)+ arXiv,用 `paperscraper` 或 Open Engage 检索作者预印本版。
4. **出版商 OA 直链**:本仓 **`publisher_adapter`(A3)** 已按 DOI 前缀路由 ACS/Springer/Wiley/IOP 等的直链模板 + `Accept: application/pdf` 头 + Crossref(TDM 降权);对少数 gold/hybrid-OA 文章有效。
5. **落地页解析回收**:拿到 HTML 落地页时用本仓 **`landing.py`(A2)** 抠 `citation_pdf_url`/出版商 selector/内嵌 PDF(能回收一部分"定位到却返回 HTML")。
6. **搜索引擎兜底**:`"精确标题" filetype:pdf`(Bing/DuckDuckGo 优先),`site:researchgate.net`/机构域找作者自存稿;结果必过 `%PDF`+体积+标题相似度校验。
7. **(合规边界外,默认关)** Sci-Hub / SciDB:法律/伦理风险,本项目默认不启用;仅在用户明确知情并自担风险时作为最后手段。

**诚实边界**:纯订阅催化论文,任何免费手段都拿不到全文;要更高覆盖只能上**机构订阅**(本仓 `http_client` 有 EZproxy 钩子)或**商业抓取服务**(见 角度4)。对开放/绿色 OA 论文,上面 1–5 步已能稳定命中。

---

## 五、合规声明
- 上述途径均针对**合法免费副本**(OA/预印本/作者自存/机构库);不绕付费墙、不抓 Scholar 正文。
- Sci-Hub / SciDB 属版权灰/黑区,**默认关闭**;ResearchGate 等社交平台副本版权状态不一,自动化抓取前需评估其 ToS。
- 通用搜索引擎抓取需遵守其 ToS 与 `robots.txt`,并限速退避(Google 尤甚,等同抓 Scholar 的风控)。

---

## 六、来源(均 2026-07-01 核验)
- Unpaywall REST API:`unpaywall.org/products/api`(`/v2/{doi}`、`best_oa_location`、10万/天)
- OpenAlex:`developers.openalex.org`(`/works`、`open_access.oa_url`、`mailto`/可选 api_key)
- Semantic Scholar:`api.semanticscholar.org`(`openAccessPdf`、bulk、免费 key)
- CORE v3:`core.ac.uk/documentation/api` + `core.ac.uk/services/api`(免费 key、`/v3/search/works`、全文 `/v3/outputs/{id}/download`、37M+ 全文)
- **Open Access Button / oa.works 关停**:`blog.oa.works/sunsetting-the-open-access-button-instantill/`(2025-11-18 永久关停,迁 OpenAlex/Unpaywall);`github.com/oaworks/api`(410/503 关停代码)
- 开源库:`github.com/jannisborn/paperscraper`(chemRxiv、v1.0.0 2026-06)、`github.com/scholarly-python-package/scholarly`、`github.com/ferru97/PyPaperBot`、`github.com/Tishacy/SciDownl`(#32 "still alive?" 2025-06→2026-03、PR#34 修复)、`github.com/unpywall/unpywall`(v0.2.3 2024-02)、PyPI `respf`(多源 OA-first + %PDF 校验)、`github.com/dr-dumpling/paper-search-cli`
- 搜索引擎技巧:`pdf.ai/resources/pdf-document-search-engines`(2026,Google/Bing/DuckDuckGo `filetype:pdf`);Google 高级搜索/`filetype:` 说明
- 本仓交叉:`检索成果-角度1/2/5`、`经验记录-踩坑与发现.md`(A.9 Crossref TDM 降权、化学订阅天花板 ~11%)、`fulltext_fetcher/publisher_adapter.py`(A3)、`fulltext_fetcher/landing.py`(A2)
