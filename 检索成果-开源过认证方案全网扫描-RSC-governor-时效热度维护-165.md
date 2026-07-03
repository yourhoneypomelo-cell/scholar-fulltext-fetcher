# 检索成果 · 开源「过认证」方案全网扫描（针对 RSC 两道门 · 强调时效/适用/热度/维护）

> 交付：**谷歌学术人机认证-165**｜触发：用户「全网检索有没有开源项目…解决当前过不去认证的难题」+ RSC governor 截图｜检索日 2026-07-02（stars/最近提交均为当日 web 实测）。
> **配套**：本文与《选型2026-route-B反RSC-governor补丁方案-165.md》成对——那篇讲"我们自己怎么改"，本篇讲"业界有哪些现成开源可借力/替换"。

---

## 〇、先把问题说死：你卡的是「第二道」，开源救不了那张验证码

- **图1 Cloudflare Turnstile**：你们的 nodriver 真 Chrome **已能过**（经验记录 N.1/N.4 实证）。这一层开源选择很多、且成熟。
- **图2 RSC `crawlprevention/governor` 的 reCAPTCHA**：报 `ERROR for site owner: Invalid domain for site key` = **site key 与域不匹配的「坏」验证码**——**真人点不过、2captcha/anticaptcha 也解不了**（打码平台需要有效 site_key + 正确域）。它是**按速率/行为触发的软封**（"第一次过、第二次死"）。
- **所以结论不变**：**没有任何开源项目能"解"这张 reCAPTCHA**。开源的真正价值在两处 ——
  1. **降低"被判定为 bot"的概率**（更真的指纹 + 干净启动参数，去掉图2 那条 `--disable-blink-features=AutomationControlled` 横幅）→ 让 governor **压根不触发**；
  2. **过第一道 CF** 更稳、可复用会话 cookie。
  - 而**速率/行为 governor** 只能靠 **限速 + landing 预热 + 住宅代理 + 会话复用**（＝ -165 补丁方案）压制，任何单一开源都不"开箱"覆盖 RSC 这个自家 governor。

---

## 一、候选开源横评（2026-07-02 实测 stars / 最近提交）

| 项目 | 热度(stars) | 时效/维护(最近提交·版本) | 引擎/隐身手段 | 对本难题的适用性 |
|---|:--:|---|---|---|
| **Scrapling** (D4Vinci) | **≈66k**（2026-02 GitHub Trending #1） | 活跃：push 2026-06-26 / v0.4.9 2026-06-07 | 编排层：`StealthyFetcher`(底层 Camoufox)+`solve_cloudflare=True`；HTTP `Fetcher` 带 TLS 指纹/HTTP3；持久会话+代理轮换+spider | ⭐**最推荐调研**：一层把"隐身浏览器+CF 求解+会话+代理轮换"打包，能直接顶替你们一部分 route-B 脚手架 |
| **camoufox** (daijro→Clover Labs) | ≈9.2k | push 2026-06-23 / v150.0.2 2026-05-11（**2026 新版实验性**） | Firefox **C++ 级**指纹伪装(canvas/WebGL/字体) | ⭐**指纹层最强**(CreepJS 0%)；但 2026 有过维护空档、新版不稳。适合"被指纹卡"时上 |
| **DrissionPage** (g1879, 国产) | ≈12k | push 2026-06-05 / v4.1 | 浏览器控制 + shadow-DOM 穿透 | 热度高、中文文档全、能处理 CF shadow DOM；但对最新 CF(PAT/行为分析)也吃力 |
| **botasaurus** (omkarcloud) | ≈4.8k | push 2026-03-18 | Selenium 系 + **Bézier 鼠标/拟人行为** + CDP 事件；`bypass_cloudflare=True` | 拟人**行为**层强——正好对"速率/行为 governor"有帮助 |
| **Byparr** (ThePhaseless) | ≈1.6k | 活跃：push 2026-06-11 / v2.1 2026-02-08 | **FlareSolverr 直替**(同 API/8191)，底层 **Camoufox** | ⭐你们已提过；FlareSolverr 停摆后的**活跃替代**，返回 cookie/headers。适合替换现有 FS shim |
| **zendriver** (cdpdriver) | ≈1.3k | 活跃：push 2026-04-19 / v0.15.3 2026-03-12 | **nodriver 活跃分叉**：CDP、`asyncio.run`(非 uc.loop)、**官方 Docker**、cookie 持久化、typed CDP | ⭐**对你们最省事**：你们正用 nodriver 且撞到"未合并 bugfix/CDP schema 漂移"，zendriver 恰好把这些补了(某基准 75% vs nodriver 25%) |
| **patchright** (Kaliiiiiiiiii-Vinyzu) | ≈1.4k(py，月下载 330 万) | 活跃：commit 2026-06-03 / v1.61.1 | **Playwright 直替**：修 `Runtime.enable`/`Target.setAutoAttach` CDP 泄漏；`channel=chrome` 用真 Chrome | 若改走 Playwright 栈时的隐身首选；纯 Chromium fork 风险最小 |
| **SeleniumBase CDP Mode** (mdmintz) | 大项目·很活跃 | 活跃(2026 持续) | UC Mode→**CDP Mode**(MyCDP)，`solve_captcha()`(不再靠 PyAutoGUI) | 免费方案里对 **Turnstile** 可靠；但 `solve_captcha` 面向"正常"验证码，对 RSC 坏 reCAPTCHA 无效 |
| nodriver (ultrafunkamsterdam) | ≈2.3k | **维护受限**(PR/issue 多不处理) | 你们**现用** | 协议级仍强(某基准 28/31、0 block)，但贡献受限 → 建议迁 zendriver |

> 说明：某第三方基准(31 CF 目标)显示 **nodriver/zendriver > Patchright/Camoufox/CloakBrowser > 原生 Playwright/rebrowser**；且 **curl_cffi 裸 HTTP 都能过 26/31**——印证你们 N.3「能不能过 CF」与「能不能下到 PDF(JA3)」要分开看。

---

## 二、对本项目（已用 nodriver + curl_cffi + FS shim）的落地建议

**按"改动小→收益大"排序：**

1. **nodriver → zendriver（最低成本升级）**：API 几乎一致、迁移平滑；直接吃到"未合并 bugfix + CDP typed 事件 + Docker + cookie 持久化"，正好治你们 N.4 记的 `KeyError: localNetworkAccessRequestPolicy` CDP schema 漂移与偶发 `Event loop is closed`（zendriver 用标准 `asyncio.run`）。**建议先在 route-B 抓字节路径小样本对照 zendriver vs nodriver 通过率。**
2. **去掉自动化指纹**：不管用谁，**都别再传 `--disable-blink-features=AutomationControlled`**（图2 那条横幅就是它触发的、是明信号）；用持久 `user-data-dir` 真实档案复用 cookie。
3. **Scrapling 作"编排层"调研**：`StealthyFetcher(solve_cloudflare=True)` + 持久会话 + 代理轮换，能顶替一部分 route-B 脚手架；可作为 RSC 桶的**独立对照通道**跑 A/B，而非马上替换主链。
4. **住宅代理（规模化必需）**：几乎所有资料都强调——`cf_clearance` 绑 IP，**数据中心 IP 必被 RSC governor 盯死**；RSC 桶要稳过第二道，住宅/移动 IP 是硬门槛。
5. **行为层（botasaurus 思路）**：Bézier 鼠标轨迹 + 随机停留，喂给"速率/行为 governor"降可疑度——可借鉴其实现，不必整包引入。
6. **Byparr 替换 FS shim（可选）**：若继续走"solve 拿 cookie"路线，Byparr(Camoufox 底)比停摆的 FlareSolverr 更活跃；但**对 RSC 绑 JA3 站，solve→回放仍 403（N.3）**，故 Byparr 对 RSC 帮助有限，价值在其他 CF 站。

---

## 三、给 RSC「第二道 governor」的现实结论

- **能显著帮忙**：zendriver / Camoufox / Scrapling / patchright（**降低被判定 → governor 少触发**）+ **住宅代理** + **行为拟人**。
- **帮不上**：任何"验证码求解器"（2captcha/anticaptcha/SeleniumBase `solve_captcha`）——因为图2 是 **Invalid-domain 的坏 reCAPTCHA**，不可解。
- **真正的解法组合** = **(更强隐身开源，如 zendriver/Camoufox) + (住宅 IP) + (-165 补丁方案：landing 预热不怼 PDF handler + per-host 限速/冷却)**。三者缺一，RSC "第二篇即死"就治不干净。

---

## 四、来源（2026-07-02 实测）

- zendriver `github.com/cdpdriver/zendriver`（1.3k，push 2026-04-19，v0.15.3）；ByteTunnels nodriver-vs-zendriver 基准。
- camoufox `github.com/daijro/camoufox`（9.2k，commit 2026-06-23，v150.0.2；2026 维护空档后 Clover Labs 接手，新版实验性）。
- Scrapling `github.com/D4Vinci/Scrapling`（66k，push 2026-06-26，v0.4.9；`StealthyFetcher.solve_cloudflare`）。
- DrissionPage `github.com/g1879/DrissionPage`（12k，push 2026-06-05）。
- botasaurus `github.com/omkarcloud/botasaurus`（4.8k，push 2026-03-18，`bypass_cloudflare=True`）。
- Byparr `github.com/ThePhaseless/Byparr`（1.6k，push 2026-06-11，v2.1；FlareSolverr 直替/Camoufox 底）。
- patchright `github.com/Kaliiiiiiiiii-Vinyzu/patchright-python`（1.4k，commit 2026-06-03，v1.61.1）。
- SeleniumBase CDP Mode `seleniumbase.io/examples/cdp_mode`（`solve_captcha()`；维护者 mdmintz 2026 持续答疑）。
- 基准：`ianlpaterson.com` 2026 anti-detect benchmark（31 CF 目标）；`unifuncs.com` 2026 headless 横评。

---

*-165 交付 · 2026-07-02。全网时效检索（stars/最近提交当日实测）。核心判断：本难题第二道是 RSC governor 坏 reCAPTCHA（不可解），开源价值在"降判定+过 CF+会话/代理"，落地首选 nodriver→zendriver + 住宅代理 + -165 反 governor 补丁。*
