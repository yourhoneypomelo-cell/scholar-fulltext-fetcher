# AIP / T&F 绑 JA3 探针 —— 实测结论（P0·0 改动）

> 交付：**谷歌学术人机认证-157**（worker）→ 总指挥｜2026-07-03｜taskId=`task-b17f150d-797b-423a-a32e-8c315f83af6f`
> 边界：**真机联网探针 + 写 md/样本**，0 改任何核心 `.py`（仅 `import` 复用 `tools.flaresolverr_nodriver.Solver` / `fulltext_fetcher.landing` / `curl_cffi`）；未发射批量、未回写 coverage、未动 git。
> 复用/新增脚本：`_aip_tandf_ja3_probe_147.py`（主探针，-162 起草、本波实跑）、`_aip_ja3_probe2_157.py`（AIP 决断补充）、`_aip_oa_confirm_157.py`（AIP OA 正对照坐实）。

---

## 〇、TL;DR（一页结论，给总指挥）

- **结论：AIP(`pubs.aip.org`) 与 T&F(`www.tandfonline.com`) 都【不绑 JA3】。**两者的 `cf_clearance` 都可跨 JA3 移植——nodriver（浏览器 JA3）solve 出的 `cf_clearance`，用 `curl_cffi`（另一套 JA3）回放即可通过盾。
- **决策：不改 `render_fetch._JA3_BOUND_CF_HOSTS`（保持 4 家：rsc/sciencedirect/wiley/acs）。** AIP/T&F **不入名单、不走 route-B 浏览器内直下**；维持现状「shim solve → curl_cffi 回放」轻量路径即可。
- **坐实（正对照）**：AIP Advances（Gold OA）`10.1063/5.0274507` 用 `curl_cffi + cf_clearance` **完整下到 7,152,976 B 的真 %PDF**（`%PDF` 头 + `%%EOF` 尾，`application/pdf`，25.6s）。→ 证明 AIP 的 PDF 端点（含 `watermark*.silverchair.com` CDN）**对 curl 回放开放、不校验浏览器 JA3**。
- **那 AIP5 / T&F3 为什么还 miss？答案是【订阅墙】，不是 JA3。** 实测这 8 条里被测的 4 条都是**无 entitlement**：AIP 付费文的 PDF 直链 **302 回退到 `article-abstract?redirectedFrom=PDF`**（HTTP 200 的摘要页，不是 403 质询）；T&F 的 `/doi/pdf/` 直接返回 **200 订阅墙 HTML**。→ 这 8 条属 **A5 机构订阅（route-A）** 域，**不是 route-B 可救**。
- **净增口径（诚实）**：本探针对「绑 JA3 → route-B」的净增 = **+0**（因两家都不绑 JA3，route-B 名单无需扩，且这 8 条是订阅墙）。ROI 兑现方式：**关掉「AIP/T&F 入 route-B」这条伪线索**，把 8 条并入 A5 队列。

---

## 一、问题与判据

**问题（147 波 P0）**：AIP(10.1063) / T&F(10.1080) 当前**不在** `_JA3_BOUND_CF_HOSTS`，走「shim `solve()` 拿 `cf_clearance`+UA → `curl_cffi` 回放」。需实测这条回放到底成不成，以决定：

```394:398:fulltext_fetcher/render_fetch.py
_JA3_BOUND_CF_HOSTS = (
    "pubs.rsc.org", "rsc.org",
    "sciencedirect.com", "pdf.sciencedirectassets.com", "sciencedirectassets.com",
    "onlinelibrary.wiley.com", "pubs.acs.org",
)
```

**判据（JA3 绑定的签名）**：在**已持该 origin 有效 `cf_clearance`** 的前提下，用 `curl_cffi`（非浏览器 JA3）回放 **PDF 直链**——
- 回放 **200 %PDF** → `cf_clearance` **不绑 JA3** → curl 回放可下 → **不入名单**。
- 回放 **403 / CF 质询** → `cf_clearance` **绑浏览器 JA3**（同 cookie 换 JA3 即失效）→ **须入名单走 route-B**（浏览器内同会话同 JA3 抓字节）。
- 回放 **200 但订阅墙 / 无 PDF 链 / 302 回摘要** → **非 JA3 问题**（订阅墙）→ 走 **A5**，不入名单。

---

## 二、方法

1. **主探针 `_aip_tandf_ja3_probe_147.py`**（有头 nodriver）：每家 2 条 still_missing 语料 DOI，跑 Phase A 裸 curl 基线 → Phase B/C `shim solve → curl_cffi 回放 PDF 直链` → Phase D（回放拿不到 %PDF 的 host）`render_download_pdf_bytes` route-B 浏览器内直下交叉验证。
2. **AIP 决断补充 `_aip_ja3_probe2_157.py`**：主探针 AIP 臂因**抽不到 silverchair PDF 直链**而 INCONCLUSIVE，本补充改为「solve 拿 clearance → curl 带 clearance 取**文章页真 HTML** → 抽 `citation_pdf_url` 真直链 → 回放」，并**现拉 1 条 AIP Advances(Gold OA, ISSN 2158-3226) 真实 DOI 作正对照**（Crossref API，不杜撰），把「绑 JA3」与「订阅墙」彻底分开。
3. **OA 正对照坐实 `_aip_oa_confirm_157.py`**：对上一步的 OA DOI，`curl_cffi + cf_clearance` **流式 180s 下载**其 PDF 直链，校验 `%PDF`/`%%EOF`/体积。

---

## 三、逐条实测结果

### 3.1 AIP（`pubs.aip.org`）

| DOI | 期刊/类型 | 文章页(带 clearance) | PDF 直链回放(带 clearance) | 判读 |
|---|---|---|---|---|
| `10.1063/5.0228286` | Appl. Phys. Rev.（付费/hybrid） | **200** ✓ | **302 → `article-abstract?redirectedFrom=PDF`**（200 HTML，非 %PDF、非 403） | **订阅墙**（无 entitlement，非 JA3） |
| `10.1063/1.1647050` | J. Chem. Phys. 2004（付费） | **200** ✓ | **302 → `article-abstract?redirectedFrom=PDF`**（200 HTML） | **订阅墙**（非 JA3） |
| `10.1063/5.0274507` | **AIP Advances（Gold OA）** ★正对照 | **200** ✓ | **200 `application/pdf`，7,152,976 B，`%PDF`+`%%EOF`** ✓ | **NOT-JA3-BOUND（curl 回放下到真 %PDF）** |

- 三条都拿到 `cf_clearance=YES`（4 cookies，solve ~7–9s），文章页 curl 回放全 **200**。
- 关键：付费文 PDF 直链**不是 403 质询**，而是 **entitlement 回退到摘要页**；OA 文 PDF 直链**被 curl 回放完整下回**（经 `watermark02.silverchair.com` token CDN，无质询、无 JA3 校验）。
- → **AIP 的 CF（文章页与 PDF 端点）均不绑 JA3**；miss 的付费文是**订阅墙**。

### 3.2 T&F（`www.tandfonline.com`）

| DOI | 裸 curl `/doi/pdf/` | solve | 回放 `/doi/pdf/`(带 clearance) | route-B 交叉验证 | 判读 |
|---|---|---|---|---|---|
| `10.1080/09593330.2019.1625954` | **200**（订阅墙 HTML，210KB，非 403） | cf_clearance=YES(26ck) | **200 订阅墙 HTML**（非 %PDF、非 403） | `no-pdf-captured` | **订阅墙**（非 JA3） |
| `10.1080/0892702031000117135` | **200**（订阅墙 HTML，205KB） | cf_clearance=YES(cache) | **200 订阅墙 HTML** | — | **订阅墙**（非 JA3） |

- T&F 的 `/doi/pdf/` 端点**裸 curl 就已 200**（连 CF 403 都不出），拿到 clearance 后回放仍是 **200 订阅墙 HTML**。→ 阻断因子是**订阅**，与 JA3 无关。

---

## 四、坐实证据（OA 正对照原始输出）

```
[oa-confirm] solve cf_clearance=True cookies=4
[oa-confirm] status=200 final=https://watermark02.silverchair.com/085311_1_5.0274507.pdf?token=AQEC...(截断)
[oa-confirm] bytes=7152976 is_pdf=True has_eof=True elapsed=25.6s ct=application/pdf
OA_CONFIRM: PASS %PDF
```

**含义**：nodriver（浏览器 JA3）solve 出的 `cf_clearance`，交给 **`curl_cffi`（不同 JA3）** 回放 AIP 的 PDF 直链，成功拿到**完整 7MB 真 %PDF**。若 `cf_clearance` 绑 JA3，换 JA3 的 curl 必被 403——事实相反 → **不绑 JA3，实锤**。

---

## 五、判读与决策

| 出版商 | 是否绑 JA3 | 依据 | 决策 |
|---|:--:|---|---|
| **AIP** `pubs.aip.org` | **否** | OA 文 curl 回放下到 7MB %PDF；付费文 PDF 直链是 302 回摘要（entitlement），非 403 | **不入 `_JA3_BOUND_CF_HOSTS`**；维持 shim solve→curl 回放 |
| **T&F** `www.tandfonline.com` | **否** | `/doi/pdf/` 裸 curl 即 200、回放 200 订阅墙 HTML，全程无 403 质询 | **不入 `_JA3_BOUND_CF_HOSTS`**；维持轻量回放 |

**→ `_JA3_BOUND_CF_HOSTS` 保持不变（rsc/sciencedirect/wiley/acs 四家）。本探针不产生任何核心码改动。**

**对 still_missing 的 AIP5 / T&F3（共 8 条）**：被测 4 条均为**订阅墙**，应并入 **A5 机构订阅（route-A）** 队列，**不占 route-B 有头浏览器算力**。
> 建议（业务侧，非本任务范围）：AIP 5 里若混有 **AIP Advances / APL 系 Gold OA** 长尾，现有「shim solve→curl 回放」**本就能取回**（见正对照），值得对这 5 条各查一次 OA 状态再定路由；纯付费的归 A5。

---

## 六、与已知桶对照（把 AIP/T&F 归位）

| 桶 | Host | 绑 JA3? | 现路线 | 本探针后定性 |
|---|---|:--:|---|---|
| ACS | `pubs.acs.org` | 否 | shim solve→curl 回放（-145 实测可下） | 参照系（AIP/T&F 与 ACS 同类：managed challenge、clearance 可移植） |
| Wiley | `onlinelibrary.wiley.com` | **是** | 已在名单→route-B | 反例（真绑 JA3） |
| RSC/ScienceDirect | `pubs.rsc.org` / `sciencedirect` | **是** | 已在名单→route-B | 反例 |
| **AIP** | `pubs.aip.org` | **否**（本波实锤） | shim solve→curl 回放 | **同 ACS，不入名单** |
| **T&F** | `www.tandfonline.com` | **否**（本波实锤） | shim solve→curl 回放 | **同 ACS，不入名单** |

结论：AIP/T&F 与 **ACS 同类**（CF managed challenge、`cf_clearance` 不绑 JA3），**不同于** Wiley/RSC/ScienceDirect（真绑 JA3 需 route-B）。147 波两文《过认证墙开源方案检索-CF绕过-147.md / 总评估-147.md》中标注的「AIP/T&F 待验证」——**至此判定完毕：均不绑 JA3**。

---

## 七、净增与 ROI（诚实标注）

- **JA3 绑定 → route-B 名单扩充带来的净增 = +0**（两家都不绑 JA3，名单无需改）。
- **本探针的真实 ROI = 关掉一条伪线索**：确认「把 AIP/T&F 塞进 route-B」是**无效功**，避免为其投 route-B 有头浏览器算力；把 AIP5+T&F3=8 条**正确改道 A5**。
- 净覆盖率基线不受影响（本探针 0 回写；参照 173 冻结基线 340/659 或 coverage.json 权威值，以口径文件为准）。

---

## 八、附录

**复现命令**
```
python -X utf8 _aip_tandf_ja3_probe_147.py            # 主探针(有头)
python -X utf8 _aip_ja3_probe2_157.py                 # AIP 决断补充(含 OA 正对照)
python -X utf8 _aip_oa_confirm_157.py                 # AIP OA 下载坐实
```

**产物 / 样本**
- `out/_aip_tandf_ja3_probe_147.json`（5,633 B）主探针 4 条明细
- `out/_aip_ja3_probe2_157.json`（6,921 B）AIP 3 条（含 OA 对照）明细
- `out/_aip_oa_confirm_157.pdf`（7,152,976 B）AIP OA 真 %PDF 坐实件
- `out/_probe_samples_157/*.html`（5 个）文章页/回放 HTML 样本

**测试 DOI 清单**
- AIP：`10.1063/5.0228286`（APR，付费）、`10.1063/1.1647050`（JCP2004，付费）、`10.1063/5.0274507`（AIP Advances，**Gold OA 正对照**）
- T&F：`10.1080/09593330.2019.1625954`、`10.1080/0892702031000117135`（均订阅墙）

**环境**：Windows 10；Python 3.11.2；curl_cffi 0.15.0；nodriver 0.50.3；有头 Chrome。
