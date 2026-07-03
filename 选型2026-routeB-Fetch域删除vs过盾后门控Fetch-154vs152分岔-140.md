# route-B 方法A 实现分岔:-154「删 Fetch 域改 Network」 vs 152「过盾后门控 Fetch.enable」

> 交付:**谷歌学术人机认证-140**(起草)｜事实源:**-152**(机制层作者,据源码直供)｜工单:总指挥 -148｜2026-07-02。
> **边界**:纯文档、只读,不改任何 `.py`。**结论待 -144 的 A/B 实测(人类 go)落定,本文不写死**;A/B 出结果由 -152 同步后补定论。
> **状态(-143 归档)**:**已并入《经验记录-踩坑与发现.md》正文 · 事实源指针**——A/B 定论(同源 B1 / 跨源过盾后门控 Fetch RESPONSE、Network 域取不到导航 articlepdf body)落 **P 节 + N.8 #2**;PreflightWarn 枚举 ValueError 洪水 bug 落 **W.3**。本文保留作原始分岔分析证据,不再作为待定论草稿。
> 定位:CF 过盾**之后**,如何把 RSC 这类「文章页无明链、需导航到构造的 `articlepdf` 直链、且触 viewer/下载」的 PDF **字节**拿到手——两种 CDP 实现路径的分岔与取舍。

---

## 〇、TL;DR

- **同一目标**(过盾后抓 PDF 字节),**两条 CDP 实现路径**,当前工作树与 152 探针**用法不同**:
  - **-154(当前 `render_fetch.py`)**:**整体删除 `cdp.fetch.enable` RESPONSE 拦截**,方法A 改走 **Network 域**(`ResponseReceived` 标记 PDF 请求 + `LoadingFinished` → `network.get_response_body` 取体)。
  - **152 探针(`_route_b_b2_152.py`)**:**过盾之后才** `cdp.fetch.enable` RESPONSE 拦截(同一 tab),导航到 `articlepdf` 直链,在 RESPONSE 阶段抓体。
- **✅ A/B 已完整跑完(2026-07-02,-152 真机,同机单头 nodriver 0.50.3+Chrome),结论可写死**:
  - **A 端(当前 Network 域方法A)对 RSC `d5ra08493h` = FAIL**(size=0、no-pdf-captured、188s)→ Network 域拿不到导航 articlepdf 的 body。
  - **B 端(过盾后门控 Fetch.enable RESPONSE,同 tab)对同 RSC = PASS**(CF 15.5s 过、**484,829B、%PDF-1.6、24s、QC match**,DOI 在正文)。
  - **ACS-OA(B1 页内 fetch)= PASS**(13.78MB、%PDF-1.4、QC match)。
- **✅ 写死定论**:**同源 PDF(ACS-OA)用 B1 页内 fetch;跨源/viewer 导航 PDF(RSC articlepdf)Network 域不行、必须「过盾后门控 Fetch.enable RESPONSE」(同 tab、cf_clearance 之后才 enable,区别于 -154 早开法)**。-154「整体移除 Fetch」对同源 OK、但**对 RSC 跨源导航不够,需把过盾后门控 Fetch 引回**。
- **仍为假说的部分**:根因「target 互换」——A/B 只证了"Network 不行 / Fetch 行"的**现象**,未直接探到 session 层铁证,故 §二 仍标假说。

---

## 一、两种写法(客观并列,-152 据源码)

| 维度 | **-154:删 Fetch,走 Network 域** | **152 探针:过盾后门控 Fetch.enable** |
|---|---|---|
| 拦截域 | 只开 `network.enable`(`about:blank` 上,导航前) | 过盾后开 `fetch.enable`(RESPONSE 阶段) |
| 抓体 API | `network.get_response_body(request_id)`(`LoadingFinished` 触发) | Fetch RESPONSE 拦截 → 抓 paused 响应体 |
| Fetch.enable 时机 | **不开** | **过盾之后**(cf_clearance 为过盾信号) |
| 代码位置 | `render_fetch.py` `_nodriver_capture_fn._capture`(`on_resp`/`on_finished`,标 `how="b2"`) | `_route_b_b2_152.py` |
| 实测状态(A/B 完整) | **RSC `d5ra08493h` = FAIL(size=0、no-pdf-captured、188s)** | **RSC `d5ra08493h` = PASS(CF 15.5s 过、484,829B、%PDF-1.6、24s、QC match)** |
| 环境 | Chrome 133 + nodriver 0.50.3(有头) | 同上 |

> **补充(-152 A/B 发现的新 bug,待入档)**:`render_fetch` 的 CDP 兼容 patch(`_patch_nodriver_cdp_compat`)**只处理字段缺失,遇到未知枚举值仍抛 `ValueError`**——实测 `PreflightWarn`(不属于 nodriver 0.50.3 的 `LocalNetworkAccessRequestPolicy` 枚举)触发,刷上千行洪水。修法:patch 里对未知枚举值也容错(退回 `ALLOW` 或跳过),而非只补缺字段。

> -154 删 Fetch 的**理由**(当前 `render_fetch.py:540-545` 注释):该 nodriver/CDP 组合下,导航后 `fetch.get_response_body`/`continue_request` 抛 `ProtocolException 'Fetch domain is not enabled [-32000]'`(命令与 enable 落到**不同 session**),paused 的 PDF 请求**永不放行** → 方法B 页内 fetch 挂到超时、方法A 读不到 body → **全站 no-pdf-captured**。故 -154 改用 Network 域兜底 + 方法B(页内 fetch)为主。

---

## 二、根因假说(**A 端已部分坐实,B 端最终收口**)

> 出处:-152 机制层分析。A/B 前半(Network 域 RSC FAIL)与本假说一致,但"是否 target 互换"的直接证据待 B 端;仍标"极可能",非终裁。

- **假说**:-154 报的 `'Fetch domain is not enabled / different session'`,**极可能因为它把 `Fetch.enable` 开在【过盾前】**(`about:blank` / 导航前);CF 质询期的跳转会**把 target 换掉**,`enable` 落在**旧 target**、而 `get_response_body` 落在**新 target** → 报错。
- **对照**:152 探针**过盾之后才开** Fetch,此时 target 已稳定、同 session,**未报错**、成功抓体。
- **推论(A/B 已印证现象)**:「Fetch 域本身没问题,问题在**开的时机**」——过盾后门控开 Fetch **已证 OK(B 端 PASS)**;而 **-154 的 Network 域法(`about:blank` 过盾前就 `network.enable`)已证撑不住(A 端 FAIL)**。二者与假说方向一致,但 session 层直接证据仍缺,故本节维持"假说"。

---

## 三、关键点验证进展(A 端已证)

1. **✅ 已证 FAIL**:**-154 的 Network 域方法A 对 RSC `articlepdf` 导航拿不到 body**——A/B 前半实测 `d5ra08493h` **size=0、no-pdf-captured、188.3s**。(RSC 文章页无明链,须导航到 `publisher_direct.build_static_candidates` 构造的 `pubs.rsc.org/en/content/articlepdf/{year}/{jcode}/{suffix}`;导航触 viewer/下载,Network 域 `get_response_body` 拿不到。)
2. **高度疑似坐实**:`network.enable` 在 `about:blank`(过盾前)开,**很可能同样撑不住 target 互换**——这正是 §二假说所指,且 A 端 FAIL 与之一致。B 端(过盾后门控 Fetch)结果将最终判定。
3. 方法B(页内 `fetch().arrayBuffer()`)对 RSC `articlepdf` **已知失败**(`ERR:TypeError: Failed to fetch`,CSP/跨源,-152);**已证 PASS** 于 ACS-OA 同源(`acsomega.6c04195` 13.78MB)。→ **RSC 必须靠方法A(网络层)**,故方法A 选型对 RSC 桶**决定性**。

---

## 四、结论(✅ A/B 已收口,写死)

- **判据**:**谁能真落 %PDF(且 QC match)用谁。**
- **✅ 最终定论(按 PDF 来源分流)**:
  - **同源 PDF(如 ACS-OA `acsomega.6c04195`)→ B1 页内 `fetch().arrayBuffer()`**(PASS 13.78MB)。
  - **跨源/viewer 导航 PDF(如 RSC `articlepdf`)→ 过盾后门控 `Fetch.enable` RESPONSE(同 tab、cf_clearance 之后才 enable)**(PASS 484,829B);**Network 域方法A 对此 = FAIL(size=0),不可用**。
- **对 -154 当前工作树的判定**:「整体移除 Fetch 改 Network 域」**对同源 OK,但对 RSC 这类跨源导航不够** → **需把过盾后门控 Fetch.enable RESPONSE 引回**(务必区别于 -154 之前「导航前早开」——早开卡 CF/`not enabled`,见 §五 N.8)。即最终形态 = **B1(同源)+ 过盾后门控 Fetch(跨源) 双支路**。
- **落地建议(交 -144/-154 改 `render_fetch.py`)**:① 保留 B1 页内 fetch;② 方法A 从纯 Network 域改为「过盾后(cf_clearance 确认)才 `fetch.enable` RESPONSE、同 tab」;③ 修 `_patch_nodriver_cdp_compat` 未知枚举容错(见 §一补充)。

---

## 五、与经验记录的衔接(单一事实源指针)

- 本分岔是 `经验记录-踩坑与发现.md` **N.8 #2** 的下游细化:N.8 已定论 **route-B 卡 CF 的真因 = 过盾期开了 CDP Fetch/Network 拦截**(非 env/指纹/Chrome 版本);`acsomega.6c04195` 修法后已落 13.7MB %PDF(B1 页内 fetch)。
- **本文补充的是 N.8 未覆盖的一层**:B1(页内 fetch)对**同源** PDF(ACS-OA)已通;但 **RSC 的 articlepdf 跨源/CSP,B1 失败,必须方法A(网络层)** —— 而方法A「用 Network 域 vs 过盾后门控 Fetch」这道选择题,**N.8 尚未定,正是本文 + A/B 要收口的点**。
- **两桶路径定论(A/B 已证)**:ACS-OA=**B1**(页内 fetch,13.78MB,PASS);RSC=**过盾后门控 Fetch.enable RESPONSE**(484KB,PASS);**Network 域对 RSC = FAIL**。→ 建议并入 N.8 之下新增 **N.9「route-B 方法A 定论:同源 B1 / 跨源过盾后门控 Fetch;Network 域取不到导航 articlepdf body」**。
- **A/B 原始记录**:见 `路线B-真机冒烟结果-152.md` **UPDATE-2**(-152 已写入两端真机数据),本文与之同源、可交叉引。

---

## 六、待办

- [x] **A/B 完整跑完**:A 端 Network 域 RSC=FAIL(size=0);B 端过盾后门控 Fetch RSC=PASS(484,829B/QC match);ACS-OA B1=PASS(13.78MB)。已写死 §〇/§四。
- [ ] **交 -144/-154 改 `render_fetch.py`**:方法A 从纯 Network 域 → 过盾后门控 Fetch.enable RESPONSE(同 tab);保留 B1;修 `_patch_nodriver_cdp_compat` 未知枚举(`PreflightWarn`)容错。
- [ ] **并入 `经验记录` N.9**(建议):route-B 方法A 定论。交经验记录写锁属主(-146?)或总指挥指派。

---

*核验 2026-07-02｜-140 起草 · -152 供 A/B 实证 · -148 工单｜纯文档只读,未改任何 .py。A/B 已收口:同源 B1 / 跨源过盾后门控 Fetch(RSC PASS 484KB),Network 域对 RSC FAIL。根因「target 互换」仍标假说(只证现象未探 session 层铁证)。*
