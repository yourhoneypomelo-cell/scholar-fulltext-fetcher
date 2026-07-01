# 检索成果 · batch4(语料B)真实成功率权威汇总

> 数据源:`out/batch4_p1..p5/{metadata.jsonl, pdfs/, summary.json}`,由 `tools/aggregate_batch4.py` 去重汇总,落盘 `out/batch4_aggregate.json`(`final=true`)。
> 生成方式:纯离线只读 + 生成(不联网、不改抓取源码)。基线对照:batch6 = 410/500 = 82.0%。

## 0. 一句话结论

**语料B(batch4,500 个 DOI,与 batch6 不相交)去重 union 真实成功 348/500 = 69.6%**(落盘 PDF 349 份);主力来源 `websearch`(263,占成功 75.6%)。同规模对照 batch6(410/500=82.0%):**成功率低 12.4 个百分点、计数少 62**。两批输入 DOI 交集为 0,属不同论文集,按"同规模真实成功率"口径可比,而非同输入差集。

## 1. 口径定义(为什么不能直接看 summary.json)

- **去重键**:规范化 DOI(优先 `doi` 字段,回退 `raw_input`;小写、去 `doi.org/`、`doi:` 前缀)。
- **真实成功(real success)**:某 DOI 至少有一条 `success==true` **且**其 `pdf_path` 对应文件**确实存在**于该分片 `pdfs/`。仅 metadata 声称成功但磁盘无 PDF 的**不计**。
- **union**:5 分片按 DOI 去重后,任一分片真实成功即计 1。
- **over-total** = union_real / 500(最终 KPI,分母=输入总数);**over-seen** = union_real / distinct_dois_seen(已处理口径)。
- **为何不用 summary.json**:pipeline 的 `summary.json` 只统计"本次运行 processed 的条数",断点续跑时历史成功不计入 `success`,会**低估**真实成功。典型:`batch4_p1` 最后一次是续跑,`summary.json` 仅 `success=2 / processed=3`,而其 `pdfs/` 实有 **70** 份。故权威口径以"metadata 去重 + PDF 落盘实证"为准。

## 2. 关键指标

| 指标 | 数值 |
|---|---|
| total_inputs(输入总数) | **500** |
| distinct DOI seen(已见去重 DOI) | **499** |
| union 真实成功 | **348** |
| success_rate **over-total**(/500) | **69.6%** |
| success_rate **over-seen**(/499) | **69.7%** |
| PDF 落盘(跨分片累计) | 349 |
| miss(over-total,500−348) | 152 |
| final | **true**(5 片 summary.json 齐备) |

> 说明:`distinct=499` 而非 500 —— 有 1 个输入(`10.1016/j.fuproc.2018.11.017`,Elsevier)在 `batch4_p4` 从未入库(大概率 Cloudflare/paywall miss)。PDF 落盘 349 比 union 348 多 1 —— `batch4_p3` 有 1 份孤儿 PDF(72 份磁盘文件 vs 71 条 success 行)。

## 3. 分片明细

| 分片 | metadata 行 | metadata success | PDF 落盘 | summary(success/processed) | 备注 |
|---|---|---|---|---|---|
| batch4_p1 | 101 | 70 | 70 | 2 / 3 | 末次为续跑,summary 严重低估;101 行含 1 条续跑重复 |
| batch4_p2 | 100 | 73 | 73 | 73 / 100 | 单次跑完 |
| batch4_p3 | 100 | 71 | 72 | 71 / 100 | 1 份孤儿 PDF |
| batch4_p4 | 99 | 66 | 66 | 66 / 99 | 1 条输入未入库(Elsevier DOI) |
| batch4_p5 | 100 | 68 | 68 | 68 / 100 | 单次跑完 |
| **union(去重)** | **500** | **348** | **349** | real=**348** | 各片 success 之和=348,无跨片重复命中 |

## 4. 成功来源分布(by_source_real,共 348)

| 来源 | 命中数 | 占成功比 |
|---|---|---|
| websearch | 263 | 75.6% |
| unpaywall | 35 | 10.1% |
| semantic_scholar | 16 | 4.6% |
| europe_pmc | 13 | 3.7% |
| publisher_oa:nature | 8 | 2.3% |
| crossref | 4 | 1.1% |
| zenodo | 3 | 0.9% |
| openaire | 3 | 0.9% |
| preprints | 2 | 0.6% |
| openalex | 1 | 0.3% |

**观察**:websearch 是绝对主力(占成功 3/4);结构化 OA 源(unpaywall+semantic_scholar+europe_pmc+crossref+openaire+openalex)合计 72,是第二梯队。

## 5. 失败主因(top_errors,去重后非真实成功项)

| 失败归因 | 计数 |
|---|---|
| download-failed:cloudflare-challenge(http-403) | 72 |
| no-candidates | 41 |
| download-failed:landing-no-embedded-pdf(text/html) | 11 + 6 = 17 |
| download-failed:http-403 | 8 |
| download-failed:no-response(retries-exhausted) | 5 |
| download-failed:http-202 | 2 |
| download-failed:http-412 | 2 |

**归并解读**:
- **403 族(Cloudflare/反爬)= 72 + 8 = 80**,是第一大失败根因 → 可回收方向:FlareSolverr / 无头浏览器过盾、Wayback 快照。
- **no-candidates = 41**:所有源零命中(冷门/纯订阅),属难回收的硬失败。
- **landing-no-embedded-pdf = 17**:定位到落地页但页面无可解析 PDF 链接 → 可回收方向:增强落地页解析 / 出版商直取。
- 其余 202/412/retries-exhausted 为少量临时或协议类失败。

## 6. 同规模对照 batch6(输入不相交)

| 维度 | batch4(语料B) | batch6 | 差异 |
|---|---|---|---|
| 真实成功 / 总输入 | 348 / 500 | 410 / 500 | **−62** |
| 成功率(over-total) | **69.6%** | 82.0% | **−12.4pp** |
| 输入 DOI 交集 | — | — | 0(disjoint) |
| 主力源 | websearch 263 | websearch 260 | 相当 |
| 出版商 OA | nature 8 | acs-authorchoice 52 + acs-goldoa 2 | batch6 富含 ACS 金/作者选 OA |
| openalex | 1 | 30 | batch6 openalex 命中远多 |

**差距归因(初判)**:两批 websearch 命中相当(263 vs 260),差距主要来自**结构化 OA 覆盖**——batch6 语料含大量 ACS Author-Choice(52)与 OpenAlex 命中(30),而 batch4 语料这两类稀少(nature 8、openalex 1)。即差异更多是**两批论文集的 OA 可得性不同**,而非流水线能力回退(两批输入不相交,不能按同输入差集解读)。

## 7. 可回收空间(粗估)

- **403 族 80 条**:接入 FlareSolverr/无头过盾后,乐观可回收其中相当比例 → 若回收 50–60%,约 +40~48,成功率可上探至 ~77–79%。
- **landing-no-embedded-pdf 17 条**:增强落地页/出版商直取解析,可回收部分。
- **no-candidates 41 条**:硬失败,回收成本高,优先级最低。
- 合计乐观可回收 ~50–65 条,理论上限接近 batch6 的 80% 区间。

---

*汇总脚本:`tools/aggregate_batch4.py`;权威 JSON:`out/batch4_aggregate.json`(final=true)。本页数字与该 JSON 完全一致。*
