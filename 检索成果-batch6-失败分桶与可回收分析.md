# 检索成果 · batch6 · 失败分桶与可回收分析

> ⚠️ **2026-07-02 刷新**：本文取代 **7/1 11:56 旧 run（success 69/500 = 13.8%，MISS 431）** 的分析，现依据 **7/1 13:40 run（累计 success 410/500 = 82%，MISS 90）** 全量重算。旧口径的 A=86 / B=149 / C=196 已作废，新旧对比见 §〇。
>
> ⚠️ **净覆盖率口径统一（173 冻结）**：本文 **82%（410/500）**是 **batch6 单批·metadata 声称成功**口径（含 websearch 抓错论文假阳），**既非全库、也非内容 QC 后净覆盖**。**全库内容 QC 后真净覆盖（唯一权威）= `out/coverage.json`：326 success / 673 miss / 999 = 32.63%**（generated_ts 2026-07-03 12:50:24，allow_override=10）。口径不同勿混用；详见 **《基线口径冻结说明-388-173.md》**。
>
> 刷新者：谷歌学术人机认证-176（worker）｜原分析者：谷歌学术人机认证-154｜任务：`task-d9b473e6-ac1c-47e3-847a-d4dc295c218f`
> 数据口径：`out/batch6/{summary.json, results.csv, metadata.jsonl, attempts.jsonl}`（纯离线只读）。`metadata.jsonl` 因断点续跑累计 1356 行，按 DOI 去重为 500 唯一：success 取"曾成功"并集，miss 取末次记录。
> 说明：本次仅刷新本 md，未改动任何 `.py` 或其它文件。

---

## 〇、新旧口径对比（为什么要刷新）

| 指标 | 旧 run（7/1 11:56） | 现行 run（7/1 13:40） | 变化 |
|---|---:|---:|---:|
| 输入 DOI | 500 | 500 | — |
| 成功 | 69（13.8%） | **410（82.0%）** | **+341 / +68.2pt** |
| MISS | 431 | **90** | **−341** |
| A_OA已定位·下载失败 | 86 | **73** | −13 |
| B_仅出版商链接 | 149 | **1** | **−148** |
| C_全网未定位 | 196 | **16** | **−180** |

**跃升主因**：新管线启用了 `websearch`（深度搜索引擎找 PDF）与 `publisher_oa`（ACS AuthorChoice / GoldOA 直取）。
- `websearch` 单独贡献 **260** 条成功（占全部成功的 63%）；
- `publisher_oa:acs-authorchoice` **52** + `acs-goldoa` **2** = 54，几乎清空旧 B 类（ACS 付费落地页 149 → 1）；
- 旧 C 类（Elsevier 全网零命中 196）经 websearch 兜底后降到 16。

---

## 一、总览（现行 82% 口径）

| 指标 | 数值 |
|---|---|
| 输入 DOI | 500 |
| 成功 | **410（82.0%）** |
| MISS | **90（18.0%）** |
| 成功来源（by_source，去重后累计） | websearch 260 / publisher_oa:acs-authorchoice 52 / openalex 30 / semantic_scholar 21 / unpaywall 16 / crossref 12 / europe_pmc 9 / openaire 7 / publisher_oa:acs-goldoa 2 / hal 1 |

> 口径说明：`summary.json` 的 `success_rate=0.79` 是**本次 run 口径**（processed 425 中 success 336）；叠加 `skipped_resume=74`（前序已成功、本次跳过）后**累计 success=410**，即 410/500 = 82%。磁盘 `pdfs/` 实有 **410** 个 PDF，交叉印证。

**核心发现（决定后续策略）：**

1. **90 条 MISS 的顶层 `error` 仍 100% 是 `no-downloadable-pdf`**；attempts 中**无任何** timeout / SSL / 熔断 / 403 / 429 / 连接错误。→ 剩余失败**不是网络/传输/风控问题**，而是"**定位到 URL 却拿不到可下载 PDF**"（落地页非 PDF / 反爬渲染 / 登录墙），或"**全网无候选**"。
2. 沿用旧文 **三分类 A/B/C**（按 attempts 中"哪类源定位到候选"派生）。交叉校验一致：`candidates>0`（找到候选 URL 但下载失败）= **74** = A73 + B1；`candidates=0`（全网无候选）= **16** = C16。
3. **剩余 MISS 高度集中在 Elsevier**：80/90（89%）为 `10.1016` 前缀（ScienceDirect）；其余 10 条分散在 Wiley/AIP/T&F/CSJ/JJAP。**Elsevier 已成为唯一系统性缺口。**

---

## 二、失败原因（派生三分类 = 精细化失败原因）

| 类 | 含义 | 条数 | 判据（attempts） | 可回收性 |
|---|---|---:|---|---|
| **A** | **OA/免费副本已定位、但下载失败** | **73** | 除 crossref 外 ≥1 个源 `n_candidates>0`（含 websearch / OA 聚合器 / publisher_oa） | 中：候选 URL 存在，卡在落地页非 PDF / 反爬渲染 |
| **B** | 仅有出版商链接（crossref） | **1** | 仅 crossref 命中候选，无任何免费源 | 中低：需替代免费源 |
| **C** | 全网未定位任何候选 | **16** | 所有源都无候选 | 低：几乎纯付费墙（全为 Elsevier） |

A 类"哪类源定位到候选"（可多源命中，计数可重叠）：**websearch 67** / semantic_scholar 8 / unpaywall 6 / openalex 6 / publisher_oa 4 / openaire 3。

> 与旧口径的关键差异：旧 A 多由 OA 聚合器（openalex/S2）定位、相对易下；**现行 A 的 67/73 由 websearch 定位**——即"搜索引擎找到疑似 PDF 链接但下载器没拿到真正 PDF"（多为 ResearchGate/机构库登录墙或 ScienceDirect 渲染页）。因此现行 A 的**平均可回收率低于旧 A**，需靠浏览器渲染 / wayback 才能进一步榨取。

---

## 三、分桶表（出版商/DOI 前缀 × 三分类）

| 出版商（前缀） | A_已定位 | B_仅出版商 | C_未定位 | MISS合计 |
|---|---:|---:|---:|---:|
| Elsevier (10.1016) | 64 | 0 | **16** | **80** |
| Wiley (10.1002) | 4 | 0 | 0 | 4 |
| AIP (10.1063) | 2 | 0 | 0 | 2 |
| Taylor&Francis (10.1080) | 1 | 1 | 0 | 2 |
| CSJ/ChemLett (10.1246) | 1 | 0 | 0 | 1 |
| JJAP/IOP (10.35848) | 1 | 0 | 0 | 1 |
| **合计** | **73** | **1** | **16** | **90** |

**读表要点：**
- **Elsevier 80 条（占 MISS 89%）= 唯一系统性痛点**：64 条 A 类（websearch/OA 定位到疑似副本却没下下来，多为 ScienceDirect 渲染 / 机构库墙）+ 16 条 C 类（全网零命中，纯付费墙）。
- 其余 **10 条分散**（Wiley 4 / AIP 2 / T&F 2 / CSJ 1 / JJAP 1），几乎全 A 类，是"逐条手工/浏览器"级别的长尾。
- 旧文的 ACS（76 B 类）、RSC（48）、MDPI（13 A 类）、PMC 等**已全部回收**，本轮不再出现。

---

## 四、可回收性分级与估计（保守；管线已用尽 websearch / OA / publisher_oa）

> 重要前提：剩余 90 条是**已经过 websearch + unpaywall/openalex/S2/openaire/europe_pmc + publisher_oa + 预印本 兜底后仍失败**的残差，故"易得"部分基本已被吃掉，以下估计从严。

### Tier 1 · 非 Elsevier A 类长尾 9 条（命中率 ~45% → ≈4 条，性价比最高）
物理类走 arXiv、化学类走 wayback / 作者自存稿，逐条浏览器渲染。
- 物理（arXiv 优先）：`10.35848/1347-4065/ad280f`(JJAP)、`10.1063/5.0228286`、`10.1063/1.1647050`(AIP)
- 化学（Wiley/CSJ/T&F，wayback + browser）：`10.1002/cctc.200900309`、`10.1002/asia.201600115`、`10.1002/cphc.201800122`、`10.1002/1099-0739(200012)14:12`、`10.1246/cl.180037`、`10.1080/0892702031000117135`

### Tier 2 · Elsevier A 类 64 条（命中率 ~25% → ≈16 条）
websearch 已定位候选 URL 但非可下载 PDF（ScienceDirect 渲染页 / ResearchGate 登录墙 / 机构库 HTML）。
手段：`browser_search`（渲染后抓 `pdf.sciencedirectassets.com` 真链）+ `wayback`（取存档 PDF）+ 机构库/作者自存稿深挖。
示例：`10.1016/j.jcou.2013.10.003`、`10.1016/j.rser.2020.110057`、`10.1016/j.jpowsour.2015.01.168`、`10.1016/j.apenergy.2013.08.047`。

### Tier 3 · Elsevier C 类 16 条（命中率 ~10% → ≈2 条，最低优先）
ScienceDirect 强付费墙 + 无任何免费索引，多为 2005–2020 老文或 2025 新文。
示例：`10.1016/j.jcat.2005.03.001`、`10.1016/s0021-9517(79)80027-5`、`10.1016/j.jece.2025.120071`。**建议低优先，先抽样验证再决定是否规模化。**

---

## 五、纯付费墙 vs 可回收（对应任务 a/b 结论，现行口径）

| 类别 | 估计条数 | 构成 |
|---|---:|---|
| **(a) 纯付费墙、免费几乎不可能** | **≈ 68** | Elsevier C 类 16（零命中）+ Elsevier A 类里渲染/墙无法突破的 ~50 + B 类 1 + 长尾少量 |
| **(b) 有合理免费路线、可再榨取** | **≈ 22** | 非 Elsevier A 长尾 ~4 + Elsevier A 经浏览器/wayback ~16 + C 类抽样 ~2 |

> 保守估计 **≈ 22 条**仍可回收（约占剩余 90 的 24%）；其中"较稳"的是**非 Elsevier 长尾 9 条**与 **Elsevier A 中可浏览器渲染的部分**。整体已接近**免费可得上限**：若再回收 ~22，则封顶约 **432/500 ≈ 86%**。

---

## 六、Top-3 可回收桶 + 推荐手段

1. **Elsevier A 类 64 条 → 回收 ≈16（最大绝对量）**：`browser_search` 渲染 ScienceDirect + `wayback`；单条命中率低但基数大。
2. **非 Elsevier A 类长尾 9 条 → 回收 ≈4（最稳、性价比最高）**：物理 arXiv、化学 wayback / 自存稿，逐条浏览器。
3. **Elsevier C 类 16 条 → 回收 ≈2（最低优先）**：抽样 `websearch` + `wayback`，验证命中率后再定是否规模化。

---

## 七、给总指挥的派活路由建议（source → bucket）

| 手段 | 目标桶 | 条数 | 建议人力 | 预期回收 |
|---|---|---:|---|---:|
| `browser_search`+`wayback`（arXiv 优先） | 非 Elsevier A 长尾 | 9 | 1 人（先清，最稳） | ~4 |
| `browser_search`（ScienceDirect 渲染）+`wayback` | Elsevier A | 64 | 1–2 人 | ~16 |
| `websearch`+`wayback`（低优先，先抽样） | Elsevier C | 16 | 抽样后定 | ~2 |

> 结论：batch6 已从 13.8% → 82%，**剩余 90 条中 89% 是 Elsevier ScienceDirect**，属"浏览器渲染 / wayback 才能再榨"的硬骨头；免费路线封顶约 86%。是否为最后 ~22 条投入浏览器人力，请总指挥按 ROI 决策。

---

## 附录 · 数据与方法

- 分类基于 `metadata.jsonl` 每条 `attempts[].source / n_candidates`；出版商由 DOI 前缀映射（`10.1016`→Elsevier 等）。
- `metadata.jsonl` 因断点续跑累计 1356 行，按 DOI 去重为 500 唯一：success 取"曾成功"并集（410），miss 取末次记录（90）。
- 免费/OA 源集合（定位到即计入 A）：websearch / unpaywall / openalex / doaj / europe_pmc / pmc / core / base / semantic_scholar / openaire / hal / osf / zenodo / scienceopen / publisher_oa / oa_button / preprints / wayback / publisher_direct；`crossref` 归为"出版商链接"（B）。
- `candidates>0`（有候选 URL 但下载失败）74 / `candidates=0`（无候选）16，与 A+B / C 完全对齐。
- 本批 attempts 无任何 timeout/SSL/熔断/403/429 记录，故无"传输失败"分桶；90 条顶层 error 均为 `no-downloadable-pdf`。
- 命中率为经验估计（含领域与出版商自存稿文化假设，且已扣除管线既用尽的 websearch/OA/publisher_oa），实际以浏览器渲染二次抽样为准。
