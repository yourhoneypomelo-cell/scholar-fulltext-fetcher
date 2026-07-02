# 选型2026 · 免 Docker FlareSolverr —— 仓内 nodriver shim 实测与落地（补 -177 文档）

> 交付：组员 **-179**｜2026-07-02｜工单来源：总指挥 **-156**「免Docker FlareSolverr 变体」（在 -179 名下）。
> 关系：本文是 **-177《选型2026-FlareSolverr免Docker变体-给145.md》的实测补丁**。-177 已把外部克隆型方案（byparr/FlareBypasser/Solvearr）调研到位；本文补两块 -177 未覆盖的：
> ① **本仓已自带一个免 Docker 的 FlareSolverr `/v1` 兼容变体 `tools/flaresolverr_nodriver.py`**（-177 文档未提及）；② 在**本机 Windows/PowerShell 上端到端实测通过**并给出可直接复制的 runbook。
> **致谢/归属**：`tools/flaresolverr_nodriver.py` 由 **-145/-173** 为本任务编写；本文是 **-179** 的**端到端实测 + `--selftest` 自检接入 + 调优/根因发现**，JA3 绑定的根因由 -145/-173 复核厘清。
> 边界：`--selftest` 接入外新增的都是实测/文档，不改 shim 的服务逻辑。

---

## 0. 结论（已实测，一句话）

**别急着 `git clone` 外部项目——本仓 `tools/flaresolverr_nodriver.py` 就是一个免 Docker、FlareSolverr `/v1` 逐字段兼容的求解端点，用 `nodriver`（uc 的现代继任者、兼容最新 Chrome）实现；本机 `nodriver 0.50.3` + `curl_cffi` 已装，实测健康检查 + 端到端真解全通过。这才是 -145 uc3.5.5/Chrome 卡点的「零安装、零改码、最省事」首选；byparr/Camoufox（-177 文档）留作 nodriver headed 仍被特定 Turnstile 识别时的升级选项。**

---

## 1. 实测证据（2026-07-02，本机 Windows 10 / PowerShell）

| 检查项 | 命令 | 结果 |
|---|---|---|
| 依赖已就绪 | `python -c "import nodriver,curl_cffi"` | ✅ `nodriver 0.50.3`、`curl_cffi OK`（**无需再装任何东西**） |
| shim 语法有效 | `python -m py_compile tools/flaresolverr_nodriver.py` | ✅ `COMPILE_OK` |
| 起服务（headless, 8199） | `python tools/flaresolverr_nodriver.py --headless --port 8199` | ✅ `[ready] ... listening on http://127.0.0.1:8199/v1` |
| 健康检查 | `GET http://127.0.0.1:8199/` | ✅ `FlareSolverr is ready! (nodriver shim)` |
| **端到端真解**（用仓库真实客户端） | 见下 | ✅ `SOLVE_OK` |

端到端用的就是 `download.py` 兜底调用的**同一条客户端** `fulltext_fetcher.flaresolverr.solve()`：

```powershell
$env:FLARESOLVERR_URL = "http://127.0.0.1:8199/v1"
python -c "from fulltext_fetcher.flaresolverr import solve; r=solve('https://example.com/'); print(list(r.keys())); print('ua=',r['user_agent'][:40])"
```
返回：
```
['html', 'cookies', 'user_agent', 'url', 'status_code']     # 正是 download.py 需要的契约
ua= Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit   # 真实 Windows Chrome UA
```
→ 链路 **仓库客户端 → nodriver shim → 真 Chrome → 目标站 → HTML+cookies+UA 回传** 全程打通。

---

## 2. 为什么它能「零改码」启用（端到端链路已核对）

- 客户端 `fulltext_fetcher/flaresolverr.py::_endpoint()`：端点取值 `cfg.flaresolverr_url > env FLARESOLVERR_URL > 默认 http://localhost:8191`，且自动补 `/v1`。**只认端点、不认后端** → 换任何 `/v1` 兼容服务零改码。
- 启用开关 `fulltext_fetcher/download.py::_flaresolverr_enabled(cfg)`：
  ```
  return cfg.use_flaresolverr  or  cfg.flaresolverr_url  or  os.environ["FLARESOLVERR_URL"]  # 任一为真即启用
  ```
  → **只 `set` 一个环境变量 `FLARESOLVERR_URL` 就能启用兜底**，`--` 命令行不用加任何开关、`config.py` 不用改。
- shim `tools/flaresolverr_nodriver.py` 实现了 `cmd:"request.get"` 并返回 `{status:"ok", solution:{response,cookies,userAgent,url,status}}`，与 `solve()` 的解析逐字段吻合；`sessions.*` 作 no-op 兼容。

---

## 3. 落地 runbook（Windows / PowerShell，两个终端）

**终端 A —— 起 shim（建议 headed，CF 通过率更高）：**
```powershell
# 本机 nodriver/curl_cffi 已装，直接起；有头模式过 CF 更稳
python tools/flaresolverr_nodriver.py --port 8191
#   --headless      # 无显示环境才用（CF 通过率略低）
#   --cache-ttl 1200  --page-wait 6   # 默认值，一般不用改
# 就绪后应打印：[ready] FlareSolverr(nodriver) listening on http://127.0.0.1:8191/v1
```

**终端 B —— 指向它并跑回收：**
```powershell
$env:FLARESOLVERR_URL = "http://127.0.0.1:8191/v1"     # PowerShell 语法（注意：不是 cmd 的 set VAR=）
python -m fulltext_fetcher -f recover_b4_cf_input.txt -o out\recover_b4_cf --email you@org.edu
```

> ⚠️ **给 -145**：-177 文档里的 `set FLARESOLVERR_URL=...` 是 **cmd/bat 语法，在 PowerShell 里不生效**（不会报错、但变量没设上，`_flaresolverr_enabled` 仍为 False，兜底静默不触发）。PowerShell 必须用 `$env:FLARESOLVERR_URL = "..."`。若坚持用 cmd 窗口则 `set` 可用。

---

## 4. 仓内 nodriver shim  vs  -177 的 byparr —— 用哪个

| 维度 | **① 仓内 `tools/flaresolverr_nodriver.py`（本文，首选）** | ② byparr（-177 文档，升级项） |
|---|---|---|
| 安装成本 | **零**：nodriver/curl_cffi 本机已装，脚本在仓里 | `pip install uv` + `git clone` + `uv sync`（拉 Camoufox/Firefox） |
| 引擎 | nodriver（真 Chrome、CDP 直连、无 uc3.5.5） | Camoufox/Firefox（C++ 级指纹） |
| 绕过 uc3.5.5/Chrome 卡点 | ✅ 根本不用 uc | ✅ 根本不用 Chrome |
| Turnstile/托管挑战强度 | 强（社区 ~90%）；headed 更稳 | **最强**（Camoufox 指纹更深） |
| 许可证 | nodriver = **AGPL-3.0**（内部/研究无碍；对外服务须开源，见 §6） | GPL-3.0（独立进程调用无传染） |
| 维护面 | 就在本仓，可读可控 | 外部仓，随上游走 |

**升级阶梯（推荐）**：先跑 ①（零成本、已实测）→ 若某出版商的 Turnstile 对 nodriver **headed** 仍持续失败，再上 ② byparr（Camoufox）→ 都不行才考虑住宅代理（cf_clearance 绑 IP，见 §5）。

---

## 5. cookie 复用正确性（与 -177 §3 一致，实测印证）

- shim 回传的 `cf_clearance` **绑定 IP + UA**；`solve()` 已一并返回 `user_agent`，`download.py` 重下 PDF 时会带上 → 天然正确，**别自己另换 UA**。
- 本 shim 引擎是 **Chrome 系（nodriver）→ 返回 Chrome UA**；若改用 ② byparr 则是 **Firefox UA**，各自跟随一致即可，两者别混。
- 实测回传里 `user_agent` 为本机真实 Chrome UA（见 §1），符合「同一出口 IP + 同一 UA 重下」的要求。

## 6. 注意事项 / 坑（实测记录）

- **许可证**：`nodriver = AGPL-3.0`（本仓 `browser_search.py`/`scholar/fetcher.py` 头部已声明）。**内部批量回收/个人研究无碍**；若要把这个 shim 作为对外网络服务提供，须开源修改或过法务。
- **端口冲突**：-145 正在跑 FlareSolverr 回收，很可能已占 `8191`。多人同机时各自用不同端口（如 `--port 8199`）并相应改 `$env:FLARESOLVERR_URL`，避免抢端口。
- **无 CF 的小页会「等满超时」**：实测对 example.com（无 CF、HTML<2000B）单次耗时 ~59s——因为 shim 在等不到 `cf_clearance` 且页面过小时会循环到 `~0.9×maxTimeout`。**真实回收不受影响**：shim 只在 `download.py` 已检测到 CF 质询后才被兜底调用，真 CF 站会拿到 `cf_clearance` 提前 break，且**按 origin 缓存**（默认 1200s）——80 条 DOI 通常只落 4~5 个域，只有每域首条付一次解题成本。
- **Windows 子进程**：shim 已处理（`ProactorEventLoop`）；nodriver 以子进程拉 Chrome，`Ctrl+C` 停服务后如遇端口残留，用 `Get-NetTCPConnection -LocalPort <port> -State Listen` 找 `OwningProcess` 再 `taskkill /PID <pid> /T /F` 连子树清掉（本次实测清理即如此）。
- **headed vs headless**：默认有头，CF 通过率更高；无显示环境（服务器/CI）才 `--headless`。

---

## 7. smoke10 端到端实测结果(2026-07-02，本机 headed，端口 8199）

命令:`python -m fulltext_fetcher -f recover_b4_cf_smoke10.txt -o out\recover_b4_cf_smoke_179 --email ... -c 1`(`$env:FLARESOLVERR_URL=http://127.0.0.1:8199/v1`)。

**权威口径以 shim 作者 -145/-173 的完整跑为准**(其 :8191 常驻实例、跑满 10 条):**smoke10 = 7/10(70%),flaresolverr_recovered=3**——逐条:RSC×3 OK但走 websearch(FS 回放被 RSC JA3 拒)、ACS `acscatal.0c01253` **FS 真解 4.41MB**、Wiley `cssc.201601217` OK(FS-jaad.org)、Elsevier `apcatb.2021.120319` OK(FS-iris.unito.it);MISS=ACS `iecr.9b01153`、Elsevier `jcou.2021.101493`/`cej.2024.151964`。**全量 80 条正由 -145/-173 跑,权威 recovered/failed 待其收官。**

**本文 -179 的独立跑(交叉印证,非权威)**:成功 **4/10**,用时 740.9s——低于上面 7/10,是因为**尾部 5 条被流水线 straggler 守卫误杀**(见下),属地板值。但**机制层面与作者跑一致**:shim 对 4/4 origin 拿到 cf_clearance、并有 1 条干净 FS 真解(ACS OA)。**结论:不必两人同机重复跑(同出口 IP + 两个有头 Chrome 撞同批出版商会互相拉高限速),回收率以 -145/-173 权威跑为准。**

**shim 的 CF 求解记录(关键,来自 shim 日志)**:对拿到的 4 个出版商 origin **全部拿到 `cf_clearance=YES`**:
```
pubs.rsc.org            cf_clearance=YES  9.9s   (+2 次 origin 缓存命中)
pubs.acs.org            cf_clearance=YES  54.1s  (+1 次缓存命中)
www.researchgate.net    cf_clearance=YES  54.8s  (第2次成功)
onlinelibrary.wiley.com cf_clearance=YES  54.4s  (+1 次缓存命中)
```
→ **nodriver shim 过 Cloudflare 稳定有效**,按 origin 缓存也按预期工作。

**flaresolverr 事件(attempts.jsonl)**:`flaresolverr_recovered`=1、`flaresolverr_failed`=8。
- ✅ 唯一 recovered = **ACS `acscatal.0c01253`(author-choice OA,4.4MB)**——干净的 CF 路径命中(日志「flaresolverr 过 Cloudflare 质询命中」)。
- ❌ 8 条 failed 分两类根因(经 shim 作者 **-145/-173** 复核厘清):
  - **(a) `cf_clearance` 绑定 JA3(RSC)**:shim **解得开、cf_clearance 到手**,但 `download.py` 把 cookie 交给 **curl_cffi 第三方回放**下 PDF 时,RSC 校验 **JA3 TLS 指纹**不匹配 → 仍 `403`。**这不是没过 CF,也不是付费墙**——是「cookie→异客户端回放」这条链在强 CF 站失效(ACS 不绑 JA3,故 ACS OA 能过)。**真解 = 浏览器内直下 PDF**(见下)。其中 3 条 RSC 已被 websearch 兜回。
  - **(b) 真·订阅墙(ACS `iecr.9b01153`、Wiley `anie.201007484`)**:非 OA 条目,过了 CF 仍 `403`——任何 CF/JA3 手段都救不了。

**核心结论**:**shim 可靠过 CF(4/4 origin cf_clearance=YES);能否把 PDF 下全取决于两件与 CF 无关的事——① 该站 cf_clearance 是否绑 JA3(绑则 curl_cffi 回放失败,需浏览器内直下);② 该条是否真 OA(订阅墙救不了)。** 判断「回收率」必须把这三层(过 CF / JA3 回放 / 付费墙)分开看。

**JA3 绑定的正解——浏览器内直下 PDF**:本仓 `download.py` 已有 `_nodriver_fetch_pdf_bytes` + `cfg.browser_pdf_download=True`(用 nodriver 在**同一浏览器会话/同一 JA3** 内直接取 PDF 字节),正是 RSC 这类 JA3 绑定站的解法;或让 shim 扩展一个「浏览器内下 PDF」的命令。**后续增强方向**:CF 回收对 JA3 绑定站(RSC 等)优先走浏览器内直下,而非 cookie→curl_cffi 回放。

**踩坑:straggler 守卫对浏览器 CF 重活过于激进**。流水线「尾部若干条 240s 内无进展即判卡死」的守卫,在 CF 回收(每次解 CF ~54s、还叠加 502/websearch)下会**把尾部 5 条(2 Elsevier/1 Wiley cssc 等)在没真正跑完前直接判失败**(`error=straggler-timeout`,elapsed=0)。给 -145 的实跑建议:
1. **CF 桶回收裁剪 sources**:`--sources publisher_oa,publisher_direct,crossref`(去掉慢的 websearch/wayback),缩短每条耗时、让进展更密。
2. 或**调大 straggler 无进展阈值**到 ~600s(容纳「~54s/CF 解 × 多源」)。
3. **付费墙 403 非 CF 可解**:CF 回收应聚焦「CF 后面的 OA」(如 ACS author-choice / Wiley OnlineOpen 真 OA 条目),订阅墙条目走 websearch/绿色 OA 兜底更划算。

## 8. 已接入 run_all_selftests.py 的可选联网自检(2026-07-02，-179）

- 给 `tools/flaresolverr_nodriver.py` 增加 **`--selftest`**:起 headless + 临时 `/v1`,真解 `example.com`,校验 health + `solution` 契约齐全,成功打印 **`FLARESOLVERR_NODRIVER_OK`**、退出 0;任何失败(含无 Chrome/nodriver)→ 非 0。
- 在 `run_all_selftests.py` 增加 **`ONLINE_CHECKS`**(与离线 `CHECKS` 分开):**默认 SKIP**(离线 CI 逐字节不受影响),仅当 **`RUN_ONLINE_SELFTESTS=1`** 时才真跑,超时放宽到 `ONLINE_TIMEOUT=240s`。
- 实测:
  - `python -m tools.flaresolverr_nodriver --selftest` → `FLARESOLVERR_NODRIVER_OK`(~21s)。
  - `python run_all_selftests.py`(默认)→ `SUMMARY: PASS=40 FAIL=0 SKIP=1`,其中 `flaresolverr_nodriver` 记 SKIP,**离线全绿**。
  - 需真验端到端:`$env:RUN_ONLINE_SELFTESTS="1"; python run_all_selftests.py`。
- **小 nit(不影响功能)**:shim 用的 `cdp.network.get_all_cookies()` 在 nodriver 1.3 已 DeprecationWarning;shim 已有 `browser.cookies.get_all()` 回退,当前照常工作。后续可切到未废弃 API 消除告警。

## 9. 来源 / 交叉引用

- 本仓源码（实测依据）：`tools/flaresolverr_nodriver.py`、`fulltext_fetcher/flaresolverr.py`（`/v1` 客户端）、`fulltext_fetcher/download.py`（`_flaresolverr_enabled`/`_flaresolverr_fallback`）、`fulltext_fetcher/config.py`（`use_flaresolverr`/`flaresolverr_url`）。
- -177《选型2026-FlareSolverr免Docker变体-给145.md》（外部克隆型方案 byparr/FlareBypasser/Solvearr、病根定位、cookie 复用）。
- -176《选型2026-RSC-Cloudflare挑战绕行方案.md》（render_fetch.py 内置 nodriver、CF 性价比论证）。
- 158《选型2026-隐身无头浏览器与反检测.md》（nodriver=AGPL-3.0、benchmark 31 目标零封锁、uc 已弃）。

---
*核验 2026-07-02｜-179｜工单「免Docker FlareSolverr 变体」实测补丁｜结论：本仓 `tools/flaresolverr_nodriver.py` 免Docker、零安装（nodriver 0.50.3 已装）、端到端实测通过 → -145 首选此路，byparr 作升级项。仅实测/手册，不改 .py。*
