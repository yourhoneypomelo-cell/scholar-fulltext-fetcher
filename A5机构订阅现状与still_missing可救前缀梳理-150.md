# A5 机构订阅 / EZproxy / Cookie 持久化 — 现状盘点 + still_missing 可救前缀 Top10 与缺口（只读梳理）

> 交付：**谷歌学术人机认证-150**（worker）｜2026-07-02｜工单来源：总指挥 -144（改派自 -150）
> taskId=`task-75878107-369e-4279-b002-5555d0e1d9d9`
> 边界：**只读梳理，只新建本 1 份 md，未改任何 `.py` / 产物**。数据取自仓内已提交源码、文档与 `out/still_missing_shards/_shard_stats.json`（**628 条**，2026-07-02 11:48）。
> 承接：`机构订阅集成设计.md`、N4《选型2026-机构订阅Cookie与Profile持久化源码架构-对141建议》、《选型2026-A5机构订阅SSO浏览器接入实现者骨架-SciTeX参考》、`ROI-路线A-机构订阅代理`、`路线A-机构订阅实测Runbook`。

---

## 〇、TL;DR

- **代码地基已就绪、默认零副作用**：`http_client` 单点注入（`needs_institution_access` + `rewrite_url_for_proxy` 委托 `ezproxy.py` **双模式**改写 + `get()` 注入 `institution_cookie`）+ `publisher_direct` 直链源（`--institutional` 门控）+ CLI 四个开关，均带离线 selftest（`EZPROXY_OK` / `INSTITUTIONAL_OK` / `PUBLISHER_DIRECT_OK` / `HTTP_CLIENT_OK`）。
- **两处未落地（缺口）**：① **会话持久化层**（N4 `CookieStore` 四层 + 可见浏览器 SSO 登录 + 一次登录多篇 + `sources/institutional.py`）**仅有文档骨架**；② **凭据永久 gate**——用户明确无机构订阅凭据，路线A 已封存，代码就绪但永不联网实测，**ROI 严格 = 0**（待凭据到手照 runbook 3 步即可跑）。
- **still_missing 628 条中，A5 可救前缀 Top10 覆盖 ~593 条（94%）**，其中 **Elsevier(10.1016)+ACS(10.1021)+RSC(10.1039) 三社 = 536 条（85%）** 是主体。
- **两个可低成本收敛的模板缺口**：`publisher_direct` 对 **10.1006 / 10.1023 / 10.1134** 无直链模板（同族模板即可补），另有 ~20 条长尾小社前缀无模板。**注：补模板/建会话层是代码活，归 -153（N3/N4 归口）；本梳理只标缺口。**
- **一处命名不一致（实现前必须统一）**：SciTeX 骨架文档用的 `institutional_enabled/institutional_mode/ezproxy_host/ezproxy_base` 与**现行已落地** config 字段 `institutional/ezproxy_prefix/institution_cookie/institution_domains` **不是同一套**。

---

## 一、机构订阅 / EZproxy / Cookie 现有代码盘点（已落地）

| 能力 | 位置 | 现状 | selftest |
|---|---|---|---|
| 机构总开关 + 接入 publisher_direct 源顺序 | `cli.py --institutional` / `config.institutional` | ✅ 默认关；开启后把 `publisher_direct` 置于 OA 源后、websearch 前 | `cli` 内联 ⑤ |
| 域名分流（OA 豁免 + 白名单） | `http_client.needs_institution_access` + `_OPEN_ACCESS_HOSTS` | ✅ 未配凭据恒 False；OA/开放 API 域名永不改写、永不注 Cookie | `HTTP_CLIENT_OK` |
| EZproxy URL 改写（**双模式**） | `http_client.rewrite_url_for_proxy` → 延迟导入委托 `ezproxy.py` | ✅ **前缀式**（含 `://`/`=`/`/`）与**主机名改写式**（裸域名，点→`-`、连字符加倍）自动识别；显式端口/畸形 URL 保守恒等 | `EZPROXY_OK` |
| 机构会话 Cookie 注入 | `http_client.HttpClient.get()` | ✅ 仅对"需机构访问"的白名单域注入 `institution_cookie`；调用方显式 headers 优先；OA/第三方绝不注入 | `INSTITUTIONAL_OK` |
| 机构订阅直链源（DOI→PDF 模板） | `sources/publisher_direct.py` | ✅ `cfg.institutional=True` 才产候选；14 前缀 + Atypon 系；Elsevier/MDPI 经一次 Crossref 精确取路径 | `PUBLISHER_DIRECT_OK` |
| CLI 凭据入口 | `cli.py` | ✅ `--institutional` / `--ezproxy-prefix` / `--institution-cookie` / `--institution-domain`（可重复+逗号混用），Cookie/前缀默认取环境变量 `INSTITUTION_COOKIE`/`EZPROXY_PREFIX`，不留 shell 历史 | `cli` 内联 |
| 不产假阳纪律 | `download.py` `%PDF` 校验 + `selftest_institutional.py` | ✅ 无凭据打订阅直链回 401/403/登录页 HTML → 优雅判失败（`http-401`/`landing`/`not-pdf`）、不落盘、不记 success | `INSTITUTIONAL_OK` |

**config 现行字段（已落地，冻结）**：`institutional: bool` / `ezproxy_prefix: Optional[str]` / `institution_cookie: Optional[str]` / `institution_domains: List[str]`（`config.py` L95–100，默认全关/空）。

**要点**：整条流水线所有出网都汇聚到 `HttpClient.get()`，A5 只在这一个点接入，即同时覆盖"API 定位 + PDF 下载"，`download.py`/各源连接器零改动。

---

## 二、现有文档盘点（含 141 历史交付）

| 文档 | 归属 | 内容定位 |
|---|---|---|
| `机构订阅集成设计.md` | 141 系 | **实现规格**：三种接入（EZproxy 前缀/主机名、SSO/Shibboleth Cookie、IP 白名单）、`http_client` 单点注入、回退矩阵（默认逐字节一致）、TODO |
| `选型2026-机构订阅Cookie与Profile持久化源码架构-对141建议.md` | 142→141（**N4**） | **给 141 的落地建议**：scansci/instsci `CookieStore` 四层（JSON 持久化+过期校验 / 浏览器态 cookies+localStorage 双持久化 / per-publisher cookie / 长存会话 broker）+ Windows 平台补丁；P0/P1/P2 分期 |
| `选型2026-A5机构订阅SSO浏览器接入实现者骨架-SciTeX参考.md` | 承 177 | **骨架代码**：`sources/institutional.py`（BaseSource 子类，默认关）+ N4 CookieStore + §八 授权会话内 CDP 抓字节；代码活归 -153 |
| `选型2026-机构订阅与住宅代理方案.md`（**N3**） | 156 | scansci/instsci、WebVPN(100+ 高校 CAS)、CARSI、住宅代理选型 |
| `ROI-路线A-机构订阅代理.md` | 144 | **决策卡**：有机构 +350~400 篇（+35~40pp）、无机构 +0；最小路径 3~5 人日、完整 A5 ~2~3 人周；bulk 风控/AUP 红线 |
| `路线A-机构订阅实测Runbook-凭据到手3步.md` | — | **凭据到手照做**：Cookie 导出 how-to + 3 条冒烟 + 20 条 Elsevier + 放量命令（**已归档 gate**） |

---

## 三、still_missing 中 A5 可救前缀 Top10（分母 628，2026-07-02 11:48）

> "A5 可救" = 在**用户拥有合法机构订阅**前提下，经 EZproxy/CARSI/SSO/校园 IP 正门可合法取回的**订阅/付费墙**缺口（区别于纯 OA 免费桶）。墙型标注取自 `_shard_stats.json` 的 `roi` 字段与 N4/144 分片结论。

| # | 前缀 | 出版商 | 条数 | 占比 | 墙型 / 免费到顶结论 | A5 可救性 | publisher_direct 模板 |
|---:|---|---|---:|---:|---|---|---|
| 1 | **10.1016** | Elsevier(ScienceDirect) | **374** | 59.6% | IP/登录墙（**非 CF**）；browser_search 0/10、wayback 0/12 到顶 | ★★★ A5 主力（唯一合法解） | ✅ 经 Crossref PII → `/pdfft` |
| 2 | **10.1021** | ACS | **95** | 15.1% | 混：**纯订阅 403** + CF403(OA 子集) | ★★★ A5 救订阅部分；CF-OA 子集 FS 已可救 | ✅ `/doi/pdf/{doi}` |
| 3 | **10.1039** | RSC | **67** | 10.7% | **JA3 绑 CF + 订阅**；curl_cffi 回放 403 | ★★☆ 需 **A5 授权会话 + 路线B 页内直下**叠加 | ✅ 推年份/刊码 `articlepdf` |
| 4 | **10.1002** | Wiley | **21** | 3.3% | CF(Just-a-moment) + 订阅 | ★★☆ A5 + FS | ✅ `/doi/pdf`+`/pdfdirect` |
| 5 | **10.1007** | Springer | **14** | 2.2% | 常规链路（link.springer.com） | ★★★ A5 直取 | ✅ `content/pdf/{doi}.pdf` |
| 6 | **10.1023** | Springer / Kluwer | **6** | 1.0% | 常规链路 | ★★★ A5 直取 | ❌ **缺口**（同 springer 模板可补） |
| 7 | **10.1006** | Elsevier（旧刊） | **5** | 0.8% | 订阅 | ★★★ A5 | ❌ **缺口**（`_elsevier` 仅对 10.1016 触发） |
| 8 | **10.1166** | ASP（J. Nanosci. Nanotechnol.） | **4** | 0.6% | 订阅小社 | ★★☆ A5 | ❌ 缺口（需新模板） |
| 9 | **10.1246** | CSJ（Chem. Lett.，现 OUP 托管） | **4** | 0.6% | 订阅 | ★★☆ A5 | ❌ 缺口（需新模板） |
| 10 | **10.1134** | Pleiades / Springer | **3** | 0.5% | 订阅 | ★★☆ A5 | ❌ **缺口**（同 springer 模板可补） |
| — | 并列 | 10.1080 T&F（3）/ 10.1063 AIP（3） | 6 | — | T&F=CF桶+订阅（✅ tandf 模板）；AIP=CF桶 Just-a-moment（FS 可救，❌ 无模板） | ★★☆ | 见注 |

**Top10 合计 ≈ 593 / 628（94%）**；三大社（Elsevier+ACS+RSC）= **536（85%）**。

**非 A5（免费桶，勿计入 A5 ROI）**：`10.3390` MDPI **7 条**为 **OA**，应走常规免费源回收；其余长尾含 Hindawi(10.1155) 等亦偏 OA。

---

## 四、缺口清单（按优先级）

### 缺口 1 — 会话持久化层未实现（P0→P3，代码活归 -153）
现有仅"**静态单 `institution_cookie` 串**注入 + EZproxy 双模式改写 + `publisher_direct` 直链（gated）"。**缺**（N4/SciTeX 文档已给骨架，均未落地）：
- `CookieStore`（JSON 持久化 + 过期校验 + 注入会话）
- 可见浏览器 SSO 登录 `open_login_browser`（人工过 CARSI/WebVPN/OpenAthens，**不自动填凭据**）
- per-publisher cookie 文件 + merge/dedup + localStorage 持久化
- 一次登录多篇会话复用（PersistentBrowser / broker）→ **Elsevier 374 条放量的前提**（否则逐条静态 Cookie 会过期）
- `sources/institutional.py`（授权会话内 CDP 抓字节，机构站多在 CF/JS 后）
- Windows 平台补丁（`cloakbrowser_compat`，本项目 Windows 必带）

### 缺口 2 — 凭据永久 gate（决定性，非工程可解）
用户明确**无机构订阅凭据** → 路线A 已封存归档，代码就绪但**永不联网实测**，ROI 严格 = 0。凭据到手后照 `路线A-...Runbook` 3 步（导 Cookie → 3 条冒烟 → 20 条 Elsevier → 放量）即可。

### 缺口 3 — publisher_direct 模板覆盖 vs still_missing 前缀分布
- **可低成本补（同族模板即可，~14 条）**：`10.1023`/`10.1134`（复用 `link.springer.com/content/pdf/{doi}.pdf`）、`10.1006`（把 `_elsevier` 的 Crossref-PII 触发从"仅 10.1016"扩到含 10.1006）。
- **需新模板（长尾 ~20 条）**：`10.1166`(ASP/ingenta)、`10.1246`(CSJ→OUP)、`10.1063`/`10.1116`(AIP)、`10.1088`/`10.1070`/`10.1149`(IOP)、`10.1109`(IEEE)、`10.1093`(OUP)、`10.1017`(Cambridge)、`10.1107`(IUCr)、`10.1515`(De Gruyter)、`10.1595`(Johnson Matthey)、中日俄小社(`10.11862`/`10.3866`/`10.7503`/`10.26599` 等)。

### 缺口 4 — config 命名不一致（实现 sources/institutional.py 前必须统一）
| 现行已落地（`config.py`） | SciTeX 骨架文档所设 |
|---|---|
| `institutional` / `ezproxy_prefix` / `institution_cookie` / `institution_domains` | `institutional_enabled` / `institutional_mode` / `ezproxy_host` / `ezproxy_base` / `institutional_cookie_store` |

→ 建议**以现行 4 字段为准**扩展，避免双套配置；`institutional_mode`/`cookie_store` 作**新增**字段并入，勿重命名既有字段（会破 selftest 与 `api._make_config`）。

### 现状更新（原文档已过时之处）
- `机构订阅集成设计.md` 称"主机名改写式 TODO / 本设计不改 cli.py"——**均已完成**：主机名式落在 `ezproxy.py`、CLI 四开关已在 `cli.py`。

---

## 五、给总指挥（-144）的收口建议

1. **无凭据现状下**：A5 代码地基**无需再动**（默认关、零副作用、selftest 齐全），路线A 保持归档，ROI=0；把回收重心放在免费桶（MDPI 10.3390 等 OA）与路线B（CF-OA 页内直下）。
2. **若要"零凭据也能推进的低风险工程"**：仅"缺口 3 可低成本补"（10.1006/10.1023/10.1134 三前缀共 14 条模板）+ "缺口 4 命名统一"值得排给 **-153**——即使无凭据，直链构造正确性可离线 selftest 验证，凭据到手即生效。
3. **有凭据那天**：直接照 `路线A-...Runbook` 3 步，先 20 条 Elsevier 冒烟，≥70% 再放量整分片（`-c 2 --per-host-interval 1.0`，防 bulk 风控）。

**合规红线（不变）**：仅对本人机构确有订阅权限的资源、经正门等效人工登录取用；默认关、低并发、凭据绝不入 git/日志/产物；不破付费墙本身、不引 Sci-Hub。

---

## 六、来源
- 源码：`fulltext_fetcher/{http_client.py, ezproxy.py, config.py, cli.py, selftest_institutional.py, sources/publisher_direct.py, download.py}`。
- 文档：`机构订阅集成设计.md`、`选型2026-机构订阅Cookie与Profile持久化源码架构-对141建议.md`、`选型2026-A5机构订阅SSO浏览器接入实现者骨架-SciTeX参考.md`、`选型2026-机构订阅与住宅代理方案.md`、`ROI-路线A-机构订阅代理.md`、`路线A-机构订阅实测Runbook-凭据到手3步.md`。
- 数据：`out/still_missing_shards/_shard_stats.json`（628 条，2026-07-02 11:48）。

---
*核验 2026-07-02｜-150｜工单「P1 机构订阅 A5 层现状与 still_missing 可救前缀梳理」（taskId=`task-75878107-369e-4279-b002-5555d0e1d9d9`）｜结论：A5 HTTP 地基+直链源+CLI 已就绪且默认零副作用，缺会话持久化层与凭据（永久 gate、ROI=0）；still_missing 628 中 A5 可救 Top10 覆盖 594≈94%（Elsevier+ACS+RSC=536/85%）；模板缺口 10.1006/10.1023/10.1134 可低成本补、另有 ~20 长尾前缀需新模板，config 命名需统一——代码活归 -153。仅新建本 1 份 md，未改任何 .py。*
