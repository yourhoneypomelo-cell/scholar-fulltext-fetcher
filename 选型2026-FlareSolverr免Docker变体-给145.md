# 选型2026 · 免 Docker 的 FlareSolverr 变体（解 145 的 uc3.5.5/Chrome 卡点）

> 智库交付（信息检索-智库专家 **-177**）｜2026-07-02｜任务来源：总指挥 -156 `task-ce9111a4`（急件，直送 -145）。
> 触发：-145 在「FlareSolverr 实跑回收 batch4『A+Cloudflare』桶」时，Docker-free 跑 FlareSolverr 撞上 `undetected-chromedriver 3.5.5` 与本机 Chrome 版本不兼容。
> 边界：只做选型/运行手册，不改 `.py`。

---

## 0. 结论（一句话）
**病根是 FlareSolverr 钉死 `undetected-chromedriver==3.5.5`（老、与现代 Chrome 持续错配）。** 本仓 `flaresolverr.py` 是**通用 FlareSolverr `/v1` API 客户端（只认端点、不认后端）**，故最优解是把 `FLARESOLVERR_URL` 指向一个**「现代引擎 + 免 Docker」的 `/v1` 兼容服务**。

> **修订（谢 -140/牛马 实测）**：**零安装首选 = 本仓已自带的 `tools/flaresolverr_nodriver.py`**（nodriver shim，无 uc/Chrome 钉子，-140 本机端到端实测全绿）——我原稿漏了这个仓内件（未扫 `tools/`）。**byparr(Camoufox) 降为「nodriver 有头仍被特定 Turnstile 识别时」的升级项。** 另：环境变量须用 **PowerShell `$env:FLARESOLVERR_URL="..."`**（本机 shell 是 PowerShell，非 cmd 的 `set`）。详见 -140《选型2026-FlareSolverr免Docker-仓内nodriver-shim实测与落地-179》。

---

## 1. 病根定位（为什么 uc3.5.5 卡）
- FlareSolverr 用 Selenium + `undetected-chromedriver 3.5.5` 驱动 Chrome；uc 自取的 chromedriver 版本与本机 Chrome 主版本错配 → 典型报错 `This version of ChromeDriver only supports Chrome version X / Current browser version is Y` 或 `cannot connect to chrome`。
- uc 3.5.5 是 2023 老版本，与 2026 的 Chrome 是**持续军备竞赛**；改 `version_main` / 删缓存只能治标，**下次 Chrome 自动更新又犯**。
- 关键洞察：本仓 `flaresolverr.py`（`solve()` / `fetch_via_flaresolverr()`）只发 `POST {FLARESOLVERR_URL}/v1`，端点由 `FLARESOLVERR_URL` 环境变量或 `cfg.flaresolverr_url` 决定 → **换任何 `/v1` 兼容后端都零改代码**。

---

## 2. 免 Docker + 现代引擎的 `/v1` 兼容服务（按推荐度）

| 方案 | 引擎 | 免 Docker 起法 | uc/Chrome 问题 | /v1 兼容 | 许可 | 备注 |
|---|---|---|---|---|---|---|
| **⓪ 仓内 nodriver shim** `tools/flaresolverr_nodriver.py`（本项目自带） | **nodriver**（uc 现代继任者，驱动最新 Chrome 133） | `python tools/flaresolverr_nodriver.py`（默认 127.0.0.1:8191，有头） | **无**（nodriver 无 uc 钉子） | ✅ 原生 `/v1`（request.get + sessions.*） | 随本仓 | **★零安装首选**（nodriver+curl_cffi 已装）；按 origin 缓存 cf_clearance(20min)；Windows 用 ProactorEventLoop；-140 实测全绿 |
| **① byparr**（ThePhaseless/Byparr, ~1K★） | **Camoufox/Firefox**（C++ 级指纹） | `pip install uv` → `git clone` → `uv sync && uv run main.py`（默认 8191） | **根本不用**（Firefox 系） | ✅ v1 逐字节兼容(POST /v1) | GPL-3.0 | **升级项**（shim 被特定 Turnstile 识别时）；2026 开源过 Turnstile 最强；独立服务进程调用无 GPL 传染 |
| **② FlareBypasser**（yoori/flare-bypasser） | **zendriver**(nodriver 系, Chrome) | `pip install git+https://github.com/yoori/flare-bypasser.git` → `flare_bypass_server` | 不用 uc3.5.5（zendriver 自管） | ✅ `/v1`(request.get/get_cookies/post) | 开源 | **pip 一条龙、最省事**；仍用 Chrome 但非 uc 老钉子 |
| ③ Byparr-nodriver（hatemosphere） | nodriver/seleniumbase | `uv sync && uv run main.py` | 不用 uc3.5.5 | ✅ drop-in | — | 备选；README 略不一致 |
| ④ Solvearr（nabil-ak） | **纯 TLS 指纹、无浏览器** | `uvicorn main:app --port 8191` | 无浏览器 | ✅ FlareSolverr 规范 | — | 轻，但**不执行 JS→过不了 Turnstile/托管挑战**；仅 TLS 门站，batch4 CF 桶多半不够 |
| ⑤ vanilla FlareSolverr 临时救火 | uc3.5.5/Chrome | 删 `%AppData%\undetected_chromedriver\*.exe` 重跑；或 `pip install -U undetected-chromedriver`(>3.5.5) | **治标** | ✅ 原生 | MIT | 只应急，建议尽快切 ①/② |

### 落地命令（PowerShell — 本机 shell）

**⓪ 零安装首选 — 仓内 nodriver shim**
```powershell
python tools/flaresolverr_nodriver.py            # 默认 127.0.0.1:8191（有头，CF 通过率更高；--headless 可选）
# 另一 PowerShell 窗口：
$env:FLARESOLVERR_URL = "http://127.0.0.1:8191/v1"    # ← PowerShell 语法（不是 cmd 的 set）
python -m fulltext_fetcher -f <input>.txt -o out\... --email you@org
```

**① 升级项 — byparr（nodriver 仍被特定 Turnstile 识别时）**
```powershell
pip install uv
git clone https://github.com/ThePhaseless/Byparr; cd Byparr
uv sync; uv run main.py            # 免 Docker；Camoufox 自动下 Firefox；默认端口 8191
$env:FLARESOLVERR_URL = "http://localhost:8191"      # ← PowerShell 语法
```

---

## 3. 关键提醒（cookie 复用正确性）

- **⚠️⚠️ 不止 IP+UA——强 CF 站还把 cf_clearance 绑到 JA3/TLS 指纹（-145 实测，重要修正）**：RSC 的 cf_clearance 即便回放时带**同一 `user_agent` + 同一出口 IP**，用 `curl_cffi` 回放**仍 403**（`flaresolverr_failed`）——因为 curl_cffi 的 JA3 ≠ 真 Chrome。**结论：只要是「solve 拿 cookie → 第三方 HTTP 客户端回放」这条链，强 CF 站(RSC)就会因 JA3 不符拒绝**；换 byparr(Firefox JA3)/FlareBypasser **同样救不了 RSC**（其 JA3 也非回放客户端的 JA3）。
  - **站点分档（实测）**：**ACS 等中等 CF 站回放可过**（`acscatal` 已回收）；**RSC 等强 CF 站回放失效**。
  - **强 CF 真解 = 浏览器内直接下 PDF**：用 `render_fetch.py` 内置 nodriver（或在解挑战的**同一浏览器**里直接下载），让下载与挑战在同一真 Chrome 指纹内完成——而非把 cookie 交给外部 HTTP 回放。此即 -176《选型2026-RSC-Cloudflare挑战绕行方案》的「形态 A（渲染直取 PDF）」结论。
- **cookie 回放仍适用的场景**：中等 CF 站（ACS 等）——回传 cookie 给本仓 `http_client` 直下时，须带 `solve()` 返回的 `user_agent` + 同一出口 IP（`flaresolverr.solve()` 已返回 `user_agent`）。引擎决定 UA 家族：byparr=Firefox UA、FlareBypasser/仓内 shim=Chrome UA，各自一致即可，勿混用。
- HTTP/2：部分站用 HTTP/2 时，拿 cookie 后直下建议用支持 HTTP/2 的客户端（`httpx`），`requests`(HTTP/1.1) 偶发 403。

## 4. 更轻的替代（若不非要 /v1 服务模型）
本仓 `render_fetch.py` **已内置 nodriver**（`pip install nodriver`，免 Docker 免常驻服务，CDP 直连，CF 通过率高）——见 -176《选型2026-RSC-Cloudflare挑战绕行方案》§5。适合「渲染落地页直取 PDF」；-145 既走 FlareSolverr-API 回收流，`byparr` 是最省事的 drop-in 治本。

## 5. 来源（2026 时效）
- ThePhaseless/Byparr（README 本地 `uv run main.py` 安装、v2.1.0/2026-02、Camoufox、FlareSolverr v1 兼容）；roundproxies/godberrystudios 2026 评测。
- yoori/flare-bypasser（README：`pip install git+…` + `flare_bypass_server`、zendriver、`/v1` 兼容）；hatemosphere/Byparr-nodriver；nabil-ak/Solvearr（纯 TLS、无浏览器）。
- ultrafunkamsterdam/undetected-chromedriver issues #1800/#2158/discussion #2282（版本错配与 `version_main`/删缓存修法）；PyPI uc v3.5.5。
- 本仓源码：`fulltext_fetcher/flaresolverr.py`（`/v1` 客户端、`FLARESOLVERR_URL`）、`render_fetch.py`（内置 nodriver）。

## 6. 免 Docker 故障排查（备 -145 落地）

**⓪ 仓内 nodriver shim 排查**：需 `pip install nodriver`（curl_cffi 本仓已装）；Windows 自动走 ProactorEventLoop；有头首启会弹一个 Chrome 窗口（正常）；健康检查 `GET http://127.0.0.1:8191/` 应回 `FlareSolverr is ready! (nodriver shim)`；同 origin 首次真解、其余 20min 内命中缓存；异常一律降级 `{status:"error"}` 不崩端点。

**① byparr 排查**：

| 症状 | 排查 |
|---|---|
| `uv` 命令找不到 | `pip install uv` 后 `uv --version`；Windows 重开终端刷新 PATH |
| 首启卡在下载 Firefox | `uv run main.py` 首次会由 Camoufox 拉一份 Firefox(~数百 MB)；网络差先 `uv run camoufox fetch` 预取或设代理重试；缓存在用户目录，装一次即可 |
| 端口 8191 被占 | 之前的 FlareSolverr/其它服务占用 → 改端口（byparr: env `HOST`/`PORT`；shim: `--port`）并同步 `$env:FLARESOLVERR_URL="http://localhost:<新端口>"`（PowerShell） |
| 服务器/无显示环境报错 | 设 `USE_HEADLESS=true`；Windows 本机建议 **headful**（更稳过 Turnstile） |
| Python 版本 | byparr v2.1.0 支持到 3.14；`uv` 自管虚拟环境 Python，一般无需手动装 |
| 验证是否起好 | 浏览器开 `http://localhost:8191/docs`(FastAPI 自动文档)，或 `POST /v1 {"cmd":"request.get","url":"https://…","maxTimeout":60000}` 看是否回 `solution` |
| 本仓联调超时 | byparr 首次解挑战较慢 → 把 `cfg.flaresolverr_timeout_ms`(默认 60000)调大；`FLARESOLVERR_URL` 不带 `/v1` 也行(客户端自动补) |
| cf_clearance 复用 403 | byparr=Firefox UA → 回传直下务必带 `solve()` 的 `user_agent` + 同一出口 IP；HTTP/2 站用 `httpx` 而非 `requests` |

**FlareBypasser 备选**：`zendriver` 需本机 Chrome/Chromium（无则装）；`flare_bypass_server` 默认 8191；代理需 `gost`（Chrome SOCKS5 鉴权限制）。

> -145 的 FS 工单归 -140；本文档与 -140《…仓内nodriver-shim实测与落地-179》交叉引用，-145-facing 落地由 -140 主导，我不重复推送。

---
*核验 2026-07-02｜信息检索-智库专家 -177｜仅选型/运行手册，不改 .py。核心：flaresolverr.py 是通用 /v1 客户端 → **零安装首选=仓内 `tools/flaresolverr_nodriver.py`(nodriver shim)**，byparr(Camoufox) 作升级项，皆绕开 uc3.5.5/Chrome。**修订：①(谢 -140 实测) 补仓内 shim 为零安装首选；② 环境变量用 PowerShell `$env:FLARESOLVERR_URL=`（非 cmd `set`）；③(谢 -145 实测) cf_clearance 还绑 JA3/TLS——强 CF(RSC) cookie 回放必 403(curl_cffi/byparr JA3≠真Chrome)，真解=浏览器内直下 PDF(render_fetch nodriver)，见 §3。***
