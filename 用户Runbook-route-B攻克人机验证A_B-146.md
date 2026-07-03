# 用户 Runbook · route-B 攻克人机验证 · A/B 控制面板 — 146

> 交付：**谷歌学术人机认证-146**｜2026-07-03｜承接用户「必须攻克这类人机验证 / 三条路都配置」。
> 覆盖两类真机验证：**① CF Turnstile**（"Verify you are human" 勾选框）**② RSC governor**（`crawlprevention/governor` 的坏 reCAPTCHA）。
> 全部开关 **env-gated、默认关**（不设=route-B 行为逐字节不变）；离线 `RENDER_OK` + 全量 `run_all_selftests` 46/0/2 全绿。
> 相关提交：`3cec811`(P6 代理) ← `d0aecea`(三路 A/B) ← `ff2caca`(Turnstile 解题器+P4)。

---

## 一、三层检测 × 攻克杠杆（一句话模型）

人机验证有**三层独立检测**，住宅代理只解第①层。哪层是主矛盾取决于验证类型与你当前 IP：

| 检测层 | 攻克杠杆 | 对 CF Turnstile | 对 RSC governor |
|---|---|---|---|
| ① IP 信誉 | 住宅/移动代理（P6） | 机房 IP 才需；家用 IP 多半不必 | IP 被烧后需轮换 |
| ② 浏览器指纹 | 真浏览器 + 去自动化标 + 持久档案（引擎/P4） | **主矛盾** | 次（降触发概率） |
| ③ 速率/行为 | 限速 + landing 预热 + 会话复用（-165） | 次 | **主矛盾**（第二篇即死） |

> 结论：**两类都不是"必须先上住宅代理"**。代理只在【机房 IP】或【IP 被烧需轮换】时才是硬门槛。

---

## 二、控制面板（全 env-gated，默认关）

| 检测层 | 杠杆 | 开关（PowerShell） | 成本 |
|---|---|---|---|
| IP 信誉 | 住宅代理出口(P6) | `$env:FTF_ROUTE_B_PROXY="http://host:port"` | 代理费 |
| 浏览器指纹 | zendriver 引擎(Path3) | `$env:FTF_ROUTE_B_ENGINE="zendriver"` | 免费 |
| 浏览器指纹 | 持久档案(P4) | `$env:FTF_ROUTE_B_USER_DATA_DIR="e:\...\.rb_profile"` | 免费 |
| Turnstile | verify_cf 免费点选(Path1) | `$env:FTF_ROUTE_B_VERIFY_CF="1"` | 免费 |
| Turnstile | EzSolver 自托管(Path2) | `$env:FTF_TURNSTILE_SOLVER_URL="http://localhost:5033"` | 免费 |
| Turnstile | capsolver/2captcha(付费兜底) | `$env:FTF_CAPTCHA_ENABLED="1"; $env:FTF_CAPTCHA_PROVIDER="capsolver"; $env:FTF_CAPTCHA_KEY="<key>"` | 付费 |
| RSC governor | -165 不触发(P1/P2/P3/P5) | 自动（route-B 内，已在码） | 免费 |
| 窗口显示 | 有头显示/纯无头 | `$env:FTF_BROWSER_SHOW="1"` / `$env:FTF_HEADLESS="1"` | — |

> 认证代理（`user:pass@host:port`）：Chrome `--proxy-server` 不接受内联凭据，且过 CF 期【绝不能提前 enable Fetch 域】做 CDP 鉴权（-154 会破盾）。请用 **IP 白名单授权**，或本机起**非认证转发端点**（localhost:port）指向上游认证代理，再把本地端点填进 `FTF_ROUTE_B_PROXY`。

---

## 三、token 求解优先级（Turnstile）

route-B 命中 Turnstile 质询页时，按此顺序（各自 gated、默认关）：

1. **verify_cf()**（Path1，浏览器内 opencv 点选，免费）— `FTF_ROUTE_B_VERIFY_CF=1`
2. **token 求解**（`_acquire_turnstile_token`）：**EzSolver 自托管（免费）→ capsolver/2captcha（付费）**，抽 sitekey → 出 token → 注入页面 → 重判。

> ⚠️ **RSC governor 那张坏 reCAPTCHA（`Invalid domain for site key`）不可解**：真人点不过、任何打码平台也解不了。命中 `_looks_governor` 直接判 `blocked:rsc-governor` 冷却，**绝不调用打码**（-165 P5）。

---

## 四、A/B 实测 SOP

**目标**：同一 target，逐个开关跑，比 `note`，看哪条最有效。

**基线命令**（先开 route-B、给文章页 URL）：
```powershell
python -m fulltext_fetcher.render_fetch "<文章页URL>" --capture-bytes
# 或整流水线：python -m fulltext_fetcher "<DOI>" --route-b cf-only
```

**逐路对照**（每轮设 env → 跑 → 记 note，跑完 `Remove-Item Env:XXX` 复位）：

| 轮次 | 设定 | 观察 |
|---|---|---|
| A 基线 | 无（默认 nodriver） | `note` = ? |
| B 引擎 | `FTF_ROUTE_B_ENGINE=zendriver` + `FTF_ROUTE_B_USER_DATA_DIR=<dir>` | 通过率是否↑ |
| C 免费点选 | 再加 `FTF_ROUTE_B_VERIFY_CF=1` | Turnstile 是否过 |
| D 代理 | 再加 `FTF_ROUTE_B_PROXY=<住宅>` | 被烧 IP 是否救回 |
| E 付费 | 再加 `FTF_CAPTCHA_*` | 硬 Turnstile 兜底 |

**判读 `note`**：
- `ok:b1` / `ok:b2` / `ok:b2-fetch` / `ok:b2-viewerfetch` = **成功**（拿到 %PDF 字节）
- `blocked:challenge-page` = 仍卡 CF 质询（换引擎/代理/verify_cf 再试）
- `blocked:rsc-governor[-softblock]` = RSC governor 触发（换未烧 IP + 更保守节流；坏码不可解）
- `deferred:rsc-governor-cooldown` = 该 host 冷却中（等冷却或换 IP）
- `no-pdf-captured` / `no-pdf: ...` = 过盾但没抓到 PDF 字节（landing 预热/fallback 问题）

**RSC 复测目标**（`routeB_rsc_goldoa.txt`，8 条金 OA）：`10.1039/{c4ra00825a,c4ra02037e,c4ra14572k,c5ra04969e,d0gc02302g,d2gc02623f,d3ee02589f,d5fd00172b}`；已知可过 PoC：`10.1039/d5ra08493h`（484KB %PDF-1.6）。

---

## 五、诚实边界（别做无用功）

1. **三路只治 CF Turnstile**；**RSC governor 坏码无解**，只能 -165 不触发 + 被烧后换 IP。
2. **过验证 ≠ 拿全文**：若目标是**订阅制**，破验证后仍撞付费墙（"购买 $39.95"）——那不是验证、是授权，唯 **A5 机构订阅**。
3. 掉头的 still_missing 大头是**付费墙**（非验证）；开源工具天花板个位~低两位 pp，**最大净增仍是 A5**（可救 ≈94% still_missing，唯一 gate = 用户凭据）。
4. 免费公开边界净覆盖已到顶 ≈34%（权威 `out/coverage.json` 326/999=32.63%）。

---

## 六、开源横评（2026-07 实测，摘自 -165/-159 扫描）

| 开源 | 对 Turnstile | 代理/key? | 备注 |
|---|---|---|---|
| **nodriver `verify_cf()`**（在用） | ✅ 免费点选 | 免 | 几行接入（Path1） |
| **EzSolver**（2026 新） | ✅ 真浏览器零付费 | 免 | 本地 HTTP API（Path2） |
| **SeleniumBase UC** `uc_gui_click_captcha()` | ✅ 最稳免费 | 免 | 备选 |
| **zendriver** | ✅ | 免 | nodriver 活跃分叉，修 CDP 漂移（Path3） |
| Camoufox / patchright / Byparr / Scrapling | ✅ 指纹强 | 免 | 选用 |
| capsolver / 2captcha | ✅ 出 token | 付费 | 硬 case 兜底 |
| 任何打码器 → RSC governor 坏码 | ❌ | — | 不可解 |

---

*146｜2026-07-03｜控制面板 + A/B SOP + 边界。实现见 `fulltext_fetcher/render_fetch.py`（三路 + P4 + P6 + -165）与 `scholar/captcha.py`（solve_turnstile）。真效果需在目标站 + 你的 IP 上实跑对照。*
