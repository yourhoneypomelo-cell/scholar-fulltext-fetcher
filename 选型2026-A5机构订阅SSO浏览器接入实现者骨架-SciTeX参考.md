# 选型2026 · A5 机构订阅「SSO 浏览器接入」实现者骨架（SciTeX-Scholar 参考 + N3/N4 落地）

> 交付：**信息检索-智库专家岗**（承 -177，本会话）｜2026-07-02
> 触发：用户点名「深挖 SciTeX-Scholar 源码 → A5 机构订阅 SSO 浏览器接入实现者骨架」。
> 边界：**只新建本 1 份骨架**；**不改任何 .py**（A5 代码活归 -153，见 ⑤/N3/N4）。基于：SciTeX-Scholar 架构（实读 README + 文件树）+ 本仓 N3/N4 机构订阅设计 + `sources/base.py` 插件接口 + §八 的浏览器内 CDP 抓字节（本会话强CF骨架）。
> 定位：A5 是**突破订阅付费墙天花板的根本途径**（Elsevier/RSC 等纯订阅刊，免费路线已到顶 → 唯机构订阅）。本骨架把「登录持久化(N4) + 授权会话内下载(强CF骨架) + EZproxy/SSO 改写」串成一个可插拔 `sources/institutional.py`。

---

## 〇、TL;DR

- **SciTeX 的可借鉴主链**：`enrich → resolve URL → authenticate(OpenAthens/SSO, Playwright) → download(chrome-viewer / direct / fallback 三策略) → store(MASTER-hash 库)`。
- **本仓落地形态**：新增 `sources/institutional.py`（`BaseSource` 子类，默认关），复用：① N4 的 **CookieStore 4 层持久化 + 一次性登录浏览器**；② 本会话 §八 的**授权会话内 CDP 抓 PDF 字节**（机构站也多在 CF/JS 后，直下才稳）；③ **EZproxy/CARSI/OpenAthens/Shibboleth/WebVPN** 的 URL 改写或代理。
- **合规红线**：仅对**你确有合法机构订阅权限**的资源；默认 `enabled=False`；**绝不创造无权限的访问**（不破 CAPTCHA/付费墙本身，只是以你的合法身份走正门）。

---

## 一、读 SciTeX-Scholar 提炼的架构（实读 README + 文件树）

| SciTeX 组件 | 做法 | 对本仓的借鉴 |
|---|---|---|
| **认证** | Playwright 浏览器走 **OpenAthens / 机构 SSO** 登录，拿到授权会话 | → N4 的 `open_login_browser()` 一次性登录 + CookieStore 持久化 |
| **下载三策略** | `pdf_download/`：**chrome-viewer**（浏览器内查看器取）/ **direct**（直链）/ **fallback**（元数据/iframe/embed） | → 与 §八 CDP 抓字节同构；direct 走本仓 download.py，chrome-viewer 走 §八 |
| **全链一次调用** | `paper fetch --doi` = `enrich → resolve URL → authenticate → download → store` | → `institutional.find_candidates()` 出「授权可下的 URL」，交 download 层 |
| **库管理** | MASTER-hash 库 + 每项目 symlink | → 本仓已有标准化命名/落盘，不需引入；MASTER-hash 去重思路登记 |
| **许可/依赖** | Playwright（重） | 本仓首选 **nodriver**（已装、已用），Playwright 仅可选；勿强依赖 |

> 关键判断：SciTeX 证明「**机构 SSO 浏览器授权会话 + 浏览器内下载**」是订阅刊的可行正门；但其 Playwright/MASTER-hash 全家桶偏重。本仓**只借主链思想**，落到 N3/N4 既有设计 + nodriver。

---

## 二、落地骨架 `fulltext_fetcher/sources/institutional.py`

> `BaseSource` 子类（接口见 `sources/base.py`）。**默认关**：无凭据/未开 → `applicable()` 返 False，优雅跳过。

```python
"""机构订阅接入(A5):以你的合法机构身份走正门取订阅刊全文。默认关闭。

合规:仅对你确有订阅权限的资源;绝不创造无权限访问(不破付费墙本身)。
路线:EZproxy/CARSI/OpenAthens/Shibboleth/WebVPN 改写 URL + 持久化授权会话
     (N4 CookieStore) + 授权会话内下载(强CF骨架 render_download_pdf_bytes)。
"""
from __future__ import annotations
from typing import List, Optional
from urllib.parse import urlparse
from ..models import Paper, PdfCandidate
from .base import BaseSource, SourceContext, register

# 订阅型出版商域(与 aggregators._CROSSREF_PAYWALL_HOSTS 对齐)
_SUBSCRIPTION_HOSTS = ("sciencedirect.com", "pubs.rsc.org", "onlinelibrary.wiley.com",
                       "pubs.acs.org", "academic.oup.com", "tandfonline.com",
                       "journals.sagepub.com", "link.springer.com", "ieeexplore.ieee.org")


def ezproxy_rewrite(url: str, ezproxy_host: str) -> str:
    """把出版商 URL 改写成 EZproxy 主机名式代理 URL。
    例: https://www.sciencedirect.com/x + ezproxy.univ.edu
     → https://www-sciencedirect-com.ezproxy.univ.edu/x
    (EZproxy 主流的 host-rewriting 模式;若你校用 URL 前缀式 login?url= 见下 alt。)"""
    p = urlparse(url)
    if not p.hostname:
        return url
    host = p.hostname.replace("-", "--").replace(".", "-")
    return f"{p.scheme}://{host}.{ezproxy_host}{p.path}" + (f"?{p.query}" if p.query else "")


def ezproxy_login_prefix(url: str, ezproxy_base: str) -> str:
    """前缀式 EZproxy: https://ezproxy.univ.edu/login?url=<原始URL>。"""
    from urllib.parse import quote
    return f"{ezproxy_base.rstrip('/')}/login?url={quote(url, safe='')}"


def is_subscription_host(url: str) -> bool:
    try:
        h = (urlparse(url or "").hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return any(s in h for s in _SUBSCRIPTION_HOSTS)


@register
class Institutional(BaseSource):
    name = "institutional"
    requires_doi = True

    def applicable(self, paper: Paper) -> bool:
        # 需:总开关开 + 有登录态(cookie store) + DOI(实际 host 判断在 find_candidates)
        return bool(paper.doi)   # 细化:见 find_candidates 里对 cfg 的门控

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        cfg = ctx.cfg
        if not getattr(cfg, "institutional_enabled", False):
            return []                              # 默认关
        # 以出版商落地页 URL 为基(可由 publisher_adapter/DOI 前缀推导,或 Crossref/landing 给)
        base_url = _publisher_url_for(paper)       # 复用现有 publisher_adapter 推导
        if not base_url or not is_subscription_host(base_url):
            return []
        mode = getattr(cfg, "institutional_mode", "cookie")   # cookie|ezproxy_host|ezproxy_prefix
        if mode == "ezproxy_host" and getattr(cfg, "ezproxy_host", None):
            url = ezproxy_rewrite(base_url, cfg.ezproxy_host)
        elif mode == "ezproxy_prefix" and getattr(cfg, "ezproxy_base", None):
            url = ezproxy_login_prefix(base_url, cfg.ezproxy_base)
        else:
            url = base_url                          # cookie 模式:靠持久化授权会话
        # 高置信候选,但标记 needs_authorized_session=True → download 层走授权会话内 CDP 直下
        return [PdfCandidate(url, self.name, "landing", None, None, 88,
                             meta={"needs_authorized_session": True})]
```

> `PdfCandidate.meta`（若无则复用现有字段/新增可选 meta）标 `needs_authorized_session=True`，指示 `download.py`：**别用 curl_cffi 裸下**，改走 §八 `render_download_pdf_bytes(url)`（用持久化的授权 cookie + 浏览器内 CDP 抓字节；机构站多在 CF/JS 后，直下才稳、且带机构 entitlement）。

---

## 三、N4 CookieStore + 一次性登录浏览器（持久化授权会话）

```python
# fulltext_fetcher/institutional_session.py (或并入 institutional.py)
import json, os, time
from typing import Dict, List

class CookieStore:
    """按出版商域持久化授权 cookie(N4 第①层)。明文落本地,权限 600;含过期戳。"""
    def __init__(self, path: str):
        self.path = path
        self._data: Dict[str, dict] = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:  # noqa: BLE001
                return {}
        return {}

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f)
        os.replace(tmp, self.path)
        try: os.chmod(self.path, 0o600)
        except Exception: pass  # noqa: E722

    def put(self, host: str, cookies: List[dict]) -> None:
        self._data[host] = {"cookies": cookies, "saved_at": time.time()}
        self.save()

    def get(self, host: str, max_age_s: float = 14 * 86400) -> List[dict]:
        rec = self._data.get(host)
        if not rec or (time.time() - rec.get("saved_at", 0)) > max_age_s:
            return []
        return rec.get("cookies", [])


def open_login_browser(login_url: str, cookie_store: CookieStore, host: str,
                       ready_timeout: float = 300.0) -> bool:
    """N4 第②层:弹 headed 浏览器让用户人工过机构 SSO;登录后抓 cookie 存库。
    实现:nodriver 起 headed → 打开 login_url → 轮询直到检测到登录成功标志(如出现某
    授权元素/cookie 出现) 或用户回车 → 用 CDP Network.getAllCookies 导出 → cookie_store.put。
    合规:仅供你本人以合法机构账号登录;不自动化输入凭据(避违 SSO 条款),人工登录。"""
    ...   # 见 §八 nodriver 起浏览器范式;此处 headed + 人工登录 + 抓 cookie
    return True
```

---

## 四、配置项（config.py，全部默认关/空）

```python
institutional_enabled: bool = False          # A5 总开关
institutional_mode: str = "cookie"           # cookie | ezproxy_host | ezproxy_prefix
ezproxy_host: Optional[str] = None           # 如 "ezproxy.univ.edu"(host-rewrite 式)
ezproxy_base: Optional[str] = None           # 如 "https://ezproxy.univ.edu"(前缀式)
institutional_cookie_store: Optional[str] = None   # cookie 持久化路径
```

CLI：`--institutional`（开关）、`--ezproxy-host`/`--ezproxy-base`、`--institutional-login`（先跑一次 `open_login_browser`）。

---

## 五、selftest 草案（离线、不联网、不起浏览器）

- `ezproxy_rewrite("https://www.sciencedirect.com/science/article/pii/X", "ezproxy.univ.edu")` == `https://www-sciencedirect-com.ezproxy.univ.edu/science/article/pii/X`（点→`-`、连字符→`--`）。
- `ezproxy_login_prefix(url, "https://ezproxy.univ.edu")` 含 `login?url=` 且原 URL 被 quote。
- `is_subscription_host` 对 sciencedirect/rsc/wiley 真、对 mdpi/arxiv 假。
- `Institutional.find_candidates`：`institutional_enabled=False` → `[]`；开且订阅域 → 1 候选且 `meta.needs_authorized_session`。
- `CookieStore` put/get 往返 + 过期(max_age) 归零。
- 打印 `INSTITUTIONAL_OK`。

---

## 六、护栏 / 合规（务必写进实现）

1. **仅合法权限**：只对你**确有机构订阅**的刊；A5 是「以合法身份走正门」，**不是破付费墙**。
2. **人工登录**：SSO 登录人工完成，**不自动填凭据**（避违机构/IdP 条款）；凭据/cookie 只落本地、600 权限、可过期。
3. **默认关**：`institutional_enabled=False`；无 cookie store/凭据 → 优雅跳过。
4. **授权会话内下载**：机构站多在 CF/JS 后 → 复用 §八 `render_download_pdf_bytes`（浏览器内 CDP 抓字节，带机构 cookie），别 curl_cffi 裸下（易掉 entitlement / JA3 403）。
5. **礼貌**：机构流量同样限速；别高并发拖累机构出口/触发风控。
6. **代码活归属**：A5 实现归 -153（N3/N4 归口）；本骨架仅供其直取。

---

## 七、来源

- `ywatanabe1989/SciTeX-Scholar`（实读 README + 文件树）：Playwright OpenAthens/SSO 认证、`pdf_download/`（chrome-viewer/direct/fallback）、`enrich→resolve→authenticate→download→store` 全链、MASTER-hash 库。
- 本仓 **N3**（`选型2026-机构订阅与住宅代理方案`,156）+ **N4**（`选型2026-机构订阅Cookie与Profile持久化源码架构-对141建议`,142）：instsci CloakBrowser + CookieStore 4 层持久化 + WebVPN/CARSI/EZproxy/Shibboleth。
- 本仓 `sources/base.py`（BaseSource/register 插件接口）、`publisher_adapter.py`（出版商 URL 推导）、本会话 §八 `render_download_pdf_bytes`（授权会话内 CDP 抓字节）。
- `Given-Dream/sciencedirect-live-session-fetcher`：活授权会话复用（登录后保持窗口、脚本 attach）——与本骨架 `open_login_browser` 同构。

---

*核验 2026-07-02｜信息检索-智库专家岗（承 -177，本会话）｜工单「A5 机构订阅 SSO 浏览器接入实现者骨架」｜结论：借 SciTeX「SSO 授权会话 + 浏览器内下载」主链,落到本仓 `sources/institutional.py`(默认关) = N4 CookieStore 持久化 + EZproxy/CARSI URL 改写 + §八 授权会话内 CDP 抓字节;合规红线=仅合法权限、人工登录、不破付费墙本身。代码活归 -153。仅新建本 1 份骨架,未改任何 .py。*
