# 经验待归档 · route-B 浏览器内直下 PDF 抓字节：Network 域 vs 过盾后 Fetch.enable 分叉（-142）

> 状态：**已并入《经验记录-踩坑与发现.md》正文 · 事实源指针（-143 归档）**。过 CF 铁律 + B1/B2 两法 → **N.8 #2**；方法A「Network 域 vs 过盾后门控 Fetch」A/B 定论 → **P 节（P.1–P.5）+ N.8 #2**；PreflightWarn 枚举 ValueError 洪水 bug → **W.3**。本文保留作原始探针证据（`_route_b_b2_152.py`），不再作为待办草稿。
> 用途：沉淀 route-B 抓字节的铁律 + 两法适用 + 一处**未解分叉**；待 -144 的 A/B 冒烟定案后，由委派人/总指挥持写锁合入经验记录。
> 事实来源：-152 探针实证（`_route_b_b2_152.py`）+ -144 工作树核实（`fulltext_fetcher/render_fetch.py`），由总指挥拍板。
> 边界声明：本次仅**只读**核实了 `render_fetch.py` 当前实现，未改任何 `.py`，未碰其他成员在飞文件。

---

## 一、过 CF 铁律（已实证）

- **过盾期绝不开 CDP Fetch/Network 拦截**：质询阶段一旦启用拦截，CF 跳转会把 target/session 换掉，后续抓字节命令落到错误 session。
- **判过盾用「可见文案 + cf_clearance」双信号**：
  - 权威信号：`cf_clearance` cookie 出现（`_has_cf` / `_has_cf_clearance`）。
  - 双保险：`title + body.innerText` 同查 `_BLOCK_SIGNALS`（"just a moment" 等常放在 `<title>`，只看 body 会漏判）。
  - 勿用 `cf-chl` / `challenge-platform` 脚本标记判过盾——会假阳（-152 结论）。
- **过盾后才抓字节**。
- **免升级组合**：Chrome 133 + nodriver 0.50.3（配 `render_fetch._patch_nodriver_cdp_compat` 容忍 `ClientSecurityState` 的 CDP 字段漂移即可，不必升级）。

## 二、拓字节两法与适用

| 方法 | 机制 | 适用 / 实证 |
| --- | --- | --- |
| **B1：页内同源 fetch** | 在【已过 CF 的文章页上下文】里 `fetch(url, {credentials:'include'})` → `blob` → `FileReader` 转 data-URL(base64) 回传（`_inpage_fetch_pdf_js`）。天然继承该页 cookie + JA3，同源最稳。 | ACS-OA 已证：`acsomega.6c04195` 落 **13.7MB %PDF**、QC match。跨源被 CSP/CORS 拦时 `fetch` 抛 TypeError（**RSC 即如此**）。 |
| **B2：导航 PDF 直链后网络层抓** | 导航到 PDF 直链，在网络层（CDP）截获响应体，绕过 CORS。 | RSC 因 CSP/跨源 B1 失败，**必走 B2**。 |

B1 首选、B2 兜底：`_nodriver_capture_fn._capture` 内即先页内 fetch（方法 B），不成再导航直链由网络层抓（方法 A）。

## 三、未解分叉（本日新增）：B2 在网络层抓字节，用哪个 CDP 域？

同为「过盾后抓 RSC 的字节」，两处实现走了**不同 CDP 域**，且结论未对齐：

### 证据 a —— -152 探针：过盾后开 **Fetch.enable RESPONSE 拦截** → 成功
`_route_b_b2_152.py`（阶段化）：
1. 阶段 1 只导航文章页、轮询等 `cf_clearance`，**不开任何拦截**；
2. 过盾后（阶段 2）才 `cdp.fetch.enable(patterns=[RequestPattern(url_pattern=p, request_stage=RESPONSE)])` + `add_handler(cdp.fetch.RequestPaused, on_paused)`；
3. `on_paused` 里 `cdp.fetch.get_response_body` 取字节、`cdp.fetch.continue_request` 放行；
4. 导航到 `build_static_candidates(DOI)` 构造的 articlepdf 直链。

→ **实证抓到 RSC 484KB `%PDF`**（`ROUTE_B_B2_PDF_OK`，落 `out/runbook_b/…pdf`）。

### 证据 b —— 当前工作树 `render_fetch.py`（-154 改）：改用 **Network 域**，对 RSC 未证
`_nodriver_capture_fn._capture` 现状（只读核实）：
- `cdp.network.enable(max_total_buffer_size=…, max_resource_buffer_size=…)`；
- `add_handler(cdp.network.ResponseReceived, on_resp)`：`_looks_pdf_response` 命中即记 `request_id`；
- `add_handler(cdp.network.LoadingFinished, on_finished)`：`cdp.network.get_response_body(request_id)` 取字节，`%PDF` 兜底校验；
- **明确删除了 `cdp.fetch.enable`**（见其内注 L538–543）。
- 对 RSC 能否稳定落 `%PDF`：**未证**。

### 真因假说（关键）
-154 之所以在注释里判「Fetch 域不可用」（报 `Fetch domain is not enabled [-32000]`、被 paused 的 PDF 请求永不放行 → 方法 B 页内 fetch 挂超时、方法 A 读不到 body → 全站 `no-pdf-captured`），**很可能不是 Fetch 域本身不可用，而是把 `Fetch.enable` 开在了过盾前**（`about:blank`/质询期）：CF 跳转把 target/session 换掉后，`enable` 与后续 `get_response_body`/`continue_request` 落到**不同 session**。

- **-152 证据支持此假说**：同一 nodriver/CDP 组合，只要把 `fetch.enable` **挪到过盾之后**，`fetch.get_response_body` 就能正常抓到 `%PDF`。
- 即：分叉的本质是 **`Fetch.enable` 的调用时机（相对过盾）**，而非 Network 域 vs Fetch 域谁「能用」。

## 四、A/B 冒烟结论（-148 有头真机取证，2026-07-02 回填）

环境：Windows 10.0.26100 · Python 3.11.2 · **Chrome 133.0.6943.98 · nodriver 0.50.3 · curl_cffi 0.15.0**（与 -152 一致），有头可见桌面、串行 concurrency=1 锁。

| 样本 | 路径 | CF 过盾 | 结果 | 内容 QC |
| --- | --- | --- | --- | --- |
| ACS-OA `10.1021/acsomega.6c04195` | 生产 `render_download_pdf_bytes` → **B1 页内 fetch** | ✅ 9.9s | **%PDF 13,832,724B / 17 页** | doi_in_text=True，标题 8/8 ✅ match |
| RSC `10.1039/d5ra08493h` | **A = 生产 Network 域**（`network.get_response_body`） | ✅ 过盾（cf_clearance 到手） | ❌ **`no-pdf-captured`**（104.7s，未抓到 body） | — |
| RSC `10.1039/d5ra08493h` | **B = 过盾后 `Fetch.enable` RESPONSE 拦截**（`_route_b_b2_152.py`） | ✅ 16.3s | ✅ **%PDF-1.6 484,829B / 8 页** | doi_in_text=True，thermochemical/photochemical/benzylic/oxidation/aerobic 全中 ✅ match |

**结论（分叉定案）**：
- 对 **RSC**，当前生产实现的 **A（Network 域方法A）抓不到 body → `no-pdf-captured`**；而 **B（过盾后 Fetch.enable RESPONSE 拦截）能稳定落 %PDF 且过内容 QC**。→ **证据 a 胜**，证据 b（-154 改用 Network 域、删 Fetch.enable）对 RSC **不成立**。
- **真因假说得证**：-154 判「Fetch domain is not enabled」确实是**把 Fetch.enable 开在了过盾前**（CF 跳转换 session）；`_route_b_b2_152.py` 把 `fetch.enable` 挪到**过盾之后**即正常抓字节。分叉本质 = **Fetch.enable 的调用时机（相对过盾）**，非 Network vs Fetch 谁「可用」。
- **验收硬标准**（ACS-OA + RSC 两样本都 %PDF 且过内容 QC）：ACS-OA 已达（B1）；RSC **仅经 B 路径达标**，当前生产 A 路径未达 → 生产 `render_fetch.py` 需补【RSC 过盾后 Fetch.enable 直链兜底】（属主 -144）。

**附带实锤 bug（Chrome 133 新增枚举值，-148 冒烟新发现）**：
- RSC 生产跑中，后台监听器抛 **`ValueError: 'PreflightWarn' is not a valid LocalNetworkAccessRequestPolicy`** 洪水（单次约 270 次），源自 `render_fetch._patch_nodriver_cdp_compat._tolerant_from_json`：它只兜了「字段缺失(KeyError)」，未兜「**字段存在但枚举值 nodriver 0.50.3 不认**」——Chrome 133 新发 `PreflightWarn` 值，`LocalNetworkAccessRequestPolicy.from_json(raw)` 直接抛 ValueError → `parse_json_event` 崩 → **网络事件被丢弃**，这正是 A（Network 域）在 RSC 抓不到 `LoadingFinished`/body 的直接机制之一。
- `_route_b_b2_152.py` 的 `_tol` 更稳（`try: _LNAP(raw) except: ALLOW`），故不崩、能抓到字节。
- **修法**：把 `_tolerant_from_json` 的枚举转换包 `try/except`，未知值降级 `ALLOW`（与 `_tol` 对齐）。

**待办（真依赖，已当场协调）**：
1. -144（`render_fetch.py`/`download.py` 属主）补：① RSC（及 JA3 桶）**过盾后 Fetch.enable RESPONSE 拦截**兜底（B1 失败→B2 用 Fetch 域而非 Network 域）；② `_tolerant_from_json` 枚举值容错。
2. 落地后由 -148 复跑 RSC 生产路径复验（目标：生产 `render_download_pdf_bytes` 对 RSC 直接落 %PDF）。
3. 本节可由协调者**持写锁**合入《经验记录-踩坑与发现.md》。

---

### 合入说明
本文件为**可直接合入的成段落草稿**，不直接写入多人共写的《经验记录-踩坑与发现.md》正文（该文件需写锁、且 A/B 未定）。A/B 结果回填第四节后，由协调者持写锁合并。
