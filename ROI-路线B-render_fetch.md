# ROI · 路线B：render_fetch 无头浏览器「页内直下」可行性与成本（只调研不实现）

> 交付：组员 **-144**｜2026-07-02｜工单来源：总指挥 **-156**「ROI调研·路线B：render_fetch 无头浏览器页内直下 可行性与成本」（taskId=`task-a79788c0-6be0-4ff2-bce8-c66f1d2135ad`）。
> 边界：**纯文档、只新建本 1 份 md，不改任何 `.py`/PDF/metadata、不联网抓正文**。数据取自仓内已提交文档与源码 + 2026-07-01/02 GitHub/PyPI/评测核验。
> 关系：本文承接 -179《FlareSolverr免Docker-仓内nodriver-shim实测》、-176《RSC-Cloudflare绕行》、-149《回收实测结论-CF与免费路线到顶》、-153《采纳与淘汰总表》里反复点名却始终"列 P2 未定量"的**「浏览器内直接下 PDF」**路线，给它一次性做 ROI 定量收口。
> 一句话定位：**路线B 不是从零选型——仓内 `download.py::_nodriver_fetch_pdf_bytes`（第⑥层）已实现「有头真 Chrome 页内 CDP 下 PDF」并在 MDPI/Akamai 实网验证过；本文回答的是「把它扩到 CF/JA3/viewer 桶值不值、增量多大、要花多少」。**

---

## 〇、TL;DR（先给决策卡 4 个数）

| 决策卡字段 | 结论（点估 + 区间） |
|---|---|
| **① 预期成功率增量**（still_missing≈553 的 CF/闭源桶） | **净 +15~35 篇 ≈ +1.5~3.5pp**（44.8%→~46~48%），**点估 +20 篇（+2pp）**。其中"稳拿"高置信仅 **~15 篇**。**注意：CF/闭源桶主体（~300 篇）是真订阅付费墙，路线B 物理上救不了**——路线B 只吃"OA/免费正文被 JA3 绑定型 CF 或 viewer 包壳挡住"这一小片。 |
| **② 实现复杂度 / 维护成本** | **低-中**。核心是给现有 `_nodriver_fetch_pdf_bytes` 加一条 **页内 `fetch().arrayBuffer()`** 支路（JA3 安全）+ viewer 探测 + 路由。**~1~2 人日**（脚手架已在）。维护=跟随 CF 偶尔升 nodriver；有头需显示/Xvfb；量大需住宅代理（cf_clearance 绑 IP）。 |
| **③ 可直接复用开源项 + 建议** | **主引擎 nodriver（已装 0.50.3、CDP 原生、能访问内嵌 PDF viewer、2026 CF 基准第一）**；回退 patchright（已接线）；受控升级 camoufox（最狠指纹站）。**不为路线B 引入 byparr / 经典 FlareSolverr**——它们是"解挑战→cookie 交 curl_cffi 回放"范式，正是 RSC 上失败的那条链。 |
| **④ 一次性 + 持续成本** | 一次性：依赖 **¥0**（nodriver 已装）+ **~1~2 人日**工程。持续：每篇有头 Chrome **~15~25s / ~300MB RAM**；跟随 CF 的偶发维护；可选住宅代理（规模化才需，$/GB）；**无 Docker、无常驻服务**。 |

> **核心判断**：路线B 的价值**不在量、在质**——它是 **JA3 绑定型强 CF（RSC/ScienceDirect）唯一的技术正解**，且若走"权威 DOI 落地页页内直下"还能**天然规避 websearch 68.5% 抓错论文的假阳**（-150 审计）。作为"提质 + 拉高未来批次天花板"的能力值得以最小改动点亮；作为"清空当前 still_missing"的走量手段则 ROI 有限（主体是订阅墙，得靠机构订阅 A5）。

---

## 一、路线B 是什么 & 仓内现状盘点（不是从零造轮子）

**"页内直下"（in-page direct download）= 用反检测真浏览器打开落地页 → 在同一浏览器会话/同一指纹出口内，直接把 PDF 字节取回来**，而非"浏览器解挑战拿 cookie → 交 `curl_cffi`/`requests` 换个客户端回放下载"。后者正是仓内实测在 RSC 上 403 的死结（cf_clearance 绑 JA3，换客户端即失配）。

仓内**已经有**的三块拼图（关键：路线B 是"扩展"不是"新建"）：

| 组件 | 位置 | 现状 | 与路线B 关系 |
|---|---|---|---|
| **有头浏览器页内 CDP 下 PDF** | `download.py::_nodriver_fetch_pdf_bytes` + `_browser_pdf_download`（第⑥层，`cfg.browser_pdf_download=True`，默认关） | **已实现并实网验证**：nodriver 有头真 Chrome 过 Akamai `bm-verify` → `Page.setDownloadBehavior(allow)` 触发下载 → 取回 **MDPI 6.5MB PDF**。缺 nodriver/无显示优雅降级 | **路线B 的地基**。当前只覆盖 Akamai；扩到 CF/JA3/viewer 即成路线B |
| **无头渲染取直链兜底** | `render_fetch.py::render_get_pdf_url(engine=auto\|playwright\|nodriver)` | 已实现、默认关；渲染后复用 `landing.extract_pdf_links` 抠直链；强限流 2s；**合规守卫永不渲染 Scholar** | 路线B 的"取直链"半条腿（但对 viewer 型/无 `<a href=.pdf>` 的页无效，需页内直下补强） |
| **免 Docker CF 求解 shim** | `tools/flaresolverr_nodriver.py`（-145/-173 写、-179 实测） | nodriver 实现的 FlareSolverr `/v1` 兼容端点，过 CF 稳定（4/4 origin `cf_clearance=YES`） | 属"解挑战→cookie 回放"范式，**对 ACS(不绑JA3)有效、对 RSC(绑JA3)无效**——正是路线B 要补的缺口 |

**结论**：破 CF 的"浏览器腿"仓库已铺好，路线B 的净工作量 = **把第⑥层从"Akamai 专用 + 只会 CDP-download"升级为"CF/JA3/viewer 通用 + 会页内 fetch"**，并在 `download_pdf` 的 CF/JA3 失败分支路由过去。

---

## 二、技术核心：页内直下三法，与 JA3 死结的真解

浏览器里把"显示在 viewer 里的 PDF"或"被 CF 挡住的 PDF"取成字节，2026 有三条成熟路径（Playwright/Chromium 官方 issue #7822、#499 + 多篇 2026 实践一致）：

| 方法 | 机理 | 能否过 JA3 绑定型 CF | 能否取内嵌 viewer 的 PDF | 仓内现状 |
|---|---|---|---|---|
| **A. CDP `Page.setDownloadBehavior(allow)` + 导航到 PDF URL** | 让浏览器自己把 PDF 落盘到临时目录，再读字节 | **✅ 能**（下载走浏览器自身网络栈=同 JA3+同 cookie） | ✅ 能（下载不经 viewer 渲染） | **已实现**（`_nodriver_fetch_pdf_bytes`，MDPI 已验证） |
| **B. 页内 `fetch(pdfUrl).then(r=>r.arrayBuffer())`** 取 blob→base64 回传 | 在**页面 JS 上下文**里发起 fetch，**继承该页所有 cookie + 出口 IP + 浏览器 TLS/JA3** | **✅ 能，且最稳**（请求就在浏览器内发出，指纹天然一致） | ✅ 能（viewer 的 PDF 源 URL 也可 fetch） | **未实现（本文建议新增，路线B 关键增量）** |
| **C. `page.route` 拦截改 `Content-Disposition: attachment` / 关内置 viewer** | 强制浏览器把 PDF 当附件下载而非 viewer 预览 | ✅ 能 | ✅ 能 | 未实现（Playwright/patchright 专用手法） |

**为什么方法 B 是 RSC/ScienceDirect 这类 JA3 绑定站的真解**：
- -179/-149 实测锤死：nodriver shim **能解 CF、cf_clearance 到手**，但 `download.py` 把 cookie 交 `curl_cffi` **回放**下 PDF 时，RSC **把 cf_clearance 绑到 JA3/TLS 指纹**，curl_cffi 的 JA3 ≠ 真 Chrome → 仍 403。**换更强求解器（byparr/Camoufox）走同一回放链，救不了**。
- 方法 B 让"下 PDF"这一步**根本不离开浏览器**：`tab.evaluate("fetch(url).then(r=>r.arrayBuffer())…")` 在页面里跑，用的就是刚过完 CF 的那个真 Chrome 的 TLS 握手 + cf_clearance + 会话 cookie → **指纹/cookie/IP 三位一体天然一致，JA3 校验无从失配**。
- ⚠️ **官方限制**：Playwright/patchright 用 JS **访问不到 Chromium 内置 PDF viewer**（microsoft/playwright #3509、browser-use #499）——所以纯 Playwright 系要么用方法 C（route 改头），要么用方法 B（在 viewer 加载前对源 URL fetch）。**nodriver 纯 CDP，无此限制**，方法 A/B 都顺。

> 一句话：**路线B = 现有第⑥层（方法 A）+ 新增页内 fetch（方法 B）+ CF/JA3 路由**。方法 B 是把 -153《采纳淘汰总表》§四反复讲的"solve 与 download 用同一浏览器会话/同一指纹出口"真正落到字节级的那一小段代码。

---

## 三、引擎逐项评测（2026-07-01/02 核验：时效 / 热度 / 维护 / 许可 / 对 CF+JS+viewer 覆盖）

| 引擎 | ⭐Star | 许可 | 最新版 / 活跃 | 引擎 · 驱动 | 过 CF「Just a moment」JS 挑战 | 能否访问内嵌 PDF viewer / 页内直下 | 部署 | 路线B 定位 |
|---|---|---|---|---|---|---|---|---|
| **nodriver** | ~4,384 | **AGPL-3.0** | v0.50.3（2026-05-13）活跃 | 纯 CDP 直连系统 Chrome | **强**（2026 基准 28/31、**唯一 0 封锁**；本仓 shim 4/4 origin cf_clearance=YES） | **✅ 最顺**（纯 CDP，方法 A+B 都行；无 Playwright viewer 限制） | `pip`+Chromium，**无服务**（已装） | **✅ 主引擎** |
| **patchright** | ~2,790 | Apache-2.0 | py v1.61.1（2026-06-29）活跃 | Playwright drop-in、`channel=chrome` | 中-强（补 `Runtime.enable`/CDP 泄漏；须 persistent_context+headful） | ⚠️ JS 访问不到内嵌 viewer→须方法 C（route 改头）或方法 B | `pip`+Chrome | **回退**（已接 browser_search） |
| **camoufox** | ~9,100 | MPL-2.0 | v150.x-beta（2026-05）**实验/恢复期** | Firefox C++ 级指纹 | **最强**（重指纹站；CreepJS/BrowserScan 0% 检出） | ✅（Playwright 兼容，方法 B/C） | 自带 Firefox ~200MB，较重 | **受控升级**（nodriver 被最狠站挡时） |
| **byparr** | ~1,000 | 见仓（Camoufox=MPL/PW） | v2.1.0（2026-02）单人活跃、周更 | Camoufox+Playwright，**FlareSolverr `/v1` 服务** | 强（Camoufox 引擎） | —（**服务只回 HTML+cookies**，本质仍是"解挑战→回放"范式） | Docker 首选（免Docker `uv run` 可，拉 Camoufox） | **不用于路线B**（回放范式，救不了 JA3） |
| **经典 FlareSolverr** | ~10k+ | MIT | v3.5.0（2026-05-26）维护中 | 钉死 uc3.5.5 + Chromium | 中（IUAM 可；Turnstile/2026 Managed 常超时，issue #1675） | —（同上，cookie 引导） | **Docker 服务** + ~1GB 镜像 | **淘汰**（老站登记；仓内 shim 已替代） |
| **Playwright（vanilla）** | ~76k | Apache-2.0 | 活跃 | Chromium/FF/WebKit | 弱（无隐身，基准垫底 24/31） | ⚠️ viewer 限制同 patchright | `pip`+浏览器 | render_fetch 现有引擎，**非 CF 主力** |
| **cloudscraper / curl_cffi 单用** | — | MIT | cloudscraper v3.0.0(2025-06)缓慢 | 无浏览器 | **无效**（不执行 JS；curl_cffi 只伪 TLS，已实测过不了 RSC） | ✗ | 最轻 | **不用**（curl_cffi 只做同栈回放，正是 JA3 失配那端） |

**读表 3 个要点**：
1. **许可证纠偏（重要）**：-176 文档记 "nodriver=MIT" **有误**；权威口径 **nodriver = AGPL-3.0**（GitHub LICENSE.txt + Ian Paterson 2026 基准 + 158/179 文档一致）。含义：**未修改、仅作后端库内部批量回收 → 只需"提一句致谢"**（作者本人在 discussion #2215 明确）；只有"改了 nodriver 源码并对外提供网络服务"才触发开源义务。**本项目内部回收无碍**。
2. **能"访问内嵌 viewer"是路线B 的硬门槛**——这正是选 **nodriver（纯 CDP）而非 Playwright 系**的决定性理由：Playwright/patchright 有官方 viewer 访问限制，nodriver 没有。
3. **byparr / 经典 FlareSolverr 对路线B 无增益**：它们再强也只回 HTML+cookies，仍要把 cookie 交别的客户端回放——**RSC 的 JA3 死结原样存在**。路线B 的价值恰恰是"不回放、页内直下"，故不引入这两者。

---

## 四、Deliverable ①：预期成功率增量（still_missing≈553 的 CF/闭源桶）

### 4.1 分母与桶拆解（跨批 blacklist-aware 口径）

净覆盖 **448/999 ≈ 44.8%**（-150/-149，剔 websearch 假阳后）→ still_missing ≈ **551~553**。其 CF/闭源构成（综合 val500 / batch4 / batch6 失败分桶，标注为**估计**）：

| still_missing 子桶 | 规模（估计） | 墙类型 | 路线B 能救吗 | 依据 |
|---|---:|---|---|---|
| **真订阅付费墙 403**（ACS/RSC 订阅刊、Elsevier 订阅） | **~300**（val500 里仅-403 就 ACS80+RSC41=121 是真墙；跨批更多） | 付费墙（非 CF、非 viewer） | **❌ 救不了**（过了 CF/进了浏览器仍 403）→ 机构订阅 A5 | 数据分析 §7.3、§六 |
| **Elsevier/ScienceDirect 下载环 IP/登录墙** | **~40~80** | 数据中心 IP/登录墙（非 CF） | **❌ 基本救不了**（家宽/数据中心 IP 仍 403，需住宅/机构登录）；browser_search 0/10 + wayback 0/12 已到顶 | -149 §三、batch4 Elsevier 110 MISS |
| **JA3 绑定型 CF 后面的 OA/免费正文**（RSC OA、ScienceDirect OA） | **~5~15** | CF + cf_clearance 绑 JA3 | **✅ 路线B 正解**（方法 B 页内 fetch）；但 RSC 净 MISS≈0（websearch 已兜底） | -179 §7、-176 TL;DR |
| **其它 CF 后面的 OA**（AIP/Wiley/OUP/T&F/RG/ChemRxiv，不绑 JA3 者） | **~10~25** | CF（可回放型） | **✅ 部分**（但这类 ACS shim 回放已能救、且 websearch 常兜底，路线B 边际小） | -149 §二、§五 |
| **viewer-only OA**（Atypon `epdf`/PDF.js 包壳、无 `<a href=.pdf>`） | **~5~10** | 无直链，只有 viewer | **✅ 路线B 增量**（方法 B/C 取 viewer 源） | render_fetch 对 viewer 型无效 → 需页内直下 |

### 4.2 增量估计（三档，诚实标注重叠）

- **高置信"稳拿"**（JA3-OA + viewer-only OA，几乎只有路线B 能取）：**~15 篇**。
- **加上可回放型 CF-OA 的净新增**（扣掉 websearch/ACS-shim 已兜底的重叠）：**+5~20 篇**。
- **净增量点估 = +20 篇 ≈ +2.0pp**（44.8% → **~46.8%**）；乐观上界 **+35 篇（+3.5pp）**，保守下界 **+10 篇（+1pp）**。

> ⚠️ **三条必须写进决策卡的诚实前提**：
> 1. **CF/闭源桶主体（~300+ 真订阅墙）路线B 物理救不了**——想清空 still_missing 得靠机构订阅 A5，不是路线B。
> 2. **RSC 净 MISS≈0**（websearch 已从他站兜底）——为 RSC 单独上路线B 走量收益≈0，与 -176 结论一致。
> 3. **相当比例"增量"与 websearch 重叠**——真正"only 路线B 能拿"的净新增偏小（~15）。

### 4.3 被低估的"质"红利（路线B 的真正卖点，非走量）

1. **JA3 死结唯一解**：RSC/ScienceDirect 这类"过了 CF 仍回放 403"的站，除路线B（页内直下）外**无免费解**（换求解器无效已实测）。这是能力上的"从 0 到 1"，不是百分点游戏。
2. **天然规避假阳**：路线B 从**权威 DOI 落地页**页内直下，不像 websearch 取"搜索引擎首个 PDF"——**直接绕开 -150 审计的 68.5% 抓错论文假阳**。即"路线B 拿到的每一篇内容可信度远高于 websearch 成功"。
3. **拉高未来批次天花板**：当前 999 是已被 websearch 深挖过的存量；对**新输入**（尤其 CF 出版商占比高的语料），路线B 的相对增量会明显大于 +2pp 这个存量口径。

---

## 五、Deliverable ②：实现复杂度与持续维护成本

### 5.1 一次性实现复杂度：**低-中（~1~2 人日）**

改动点（**本文不实现，仅给方案**，全部在已有脚手架上增量）：
1. **给 `_nodriver_fetch_pdf_bytes` 加方法 B 支路**（核心）：CDP 下载失败 / 命中 viewer / 命中 JA3 绑定域时，回退到页内 `fetch(pdfUrl).then(r=>r.arrayBuffer())` → base64 → 解码字节。~30~50 行。
2. **viewer 探测**：现有 `_FIND_PDF_JS` 已找 PDF URL；补一条"页是 PDF viewer 包壳（`embed[type=application/pdf]` / pdf.js / Atypon epdf）时取其 `src`/资源 URL"。~10~20 行。
3. **路由**：`download_pdf` 的 `cloudflare-challenge` / JA3 绑定域（RSC/ScienceDirect 名单）失败分支，优先走"页内直下"而非"solve→curl_cffi 回放"。~10 行 + 一张域名小表。
4. **复用既有护栏**：合规守卫（永不渲染 Scholar）、`looks_like_pdf`/`pdf_defect`/`min_pdf_bytes` 校验、强限流、影子库硬拒——**全部现成，零新增合规面**。
5. **接 `--selftest`**：仿 -179 给 shim 加自检的做法，给页内 fetch 支路加离线 mock 自检，纳入 `run_all_selftests.py`。

### 5.2 持续维护成本：**低-中**

| 维护项 | 成本 | 缓解 |
|---|---|---|
| 跟随 CF 更新 | 偶发（升 nodriver 版本即可，社区跟得紧） | nodriver 活跃、2026 基准第一 |
| 有头需显示环境 | 服务器/CI 需 Xvfb 或有头机 | 与现有 `browser_pdf_download` 同哲学（默认关、只本机回收开） |
| 单篇开销 | ~15~25s / ~300MB RAM（有头 Chrome） | 按 origin 缓存 cf_clearance（shim 已有）；只对 CF/JA3 桶启用，非默认路径 |
| cf_clearance 绑 IP | 量大时同 IP 被限速 | 强限流已内置；规模化才上住宅代理 |
| **bus factor** | nodriver 仅 3 contributors | patchright（Apache-2.0）作第二真 Chrome 通道抗单点失效 |
| 许可 | AGPL-3.0 | 内部回收无碍（仅需致谢）；对外服务前过法务 |

---

## 六、Deliverable ③：可直接复用开源项 + 采纳/整合建议

**可直接复用（按 ROI 从高到低）**：

1. **nodriver 0.50.3（已装，主引擎）** —— 直接复用仓内已跑通的 `_nodriver_fetch_pdf_bytes`，加方法 B 支路。**改动近零、无新依赖、AGPL 内部无碍**。这是路线B 的落地主力。
2. **patchright（已接线，回退）** —— 作 nodriver 之外第二真 Chrome 通道；对 viewer 用方法 C（`route` 改 `Content-Disposition`）。Apache-2.0 商用友好、抗单引擎失效。
3. **camoufox（受控升级，非默认）** —— 仅当 nodriver/patchright 被 DataDome/CF-Managed 这类最狠指纹站持续拦时再上；**当前 v150.x-beta 实验期、官方"不适合生产"**，用稳定分支、单独 profile、默认关。
4. **仓内 `render_fetch.py` / `landing.extract_pdf_links`** —— 复用其"渲染后抽直链"能力做路线B 的前置（先试直链、再页内直下），并把 `_patchright_render_fn`（-176 §六给了现成 10 行）补进引擎工厂表。

**明确不采纳（对路线B）**：
- **byparr / 经典 FlareSolverr**：回放范式，救不了 JA3 死结；且 byparr 需拉 Camoufox、Docker 首选（免 Docker `uv run` 亦重），对路线B **零边际**。留作"需批量 CF cookie 引导且不想在业务进程内跑浏览器"的可选服务，不进路线B 主路径。
- **cloudscraper / curl_cffi 单用**：不执行 JS 过不了 CF；curl_cffi 恰是 JA3 失配的那端。
- （旁注）Node 生态的 `jo-inc/camofox-browser`（~7k⭐、MIT、Camoufox 服务）是 Node 侧方案，与本 Python 仓栈不合，不建议引入。

**整合建议一句话**：**以 nodriver 页内直下为主、patchright 为回退、camoufox 为受控升级；把"solve→回放"链保留给 ACS 类可回放 CF，把 RSC/ScienceDirect/viewer 类路由到页内直下。**

---

## 七、Deliverable ④：一次性 + 持续成本粗估

| 成本项 | 一次性 | 持续 |
|---|---|---|
| **依赖 / 采购** | **¥0**（nodriver 0.50.3 + curl_cffi 本机已装；无需 Docker、无需买服务） | ¥0（除非规模化上住宅代理） |
| **工程人力** | **~1~2 人日**（方法 B 支路 + viewer 探测 + 路由 + selftest 接线 + RSC/SD/viewer 抽样实测） | 偶发（跟随 CF 升 nodriver，季度级 ~0.5 人日） |
| **算力 / 运行** | 首次拉 Chromium ~300MB（已装则 0） | 每篇有头 Chrome **~15~25s / ~300MB RAM**；仅对 CF/JA3 桶启用，按 origin 缓存 → 每域首篇付一次解题成本 |
| **住宅代理**（仅规模化/被限速时） | 0（起步不需要） | $ 按量（cf_clearance 绑 IP，量大才需；本项目量小家宽足够） |
| **合规 / 法务** | 0（AGPL 未修改+内部回收，仅致谢） | 0（对外提供服务才需过法务） |

**性价比结论**：一次性≈**1~2 人日 + ¥0 依赖**，换来 **JA3 绑定型强 CF 的唯一免费解 + 质更高的 ~15~35 篇净增 + 未来批次更高天花板**。作为"点亮已有能力"的 P2 增量，**投入极小、能力从 0 到 1，值得做**；但**别把它当清空 still_missing 的走量方案**——那 300+ 订阅墙只有机构订阅 A5 能破。

---

## 八、给决策卡 / 总指挥的一句话收口

**路线B（render_fetch 页内直下）= 用 nodriver 在同一浏览器会话内把 PDF 字节取回来，是 RSC/ScienceDirect 这类"cf_clearance 绑 JA3、换客户端回放必 403"站点的唯一免费技术正解，也是 viewer-only OA 的解法；仓内第⑥层已实现地基（MDPI 验证），补一条页内 `fetch().arrayBuffer()` 支路即成（~1~2 人日、¥0 依赖）。诚实预期：净增 +15~35 篇（+2pp 点估），且相当比例与 websearch 重叠——它的价值在"提质 + 拉高未来天花板 + JA3 死结从 0 到 1"，不在清空当前 still_missing（主体是订阅墙，归机构订阅 A5）。引擎选 nodriver（CDP 原生、能进内嵌 viewer、2026 CF 基准第一、已装），不引入 byparr/经典 FlareSolverr（回放范式救不了 JA3）。**

---

## 九、来源 / 证据索引

**仓内源码（实现地基）**：
- `fulltext_fetcher/download.py` §863–963 `_nodriver_fetch_pdf_bytes` / `_browser_pdf_download`（第⑥层，MDPI 6.5MB 已验证）、§966+ `download_pdf` 六层兜底契约。
- `fulltext_fetcher/render_fetch.py`（`render_get_pdf_url`、`_nodriver_render_fn`、合规守卫 `_is_scholar_host`）。
- `tools/flaresolverr_nodriver.py`（免 Docker CF 求解 shim，-145/-173）。

**仓内文档（口径与实测）**：
- `选型2026-FlareSolverr免Docker-仓内nodriver-shim实测与落地-179.md`（§7 JA3 死结实测：RSC cf_clearance 到手但 curl_cffi 回放 403；ACS 不绑 JA3 可救）。
- `回收实测结论-CF与免费路线到顶.md`（-149/-150：净覆盖 448/999≈44.8%；websearch 假阳 A=68.5%；ACS 可救/RSC 难越/Elsevier 免费到顶）。
- `选型2026-RSC-Cloudflare挑战绕行方案.md`（-176：RSC 净 MISS≈0、HTTP 层过不了、`render_fetch` 内置 nodriver、`_patchright_render_fn` 现成 10 行）。
- `选型2026-采纳与淘汰总表.md`（-153 §四：新增 P2「浏览器内直下 PDF」项、CF/JA3 口径修订）。
- `选型2026-隐身无头浏览器与反检测.md`（-158：nodriver=AGPL-3.0、2026 基准 28/31 0 封锁、camoufox ~9,100⭐实验期、本仓 Bing 5/5 实测）。
- `检索成果-数据-失败原因分析.md`（-141：仅-403 里 ACS80+RSC41=121 真付费墙）；`检索成果-batch4-失败分桶与可回收分析.md`（-146：CF download 519 次、Elsevier110/ACS13/RSC5 MISS）。

**2026-07-01/02 外部核验**：
- nodriver：GitHub `ultrafunkamsterdam/nodriver`（LICENSE.txt=**AGPL-3.0**、⭐~4,384、push 2026-05-13、v0.50.3、3 contributors）、discussion #2215（未改+网络使用仅需致谢）。
- Ian L. Paterson《Anti-detect browser benchmark 2026》（nodriver 28/31 唯一 0 封锁；AGPL 说明）。
- byparr：GitHub `ThePhaseless/Byparr`（⭐~1,000、v2.1.0 2026-02、Camoufox+Playwright、FlareSolverr `/v1` drop-in、单人周更）；godberrystudios《Byparr+Scrapling 2026》。
- camoufox：`daijro/camoufox`（⭐~9,100、MPL-2.0、v150.x-beta 实验期）。
- 页内直下三法：Playwright #7822/#3509、browser-use #499（Playwright 访问不到内嵌 viewer；CDP 迁移后解除）、pixeljets/web-scraping.dev（route 改 `Content-Disposition` / `Page.setDownloadBehavior` / 页内 `fetch().arrayBuffer()`）。

---
*核验 2026-07-02｜-144｜工单「ROI·路线B render_fetch 页内直下 可行性与成本」（taskId=`task-a79788c0-…`）｜结论：路线B=JA3 绑定型强 CF 的唯一免费正解 + viewer-only OA 解法，仓内地基已在（第⑥层 MDPI 验证），补页内 fetch 支路即成（~1~2 人日、¥0 依赖）；净增量 +15~35 篇（+2pp 点估，与 websearch 部分重叠），价值在提质与未来天花板，不在清空订阅墙。引擎选 nodriver，不引入 byparr/经典 FlareSolverr。仅新建本 1 份文档，未改任何 .py。*
