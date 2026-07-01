# 选型2026 — 机构订阅 Cookie / Profile 持久化源码架构（scansci/instsci 拆解 + 给 141 的落地建议）

> **定位**：项目智库（142）对 `scansci-pdf`（内含 instsci 桥）的 **CloakBrowser + Cookie/Profile 持久化** 源码级拆解，对标本项目 `http_client.py` 现有的「静态单 Cookie 串」骨架，给出 141 的机构订阅 Cookie 持久化层（P0）可直接落地的分层设计、接线方式与代码骨架。
> 整理人：谷歌学术人机认证-142（项目智库）｜2026-07-02
> **状态**：智库检索成果，待总指挥（147）判断；建议直送组员 141（机构订阅 Cookie 持久化层负责人）。
> **源码基准**：`scansci-pdf` @ master：`session_store.py` / `browser_login.py` / `browser_cookies.py` / `session_broker.py` / `cloakbrowser_compat.py`。

---

## 一、结论速览

- **本项目现状**：`http_client.py` 只有「**静态单 `institution_cookie` 串 + `ezproxy_prefix` 前缀重写 + `institution_domains` 白名单**」的可插拔骨架（默认关、零副作用），**没有**：浏览器交互式登录取 Cookie、按出版商持久化、过期校验、localStorage 持久化、一次登录多篇的会话复用。这正是 141 的 P0 缺口。
- **scansci/instsci 做法**：分 **4 层**——① `CookieStore` 底层 JSON 持久化（过期校验）；② 浏览器态捕获（可见 CloakBrowser 登录 + **cookies + localStorage** 双持久化 + 登录自动检测）；③ 认证流（WebVPN/CARSI/EZProxy，**每出版商一份 cookie 文件**）；④ 长存会话 broker（一次登录多篇、broker 状态**不存 cookie 值**）。
- **给 141 的建议**：P0 先落 ①+②（`CookieStore` + `open_login_browser`）并把 `http_client` 的「单串注入」改为「按域从 CookieStore 取」；P1 落 ③ 每社 cookie + merge/dedup + localStorage；P2 落 ④ broker（批量一次登录多篇，与竞速引擎批级 Phase2 协同）。**本项目在 Windows，务必带 `cloakbrowser_compat` 的平台补丁**。

---

## 二、scansci/instsci 的 Cookie/Profile 持久化四层架构

### 2.1 底层：`CookieStore`（session_store.py，~90 行零依赖）

纯 JSON cookie 持久化 + 过期校验 + 注入 requests 会话：

```python
class CookieStore:
    def __init__(self, path): self.path = Path(path)
    def load(self, now=None):            # 读盘 → 过滤过期 → 返回有效 cookie 列表
    def save(self, cookies, now=None):   # 只存有效的（过期/缺字段丢弃）
    def load_into(self, session):        # 注入 requests 会话 cookie jar
    @staticmethod
    def _is_valid(cookie, now):          # expires==0 → 会话 cookie 恒有效；否则 expires>now
```
> 价值：把「一个静态串」升级为「结构化、可过期、可增量」的 cookie 仓。**可原样移植**到本项目（零依赖）。

### 2.2 浏览器态捕获（browser_login.py / browser_cookies.py）—— 两种互补机制

**(a) `PersistentBrowser` 单例**：登录一次、整个进程复用同一浏览器（WebVPN 会话不断）。核心是 **cookies + localStorage 双持久化**（`browser_state.json`）：

```python
def save_cookies(self, config):
    cookies = self._context.cookies()
    localStorage = {}                       # 逐 page 抓 localStorage（部分出版商把登录态放这里）
    for page in self._context.pages:
        origin = f"{scheme}://{hostname}"
        localStorage[origin] = page.evaluate("(()=>{...localStorage...})()")
    state = {"cookies": cookies, "localStorage": localStorage}
    (cache_dir/"browser_state.json").write_text(json.dumps(state))
    # 另存 instsci-cookies.json + Netscape .txt（供 requests / CloakBrowser 导入）

def _restore_state(self, config):           # 重启后 add_cookies + 逐 origin 写回 localStorage
```

**(b) `open_login_browser`**：可见隐身浏览器交互式登录，**自动检测登录完成**（URL 不再含 login/cas/sso/wayf/saml/idp，或自定义 `detect_login` 回调），完成即抓 cookie → JSON + Netscape → 自动导入 CloakBrowser。`keep_alive=True` 可返回 context/page 继续用。

**(c) `extract_via_browser`（browser_cookies.py）**：更简的「等用户关窗」式捕获，含 **OneTrust 等 consent 弹窗自动点掉**，按 `PUBLISHER_DOMAINS` 过滤出版商 cookie，`merge_cookies` 按 `(name,domain,path)` 去重合并。

### 2.3 认证流（browser_login.py）—— 每出版商一份 cookie

```python
def webvpn_login(config):   # → open_login_browser(webvpn_base, max_wait=600)
def carsi_login(publisher, config, *, login_url, domains):
    cookie_file = cache_dir/"carsi_cookies"/f"{publisher}.json"    # 每社独立
    def _detect(ctx, page):  # 落在出版商域且不在登录域 → 判定成功
        return any(d in page.url for d in domains) and not any(x in page.url.lower()
                   for x in ("login","institutional","wayf","saml","cas","idp"))
def ezproxy_login(config):  # login_url 用 {url} 占位注入目标站
```
> 关键：**per-publisher cookie 文件**（`carsi_cookies/{publisher}.json`）——与本项目「按域注入」天然契合。

### 2.4 长存会话 broker（session_broker.py）—— 一次登录多篇

- 每出版商一个常驻 CloakBrowser 子进程（`session-broker-run` CLI），文件队列投递 DOI 批任务（`{job}.json` → `{job}.done.json` 轮询），TTL + 心跳 + stop 文件 + pid 存活检测。
- **`BrokerState` 只存 publisher/profile_dir/pid/queue/ttl，不存任何 cookie 值**（cookie 全在持久化 Profile 里）——安全设计。
- 对应竞速引擎的「批级 Phase 2 按出版商分组一次登录」（见《选型2026-scansci竞速引擎源码架构与并行化改造》§3.6）。

### 2.5 运行时兼容（cloakbrowser_compat.py）

- 把 CloakBrowser 缓存指向项目自管目录（`CLOAKBROWSER_CACHE_DIR`）。
- **Windows 平台补丁**：当 `platform.machine()` 为空时补 `("Windows","")→windows-x64`，否则 CloakBrowser 平台探测失败。**本项目在 Windows，必带**。

### 2.6 安全设计原则（与 instsci 一致，务必沿用）

- **绝不存密码**：SSO/2FA/CAPTCHA 全在可见浏览器由用户完成。
- cookie/localStorage 仅本地持久化（JSON + Netscape）；broker 状态不含 cookie 值。
- 开放 API / OA 域名永不注入机构 cookie（防会话外泄）——本项目 `http_client._OPEN_ACCESS_HOSTS` 已有此防线，保留。
- 每社独立 cookie 文件，过期自动失效。

---

## 三、本项目现状对照（`http_client.py`）

| 能力 | 本项目现状 | scansci/instsci |
|------|-----------|-----------------|
| 机构总开关 / OA 域名豁免 | ✅ `needs_institution_access` + `_OPEN_ACCESS_HOSTS` | ✅ |
| EZproxy URL 重写 | ✅ 前缀式（form 1）；hostname 式 TODO | ✅ ezproxy_login + 重写 |
| Cookie 来源 | ⚠️ **单一静态 `institution_cookie` 串**（手工粘） | ✅ 浏览器登录自动捕获 |
| 按出版商持久化 | ❌ | ✅ `carsi_cookies/{publisher}.json` |
| 过期校验 | ❌ | ✅ `CookieStore._is_valid` |
| localStorage 持久化 | ❌ | ✅ `browser_state.json` |
| 一次登录多篇复用 | ❌ | ✅ PersistentBrowser / broker |
| CloakBrowser 交互登录 | ❌ | ✅ `open_login_browser` + 自动检测 |
| Windows 兼容补丁 | ❌ | ✅ `cloakbrowser_compat` |

本项目相关骨架（保留、在其上扩展）：

```
http_client.py:
  needs_institution_access(host, cfg)  # OA 豁免 + 白名单，默认关 → 恒 False
  rewrite_url_for_proxy(url, cfg)      # EZproxy 前缀重写（form 1）
  request(): if needs_institution_access: headers={"Cookie": cfg.institution_cookie,...}; url=rewrite(...)
config.py: institutional / ezproxy_prefix / institution_cookie / institution_domains
```

---

## 四、给 141 的落地建议

### 4.1 P0：`CookieStore` + 浏览器登录，把「单串」升级为「按域取」

- **新增** `fulltext_fetcher/institutional/cookie_store.py`：原样移植 `CookieStore`（零依赖、附离线 selftest）。cookie 存 `out/.institution/cookies/{publisher_or_domain}.json`。
- **新增** `fulltext_fetcher/institutional/login.py`：移植 `open_login_browser`（CloakBrowser 可选依赖，未装则明确报错并降级），入口 `institution_login(identifier|publisher)`；用登录自动检测（URL 脱离 login/cas/sso）。
- **改 `http_client.request`**：把「注入单一 `institution_cookie` 串」改为「**按目标域从 CookieStore 取该域 cookie 注入**」，`institution_cookie` 保留为手工兜底（二者并存，显式 headers 优先）：

```python
if needs_institution_access(host, self.cfg):
    jar = self._cookie_store_for(host)      # 按域/出版商载入持久化 cookie（过期已过滤）
    cookie_hdr = "; ".join(f"{c['name']}={c['value']}" for c in jar) or getattr(self.cfg,"institution_cookie",None)
    if cookie_hdr:
        headers = {"Cookie": cookie_hdr, **(headers or {})}
    url = rewrite_url_for_proxy(url, self.cfg)
```

### 4.2 P1：每社 cookie + merge/dedup + localStorage

- 按出版商域名分文件（对齐 §4.1 catalog 的 `carsi_cookie_dir/{publisher}.json` 约定），`merge_cookies` 去重（name,domain,path）+ 过期过滤。
- 需要时持久化 localStorage（`browser_state.json`），登录复用时写回——部分 Atypon/SSO 站把登录态放 localStorage。

### 4.3 P2：PersistentBrowser / 会话 broker（一次登录多篇）

- `PersistentBrowser` 单例：批量下载期间登录一次、复用浏览器，配合竞速引擎「批级 Phase 2 按出版商分组」。broker 版可选（重，收益在超大批量）。

### 4.4 依赖与兼容

- CloakBrowser 为**可选依赖**（`pip install cloakbrowser`）：未装时机构浏览器路径降级、纯 HTTP+静态 cookie 仍可用。
- **务必移植 `cloakbrowser_compat` 的 Windows 平台补丁**（本项目 Windows 环境）。
- 复用本项目既有 `download.py` 的 `%PDF` 校验：机构 cookie 失效时直链返回 401/403/HTML，被自动过滤，不产假成功。

### 4.5 模块划分建议

```
fulltext_fetcher/institutional/
  __init__.py
  cookie_store.py      # CookieStore（移植 session_store.py）
  login.py             # open_login_browser + webvpn/carsi/ezproxy_login
  cloak_compat.py      # cloakbrowser_compat（Windows 补丁）
  broker.py            # (P2) 长存会话 broker
# http_client.py 仅新增「按域取 cookie」接线，主体不动
```

---

## 五、安全与合规（必须写进实现）

- 仅供拥有**合法机构订阅**、对相应内容**有权访问**的用户，在授权前提下经机构 EZproxy/SSO 正常取用全文；不得绕过付费墙。
- **绝不存密码**；SSO/2FA/CAPTCHA 全在可见浏览器完成。
- 机构 cookie 只注入白名单/出版商域，OA/开放 API 域名永不注入（`_OPEN_ACCESS_HOSTS` 防线保留）。
- 持久化文件（cookies/localStorage）落本地、进 `.gitignore`；broker 状态不含 cookie 值。

---

## 六、给总指挥（147）/ 组员 141 的落地建议

1. **P0 直接采纳**：`CookieStore` 移植 + `open_login_browser` + `http_client` 按域取 cookie 接线。低风险（默认关、OA 豁免不变、%PDF 兜底）。
2. **P1**：每社 cookie 文件 + merge/dedup + localStorage 持久化；对齐 §「出版商访问目录」的 `carsi_cookie_dir/{publisher}.json` 约定。
3. **P2**：PersistentBrowser / broker，一次登录多篇，与竞速引擎批级 Phase 2 协同（142 另一份文档）。
4. **协同**：本文件可由 142 通过 `send_to_session` 直送 141 供实现参考——待工作组恢复后执行；141 若已开工，建议就「cookie 存储路径/命名、http_client 接线点」与 142 对齐后再动手。

---

## 参考

- scansci-pdf @ master：`session_store.py`（CookieStore）、`browser_login.py`（PersistentBrowser / open_login_browser / webvpn·carsi·ezproxy_login）、`browser_cookies.py`（extract_via_browser / merge_cookies / Netscape）、`session_broker.py`（长存 broker）、`cloakbrowser_compat.py`（Windows 补丁）。
- 本项目：`fulltext_fetcher/http_client.py`（`needs_institution_access` / `rewrite_url_for_proxy` / `request` 机构接线）、`config.py`（`institutional` / `ezproxy_prefix` / `institution_cookie` / `institution_domains`）。

> 本文档为智库检索成果，判断基于 2026-07-02 的 scansci master 源码与本项目当时代码；实现须遵守合规声明，默认关闭、对开放 API 零副作用。
