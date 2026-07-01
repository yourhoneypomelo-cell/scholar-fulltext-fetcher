# 选型 2026 · 隐身 HTTP 与 TLS 指纹客户端(服务 download / http_client 取回反指纹)

> 整理人:谷歌学术人机认证-148 ｜ 数据核验:**2026-07-01**(star/版本/许可以该日 GitHub / PyPI 为准)。
> 目的:项目最大瓶颈是「**定位到 OA 副本却下不下来**」——出版商 / CDN 对无浏览器指纹的 `requests` 直连
> 常以 TLS/JA3、HTTP2 指纹判机器人而 403/挂断。本文为 `fulltext_fetcher.http_client` / `download`(以及
> `scholar.fetcher` 已用)选一款**隐身 HTTP + TLS 指纹客户端**:能伪装真实浏览器 JA3/JA4/HTTP2 指纹、可直接
> 落到我们的取回路径。
> 边界:本文只**新增本 md**,不改任何 .py、不改他人文档。选型落地由总指挥统筹。

---

## 〇、一页结论(TL;DR)

- **主采用:`curl_cffi`(lexiforest)** —— 最成熟、社区最大、`requests` 式 API(近乎 drop-in)、**唯一带 HTTP/3 指纹**、
  `curl-cffi update` 可不升级库热更指纹、预编译含 Windows 轮子、MIT。**且 `scholar.fetcher` 已在用它**,父包
  `download`/`http_client` 复用它做「反指纹取回兜底」**集成成本最低、技术栈统一**。
- **A/B 备选:`primp`(deedy5)** —— Rust(rquest)驱动、**自称最快**、独有「**浏览器与 OS 指纹独立选择**」、MIT、含
  Windows 轮子。API 非 `requests` 完全同形(用 `Client`),社区较小、无 HTTP/3。**吞吐吃紧或需独立 OS 指纹时 A/B。**
- **BSD-4 备胎:`tls-client`(bogdanfinn)Python 绑定** —— Go 引擎极活跃;Python 侧用**活跃维护绑定**
  `tls-client-python`(CFFI)或 `async-tls-client`(diprog,asyncio),**别用**已弃维护的原版 `FlorianREGAZ/Python-Tls-Client`。
  指纹控制最细,但轮子重(~40MB,内嵌 Go .so)、许可 BSD-4-Clause(含"广告条款")。仅当 curl_cffi/primp 都不满足时用。
- **不用:`hrequests`(daijro,2024-12 停更)、`Python-Tls-Client` 原版(弃维护)**。
- **不用于反指纹:`httpx`** —— 无原生 TLS 指纹伪装(用 Python `ssl`/`h2`,JA3 固定易识别);要指纹须叠 `httpx-curl-cffi`
  之类适配器(等于还是 curl_cffi)。`httpx` 保留作普通异步 HTTP 用途即可,不承担反指纹职责。

**一句话**:`http_client`/`download` 的「反指纹取回」统一走 **curl_cffi**(与 scholar.fetcher 同栈),`primp` 留作性能/独立OS 的 A/B,`tls-client` 系作 BSD-4 备胎;`hrequests`、`httpx(裸)` 出局。

---

## 一、现有文档评估(是否充分)

| 已有文档 | 覆盖 | 对本专项是否充分 |
|---|---|---|
| `检索成果-角度1-GitHub开源项目直检.md`(152) | Scholar 抓取/下载**项目**(scholarly / PyPaperBot / paperscraper …) | **不充分**:面向"爬虫项目"而非"HTTP/TLS 指纹客户端库",未逐库比 curl_cffi/tls-client/primp/httpx |
| `谷歌学术爬虫-调研-反爬与浏览器自动化.md`(153,R1) | 反爬三层两翼;L1 提到 curl_cffi、tls-client、hrequests | **部分**:从"抓 Scholar"角度给了 L1 结论,但**未含 `primp`、未评 `httpx` 定制、未聚焦 download/http_client 取回集成** |

→ 本文**补齐**:以"下载取回反指纹客户端"为唯一焦点,纳入 R1 未覆盖的 `primp` 与 `httpx` 判定,并给出对 `download.py`/`http_client.py` 的**集成落点与工作量**。

---

## 二、决策表(2026-07-01 核验)

| 项目 | ⭐Star | 最近更新 | 许可 | 关键能力 | 适配我们哪个模块 | 采用/跳过 + 理由 | 集成工作量 |
|---|---|---|---|---|---|---|---|
| **curl_cffi** `lexiforest/curl_cffi` | ~5.9k | v0.15.1b2 · 2026-06-05(活跃) | **MIT** | JA3/JA4 + **HTTP/2 + HTTP/3** 指纹;`requests` 式 API(Session/AsyncSession);websocket;`curl-cffi update` 热更指纹;预编译(含 Windows) | `http_client`(反指纹取回兜底)、`download`(PDF 直取)、`scholar.fetcher`(**已用**) | **✅ 主采用** —— 最成熟、drop-in、HTTP/3、栈已统一 | **低**(已是可选依赖;requests-like) |
| **primp** `deedy5/primp` | ~0.5k | v1.3.1 · 2026-05-23(活跃) | **MIT** | Rust(rquest);JA3/JA4 + HTTP/2 + 头序;**浏览器/OS 指纹独立选择**;sync `Client` + `AsyncClient`;Windows 轮子;自称最快 | `download`/`http_client` 的 A/B | **✅ 备选(A/B)** —— 吞吐吃紧或需独立 OS 指纹时;API 非完全 requests 同形、无 HTTP/3、社区小 | **低-中**(薄适配 `Client`) |
| **tls-client-python**(绑定 `bogdanfinn/tls-client`,CFFI) | 绑定较新 | 1.15.0.4 · 2026-06-07(活跃) | 引擎 **BSD-4-Clause** | Go 引擎经 CFFI;`requests` 式 Session/AsyncSession;26 字段自定义 TLS;头序/证书 pin;panic-proof | 备胎 | **➖ 备选** —— 指纹控制最细,但轮子重(~40MB+Go .so)、BSD-4 广告条款 | **中** |
| **async-tls-client** `diprog/python-tls-client-async` | 小 | v2.2.0(活跃) | 绑定 MIT / 引擎 BSD-4 | 原 Python-Tls-Client 的 **asyncio 活跃分支**;跟进 Go 引擎;Py3.9-3.13 | 备胎(异步场景) | **➖ 备选** —— 需要 tls-client 且要 async 时 | **中** |
| **tls-requests** `thewebscraping/tls-requests` | ~160 | v1.2.5 · 2026-02 | 绑定 MIT / 引擎 BSD-4 | 基于 tls-client 的 requests 风格封装;主打反 bot | 备胎 | **➖ 备选** | **中** |
| **Python-Tls-Client** `FlorianREGAZ/...`(原版) | ~4k | **停更** | MIT | tls-client 早期 Python 绑定 | — | **❌ 跳过** —— 已弃维护(社区转 async-tls-client / tls-client-python) | — |
| **hrequests** `daijro/hrequests` | ~1k | **2024-12 停更** | Apache-2.0 | tls-client + BrowserForge 头 + Playwright 渲染一体 | — | **❌ 跳过** —— 停更;能力已被 botasaurus-requests 延续 | — |
| **httpx** `encode/httpx`(+ 定制) | ~14k | 活跃 | BSD | 现代 sync/async HTTP;**但无原生 TLS 指纹伪装**(JA3 固定) | 仅经 `httpx-curl-cffi` 适配器 | **❌ 不用于反指纹** —— 裸 httpx 过不了 JA3 检测;要指纹等于叠 curl_cffi | —(普通 HTTP 用途另说) |

---

## 三、Top 1–2 深评

### 3.1 curl_cffi(Top 1,主采用)
- **impersonate 机制**:Python 绑定 `lexiforest/curl-impersonate`(curl-impersonate 的活跃 fork),在**加密层逐字节复刻**真实浏览器
  TLS/JA3/JA4 与 HTTP/2 帧顺序;**v0.15.0 新增 HTTP/3 指纹 + UDP socks5 代理**。用法即 `impersonate="chrome"`(自动跟最新,
  现为 `chrome146`/`safari260`/`firefox147`);也可 `ja3=/akamai=/extra_fp=` 自定义。
- **维护 / 热更**:v0.15.1b2(2026-06-05)活跃;**`curl-cffi update` 可不升级库就热更指纹库**(Chrome/Safari/Firefox 免费,其余商业版)——
  显著降低"随浏览器升级失效"的维护成本。~5.9k star、社区/文档最全,有 requests / httpx / Scrapy 适配器与打码集成生态。
- **许可 / Windows**:**MIT**;PyPI 提供**预编译轮子含 Windows amd64**,`pip install curl_cffi` 即用,无需本地编译。
- **API**:`from curl_cffi import requests as creq; creq.get(url, impersonate="chrome")` / `creq.Session()` / `AsyncSession()`——
  与 `requests` 近乎同形,**替换 http_client 的 session 极低成本**。
- **注意**:近期版本修过重定向型 SSRF,接受外部 URL 时可设 `allow_redirects` 谨慎;beta 版本号(0.15.x)但已长期生产可用。

### 3.2 primp(Top 2,A/B 备选)
- **impersonate 机制**:Python 绑定 Rust 的 `rquest`(reqwest 定制),伪装 TLS/JA3/JA4 + HTTP/2 + 头序;profile 如 `chrome_146`,
  **可 `impersonate_os="windows"` 把 OS 指纹与浏览器 profile 独立组合**(curl_cffi 目前做不到)。
- **维护 / 性能**:v1.3.1(2026-05-23)活跃、56 个 release;Rust 底层,**基准里常是最快的 Python 反指纹客户端**(吞吐优先场景有优势)。
- **许可 / Windows**:**MIT**;PyPI 提供 Windows amd64 轮子(以及 linux/macos)。
- **API / 短板**:`primp.Client(impersonate=..., impersonate_os=...)`(**非** requests 模块级函数),需薄适配;**无 HTTP/3**;star ~0.5k、文档/社区显著小于 curl_cffi。
- **定位**:作为 curl_cffi 的 **A/B 对照**——当某些顽固站点用 curl_cffi 仍被拦、或需要独立 OS 指纹、或批量吞吐吃紧时切它试。

---

## 四、集成要点(落到 `download.py` / `http_client.py`)

> 原则(承父包/子包既有约定):**不进强制依赖、函数内延迟导入、缺库优雅降级到现有 `requests` 路径**。

1. **http_client.py**:现为 `requests.Session`(重试/退避/限速/熔断齐全)。建议加一条**可选「impersonate 取回」路径**:
   对被普通 `requests` 判机器人而 403/挂断的 host(或全局开关 `cfg.impersonate_http=True`),改用
   `curl_cffi.requests.Session(impersonate=cfg.impersonate)` 发起 GET,**复用现有重试/退避/熔断与限速逻辑**(curl_cffi 响应
   对象与 requests 近乎同形,`status_code/headers/content/iter_content` 均可用)。缺 curl_cffi 时回退现状,零行为变化。
2. **download.py**:PDF 直取遇 403/TLS 挂断时,用 curl_cffi(`impersonate="chrome"`)重试该 URL——这正是「定位到 OA 副本却下不下来」的直接解药。
   建议做成 `download_pdf` 的**兜底重试层**(先普通 client,失败且疑似指纹拦截再 impersonate 一次)。
3. **与 scholar.fetcher 对齐**:`scholar.fetcher.CurlCffiEngine` 已用 curl_cffi + `cfg.impersonate`;父包取回统一到同一库,**指纹策略/依赖单点管理**,避免多套栈。
4. **A/B 钩子**:把「取回引擎」抽象成可切换项(`curl_cffi` / `primp`),默认 curl_cffi;primp 作实验开关,便于按 host 命中率/吞吐对照。
5. **依赖治理**:`curl_cffi`(及可选 `primp`)放 `requirements-*-optional.txt` 或说明文档,**不进 `fulltext_fetcher/requirements.txt` 强制依赖**;一律 `try: import ... except ImportError: 降级`。

**集成工作量估**:curl_cffi 反指纹兜底(http_client + download)约**半天**(薄封装 + 开关 + 离线 mock 测试);primp A/B 适配约**再半天**。

---

## 五、合规

- 伪装浏览器指纹绕过反爬处**灰色地带**,可能违反目标站 ToS;本项目仅对**已定位到的 OA/有权访问副本**做取回兜底、默认本地 IP + 限速,
  不用于绕过付费墙授权。使用者自负合规与法律责任。
- 许可传染:curl_cffi / primp 为 **MIT**(宽松);tls-client 引擎 **BSD-4-Clause**(含广告条款,商用需保留)。默认路径用 MIT 项目更省心。

---

## 六、来源(2026-07-01 核验)

- curl_cffi:GitHub `github.com/lexiforest/curl_cffi`(⭐~5.9k、MIT、v0.15.1b2 2026-06-05)、PyPI `curl-cffi`、readthedocs impersonate targets(chrome146/safari260/firefox147;`curl-cffi update` 自 v0.15.1;HTTP/3 自 v0.15.0)。
- primp:GitHub `github.com/deedy5/primp`(⭐~0.5k、MIT、v1.3.1 2026-05-23、绑定 Rust rquest)、PyPI `primp`、DeepWiki Browser Impersonation、webscraping.fyi primp vs curl-cffi、datahut《curl_cffi Guide 2026》。
- tls-client:`pkg.go.dev/github.com/bogdanfinn/tls-client`(BSD-4、v1.15.1 2026-06-08)、PyPI `tls-client-python`(1.15.0.4 2026-06-07,CFFI 绑定)、`async-tls-client`(diprog,v2.2.0,MIT)、`github.com/thewebscraping/tls-requests`(v1.2.5)、`FlorianREGAZ/Python-Tls-Client`(原版停更)。
- hrequests:`github.com/daijro/hrequests`(Apache-2.0,2024-12 停更)。
- httpx:`github.com/encode/httpx`(无原生 TLS 指纹;经 `httpx-curl-cffi` 适配器方可)。
- 仓内交叉:`检索成果-角度1-GitHub开源项目直检.md`、`谷歌学术爬虫-调研-反爬与浏览器自动化.md`。
