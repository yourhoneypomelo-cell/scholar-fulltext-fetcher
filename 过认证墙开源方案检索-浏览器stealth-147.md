# 过认证墙开源方案检索 · 浏览器 stealth / 反检测专项（强化 route-B）-147

> 交付：**谷歌学术人机认证-155**（worker）｜工单：`task-1a96d0eb-3985-4289-8e72-029acb7514f8`｜2026-07-03。
> **边界（硬约束）**：只读检索 + 写本 md。**未改核心码 / coverage、未发射、未动 git**。落地由 route-B 属主（-141/-144/-157）拍板。
> **检索口径**：8 个候选按「重适配我们浏览器栈（nodriver + 可选 playwright）」的**统一 6 维加权**评分；证据为 2026-07 实时 web 检索（scrapfly / rebrowser / camoufox 官方 / SeleniumBase 官方 / nslsolver / pim97 对比表等）。

---

## 〇、TL;DR（给 route-B 属主）

1. **我们已经站在 2026 的天花板上**：route-B 主引擎 **nodriver**（undetected-chromedriver 的官方继任、CDP 直连真 Chrome、原生反检测、天然不发 `Runtime.enable` 泄露）——多方 2026 评测一致认定「新项目首选」。**换隐身库对 CF 这道门边际收益低。**
2. **真痛点不是指纹、是行为**：165 已用真机实证——RSC 上 CF 盾 nodriver **能过**，卡死的是 **RSC governor 速率/行为门**（`Invalid domain` 坏 reCAPTCHA 不可解）。**隐身库解决的是「像不像人」，解决不了「抓得太快」**——故最高 ROI 仍是 165 的行为面补丁（per-host 限速+冷却+landing 预热+持久档案），**非换库**。
3. **值得吸收的三件小事**（低成本、真增益）：① **nodriver 的 Chrome 146 cookie/`cf_clearance` 回归**（Issue #33 / PR #34 / MyCDP v1.3.4）需盯，可能要扩我们的 `_patch_nodriver_cdp_compat`；② 内置 `tab.cf_verify()`（CF 勾选框自动点，装 opencv 即用）；③ **持久 `user-data-dir` 真实档案**（跨工具共识：nodriver / camoufox / SeleniumBase 都推）。
4. **可选栈升级**：若日后需要 playwright 作兜底引擎，用 **patchright**（Python drop-in、源码级消 `Runtime.enable` 泄露）替代原生 playwright；**camoufox**（Firefox 系、C++ 级指纹）作「最硬指纹门主机」的观察项——但其 **2026 处于维护空档后重建期、releases 实验性不稳**，暂 **HOLD 不落地**。
5. **反面清单（勿采）**：`undetected-chromedriver`（维护放缓、作者已转投 nodriver）、`puppeteer-extra-stealth`（2025-02 起停维、过不了现行 CF）、`FlareSolverr`（底层是 UC、同样衰减 → 建议本项目 flaresolverr 路线降级/退役）。

---

## 一、现状：我们的 route-B 浏览器栈盘点（只读）

| 组件 | 现状 | 源 |
|---|---|---|
| 主引擎 | **nodriver 0.50.x**（异步、CDP 直连、真 Chrome、headful 过 CF） | `render_fetch._nodriver_capture_fn` / `_nodriver_render_fn` |
| 可选引擎 | **Playwright（同步 API）**，延迟导入、未装则优雅降级 | `render_fetch._playwright_render_fn` |
| CDP 兼容补丁 | `_patch_nodriver_cdp_compat()`：已修 **Chrome 133** `requestWillBeSentExtraInfo` 等字段漂移（nodriver 0.50.x 按必选字段解析会崩） | `render_fetch.py` #51-100 |
| B1 取字节 | 浏览器内经 CDP（`Network.getResponseBody` / `Fetch`）截 PDF 字节，绕 CORS/JA3 死结 | `_decode_cdp_body` / `inject_institutional_session` |
| 机构注入 | route-B 导航前注入机构 Cookie(+UA)，同 tab 同 JA3 | `institutional/route_b_bridge.py` + `render_fetch.inject_institutional_session` |
| 反 governor | **缺**（165 已出设计 P1–P6，默认关，待落地） | `选型2026-route-B反RSC-governor补丁方案-165.md` |

**结论**：栈选型本身**已是 2026 最优解**；缺口在**行为面**（governor）与**时效维护**（新版 Chrome 字段/ cookie 漂移），不在「隐身库不够强」。

---

## 二、候选池 · 统一 6 维加权评分（重适配我们栈）

**维度与权重**（面向「我们已是 nodriver/CDP 的 Python 栈、真敌是 CF+行为门」定制）：

| 维度 | 权重 | 含义 |
|---|:--:|---|
| **W1 隐身/反检测强度** | 25% | 对 CF managed / Turnstile / 指纹探针 的对抗（CreepJS/nowsecure 等） |
| **W2 与现有栈契合度** | 25% | 是否 Python、能否 drop-in nodriver/playwright、我们 CDP 取字节路径是否复用 |
| **W3 维护活跃度/时效(2026)** | 20% | 是否跟得上 Chrome/CF 迭代、近期 release |
| **W4 对真痛点(RSC governor 行为门)针对性** | 15% | 能否降低触发速率门/提供行为拟真 |
| **W5 集成成本/侵入性** | 10% | drop-in vs 换栈重写 |
| **W6 资源开销/规模化** | 5% | headless 体积、并发成本 |

**评分（1–5，越高越好）与加权总分**：

| 候选 | 语言/形态 | W1 | W2 | W3 | W4 | W5 | W6 | **加权** | 名次 |
|---|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **nodriver**（现用基线） | Py / CDP 真Chrome | 4.5 | 5 | 4 | 3 | 5 | 4 | **4.33** | **1** |
| **patchright** | Py+Node / Playwright drop-in | 4 | 4.5 | 4.5 | 2.5 | 4 | 4 | **4.00** | **2** |
| **SeleniumBase CDP Mode** | Py / MyCDP | 4.5 | 3 | 5 | 2.5 | 3 | 4 | **3.75** | **3** |
| playwright-stealth | Py / JS 注入 | 2.5 | 4 | 3.5 | 2 | 4.5 | 4 | 3.28 | 4 |
| **camoufox** | Py / Firefox 分支 | 4.5 | 3 | 2 | 2.5 | 2.5 | 4.5 | 3.13 | 5（HOLD） |
| rebrowser-patches | Node / 源码补丁 | 4 | 1.5 | 4 | 2 | 2 | 4 | 2.88 | 6 |
| undetected-chromedriver | Py / Selenium | 2.5 | 3 | 2 | 2 | 3 | 3 | 2.53 | 7（退役） |
| puppeteer-extra-stealth | Node / JS 注入 | 2 | 1 | 1.5 | 1.5 | 2 | 4 | 1.68 | 8（弃） |

> 评分依据见 §三/§四逐条；**nodriver 居首≈「保持现状」是对的**，patchright/SeleniumBase 是「按需增强项」，camoufox 是「观察项」，末四位为「弱/停维/换栈不划算」。

---

## 三、Top 1–3 详评

### 🥇 Top1 · nodriver（保持 + 硬化）— 加权 4.33
- **为何第一**：CDP 直连、无 Selenium/WebDriver 层、原生反检测、**天然规避 `Runtime.enable` 泄露**（这是 CF/DataDome 现行主检测点）；作者即 UC 作者，官方继任；内置 `tab.cf_verify()`（勾选框自动点，需 `opencv-python`）。多篇 2026 评测（scrapfly / nslsolver）判定「新项目/CF/Turnstile 首选」。
- **短板/时效**：**Chrome 146 起 cookie/`cf_clearance` 取值回归**（GitHub Issue #33，PR #34；同类 bug 在 SeleniumBase 由 MyCDP v1.3.4 修复）——CDP cookie 解析器遇新版 Chrome 删字段（如 `sameParty`）会 hang。**我们的 `_patch_nodriver_cdp_compat` 已修 Chrome 133 一类漂移，Chrome 146 可能需同法扩一条**。仍不产 Turnstile token（须真人点/暖会话）。
- **动作**：见 §五「立即」。

### 🥈 Top2 · patchright（作 playwright 兜底引擎的 drop-in 升级）— 加权 4.00
- **定位**：Playwright 的**源码/二进制级**补丁版，**Python 可用**，drop-in 替换 `playwright`。开机前就抹掉 `HeadlessChrome` 标记、`navigator.webdriver`、**`Runtime.enable` 泄露**，故能扛住 `Function.prototype.toString` 这类「JS 注入反被侦测」的陷阱（playwright-stealth 的死穴）。CreepJS 100%→67%、过 nowsecure headless。
- **与我们的关系**：我们主引擎是 nodriver（已无泄露），故 patchright 的价值在**「可选 playwright 路径」**：`render_fetch._playwright_render_fn` 若被启用作兜底，用 patchright 替代原生 playwright 即免费获得源码级隐身。**非必须、但零成本升级**。
- **短板**：仍是指纹/协议层，**对 governor 行为门无解**；highest-security（Akamai/PerimeterX）仍需行为拟真。

### 🥉 Top3 · SeleniumBase CDP Mode（思路借鉴，不整栈迁移）— 加权 3.75
- **亮点**：`activate_cdp_mode()` 断开 WebDriver、纯 CDP 驱动；内置 **`sb.solve_captcha()` / `uc_gui_click_captcha()`** 对 CF Turnstile 有成熟处理（2026 官方 discussion 实证「Ubuntu 下过 Turnstile 无碍」）；维护极活跃（mdmintz）。**Turnstile 现已进闭合 Shadow-root**，其方案是「按加载时序 gui 点击」而非找 iframe——**这个时序技巧值得我们借鉴**。
- **为何不整栈迁移**：采用=引入与 nodriver 并行的第二套栈，W2/W5 成本高；**更划算的是 cherry-pick 其 Turnstile 时序点击思路**补进我们 nodriver 流程。

### 观察项 · camoufox（Firefox 系，HOLD 不落地）— 加权 3.13
- **强在哪**：**C++ 引擎级指纹注入（非 JS）** + BrowserForge 真实分布指纹 + `geoip=True`（tz/locale/WebRTC 一致性），Playwright 兼容 API，headless <200MB；Firefox 比 Chromium 更难被指纹识别。**对「最硬指纹门」是同类最强。**
- **为何 HOLD**：官方明示 **2026 有近一年维护空档、性能回退、新 releases「高度实验性、预期破坏性变更、不适合生产」**；Turnstile 仅 ⚠️（需持久 context 手过）。且 **Firefox 引擎 ≠ 我们 Chrome/CDP 的 B1 取字节路径**（`Network.getResponseBody` 是 Chrome CDP 语义），采用要重写取字节层。→ **列为观察项，待其稳定 + 出现「nodriver 过不了的纯指纹门主机」再评。**

---

## 四、末位候选（勿采，附理由）

| 候选 | 结论 | 理由（2026） |
|---|---|---|
| playwright-stealth | 仅兜底/轻目标 | JS 注入（`addInitScript`），被 `Function.toString`/时序识破，企业级 anti-bot 天花板明显；若要 playwright 直接上 patchright |
| rebrowser-patches | 不适配 | 优秀但**以 Node/npm 为主**（`rebrowser-playwright`）；Python 侧等价物就是 patchright，故我们选 patchright |
| undetected-chromedriver | **退役** | 维护放缓、过不了现行 Turnstile/managed；**作者本人转投 nodriver**。**本项目 `flaresolverr` 路线底层即 UC → 建议降级/退役** |
| puppeteer-extra-stealth | **弃** | 2025-02 起停维、不修 `Runtime.enable`、过不了现行 CF；Node-only |

---

## 五、强化 route-B 的具体建议（分档，均建议 gated·默认关）

### A. 立即（低成本、纯增益、内聚在 nodriver 路径）
1. **盯并预置 Chrome 146 cookie 修复**：跟踪 nodriver Issue #33 / PR #34；若真机命中「过 CF 后 `cf_clearance` 取不到/刷新即丢」，按 `_patch_nodriver_cdp_compat` 同法补一条 Chrome 146 cookie 字段兼容（或锁 nodriver/Chrome 版本、或引 MyCDP v1.3.4 思路）。**时效性最高**。
2. **启用 `tab.cf_verify()`**：CF 勾选框页作为 `blocked:challenge-page` 的一次自动点击尝试（装 `opencv-python`，可选依赖、未装则跳过）。
3. **持久 `user-data-dir` 真实档案**（= 165 P4）：复用历史 cookie/信誉，让 CF/RSC 看「回访人类」；跨工具共识做法。

### B. 短期（与 165 合流，收益最大的是行为面）
4. **落 165 的 P1–P3**（governor 检测 `blocked:rsc-governor` + landing 预热别怼 PDF handler + per-host 限速/冷却退避）——**这才是解 RSC「第二次即死」的正解，隐身库替代不了**。
5. **借鉴 SeleniumBase 的 Turnstile 时序点击**：Turnstile 进闭合 Shadow-root 后，用「等足加载时长再按坐标点」而非找 iframe。

### C. 可选/观察
6. **playwright 兜底路径 → patchright drop-in**：若 `_playwright_render_fn` 被启用，`pip install patchright` + `from patchright.sync_api import sync_playwright` 即源码级隐身升级（保持默认关）。
7. **camoufox 观察**：待其 2026 稳定版 + 出现纯指纹门硬骨头再评；采用需重写 Chrome-CDP 取字节层。

---

## 六、集成示例（示意，未落地；引用真实符号）

**(1) patchright 作可选引擎（改 `render_fetch._playwright_render_fn` 的导入，drop-in）**
```python
def _playwright_render_fn():
    try:
        # 原：from playwright.sync_api import sync_playwright
        from patchright.sync_api import sync_playwright  # drop-in：源码级消 Runtime.enable 泄露
    except Exception:
        return None
    ...
```

**(2) nodriver 内置 CF 勾选框自动点（在 capture 命中 challenge 时试一次）**
```python
# _nodriver_capture_fn 内、判定为 challenge-page 后：
with contextlib.suppress(Exception):
    await tab.cf_verify()      # 需 opencv-python；未装/失败则回退现有 blocked 逻辑
```

**(3) 持久档案（165 P4；nodriver 启动参数）**
```python
# 由 cfg.route_b_user_data_dir 提供路径；默认关，配置后启用
browser = await nd.start(user_data_dir=cfg.route_b_user_data_dir, headless=False)
```

> 以上均为示意，**须 route-B 属主评审后 gated 落地**，并复跑 `run_all_selftests.py` 确认 `RENDER_OK` 稳定绿。

---

## 七、与 165 的关系 & 协作

- **本文（选型/检索）与《选型2026-route-B反RSC-governor补丁方案-165.md》（设计/伪码）互补**：165 定「不触发 governor」的**行为面**打法；本文从**工具面**印证「换隐身库解决不了 governor、且我们已在最优隐身库」，并补 3 件时效性硬化（Chrome146/cf_verify/持久档案）。
- **消费方 = route-B 属主（-141 总指挥在跑 RSC / -144 / -157）**：建议顺序 **A 立即档 → B 短期档（并入 165 P1–P3）**；camoufox/patchright 为观察/可选。已随 `report_task` 回报总指挥统筹排期。

---

## 八、护栏

- 本文为**只读检索 + 写 md**：**未改核心码 / coverage、未发射、未动 git**。
- 所有集成示例为**示意**，落地须 route-B 属主拍板、gated、默认关、默认行为零变更，并过 `RENDER_OK` 离线自检。

---

*核验 2026-07-03（浏览器 stealth 只读检索）｜-155 交付 · 工单 `task-1a96d0eb`。Top1 nodriver(保持+硬化 4.33)｜Top2 patchright(playwright drop-in 4.00)｜Top3 SeleniumBase CDP Mode(借鉴 3.75)｜camoufox HOLD(3.13)｜UC/puppeteer-extra/flaresolverr 退役。核心结论：已在 2026 隐身天花板，真痛点是 RSC governor 行为门（165 正解），换库边际低；最高 ROI = 盯 Chrome146 cookie 修复 + 落 165 P1–P3 行为面。*
