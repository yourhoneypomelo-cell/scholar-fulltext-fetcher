# 检索成果 · 让「两道认证一定能完成」的分层方案（CF Turnstile + RSC governor）

> 交付：**谷歌学术人机认证-148**｜触发：用户「这两个服务商的认证一定要能完成」+ 两张截图（RSC governor reCAPTCHA / Cloudflare Turnstile）+「全网检索项目、关注热度/维护/时效、据此提方案」｜检索日 2026-07-03（stars/最近提交/价目均为当日 web 实测）。
> **定位**：本文**推进** -165《开源过认证方案全网扫描》与《route-B 反 RSC-governor 补丁方案》、-160《RSC 0/8 归零因》——补上 -165 没讲透的那一层：**「一定能完成」的保底架构 = 人在环 + 持久真实档案**，并用 2026-07 新鲜检索刷新选型。
> **边界**：research + 设计，**未改生产码**；route-B/render_fetch 属 -141/-144/-157，落地需属主拍板、避开跑批抢头锁。合规见 §六。

---

## 〇、结论先行（TL;DR）

**两道门本质不同，"一定能完成"必须分开谈：**

| 门 | 截图 | 本质 | 能否"一定完成" | 怎么完成 |
|---|---|---|---|---|
| ① **Cloudflare Turnstile** | 图2「Are you a robot?」 | 指纹+行为+网络评分的**人机验证**（可过） | ✅ **能** | 自动:nodriver/zendriver 真 Chrome（2026 bench **0 blocked**）；兜底:人工点一次 / 商用解 token |
| ② **RSC `crawlprevention/governor`** | 图1「unusual traffic」+ reCAPTCHA `Invalid domain for site key` | RSC 自家**速率/行为软封**，发的是**坏 reCAPTCHA**（真人/打码平台都解不了） | ✅ **能，但只能靠"不触发 + 人在环暖会话"** | **不解那张码**：landing 预热 + per-host 限速/冷却 + 持久真实档案 + 必要时人工在有头窗口过一次 |

> **一句话**：CF Turnstile 是"可解的验证"，用更干净的自动化就能过；RSC governor 那张是"**坏码**"，任何求解器都无效——**保证完成的唯一现实解 = 让流程能退回"人点一次 + 复用暖会话"，同时用工程手段让 governor 尽量不出现**。这正是成熟学术下载生态（ref-downloader / auto-paper-harvester）的做法。

---

## 一、为什么"一定能完成"必须靠分层（关键判断）

1. **CF Turnstile ≠ RSC 那张 reCAPTCHA**。Turnstile 是 Cloudflare 的无感人机验证，正规站点用它保护表单/入口，**真人能过、自动化也能过**（下文 bench）。RSC governor 弹的是 **Google reCAPTCHA v2 且报 `ERROR for site owner: Invalid domain for site key`** —— site key 与域不匹配，**真人点了也不算数、2captcha/CapSolver 也解不了**（打码平台要有效 site_key+正确域）。-165 已实锤，本波不推翻。
2. **决定成败的主因是"自动化协议指纹"，不是 IP / 不是 TLS**（2026 bench 结论）。两张截图顶栏那条 `--disable-blink-features=AutomationControlled` 就是**明信号**——去掉它、去掉 Playwright shim，比换代理更管用。
3. **"一定能完成"= 必须给出一条不依赖"解码"的保底路**。既然 RSC 那张坏码不可解，唯一能对用户承诺"一定完成"的，是**人在环**：有头窗口 + 用户真实登录档案，人过一次认证、cookie 落档、后续复用暖会话。工程隐身与反 governor 只是**降低人被叫起来的频率**，不是替代。

---

## 二、全网检索刷新（2026-07-03 实测 · 热度/维护/时效/适用）

### 2.1 隐身浏览器引擎（过 CF Turnstile 的主力）

| 项目 | 热度(stars) | 维护/时效 | 关键能力 | 对本难题适用性 |
|---|:--:|---|---|---|
| **nodriver**（你们现用） | ≈2.4k | 活跃但**贡献受限**(PR 多不并) / AGPL-3.0 | 直连 CDP、无 Playwright shim | ⭐ 2026 bench **28/31 OK、0 blocked**（唯一零封），Turnstile 站 canadianinsider 只有它过。**先别急着换** |
| **zendriver**（nodriver 活跃分叉） | **1.31k**（40 releases、30 贡献者） | **很活跃**:push 2026-04-19 / v0.15.3、**官方 Docker** / AGPL-3.0 | CDP、`asyncio.run`、cookie 持久化、**内置 `verify_cf` 自动过 shadow-root Turnstile** | ⭐**最省事升级**:API 近同、补齐 nodriver 未并 bug + CDP 漂移，`verify_cf` 直接顶 Turnstile 交互码 |
| **patchright**（Playwright 直替） | 3.2k | 活跃:v1.61+ / channel=chrome 真 Chrome148 / Apache-2.0 | 修 `Runtime.enable`/`Target.setAutoAttach` CDP 泄漏 | 走 Playwright 栈时首选；但 bench 里对 Turnstile 最硬的关（canadianinsider）**没过**——CDP 补丁不治协议层 |
| **camoufox**（Firefox 系） | ≈9.2k | push 2026-06-23（2026 有维护空档、新版实验性）/ MPL-2.0 | C++ 级指纹伪装（CreepJS 0%） | 指纹层最强；**Docker 内 Turnstile 静默失败**(issue #574)，须跑宿主机 |
| **SeleniumBase CDP Mode** | 大项目·很活跃 | 持续维护 | UC/CDP Mode + `uc_gui_click_captcha`/`solve_captcha()` | 免费方案里对**交互式 Turnstile 点击**很可靠；对 RSC 坏码无效 |
| **botasaurus** | ≈4.8k | push 2026-03 | `bypass_cloudflare=True` + Bézier 拟人鼠标 | 行为层强，正对"速率/行为 governor"降可疑度 |
| **Scrapling**（编排层） | ≈66k | 活跃 v0.4.9 | `StealthyFetcher(solve_cloudflare=True)`+会话+代理轮换 | 一层打包"隐身+CF解+会话"，可作 RSC 桶 A/B 对照通道 |

**2026 bench 硬结论（同一残差住宅 IP、有头、31 CF 目标、651 判定）**：nodriver 28/3/0（**唯一 0 blocked**）＞ curl_cffi 26 ≈ patchright 25 ≈ camoufox 25 ＞ 原生/rebrowser Playwright 24。**主因是"怎么驱动浏览器"的协议指纹**；**住宅代理单独不救**——"形状一致性"被破坏（Linux VPS+住宅代理反而更容易被封）；浏览器必须跑在**拥有该 IP 的宿主机**上。→ 你们在**用户本机真 Chrome**跑，天然形状一致，占优。

### 2.2 商用打码（仅对"正常码"，**不解 RSC 坏码**）

| 服务 | reCAPTCHA v2 | CF Turnstile | 成功率/时延 | 模式 |
|---|:--:|:--:|---|---|
| **CapSolver** | $0.80/1k | $1.00–1.20/1k | 91–95% / 3–8s、**按成功计费** | 纯 AI、`createTask`(AntiTurnstileTaskProxyLess)→轮询 token |
| **2captcha** | $1–2.99/1k | $1.45/1k | 96–99% / 13–40s | AI+人工混合、`in.php`/createTask |
| CapMonster/Anti-Captcha | $0.5–0.8/1k | 支持 | ~99% | AI/人工 |

> **用法**:抓 `websiteKey`+`websiteURL` → 拿 token → 注入表单字段。**仅适用于站点内嵌 Turnstile / 正规 reCAPTCHA**；对**CF 全页 Managed Challenge 插页**与 **RSC `Invalid domain` 坏码均不可靠/无效**。定位=**其它出版商正常码的自动兜底**，非 RSC 解药。

### 2.3 学术下载生态（"一定能完成"的现实范本）

| 项目 | 做法 | 对本项目的启示 |
|---|---|---|
| **ref-downloader** | 驱动**用户真实 Edge 档案**，institutional 登录直接带过；17+ 出版商专用路径（含 Wiley PDFDirect）；SSO/CAPTCHA **检测不解**→`manual_pending` | ⭐ RSC/ACS 等归为 **browser_only**：不"破盾"，**复用用户已登录会话** |
| **auto-paper-harvester** | TDM API→OA→**`--use-browser-fallback` Playwright 复用机构 cookie**（ACS/RSC/IEEE/AIP/IOP/APS）；首跑开窗人工登录一次，档案持久化 | ⭐ 明确把 ACS/RSC/... 列 `browser_only`：**只有复用机构 SSO 会话这一条现实路** |
| paper-fulltext-harvest (skill) | 同上三层路由，浏览器兜底跑登录档案 | 佐证"人在环+暖档案"是业界共识 |

**共识**：面向 RSC 这类"自家 governor + 订阅墙"的站，**没有"纯自动破解"**；成熟做法都是**人过一次、机器复用暖会话**（对有合法机构订阅者，这既合规又可靠）。

---

## 三、解决方案：四层，越靠上越"一定"，越靠下越"省人"

> 设计原则：**保底在人、提效在机**。Tier-0 保证"一定能完成"，Tier-1~3 让 Tier-0 尽量少被触发。全部 gated·默认关·默认零变更。

### Tier-0 · 保底：人在环 + 持久真实档案（THE「一定能完成」）
- **有头**真 Chrome + **持久 `user-data-dir`**（可指向用户真实档案或专用暖档案），**去掉 `--disable-blink-features=AutomationControlled`** 等泄漏 flag。
- 首跑：用户在该窗口**完成机构 SSO + 手点任何 CF Turnstile / 正规 reCAPTCHA**（RSC 若弹坏码则退避重试而非硬点）。cf_clearance/SSO/session cookie **落档持久**。
- 后续：流程**复用这份暖会话**抓字节；仅当会话失效/再弹认证时才再次叫人（`needYou`）。
- ⇒ CF Turnstile：人一定能点过；RSC governor：暖人类会话极少弹，弹了正规码人点、坏码退避——**对用户可承诺"完成"**。

### Tier-1 · 自动隐身（把"叫人"频率压到最低）
1. **引擎:nodriver → zendriver 平滑升级**（吃 `verify_cf` 自动过 shadow-root Turnstile + 未并 bug 修复 + Docker + cookie 持久化）；先在 route-B 抓字节路径做 **zendriver vs nodriver 小样本 A/B 通过率**再定。
2. **去自动化指纹**：删 `--disable-blink-features=AutomationControlled`；隐藏 `navigator.webdriver`；持久真实档案。
3. **形状一致性**：浏览器跑在**拥有出口 IP 的宿主机**；**不要** Linux VPS 前挂住宅代理（=制造矛盾、更易封）。

### Tier-2 · 反 RSC governor（-165 六点，落地①②③收益最大）
- ① governor 检测 → `blocked:rsc-governor`（与 CF 分开）；含 `Invalid domain` 再细分 softblock。
- ② **landing 预热**：入口永远喂文章 landing（由 DOI 推），**绝不直导航 `ArticlePdfHandler.ashx`**；页内解析 articlepdf 后**同会话 `fetch().arrayBuffer()`** 取字节。
- ③ **per-host 限速 30–90s + 命中即冷却**（5→30min 指数退避、冷却期跳过记 `deferred`）。
- ④ 去自动化 flag + 持久档案（同 Tier-1）；⑤ 坏码**不硬解**（直接冷却）；⑥ 暖会话/住宅或移动 IP/配额化（规模化）。

### Tier-3 · 商用解兜底（**仅正常码**，不含 RSC）
- CapSolver `AntiTurnstileTaskProxyLess`/reCAPTCHA v2 任务：抓 sitekey+URL→token→注入，作**其它出版商内嵌正常码**的自动兜底；**RSC `Invalid domain` 坏码显式跳过、绝不调用**（避免白花钱+违背 -165 结论）。gated、默认关、需用户自备 key。

---

## 四、本仓集成点（供属主评审）

| 层 | 触点（现状） | 建议动作 |
|---|---|---|
| Tier-0 人在环 | `render_fetch.py`（headless 参数）；无"暖档案+叫人"闭环 | 新增 gated **assisted 模式**：`cfg.route_b_user_data_dir` + 有头 + 检测到认证→经 pchat `needYou` 叫人过一次→落档复用 |
| Tier-1 引擎 | `render_fetch._nodriver_capture_fn` / `is_ja3_bound_cf_host` | 加 zendriver 后端开关，A/B 对照；统一去 `--disable-blink-features=AutomationControlled` |
| Tier-2 governor | `render_fetch` capture 判定 / `download._browser_capture_fallback` / `_static_pdf_fallbacks` | 落 -165 ①②③（检测+预热+per-host 冷却）；入口改喂 landing 而非 articlepdf 直链 |
| Tier-3 打码 | 无 | 新增可选 `captcha_solver`（CapSolver 客户端），gated、仅正常码 |

---

## 五、落地排序 + 协作

**改动小→"一定能完成"收益大排序：**
1. **Tier-0 assisted 模式（人在环+暖档案）** —— 直接兑现"认证一定能完成"，且改动内聚、风险低（有头+持久档案+叫人）。**首选先做。**
2. **去 `--disable-blink-features=AutomationControlled` + 持久档案**（Tier-1.2/1.3）—— 一行级、全局降判定。
3. **-165 ②landing 预热 + ③per-host 冷却**（Tier-2）—— 治 RSC "第二篇即死"。
4. **nodriver→zendriver A/B**（Tier-1.1）—— 中期，吃 verify_cf + 维护红利。
5. **CapSolver 兜底**（Tier-3）—— 可选，面向其它社正常码。

**协作**：route-B 强耦合方 **-141（协调者/RSC 跑批）、-144、-157**。建议本方案经 -141/-144 评审；-165 已有补丁设计，本文补齐 **Tier-0 保底架构 + 2026 选型刷新**，落地避开 RSC 跑批窗、勿抢头锁。

---

## 六、合规声明

本方案仅供**拥有合法机构订阅/对内容有访问权**的用户，在**已获授权**前提下经机构 SSO/EZproxy 正常取用全文，并**完成正规人机验证**（证明"你是有权访问的真人"）；**不得用于绕过付费墙或任何访问授权**。RSC 坚持"不硬解坏 reCAPTCHA"，正是拒绝任何"破解验证"路径、只做"降低误判 + 人过一次"的体现。无有效订阅时，直链返回 401/403/落地页，由 `download.py` 的 `%PDF` 魔数 + 内容 QC 门自动过滤，**不产生假成功**。

---

## 七、来源（2026-07-03 实测）

- Ian L. Paterson《Anti-detect browser benchmark 2026》(7 工具/31 CF 目标/651 判定，住宅 IP)：nodriver 28/0 blocked；主因=自动化协议指纹；住宅代理单独不救(形状一致性)。
- zendriver `github.com/cdpdriver/zendriver`（1.31k，push 2026-04-19，v0.15.3，官方 Docker，`verify_cf`）；zendriver.dev/advanced/cloudflare-bypass（仅交互式 checkbox、非图选码）。
- patchright（3.2k，channel=chrome Chrome148）；camoufox（9.2k，issue #574 Docker 内 Turnstile 失败）；SeleniumBase CDP Mode（`uc_gui_click_captcha`）；botasaurus（4.8k，`bypass_cloudflare`）；Scrapling（66k，`solve_cloudflare`）。
- CapSolver 价目/成功率（reCAPTCHAv2 $0.80/1k·95%；Turnstile $1.0–1.2/1k·91%，按成功计费）；2captcha（Turnstile $1.45/1k·96%）；CaptchaAI《Turnstile Interception Methods》(token stub/注入)。
- 学术下载生态：ref-downloader（驱动用户 Edge 档案、SSO 检测不解）、auto-paper-harvester（`--use-browser-fallback` 复用机构 cookie，ACS/RSC=browser_only）、paper-fulltext-harvest skill。
- 本仓：-165《开源过认证方案全网扫描》《route-B 反 RSC-governor 补丁方案》、-160《RSC 0/8 归零因》、经验记录 N.1/N.3/N.4。

---

*-148 交付 · 2026-07-03。research+设计、未改生产码。核心新增：**「一定能完成」= Tier-0 人在环+暖档案（保底）+ Tier-1~3 隐身/反governor/打码（省人）**；RSC 坏码仍不可解，靠不触发+人过一次。*
