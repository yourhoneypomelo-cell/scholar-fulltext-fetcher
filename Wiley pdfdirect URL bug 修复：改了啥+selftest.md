# Wiley pdfdirect URL bug 修复：改了啥 + selftest

> 交付：**谷歌学术人机认证-174**｜task-3a1d3e38｜2026-07-03  
> 问题：遗留 Wiley DOI（含 `()` `:` `<` `>` `;` 等）构造 `onlinelibrary.wiley.com/doi/pdfdirect/…` 时**未 encode 后缀**，浏览器/HTTP 栈把 `:` 等当路径分界 → **404 / 截断**（用户实证 `10.1002/1099-0739(200012)14:12…`）。

---

## 改了啥

**策略**：保留 `prefix/suffix` 间 `/` 不编码；对 **suffix 整段** `urllib.parse.quote(suffix, safe="")`。

| 文件 | 变更 |
|---|---|
| `fulltext_fetcher/sources/publisher_oa.py` | 新增 `_wiley_doi_path()`；`_wiley_openonline` 同时产出 **pdfdirect + pdf** 两链，均用 encoded path |
| `fulltext_fetcher/sources/publisher_direct.py` | 新增 `_wiley_doi_path()`；Wiley 模板填充时用 encoded DOI |
| `fulltext_fetcher/publisher_adapter.py` | 新增 `_wiley_doi_path()`；`pdf_candidates()` 对 `key==wiley` encode |

**示例**（legacy DOI）：

```
输入: 10.1002/1099-0739(200012)14:12<836::AID-AOC97>3.0.CO;2-C
输出: https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/1099-0739%28200012%2914%3A12%3C836%3A%3AAID-AOC97%3E3.0.CO%3B2-C
```

现代 DOI（无特殊字符）**不变**：`10.1002/adma.202000000` 仍为明文路径。

---

## selftest

三模块均新增 legacy Wiley 断言；离线通过：

```powershell
python -m fulltext_fetcher.sources.publisher_oa      # PUBLISHER_OA_OK
python -m fulltext_fetcher.sources.publisher_direct # PUBLISHER_DIRECT_OK
python -m fulltext_fetcher.publisher_adapter        # PUBLISHER_ADAPTER_OK
python -m compileall -q fulltext_fetcher            # exit 0
```

---

## 未改

- `render_fetch.py` / coverage / `run_all.py`（按派单避撞）
- 未做真网下载验证（离线 URL 构造 + selftest 即可）

---

*174｜纯 bugfix，非人机验证。*
