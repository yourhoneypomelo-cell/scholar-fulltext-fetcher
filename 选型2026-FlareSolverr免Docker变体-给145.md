# 选型2026 · 免 Docker 的 FlareSolverr 变体（解 145 的 uc3.5.5/Chrome 卡点）

> 智库交付（信息检索-智库专家 **-177**）｜2026-07-02｜任务来源：总指挥 -156 `task-ce9111a4`（急件，直送 -145）。
> 触发：-145 在「FlareSolverr 实跑回收 batch4『A+Cloudflare』桶」时，Docker-free 跑 FlareSolverr 撞上 `undetected-chromedriver 3.5.5` 与本机 Chrome 版本不兼容。
> 边界：只做选型/运行手册，不改 `.py`。

---

## 0. 结论（一句话）
**病根是 FlareSolverr 钉死 `undetected-chromedriver==3.5.5`（老、与现代 Chrome 持续错配）。** 本仓 `flaresolverr.py` 是**通用 FlareSolverr `/v1` API 客户端（只认端点、不认后端）**，故最优解是把 `FLARESOLVERR_URL` 指向一个**「现代引擎 + 免 Docker」的 `/v1` 兼容服务**——**首选 byparr（Camoufox，根本不用 uc/Chrome）**，零改代码。

---

## 1. 病根定位（为什么 uc3.5.5 卡）
- FlareSolverr 用 Selenium + `undetected-chromedriver 3.5.5` 驱动 Chrome；uc 自取的 chromedriver 版本与本机 Chrome 主版本错配 → 典型报错 `This version of ChromeDriver only supports Chrome version X / Current browser version is Y` 或 `cannot connect to chrome`。
- uc 3.5.5 是 2023 老版本，与 2026 的 Chrome 是**持续军备竞赛**；改 `version_main` / 删缓存只能治标，**下次 Chrome 自动更新又犯**。
- 关键洞察：本仓 `flaresolverr.py`（`solve()` / `fetch_via_flaresolverr()`）只发 `POST {FLARESOLVERR_URL}/v1`，端点由 `FLARESOLVERR_URL` 环境变量或 `cfg.flaresolverr_url` 决定 → **换任何 `/v1` 兼容后端都零改代码**。

---

## 2. 免 Docker + 现代引擎的 `/v1` 兼容服务（按推荐度）

| 方案 | 引擎 | 免 Docker 起法 | uc/Chrome 问题 | /v1 兼容 | 许可 | 备注 |
|---|---|---|---|---|---|---|
| **① byparr**（ThePhaseless/Byparr, ~1K★） | **Camoufox/Firefox**（C++ 级指纹） | `pip install uv` → `git clone` → `uv sync && uv run main.py`（默认 8191） | **根本不用**（Firefox 系） | ✅ v1 逐字节兼容(POST /v1) | GPL-3.0 | 2026 开源过 Turnstile 最强；独立服务进程调用无 GPL 传染 |
| **② FlareBypasser**（yoori/flare-bypasser） | **zendriver**(nodriver 系, Chrome) | `pip install git+https://github.com/yoori/flare-bypasser.git` → `flare_bypass_server` | 不用 uc3.5.5（zendriver 自管） | ✅ `/v1`(request.get/get_cookies/post) | 开源 | **pip 一条龙、最省事**；仍用 Chrome 但非 uc 老钉子 |
| ③ Byparr-nodriver（hatemosphere） | nodriver/seleniumbase | `uv sync && uv run main.py` | 不用 uc3.5.5 | ✅ drop-in | — | 备选；README 略不一致 |
| ④ Solvearr（nabil-ak） | **纯 TLS 指纹、无浏览器** | `uvicorn main:app --port 8191` | 无浏览器 | ✅ FlareSolverr 规范 | — | 轻，但**不执行 JS→过不了 Turnstile/托管挑战**；仅 TLS 门站，batch4 CF 桶多半不够 |
| ⑤ vanilla FlareSolverr 临时救火 | uc3.5.5/Chrome | 删 `%AppData%\undetected_chromedriver\*.exe` 重跑；或 `pip install -U undetected-chromedriver`(>3.5.5) | **治标** | ✅ 原生 | MIT | 只应急，建议尽快切 ①/② |

### 落地命令（byparr，首选）
```bash
pip install uv
git clone https://github.com/ThePhaseless/Byparr && cd Byparr
uv sync && uv run main.py          # 免 Docker；Camoufox 自动下 Firefox；默认端口 8191
# 另一终端 / 环境：
set FLARESOLVERR_URL=http://localhost:8191   # flaresolverr.py 自动读该环境变量
```

---

## 3. 关键提醒（cookie 复用正确性）
- byparr/FlareBypasser/FlareSolverr 拿到的 `cf_clearance` **绑定 IP + UA**：回传 cookie 给本仓 `http_client` 直下 PDF 时，**必须带 `solve()` 返回的 `user_agent`、且同一出口 IP**（`flaresolverr.solve()` 已返回 `user_agent`，天然支持）。
- 引擎决定 UA 家族：**byparr = Firefox UA**、**FlareBypasser = Chrome UA**——各自跟随一致即可，勿混用。
- HTTP/2：部分站用 HTTP/2 时，拿 cookie 后直下建议用支持 HTTP/2 的客户端（`httpx`），`requests`(HTTP/1.1) 偶发 403。

## 4. 更轻的替代（若不非要 /v1 服务模型）
本仓 `render_fetch.py` **已内置 nodriver**（`pip install nodriver`，免 Docker 免常驻服务，CDP 直连，CF 通过率高）——见 -176《选型2026-RSC-Cloudflare挑战绕行方案》§5。适合「渲染落地页直取 PDF」；-145 既走 FlareSolverr-API 回收流，`byparr` 是最省事的 drop-in 治本。

## 5. 来源（2026 时效）
- ThePhaseless/Byparr（README 本地 `uv run main.py` 安装、v2.1.0/2026-02、Camoufox、FlareSolverr v1 兼容）；roundproxies/godberrystudios 2026 评测。
- yoori/flare-bypasser（README：`pip install git+…` + `flare_bypass_server`、zendriver、`/v1` 兼容）；hatemosphere/Byparr-nodriver；nabil-ak/Solvearr（纯 TLS、无浏览器）。
- ultrafunkamsterdam/undetected-chromedriver issues #1800/#2158/discussion #2282（版本错配与 `version_main`/删缓存修法）；PyPI uc v3.5.5。
- 本仓源码：`fulltext_fetcher/flaresolverr.py`（`/v1` 客户端、`FLARESOLVERR_URL`）、`render_fetch.py`（内置 nodriver）。

---
*核验 2026-07-02｜信息检索-智库专家 -177｜急件直送 -145｜仅选型/运行手册，不改 .py。核心：flaresolverr.py 是通用 /v1 客户端 → 换 byparr(Camoufox,免Docker,无uc) 即彻底绕开 uc3.5.5/Chrome。*
