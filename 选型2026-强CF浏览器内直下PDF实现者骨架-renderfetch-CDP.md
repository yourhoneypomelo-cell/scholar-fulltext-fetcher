# 选型2026 · 强CF「浏览器内直接下 PDF」实现者骨架（render_fetch.py + CDP 抓字节）

> 交付：**信息检索-智库专家岗**（承 -177，本会话）｜2026-07-02
> 触发：用户点名「读 paper-scraper / sciencedirect-live-session-fetcher 源码 → render_fetch.py『CDP 浏览器内抓字节』骨架，破 JA3 强CF」。
> 边界：**只新建本 1 份骨架文档**；**不改任何 .py**（代码活交实现者）；已**实读**两个 OSS 的源码/README（见 §二、§七）。承 `选型2026-采纳与淘汰总表` ⑤ 的 P2「浏览器内直下 PDF」+ -145 的 JA3 实测发现。

---

## 〇、TL;DR

- **要解的死结**：RSC/ScienceDirect 把 `cf_clearance` **绑 JA3/TLS 指纹** → 浏览器解出 CF 拿到 cookie 后，`download.py` 交 `curl_cffi`/`requests` **回放**下载仍 403（换更强求解器 byparr 也无效）。
- **破法（唯一免费出路）**：**solve 与 download 用同一浏览器会话**——不把 PDF URL 交给外部 HTTP 客户端，而是**在浏览器内经 CDP 直接抓 PDF 响应字节**。这样 TLS/JA3 出口天然一致，CF 无从判别。
- **落点**：本仓 `render_fetch.py` 现有 `render_get_pdf_url()`（渲染取 URL，仍会踩 JA3 回放坑）。**新增一个并列扩展点 `render_download_pdf_bytes()`**（渲染并**在浏览器内抓字节**），复用现有 nodriver 引擎、合规守卫、强限流、信封与 selftest 规格。
- **已从源码提炼出可照抄的 CDP 配方**（paper-scraper `_dt_capture_pdf`，见 §二）——实现者可直接照做。

---

## 一、破局原理（为什么「浏览器内抓字节」能过、URL 回放不能）

| 环节 | 现有 `render_get_pdf_url` / download.py 回放 | 新 `render_download_pdf_bytes`（浏览器内抓字节） |
|---|---|---|
| 解 CF | 浏览器（nodriver）解质询、拿 `cf_clearance` | 同上 |
| **取 PDF** | 把 pdf_url 交 `curl_cffi` **另发一个 HTTP 请求** | **在同一浏览器会话内**由 CDP 截获该 PDF 响应体 |
| JA3 出口 | curl_cffi 的 JA3 ≠ 真 Chrome → **RSC 403** | 就是真 Chrome 的 JA3 → **一致、放行** |
| 短时签名 URL | 冷取 `pdf.sciencedirectassets.com/...md5=` 常 403 | 在授权页上下文内由浏览器自身发起、天然带全套 cookie/referer |

**一句话**：强 CF 的瓶颈在**「回放下载」这一步换了出口指纹**；把下载留在浏览器里，指纹就不会变。

---

## 二、读源码提炼：可照抄的 CDP 抓字节配方

### 2.1 `GAO-pooh/paper-scraper` · `_dt_capture_pdf()`（核心，MIT，纯 `websocket-client`，无 Playwright）

实读其 `sd_scraper_en.py`（1641 行）核心函数 `_dt_capture_pdf(ws_url, url, timeout)` 的 CDP 流程（**这就是要照抄的骨**）：

1. `websocket.create_connection(ws_url)` 连到 Chrome 某 tab 的 `webSocketDebuggerUrl`。
2. `Page.enable`；`Page.addScriptToEvaluateOnNewDocument`（注入 stealth JS，可选）。
3. **`Fetch.enable`** 带 URL 模式、`requestStage: "Response"`（拦响应阶段）：
   ```json
   {"patterns": [
     {"urlPattern": "*pdf.sciencedirectassets.com/*", "requestStage": "Response"},
     {"urlPattern": "*pdfft*", "requestStage": "Response"}
   ]}
   ```
4. **`Network.enable`**（`maxTotalBufferSize`/`maxResourceBufferSize` 调大到 ~100–120MB，防大 PDF 被丢）；`Network.setCacheDisabled=true`。
5. **`Page.navigate` 到「文章页」**（不是 PDF md5 短链）。
6. **事件循环**（到 deadline 止）三条抓取路径并行：
   - `Fetch.requestPaused` → 命中 PDF 响应 → **`Fetch.getResponseBody`**；否则 `Fetch.continueRequest`。
   - `Network.responseReceived` → 是 PDF 响应（content-type / url）→ 记 `requestId`。
   - `Network.loadingFinished` → 该 `requestId` 是 PDF → **`Network.getResponseBody`**。
   - `Page.loadEventFired` → `Runtime.evaluate` 读 `document.body.innerText` 前 2000 字 → 命中 `BLOCK_PAGE_SIGNALS`（"just a moment"/"verify you are human"…）→ 返回 `blocked:...`。
7. **取到 body** → `base64` 解码（`result.base64Encoded` 为真时）→ **校验 `data[:4] == b"%PDF"`** → 返回 `(bytes, pdf_url)`。

> 关键点：**用 `Fetch`+`Network` 双通道**（有些站 PDF 走 fetch 拦截、有些走 network 完成事件），**首字节 `%PDF` 兜底校验**（与本仓 `download.py` 的 `%PDF` 校验同哲学）。

### 2.2 `Given-Dream/sciencedirect-live-session-fetcher`（复用「活会话」，Python 3.10+，DevTools 远程调试口）

补充两条**运营级避坑**（实读其 README/脚本清单）：
- **附着到已授权的活浏览器**：`--remote-debugging-port 9222` 起一个独立 user-data-dir 的 Edge/Chrome，人工登录 + 过一次人机页 + 开一篇文章点「View PDF」，保持窗口开；脚本再 attach 抓取。→ **对需机构登录的 ScienceDirect/IEEE 尤为关键**。
- **别冷取短链 / 别复用 viewer URL**：`pdf.sciencedirectassets.com/...md5=` 短时且绑会话，**脱离活页上下文冷取必 403**；若 Chrome 用 `extension://.../pdfjs/...viewer.html?file=` 打开，说明被 PDF 插件劫持——应**禁扩展重开**，别复用该 viewer URL。IEEE 的 `stamp.jsp`/`stampPDF` 要**先归一化回文章详情页**再找授权 PDF 路由。

### 2.3 `go-rod/rod#953`（备用配方：让浏览器「下载」而非「查看」）

若某站 PDF 在浏览器里被 viewer 直接打开、拦不到响应体，另一条路：
- 设 `plugins.always_open_pdf_externally=true`（阻止内置 PDF viewer 吞流）→ headed 模式点过 CF 复选框 → 用 `Page.setDownloadBehavior` + 下载完成事件（`Browser.downloadWillBegin`/`downloadProgress`）落盘字节。

---

## 三、映射到本仓：`render_fetch.py` 新增扩展点（骨架）

> 复用现有：`_is_scholar_host` 合规守卫、`_throttle` 强限流、延迟导入 nodriver、统一信封 dict、离线 selftest 规格。**新增**一个「渲染并在浏览器内抓字节」的函数族。**首选 nodriver 引擎**（本仓已用、已装、零新依赖）；`websocket-client` 直连 CDP 作为等价备选（paper-scraper 已证）。

```python
# 新签名:抓字节而非取 URL。返回 (pdf_bytes | None, note)
RenderBytesFn = Callable[[str, float], Tuple[Optional[bytes], str]]

# JA3 绑定型强 CF 站(需浏览器内直下;普通 OA 站不必走这条重路径)
_JA3_BOUND_CF_HOSTS = ("pubs.rsc.org", "sciencedirect.com", "pdf.sciencedirectassets.com")

def _nodriver_capture_pdf_fn() -> Optional[RenderBytesFn]:
    """返回 nodriver 版『浏览器内抓 PDF 字节』函数;未装 nodriver 则 None。"""
    try:
        import nodriver  # noqa: F401
    except ImportError:
        return None
    import asyncio

    def _capture(url: str, timeout: float) -> Tuple[Optional[bytes], str]:
        import nodriver as nd
        from nodriver import cdp  # nodriver 自带 CDP 绑定(snake_case)

        async def _go() -> Tuple[Optional[bytes], str]:
            # headed 通常 CF 通过率更高;真机活。可按需 headless。
            browser = await nd.start(headless=False)
            try:
                tab = await browser.get("about:blank")
                # ① 开 Network / Fetch 域(大 buffer 防大 PDF 被丢)
                await tab.send(cdp.network.enable(
                    max_total_buffer_size=120 * 1024 * 1024,
                    max_resource_buffer_size=100 * 1024 * 1024))
                await tab.send(cdp.network.set_cache_disabled(cache_disabled=True))
                await tab.send(cdp.fetch.enable(patterns=[
                    cdp.fetch.RequestPattern(url_pattern="*pdfft*", request_stage=cdp.fetch.RequestStage.RESPONSE),
                    cdp.fetch.RequestPattern(url_pattern="*sciencedirectassets.com/*", request_stage=cdp.fetch.RequestStage.RESPONSE),
                    cdp.fetch.RequestPattern(url_pattern="*.pdf*", request_stage=cdp.fetch.RequestStage.RESPONSE),
                ]))

                captured: Dict[str, Optional[bytes]] = {"data": None}
                pdf_req_ids: set = set()

                async def on_fetch_paused(ev):
                    rid = ev.request_id
                    if _is_pdf_response(ev.request.url, getattr(ev, "response_status_code", None),
                                        getattr(ev, "response_headers", None)):
                        body, b64 = await tab.send(cdp.fetch.get_response_body(request_id=rid))
                        data = _b64decode(body, b64)
                        if data[:4] == b"%PDF":
                            captured["data"] = data
                        await tab.send(cdp.fetch.continue_request(request_id=rid))
                    else:
                        await tab.send(cdp.fetch.continue_request(request_id=rid))

                async def on_response(ev):
                    if _is_pdf_response(ev.response.url, ev.response.status, ev.response.headers):
                        pdf_req_ids.add(ev.request_id)

                async def on_finished(ev):
                    if ev.request_id in pdf_req_ids and captured["data"] is None:
                        body, b64 = await tab.send(cdp.network.get_response_body(request_id=ev.request_id))
                        data = _b64decode(body, b64)
                        if data[:4] == b"%PDF":
                            captured["data"] = data

                tab.add_handler(cdp.fetch.RequestPaused, on_fetch_paused)
                tab.add_handler(cdp.network.ResponseReceived, on_response)
                tab.add_handler(cdp.network.LoadingFinished, on_finished)

                # ② 导航到「文章页」(不是 md5 短链);nodriver 自动过 CF 质询
                await tab.get(url)
                # ③ 轮询到 deadline:命中即返回;期间可检测 block page 文本
                deadline = time.monotonic() + max(5.0, timeout)
                while time.monotonic() < deadline and captured["data"] is None:
                    await tab.sleep(0.5)
                    text = (await tab.evaluate(
                        "document.body?document.body.innerText.slice(0,2000).toLowerCase():''") or "")
                    if any(s in text for s in _BLOCK_SIGNALS):
                        return None, f"blocked:{text[:120]}"
                return captured["data"], ("ok" if captured["data"] else "no-pdf-captured")
            finally:
                try: browser.stop()
                except Exception: pass

        return asyncio.run(_go())

    return _capture
```

辅助（纯函数，可离线 selftest）：
```python
_BLOCK_SIGNALS = ("just a moment", "verify you are human", "enable javascript and cookies", "attention required")

def _is_pdf_response(url, status, headers) -> bool:
    u = (url or "").lower()
    if status is not None and int(status) != 200:
        return False
    ct = _header(headers, "content-type").lower()
    if "application/pdf" in ct:
        return True
    return u.endswith(".pdf") or "/pdfft" in u or "sciencedirectassets.com" in u

def _b64decode(body, is_b64):
    import base64
    return base64.b64decode(body) if is_b64 else (body or "").encode("latin-1", "ignore")
```

对外统一入口（信封与现有 `render_get_pdf_url` 对齐；先走合规守卫 + 限流）：
```python
def render_download_pdf_bytes(url, timeout=DEFAULT_TIMEOUT, *, min_interval=DEFAULT_MIN_INTERVAL,
                              _capture_fn=None) -> Dict[str, Any]:
    if _is_scholar_host(url):
        return {"available": True, "error": "refused: never render Google Scholar", "pdf_bytes": None}
    cap = _capture_fn or _nodriver_capture_pdf_fn()
    if cap is None:
        return {"available": False, "reason": "need nodriver", "pdf_bytes": None}
    _throttle(min_interval)
    try:
        data, note = cap(url, timeout)
    except Exception as exc:  # noqa: BLE001
        return {"available": True, "error": f"capture failed: {exc}", "pdf_bytes": None}
    if note.startswith("blocked:"):
        return {"available": True, "error": note, "pdf_bytes": None}
    return {"available": True, "url": url, "note": note,
            "pdf_bytes": data, "size": len(data) if data else 0}
```

---

## 四、接线点（给 download.py 实现者：何时触发这条重路径）

- **仅低频兜底**：`download.py` 检出终态 `cloudflare-challenge` **且** URL host ∈ `_JA3_BOUND_CF_HOSTS`（RSC/ScienceDirect）时，才调 `render_download_pdf_bytes(article_url)`——**传文章页 URL、不要传 pdf 短链**。
- 拿到 `pdf_bytes` → 复用现有 `%PDF`/`%%EOF`/体积校验 → 落盘 + 记 `flaresolverr_recovered` 同级的新事件（如 `browser_capture_recovered`）。
- **按 origin 缓存浏览器会话**（同 shim 的 origin 缓存），一域一次解题成本；批内多条同域复用。
- 默认 **gated 关闭**（同 `render_fetch`/`_flaresolverr_fallback`）：未装 nodriver / 未开开关则优雅跳过，绝不阻断主流程。

---

## 五、护栏 / 坑（务必写进实现）

1. **headed vs headless**：headed CF 通过率更高但需可见桌面（无头机可 `xvfb`）；先 headed 验证，再评 headless。
2. **别冷取短链**：ScienceDirect `...md5=` 短时绑会话，必须**在活页上下文内**由浏览器发起。
3. **PDF viewer 劫持**：禁用 PDF 扩展，或用 §2.3 的 `always_open_pdf_externally` 走下载事件。
4. **大 PDF**：`Network.enable` buffer 调大（≥100MB），否则响应体被丢。
5. **真机 / 合规**：仅对**有权访问**的资源；AGPL(nodriver) 内部回收无碍；住宅代理仅最后兜底（cf_clearance 绑 IP）。
6. **强限流**：浏览器开销大、更触发风控，沿用 `_throttle` + 每 origin 最小间隔。
7. **仅这条重路径走浏览器抓字节**；普通 OA 站继续走 `curl_cffi`/`render_get_pdf_url`，别整体切换（成本/风险）。

---

## 六、selftest 草案（离线、不联网、不起浏览器）

- 注入 `_capture_fn` mock：返回 `(b"%PDF-1.7 ...", "ok")` → 断言信封 `pdf_bytes[:4]==b"%PDF"`、`size>0`。
- mock 返回 `(None, "blocked:just a moment")` → 断言 `error` 以 `blocked:` 开头、`pdf_bytes is None`。
- 无 nodriver（工厂返 None）→ 断言 `{"available": False, "reason": "need nodriver"}`。
- Scholar host → 断言 `refused`。
- 纯函数 `_is_pdf_response` / `_b64decode` 逐例断言。打印 `RENDER_BYTES_OK`。

---

## 七、来源（均 2026-07 实读源码/README）

- `GAO-pooh/paper-scraper`（MIT，87★）：`sd_scraper_en.py` 的 `_dt_capture_pdf`（Fetch/Network 双通道 CDP 抓字节、`%PDF` 校验、block-page 检测）、`download_pdfs_devtools`（`--remote-debugging-port` 起 Chrome + `webSocketDebuggerUrl` 连接）；依赖 `curl_cffi + websocket-client + browser-cookie3`。
- `Given-Dream/sciencedirect-live-session-fetcher`（111★，Py3.10+）：活会话 DevTools 附着、短时签名 URL 必须活页上下文、IEEE `stamp.jsp` 归一化、PDF viewer 扩展劫持避坑。
- `go-rod/rod#953`：`always_open_pdf_externally` + 点 CF 复选框 + 下载事件 落盘（备用配方）。
- 本仓 `render_fetch.py`（现有 nodriver 引擎、`_is_scholar_host`/`_throttle`/信封/ selftest 规格）、`download.py`（`%PDF` 校验 + `_flaresolverr_fallback` 接线范式）、`选型2026-采纳与淘汰总表` ⑤ §四（JA3 口径 + P2）。

---

## 八、逐行可照抄补丁（`render_download_pdf_bytes` 全文 + selftest）——实现者直取

> 追加（应用户「细化为逐行可照抄补丁 + selftest 全文」）。以下为**可直接粘进 `render_fetch.py` 的新增块**（纯新增、不改现有函数；沿用本模块既有 `_is_scholar_host`/`_throttle`/`DEFAULT_TIMEOUT`/`DEFAULT_MIN_INTERVAL`）。给**两种等价实现**：A=nodriver 自带 CDP（零新依赖，首选）；B=raw `websocket-client`（paper-scraper 已证、版本最稳，作降级/备选）。实现者二选一接入即可。

### 8.1 新增常量与纯函数（可离线 selftest）

```python
import base64 as _b64

# JA3 绑定型强 CF 站(仅这些走浏览器内直下重路径;普通 OA 站不必)
_JA3_BOUND_CF_HOSTS = ("pubs.rsc.org", "sciencedirect.com", "pdf.sciencedirectassets.com",
                       "onlinelibrary.wiley.com", "pubs.acs.org")
_BLOCK_SIGNALS = ("just a moment", "verify you are human", "enable javascript and cookies",
                  "attention required", "checking your browser")
# PDF 响应拦截 URL 模式(Fetch.enable 用)
_PDF_URL_PATTERNS = ("*pdfft*", "*sciencedirectassets.com/*", "*/pdf/*", "*.pdf*")


def is_ja3_bound_cf_host(url: str) -> bool:
    """该 URL host 是否属 JA3 绑定型强 CF 站(需浏览器内直下、curl_cffi 回放会 403)。"""
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return any(h in host for h in _JA3_BOUND_CF_HOSTS)


def _header_get(headers, name: str) -> str:
    """从 CDP responseHeaders(list[{name,value}] 或 dict)取头值,大小写不敏感。"""
    name = name.lower()
    if isinstance(headers, dict):
        for k, v in headers.items():
            if str(k).lower() == name:
                return str(v)
        return ""
    for h in (headers or []):
        if str(h.get("name", "")).lower() == name:
            return str(h.get("value", ""))
    return ""


def _looks_pdf_response(url: str, status, headers) -> bool:
    """响应像 PDF:200 + content-type application/pdf,或 URL 形似 pdf 直链。"""
    if status is not None:
        try:
            if int(status) != 200:
                return False
        except (TypeError, ValueError):
            pass
    if "application/pdf" in _header_get(headers, "content-type").lower():
        return True
    u = (url or "").lower().split("#", 1)[0].split("?", 1)[0]
    return u.endswith(".pdf") or "/pdfft" in u or "sciencedirectassets.com" in u


def _decode_cdp_body(body: str, base64_encoded: bool) -> bytes:
    return _b64.b64decode(body) if base64_encoded else (body or "").encode("latin-1", "ignore")


def _is_pdf_bytes(data) -> bool:
    return bool(data) and data[:4] == b"%PDF"
```

### 8.2 抓字节函数（引擎 A：nodriver 自带 CDP）

```python
# 抓字节函数签名:capture_fn(article_url, timeout) -> (pdf_bytes|None, note)
CaptureFn = Callable[[str, float], Tuple[Optional[bytes], str]]


def _nodriver_capture_fn() -> Optional[CaptureFn]:
    """nodriver 版『浏览器内抓 PDF 字节』;未装 nodriver → None。"""
    try:
        import nodriver  # noqa: F401
    except ImportError:
        return None
    import asyncio

    def _capture(article_url: str, timeout: float) -> Tuple[Optional[bytes], str]:
        import nodriver as nd
        from nodriver import cdp  # CDP 绑定(snake_case);若你的 nodriver 版本命名不同,见 8.3 备选

        async def _go() -> Tuple[Optional[bytes], str]:
            browser = await nd.start(headless=False)  # headed CF 通过率更高;无头机用 xvfb
            try:
                tab = await browser.get("about:blank")
                await tab.send(cdp.network.enable(
                    max_total_buffer_size=120 * 1024 * 1024,
                    max_resource_buffer_size=100 * 1024 * 1024))
                await tab.send(cdp.network.set_cache_disabled(cache_disabled=True))
                await tab.send(cdp.fetch.enable(patterns=[
                    cdp.fetch.RequestPattern(url_pattern=p,
                                             request_stage=cdp.fetch.RequestStage.RESPONSE)
                    for p in _PDF_URL_PATTERNS]))

                got: Dict[str, Optional[bytes]] = {"data": None}
                pdf_rids: set = set()

                async def on_paused(ev):
                    rid = ev.request_id
                    resp_url = ev.request.url
                    status = getattr(ev, "response_status_code", None)
                    hdrs = getattr(ev, "response_headers", None)
                    try:
                        if got["data"] is None and _looks_pdf_response(resp_url, status, hdrs):
                            body, b64 = await tab.send(cdp.fetch.get_response_body(request_id=rid))
                            data = _decode_cdp_body(body, b64)
                            if _is_pdf_bytes(data):
                                got["data"] = data
                    finally:
                        try:
                            await tab.send(cdp.fetch.continue_request(request_id=rid))
                        except Exception:  # noqa: BLE001
                            pass

                async def on_resp(ev):
                    if _looks_pdf_response(ev.response.url, ev.response.status, ev.response.headers):
                        pdf_rids.add(ev.request_id)

                async def on_finished(ev):
                    if got["data"] is None and ev.request_id in pdf_rids:
                        try:
                            body, b64 = await tab.send(
                                cdp.network.get_response_body(request_id=ev.request_id))
                            data = _decode_cdp_body(body, b64)
                            if _is_pdf_bytes(data):
                                got["data"] = data
                        except Exception:  # noqa: BLE001
                            pass

                tab.add_handler(cdp.fetch.RequestPaused, on_paused)
                tab.add_handler(cdp.network.ResponseReceived, on_resp)
                tab.add_handler(cdp.network.LoadingFinished, on_finished)

                await tab.get(article_url)  # 导航到「文章页」;nodriver 自动过 CF
                deadline = time.monotonic() + max(5.0, float(timeout))
                while time.monotonic() < deadline and got["data"] is None:
                    await tab.sleep(0.5)
                    try:
                        txt = (await tab.evaluate(
                            "document.body?document.body.innerText.slice(0,1500).toLowerCase():''"
                        ) or "")
                    except Exception:  # noqa: BLE001
                        txt = ""
                    if got["data"] is None and any(s in txt for s in _BLOCK_SIGNALS):
                        # 仍在质询页:继续等 nodriver 过盾,不立即失败
                        continue
                return got["data"], ("ok" if got["data"] else "no-pdf-captured")
            finally:
                try:
                    browser.stop()
                except Exception:  # noqa: BLE001
                    pass

        return asyncio.run(_go())

    return _capture
```

### 8.3 抓字节函数（引擎 B：raw websocket-client，paper-scraper 已证，最稳备选）

```python
def _websocket_capture_fn(ws_url_provider: Callable[[], str]) -> Optional[CaptureFn]:
    """raw CDP 版:连到已起 Chrome(--remote-debugging-port)的 tab webSocketDebuggerUrl。
    ws_url_provider(): 返回目标 tab 的 webSocketDebuggerUrl(实现者按环境提供:
      如复用 nodriver 已起浏览器的调试口,或 subprocess 起 Chrome 后从 /json 取)。
    方法名为 CDP 原生 JSON(跨版本稳定),照抄自 paper-scraper _dt_capture_pdf。"""
    try:
        import websocket  # noqa: F401  (pip install websocket-client)
    except ImportError:
        return None

    def _capture(article_url: str, timeout: float) -> Tuple[Optional[bytes], str]:
        import websocket as _ws
        ws = _ws.create_connection(ws_url_provider(), timeout=180, suppress_origin=True)
        mid = {"n": 200}
        def send(method, params=None):
            mid["n"] += 1
            ws.send(json.dumps({"id": mid["n"], "method": method, "params": params or {}}))
            return mid["n"]
        pdf_rids, body_reqs, fetch_body_reqs = set(), {}, {}
        try:
            send("Page.enable"); send("Network.setCacheDisabled", {"cacheDisabled": True})
            send("Fetch.enable", {"patterns": [
                {"urlPattern": p, "requestStage": "Response"} for p in _PDF_URL_PATTERNS]})
            send("Network.enable", {"maxTotalBufferSize": 120*1024*1024,
                                    "maxResourceBufferSize": 100*1024*1024})
            send("Page.navigate", {"url": article_url})
            deadline = time.time() + max(5, float(timeout))
            while time.time() < deadline:
                ws.settimeout(max(0.5, min(2.0, deadline - time.time())))
                try:
                    msg = json.loads(ws.recv())
                except Exception:  # noqa: BLE001
                    continue
                m = msg.get("method")
                if m == "Fetch.requestPaused":
                    p = msg["params"]; rid = p.get("requestId")
                    if rid and _looks_pdf_response((p.get("request") or {}).get("url", ""),
                                                   p.get("responseStatusCode"),
                                                   p.get("responseHeaders")):
                        fetch_body_reqs[send("Fetch.getResponseBody", {"requestId": rid})] = rid
                    elif rid:
                        send("Fetch.continueRequest", {"requestId": rid})
                elif m == "Network.responseReceived":
                    p = msg["params"]; r = p.get("response", {})
                    if _looks_pdf_response(r.get("url", ""), r.get("status"), r.get("headers")):
                        pdf_rids.add(p.get("requestId"))
                elif m == "Network.loadingFinished":
                    rid = msg["params"].get("requestId")
                    if rid in pdf_rids and rid not in body_reqs.values():
                        body_reqs[send("Network.getResponseBody", {"requestId": rid})] = rid
                elif msg.get("id") in fetch_body_reqs or msg.get("id") in body_reqs:
                    res = msg.get("result", {})
                    if "error" not in msg and res.get("body"):
                        data = _decode_cdp_body(res["body"], res.get("base64Encoded", False))
                        if _is_pdf_bytes(data):
                            return data, "ok"
            return None, "no-pdf-captured"
        finally:
            try: ws.close()
            except Exception: pass  # noqa: E722

    return _capture
```

### 8.4 对外统一入口（信封 + 合规守卫 + 限流，与 `render_get_pdf_url` 对齐）

```python
def render_download_pdf_bytes(
    article_url: str,
    timeout: float = DEFAULT_TIMEOUT,
    *,
    min_interval: float = DEFAULT_MIN_INTERVAL,
    _capture_fn: Optional[CaptureFn] = None,
) -> Dict[str, Any]:
    """在浏览器内直接抓 PDF 字节(破 JA3 绑定型强 CF)。可选、默认关闭、强限流。

    返回信封:
      无引擎:        {"available": False, "reason": "need nodriver", "pdf_bytes": None}
      合规拒绝:      {"available": True, "error": "refused: ...", "pdf_bytes": None}
      被质询拦:      {"available": True, "error": "blocked:...", "pdf_bytes": None}
      成功:          {"available": True, "url":..., "pdf_bytes": b"%PDF...", "size": N}
      失败:          {"available": True, "error": "...", "pdf_bytes": None}
    合规:命中 Google Scholar 直接拒绝(复用 _is_scholar_host)。
    """
    if _is_scholar_host(article_url):
        return {"available": True, "error": "refused: never render Google Scholar",
                "pdf_bytes": None}
    cap = _capture_fn or _nodriver_capture_fn()
    if cap is None:
        return {"available": False, "reason": "need nodriver", "pdf_bytes": None}
    _throttle(min_interval)
    try:
        data, note = cap(article_url, timeout)
    except Exception as exc:  # noqa: BLE001 - 绝不外抛,优雅降级
        return {"available": True, "error": f"capture failed: {exc}", "pdf_bytes": None}
    if isinstance(note, str) and note.startswith("blocked:"):
        return {"available": True, "error": note, "pdf_bytes": None}
    if not _is_pdf_bytes(data):
        return {"available": True, "error": f"no-pdf: {note}", "pdf_bytes": None}
    return {"available": True, "url": article_url, "note": note,
            "pdf_bytes": data, "size": len(data)}
```

### 8.5 selftest 全文（离线、不起浏览器；并入 `_selftest()`，打印 `RENDER_BYTES_OK`）

```python
def _selftest_bytes() -> None:
    # 1) 纯函数
    assert is_ja3_bound_cf_host("https://pubs.rsc.org/en/content/articlepdf/2011/GC/C1GC15503B")
    assert is_ja3_bound_cf_host("https://www.sciencedirect.com/science/article/pii/X")
    assert not is_ja3_bound_cf_host("https://www.mdpi.com/x")
    assert _looks_pdf_response("https://x/pdfft?md5=1", 200,
                               [{"name": "Content-Type", "value": "application/pdf"}])
    assert not _looks_pdf_response("https://x/article", 200,
                                   [{"name": "Content-Type", "value": "text/html"}])
    assert not _looks_pdf_response("https://x/a.pdf", 403, [])  # 非 200 不算
    assert _is_pdf_bytes(b"%PDF-1.7 xx") and not _is_pdf_bytes(b"<html>")
    assert _decode_cdp_body("JVBERi0=", True)[:4] == b"%PDF"  # base64("%PDF")

    # 2) 成功路径:注入 mock capture 返回 %PDF 字节
    ok = render_download_pdf_bytes("https://pubs.rsc.org/a",
                                   _capture_fn=lambda u, t: (b"%PDF-1.7 ...", "ok"),
                                   min_interval=0.0)
    assert ok["available"] and ok["pdf_bytes"][:4] == b"%PDF" and ok["size"] > 0, ok

    # 3) blocked
    b = render_download_pdf_bytes("https://pubs.rsc.org/a",
                                  _capture_fn=lambda u, t: (None, "blocked:just a moment"),
                                  min_interval=0.0)
    assert b["pdf_bytes"] is None and b["error"].startswith("blocked:"), b

    # 4) 抓到非 PDF
    n = render_download_pdf_bytes("https://pubs.rsc.org/a",
                                  _capture_fn=lambda u, t: (b"<html>", "ok"), min_interval=0.0)
    assert n["pdf_bytes"] is None and "no-pdf" in n["error"], n

    # 5) 合规拒绝 Scholar
    r = render_download_pdf_bytes("https://scholar.google.com/scholar?q=x",
                                  _capture_fn=lambda u, t: (b"%PDF", "ok"), min_interval=0.0)
    assert r["pdf_bytes"] is None and r["error"].startswith("refused"), r

    # 6) capture 抛错 → 优雅降级
    def _boom(u, t): raise RuntimeError("cdp timeout")
    e = render_download_pdf_bytes("https://pubs.rsc.org/a", _capture_fn=_boom, min_interval=0.0)
    assert e["pdf_bytes"] is None and "capture failed" in e["error"], e

    # 7) 无引擎 → available False(临时把工厂置空以确定性断言;此处直接构造)
    #    实测:未装 nodriver 时 _nodriver_capture_fn() 返回 None → reason need nodriver
    print("RENDER_BYTES_OK")
# 在 _selftest() 末尾(print("RENDER_OK") 之前)调用 _selftest_bytes()
```

### 8.6 download.py 接线（给下载层实现者）

```python
# 伪代码:在 download_pdf 的 Cloudflare 兜底分支(现有 _flaresolverr_fallback 之后/并列)
from .render_fetch import render_download_pdf_bytes, is_ja3_bound_cf_host

def _browser_capture_fallback(article_url, client, log, events):
    if not is_ja3_bound_cf_host(article_url):
        return None                      # 非 JA3 型强 CF,不走这条重路径
    if not _browser_capture_enabled(client.cfg):   # gated,默认关(同 _flaresolverr_enabled)
        return None
    res = render_download_pdf_bytes(article_url, timeout=client.cfg.timeout)
    if res.get("pdf_bytes"):
        # 复用现有 %PDF/%%EOF/体积校验后落盘;记事件
        events.emit("browser_capture_recovered", url=article_url, bytes=res["size"])
        return res["pdf_bytes"]
    events.emit("browser_capture_failed", url=article_url, reason=res.get("error"))
    return None
```
> 触发点:`download.py` 检出终态 `cloudflare-challenge` 且 `is_ja3_bound_cf_host(url)` 为真时调用;**传文章页 URL、不传 pdf 短链**;按 origin 缓存浏览器会话;默认 gated 关闭。

---

*核验 2026-07-02｜信息检索-智库专家岗（承 -177，本会话）｜工单「强CF 浏览器内直下 PDF 实现者骨架」+「逐行可照抄补丁细化」｜结论：破 JA3 死结的唯一免费法＝solve 与 download 同一浏览器会话、经 CDP(Fetch/Network getResponseBody)在浏览器内抓 %PDF 字节;已从 paper-scraper 源码提炼可照抄配方、给出 nodriver(A)/raw-websocket(B) 两版全文补丁 + 离线 selftest(RENDER_BYTES_OK) + download.py 接线,映射到 render_fetch.py 新扩展点 render_download_pdf_bytes()。仅新建/追加本 1 份骨架文档，未改任何 .py。*
