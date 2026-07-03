# route-B RSC 0/8 归零因与收口结论 · 160

> 交付：**谷歌学术人机认证-160**（worker）｜taskId=`task-d2738eb4-7ba9-4f72-8d1a-79f153a26090`｜2026-07-02
> 边界：**只读诊断**；未发射 route-B、未改 `render_fetch.py`/coverage、未提交 git。
> 证据源：`out/routeB_rsc_launch_156.log`（-156 生产脚本 `_routeb_rsc_launch_156.py` 全量输出）、《经验记录》S.2/P 节、《选型2026-route-B反RSC-governor补丁方案-165.md》、《检索成果-开源过认证方案全网扫描-RSC-governor-165.md》、174 机制分桶。

---

## 〇、TL;DR（给最终交付）

| 项 | 结论 |
|---|---|
| **本波结果** | RSC 金 OA **8/8 全 MISS**，`netgain=0/8` |
| **归零主因** | **非 JA3 回放链**（已是 route-B 页内直下）；主因 = **直接导航 articlepdf 直链 + 连续快跑** 触发 RSC 第二道 **`crawlprevention/governor` rate-gate**（7× `no-pdf-captured` + 1× `blocked:challenge-page`） |
| **与 PoC 悖论** | P 节单条 `d5ra08493h` 484KB 成功 vs 本波 8 条全败 → **单条 PoC ≠ 批量可复现**；governor「第一篇过、第二篇即死」 |
| **能否救** | **需 -165 governor 反制补丁**（landing 预热 + per-host 30–90s 限速/冷却 + governor 检测）；**坏 reCAPTCHA 不可解**，只能不触发 |
| **当前处置** | **defer**——不扩 route-B RSC 长尾，等补丁小样本验证 |
| **ROI** | RSC **金 OA ~8 条上限**，点估 **+0~8**（本波实测 **0**）；RSC **订阅 ~59 条唯 A5**，route-B 对订阅墙 `no-pdf` 为正确行为 |

---

## 一、0/8 逐条机理（`out/routeB_rsc_launch_156.log`）

生产路径：`_routeb_rsc_launch_156.py` → `render_download_pdf_bytes(headless=False, pdf_url_fallbacks=build_static_candidates(doi))`，单头锁 `out/.route_b.lock`，timeout=120s，**有头串行 8 条**。

| # | DOI | 年/刊 | 耗时 | note | 归类 |
|---:|---|---|---:|---|---|
| 1 | `10.1039/c4ra00825a` | 2014/ra | 126s | `no-pdf: no-pdf-captured` | governor/viewer 未落字节 |
| 2 | `10.1039/c4ra02037e` | 2014/ra | 126s | `no-pdf: no-pdf-captured` | 同上（websearch 曾抓 NIST 假阳） |
| 3 | `10.1039/c4ra14572k` | 2014/ra | 125s | **`blocked:challenge-page`** | CF 或 governor 质询页 |
| 4 | `10.1039/c5ra04969e` | 2015/ra | 128s | `no-pdf: no-pdf-captured` | 同上 |
| 5 | `10.1039/d0gc02302g` | 2020/gc | 129s | `no-pdf: no-pdf-captured` | 同上 |
| 6 | `10.1039/d2gc02623f` | 2022/gc | 127s | `no-pdf: no-pdf-captured` | 同上 |
| 7 | `10.1039/d3ee02589f` | 2023/ee | 127s | `no-pdf: no-pdf-captured` | 同上 |
| 8 | `10.1039/d5fd00172b` | **2025/fd** | 227s | `no-pdf: no-pdf-captured` | **新文亦败**，推翻「仅老文失败」 |

**汇总**：`pdf_ok=0`，`how=-`（无一命中 b2-viewerfetch），QC 全 `-1.0`。

**关键观察**：
- 全部 fallback 均为 **`pubs.rsc.org/en/content/articlepdf/{year}/{jcode}/{suffix}` 直链**——正是 -165 认定的 **governor 最强触发器**（直怼 `ArticlePdfHandler.ashx`）。
- 7/8 表现为「过盾后仍 0 字节」→ 与 P 节「CDN 内联 viewer + 方法 D 未稳定落字节」一致，但在批量快跑场景下 **连第一篇也未稳定产出**（与 governor 速率门叠加）。
- 1/8 显式 `blocked:challenge-page` → CF 或 governor 质询；当前代码**未区分** `blocked:rsc-governor`（-165 P1 待补）。

---

## 二、两道门分解（CF / JA3 / governor）

| 层 | 本波表现 | 说明 |
|---|---|---|
| **Cloudflare（门①）** | 部分条目可能已过（126s 级耗时暗示在等盾/SSO） | nodriver 真 Chrome **能过**（N.1/N.4 已实证） |
| **JA3 绑定（N.3）** | **不适用本路径** | 本波走 route-B **页内直下**，非 cookie→curl_cffi 回放 |
| **RSC governor（门②）** | **主因** | 应用层 rate-gate + 坏 reCAPTCHA（`Invalid domain for site key`）；**不可硬解** |
| **CDN 内联 viewer（P 节）** | 次要/叠加 | 即使过 governor，articlepdf→silverchair CDN 内联流需 **方法 D（b2-viewerfetch）**；本波 `how=-` 表明未走到成功 how |

**「第一次过、第二次过不去」**：-165 实锤 governor 按速率/行为判定；`_routeb_rsc_launch_156.py` **8 条连续串行、间隔≈0、直导航 articlepdf** → 完美踩中触发条件。解释 P 节 **单条** `d5ra08493h` 成功与本波 **0/8** 悖论。

---

## 三、-165 补丁方案 vs 开源扫描：什么能救、什么不能

### 3.1 必做补丁（-165，gated·默认关）

| 补丁点 | 作用 | 优先级 |
|---|---|---|
| **P1 governor 检测** | 识别 `crawlprevention/governor` → `blocked:rsc-governor`，与 CF 分开 | P0 |
| **P2 landing 预热** | **勿直导航 articlepdf**；先 landing → 页内 fetch/B2 | P0 |
| **P3 per-host 限速+冷却** | 同 host 间隔 30–90s；命中 governor → 5–30min 冷却 | P0 |
| P4 去 `--disable-blink-features=AutomationControlled` | 降 bot 信号 | P1 |
| P5 坏 reCAPTCHA 不硬解 | 直接冷却，不调打码 | P0 |
| P6 住宅 IP / 会话复用 | 规模化硬门槛 | P2 |

### 3.2 开源借力（165 扫描）

- **能帮**：zendriver/Camoufox/Scrapling → **降 bot 判定、少触发 governor**；住宅代理。
- **帮不上**：2captcha/anticaptcha/SeleniumBase `solve_captcha` → 坏 reCAPTCHA **不可解**。
- **组合解法** = 更强隐身 + 住宅 IP + **-165 补丁 ①②③**。

### 3.3 ROI 判定

| 池 | 规模 | route-B 净增（诚实） | 根本解 |
|---|---:|---|---|
| RSC **金 OA** | ~8 | **本波 0**；补丁后点估 **+0~8** | route-B + governor 补丁 |
| RSC **订阅** | ~59 | **0**（`no-pdf` 正确） | **A5 机构订阅** |
| RSC **CF-hard 全桶** | 67 | 免费果主要在金 OA 子集 | 订阅主体唯 A5 |

**ROI 递减结论**：RSC route-B 价值在 **JA3 机制从 0→1 + 提质**（N.4），**不在清空 still_missing**；本波 0/8 后 **边际 ROI 进一步递减**，符合总指挥「RSC 本波跑完前不扩 route-B」收口。

---

## 四、最终交付收口表述（可直接引用）

1. **route-B RSC 金 OA launch = netgain 0/8**，主因 **governor rate-gate**（直怼 articlepdf + 连续快跑），非 CF/JA3 未解。
2. **当前 defer**：不扩 route-B RSC 发射；**待 -165 governor 补丁**（landing 预热 + per-host 限速/冷却 + 检测）后 **小样本 ≥3 篇** 再验。
3. **诚实 ROI**：RSC 金 OA **上限 ~8 篇**；RSC 订阅 **~59 篇唯 A5**；免费天花板不受本项阻塞（MDPI7/T0/CF-soft 等正交池优先）。
4. **与 PoC 关系**：`d5ra08493h` 484KB 证明 **机制可通**；批量 0/8 证明 **生产路径未就绪**，不能写「RSC route-B 已回收」。

---

## 五、证据路径

| 产物 | 路径 |
|---|---|
| 生产日志（权威 0/8） | `out/routeB_rsc_launch_156.log` |
| 发射脚本 | `_routeb_rsc_launch_156.py` |
| 输入清单 | `routeB_rsc_goldoa.txt`（8 条） |
| governor 补丁设计 | `选型2026-route-B反RSC-governor补丁方案-165.md` |
| 开源扫描 | `检索成果-开源过认证方案全网扫描-RSC-governor-165.md` |
| 经验记录 | `经验记录-踩坑与发现.md` S.2 / P 节 |
| 机制分桶 | `检索成果-still_missing分桶统计刷新与下一波ROI-174.md` §三 |

---

*核验 2026-07-02｜-160｜只读、未发射/未改码｜结论：RSC 金OA route-B 0/8 主因 governor 二道门+articlepdf 直导航；需 -165 补丁 defer；ROI 递减（金OA ~8 上限、订阅 59 唯 A5）。*
