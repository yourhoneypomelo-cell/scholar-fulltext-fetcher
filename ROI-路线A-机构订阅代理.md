# ROI · 路线A：机构订阅 / EZProxy / 机构代理 直取闭源 PDF 可行性与成本（只调研不实现）

> 交付：组员 **-144**｜2026-07-02｜工单来源：总指挥 **-156**「ROI调研·路线A：机构订阅/EZProxy/机构代理 直取闭源PDF 可行性与成本（只调研不实现）」（taskId=`task-a43d06e6-efd5-470e-83f8-106c0ed900ef`）。
> 边界：**纯文档、只新建本 1 份 md，不改任何 `.py`/PDF/metadata、不联网抓正文**。数据取自仓内已提交文档、源码与 `out/still_missing_shards/_shard_stats.json`（551 条，2026-07-02 03:35）。
> 关系：本文承接 -149《回收实测结论-CF与免费路线到顶》、-153《北极星主流程与回收结论汇总》、`机构订阅集成设计.md`、N3/N4《机构订阅与住宅代理方案》/《Cookie 持久化架构》，以及 -144 同日产出的《ROI-路线B-render_fetch》。**路线A 与路线B 互补**：A 破「真订阅付费墙」，B 破「JA3 绑定型 CF / viewer 包壳」；二者叠加才是 still_missing 的完整解法。
> 一句话定位：**路线A = 在「用户已拥有合法机构订阅权限」前提下，经 EZproxy/CARSI/Shibboleth/OpenAthens/WebVPN 把 still_missing 里 ~300+ 纯订阅缺口合法取回——这是免费路线物理到顶后唯一根本途径，但强依赖机构凭据、且工程面比「开 `--institutional`」大得多。**

---

## 〇、TL;DR（先给决策卡 4 个数）

| 决策卡字段 | 结论（点估 + 区间） |
|---|---|
| **① 预期成功率增量**（still_missing≈551 的闭源桶；**前提：用户有合法机构订阅且覆盖对应出版商**） | **点估 +350~400 篇 ≈ +35~40pp**（44.8%→**~79~85%**）。分档：**全量 CARSI/EZproxy + Elsevier/ACS/RSC/Wiley/Springer 均覆盖** → +350~420；**仅 EZproxy + 部分社** → +150~250；**无机构凭据** → **+0**。still_missing 主体 **Elsevier 344（62%）+ ACS 75 + RSC 58** 几乎全属此桶。 |
| **② 接入复杂度 / 可维护性** | **中-高（分阶段）**。**最小可用路径**（手动导出 Cookie + `publisher_direct --institutional` + 既有 `http_client` EZproxy 钩子）：**~3~5 人日**。**完整路径**（CookieStore 持久化 + SSO 可见浏览器登录 + CARSI/WebVPN + 按出版商批级一次登录 + JA3 站页内直下）：**~2~3 人周**（N3/N4/P0 估 3~5h Cookie 层 + 3~5h 批级分组 + 8~12h institutional 源 + 联调实测）。维护 = **会话 Cookie 过期需人工重登（MFA）**、出版商路由/CF 变更、批量风控。 |
| **③ 订阅/代理成本模型** | **对用户边际 ¥0**（机构已付年费包，典型高校 Elsevier+ACS 等 **$5万~$200万+/年** 数据库预算，个人不另付）。**实现成本**：最小路径 **~3~5 人日**；完整 A5 **~2~3 人周**。**持续**：无住宅代理刚需（走图书馆 EZproxy/CARSI 出口）；Cookie 刷新人工 **~月度级**；若触发出版商 bulk 风控需降并发/分桶。**对比**：无订阅时单篇 $30~50 × 551 ≈ **$1.6万~$2.7万** 买断价（仅作 ROI 参照，非推荐路径）。 |
| **④ ToS/版权/合规风险与边界** | **合法前提**：仅对**用户确有订阅权限**的全文，经机构正门（EZproxy/SSO/IP 授权）取用，等效人工浏览器登录。**红线**：❌ 共享/转售 Cookie；❌ 无权限批量爬取；❌ 系统性超量下载触发 Elsevier/ACS **bulk download 检测**（可封号/通报图书馆）。**CARSI/机构 AUP** 通常禁止把凭据用于第三方自动化工具——须机构 IT/馆员知情或仅限个人研究规模。**默认关**（`institutional=False`、三字段空）= 零合规面；启用后责任在用户。**Sci-Hub/灰色源不在路线A 范围**。 |

> **核心判断**：路线A 是 **still_missing 里 ~300+ 真订阅付费墙的唯一合法根本解**，预期增量 **远大于路线B（+2pp）**，但 **100% 门控于「有没有机构订阅」**——没有凭据则 ROI=0。工程上不必从零造：`http_client` 钩子 + `publisher_direct` 已就绪，缺的是 **Cookie 持久化 + SSO 浏览器链 + 与 JA3 站（RSC）的页内直下协同**（见 N4/SciTeX 骨架）。**建议决策：有机构用户 → P0 排最小路径实测 20 条 still_missing 分片；无机构 → 路线A 不排，转路线B/接受 44.8% 净覆盖边界。**

---

## 一、路线A 是什么 & 仓内现状盘点

**路线A = 机构订阅 / EZProxy / 联邦 SSO（Shibboleth·OpenAthens·CARSI）/ WebVPN / 校园 IP 授权**，在**已获合法授权**前提下，把出版商 PDF 直链或落地页经机构通道取回。

与免费路线的边界（-149 已锤死）：

| 失败类型 | still_missing 规模 | 免费路线 | 路线A |
|---|---:|---|---|
| **真订阅 403 付费墙**（Elsevier 订阅刊、ACS/RSC 订阅刊） | **~300+** | ❌ 物理拿不到 | ✅ **唯一合法解** |
| **Elsevier IP/登录墙**（非 CF） | **~340**（10.1016 前缀） | browser_search 0/10、wayback 0/12 到顶 | ✅ EZproxy/CARSI 登录态 |
| **JA3 绑定型 CF + 订阅**（RSC articlepdf） | **~58** | curl_cffi 回放 403 | ⚠️ 需 **A5 授权会话 + 路线B 页内直下** 叠加 |
| **可回放型 CF-OA**（ACS-authorchoice 等） | **~10~20** 子集 | ✅ FS/nodriver shim 已可救 | 路线A 非必须（边际小） |

仓内**已有** vs **缺失**：

| 组件 | 位置 | 现状 | 路线A 关系 |
|---|---|---|---|
| **EZproxy URL 重写 + Cookie 注入钩子** | `http_client.py`（`needs_institution_access` / `rewrite_url_for_proxy`） | ✅ 骨架已落地，**默认关、零副作用** | 路线A 的 HTTP 层地基 |
| **配置三字段** | `config.py`（`ezproxy_prefix` / `institution_cookie` / `institution_domains`） | ✅ 已定义，默认空 | 用户凭据入口 |
| **机构直链源** | `sources/publisher_direct.py` + CLI `--institutional` | ✅ 8+ 出版商 DOI→PDF 模板，**gated** | 产候选；无 Cookie 仍 401/403 |
| **机构订阅设计文档** | `机构订阅集成设计.md` | ✅ 三种接入方式 + 合规 + 回退矩阵 | 实现规格 |
| **Cookie 持久化 + 一次性登录浏览器** | N4 设计（`CookieStore` 四层） | ❌ **未实现** | 批量复用登录态的前提 |
| **SSO 浏览器源 `institutional.py`** | N3/N4 + SciTeX 骨架 | ❌ **未实现** | CARSI/WebVPN/OpenAthens 自动化 |
| **按出版商批级一次登录** | scansci `batch_download` Phase2 | ❌ 未移植 | 降登录次数、提吞吐 |
| **TDM API token 层** | 角度8（Wiley TDM / Elsevier APIKey） | ❌ 未实现 | 与 A5 **同层**「机构授权 API 形态」，可并行 |

**结论**：路线A 不是 greenfield——**HTTP 改写 + 直链构造已就绪**；缺口在 **「登录一次、批量复用」的会话层** 与 **强 CF 出版商上的浏览器内下载**（与路线B 交界）。

---

## 二、Deliverable ①：对 still_missing 553（实测 551）闭源桶的预期成功率增量

### 2.1 分母与桶拆解（`_shard_stats.json` + 跨文档口径）

- **净覆盖基线**：**448/999 ≈ 44.8%**（QC 黑名单感知，`out/coverage.json`）。
- **still_missing**：**551** 唯一 DOI（任务口径 553 ≈ 同集 ± 续跑抖动）。
- **闭源出版商构成**：

| 分片桶 | 条数 | 占比 | 主要前缀 | 墙型（-149/-144 分片 ROI 标注） | 路线A 预期救回率（**有订阅**） |
|---|---:|---:|---|---|---|
| **elsevier** | 344 | 62.4% | 10.1016 | IP/登录墙，免费到顶 | **85~95%** → **~290~327** |
| **acs** | 75 | 13.6% | 10.1021 | 混：**订阅 403** + CF403(OA 子集) | **订阅部分 70~85%** → **~45~55**（扣 OA 已由 FS 覆盖） |
| **rsc** | 58 | 10.5% | 10.1039 | **JA3 绑 CF + 订阅** | **60~75%**（须叠加页内直下）→ **~35~44** |
| **wiley** | 19 | 3.4% | 10.1002/10.1111 | CF + 订阅 | **70~85%** → **~13~16** |
| **springer** | 20 | 3.6% | 10.1007/10.1023/10.1134 | 常规链路 | **80~90%** → **~16~18** |
| **aip/iop/other** | 35 | 6.4% | 多前缀 | CF 或长尾 | **40~70%** → **~12~20** |
| **合计点估** | 551 | 100% | — | — | **~350~420 篇** |

### 2.2 三档增量（诚实标注前提）

| 场景 | 条件 | 从 still_missing 救回 | 净覆盖增量 | 净覆盖率 |
|---|---|---:|---:|---|
| **A · 全量机构** | 合法 CARSI/EZproxy + 覆盖表中六社 + 会话有效 + RSC 走页内直下 | **+350~420** | **+35~42pp** | **~80~87%** |
| **B · 部分机构** | 仅有 EZproxy + Elsevier+Springer，无 ACS/RSC 全包 | **+150~250** | **+15~25pp** | **~60~70%** |
| **C · 无机构** | 无凭据 / 校外无 VPN | **+0** | **+0pp** | **~44.8%**（不变） |

### 2.3 与路线B 的分工（避免 double-count）

- **路线B 净增点估 +20 篇（+2pp）**：只吃 JA3-OA / viewer-only / 可回放 CF-OA 小片；**救不了真订阅墙**（-144《ROI-路线B》§四）。
- **路线A 独占**：上表 **~300+ 真订阅** + **Elsevier 344 主体**。
- **叠加区（RSC 58、部分 ACS）**：路线A 提供**授权会话**，路线B 提供**同会话内页内 fetch**——工程上应合并为 A5 一条链，ROI 算在 A，不重复加计。

### 2.4 必须写进决策卡的诚实前提

1. **门控于凭据**：无机构订阅 → 路线A ROI **严格为 0**；决策卡须分「有/无机构用户」两列。
2. **非 100% 包覆盖**：551 条中可能有**未订刊、单篇 OA 例外、停刊**等，10~15% 即使用户「有机构」仍可能 miss。
3. **QC 仍必要**：机构通道取回的是**正确出版商 PDF**，但不替代 DOI-in-text 校验——假阳主因是 websearch，路线A 从权威直链取，**假阳率预期 ≈ DOI-keyed 源水平（~0%）**。
4. **与免费天花板对比**：免费公开边界 ~82%（metadata 口径）/ 净 **44.8%**（QC 后）；路线A 的价值是把 **「付费墙内那 ~40pp」** 在合法前提下收回，而非替代 OA 源。

---

## 三、Deliverable ②：接入复杂度、认证流与可维护性

### 3.1 三条主流通道（摘自 `机构订阅集成设计.md` §1）

| 通道 | 原理 | 适用 | 本项目改造点 | 自动化难度 |
|---|---|---|---|---|
| **EZproxy 前缀/主机名重写** | 图书馆网关；URL 改写 + 会话 Cookie | 校外最普遍 | `rewrite_url_for_proxy` ✅；缺 CLI 暴露 | **中**（Cookie 导出/刷新） |
| **SSO / Shibboleth / OpenAthens / CARSI** | SAML 联邦；WAYF→IdP→SP Cookie | Elsevier/IEEE/Wiley 等大社 | Cookie 注入 ✅；**缺浏览器登录** | **高**（MFA/WAYF/验证码） |
| **IP 白名单 / WebVPN** | 出口 IP 在机构段内 | 校内或 VPN 后 | 可选 `proxies` TODO | **低**（VPN 已连则近零改造） |

**认证流（推荐生产形态，N3 + SciTeX 骨架）**：

```text
用户一次性可见浏览器登录（CARSI/WebVPN/EZproxy/OpenAthens）
    → CookieStore 持久化（按 SP 域名分桶，~7~30 天有效）
    → find_candidates: publisher_direct 构造授权 URL
    → HttpClient.get: 域名分流 + Cookie 注入 + EZproxy 改写
    → [若 CF/JA3] 同 Cookie 会话内 nodriver 页内直下（路线B 支路）
    → download 层 %PDF 校验 → 落盘
```

**批级优化**（scansci Phase2）：still_missing 按出版商分组 → **每组一次登录** → 批量取该组全部 DOI（Elsevier 344 条可能 **1~2 次登录** vs 逐条 344 次）。

### 3.2 实现复杂度分阶段

| 阶段 | 范围 | 人力 | 依赖 | 可验证产出 |
|---|---|---:|---|---|
| **P0 最小可用** | 手动 Cookie + `--institutional` + `institution_domains` 白名单 + 20 条 still_missing 分片实测 | **3~5 人日** | 用户自行浏览器登录导出 Cookie | Elsevier/ACS 直链 401→200+%PDF |
| **P1 会话持久化** | N4 CookieStore + `open_login_browser()` + 按域过期提醒 | **+3~5 人日** | P0 | 「登录一次、批量 50 条」不断线 |
| **P2 SSO 源** | `sources/institutional.py` + CARSI/WebVPN 配置模板 | **+5~8 人日** | P1 | scansci 同级 MCP/CLI 子集 |
| **P3 批级 + JA3** | 出版商分组 + RSC 页内 fetch 与 A5 同会话 | **+3~5 人日** | P2 + 路线B 页内支路 | RSC 58 桶救回率 >60% |

**总完整路径：~2~3 人周**（与 ⑤ 母表 A5/N3/N4 排期一致）。

### 3.3 可维护性风险

| 风险 | 表现 | 缓解 |
|---|---|---|
| **Cookie 过期** | 401/HTML 登录页，`%PDF` 校验拦截 | CookieStore 过期检测 + CLI 提示重登；按 SP 分桶 |
| **MFA / 验证码** | 自动化登录中断 | **默认不做全自动**；可见浏览器一次性登录（N4 设计） |
| **出版商改 URL/CF** | 直链模板失效 | `publisher_access_catalog` 维护；publisher_direct 前缀表 |
| **bulk 风控** | IP/账号封禁、图书馆通报 | 沿用按域限速+低并发；单线程机构桶；分日批跑 |
| **EZproxy 版本差异** | 前缀式 vs 主机名式 | `rewrite_url_for_proxy` 双模式（TODO 主机名式） |

---

## 四、Deliverable ③：订阅/代理成本模型

### 4.1 用户侧（边际成本）

| 项 | 典型成本 | 说明 |
|---|---|---|
| **机构数据库订阅** | **$0 边际**（已含在学费/科研经费） | 单校 Elsevier SD 全库常 **六位数 USD/年**；ACS/RSC/Wiley 分包另计 |
| **CARSI / EZproxy** | **$0** | 图书馆 IT 已部署 |
| **WebVPN** | **$0** | 校内 CAS，密码不经工具（scansci 设计） |
| **个人买断 551 篇** | **~$1.6万~$2.7万**（$30~50/篇） | 仅 ROI 参照；**非路线A 目标用户** |
| **住宅代理** | **路线A 通常不需要** | 机构出口 IP 已授权；住宅代理是 Scholar 反爬（角度6）用，非 A5 刚需 |

### 4.2 项目侧（实现 + 运维）

| 项 | 一次性 | 持续 |
|---|---|---|
| **工程（P0~P3）** | **3~5 人日（P0）~ 2~3 人周（全量）** | 季度级模板/CF 跟进 **~0.5 人日** |
| **依赖** | scansci/instsci **可选**（重）；本仓 nodriver **已装** | nodriver 版本跟进 |
| **运维人工** | Cookie 首次导出 **~15 分钟** | 过期重登 **~月度 15~30 分钟**；MFA 不可无人值守 |
| **算力** | 0 | 机构 HTTP 直链 **~2~5s/篇**；浏览器登录 **~1~3 分钟/出版商组** |

### 4.3 ROI 对比（决策卡用）

- **有机构用户**：实现 **~1 人周（P0+P1）** → 预期 **+35~40pp** → **每 pp 成本 ~0.15~0.25 人日**，**远高于路线B（+2pp / 1~2 人日）**。
- **无机构用户**：实现成本 **∞ ROI（+0）** → **不排路线A**。

---

## 五、Deliverable ④：ToS / 版权 / 合规风险与边界

### 5.1 合法使用边界（项目一贯口径）

✅ **允许**（路线A 设计目标）：

- 用户**本人**所在机构**已订阅**的全文；
- 经 **EZproxy / CARSI / SSO / 校园 IP** 等**机构正门**，等效人工登录后下载；
- **个人研究 / 课题组合理规模**批量（配合限速）。

❌ **禁止**（合规红线，`机构订阅集成设计.md` 置顶）：

- 绕过、破解付费墙；使用**非本人/非本机构**凭据；
- **共享、转售、囤积** Cookie 或 PDF；
- 引入 **Sci-Hub / LibGen** 等灰色源（scansci 可选模块，**本项目不采纳**）；
- **无权限**系统性批量爬取（尤其 Elsevier **bulk download detection**）。

### 5.2 出版商与机构政策风险

| 风险源 | 严重度 | 说明 |
|---|---|---|
| **Elsevier SD bulk 检测** | **高** | 短时间大量 PDF 可触发账号/机构 IP 封禁；须低并发、分桶、礼貌延迟 |
| **ACS / RSC ToS** | 中 | 禁止 robot 抓取；机构通道「像人一样用」通常可接受，超量仍风险 |
| **CARSI / 图书馆 AUP** | 中 | 部分馆禁止把联邦登录用于自动化脚本——**须馆员知情或仅限个人终端** |
| **中国著作权法** | 中 | 合理使用边界；**不得**向第三方传播下载全文 |
| **出口 / 数据合规** | 低 | PDF 内容一般不涉出境审查；凭据**不得**入 git/日志（设计已要求） |

### 5.3 项目默认安全姿态

- `institutional=False` + 三字段空 → **与未引入 A5 逐字节一致**；
- `publisher_direct` 无 Cookie 时 401/403 → **`%PDF` 校验过滤，不产假成功**；
- 凭据**不落库、不入 metadata.jsonl**（设计 §5）。

---

## 六、Deliverable ⑤：可复用开源工具与采纳建议

| 项目 | 许可 | 能力 | Stars/活跃 | 路线A 建议 |
|---|---|---|---|---|
| **[scansci-pdf](https://github.com/Rimagination/scansci-pdf)** + **[instsci](https://github.com/Rimagination/instsci)** | Apache-2.0 / MIT | WebVPN(100+ 高校 CAS)、CARSI、EZproxy、CloakBrowser 登录、批级 Phase2 | ~216 / ~96；2026-05~06 活跃 | **🧩 借鉴架构**（中台登录 + Cookie 持久化）；**不整体依赖**（含 Sci-Hub 可选模块、较重） |
| **[SciTeX-Scholar](https://github.com/ywatanabe1989/SciTeX-Scholar)** | 见仓 | OpenAthens/SSO Playwright 链 + chrome-viewer 下载三策略 | 新、活跃 | **🧩 借鉴** SSO→download 主链（见 `选型2026-A5机构订阅SSO浏览器接入实现者骨架-SciTeX参考.md`） |
| **CloakBrowser** | MIT | reCAPTCHA v3 ~0.9；instsci 认证窗口 | ~274 | **P2 待评估**（SSO 登录窗；非默认） |
| **本仓 `publisher_direct` + `http_client` 钩子** | 本项目 | DOI 直链 + EZproxy 改写 | ✅ 已落地 | **✅ 直接复用**（P0 主力） |
| **本仓 nodriver + 路线B 页内直下** | AGPL-3.0 | RSC/JA3 授权会话内取字节 | ✅ 已装 | **✅ 与 A5 叠加**（非替代） |
| **LibKey Nomad** | 免费扩展 | 浏览器一键机构全文 | 产品非库 | **参考 UX**，非 batch 引擎 |

**整合建议（一句话）**：

- **P0**：不引外部重依赖 → 手动 Cookie + 本仓 `http_client` + `publisher_direct --institutional` + still_missing 分片实测。
- **P1+**：借鉴 **instsci CookieStore + 可见浏览器登录**、**SciTeX authenticate→download 链**；CARSI/WebVPN **配置模板**可参考 scansci MCP 工具命名，**代码自研**以保持无 Sci-Hub、默认关。
- **TDM API**（Wiley/Elsevier/IEEE token，角度8）：与 A5 **同配置层**并行，非替代 EZproxy。

---

## 七、与路线B 的决策矩阵（给总指挥汇总用）

| 维度 | 路线A（机构订阅） | 路线B（页内直下） |
|---|---|---|
| **主要吃掉的 still_missing** | 真订阅墙 ~300+、Elsevier 344 | JA3-CF-OA ~15、viewer ~10 |
| **净增量点估** | **+35~40pp**（有机构） | **+2pp** |
| **凭据门控** | **必须** | 不需要 |
| **实现人力** | 3~5 人日 ~ 2~3 人周 | 1~2 人日 |
| **合规** | 机构 AUP + bulk 风控 | 同（只下 OA/已授权） |
| **优先级** | **有机构用户 → P0** | 无机构 / 提质 → P2 |

**推荐组合**：**A5（机构会话）+ 路线B（同会话页内 fetch）+ 既有 FS shim（ACS 可回放 CF）** = still_missing 诚实上限。

---

## 八、给决策卡 / 总指挥的一句话收口

**路线A（机构订阅/EZProxy/SSO）是 still_missing≈551 里 Elsevier 344 + ACS/RSC 订阅主体的唯一合法根本解：在用户拥有合法机构订阅时，点估净增 +350~400 篇（+35~40pp，44.8%→~80~85%），ROI 远高于路线B；无凭据则严格 +0。仓内 `http_client` EZproxy 钩子 + `publisher_direct --institutional` 已就绪，最小可用 3~5 人日（手动 Cookie），完整 A5（CookieStore + CARSI/WebVPN + 批级登录 + RSC 页内直下）约 2~3 人周。成本对用户边际 ¥0，风险在 bulk 下载风控与 CARSI AUP——须默认关、低并发、凭据不入库。开源借鉴 scansci/instsci 与 SciTeX 登录链，不引入 Sci-Hub。建议：有机构 → 立刻 P0 实测 20 条 still_missing 分片；无机构 → 不排 A，接受 44.8% 净覆盖或走商业解锁。**

---

## 九、来源 / 证据索引

**仓内数据**：
- `out/still_missing_shards/_shard_stats.json`（551 条分桶：elsevier 344 / acs 75 / rsc 58 / …）。
- `out/coverage.json`（净成功 448/999≈44.8%）。
- `out/still_missing.txt`（闭环续跑输入）。

**仓内文档**：
- `回收实测结论-CF与免费路线到顶.md`（-149/-150：免费到顶、Elsevier 0/10+0/12、真墙 ACS80+RSC41）。
- `机构订阅集成设计.md`（三种接入、合规、http_client 单点注入）。
- `选型2026-机构订阅与住宅代理方案.md`（N3：scansci/instsci/CARSI/WebVPN）。
- `选型2026-A5机构订阅SSO浏览器接入实现者骨架-SciTeX参考.md`（institutional.py 骨架）。
- `选型2026-出版商前缀直链路由表-scansci对标补丁.md`（publisher_access_catalog、SSO 入口词）。
- `ROI-路线B-render_fetch.md`（-144：路线分工、JA3 死结、+2pp 点估）。
- `北极星一键批量下载-主流程与回收结论汇总.md`（-153：still_missing 闭环）。
- `检索成果-角度8-出版商TDM全文API与Scholar被引口径与路线图ROI.md`（TDM token 与 A5 同层）。

**仓内源码**：
- `fulltext_fetcher/http_client.py`（`needs_institution_access` / `rewrite_url_for_proxy`）。
- `fulltext_fetcher/sources/publisher_direct.py`（`--institutional` 门控）。
- `fulltext_fetcher/cli.py`（`--institutional` 开关）。

**外部参考（2026-07 口径，本文未联网复验细节）**：
- Rimagination/scansci-pdf、instsci（机构登录 MCP/WebVPN/CARSI）。
- ywatanabe1989/SciTeX-Scholar（OpenAthens SSO + Playwright 下载链）。

---
*核验 2026-07-02｜-144｜工单「ROI·路线A 机构订阅/EZProxy/机构代理 直取闭源PDF」（taskId=`task-a43d06e6-efd5-470e-83f8-106c0ed900ef`）｜结论：路线A=真订阅墙唯一合法根本解，有机构时 +350~400 篇（+35~40pp），无机构 +0；最小路径 3~5 人日，完整 A5 ~2~3 人周；合规须默认关+低并发；与路线B 叠加取 still_missing 上限。仅新建本 1 份文档，未改任何 .py。*
