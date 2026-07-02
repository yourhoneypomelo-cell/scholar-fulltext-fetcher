# 路线A · 机构订阅实测 Runbook(凭据到手后照做 3 步)

> **⛔ 归档状态(2026-07-02,总指挥定板)**:用户明确**无机构订阅凭据**,路线A 就此封存——
> 本 runbook 与 20 条实测清单**永远 gate、不启动任何联网实测**,留档待将来万一有凭据直接照做。
>
> 适用:拥有**合法机构订阅**(高校/科研机构图书馆)的用户,对其**有权访问**的内容。
> 现状:代码侧已全部就绪(`--institutional` 开关 + EZproxy 双模式改写(前缀式/主机名式自动识别,
> 实现于 `fulltext_fetcher/ezproxy.py`、经 http_client 委托接入主路径)+ Cookie 注入 + 401 优雅拦截)。
> **唯一 gate = 用户提供机构凭据**。没有凭据时以下直链必 401/403,由 `%PDF` 校验拦截,不产假成功。
> 合规红线:凭据仅限本人合法持有;严禁系统性超量批量下载(出版商 ToS);凭据绝不入 git/日志/产物。

---

## 第 0 步(一次性):从浏览器拿到你的机构凭据

三选一(按你机构的接入方式;不确定就问图书馆"校外访问电子资源怎么配"):

### 方式 A:EZproxy(最常见,高校图书馆"校外访问"入口)

1. 浏览器打开图书馆的数据库列表,点任意 ScienceDirect 链接——若跳到形如
   `https://login.ezproxy.你校.edu/login?url=https://www.sciencedirect.com/...` 的地址,
   说明是**前缀式**:取 `?url=` 之前的整段(含 `login?url=`)作为 `EZPROXY_PREFIX`。
2. 若登录后地址栏变成 `www-sciencedirect-com.ezproxy.你校.edu/...`(域名里嵌横杠),
   说明是**主机名改写式**:`EZPROXY_PREFIX` 只填裸代理域,如 `ezproxy.你校.edu`。
   (程序自动识别两种形式:含 `://` 或 `=` 按前缀式拼接;裸域名按主机名改写式。
   实现:`fulltext_fetcher/ezproxy.py`,已经 `http_client.rewrite_url_for_proxy` 委托接入主路径,
   与 143 的 curl_cffi 改造对齐后合入,离线单测 EZPROXY_OK。)
3. 完成一次 EZproxy 登录,然后导出 Cookie(见下面"Cookie 导出 how-to"),
   把 **ezproxy 域名下**的 Cookie(常见名 `ezproxy`/`EZProxy`)填入 `INSTITUTION_COOKIE`。

### 方式 B:出版商 SSO/Shibboleth 直连(无 EZproxy 时)

1. 浏览器直接开 `sciencedirect.com` → 右上角 Sign in → "Sign in via your institution" 走校内账号登录。
2. 登录成功后导出 **www.sciencedirect.com 域下**的全部 Cookie 填入 `INSTITUTION_COOKIE`;
   `EZPROXY_PREFIX` 留空。注意 SSO Cookie 按出版商域隔离:测哪家导哪家的。

### 方式 C:校园网 IP 白名单(人在校内/连校 VPN)

- 无需任何 Cookie/前缀:直接跳到第 2 步跑命令即可(`--institutional` 仍要开,
  它负责把 publisher_direct 直链源接进来;IP 授权由网络层自动生效)。

### Cookie 导出 how-to(Chrome/Edge 通用,1 分钟)

1. 在**已登录**的页面按 F12 → 顶栏 `Application`(应用)→ 左栏 `Storage → Cookies` → 选中当前站点。
2. 把要用的每行 Cookie 拼成一个字符串:`名1=值1; 名2=值2`(分号+空格分隔)。
   - EZproxy:通常只需 `ezproxy=...` 一条;SSO:建议整域全导(省得漏会话字段)。
3. 会话 Cookie 有时效(数小时~数天),401 复现时重新登录再导一次即可。
   - 更快的办法:装浏览器扩展 "Cookie-Editor",打开站点 → Export → Header String,直接得到上述格式。

---

## 第 1 步:配置凭据(PowerShell,只进环境变量,不留 shell 历史/不进 git)

```powershell
# 二选一按你的接入方式;方式 C(校园网)两条都可跳过
$env:EZPROXY_PREFIX     = "https://login.ezproxy.你校.edu/login?url="   # 前缀式;主机名式填 "ezproxy.你校.edu"
$env:INSTITUTION_COOKIE = "ezproxy=粘贴你的值"                            # 从浏览器导出的 Cookie 串
```

## 第 2 步:3 条冒烟(90 秒判死活)

```powershell
python -m fulltext_fetcher "10.1016/j.apcata.2005.04.024" "10.1016/j.apcata.2007.03.021" "10.1006/jcat.1993.1276" `
  --institutional --institution-domain "sciencedirect.com,linkinghub.elsevier.com" `
  --email 你的邮箱@你校.edu -o out_inst_smoke3 --no-resume
```

判读:
- 成功 ≥1 → 凭据有效,直接进第 3 步;
- 全部 `http-401/403` → 凭据无效/过期/白名单没覆盖:回第 0 步重导 Cookie,或确认该刊在你校订阅范围;
- `not-pdf(head='<html'...)` → 拿到的是登录页而非 PDF(Cookie 缺会话字段):整域重导 Cookie。
- ⚠️ `--institution-domain` 必填:白名单为空时程序**保守不改写任何域名**(防止把无关流量导进代理)。

## 第 3 步:20 条 Elsevier 正式冒烟 → 再放量

```powershell
# 20 条(本仓已备好输入清单 recover_a_inst_elsevier20_input.txt)
python -m fulltext_fetcher -f recover_a_inst_elsevier20_input.txt `
  --institutional --institution-domain "sciencedirect.com,linkinghub.elsevier.com" `
  --email 你的邮箱@你校.edu -o out_inst_els20 -c 2 --per-host-interval 1.0

# 判读:out_inst_els20/summary.json 的 success 数;attempts.jsonl 里 http-401 占比。
# 20 条成功率 ≥70% → 放量到整个分片(344 条,务必保持 -c 2 + 1s 间隔的礼貌节奏):
python -m fulltext_fetcher -f out/still_missing_shards/elsevier.txt `
  --institutional --institution-domain "sciencedirect.com,linkinghub.elsevier.com" `
  --email 你的邮箱@你校.edu -o out_inst_els_full -c 2 --per-host-interval 1.0
# 其余出版商分片同理换白名单:acs.txt → pubs.acs.org;rsc.txt → pubs.rsc.org;
# springer.txt → link.springer.com;wiley.txt → onlinelibrary.wiley.com
```

---

## 常见问答

- **问:凭据会被记到哪?** 答:只存在于当前 PowerShell 会话的环境变量与请求头;
  不写 `metadata.jsonl` / `attempts.jsonl` / `summary.json` / 日志;仓库 `.gitignore` 外不落任何凭据文件。
- **问:为什么必须 `--institutional`?** 答:它把订阅出版商直链源 `publisher_direct` 接入源顺序;
  不开则根本不构造 ScienceDirect 直链,Cookie 配了也没请求可用。
- **问:Cookie 与 EZproxy 前缀要同时给吗?** 答:EZproxy 用户两个都给(前缀改写 URL + Cookie 带登录态);
  SSO 直连用户只给 Cookie;校园网 IP 用户都不用给。
