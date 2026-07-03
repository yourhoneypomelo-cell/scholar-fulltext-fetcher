# A5 机构订阅框架 · CLI 接入与 route-B 契约（-174）

## 交付范围（task-9eea4f30）

机制无关的 A5 层已就绪，本波仅做 **框架接入**，不实现 SSO 浏览器登录（`-153`）与 `render_fetch` 注入（`-141`）。

| 模块 | 路径 | 职责 |
|------|------|------|
| 凭据加载 | `fulltext_fetcher/institutional/credential_store.py` | `FTF_*` env + `.ftf_institutional.local.json` |
| Cookie 持久化 | `fulltext_fetcher/institutional/cookie_store.py` | JSON + 过期 |
| 会话 | `fulltext_fetcher/institutional/auth_session.py` | `AuthSession`、`bootstrap_institutional_config()` |
| route-B 契约 | `fulltext_fetcher/institutional/route_b_bridge.py` | `RouteBInjectionPlan`、`plan_route_b_injection()` |
| 示例配置 | `.ftf_institutional.local.json.example` | 复制为 `.ftf_institutional.local.json`，勿提交 git |
| 离线自检 | `fulltext_fetcher/institutional/selftest_a5_framework.py` | 打印 `A5_FRAMEWORK_OK` |

## 启动接入（本波新增）

- **`cli.py`**：`Config` 构造后调用 `bootstrap_institutional_config(cfg, cli_institutional=args.institutional)`；CLI 已填字段优先，不被 FTF 覆盖。
- **`run_all.py`**：同上；若凭据启用机构模式则自动插入 `publisher_direct` 源（与 CLI 行为一致）。

启用方式（任选其一）：

1. `--institutional` + `INSTITUTION_COOKIE` / `EZPROXY_PREFIX`（旧口径）
2. `FTF_INSTITUTIONAL=1` + `FTF_INSTITUTION_COOKIE` / `FTF_EZPROXY_PREFIX` / `FTF_INSTITUTION_DOMAINS`
3. 项目根 `.ftf_institutional.local.json`（`enabled: true`）

## route-B 注入契约（属主 -141）

`plan_route_b_injection(session, url, user_agent=...)` 返回纯数据计划；`inject_institutional_session(tab, plan, cdp=...)` 文档化 hook，**本包不修改 `render_fetch.py`**。

## 自检

```bash
python -m fulltext_fetcher.institutional.selftest_a5_framework
# → A5_FRAMEWORK_OK
```

## 未做（刻意留后续）

- `open_login_browser()` → `-153` nodriver 可见 SSO
- `verify_live(client=...)` 联网探针 → `-153`
- `run_all.py` 透传 `--institutional` 旗标（可随 A5 实装一并加；当前靠 FTF env/文件即可）
