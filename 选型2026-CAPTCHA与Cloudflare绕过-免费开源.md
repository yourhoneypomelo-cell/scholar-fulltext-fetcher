# 选型 2026 · CAPTCHA 与 Cloudflare 绕过（免费 / 开源，服务层）

> 目的：在"**能避免就避免、必要时才自动过**"的原则下，为 fulltext_fetcher 选定**免费 / 自托管**的 CAPTCHA 与 Cloudflare 绕过方案（可作 `captcha` 模块实现，或作 FlareSolverr 式兜底服务）。**付费服务只登记、不采用。**
> 整理人：谷歌学术人机认证-155（worker）｜数据核验：**2026-07-01**（star/版本/许可以该日 GitHub/PyPI 为准，取整到十位）。
> 关系定位（去重）：
> - 广度 SOTA（隐身浏览器 + TLS + captcha 概览）见《谷歌学术爬虫-调研-无头浏览器过验证-免费.md》（本人，§2 CF / §3 captcha）；
> - Scholar 抓取库 + **付费打码 SDK** 横评 + "失败几乎全是付费墙非 reCAPTCHA"的关键事实见《谷歌学术爬虫-调研-Scholar抓取与CAPTCHA与下载.md》（141）；
> - 本文只做**服务层的选型裁决**：逐项 free-local vs paid、部署/Docker/Windows/成功率，给 `采用 / 登记 / 不用` 决策表 + Top1-2 源码级尽调。

---

## 〇、充分度评估 + 一句话结论

- **既有文档充分度**：广度已够（两篇覆盖了工具全景与 Scholar/付费 SDK），**缺口**在于——① Cloudflare **自托管服务**（byparr/FlareSolverr）的**部署/Docker/Windows/成功率**硬细节；② reCAPTCHA/hCaptcha **免费开源求解器**的**可编程性与可用边界**（Buster 是人辅扩展 ≠ 可脚本化；hcaptcha-challenger 只解 hCaptcha）。本文补齐这两块并给出可执行裁决。
- **对本项目的关键判断**（承接 141 数据）：本仓 500 样本失败**几乎全是出版商 403 付费墙 / 无 OA 候选，不是 reCAPTCHA 拦截**。且 **Google Scholar 用 reCAPTCHA v2/v3（非 hCaptcha）**，Scholar 页本身**不走 Cloudflare**（CF 出现在部分出版商/镜像下载站）。⇒ **CAPTCHA 与 CF 绕过对本项目都是"低频兜底"，不是主路径。**
- **一句话结论**：
  - **Cloudflare 兜底服务**：**采用 `byparr`**（Camoufox 内核、FlareSolverr 直替、开源栈里过 Turnstile 最强），仅在遇到 CF 保护的下载站时启用；`cloudscraper` 作零基建轻量首试；`FlareSolverr` 仅登记（现代 Turnstile 已失效）。
  - **reCAPTCHA（Scholar 相关）**：**采用「reCAPTCHA v2 音频 + 本地 Whisper」**（唯一免费、可编程、可无头的路径，见前文 §3），**仅极低频兜底**（无代理下会烧 IP）。`Buster` 登记（人辅扩展、不可规模化脚本）。
  - **hCaptcha**：本项目**用不到**（Scholar 非 hCaptcha）→ `hcaptcha-challenger` **登记**备查。
  - **付费打码**（2Captcha/CapSolver/Anti-Captcha，见 141 文）：**只登记不采用**，留作"免费全失败"时的人工开关。

---

## 一、Cloudflare 绕过（免费 / 自托管）决策表

| 方案 | 仓库 | ⭐Star | 许可 | 版本/活跃 | 形态 & 部署 | 能力 & 成功率 | Windows | 裁决 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **byparr** | ThePhaseless/Byparr | ~1,600 | **GPL-3.0** | v2.1.0（2026-02）；push 2026-06；活跃 | **自托管 API 服务**；Docker（`ghcr.io/thephaseless/byparr`，~650MB–1.1GB，端口 8191）；**FlareSolverr v1 API 直替** | **Camoufox（Firefox C++ 级 stealth）**；2026 开源栈里过 **Turnstile/Managed Challenge 最强**（Roundproxies/ZenRows/Scrapfly/WSC LAB#95 榜首）；延迟较高；仍逊于商业托管 | ✅（经 Docker Desktop） | **采用（CF 兜底首选）** |
| **FlareSolverr** | FlareSolverr/FlareSolverr | ~2.3万 | MIT | 维护放缓 | 自托管 API；Docker（端口 8191）；Selenium+UC | 仅**轻 JS 挑战**；**现代 Turnstile/Managed 已失效**；会 hang | ✅（Docker） | **登记/仅老站**（byparr 取代） |
| **cloudscraper** | VeNoMouS/cloudscraper | ~4,700 | MIT | 维护中 | **纯 pip 库、零基建**（进程内） | 仅**旧式 CF IUAM JS 挑战**；对现代 Turnstile 基本无效 | ✅（pip） | **登记/轻量首试**（易，先试再上重的） |
| **Scrapling** | D4Vinci/Scrapling | 活跃 | 开源 | v0.4.8（2026-05） | pip 框架；`StealthyFetcher(solve_cloudflare=True)` | 三档 fetcher（TLS→Camoufox 自动解 CF→Playwright） | ✅（pip；Camoufox 需下载浏览器） | **登记/备选框架** |
| curl_cffi | lexiforest/curl_cffi | ~5,900 | MIT | 活跃 | pip；进程内 | **仅 TLS/JA3 层**（非 CF-JS）；已在本仓 `fetcher.py` L1 采用 | ✅ | 已采用（见前文） |

**接法**：byparr/FlareSolverr 均为 `POST http://127.0.0.1:8191/v1`，体形如 `{"cmd":"request.get","url":"<目标>","maxTimeout":60000}`，返回解挑战后的 HTML + cookies。本仓可在 `download.py` 落地页兜底或 `fetcher.py` 的一层里，把"命中 CF"的 URL 转发给该服务取 cookies/HTML 再续下载——**接口与 FlareSolverr 完全一致，换 URL 即可**。

---

## 二、CAPTCHA 应对（免费 / 开源）决策表

> Google Scholar = **reCAPTCHA v2/v3**。免费开源只在 **reCAPTCHA v2（有音频挑战）** 这一支真正可编程；v3（纯分数）与 hCaptcha 免费基本无解。

| 方案 | 仓库 | ⭐Star | 许可 | 目标类型 | 形态（可否无头脚本化） | 成功率 & 边界 | 裁决 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **reCAPTCHA v2 音频 + 本地 Whisper** | ibedevesh/capsolver、saifyxpro/…、k19-sudo/…（MIT 系） | 各百级 | **MIT** | reCAPTCHA **v2** | ✅ **可编程/可无头**（Selenium/Playwright + `faster-whisper` + ffmpeg） | 标准 v2 号称近 100%；**仅 v2**；重用触发 "automated queries" 封；**无代理下极易烧 IP** | **采用（唯一免费可编程 reCAPTCHA，极低频兜底）** |
| **Buster** | dessant/buster | ~9,150 | **GPL-3.0** | reCAPTCHA v2 音频 | ⚠️ **浏览器扩展 + 桌面 client app**，靠**人点按钮**；非自动化 API | "**一天几次即可能被临时封**，与是否用扩展无关"；本质是**无障碍人辅工具** | **登记/不直接采用**（不可规模化脚本） |
| **hcaptcha-challenger** | QIN2DIM/hcaptcha-challenger | ~2,350 | **GPL-3.0** | **hCaptcha**（非 reCAPTCHA） | ✅ 库（Playwright/Puppeteer + 多模态 LLM/CLIP/YOLO） | 解 hCaptcha 图像题；**Alpha**；Agentic 流程需 LLM（Gemini/OpenAI，可能要 key） | **登记**（Scholar 用不到；备查/若出版商用 hCaptcha） |
| 付费打码 SDK | 2captcha / CapSolver / Anti-Captcha 客户端 | 见 141 文 | MIT（客户端） | v2/v3/Turnstile/hCaptcha… 全 | ✅ 稳定 | 覆盖最全但**持续付费**（$0.5–3/千次） | **登记不采用**（免费全失败时人工开关；详见 141 文） |

---

## 三、Top 1–2 源码级尽调（部署 / Docker / Windows / 成功率）

### 3.1 byparr（CF 兜底 Top1）
- **形态**：单开发者（ThePhaseless）维护的 **Camoufox + FastAPI** 服务；`v2.0.0` 把浏览器从 Selenium+UC 换成 **Camoufox**（C++ 级指纹补丁，检测方读不到编译层的"谎言"）；`v2.1.0`（2026-02）加 Python 3.14 + 逐请求代理 `X-Proxy-*` 头。
- **部署（Windows 可用）**：Docker 为主——`docker run -d --name byparr -p 8191:8191 --restart unless-stopped ghcr.io/thephaseless/byparr:latest`；镜像 ~650MB。Windows 经 **Docker Desktop** 即可；Linux 可选 `USE_XVFB`（可能有性能问题）。env：`USE_HEADLESS`、`PROXY`（`protocol://user:pass@host:port`，**SOCKS5 鉴权不支持**）。内置 `/health` 健康检查。
- **API**：与 FlareSolverr 完全兼容（`POST /v1`），现有 FlareSolverr 客户端零改动切过来。
- **成功率**：多家 2026 独立评测（Roundproxies/ZenRows/Scrapfly/WSC LAB#95）**开源第一**过 Turnstile；但明确声明"**不保证**、且需目标 IP 有效流量"，仍逊于商业托管；延迟高于纯 HTTP。
- **对本项目**：仅当下载站是 **CF 保护**时才起（Scholar 不需要）。Windows 本机需装 Docker Desktop；若不想引入 Docker，先用 `cloudscraper` 轻量试，真遇硬 CF 再上 byparr。

### 3.2 reCAPTCHA v2 音频 + 本地 Whisper（免费 captcha Top1）
- **形态**：一批 MIT 小库（ibedevesh/capsolver、saifyxpro、k19-sudo 等），共同套路：点 checkbox → 切"音频挑战" → 下音频 → `faster-whisper` **本地转写** → 填答提交。**无第三方服务、无 key**。
- **部署（Windows 可用）**：纯 pip：`faster-whisper`（`small` 模型约 2GB RAM）+ 系统 `ffmpeg`；**无需 Docker**，Windows 友好（装 ffmpeg 即可）。经 Selenium/Playwright/undetected-chromedriver 驱动。
- **成功率 & 边界**：标准 v2 音频号称近 100%（语音清晰，Whisper `small`/`base` 足够）；**仅 v2（非 v3、非 hCaptcha）**；频繁使用触发限流/"automated queries"、疑似 bot 站点会禁音频；官方经验都强调**需住宅代理 + IP 轮换 + 拟人**才能持续——**本项目无代理，故只能极低频用**。
- **对本项目**：作 `captcha` 模块的**免费实现**（对齐本仓 `fetcher.py` 里 `captcha_enabled` 默认 False 的"默认不硬刚"设计）；命中 Scholar reCAPTCHA 时**偶发兜底**，失败即停、不轰炸。

> 备选 #2（hcaptcha-challenger）：只解 hCaptcha、Alpha、可能需 LLM key，Scholar 用不到 → 仅登记；若未来某出版商用 hCaptcha 再评估。

---

## 四、对本项目的采用建议（结合 Windows / 无代理 / 失败画像）

1. **优先级**：CAPTCHA 与 CF 绕过都是**低频兜底**——本仓失败主因是**付费墙**，正解是**多源 OA 回退 + 合规正门（开放 API / SerpApi）**，不是"过验证"。
2. **CF 兜底**：默认 `cloudscraper`（零基建、进程内、先试）；遇现代 Turnstile → 上 **byparr**（Windows 装 Docker Desktop，`POST /v1` 复用 FlareSolverr 客户端）。二者仅对 **CF 保护的下载站**，Scholar 不用。
3. **reCAPTCHA 兜底**：**reCAPTCHA v2 音频 + 本地 Whisper** 作免费实现，**默认关**、极低频、失败即停（无代理下保护唯一干净 IP）。
4. **不采用**：Buster（人辅扩展、不可脚本化）；hcaptcha-challenger（非 reCAPTCHA，Scholar 无关）——均**登记**备查。付费打码**登记不采用**。
5. **落地位置**：CF 服务接在 `download.py` 落地页兜底 / `fetcher.py` 一层；captcha 接在 `scholar/captcha.py`（已存在 `solve_recaptcha` 契约）——**均需 config 字段时报总指挥 142 统一加**（如 `cf_service_url`、`captcha_enabled` 已有）。

---

## 五、合规与许可

- **许可**：`byparr`/`Buster`/`hcaptcha-challenger` 均 **GPL-3.0**（copyleft：自托管/内部使用无碍；若**分发修改版**须开源）；`FlareSolverr`/`cloudscraper`/`curl_cffi`/Whisper 系 **MIT**（宽松）。byparr 作为**独立服务进程**调用（非链接进你的代码），GPL 传染风险低；但若把 GPL 库**直接 import 进本仓**须评估。
- **合规**：直抓 Google Scholar、自动过 reCAPTCHA 均属**灰色**，违反 ToS；本文仅技术调研，**使用者自负合规**。免费打码仅限研究/测试自有系统。**能走开放 API / 合规商业 API（SerpApi）就别自建直抓、别硬刚验证码。**

---

*核验 2026-07-01｜来源：ThePhaseless/Byparr（GitHub/DeepWiki/Roundproxies 部署与评测）、dessant/buster、QIN2DIM/hcaptcha-challenger（GitHub/PyPI）、VeNoMouS/cloudscraper、Byparr+Scrapling 2026 评测。付费打码 SDK 横评见 141《谷歌学术爬虫-调研-Scholar抓取与CAPTCHA与下载.md》；工具广度见本人《…无头浏览器过验证-免费.md》。*
