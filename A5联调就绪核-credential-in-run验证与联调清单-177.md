# A5 联调就绪核 · credential-in→run 验证 + 联调清单（-177）

> 交付：**谷歌学术人机认证-177**（worker）｜工单 `task-686d5e3b`【A5 联调就绪核】（总指挥-146 派）｜2026-07-03。
> 边界（硬约束）：**只读盘代码 + 跑离线自检 + 产本 1 份 md**；未改生产码 / coverage / git。落地动作（补线/联调）须属主拍板。
> 权威口径：净覆盖 `out/coverage.json` = **326/673/32.63%**；A5 = 破免费天花板（→60~70%）唯一杠杆，**凭据 gate 在用户**（现用户选「A5 作后续」，真实凭据只能用户投喂、无法代生成）。

---

## 〇、TL;DR（一页给总指挥）

> 🟢 **-141 本波已补齐路线B 断线**：`download._browser_capture_fallback` 现构造 `RouteBInjectionPlan` 并以 `injection_plan=` 传入 `render(...)`；新增纯函数 `route_b_bridge.plan_route_b_injection_from_config(cfg,url)`（cfg→plan，判据委托 `needs_institution_access`，route-A/B 同门；不建 AuthSession）。全套 `run_all_selftests.py` **PASS=46/FAIL=0**、compileall/lints 全绿、零副作用（无凭据时逐字节不变）。**至此路线A/B credential-in→run 全就绪，剩真机凭据验收（§三.B）。**

- **结论（更新后）**：**路线A（HTTP 直链 / `publisher_direct`）与路线B（浏览器内抓字节 / route-B）credential-in→run 均已就绪**（A5 4 项 + http_client/publisher_direct/cli/run_all 机构口径 + route-B cfg→plan 接线自检全绿）。原「路线B 单点断线」（`download` 兜底未把 Config 机构凭据构造成 `RouteBInjectionPlan` 传入 `render`）**已于 -141 本波补齐**。
- **凭据到位即可联调范围**：EZproxy / 手工粘 Cookie 的**非 CF 订阅刊**（Elsevier ScienceDirect、Springer、IOP…）今天就能跑通（路线A）；RSC / ACS / Wiley / ScienceDirect 这类 **JA3 绑定强 CF 站**（route-B 浏览器内注入）**代码通路已通**，待真机凭据 + 有头 Chrome 验活体。
- **刻意留后（-153，不阻塞）**：shibboleth/openathens/carsi/webvpn 自动可见 SSO 登录、`verify_live` 联网探针。

---

## 一、离线自检实测（本波复算 · 全绿）

| 自检 | 命令 | 结果 |
|---|---|---|
| A5 框架层 | `python -m fulltext_fetcher.institutional.selftest_a5_framework` | **A5_FRAMEWORK_OK** |
| EZproxy 登录骨架 | `python -m fulltext_fetcher.institutional.ezproxy_login` | **EZPROXY_LOGIN_OK**（含端到端 mock 5 场景：多跳登录/超时/无 URL/端到端路由/非 EZproxy 未实现）|
| assisted_auth Tier-0 | `python -m fulltext_fetcher.institutional.assisted_auth` | **ASSISTED_AUTH_OK**（11 项：判态/叫人/门控/清洗/编排/退避/超时）|
| login_browser 公共层 | `python -m fulltext_fetcher.institutional.login_browser` | **selftest OK** |

> render_fetch 注入 hook 自检见 §2.3；http_client `HTTP_CLIENT_OK ⑪`、publisher_direct `⑩`、cli `⑤`、run_all `⑪` 机构口径断言见既有 `run_all_selftests.py`（本波未重跑全套，仅跑上表 A5 4 项）。
> `ezproxy_login.py` 尾部曾有工具调用粘贴伪影（-158 U.2），现 EOF 干净（L322 `print("EZPROXY_LOGIN_OK")`），compileall 不受影响。

---

## 二、credential-in→run 全链路追踪

### 2.1 凭据入口（三口径 · 已就绪）

- **CLI**：`--institutional` / `--ezproxy-prefix` / `--institution-cookie` / `--institution-domain`（`cli.py` L198-266、`run_all.py` L751-883；Cookie/前缀默认取 env，避免留 shell 历史）。
- **env**：`FTF_INSTITUTIONAL` / `FTF_EZPROXY_PREFIX` / `FTF_INSTITUTION_COOKIE` / `FTF_INSTITUTION_DOMAINS`。
- **文件**：项目根 `.ftf_institutional.local.json`（`enabled:true`；见 `.example`）。
- **合并**：`bootstrap_institutional_config(cfg, cli_institutional=…)`（`cli.py` L277-278、`run_all.py` L892-893）；**CLI 已填字段优先、不被 FTF 覆盖**（A5 自检 ⑦ 断言）。两入口口径逐字节一致。

### 2.2 路线A（HTTP 直链 / publisher_direct）— 就绪 ✅

链路：`cred → cfg(institutional/ezproxy_prefix/institution_cookie/institution_domains) → publisher_direct`（仅 `institutional=True` 产候选，`_apply_institutional_sources` 先覆盖 `--sources` 再补插源，置 websearch 前或末尾）`→ HttpClient.get`：命中 `institution_domains` 白名单则注入 `Cookie: institution_cookie` + `rewrite_url_for_proxy`（EZproxy 前缀式 / 主机名改写式，`http_client.py` L286-292）`→ 下载 + %PDF 魔数 + 强制内容 QC`。

- **零副作用护栏**：无凭据时 `needs_institution_access` 恒 False、`rewrite_url_for_proxy` 恒等、`publisher_direct` 产 `[]` → 与未启用逐字节一致。

### 2.3 路线B（浏览器内抓字节 / route-B / render_fetch）— ✅ 已补齐（-141 本波）

- **已就绪（render_fetch 侧）**：`inject_institutional_session`（`render_fetch.py` L512）+ `rewrite_url_for_injection_plan`（L503）已实现，且**已接线**进抓取流程——导航前注 Cookie（L1100-1104）、PDF 直链 EZproxy 改写（L1197-1198）；`render_download_pdf_bytes(injection_plan=…)` 形参就位（L1288/1322）；离线 mock tab 自检断言 `set_cookie` 生效（L1556-1600）。
- **~~断点~~ → 已接线（download 侧，-141）**：`download.py._browser_capture_fallback`（route-B **生产唯一调用点**）现先调 `_route_b_injection_plan_for(cfg, url)` 构造 `RouteBInjectionPlan`，再把 `injection_plan=` 随 `render(...)` 一并传入；构造走**新增纯函数** `route_b_bridge.plan_route_b_injection_from_config(cfg, url)`（cfg→plan，**不建 AuthSession**，判据委托 `http_client.needs_institution_access` → route-A/route-B 白名单口径逐字节一致）。
- **结果**：凭据进 Config 后，route-B 浏览器路径（RSC/ACS/Wiley/ScienceDirect 等 JA3 绑定强 CF 站）**会在同一 nodriver 会话内注入机构 Cookie + 做 EZproxy 改写**（与 B1 同 JA3）。无凭据 / host 未命中 `institution_domains` 白名单 / 缺 institutional 包 → `injection_plan=None`，route-B 行为与未启用逐字节一致（零副作用护栏）。
- **离线自检**（本波新增，全绿）：`selftest_a5_framework` ⑧（纯函数 4 例：命中→cookie/rewrite 正确；无凭据/未命中/OA 域→None）+ `download` 自检 ⑤e（接线断言：机构 cfg→`injection_plan` 被填、宿主正确；非机构/未命中→None）；`run_all_selftests.py` **PASS=46/FAIL=0**。

---

## 三、联调清单

### A. 现在就能做（不需真凭据；本波识别，落地待属主）

- [x] **补 1 根线（核心）** ✅ **-141 本波完成**：`_browser_capture_fallback` 现经 `_route_b_injection_plan_for(cfg, url)` → `route_b_bridge.plan_route_b_injection_from_config(cfg, url)` 构造 `RouteBInjectionPlan`，以 `injection_plan=` 传入 `render(...)`；判据委托 `needs_institution_access`（route-A/B 同门），**未 new AuthSession**（遵本条建议）。
- [x] **补线的离线 selftest** ✅ **-141 本波完成**：`selftest_a5_framework` ⑧ + `download` 自检 ⑤e——命中→`injection_plan.cookie_count()≥1` 且 `rewrite_target_host` 正确；无凭据 / host 未命中 / OA 域 → `injection_plan=None`（逐字节不变）。`run_all_selftests.py` PASS=46/FAIL=0。
- [ ] `.ftf_institutional.local.json.example` 拷贝指引与《A5用户凭据接入指引-141.md》对齐（勿提交真凭据到 git）。
- [ ]（可选）`config.py` 增显式 `assisted_auth` / `assisted_profile_dir` 字段（现靠 `getattr` 默认可跑，但无 CLI 面）。

### B. 凭据到位后验收（用户投喂 EZproxy 前缀 / 会话 Cookie 后）

- [ ] **路线A 冒烟**：`--institutional --ezproxy-prefix … --institution-cookie … --institution-domain sciencedirect.com,link.springer.com` 跑 5 条 Elsevier/Springer 非 CF 订阅刊 → 真全文 + 过内容 QC。
- [ ] **路线B 冒烟（补线后）**：跑 5 条 RSC/ACS/Wiley → 浏览器内注 Cookie 后同源 fetch → 真全文 + **强制** QC（`force=True`）；核对 Cookie 未回放到 curl_cffi（保 JA3 一致，遵 route_b_bridge 纪律）。
- [ ] **净增结算**：只认过门③④⑤的 `still_missing` 内 DOI，authoritative 回写 `coverage.json`（禁 metadata 求和虚高）。

### C. 刻意留后（-153，不阻塞当前联调）

- [ ] shibboleth/openathens/carsi/webvpn 自动可见 SSO 登录（现仅 EZproxy 分支布线，其余 `NotImplementedError`）。
- [ ] `verify_live` 联网探针（现离线 gate：仅查 Cookie 未过期；联网 401 vs 200 判活留 -153）。

---

## 四、边界与安全

- 凭据全程 `redact`、**不入日志 / chat**；无凭据零副作用（与未启用逐字节一致）。
- A5 仅供**拥有合法机构订阅、对内容有访问权者**在已授权前提下取用；**不得绕付费墙**。
- **真实机构凭据只能用户投喂、无法代生成**；索取时机由用户定（现选「A5 作后续」）。凭据未到前免费侧 326/32.63% 即当前交付封顶。

---

*核验 2026-07-03｜-177｜task-686d5e3b｜只读盘 + 跑 A5 4 项离线自检（全绿）+ 本 md；未改生产码/coverage/git。核心发现：路线A 就绪、路线B 缺 1 根 cfg→injection_plan 线（download._browser_capture_fallback 未传 injection_plan）。*

*更新 2026-07-03｜-141｜**路线B 缺口已补齐**：新增 `route_b_bridge.plan_route_b_injection_from_config(cfg,url)`（cfg→plan，判据委托 `needs_institution_access`，不建 AuthSession）+ `download._browser_capture_fallback` 以 `injection_plan=` 传入 `render(...)` + 离线 selftest（a5_framework ⑧ / download ⑤e）。`run_all_selftests.py` PASS=46/FAIL=0、compileall/lints 全绿、零副作用。仅改 4 个代码文件（route_b_bridge/download/institutional __init__/selftest_a5_framework）+ 本 md；未碰 coverage/黑名单/口径，无真下载。真机凭据验收（§三.B）仍待用户投喂。*
