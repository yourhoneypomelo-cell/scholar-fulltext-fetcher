# 分析 · batch6 源配置对比（用了哪些源 vs 现有可用源）

> 分析者：谷歌学术人机认证-158（worker）｜任务：task-280f905e-4856-491c-92a9-b23f6662d4d7
> 口径：**纯静态只读**（`fulltext_fetcher/config.py`、`sources/__init__.py`、`sources/*.py` 的 `@register`/DEFAULT_SOURCE_ORDER）+ 154《检索成果-batch6-失败分桶与可回收分析.md》（其读取了真实 `out/batch6/*`）。
> **数据前提（重要）**：当前工作区**无 `run.log`、无 `out/` 目录**（`out/batch6/{summary.json,attempts.jsonl,...}` 不在本工作区，154 的分析系离线只读）。故 batch6 的"运行时启用源"**据 154 分析文档 + `by_source` 成功分布 + config 源码演进推断**，非直接读 run.log；下有明确标注。`val500_input.txt`（500 DOI）与 batch6"输入 500"一致，batch6 即 val500 跑批。
> 本文件为**新建的唯一 md**，未改任何 `.py` 或其它文档。

---

## 一、结论速览（TL;DR）

- **batch6 只跑了"API 聚合器 + 学科仓储 + green_oa"这批老源**（unpaywall/openalex/semantic_scholar/crossref/openaire/europe_pmc/pmc/doaj/core/base/hal/osf/zenodo/scienceopen/arxiv/biorxiv；snapshot 视是否配 `--snapshot-db`）。
- **batch6 完全没用到"免费方法"新源**：`publisher_oa / oa_button / websearch / wayback / browser_search`（这 5 个由 `free_adapters.py` 注册，属本工作组新增），以及**尚未接线**的 `preprints`（ChemRxiv/ResearchSquare/Preprints.org）。
- 这 6 个"新可用/待接线"源，**正好对应 154 分析里 431 条 MISS 的回收手段**——即 batch6 的失败很大程度上是"**这些源当时还没上**"。
- **现默认 `DEFAULT_SOURCE_ORDER` 已含**前 4 个免费源（publisher_oa/oa_button/websearch/wayback），`browser_search` 注册但默认不入序（重、需显式 `--sources`），`preprints` **还没注册进 REGISTRY**（需集成）。
- **预期增量**：接齐新源后按 154 估计**可回收 ≈125 条 / 高置信底线 ≈28 条**（金色 OA 14 + PMC 14）。
- **建议**：① 把 `preprints` 接线并放进默认序（化学/材料语料高价值）；② 保留 `browser_search` 为"回收档"显式开启；③ 采用下文 §六 的最优顺序。

---

## 二、batch6 实际使用的源顺序（推断）

> 依据：154 文档"成功来源 by_source"与"附录·OA 源集合"（其直接来自 `out/batch6/metadata.jsonl` 的 `attempts[].source`）。**因无 run.log，顺序按当时 `DEFAULT_SOURCE_ORDER` 的老版推断**（新免费源当时尚未加入）。

- **确有 attempts 记录的源**（batch6 实际启用）：
  `unpaywall, openalex, semantic_scholar, crossref, core, openaire, europe_pmc, pmc, doaj, base, hal, osf, zenodo, scienceopen, arxiv, biorxiv`（crossref 归"出版商链接"）。
- **产生成功下载的源**（by_source，共 69 成功）：`openalex 30 / semantic_scholar 19 / crossref 10 / openaire 7 / europe_pmc 2 / hal 1`。
- **snapshot**：仅当配 `--snapshot-db` 才生效；batch6 成功分布无 snapshot、且无证据配了本地快照库 → 推断**未启用**。
- **明确未出现**：`publisher_oa / oa_button / websearch / wayback / browser_search / preprints`（154 把它们列为 MISS 的**回收手段**，即"当时没用上"）。

> 一句话：**batch6 = 纯"在线免费 API 聚合器 + 仓储"路线，没有任何"免费方法/自存稿/预印本/浏览器"兜底源**。

---

## 三、现有 `sources/` 全部可用源模块（注册名 × 接线状态）

> 注册机制：`sources/__init__.py` 通过 `import` 触发各模块 `@register`；`build_sources(cfg)` 按 `cfg.sources` 顺序实例化。**未被 import 的模块 = 不在 REGISTRY = 不可选**。

| 模块文件 | 注册源名（`name=`） | 是否 @register | 是否被 `__init__` 导入 | 是否在默认序 | batch6 用过 |
|---|---|---|---|---|---|
| `snapshot_source.py` | `snapshot` | ✅ | ✅ | ✅(1) | 否（需 --snapshot-db） |
| `aggregators.py` | `unpaywall,openalex,semantic_scholar,crossref,core,openaire` | ✅ | ✅ | ✅ | ✅ |
| `repositories.py` | `arxiv,europe_pmc,pmc,biorxiv,doaj,zenodo,hal` | ✅ | ✅ | ✅ | ✅ |
| `green_oa.py` | `base,osf,scienceopen` | ✅ | ✅ | ✅ | ✅ |
| `free_adapters.py` | `publisher_oa,oa_button,websearch,wayback,browser_search` | ✅ | ✅ | 前4在序/`browser_search`不在 | **否（新增）** |
| `publisher_oa.py`（逻辑） | —（经 free_adapters 包装为 `publisher_oa`） | ❌纯逻辑 | 经 free_adapters 延迟导入 | 见上 | 否 |
| `oa_button.py`（逻辑） | —（→ `oa_button`） | ❌ | 经 free_adapters | 见上 | 否 |
| `websearch.py`（逻辑） | —（→ `websearch`） | ❌ | 经 free_adapters | 见上 | 否 |
| `wayback.py`（逻辑） | —（→ `wayback`） | ❌ | 经 free_adapters | 见上 | 否 |
| （父包）`browser_search.py`（逻辑） | —（→ `browser_search`） | ❌ | 经 free_adapters | ❌默认不入序 | 否 |
| `preprints.py`（逻辑） | **无** | ❌ | **❌ 未被任何处导入** | ❌ | 否 |
| `scihub.py` | `scihub` | ✅ | ✅ | ❌（注释关闭，合规风险） | 否 |
| `base.py` | 基类/注册表，非源 | — | ✅ | — | — |

**当前 `DEFAULT_SOURCE_ORDER`（21 个启用）**：
`snapshot, unpaywall, openalex, publisher_oa, oa_button, europe_pmc, arxiv, biorxiv, semantic_scholar, pmc, core, base, crossref, doaj, openaire, hal, osf, zenodo, scienceopen, websearch, wayback`
（注释掉：`browser_search`、`scihub`）

**关键结构点**：
- `free_adapters.py` 是"免费方法"的**唯一集成点**：把 `publisher_oa/oa_button/websearch/wayback` 逻辑模块 + 父包 `browser_search` 包装成 `BaseSource` 并 `@register`（逻辑模块本身**不 @register**，避免多人并行改共享文件冲突）。
- **`preprints.py` 是唯一"已写好逻辑、但完全未接线"的源**：无 `@register`、`__init__.py` 与 `free_adapters.py` 均未导入它（其 docstring 明确"集成由总指挥统一做"）。→ 现阶段**无法通过 `cfg.sources` 选中**。

---

## 四、batch6 没用、但"现在已可用/近可用"的源

| 源 | 现状 | 命中的 MISS 桶（154） | 价值 |
|---|---|---|---|
| `publisher_oa` | ✅已注册、已在默认序 | 金色 OA（MDPI 13 直取 `/pdf`）、RSC free-to-read | **高**（近乎必得 floor 一部分） |
| `europe_pmc`/`pmc`（下载复核） | batch6 已"定位"但下载失败（A 类） | A 类 PMC 全文 14 | **高**（NIH 托管、无反爬；属"下载器/UA"问题） |
| `wayback` | ✅已注册、已在默认序 | A 类其余、B/C 兜底 | 中 |
| `websearch` | ✅已注册、已在默认序（146 加固中） | ACS/RSC/Wiley/Elsevier 自存稿、机构库 | 中（B/C 类主力兜底之一） |
| `browser_search` | ✅已注册，**默认不入序**（需 `--sources ...,browser_search`） | A 类渲染后下载、B/C 自存稿（Bing 召回强） | 中-高（重、慢，回收档用；本人实测 Bing 55 候选 vs 纯HTTP 4） |
| `oa_button` | ✅已注册、已在默认序 | 官方端点已停用→通常空 | 低（便宜、留着无害） |
| **`preprints`（ChemRxiv/RS/Preprints.org）** | ❌**未接线**（逻辑就绪） | **ACS 76(B类) 化学预印本、RSC/Wiley 部分** | **高**（语料=催化/化工/材料，ChemRxiv 覆盖好，154 估 ACS 回收 ≈23–25） |

> 注：`snapshot`（本地快照库）batch6 未用；若灌库（`ingest`/`snapshot_bootstrap`）则可零联网命中，属"提速/免额度"而非"多回收"。

---

## 五、新源加入后的预期增量（映射 154 的可回收估计）

> 154 基于真实 `out/batch6` 的分桶估计：**可回收 ≈125 条（约占 431 MISS 的 30%）**，**高置信"稳拿"底线 ≈28 条**。把它按"新源→桶"拆解：

| 新源/手段 | 目标桶 | 桶条数 | 预期回收(154) |
|---|---|---:|---:|
| `publisher_oa` 直取 + `pmc`/`europe_pmc` 下载复核 | 金色OA 14 + PMC 14 | 28 | **≈27（近乎必得）** |
| `browser_search` + `wayback`（渲染后下载 A 类 OA URL） | A 类其余 58 | 58 | ≈40 |
| **`preprints`(ChemRxiv) + arXiv** | ACS 76(B) + AIP/IOP/IEEE/Nature | ~82 | ≈25 |
| `websearch` 深挖（自存稿/机构库/ResearchGate） | RSC/Wiley/Springer B 类 | ~56 | ≈15 |
| `websearch`（低优先、先抽样） | Elsevier C 类 | 188 | ≈24 |
| **合计** | | | **≈125（底线≈28）** |

**解读**：batch6 的 431 MISS 中 **100% 是 `no-downloadable-pdf`（无网络/熔断问题）**——即"当时的源集合没找到/没下到免费 PDF"。**新源恰是对症下药**：金色OA/PMC 属"下载器修复即得"，ACS 靠预印本，A 类其余靠浏览器渲染下载 + wayback，B/C 靠 websearch。**理论天花板 ≈125 条回收（成功率从 13.8% → ~38%）**，其中 ≈28 条近乎必得。

---

## 六、推荐最优源顺序配置

原则：**先便宜/高精度、后重/兜底**；直链纯构造与免费 API 在前，学科预印本/自存稿其次，搜索引擎与存档兜底在后，浏览器与 Sci-Hub 显式开启。

**建议 `DEFAULT_SOURCE_ORDER`（生产默认，含接线 `preprints`）**：
```
snapshot            # 有本地快照库则零联网秒命中
unpaywall           # 免费、覆盖最广、直给 url_for_pdf
openalex            # 免费、pdf_url
publisher_oa        # 纯构造直链(MDPI/Frontiers/PLOS…)，回收金色OA、极便宜
europe_pmc          # NIH 托管、无反爬、稳定(回收 A 类 PMC)
pmc                 # PMCID→PDF
arxiv               # 预印本直链
biorxiv             # 生物预印本
preprints           # ★新接线:ChemRxiv/ResearchSquare/Preprints.org(化学/材料语料高价值)
semantic_scholar    # openAccessPdf
core                # 需 key,36M+ 全文
base                # BASE 400M+ OA 聚合
doaj                # 纯 OA 期刊
crossref            # link[] TDM,多兜底
openaire            # 聚合兜底
hal                 # 法国仓储
osf                 # OSF 预印本
zenodo              # 数据/附件/论文
scienceopen         # 10.14293 自托管 OA
oa_button           # 官方端点多已停(通常空),便宜留着
websearch           # 免费搜索引擎找自存稿/机构库(真 miss 才触发)
wayback             # Internet Archive 存档 PDF 兜底
# browser_search    # ★回收档显式开启:--sources ...,browser_search(重、慢、Bing 召回强)
# scihub            # 合规风险,--enable-scihub 才开
```

**要点**：
1. **接线 `preprints`**（唯一"已就绪未接线"）：仿 `free_adapters.py` 加一个 `PreprintsSource(BaseSource, name="preprints")` 适配器（`find_pdf_candidates(doi,title,cfg)->List[str]` 经 `_mk_candidates` 包装）+ 在 `__init__.py` 触发导入 + 放进上面顺序。**由总指挥统一改**（免费逻辑模块约定不自 @register）。
2. **`browser_search` 维持"默认关、回收档开"**：每条起无头浏览器、~10s/条且易限速；仅对 A 类其余 + B/C 自存稿做"回收专跑"时 `--sources` 显式加，Bing 主、与 146 的纯 HTTP-DDG 错峰。
3. **下载环节修复优先于加源**：154 的 A 类(86) 是"OA 已定位、下载失败"——**先把真实 UA/Referer/渲染下载补上**，这批"改下载器即得"的 ≈40–67 条 ROI 最高（无需新源）。
4. **"回收专跑 profile"（建议）**：对 431 MISS 重跑时用
   `--sources publisher_oa,europe_pmc,pmc,preprints,arxiv,websearch,wayback,browser_search`
   聚焦免费方法，避开已耗尽的 API 聚合器，省时。

---

## 七、协同与边界

- 本文仅**只读分析 + 建议**，未改任何 `.py`/其它文档；接线 `preprints`、调整 `DEFAULT_SOURCE_ORDER`、`browser_search` 入序与否均属**代码改动，需总指挥统一编排**（`config.py`/`sources/__init__.py`/`free_adapters.py` 是共享文件，避免多人并行冲突）。
- 已知真依赖/需对齐点（供总指挥决策，非阻塞本分析）：
  1. **`preprints` 未接线**——是最值得优先补的"已就绪缺口"（化学/材料语料 × ACS B 类 76）。
  2. `websearch`（146 加固中）、`browser_search`（158 已加固、实测 Bing 55 候选）为 B/C 类兜底主力；接入 pipeline 时建议两路（146 DDG-HTTP + 158 Bing-浏览器）候选**并联去重**。
  3. run.log/`out/batch6/` 不在工作区,若需精确复盘 batch6 的运行时 `--sources` 实参,请提供 run.log 或 `out/batch6/summary.json`,我可据其把"推断"升级为"实证"。

---

*核验：2026-07-01，静态只读 config/sources + 154《batch6 失败分桶》。*
