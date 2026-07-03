# 选型2026 · route-B 反 RSC「governor 二道验证」补丁方案（设计草案，默认关）

> 交付：**谷歌学术人机认证-165**｜触发：用户真机报「RSC 第一次认证能过、第二次完全过不去」+ 两张截图｜2026-07-02。
> 用户已授权 -165 自决（delegate_system），拍板本项＝**先出可评审补丁方案、再与 -141/-144/-157 对齐落地**（不直接动其活跃代码、不真机抢单头锁）。
> **边界**：本文只出设计+伪码，**未改任何生产码**。落地由 route-B 属主拍板；建议全程 **gated、默认关、默认行为零变更**（与 -157 的 `_route_b_auto_fallback_enabled` 默认 False 同口径）。

---

## 一、问题定位：RSC 上其实有「两道不同的门」

| 门 | 截图 | 机制 | 现状 |
|---|---|---|---|
| ① Cloudflare 盾 | 图1 `Performing security verification` | CF Turnstile/JS 质询 | nodriver 真 Chrome **能过**（经验记录 N.1/N.4 已实证闭环） |
| ② RSC governor | 图2 `crawlprevention/governor` → `Validate User` | RSC 自家**应用层爬虫防护**，按**速率/行为**触发 Google reCAPTCHA | **route-B 目前无专门处理 → 第二篇即死** |

**「第一次过、第二次过不去」的机理**：governor 按速率/行为判定——首篇会话冷、干净 → 放行；短时间内再次命中（尤其**直接导航 `HTTPHandlers/ArticlePdfHandler.ashx` 这个 PDF 端点**）→ 判 `unusual traffic` → 弹 reCAPTCHA。

**图2 两个致命信号**：
1. `--disable-blink-features=AutomationControlled` 顶栏 → 自动化指纹已暴露（该 flag 反而触发 Chrome「unsupported command-line flag」infobar，本身是机器信号）。
2. `ERROR for site owner: Invalid domain for site key` → 该 reCAPTCHA 的 site key 与域不匹配，**真人点不过、打码平台(2captcha/anticaptcha)也解不了**——RSC 对判定 bot 的会话发「坏」reCAPTCHA 做软封。

> **战略结论**：方向是**「不触发 governor」**，绝非「解那张验证码」。硬解是死路（`scholar/captcha.py::solve_recaptcha` 对 Invalid-domain 无效，且需真 site_key）。

---

## 二、现状缺口（代码盘点）

- `render_fetch.py`：capture 流程只有通用 `_BLOCK_SIGNALS` + 返回 `blocked:challenge-page`；**未区分 CF 质询 vs RSC governor**；`_throttle`/`min_interval` 为**进程内全局最小间隔**，非 **per-host 节流**；`_single_head_guard` 是并发护栏，**无 per-host 冷却退避**。
- `download.py`：`_browser_capture_fallback` 按 `_needs_browser_capture_host` 门控 + 组装 `lock_path`；**入口 URL 若是 PDF handler 直链就会直接怼**②。
- 无处识别 `crawlprevention/governor` / `Validate User` / `Invalid domain for site key`。

---

## 三、补丁设计（6 点，均 gated·默认关）

### P1 · governor 专门检测（新 note：`blocked:rsc-governor`）
在 `render_fetch` capture 的「拿到页面后判定」处，除现有 `_BLOCK_SIGNALS` 外，新增 governor 指纹：
```python
_GOVERNOR_SIGNALS = (
    "crawlprevention/governor", "validate user",
    "invalid domain for site key", "take me to my content",
    "experiencing unusual traffic",
)
def _looks_governor(url: str, html: str) -> bool:
    low = (url + " " + (html or "")).lower()
    return any(s in low for s in _GOVERNOR_SIGNALS)
```
命中 → 返回 `("", "blocked:rsc-governor")`（软封变体再细分 `blocked:rsc-governor-softblock`，即含 `invalid domain for site key`）。**与 `blocked:challenge-page` 分开**，便于上层按 governor 走冷却而非重试。

### P2 · landing 预热（**别直接导航 PDF handler**）
route-B 入口**永远喂文章 landing URL（由 DOI 推）**，不喂 `ArticlePdfHandler.ashx`：
1. 同会话先 `tab.get(article_landing_url)`（RSC：`/en/content/articlelanding/...` 或 `articlehtml`），过 CF、停留 + 轻滚动建立信誉；
2. 再从页内解析 `articlepdf` 链接（landing.extract_pdf_links）；
3. 页内 `fetch(pdfUrl).arrayBuffer()` 同会话取字节（既有 B1）。
> 关键：**多 media/PDF 端点不作为导航目标**，只作为「页内 fetch 的目标」。直接导航 PDF handler 是 governor 最强触发器。

### P3 · per-host 限速 + governor 冷却退避
在 `_single_head_guard` 之上加 **per-host 状态表**（进程内 + 可选落 `out/.route_b_hoststate.json`）：
- **节流**：同 host 两次抓取间隔 `uniform(30,90)s`（RSC 键控，可配 `cfg.route_b_host_min_interval`）；
- **冷却退避**：命中 `blocked:rsc-governor` → 该 host 进入 `cooldown`（首次 5min，指数到上限 30min）；冷却期内该 host 的 route-B 请求**直接跳过记 `deferred:rsc-governor-cooldown`**，不再撞门；
- 复用现有单头锁做全组串行，避免多 worker 同机并发把 RSC 打爆。

### P4 · 反自动化指纹
- **去掉/替换** `--disable-blink-features=AutomationControlled`（它触发 infobar、是明信号）；
- 用 nodriver 默认反检测 + 隐藏 `navigator.webdriver`；
- **持久化 `user-data-dir` 真实档案**复用历史 cookie（让 RSC 看「回访人类」）；档案路径可配 `cfg.route_b_user_data_dir`。

### P5 · 坏 reCAPTCHA 不硬解
命中 `blocked:rsc-governor-softblock`（Invalid domain）→ 直接判失败进 P3 冷却，**不调 `solve_recaptcha`**、不联网打码。记 miss_reason=`blocked:rsc-governor`。

### P6 · 会话/IP 策略（规模化，可选）
- 暖会话复用（cf_clearance 绑 JA3+IP，过一次后同会话续抓）；
- 被 governor 反复盯上 → 换**住宅 IP** + 冷却；
- **配额化**：RSC 篇目摊到多时段/多出口，别集中批量（与 N.9 ROI 一致：RSC 边际≈0，价值在机制+提质，不必抢速）。

---

## 四、自测/回归（默认离线，纳入 run_all_selftests）

- 新增 `render_fetch` 内置 selftest 断言：
  - governor HTML fixture（含 `crawlprevention/governor` + `Validate User`）→ `_looks_governor()==True` 且 capture 归类 `blocked:rsc-governor`；
  - softblock fixture（含 `Invalid domain for site key`）→ `blocked:rsc-governor-softblock` 且**不调 solve_recaptcha**；
  - 正常 landing/OA 页 → `_looks_governor()==False`（不误伤）；
  - per-host 冷却：注入 governor 命中后，同 host 下一次请求返回 `deferred:*`（用假时钟，不 sleep）。
- **默认行为零变更**：P2–P6 全在 `route_b` 开启且 host 命中 `_needs_browser_capture_host` 时才走；默认关。
- 提交前在**无并发 route-B** 环境复跑 `run_all_selftests.py` 确认 `RENDER_OK` 稳定绿。

---

## 五、协作与落地（route-B 属主拍板）

- **强耦合方**：`render_fetch._nodriver_capture_fn` / `download._browser_capture_fallback` 正由 **-141（此刻在跑 RSC 发射）/-157（route-B 默认集成）/ 总指挥 -144** 维护。
- **建议**：本方案先经 -144/-141 评审；落地可由属主实施，或 -165 在**与 -141 约定时间窗（避开其 RSC 跑批、避免抢单头锁）**后落 P1/P2/P3（检测+预热+冷却，收益最大、改动最内聚），P4/P6 作后续增强。
- **验收样本**：用 `路线B-浏览器内直下PDF验证Runbook-173.md` 的 RSC 样本，验「连抓 ≥3 篇不被 governor 卡死」+ 落盘 QC=match。

---

## 六、TL;DR（给属主）

1. RSC 有**两道门**：CF（能过）+ **governor rate-gate reCAPTCHA（第二次即死）**；坏 reCAPTCHA **不可解**，只能**不触发**。
2. 补丁 6 点：**①governor 检测(`blocked:rsc-governor`)｜②landing 预热别怼 PDF handler｜③per-host 限速+冷却退避｜④去自动化指纹+持久档案｜⑤坏码不硬解｜⑥暖会话/住宅IP/配额化**。
3. 全 gated·默认关·默认零变更；带离线 selftest；改动最内聚的是 ①②③。
4. 与 -141/-144/-157 对齐后落地，避开 RSC 跑批窗抢锁。

---

*-165 交付 · 2026-07-02。只出设计+伪码，未改生产码。根据用户 delegate_system 授权拍板 opt_patch。*
