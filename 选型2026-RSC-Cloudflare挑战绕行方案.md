# 选型 2026 · RSC / Cloudflare「Just a moment」OA 全文绕行方案

> 调研者：谷歌学术人机认证-176（worker）｜任务：`task-805f7122-5aeb-49c3-b292-eb9692421cad`
> 范围：纯离线调研 + 新建本 1 个 md，**未改任何 `.py`**、未联网抓 RSC 正文。
> 目标：为「`pubs.rsc.org` 被 Cloudflare JS 挑战 100% 拦截（batch6 实测 154 次 0 成功）」找 2026 时效的免费/开源/自托管最优绕行方案，评估有效性/维护/许可证/部署成本，给明确推荐与落地改动点。

---

## 〇、TL;DR（先看结论）

1. **不建议为 batch6 的 RSC 单独上 FlareSolverr。** 关键事实：batch6 现行 82% 口径下 **RSC 净 MISS = 0**——`pubs.rsc.org` 虽 100% 被 CF 挡，但这些 RSC 文章已被 **`websearch` 从他站（ResearchGate/机构库/预印本）兜底回收**。为 RSC 上 CF 破盾的**边际收益≈0**。
2. **「Just a moment」是 Cloudflare 的 JS/托管挑战 → HTTP 层工具（`curl_cffi`/`cloudscraper`）原理上过不了**（项目已实测 curl_cffi TLS 伪装失败，与调研一致）。要过必须用**能执行 JS 的真实浏览器**。
3. **若要一个通用的 CF「Just a moment」能力（惠及 batch4/batch7 等，而非仅 RSC）**，最省事路径是**复用仓库已有件**，无需新造轮子：
   - **首选：激活 `render_fetch.py` 里已内置但未安装的 `nodriver` 引擎**（`pip install nodriver` 即可，无需 docker）。nodriver = undetected-chromedriver 作者的继任者、CDP 直连、社区口碑 CF 通过率最高（~90%）、活跃维护。**改动量近乎零。**
   - **次选：`patchright` 一行替换现有 Playwright 引擎**（drop-in，补 CDP 泄漏；须 `launch_persistent_context + channel="chrome" + headless=False`）。
   - **已有兜底：`flaresolverr.py`**（自托管 FlareSolverr，仍在维护 v3.5.0/2026-05）——适合「浏览器解一次挑战 → 拿 `cf_clearance` cookie+UA → 交给现有 `http_client` 直下 PDF」的 cookie 引导模式；但要跑 docker 服务、每请求一个无头浏览器，重且脆。
4. **预计可回收**：RSC（batch6）≈ 0；跨批（batch4 的 CF-403 约 27 条 + batch7）**净增量约 5–15 条**（其中不少也会被 websearch 覆盖）。**部署成本**：nodriver = `pip install` + ~300MB Chromium、无服务；FlareSolverr = docker 服务 + ~1GB 镜像 + 每并发一个浏览器的 CPU/RAM。

> 一句话：**别为 RSC 上 FlareSolverr；要通用 CF 能力就先 `pip install nodriver` 点亮已有的 render_fetch 引擎，性价比碾压其它方案。**

---

## 一、背景与现有集成盘点（仓库里已经有什么）

| 组件 | 位置 | 现状 | 与本任务关系 |
|---|---|---|---|
| **FlareSolverr 客户端** | `fulltext_fetcher/flaresolverr.py` | 已实现、**默认关**（未配置/连不上即优雅返回 None）。`solve()` 返回 `html + cookies(含 cf_clearance) + user_agent`；`fetch_via_flaresolverr()` 返回过盾后 HTML。纯 urllib，无第三方依赖。 | 现成的「解挑战 + 取 cookie/UA」入口，只差一个 docker 服务和调用点 |
| **无头渲染兜底** | `fulltext_fetcher/render_fetch.py` | 已实现、**默认关**。`render_get_pdf_url(url, engine=auto\|playwright\|nodriver)`，渲染后复用 `landing.extract_pdf_links` 抠 PDF 直链；强限流 2s；合规守卫**永不渲染 Scholar**。**`nodriver` 已是内置可选引擎，只是没装依赖**。 | **最省事的 CF 破盾落点**——nodriver 本身就是顶级 CF 绕行器 |
| **TLS 指纹客户端** | `http_client.py` / 现有 `curl_cffi` 尝试 | 已试 `curl_cffi` TLS 伪装，**过不了 RSC 的 JS 挑战** | 印证：HTTP 层不够，必须上浏览器 |

**结论**：破 CF 的「浏览器」和「cookie 引导」两条腿仓库都已铺好，本任务本质是**选哪条腿 + 装依赖 + 接一个调用点**，不是从零选型。

---

## 二、为什么 HTTP 层工具过不了 RSC

Cloudflare 的拦截是**分层复合信任分**：TLS/JA3-JA4 指纹 + HTTP/2 指纹 + **JS 挑战执行** + 行为分 + Turnstile。RSC 的「Just a moment…」页含 `cf_chl` / `__cf_chl` / `window._cf_chl_opt`，属**托管/JS 挑战**，必须在真实浏览器里**执行那段 JS** 才能拿到 `cf_clearance`。

- `curl_cffi` / `curl-impersonate`：只伪装 **TLS/JA3-JA4**，**不执行 JS** → 仅能过「纯 TLS 门」，对「Just a moment」**无效**（项目已实测失败）。
- `cloudscraper`：内置 JS 解释器解**老式 IUAM**，但对 2026 的 v2/v3 Bot Management、Turnstile、重指纹站**成功率低**；主库最后发布 3.0.0（2025-06），活跃度一般，社区多个「AI/Gemini」小 fork 不可靠。

→ **要过 RSC 必须用能跑 JS 的真实（且反检测的）浏览器**：FlareSolverr / nodriver / patchright / Camoufox。

---

## 三、方案对比表（2026 时效）

| 方案 | 原理 | 对 CF「Just a moment」JS 挑战 | 维护/热度（2026） | 许可证 | 部署成本 | headless | 已在本仓库? |
|---|---|---|---|---|---|---|---|
| **nodriver** ✅ 首选 | CDP 直连 Chrome、无 webdriver 标志（uc 作者继任者） | **强**（社区口碑 ~90%） | 活跃、热度高 | MIT | `pip install` + Chromium，**无服务** | 支持（但 headless 更易被测，建议 headful/新头） | **是**（render_fetch 内置引擎，未装依赖） |
| **patchright** ✅ 次选 | 源码级 patch Playwright，补 `Runtime.enable`/CDP 泄漏 | **中–强**（须 persistent_context+channel=chrome+headful；README 称过 CF/Kasada/Akamai，第三方评测对纯 JS 挑战有保留） | 活跃、上升 | Apache-2.0 | `pip install patchright` + Chrome | 需 headful 才生效 patch | 否（可 1 行替换现有 Playwright 引擎） |
| **FlareSolverr** ◻ 已集成兜底 | 自托管代理，undetected-chromedriver 驱动 Chromium 解挑战，回传 HTML+cookies+UA | **中**（解 IUAM + 部分 Turnstile；托管挑战/行为分常超时失败，见 issue #1675） | 维护中（v3.5.0 2026-05，加 Turnstile、更新 CF 选择器） | MIT | **docker 服务** + ~1GB 镜像 + 每并发一浏览器 | 服务内置 | **是**（flaresolverr.py 客户端，默认关） |
| **Camoufox** ◻ 强但重 | 改 Firefox C++ 引擎级指纹伪装，Playwright 兼容 API | **强**（重指纹站最强，~80% 恢复中） | Beta（v146 2026-01，实验性） | MPL-2.0（Firefox 系） | 自定义 Firefox 构建，较重 | 支持 | 否 |
| **cloudscraper** ✗ 不荐 | requests + JS 解释器解老式 IUAM | **弱**（v2/v3/Turnstile 基本不行） | 主库缓慢、fork 杂 | MIT | `pip install`，轻 | N/A（无浏览器） | 否 |
| **curl_cffi** ✗ 不荐(单用) | TLS/JA3-JA4 伪装、无浏览器 | **无效**（不执行 JS，项目已实测） | 活跃 | MIT | `pip install`，最轻 | N/A | 部分（TLS 层已用） |

> 通用规律（多篇 2026 评测一致）：**没有银弹**，任何开源绕行都要跟着 CF 更新打补丁；**IP 信誉**是独立信号，量大时需住宅代理。

---

## 四、最省事路径（只要 OA/free-to-read 全文 PDF）

目标不是「全站解挑战」，而是「拿到那一篇 OA PDF」。两种落地形态：

**形态 A（推荐，渲染直取 PDF）**：用反检测浏览器（nodriver/patchright）打开 OA 落地页 → 页面 JS 注入 PDF 链接 → 复用 `render_fetch.py` 的 `landing.extract_pdf_links` 抠直链 → 下载。**render_fetch.py 已实现这条链，只差装引擎。**

**形态 B（cookie 引导 + 现有下载器）**：浏览器/FlareSolverr **解一次挑战**拿 `cf_clearance` cookie + 匹配 UA → 把 cookie+UA 塞回现有 `http_client` **对同域直下 PDF**（多篇调研推荐的「bootstrap cookies then requests」范式）。`flaresolverr.solve()` 已返回 `cookies`+`user_agent`，天然支持。**注意**：cf_clearance 与「IP+UA」绑定，复用时三者必须一致。

---

## 五、明确推荐（分层，按 ROI 从高到低）

1. **点亮 nodriver（首选，改动近零）**：`pip install nodriver`；recovery profile 里把「被 CF-403/『Just a moment』挡下」的 OA 落地页路由到 `render_get_pdf_url(url, engine="nodriver")`，拿到 `pdf_url` 后走现有下载器。合规守卫（永不渲染 Scholar）与强限流已就绪。
2. **patchright 作为 Playwright 的强化替身（次选）**：现有 `_playwright_render_fn` 检测率升高时，加一个 `_patchright_render_fn`（见 §六），无缝纳入引擎工厂表。
3. **FlareSolverr 仅在「需要大批 cookie 引导 / 不想在业务进程内跑浏览器」时启用**：跑 docker，遇 CF 时 `flaresolverr.solve()` 取 cookie+UA → `http_client` 复用直下。
4. **Camoufox 仅当 Chrome 系（nodriver/patchright）都被 RSC 持续识别时**再上（Firefox 引擎级，更强但重、Beta）。
5. **不采用**：`cloudscraper`（对现代 CF 成功率低）、`curl_cffi` 单用（不执行 JS，已实测过不了 RSC）。

---

## 六、落地改动点（接到现有代码；本任务不改，仅给方案）

**① 激活 nodriver（0 代码，仅装依赖）**
```bash
pip install nodriver   # render_fetch.py 的 _nodriver_render_fn 立即可用
python -m fulltext_fetcher.render_fetch "https://pubs.rsc.org/en/content/articlelanding/....." --engine nodriver
```
在 recovery 源 profile 中，对 CF 命中项调用 `render_get_pdf_url(url, engine="nodriver")` 取 `pdf_url` → 交 `download.py`。

**② patchright drop-in（在 `render_fetch.py` 仿 `_playwright_render_fn` 新增工厂）**
```python
def _patchright_render_fn():
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        return None
    def _render(url, timeout):
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir="./.patchright_profile",
                channel="chrome", headless=False, no_viewport=True)  # patch 生效前提
            try:
                page = ctx.new_page()
                page.goto(url, timeout=int(max(timeout,1)*1000), wait_until="domcontentloaded")
                page.wait_for_timeout(3000)  # 给 CF 挑战通过时间
                return page.content(), page.url
            finally:
                ctx.close()
    return _render
# 注册进 _ENGINE_FACTORIES = {"playwright":..., "nodriver":..., "patchright": _patchright_render_fn}
```

**③ FlareSolverr cookie 引导（在 `download.py`/`http_client.py` 的 CF 失败分支）**
```python
# 伪代码:命中 "Just a moment"/403 时
sol = flaresolverr.solve(landing_url, cfg)          # 已返回 cookies + user_agent
if sol:
    cookies = {c["name"]: c["value"] for c in sol["cookies"]}   # 含 cf_clearance
    # 用 sol["user_agent"] + cookies + 同一出口 IP 直下 PDF(三者须一致)
    pdf = http_client.get(pdf_url, headers={"User-Agent": sol["user_agent"]}, cookies=cookies)
```
先决条件：`docker run -d -p 8191:8191 ghcr.io/flaresolverr/flaresolverr:latest`，并设 `FLARESOLVERR_URL`（flaresolverr.py 已读该环境变量）。

---

## 七、ROI 与部署成本

| 维度 | 估计 |
|---|---|
| **RSC（batch6）可回收增量** | **≈ 0**——RSC 净 MISS 已是 0（websearch 已从他站兜底），CF 直取属重复劳动 |
| **跨批可回收增量** | batch4 CF-403 约 27 条（p2=13、p3=14）+ batch7 部分；其中相当比例 websearch 也能覆盖 → **净增量约 5–15 条** |
| **nodriver 部署成本** | 低：`pip install nodriver` + 首次拉 ~300MB Chromium；**无常驻服务**；headless 更易被测，建议 headful/新头 + 强限流（已内置 2s） |
| **FlareSolverr 部署成本** | 中：docker 常驻服务 + ~1GB 镜像 + 每并发一个无头浏览器的 CPU/RAM；维护随 CF 更新打补丁 |
| **风险/维护** | 所有开源绕行都需跟随 CF 更新；量大需住宅代理（IP 信誉独立信号）；本项目量小、走「逐篇 OA 取直链」，家宽 IP + 强限流通常够用 |

**是否值得为 ~34 条 RSC 启用 FlareSolverr？** —— **不值得**。理由：① RSC 在 batch6 已被 websearch 回收（净 0）；② FlareSolverr 是四方案里部署最重、对托管挑战又最易超时的一个。**若确要通用 CF 能力，用 nodriver（已内置、装依赖即可）性价比最高，把 FlareSolverr 留作 cookie 引导的可选兜底。**

---

## 八、参考来源（2026 时效）

- FlareSolverr CHANGELOG v3.5.0（2026-05-26，加 Turnstile/更新 CF 选择器）：`github.com/FlareSolverr/FlareSolverr/blob/master/CHANGELOG.md`
- FlareSolverr 托管挑战超时 issue #1675（2026-02，`cf_chl` 死循环）：`github.com/FlareSolverr/FlareSolverr/issues/1675`
- ScrapeOps《FlareSolverr Guide 2026》/ iproyal / ZenRows：FlareSolverr 现状、cookie 引导范式、局限
- Scrapfly《11 Best Anti-Bot Bypass Tools 2026》/《How to Bypass Cloudflare 2026》：curl-cffi=TLS层、nodriver=CDP 隐身、Camoufox=Firefox 引擎级、分层策略
- ByteTunnels / PROXIES.SX《Stealth Browsers 2026: Camoufox, Nodriver》：引擎级 vs 协议级隐身、通过率估计、puppeteer-stealth 已停更
- roundproxies《Bypass Cloudflare 2026》/《Cloudscraper Guide 2026》：cloudscraper 对现代 CF 局限
- patchright-python README（Kaliiiiiiiiii-Vinyzu）+ Spidra/Scrappey 评测：CDP 泄漏修补、须 persistent_context+channel=chrome+headful、对纯 JS 挑战的保留

> 注：以上通过率均为社区/评测经验值，随目标站配置、地理位置、代理质量波动，**无 100% 保证**；本项目实际以小样本抽测为准。
