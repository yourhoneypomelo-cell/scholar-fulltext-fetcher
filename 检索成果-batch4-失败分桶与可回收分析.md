# 检索成果 · batch4（语料B）· 失败分桶与可回收分析

> 分析者：谷歌学术人机认证-146（worker）｜任务：task-15063ea6-0a73-4507-8fec-a49b16d2d5d6
> 数据口径：`out/batch4_p1..p5/{metadata.jsonl, attempts.jsonl}` + `out/batch4_aggregate.json`（纯离线只读）
> 说明：本文件为**新建的唯一 md**，未改动任何 `.py` 或其它 md。

---

## 一、总览

| 指标 | 数值 |
|---|---|
| 输入 DOI | 500 |
| 已处理（去重 DOI） | 499（缺 1 条） |
| **真实成功**（metadata success + pdfs/ 落盘实证） | **348（69.7%）** |
| **MISS** | **151（30.3%）** |
| 成功来源（by_source） | websearch **263** / unpaywall 35 / semantic_scholar 16 / europe_pmc 13 / publisher_oa:nature 8 / crossref 4 / zenodo 3 / openaire 3 / preprints 2 / openalex 1 |

**与 batch6 同规模对比**（两批输入 DOI **不相交**，见 `batch4_aggregate.json`）：

| 批 | 真实成功 | 成功率 |
|---|---:|---:|
| batch4（语料B） | 348/500 | **69.6%** |
| batch6 | 410/500 | 82.0% |
| 差 | −62 | −12.4 pp |

**核心发现（决定后续策略）：**

1. batch4 已成功 348 条中 **websearch 占 75.6%（263/348）**，说明语料B 的免费 PDF 大量来自搜索引擎/web 深挖，与 batch6 以 API 聚合器为主的成功结构不同。
2. 151 条 MISS 的顶层 `error` **高度集中于反爬/下载环节**，而非「全网零候选」：
   - **cloudflare-challenge(http-403) 72 条（47.7%）** ← 最大单桶
   - no-candidates 41 条（27.2%）
   - landing-no-embedded-pdf 18 条（11.9%）
   - http-403 8 / no-response 4 / 其它 8
3. 与 batch6 不同，batch4 的 MISS **多数是「已定位候选、下载被 Cloudflare 拦」**，而非 batch6 那种「431 条全 no-downloadable-pdf + 196 条全网零命中」格局。
4. `attempts.jsonl` 下载事件层：1194 次 download 中 **846 次失败**，其中 **519 次 cloudflare-challenge**（含同一 DOI 多源重试），涉及 **264 个唯一 DOI**（含已成功后其它源试探性失败）。

---

## 二、失败原因分布（result 事件 + download 事件）

### 2.1 result 事件（151 条 MISS，每 DOI 终态 1 条）

| 失败原因 | 条数 | 占 MISS |
|---|---:|---:|
| **cloudflare-challenge(http-403)** | **72** | **47.7%** |
| **no-candidates** | **41** | **27.2%** |
| landing-no-embedded-pdf（各 charset 变体合计） | **18** | **11.9%** |
| http-403 | 8 | 5.3% |
| no-response(retries-exhausted) | 4 | 2.6% |
| straggler-timeout | 2 | 1.3% |
| http-202 / http-412 / http-405 / http-418 | 各 1–2 | 余量 |

### 2.2 download 事件（1194 次，含多源重试）

| 失败原因 | 次数 | 备注 |
|---|---:|---|
| **cloudflare-challenge(http-403)** | **519** | RSC/ACS/Elsevier/Wiley 均高发 |
| landing-no-embedded-pdf | 154 | 落地页 HTML 无嵌入 PDF |
| http-403 | 58 | 非 Cloudflare 403 |
| no-response(retries-exhausted) | 48 | |
| http-202 / http-400 / http-405 等 | 余量 | |

### 2.3 Cloudflare 按出版商（download 失败事件计数，含重试）

| 出版商 | Cloudflare download 失败次数 |
|---|---:|
| Elsevier (10.1016) | 208 |
| ACS (10.1021) | 155 |
| Wiley (10.1002) | 47 |
| **RSC (10.1039)** | **67** |
| 其它 | 42 |

> **RSC Cloudflare 量化**：download 层 67 次失败 / **45 个唯一 DOI** 曾触发 Cloudflare；在 151 条 MISS 中 **5 个 RSC DOI** 终态仍为 cloudflare（其余 40 个 RSC DOI 经 websearch 等源已成功绕过）。

---

## 三、三分类 A/B/C（派生失败原因 × 出版商交叉）

判据与 batch6 对齐：`attempts[]` 中 OA 源（unpaywall/openalex/S2/europe_pmc/pmc/doaj/openaire/websearch/publisher_oa/wayback 等）≥1 个 `ok=true` → **A**；仅 crossref `ok=true` → **B**；全无 → **C**。

| 类 | 含义 | 条数 | 占 MISS | 可回收性 |
|---|---|---:|---:|---|
| **A** | OA/免费副本已定位、下载失败 | **101** | **66.9%** | **最高**：卡在 Cloudflare/落地页/403 |
| **B** | 仅有出版商链接 | **8** | 5.3% | 中：预印本/websearch |
| **C** | 全网未定位候选 | **42** | 27.8% | 低：深度 websearch |

交叉校验：`candidates>0` = **109** ≈ A101 + B8；`candidates=0` = **42** = C42。✓

A 类里「哪类源定位到副本」（可有多源命中）：websearch 69 / publisher_oa 26 / semantic_scholar 23 / unpaywall 23 / openalex 23 / openaire 16 / europe_pmc 2 / doaj 2 / pmc 1 / hal 1 / wayback 1。

### 分桶表（出版商/DOI 前缀 × 三分类）

| 出版商（前缀） | A_OA已定位 | B_仅出版商链接 | C_全网未定位 | MISS 合计 |
|---|---:|---:|---:|---:|
| **Elsevier (10.1016)** | **71** | 0 | **39** | **110** |
| ACS (10.1021) | 12 | 0 | 1 | 13 |
| Wiley (10.1002) | 7 | 0 | 0 | 7 |
| Springer (10.1007) | 3 | 0 | 0 | 3 |
| 其它/未知 | 5 | 1 | 2 | 8 |
| MDPI (10.3390) | 2 | 0 | 0 | 2 |
| **RSC (10.1039)** | 1 | **4** | 0 | **5** |
| AmSciPub / Taylor&Francis / IOP | 0 | 各 1 | 0 | 3 |
| **合计** | **101** | **8** | **42** | **151** |

**读表要点：**

- **Elsevier 110 条占 MISS 73%**：71 条 A 类（有免费候选、多被 Cloudflare/403 拦）+ 39 条 C 类（no-candidates，纯检索失败）。
- **RSC 仅 5 条 MISS**（语料B 中 RSC 占比低）：4 B + 1 A；Cloudflare 在 download 层高频但 websearch 已帮大部分 RSC 成功。
- **ACS 13 条 MISS**：12 A + 1 C，几乎全是「有候选、下载失败」型。
- batch4 与 batch6 结构差异极大：batch6 MISS 中 B 类 149 + C 类 196 为主；batch4 MISS **以 A 类 Cloudflare 为主**。

### MISS 终态 error × 出版商（Top）

| 出版商 | 主要终态 error | 条数 |
|---|---|---:|
| Elsevier | cloudflare-challenge | 44 |
| Elsevier | no-candidates | 39 |
| ACS | cloudflare-challenge | 12 |
| Wiley | cloudflare-challenge | 7 |
| RSC | cloudflare-challenge | 4 |
| Elsevier | landing-no-embedded-pdf / http-403 / no-response | 各 1–6 |

---

## 四、可回收性分级与估计

> 估计 = 桶内条数 × 经验命中率。batch4 已启用 websearch 且 263 条成功，剩余 MISS 多为「最后一公里」反爬问题，可回收率高于 batch6 同类桶。

### Tier 0 · 近乎必得（floor ≈ 79–85 条，命中率 90–95%）

**Cloudflare 拦截 + A 类已定位 = 79 条**（86 个 MISS DOI 曾触发 Cloudflare，其中 79 为 A 类）

- 推荐：**FlareSolverr** 过 Cloudflare → 重试已定位 URL（unpaywall/websearch/publisher_oa 给出的 PDF 链）
- 子桶：Elsevier A+CF **≈55** / ACS **≈12** / Wiley **≈7** / RSC **≈4** / 其它 **≈3**
- 估计回收：**≈71–75 条**（90% 命中率；RSC 需 FlareSolverr 专用桶）

附加近乎必得：

- **MDPI A 2 条** → publisher_oa 直取 + 真实 UA → **≈2**
- **PMC/EuropePMC A 2 条** → 直取 NIH 托管 PDF → **≈2**

**Tier 0 floor 合计 ≈ 75–79 条**

### Tier 1 · A 类非 Cloudflare（≈22 条，命中率 ~65% → ≈14 条）

landing-no-embedded-pdf 11 + http-403 8 + no-response 4 等。

- 推荐：`browser_search`（渲染后抓 PDF）+ `wayback` + `publisher_oa` 直取
- 估计回收：**≈14 条**

### Tier 2 · B 类（8 条，命中率 ~35% → ≈3 条）

RSC 4 + AmSciPub/T&F/IOP 各 1。

- 推荐：`websearch` 深挖 + `preprints` + `wayback`；RSC B 类 4 条加 **FlareSolverr**
- 估计回收：**≈3 条**

### Tier 3 · C 类（42 条，命中率 ~12% → ≈5 条）

主体 **Elsevier 39 条 no-candidates**。

- 推荐：低优先 `websearch`（Scholar/ResearchGate/机构库）+ `preprints`；先抽样 10 条验命中率再规模化
- 估计回收：**≈5 条**

---

## 五、纯付费墙 vs 可回收

| 类别 | 估计条数 | 构成 |
|---|---:|---|
| **(a) 纯检索失败、免费路线极窄** | **≈ 35–40** | Elsevier C 39 + ACS C 1 + 其它 C 2 |
| **(b) 有合理免费路线、这次漏在下载/反爬** | **≈ 90–97（约 60–64%）** | A 类 ~85 + B 类 ~3 + C 类少量 ~5 |

> 保守点估计 **≈ 92 条可回收**（151 × 61%）；高置信「稳拿」底线 **≈ 75–79 条**（Tier 0 Cloudflare + MDPI/PMC）。

与 batch6 对比：batch6 可回收 ~125/431（29%）；batch4 可回收 ~92/151（**61%**）——因 batch4 已成功率高、MISS 更「近成功」。

---

## 六、Top-3 可回收桶 + 推荐手段

1. **A 类 + Cloudflare 拦截 79 条 → 回收 ≈71（最高价值）**
   - 手段：**FlareSolverr**（RSC/ACS/Elsevier/Wiley 均需）→ 重试已定位 PDF URL → `publisher_oa` 直取 → `browser_search` 兜底
   - 子桶：Elsevier 55 / ACS 12 / Wiley 7 / **RSC 4（FlareSolverr 专用桶）**
   - 这是 batch4 与 batch6 最大差异点：batch6 无 cloudflare 记录，batch4 近半 MISS 为此因

2. **Elsevier A 类（非 no-candidates）71 条 → 回收 ≈50（含上桶重叠，独立看 landing/403 子集 ≈16）**
   - 手段：FlareSolverr + `browser_search` + `wayback` + ScienceDirect 落地页 PDF 链解析
   - 其中 44 条终态 cloudflare + 6 landing-no-pdf + 6 http-403

3. **Elsevier C 类 no-candidates 39 条 → 回收 ≈5（基数大、单条低）**
   - 手段：`websearch` 深挖（Scholar/ResearchGate/机构库）+ `preprints`；建议抽样验证后再规模化
   - 备选第 4 桶：**ACS A 类 12 条 → ≈11**，FlareSolverr + ChemRxiv 预印本复核

---

## 七、给总指挥的派活路由建议

| 手段 | 目标桶 | 条数 | 建议人力 | 预期回收 |
|---|---|---:|---|---:|
| **FlareSolverr** + 重试已定位 URL | A 类 Cloudflare（全出版商，**RSC 单独桶**） | 79 | 1 人（优先） | ~71 |
| `browser_search` + `wayback` | A 类 landing/403 非 CF | 22 | 1 人 | ~14 |
| `websearch` 深挖（低优先、先抽样） | Elsevier C 类 | 39 | 抽样后定 | ~5 |
| `preprints` + `websearch` | B 类 RSC/其它 | 8 | 0.5 人 | ~3 |

**优先序建议**：先跑 FlareSolverr 清 A+CF 79 条（近乎白捡）→ browser/wayback 清 A 余量 → 最后才动 C 类 39 条。

---

## 附录 · 数据与方法

- 5 分片 `batch4_p1..p5` metadata.jsonl 按 DOI 去重；「真实成功」= success=true 且 pdf_path 对应文件存在于该分片 `pdfs/`（与 `tools/aggregate_batch4.py` 口径一致）。
- 分类基于 `metadata.jsonl` 每条 `attempts[].source/ok`；出版商由 DOI 前缀映射（`10.1016`→Elsevier 等）。
- result/download 事件来自 `attempts.jsonl`；download 层计数含同一 DOI 多源重试，result 层为终态每 DOI 1 条。
- Cloudflare 桶：`error` 含 `cloudflare-challenge`；RSC 专指 DOI 前缀 `10.1039`。
- 命中率为经验估计（含 batch4 已 websearch 成功 263 条这一事实），实际以 FlareSolverr 重跑抽样为准。
