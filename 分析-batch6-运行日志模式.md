# batch6 运行日志分析：运行时错误模式与系统性问题

> 数据源：`out/batch6/run.log`（约 1689 条日志记录，全部为 `[INFO]`/`[WARNING]`，**无 `[ERROR]` 级别**）
> 分析范围：只读分析，不改动代码。所有计数以 UTF-8 逐行统计为准；**成功/失败以「去重后的 DOI」为准**（日志行数含多次重试，会高于 DOI 数）。

---

## 0. 结论速览（TL;DR）

1. **这份 run.log 其实是同一批 500 条 DOI 的「三轮断点续跑」拼接**，每轮追加更多源：
   - 第 1 轮（17 个 OA/元数据源）→ 成功 **69/500 (14%)**
   - 第 2 轮（+`publisher_oa`,`oa_button`）→ 仅 **+5**（累计 74，14.8%）
   - 第 3 轮（+`websearch`,`wayback`+浏览器伪装）→ 冲到 **273/500 (54.6%)**，但**日志末尾未见「完成」行，第 3 轮疑似被中断/尚未跑完**。
2. **标准 OA/元数据源对本批 DOI 命中率极低（~15%）**；真正把覆盖率翻倍的是 **网页搜索兜底 + `curl_cffi` 浏览器指纹伪装 + sci-hub**——代价是**极高延迟**（websearch 平均 69s、最长 **501s**）。
3. **最严重的系统性问题：第 1 轮 11:36–11:40 出现 `SSLEOFError`（EOF in violation of protocol）集中爆发**，几分钟内横扫十余个互不相关的 API 主机，直接把 `api.unpaywall.org` 等核心源打到**熔断**，压低了第 1 轮产出。此形态高度指向**本地网络/代理/中间盒或并发过高**，而非各远端同时故障。
4. **PDF 校验存在可观测性缺口**：919 条 MISS **全部**记为单一原因 `no-downloadable-pdf`，校验失败被静默并入 MISS，日志中**没有**「文件太小/魔数不匹配/落地页冒充」等显式记录。但仍抓到 **1 例「落地页冒充」漏网**（把一份宣传单页当成论文判为 OK）。

---

## 1. 运行时间线

### 1.1 整体
| 项 | 值 |
|---|---|
| 首条日志 | `11:27:10` |
| 末条日志 | `13:10:15` |
| 墙钟总时长 | **约 1 小时 43 分（≈103 min）** |
| 输入规模 | 500 条 DOI（去重后 union=500） |
| 最终成功（去重 DOI） | **273 / 500 = 54.6%** |
| 最终失败（仅 MISS 未 OK） | **227 / 500 = 45.4%** |
| 「先 MISS 后 OK」被救回的 DOI | **204**（占成功数的 74.7%） |

> 说明：第 3 轮结尾没有 `完成。成功 x/x` 汇总行，末条为一条 `[MISS]`，因此 54.6% 是**日志截止时的中间状态**，实际最终值可能更高。

### 1.2 分轮明细（同一批 DOI 的三次断点续跑）
| 轮次 | 时间段 | 时长 | 并发 | 关键新增源 | 本轮成功 | 本轮吞吐 |
|---|---|---|---|---|---|---|
| **Run 1** | 11:27:10–11:48:30 | 1279.9s (≈21.3min) | **8** | 17 个 OA/元数据源（unpaywall/openalex/crossref/europe_pmc/pmc/core/base/…） | **69/500 (14%)** | ~23.5 尝试/min（仅 ~3.2 成功/min） |
| **Run 2** | 11:51:46–12:22:39 | 1852.9s (≈30.9min) | 6 | `+publisher_oa, +oa_button` | **5/431 (1%)** → 累计 74 | ~13.9 尝试/min |
| **Run 3** | 12:24:22–13:10:15+ | ≈46min（**未见完成行**） | 6 | `+websearch, +wayback`（并启用 `curl_cffi` 伪装/sci-hub 兜底） | 本段 OK ≈202 → 累计 **273** | ~9.3 尝试/min（最慢但产出最高） |

**处理速度（DOI/分钟）**：整体净产出 ≈ **273 成功 / 103 min ≈ 2.65 成功 DOI/min**；若按尝试计，Run 1 最快（~23.5/min，几乎全 MISS），Run 3 最慢（~9.3/min，但贡献了绝大多数成功）。**吞吐随「兜底强度」上升而急剧下降**。

### 1.3 成功来源分布（去重前，[OK] 行）
| 来源 | 次数 | 说明 |
|---|---|---|
| **websearch** | **153** | 网页搜索兜底，**贡献最大**，但延迟最高 |
| publisher_oa:acs-authorchoice | 33 | ACS 开放获取（配合 `curl_cffi` 伪装取正文） |
| openalex | 30 | |
| semantic_scholar | 21 | |
| unpaywall | 11 | |
| crossref | 11 | |
| openaire | 7 | |
| europe_pmc | 3 | |
| publisher_oa:acs-goldoa | 2 | |
| hal | 1 | |

> **websearch 延迟统计**（154 条）：平均 **68.7s**、最短 30.8s、**最长 500.9s**。这是 Run 3 吞吐骤降的直接原因。

---

## 2. 错误 / 警告统计

**级别分布**：`[INFO]` 1320 条、`[WARNING]` **369** 条、`[ERROR]` **0** 条。
> 管线没有 ERROR 级别输出——所有异常都降级为 WARNING，配合重试/熔断/降级源消化，属于「柔性失败」设计。

### 2.1 WARNING 分类（共 369）
| 类别 | 次数 | 含义 |
|---|---|---|
| **HTTP 5xx/429 → 退避重试** | **220** | 服务端错误/限速触发指数退避 |
| **请求异常（连接层）** | **~81** | SSL/连接被断/超时/DNS 等 |
| **SSL 握手失败 → 退避重试** | **48** | 多为证书问题（含自签名证书站点） |
| **host 熔断（连续失败跳过）** | **18** | 见 §3 |
| 未提供真实邮箱（启动告警） | 1 | Unpaywall 可能返回 422，建议加 `--email` |

### 2.2 「请求异常（连接层）」子类型（约 79–81 条）
| 异常类型 | 次数 | 典型信息 |
|---|---|---|
| **RemoteDisconnected** | 26 | `Remote end closed connection without response`（多为 PMC/NCBI） |
| **ReadTimeout** | 21 | `Read timed out (read timeout=30.0)` |
| **SSLEOFError** | 17 | `EOF occurred in violation of protocol (_ssl.c:992)`（**集中爆发，见 §5.1**） |
| **DNS 解析失败** | 11 | `getaddrinfo failed [Errno 11002]`（域名失效/不可解析） |
| **SSLCertVerifyFailed** | 4 | `certificate verify failed`（含 self-signed） |

> SSL 相关问题合计 ≈ **69 次**（17 EOF + 4 证书校验 + 48 握手失败退避），是本次运行的一大类噪声来源。

---

## 3. 熔断器（circuit breaker）触发记录

规则：`host 连续 N 次连接失败 → 本次运行内跳过（熔断）`（Run 1/2 阈值=2 次，Run 3 阈值=3 次）。共 **18 次**，涉及 15 个主机：

| 主机 | 熔断次数 | 备注 |
|---|---|---|
| **europepmc.org** | 3 | EuropePMC，跨三轮反复熔断 |
| burjcdigital.urjc.es | 2 | 机构库 |
| manuscript.elsevier.com | 2 | Elsevier 投稿系统（证书/断连） |
| **api.unpaywall.org** | 1 | ⚠️ **核心 OA 源被熔断**（11:39:29，Run 1） |
| **www.ebi.ac.uk** | 1 | EuropePMC REST 基础设施 |
| ri.conicet.gov.ar / oatao.univ-toulouse.fr / apps.dtic.mil / auetd.auburn.edu / dspace.univ-bouira.dz:8080 / www.electronicsandbooks.com / ijprajournal.com / www.navyreserve.navy.mil | 各 1 | 机构库 / 兜底站点 |
| **dd-x-0-fe-01.fe.cpd.local:4000** | 1 | ⚠️ **内网/本地主机名**（`*.local:4000`）——疑似代理/快照服务，出现在源列表里但连不上 |

**要点**：
- **`api.unpaywall.org` 在 Run 1 被熔断** → 该轮后续整批跳过主 OA 源，是 Run 1 仅 14% 的直接放大因素之一。
- **EuropePMC 全家桶（europepmc.org + www.ebi.ac.uk）反复熔断**（≥4 次），说明该源在本次网络环境下基本不可用。
- `dd-x-0-fe-01.fe.cpd.local:4000` 是内网地址，出现连接失败——需确认 `snapshot` 源/代理配置是否指向了不可达的本地服务。

---

## 4. 限速 / 退避事件

**退避重试总计 ≈ 268 次** = HTTP 编码退避 **220** + SSL 握手失败退避 **48**。采用指数退避（1s→2s→4s→8s，第 1–4 次）。

### 4.1 按 HTTP 状态码（220 次）
| 状态码 | 次数 | 性质 |
|---|---|---|
| **429** | 60 | 纯限速（Too Many Requests），主要 `zenodo.org/api`、Crossref 等 API |
| 502 | 56 | 网关错误 |
| 504 | 41 | 网关超时（**Run 3 的 sci-hub.box 大量 504**） |
| 500 | 40 | 服务端错误（如 `europepmc.org/...?pdf=render` 反复 500） |
| 503 | 23 | 服务不可用 |

### 4.2 按被退避的目标主机（Top）
| 主机 | 退避次数 | 说明 |
|---|---|---|
| **api.crossref.org** | 54 | Crossref API 被大量限速/5xx |
| **www.rsc.org** | 52 | 英国皇家化学会（出版商正文） |
| **sci-hub.box** | 32 | ⚠️ sci-hub 兜底源不稳定，全 504（Run 3） |
| europepmc.org | 24 | `?pdf=render` 反复 500 |
| www.ebi.ac.uk | 20 | |
| **www.sai-yin.com** | 16 | ⚠️ websearch 挖到的低信任镜像站 |
| www.wangxing-lab.com | 8 | ⚠️ **自签名证书**站点 |
| madridge.org / manuscript.elsevier.com / www.chem.pku.edu.cn / doi.org / hdl.handle.net | 各 8 | |

> **观察**：退避热点集中在 (a) 元数据 API（Crossref/EuropePMC/Zenodo，429/5xx）与 (b) Run 3 兜底源（sci-hub、各类实验室/镜像站）。前者靠降并发+退避可缓解；后者是低质量来源固有的不稳定。

---

## 5. 系统性问题识别（集中爆发型）

### 5.1 【最关键】`SSLEOFError` 多主机同时爆发（Run 1，11:36–11:40）
- **现象**：4 分钟内 17 次 `EOF occurred in violation of protocol (_ssl.c:992)`，**同时命中** `api.openaire.eu`、`www.nature.com`、`api.base-search.net`、`www.ebi.ac.uk`、`api.unpaywall.org`、`api.semanticscholar.org`、`pubs.acs.org`、`api.osf.io`、`zenodo.org`、`api.openalex.org` 等**十余个互不相关的主机**。
- **研判**：这么多不同厂商的 TLS 端点**在同一时间窗一起 EOF**，几乎不可能是各远端同时故障；典型成因是**本地侧**——网络抖动 / 代理或防火墙中间盒重置连接 / 并发=8 打满了某个 TLS 中间层。
- **后果**：连续失败被判定为「host 故障」→ 触发 `api.unpaywall.org` 等**熔断**→ Run 1 主源大面积失效 → 仅 14%。
- **佐证**：Run 2/3 把并发降到 6，SSLEOFError 明显减少（后续 17 次里大部分在 Run 1）。

### 5.2 标准 OA/元数据源对本批命中率结构性偏低
- Run 1（17 个 OA 源）14% → Run 2（+publisher_oa/oa_button）**仅 +1%**。说明**本批 DOI 大多不在标准 OA 索引中**（多为付费/闭源），靠「正规源」天花板就在 ~15%。
- 直接推论：覆盖率的提升几乎完全依赖 §5.3 的兜底层。

### 5.3 覆盖率靠「网页兜底 + 浏览器伪装」，但延迟成本极高
- Run 3 通过 `websearch`(153 OK) + `curl_cffi impersonate`(57 次命中，主要 `pubs.acs.org`) + `wayback`/`sci-hub` 把成功率从 15% 抬到 **55%**。
- **代价**：websearch 平均 68.7s / 最长 501s；Run 3 吞吐掉到 ~9 DOI/min。**用时间换覆盖率**。

### 5.4 兜底源与镜像站不稳定 / 低信任
- `sci-hub.box` 32×504；websearch 引入的 `www.sai-yin.com`、`www.wangxing-lab.com`（自签名证书）、`www.chem.pku.edu.cn`、`madridge.org` 等大量退避/证书错误；11 次 DNS `getaddrinfo failed`（如 `www.navyreserve.navy.mil`）——搜索结果里混入了失效/不可解析域名。

### 5.5 反爬 / 人机认证：采用「主动伪装」规避，未触发显式拦截
- 全程 **HTTP 403 = 0、无 `cloudflare`/`captcha`/`人机`/`Just a moment` 字样**。
- 说明管线用 **`curl_cffi` 浏览器指纹伪装（impersonate）主动绕过反爬**（57 次命中，集中在 ACS `pubs.acs.org/doi/pdf/...`），因此**没有触发**显式的人机验证/封禁——这正是本管线应对「人机认证」的核心手段，目前**有效**。

---

## 6. PDF 校验失败表现（含重要发现与缺口）

### 6.1 可观测性缺口：校验失败被静默并入 MISS
- **919 条 `[MISS]` 全部是同一个原因 `no-downloadable-pdf`**（去重 431 个 DOI）。
- 日志中**完全没有**「文件太小 / 魔数（`%PDF-`）不匹配 / 落地页冒充 / content-type=text/html / 字节数」等**任何 PDF 内容校验的显式记录**。
- **影响**：无法从日志区分「压根没找到 PDF」与「下到了文件但校验不通过（HTML 伪装/损坏/过小）」。两类问题被折叠成同一个 MISS，掩盖了真实的校验失败率。**建议在下载后补记校验日志**（HTTP content-type、首 8 字节 magic、文件大小、页数）。

### 6.2 抓到 1 例「落地页冒充」漏网（假阳性 / 误判为 OK）
- `12:18:55 落地页解析命中内嵌 PDF: https://radygenomics.org/wp-content/uploads/2022/03/Project-Baby-Deer_UpdateandEcoSavings_Flyer.pdf`
- `12:18:55 [OK] 10.3390/children12040429 -> unpaywall`
- **问题**：把一份 **"省钱宣传单页"（Flyer）** 当成论文正文，**通过校验判为 OK**。这就是「落地页冒充 / 内嵌 PDF 错配」却被校验放过的典型案例（与 §6.1 的"无内容校验"互为因果）。
- **附带线索**：该 DOI（MDPI *Children* 期刊）与本批（催化/CO₂ 主题）明显不符，疑似**输入 DOI 污染**或 **OA 记录错配**。

### 6.3 SI（支撑材料）错取风险
- 54 条「落地页解析命中内嵌 PDF」里 **34 条指向 ACS `.../suppl_file/..._si_001.pdf`（Supporting Information，而非正文）**。
- 所幸这些通常随后由 `curl_cffi impersonate` 命中正文 `/doi/pdf/...` 并以 `publisher_oa:acs-authorchoice` 记 OK，因此 SI 链接更像是**中间检测步骤**；但**日志无法确认最终落盘的是正文还是 SI**——建议对 ACS 这批做抽样核对（正文页数 vs SI）。

### 6.4 低信任来源的正确性风险
- 自签名证书站点（`www.wangxing-lab.com`）、各类实验室/镜像站（`sai-yin.com` 等）被 websearch 引入。这些 PDF 的「是否为目标论文、是否完整」风险最高，而当前**缺少内容校验日志**兜底（见 §6.1）。

---

## 7. 修复 / 优化建议（按优先级）

1. **定位 Run 1 的 SSLEOFError 根因（P0）**：核查本地网络/代理/防火墙与 TLS 中间盒；把默认并发从 8 降到 ≤6（Run 2/3 已验证有效），并对「短时间多主机同时 EOF」做与"远端故障"不同的处理（**不应据此熔断核心 API**）。
2. **补齐 PDF 内容校验日志（P0）**：下载后记录 content-type / magic(`%PDF-`) / 文件大小 / 页数，并把校验失败与 `no-downloadable-pdf` 分开计数；对 §6.2 这类"落地页单页/HTML 伪装"增加拦截规则。
3. **熔断策略细化（P1）**：区分「核心 OA API（unpaywall/openalex/crossref/europepmc）」与「兜底站点」——核心 API 熔断阈值应更宽或支持中途恢复，避免一次网络抖动废掉整轮主源。
4. **裁剪无效源（P1）**：`publisher_oa`/`oa_button` 本批仅 +5，`snapshot` 指向的内网 `*.local:4000` 不可达——评估是否保留或修复配置。
5. **websearch 提速（P1）**：平均 69s/最长 501s 是主要吞吐瓶颈；建议加超时上限、结果域名黑名单（失效/低信任站）、并对 DNS 不可解析域名快速跳过。
6. **输入清洗（P2）**：核查 `10.3390/children12040429` 一类与主题不符的 DOI，排查输入污染。

---

*报告基于 `out/batch6/run.log` 静态分析；计数含 UTF-8 逐行统计与 DOI 去重，个别行数因日志内含换行可能有 ±1% 出入，成功/失败均以去重 DOI 为准。*
