# batch6 下载尝试(attempts.jsonl)详细错误分类与 HTTP 状态码分布

> 数据源:`out/batch6/attempts.jsonl`(事件流日志,只读分析,未改任何代码)。
> 分析人:谷歌学术人机认证-146 ｜ 日期:2026-07-01
> 事件构成:source=18304、download=1514、input=1193、resolved=1193、result=1187
> 注:该日志由一次仍在进行/可被追加的批次写入,本文为**某一时刻快照**(两次读取间 source 事件从 18248 增至 18304),绝对数字可能随批次继续小幅变动,但分布结论稳定。

---

## 〇、一页速览(TL;DR)

- **输入 1187 条 → 最终成功 272 条、失败 915 条(成功率 22.9%)**。
- **PDF 下载尝试 1514 次:成功 272、失败 1242(下载级成功率 18.0%)**。
- **最大失败面 = 403(832 次)**;最常见错误类别 = **HTTP 403(832 次)**。
- **成功主力源 = `websearch`(153/272,占成功 56%)**——免费网页搜索捞作者自存稿是本批次命中的最大贡献者,其次 `publisher_oa:acs-authorchoice`(33)、`openalex`(30)、`semantic_scholar`(21)。这实证了「免费搜索 + OA 源」组合的价值。
- 结论先行:失败几乎全部是**出版商付费墙 HTTP 403 / 落地页非 PDF**,而非人机验证(reCAPTCHA)。免费提升空间在**开放获取(OA)覆盖 + 自存稿检索**,而非「过人机」。

---

## 一、总尝试 / 成功 / 失败

| 维度 | 总数 | 成功 | 失败 | 成功率 |
|---|---|---|---|---|
| 输入最终结果(result) | 1187 | 272 | 915 | 22.9% |
| PDF 下载尝试(download) | 1514 | 272 | 1242 | 18.0% |
| 源候选查询(source) | 18304 | 1594 | 16710 | 8.7% |

> 说明:一条输入会先经多个「源」查候选(source),命中候选后才产生若干次「下载」(download);download 的成功率低,是因为大量候选是**出版商付费墙直链**,拿到 403 或非 PDF。

## 二、HTTP 状态码分布(下载尝试)

| 状态 | 次数 | 占下载尝试 |
|---|---|---|
| 200 | 272 | 18.0% |
| 403 | 832 | 55.0% |
| 404 | 1 | 0.1% |
| 非HTTP错误 | 345 | 22.8% |
| 400 | 34 | 2.2% |
| 202 | 21 | 1.4% |
| 405 | 6 | 0.4% |
| 401 | 3 | 0.2% |

## 三、错误类型分布(失败的下载尝试,按类别)

| 错误类别 | 次数 | 占失败 |
|---|---|---|
| HTTP 403 | 832 | 67.0% |
| 落地页无内嵌PDF | 237 | 19.1% |
| 无响应/重试耗尽/熔断 | 96 | 7.7% |
| HTTP 400 | 34 | 2.7% |
| HTTP 202 | 21 | 1.7% |
| 非PDF内容 | 12 | 1.0% |
| HTTP 405 | 6 | 0.5% |
| HTTP 401 | 3 | 0.2% |
| HTTP 404 | 1 | 0.1% |

## 四、按 URL 域名分布(下载尝试最多的域名 + 成功率)

| 域名 | 尝试 | 成功 | 成功率 |
|---|---|---|---|
| pubs.acs.org | 255 | 42 | 16.5% |
| pubs.rsc.org | 154 | 0 | 0.0% |
| www.researchgate.net | 99 | 0 | 0.0% |
| onlinelibrary.wiley.com | 80 | 0 | 0.0% |
| www.mdpi.com | 79 | 0 | 0.0% |
| link.springer.com | 79 | 11 | 13.9% |
| doi.org | 73 | 0 | 0.0% |
| europepmc.org | 63 | 3 | 4.8% |
| www.ncbi.nlm.nih.gov | 52 | 1 | 1.9% |
| api.wiley.com | 34 | 0 | 0.0% |
| www.nature.com | 24 | 18 | 75.0% |
| www.osti.gov | 21 | 6 | 28.6% |
| hdl.handle.net | 16 | 2 | 12.5% |
| doaj.org | 16 | 0 | 0.0% |
| www.cell.com | 15 | 3 | 20.0% |
| escholarship.org | 14 | 5 | 35.7% |
| iopscience.iop.org | 13 | 0 | 0.0% |
| www.sciencedirect.com | 13 | 0 | 0.0% |
| manuscript.elsevier.com | 13 | 0 | 0.0% |
| www.science.org | 13 | 3 | 23.1% |

**尝试≥10 次、成功率最低的域名(付费墙重灾区):**

| 域名 | 尝试 | 成功 | 成功率 |
|---|---|---|---|
| pubs.rsc.org | 154 | 0 | 0.0% |
| www.researchgate.net | 99 | 0 | 0.0% |
| onlinelibrary.wiley.com | 80 | 0 | 0.0% |
| www.mdpi.com | 79 | 0 | 0.0% |
| doi.org | 73 | 0 | 0.0% |
| api.wiley.com | 34 | 0 | 0.0% |
| doaj.org | 16 | 0 | 0.0% |
| iopscience.iop.org | 13 | 0 | 0.0% |
| www.sciencedirect.com | 13 | 0 | 0.0% |
| manuscript.elsevier.com | 13 | 0 | 0.0% |
| ars.els-cdn.com | 11 | 0 | 0.0% |
| pubs.aip.org | 11 | 0 | 0.0% |

## 五、成功下载详细信息

- 成功下载 **272** 个 PDF;大小:最小 17 KB,中位 1687 KB,均值 2579 KB,最大 19619 KB,总计 684.9 MB。

| 大小区间 | 个数 |
|---|---|
| <100KB | 9 |
| 100KB–500KB | 41 |
| 500KB–1MB | 45 |
| 1–5MB | 138 |
| >5MB | 39 |

**成功来源(source)分布:**

| 源 | 成功下载数 |
|---|---|
| websearch | 153 |
| publisher_oa:acs-authorchoice | 33 |
| openalex | 30 |
| semantic_scholar | 21 |
| crossref | 11 |
| unpaywall | 11 |
| openaire | 7 |
| europe_pmc | 3 |
| publisher_oa:acs-goldoa | 2 |
| hal | 1 |

**成功样例(源 / 大小 / URL,最多 15 条):**

- `crossref` · 783 KB · https://www.nature.com/articles/s41929-019-0266-y.pdf
- `openalex` · 3900 KB · https://www.nature.com/articles/s41467-021-27116-8.pdf
- `openalex` · 3606 KB · https://www.nature.com/articles/srep41207.pdf
- `europe_pmc` · 4899 KB · https://europepmc.org/articles/PMC9673058?pdf=render
- `crossref` · 109 KB · http://link.springer.com/content/pdf/10.1007/s10562-018-2542-x.pdf
- `europe_pmc` · 6553 KB · https://europepmc.org/articles/PMC12503360?pdf=render
- `openalex` · 1739 KB · https://www.frontiersin.org/articles/10.3389/fchem.2020.00709/pdf
- `openaire` · 1108 KB · https://tsukuba.repo.nii.ac.jp/record/38855/files/CPL_655%EF%BC%8F656.pdf
- `openalex` · 782 KB · https://www.nature.com/articles/s41467-017-00558-9.pdf
- `semantic_scholar` · 279 KB · https://publicatio.bibl.u-szeged.hu/4195/1/1984-chem.phys.lett.110-639.pdf
- `openalex` · 1837 KB · https://link.springer.com/content/pdf/10.1007/s12209-020-00246-8.pdf
- `semantic_scholar` · 837 KB · https://ora.ox.ac.uk/objects/uuid:d186f947-b7b2-4498-8aaa-484b4e31beb4/files/ma5ecf5bcb0c6ce5575550beadd2537b3
- `semantic_scholar` · 1438 KB · https://digital.csic.es/bitstream/10261/123797/1/4%20OHL%20no%20se%20si%20sirve%20esta%20version.pdf
- `openalex` · 5965 KB · https://upcommons.upc.edu/bitstream/2117/397420/1/1-s2.0-S1385894723048143-main.pdf
- `openalex` · 2041 KB · https://refubium.fu-berlin.de/handle/fub188/27635

## 六、最常见失败模式 Top 10(原始 error 串)

| # | error | 次数 |
|---|---|---|
| 1 | `http-403` | 832 |
| 2 | `landing-no-embedded-pdf(ct=text/html; charset=u)` | 163 |
| 3 | `no-response(retries-exhausted)` | 96 |
| 4 | `landing-no-embedded-pdf(ct=text/html;charset=ut)` | 61 |
| 5 | `http-400` | 34 |
| 6 | `http-202` | 21 |
| 7 | `not-pdf(head='ÿØÿà\x00\x10JFIF\x00\x01\x01\x01\x01ô')` | 8 |
| 8 | `landing-no-embedded-pdf(ct=text/html)` | 7 |
| 9 | `landing-no-embedded-pdf(ct=text/html; charset=")` | 6 |
| 10 | `http-405` | 6 |

---

## 七、附:源命中率 / 解析来源 / 最终失败原因

**各源候选命中率(source ok / 尝试,Top 15):**

| 源 | 尝试 | 命中(产候选) | 命中率 |
|---|---|---|---|
| snapshot | 1193 | 0 | 0.0% |
| unpaywall | 1193 | 108 | 9.1% |
| openalex | 1187 | 220 | 18.5% |
| europe_pmc | 1122 | 37 | 3.3% |
| semantic_scholar | 1119 | 185 | 16.5% |
| pmc | 1098 | 34 | 3.1% |
| core | 1098 | 0 | 0.0% |
| base | 1098 | 0 | 0.0% |
| crossref | 1098 | 493 | 44.9% |
| doaj | 1087 | 29 | 2.7% |
| openaire | 1087 | 73 | 6.7% |
| hal | 1079 | 1 | 0.1% |
| osf | 1078 | 0 | 0.0% |
| zenodo | 1078 | 0 | 0.0% |
| scienceopen | 1078 | 0 | 0.0% |

**标题→DOI 解析来源(resolved.via):** openalex=1187、none=6

**最终失败原因(result.error)Top 10:**

| # | error | 次数 |
|---|---|---|
| 1 | `no-downloadable-pdf` | 915 |

---

## 八、结论与改进建议

1. **失败主因是付费墙 HTTP 403 / 落地页非 PDF,不是人机验证**——与项目既有失败分析一致;「过人机」不是瓶颈。
2. **提升免费命中的杠杆**:扩大 OA 覆盖(BASE/OSF 等绿色 OA 源)、作者自存稿检索(websearch:DDG-HTTP + 浏览器 Bing)、落地页二次回收内嵌 PDF。
3. **付费墙高 403 域名**(见 §四低成功率表)基本无免费全文,建议对这些域名的直链**早降权/早跳过**,把预算让给 OA 源与自存稿检索。
4. **成功主力源**见 §五,应在源顺序中前置;低命中源可后置以省时。
