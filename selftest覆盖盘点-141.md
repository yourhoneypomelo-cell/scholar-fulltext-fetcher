# selftest 覆盖盘点-141

> 任务:[质量·只读] selftest / 测试覆盖齐全性盘点。
> 边界:**只读盘点,不改任何代码**。本文仅给「现状 + 缺口清单 + 建议」,不落任何补丁。
> 方法(-141):静态盘点 `run_all_selftests.py` 聚合入口 + 全包 `def _selftest`/`*_OK` 令牌交叉核对(未真跑子进程)。
> 复核(-161):在本机 Python 3.11.2 **真跑** `python run_all_selftests.py`(离线全量),补齐实测证据——**发现 P0 阻断,详见「零」**。

---

## 零、复核更新(-161 实测)——⚠️ P0 阻断:`compileall` FAIL(实测发现 → ✅ 已闭环)

> -161 波在本机(Python 3.11.2)**真跑**了 `python run_all_selftests.py`(离线全量),补齐 -141 静态盘点缺失的实测证据。

**实测汇总**:`SUMMARY: PASS=44  FAIL=1  SKIP=2  (total=47)` → **退出码 = 1(非绿)**。

- ✅ **44 个离线 CHECKS 全 PASS**:逐条命中各自 `*_OK`,**实证** -141「登记 vs 真实打印一一对应、无死条目」的静态结论(含 `render_fetch` 169.9s、`institutional` 131.7s 两个较慢项,余多为 1s 级)。
- ⏭️ **2 SKIP**(符合预期,非缺陷):`flaresolverr_nodriver`(联网,需 `RUN_ONLINE_SELFTESTS=1`)、`regress_qc_union_189`(数据回归,需 `RUN_DATA_REGRESS=1`)。
- ❌ **1 FAIL —— `compileall`(P0 阻断)**:

```
[FAIL] compileall  exit=1 :: *** Error compiling 'fulltext_fetcher\institutional\ezproxy_login.py'
  File "fulltext_fetcher\institutional\ezproxy_login.py", line 323
    </parameter>
    ^
SyntaxError: invalid syntax
```

**根因**:`fulltext_fetcher/institutional/ezproxy_login.py` 文件尾(**第 323–325 行**)被误写入工具调用的 XML 残标:

```
322 |     print("EZPROXY_LOGIN_OK")
323 | </parameter>
324 | </invoke>
325 | </output>
```

这三行非合法 Python → 触发 `SyntaxError`,连带全包 `compileall -q fulltext_fetcher` 失败,使整个 `run_all_selftests.py` **退出码 = 1**。

**性质与归属(重要)**:
- 该文件 **git 未跟踪(`??`)**,属 A5/institutional 子包**在建件**(与 `auth_session.py`/`cookie_store.py`/`credential_store.py`/`route_b_bridge.py`/`selftest_a5_framework.py` 同批未跟踪),owner 为 route-B/A5 属主,**疑为落盘时误带工具标记**。
- **CI 现状**:`.github/workflows/ci.yml` 只跑**已提交**码,而此文件未提交 → **CI 暂仍绿**;但**本地 `run_all_selftests.py` 已红**,且**一旦此文件被提交,CI/compileall 将立即转红**。属"提交即爆"的隐雷。
- **影响面**:① 本地 compileall 红;② `import fulltext_fetcher.institutional.ezproxy_login` 直接崩;③ 该文件自带的 `EZPROXY_LOGIN_OK` selftest 因编不过而无法运行。
- **修复动作极小**(删末尾 3 行 XML 残标即恢复),但**本任务边界=只读,未落任何修改**;须由 ezproxy_login owner 处置以免与其在建改动冲突。已按 **P0** 上报总指挥。
- **处置状态(-161 收尾 → ✅ 已闭环)**:总指挥授权 **-142** 删除该 3 行残标;**-142 已达 `run_all_selftests PASS=45 / FAIL=0`(-141 确认)→ G0 闭环**。G6「把 `EZPROXY_LOGIN_OK` 登记进 CHECKS」**已被采纳**,纳入「全局程序化 + selftest 覆盖」改进项(backlog `bl-662fd6ad`),随 `run_all` 改造由质量秘书 **-158** 统筹落地。

---

## 一、结论摘要(TL;DR)

1. **聚合器自洽**:`run_all_selftests.py` 登记 **44 个离线 CHECKS + compileall**、**1 个联网(默认 SKIP)**、**1 个数据回归(默认 SKIP)**;逐一核对——**每个登记项都确有对应模块打印其 `*_OK` 令牌**,不存在「登记了却没自检」的死条目。**(-161 实测:44 条离线 CHECKS 全 PASS,证实无死条目;但 `compileall` 因 `ezproxy_login.py` 语法错误 FAIL,整体退出码=1,详见「零」/G0。该 P0 现已闭环:-142 修复后 `PASS=45 / FAIL=0`,-141 确认。)**
2. **关键路径全覆盖**:下载/损坏判定、**内容 QC 门(门①②③④⑤)**、文件名标准化、各主力 source、各 publisher adapter,均有离线 selftest。
3. **本波 5 项新改 → 4 项已补 selftest,1 项部分缺**:
   - Wiley pdfdirect URL bug、openalex(key 透传 + QC 豁免 + 代理豁免)、QC 门位置/判定、run_all 日志/明细输出 → **均已补离线 selftest**。
   - **FS-shim(`tools/flaresolverr_nodriver.py`)→ 只有联网 selftest(默认 SKIP),缺离线纯逻辑自检**;派生的 `fs_shim_mainloop_141.py`(仓根未跟踪临时件)**无自检、未登记**。这是本波唯一与「新改」直接相关的 selftest 缺口。
4. **次要缺口(非本波)**:`sources/repositories.py`、`sources/scihub.py`、`sources/snapshot_source.py` 三个已注册源无 selftest;`snapshot.py`、`ingest.py`、`api.py` 等包内模块无独立自检(部分被间接覆盖)。

---

## 二、聚合入口盘点(`run_all_selftests.py`)

约定:各模块 selftest「不联网、打印一行 `<MOD>_OK`」;runner 以子进程 `python -m <mod>` 触发,rc==0 且含 `*_OK` 记 PASS;模块不存在记 SKIP;存在但失败记 FAIL。

- **离线 CHECKS(44 条)**:`run_all_selftests.py:46-102`
- **联网 ONLINE_CHECKS(1 条,`RUN_ONLINE_SELFTESTS=1` 才跑)**:`run_all_selftests.py:108-110`
- **数据回归 DATA_REGRESS_CHECKS(1 条,`RUN_DATA_REGRESS=1` 才跑)**:`run_all_selftests.py:116-118`
- **compileall 全包字节码编译**(语法级健康检查,失败=真失败):`run_all_selftests.py:227`
- **CI 接线**:`.github/workflows/ci.yml` 在 py3.9/3.10/3.11/3.12 上 `compileall` + `python run_all_selftests.py`,仅装 `requests`(故意不装 `openpyxl`,验证零可选依赖路径)。

**核对结果:登记 vs 真实 `*_OK` 打印一一对应(无死条目)。** 抽样对照:

| 登记名 | 模块 | 令牌 | 打印处 |
|---|---|---|---|
| download | `fulltext_fetcher/download.py` | `DOWNLOAD_OK` | `download.py:2377` |
| publisher_direct | `sources/publisher_direct.py` | `PUBLISHER_DIRECT_OK` | `publisher_direct.py:425` |
| publisher_oa | `sources/publisher_oa.py` | `PUBLISHER_OA_OK` | `publisher_oa.py:346` |
| publisher_adapter | `publisher_adapter.py` | `PUBLISHER_ADAPTER_OK` | `publisher_adapter.py:242` |
| render_fetch | `render_fetch.py` | `RENDER_OK`(内含 `RENDER_BYTES_OK`) | `render_fetch.py:1138 / 1317` |
| a5_framework | `institutional/selftest_a5_framework.py` | `A5_FRAMEWORK_OK` | `selftest_a5_framework.py:92` |
| institutional | `selftest_institutional.py` | `INSTITUTIONAL_OK` | `selftest_institutional.py:191` |
| run_all | `run_all.py` | `RUN_ALL_OK` | `run_all.py:657`(-161 复核;-141 时为 :631,代码增改致行漂) |
| build_coverage | `tools/build_coverage.py` | `COVERAGE_OK` | `build_coverage.py:1244` |
| scholar.naming | `scholar/naming.py` | `NAMING_OK` | `naming.py:296` |

(其余 34 条离线项同样逐一命中,略。)

---

## 三、关键路径覆盖矩阵

| 关键路径 | 承载模块 | selftest 覆盖 | 证据 |
|---|---|---|---|
| **下载 + 损坏判定** | `download.py` `pdf_defect`/`download_pdf` | ✅ | `download.py:1532` 起:①截断/空/非PDF/防误杀×3、①b D2 深度完整性(缺库降级)、②端到端合法落盘 vs 截断不落盘 |
| **内容 QC 门(门①②③④⑤)** | `download.py` `_content_qc_gate`/`_content_qc_verdict`/`_content_qc_non_article_reject`/`_source_needs_content_qc` | ✅ | `download.py:2047-2066` 门籍(websearch/wayback/browser_search/landing 进门;unpaywall/**openalex**/crossref/snapshot 豁免;acs-authorchoice 特判);`:2070` verdict;`:2285-2333` 端到端门④⑤非正文(SI→uncertain/hard-reject);`:2256` 依赖缺失 fail-closed |
| **QC 并集门回归** | `tools/regress_qc_union_189.py` | ✅(opt-in) | 重放 189 条同域错论文 + 34 条 title 假匹配;`REGRESS_UNION_189_OK`;默认 SKIP,改 QC 判定后须 `RUN_DATA_REGRESS=1` 跑 |
| **文件名标准化** | `scholar/naming.py` | ✅ | `NAMING_OK`(`naming.py:296`);核心下载侧文件名由 `download._selftest②` 端到端落盘断言 + `run_all._selftest` `_pdf_basename` 覆盖 |
| **各 source(主力)** | aggregators/green_oa/oa_button/preprints/wayback/websearch/free_adapters/publisher_oa/publisher_direct | ✅ | 均在 CHECKS 且各有 `*_OK` |
| **各 source(缺)** | `repositories.py`/`scihub.py`/`snapshot_source.py` | ❌ | 见 §五 缺口 G4 |
| **publisher adapter** | `publisher_adapter.py` + `publisher_direct.py` 前缀模板 | ✅ | `PUBLISHER_ADAPTER_OK`;前缀路由(Nature/Science/PNAS/ACS/SAGE/T&F/Springer/**Wiley**/RSC/APS/Elsevier/MDPI)在 `publisher_direct.py:309-423` |
| **机构订阅(路线A)** | `http_client`(改写/白名单)+ `selftest_institutional` | ✅ | `INSTITUTIONAL_OK`:零副作用/白名单分流/EZproxy 改写/不产假阳(401、登录页)/源门 |
| **A5 框架层** | `institutional/{auth_session,cookie_store,credential_store,route_b_bridge}.py` | ✅ | 由 `selftest_a5_framework.py:9-93` 全量导入并跑(凭据加载/redact/CookieStore 往返/AuthSession/route-B plan/SSO 启发式/bootstrap 不覆盖 CLI) |
| **路线B 字节直下** | `render_fetch.py` `_selftest_bytes` | ✅ | `render_fetch.py:1137` 由 `_selftest()` 连带调用 → 进默认回归;含 RSC governor(-165)`_looks_governor`/landing 转换、A5 route_b_bridge 注入 mock |
| **北极星主流程** | `run_all.py` | ✅ | 去重/续跑过滤/route-B 透传/openalex_key 透传/明细输出/日志渲染 |

---

## 四、本波新改 × selftest 落地核对(任务核心)

| 本波新改 | selftest 是否已补 | 证据(file:line) |
|---|---|---|
| **Wiley pdfdirect URL bug 修复** | ✅ 已补 | `publisher_direct._selftest③`:`publisher_direct.py:319-327` —— 常规 Wiley `pdf`+`pdfdirect` 双候选;**legacy DOI**(`10.1002/1099-0739(200012)14:12<836::AID-AOC97>3.0.CO;2-C`)经 `_wiley_doi_path` 编码后断言 `pdfdirect/{enc}`、`pdf/{enc}` 均在,且 `":12:" not in url`(正是本 bug 的回归钉) |
| **openalex** | ✅ 已补(3 处) | ①key 透传:`run_all._selftest⑥` `run_all.py:562-575`(CLI `--openalex-key` + env `OPENALEX_KEY` → Config);②QC 豁免(DOI-keyed 源):`download.py:2053`;③代理改写豁免(OA 域恒等):`selftest_institutional.py:152` |
| **QC 门位置/判定权重** | ✅ 已补 | 门籍与「门位置」(force 在 route-B `download.py:1115/1318`;非正文 reject 在【判 match 之前】先跑 `download.py:677/691`)+ verdict 判定:`download._selftest⑦` `download.py:2047-2333`;并集门另有 `regress_qc_union_189`(opt-in) |
| **FS-shim(免 Docker FlareSolverr)** | ⚠️ 部分缺 | `tools/flaresolverr_nodriver.py:283` `selftest()` **仅联网**(起 headless + /v1 真解 example.com),登记在 ONLINE_CHECKS(`run_all_selftests.py:108-110`)**默认 SKIP**;**无离线纯逻辑自检**(Handler /v1 JSON 契约、cache TTL、health body 等可离线 mock 的部分未覆盖)。`fs_shim_mainloop_141.py`(仓根 `??` 未跟踪临时件)**无自检、未登记** |
| **run_all 日志/明细输出** | ✅ 已补 | `run_all._selftest⑦` `run_all.py:577-629`(`reason_bucket`/`_pdf_basename`/`build_detail_rows`/`write_detail_tsv` 列数恒定不串列);`⑧` `run_all.py:631+` `_render_page_lines`(run_all.log 快照与屏幕同源,QC 开/关双分支) |

**小结:5 项中 4 项已补齐离线 selftest;唯 FS-shim 仅有联网自检(默认 SKIP),离线回归里对其零覆盖。**

---

## 五、缺口清单(按优先级)

> 均为**建议**(本任务只读,不落补丁)。优先级:P1=本波相关/易回归、P2=有真实纯逻辑值得钉、P3=薄封装/低价值。

- **G0(P0·阻断)· `institutional/ezproxy_login.py` 语法错误 → `compileall` FAIL**(-161 实测新增,详见「零」)
  - 现状:文件尾 323–325 行误写入工具调用 XML 残标(`</parameter>`/`</invoke>`/`</output>`)→ `SyntaxError` → 全包 `compileall` 失败、`run_all_selftests.py` 退出码=1。文件 **git 未跟踪(在建件)**,CI 暂绿但"提交即爆"。
  - 建议:owner 删末尾 3 行残标即可恢复(修复极小);**本任务只读未落改**,已按 P0 上报总指挥,交由 ezproxy_login/route-B 属主处置以免冲突。
  - **处置(-161 收尾)→ ✅ 已闭环**:**-142** 已删末 3 行残标并达 `run_all_selftests PASS=45 / FAIL=0`(-141 确认)。

- **G1(P1)· FS-shim 缺离线自检** — `tools/flaresolverr_nodriver.py`
  - 现状:只有联网 `selftest()`(默认 SKIP),CI 离线回归完全不触碰其逻辑。
  - 建议:补一个不起浏览器的 `_selftest_offline()`(注入 mock `Solver`),离线校验 `Handler` 对 `/`(health body 含 `FlareSolverr is ready`)与 `/v1`(`request.get` → `status=ok` + `solution.response/userAgent` 契约)的路由与 JSON 组装、以及 `cache_ttl` 到期逻辑;打印如 `FLARESOLVERR_NODRIVER_OFFLINE_OK` 并登记进离线 CHECKS。

- **G2(P1/流程)· `fs_shim_mainloop_141.py` 定位未决** — 仓根未跟踪临时件
  - 现状:无自检、未登记;为 Windows `[Errno 22]` 的主线程事件循环变体启动器,importlib 复用原 shim 逻辑。
  - 建议:先按「工作树三分类收口」决定 **归档 vs 提升为正式模块**;若提升,其增量(`_load_shim` + 主线程 loop 装配)需补最小离线自检。

- **G3(P2)· 已注册源无 selftest** — `sources/repositories.py`(arXiv/EuropePMC/PMC/bioRxiv·medRxiv/DOAJ/Zenodo/HAL)、`sources/scihub.py`(`_EMBED_RE` HTML 抽链)、`sources/snapshot_source.py`
  - 现状:均 `@register` 为正式源,含可离线断言的纯逻辑(URL 构造 / 正则抽链 / DB 命中→候选映射),但无 `_selftest`、未进 CHECKS。
  - 建议:各补离线 selftest(`repositories` 验各源 URL 模板与 `applicable` 分流;`scihub` 验 `_EMBED_RE` 抽链 + 默认关不产候选;`snapshot_source` 用内存/临时 SQLite 验命中映射)。

- **G4(P3)· 包内模块无独立自检** — `snapshot.py`(`lookup` 被 `snapshot_source` 依赖,仅间接覆盖)、`ingest.py`(有 `main()` 无自检)、`api.py`、`config.py`(`apply_route_b` 已被 cli/run_all 覆盖)、`logsetup.py`、`models.py`
  - 建议:`snapshot.py`/`ingest.py` 值得补(SQLite 读写往返);其余薄封装/数据类可暂缓。

- **G5(观察项,非缺口)· openalex_key 的 CLI 层断言在 run_all 而非 cli._selftest**
  - `cli._selftest`(`cli.py:281-355`)未直接断言 `--openalex-key`,但同一 `build_parser()` 已由 `run_all._selftest⑥` 覆盖,判为**已覆盖**,无需重复。

- **G6(P2)· 「已存在但未登记」的 selftest(自检写了却不进 CI)**(-161 实测新增)
  - `institutional/ezproxy_login.py`:自带 **5 场景**离线自检(`EZPROXY_LOGIN_OK`:多跳登录抓 cookie / 超时不抓 / 无 login-url 明确报错 / `open_login_browser` 端到端路由 / 非 EZproxy 分支 `NotImplementedError`),但 `run_all_selftests.py` CHECKS **未登记** → CI 从不运行(且当前因 G0 语法错误连编译都过不了)。`工程卫生收口预案-141.md:51` 已独立标注同一缺口。建议:**先修 G0**,再把它登记为离线 CHECKS 项(`EZPROXY_LOGIN_OK`)。
  - `tools/{shard_cf_by_publisher,dedup_recover_input,title_probe}.py`:均有 `def _selftest` 但未登记(tooling 层,P3;如要纳入可另开一组 tools CHECKS)。
  - **处置(-161 收尾)**:登记 `EZPROXY_LOGIN_OK` 进 CHECKS **已被总指挥采纳**,纳入「全局程序化 + selftest 覆盖」改进项(backlog `bl-662fd6ad`,由质量秘书 **-158** 统筹),随 `run_all` 改造落地(tools/ 三项 P3 暂缓)。

---

## 六、可直接执行的验证命令(供总指挥/后续波复跑)

```bash
# 全量离线回归(CI 同款)
python run_all_selftests.py

# 联网自检(FS-shim 现有唯一自检,需浏览器 + 出网)
RUN_ONLINE_SELFTESTS=1 python run_all_selftests.py

# QC 并集门数据回归(改 QC 判定后必跑)
RUN_DATA_REGRESS=1 python run_all_selftests.py

# 本波新改点单测
python -m fulltext_fetcher.sources.publisher_direct   # Wiley/legacy → PUBLISHER_DIRECT_OK
python run_all.py --selftest                          # openalex_key + 明细/日志 → RUN_ALL_OK
python -m fulltext_fetcher.download                   # QC 门 → DOWNLOAD_OK
python -m fulltext_fetcher.render_fetch --selftest    # route-B 字节直下 → RENDER_OK(含 RENDER_BYTES_OK)
```

---

## 七、附:全模块 selftest 索引(离线 CHECKS,44 条)

landing`SELFTEST_OK` · cli`CLI_OK` · resolve`RESOLVE_OK` · http_client`HTTP_CLIENT_OK` · aggregators`AGGREGATORS_OK` · report`REPORT_OK` · download`DOWNLOAD_OK` · pipeline`PIPELINE_OK` · publisher_adapter`PUBLISHER_ADAPTER_OK` · green_oa`GREEN_OA_OK` · zotero`ZOTERO_OK` · snapshot_bootstrap`SNAPSHOT_BOOTSTRAP_OK` · citations`CITATIONS_OK` · scholar_serpapi`SCHOLAR_SERPAPI_OK` · selftest_e2e`E2E_OK` · scholar.{models,config,logsetup,query,serp,proxy,captcha,fetcher,download,naming,pipeline,e2e} · aio`AIO_OK` · render_fetch`RENDER_OK` · free_adapters`FREE_ADAPTERS_OK` · websearch`WEBSEARCH_OK` · oa_button`OA_BUTTON_OK` · publisher_oa`PUBLISHER_OA_OK` · publisher_direct`PUBLISHER_DIRECT_OK` · institutional`INSTITUTIONAL_OK` · a5_framework`A5_FRAMEWORK_OK` · ezproxy`EZPROXY_OK` · wayback`WAYBACK_OK` · preprints`PREPRINTS_OK` · browser_search`BROWSER_SEARCH_OK` · flaresolverr`FLARESOLVERR_OK` · bench_free_methods`BENCH_OK` · run_all`RUN_ALL_OK` · build_coverage`COVERAGE_OK`

**联网(默认 SKIP)**:flaresolverr_nodriver`FLARESOLVERR_NODRIVER_OK` ·
**数据回归(默认 SKIP)**:regress_qc_union_189`REGRESS_UNION_189_OK`

**未纳入自检的包内 .py**:`config.py`、`logsetup.py`、`models.py`、`api.py`、`ingest.py`、`snapshot.py`、`sources/{repositories,scihub,snapshot_source,base}.py`、`scholar/cli.py`(`--selftest` 委托 e2e)、各 `__init__.py`/`__main__.py`(入口/包壳,无需自检)。

**有自检但未登记进 CHECKS(自检写了却不进 CI,-161 新增)**:`institutional/ezproxy_login.py`(`EZPROXY_LOGIN_OK`,当前因 G0 语法错误编不过)、`tools/{shard_cf_by_publisher,dedup_recover_input,title_probe}.py`(各有 `def _selftest`)。
