# route-B 回收波 Phase1 · A集小批串行冲烟结果（会话-146）

> 工单 `task-a7db8d01`（总指挥-142）：定 2 处设计缺口 + concurrency=1 护栏 + A 集小批串行冲烟（报 pdf_ok/QC）。
> 结论：**②b JA3 直下的 B1 路径端到端跑通（ACS-OA 13.8MB、QC match）；RSC 三条均过盾但 B2/方法A 未抓到字节（`no-pdf-captured`）** —— 定位到 **render_fetch 的方法A用 Network 域抓 body 对 RSC 无效**，需按 -152 实证恢复「过盾后才开 `Fetch.enable(RESPONSE)`」的 B2。B1 与两处拍板（cf_clearance / RSC 直链兜底）已验证有效。

## 环境
- Windows 10.0.26100 ｜ Python 3.11.2 ｜ **Chrome + nodriver 0.50.3** ｜ curl_cffi 0.15.0 ｜ pypdf 3.17.4
- 冲烟脚本 `_smoke_routeb_146.py`：**直调** `render_download_pdf_bytes`（有头 headless=False、单进程串行、`min_interval=0`、`lock_path=out/.route_b.lock`、`pdf_url_fallbacks=publisher_direct.build_static_candidates(doi)`）。

## 离线自检（全绿）
`render_fetch --selftest` → RENDER_BYTES_OK/RENDER_OK；`download` → DOWNLOAD_OK；`publisher_direct` → PUBLISHER_DIRECT_OK；`pipeline` → PIPELINE_OK。

## 冲烟明细（A 集：RSC×3 + ACS-OA×1，均属 JA3 绑定 CF 桶 = ②b 路径）

| # | DOI | 刊/状态 | 耗时 | note | %PDF | 页 | 路径 | 过盾 | QC |
|---|-----|--------|------|------|------|----|----|-----|----|
| 1 | `10.1039/d5ra08493h` | RSC Adv 金OA | 93.7s | `no-pdf: no-pdf-captured` | 0 | — | — | ✅(未被 blocked) | — |
| 2 | `10.1039/c1gc15503b` | RSC Green Chem 混合 | 102.0s | `no-pdf: no-pdf-captured` | 0 | — | — | ✅ | — |
| 3 | `10.1039/d5cy00880h` | RSC Catal S&T 订阅 | 186.9s | `no-pdf: no-pdf-captured` | 0 | — | — | ✅ | — |
| 4 | `10.1021/acsomega.6c04195` | ACS Omega 金OA | **8.0s** | **`ok:b1`** | **13,832,721** | **17** | **B1** | ✅ | **match**（DOI-in-text=True；标题词 8/8）|

`SUMMARY total=4 pdf_ok=1 blocked=0 no_pdf=3`；落盘 `out/smoke_routeb_146/10.1021_acsomega.6c04195.pdf`（%PDF 校验通过）。

## 两处拍板落地核验
- **拍板1（cf_clearance 过盾信号）✅**：4/4 均越过 CF 质询进入「找 PDF」阶段（`no-pdf-captured` 而非 `blocked:challenge-page`），与 -152 `has_cf_clearance=True` 一致。`_has_cf_clearance()` 已用 `get_all_cookies`→`get_cookies` 双读法（与 -152 探针对齐）+ `_BLOCK_SIGNALS`（title+body、含新版文案）双保险。
- **拍板2（RSC articlepdf 直链兜底）✅（构造正确、已被使用）**：`build_static_candidates('10.1039/d5ra08493h')` → `https://pubs.rsc.org/en/content/articlepdf/2025/ra/d5ra08493h`；页内抽链为空时 render_fetch 正确回落到该直链作方法A导航目标。**但** 后续抓字节失败（见下）。
- **concurrency=1 护栏 ✅**：`render_fetch` 进程内 `BoundedSemaphore(1)` + `out/.route_b.lock` 跨进程文件锁（O_CREAT|O_EXCL + 陈旧锁 mtime 接管），selftest case12 与实跑均验证锁文件创建/释放/删除；`download._browser_capture_fallback` 已接线 `lock_path=<out_dir>/.route_b.lock`。

## 关键缺口（阻塞 Phase2 全量 RSC）：方法A(B2) 用 Network 域抓 body 对 RSC 失效
- 现 `render_fetch._nodriver_capture_fn` 的**方法A**：`Network.enable` + `ResponseReceived`/`LoadingFinished` → `network.get_response_body`（-154 为规避 “Fetch domain is not enabled” 而从 Fetch 域改来）。
- 本冲烟 RSC 3/3：过盾 ✅ → 页内 fetch(方法B) 因 CSP/跨源 `TypeError: Failed to fetch`（-152 已记）→ 导航 articlepdf 后 **Network 域 `get_response_body` 抓不到**（PDF 顶帧导航转下载/viewer，body 不在网络缓冲，`No resource with given identifier`）→ `no-pdf-captured`。
- **-152 `_route_b_b2_152.py` 实证可行**：**过盾之后**才 `cdp.fetch.enable(patterns=RESPONSE)` + `on_paused`→`fetch.get_response_body` + 导航到构造的 articlepdf → 抓到 **%PDF 484,829B、8 页、QC match**（`10.1039/d5ra08493h`）。
- **修法（建议给 render_fetch owner -144）**：把方法A从 Network 域换回 **Fetch 域 RESPONSE 拦截，但严格“惰性、过盾后才 enable”**（-154 的 session 报错极可能因在 about:blank / 导航前就 enable → 换 target 后失效）。即在 while 循环判定过盾且方法B失败后，才 `tab.send(cdp.fetch.enable(...))` 再 `_nav(pdf_url)`；捕获后 `fetch.disable`。B1(ACS) 路径不受影响。

## MDPI ⑥ 路径（Akamai）追加冲烟 —— 2/2 通过
MDPI 属 **Akamai Bot Manager**（bm-verify），生产走 **⑥ `_browser_pdf_download`(`_nodriver_fetch_pdf_bytes`)** + `cfg.browser_pdf_download` 开关，**不经 ②b `render_download_pdf_bytes`/`browser_capture`**（`is_ja3_bound_cf_host('mdpi.com')=False`）。故用独立脚本 `_smoke_mdpi_146.py` 直调 ⑥，与 -144 的 render_fetch 零撞车。

| DOI | 耗时 | %PDF | 页 | QC |
|---|---|---|---|---|
| `10.3390/catal16030270` | 18.7s | **4,118,864B** | 15 | **match**（DOI✓；标题词 8/8）|
| `10.3390/app14114959` | 18.6s | **8,676,122B** | 19 | **match**（DOI✓；标题词 7/7）|

`MDPI SMOKE total=2 pdf_ok=2`；落盘 `out/smoke_mdpi_146/`。**⑥ Akamai 有头下载路径端到端通、QC match**（过 Akamai 软验证 + CDP `setDownloadBehavior` 下载真 PDF）。
> 注：脚本收尾打印 `MDPI_SMOKE_DONE` 后有一条 `RuntimeError: Event loop is closed`（asyncio `BaseSubprocessTransport.__del__` 在解释器退出时的无害清理告警），非功能失败，不影响已落盘 PDF 与 QC。

## 边界与说明
- **三条 route-B 子路径本波均已实测**：②b-B1（ACS-OA）✅、②b-B2（RSC）⚠待 -144 修、⑥（MDPI/Akamai）✅。
- checkpoint 提交按边界待冲烟证明代码 good：**B1/MDPI 已 good、RSC-B2 待 -144 修**；建议 B2 修完复跑 `_smoke_routeb_146.py` RSC 3 条转 `ok:b2` 后再由总指挥统一提交 + 派 Phase2 全量。

*核验 2026-07-02 ｜ 会话-146 ｜ route-B Phase1 冲烟：B1(ACS 13.8MB)+MDPI(⑥ 2/2)端到端通、QC match；cf_clearance/RSC直链兜底/concurrency=1 三项落地；RSC B2 需恢复过盾后 Fetch.enable(RESPONSE)（-152 已实证，归 -144 owner）。*
