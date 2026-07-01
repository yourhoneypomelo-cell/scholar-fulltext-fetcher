"""FlareSolverr 客户端:借免费自托管 FlareSolverr 代解 Cloudflare JS 挑战。

出版商站点与镜像站常用 Cloudflare("Just a moment..." / JS 质询 / Turnstile)拦截直连。
FlareSolverr 是一个免费、开源、可 docker 自托管的代理:它用真实无头浏览器访问目标、
自动通过挑战,再把最终 HTML + cookies + userAgent 返回。本模块是它的最小 HTTP 客户端,
供 fetcher 在常规引擎被 Cloudflare 挡住时兜底取回页面。

启动 FlareSolverr(docker):
    docker run -d --name flaresolverr \
        -p 8191:8191 \
        -e LOG_LEVEL=info \
        --restart unless-stopped \
        ghcr.io/flaresolverr/flaresolverr:latest
    # 健康检查:curl http://localhost:8191/  → "FlareSolverr is ready!"
    # 调用示例:POST http://localhost:8191/v1
    #   {"cmd": "request.get", "url": "https://example.com", "maxTimeout": 60000}

端点通过环境变量 FLARESOLVERR_URL 配置(默认 http://localhost:8191;可含或不含 /v1);
也可经 cfg.flaresolverr_url 覆盖。未配置 / 连不上 / 超时 / 非 ok 响应时,本模块**优雅返回
None 并记日志,绝不抛异常、绝不阻断主流程**(默认即"未启用"→直接 None)。

对外接口:
    fetch_via_flaresolverr(url, cfg=None) -> Optional[str]      # 成功返回 HTML,否则 None
    solve(url, cfg=None) -> Optional[dict]                       # 额外拿 cookies / userAgent

纯标准库(urllib)。selftest(mock HTTP,不联网):python -m fulltext_fetcher.flaresolverr
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

FLARESOLVERR_URL_ENV = "FLARESOLVERR_URL"
_DEFAULT_BASE = "http://localhost:8191"
_DEFAULT_MAX_TIMEOUT_MS = 60000
_HTTP_TIMEOUT_BUFFER_S = 15.0  # HTTP 读超时 = maxTimeout/1000 + 该缓冲(留浏览器+网络余量)


def _endpoint(cfg: Any = None) -> str:
    """解析 FlareSolverr /v1 端点:cfg.flaresolverr_url > env FLARESOLVERR_URL > 默认。"""
    base = (getattr(cfg, "flaresolverr_url", None)
            or os.environ.get(FLARESOLVERR_URL_ENV)
            or _DEFAULT_BASE)
    base = (base or "").strip().rstrip("/") or _DEFAULT_BASE
    return base if base.endswith("/v1") else base + "/v1"


def _max_timeout_ms(cfg: Any = None) -> int:
    """浏览器侧最大等待(毫秒):cfg.flaresolverr_timeout_ms > 默认 60000。"""
    v = getattr(cfg, "flaresolverr_timeout_ms", None)
    try:
        v = int(v)
        return v if v > 0 else _DEFAULT_MAX_TIMEOUT_MS
    except (TypeError, ValueError):
        return _DEFAULT_MAX_TIMEOUT_MS


def _post_json(endpoint: str, payload: Dict[str, Any], timeout: float) -> Optional[Dict[str, Any]]:
    """POST JSON 到 endpoint 并解析返回 dict;任何网络/解析错误 → None(不抛)。

    单独抽出便于 selftest mock;也是"连不上即优雅降级"的唯一网络出口。
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=data, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
        parsed = json.loads(body)
        return parsed if isinstance(parsed, dict) else None
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.warning("FlareSolverr 请求失败(端点未启用/连不上/超时) endpoint=%s err=%s", endpoint, e)
        return None


def solve(url: str, cfg: Any = None) -> Optional[Dict[str, Any]]:
    """经 FlareSolverr 解挑战并取回结构化结果;失败一律返回 None(不抛)。

    返回 {"html", "cookies", "user_agent", "url", "status_code"};其中 html 为过挑战后的
    最终页面源码,cookies 可用于后续带 cookie 直连以复用会话。
    """
    if not url:
        return None
    endpoint = _endpoint(cfg)
    max_ms = _max_timeout_ms(cfg)
    payload = {"cmd": "request.get", "url": url, "maxTimeout": max_ms}
    http_timeout = max_ms / 1000.0 + _HTTP_TIMEOUT_BUFFER_S

    resp = _post_json(endpoint, payload, http_timeout)
    if not isinstance(resp, dict):
        return None
    if (resp.get("status") or "").lower() != "ok":
        log.warning("FlareSolverr 非 ok 响应:status=%s message=%s",
                    resp.get("status"), resp.get("message"))
        return None
    solution = resp.get("solution")
    if not isinstance(solution, dict):
        log.warning("FlareSolverr 响应缺少 solution 对象")
        return None
    html = solution.get("response")
    if not html:
        log.warning("FlareSolverr solution.response 为空")
        return None
    return {
        "html": html,
        "cookies": solution.get("cookies") or [],
        "user_agent": solution.get("userAgent"),
        "url": solution.get("url") or url,
        "status_code": solution.get("status"),
    }


def fetch_via_flaresolverr(url: str, cfg: Any = None) -> Optional[str]:
    """经 FlareSolverr 取回 url 过 Cloudflare 挑战后的最终 HTML;失败返回 None(绝不抛)。"""
    sol = solve(url, cfg)
    return sol["html"] if sol else None


if __name__ == "__main__":  # mock HTTP selftest(不联网): python -m fulltext_fetcher.flaresolverr
    logging.disable(logging.CRITICAL)  # 静音失败路径的 warning,保持 selftest 输出干净

    _OK_RESP = {
        "status": "ok",
        "message": "Challenge solved!",
        "solution": {
            "url": "https://example.com/",
            "status": 200,
            "response": "<html>solved</html>",
            "cookies": [{"name": "cf_clearance", "value": "abc123"}],
            "userAgent": "Mozilla/5.0 (X11) HeadlessChrome/120",
        },
    }
    captured: Dict[str, Any] = {}

    def _fake_ok(endpoint, payload, timeout):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        captured["timeout"] = timeout
        return dict(_OK_RESP)

    _real_post_json = _post_json

    # —— ① 默认端点 + 请求体正确 + 返回 HTML ——
    _post_json = _fake_ok
    assert fetch_via_flaresolverr("https://example.com/") == "<html>solved</html>"
    assert captured["endpoint"] == "http://localhost:8191/v1", captured["endpoint"]
    assert captured["payload"] == {
        "cmd": "request.get", "url": "https://example.com/", "maxTimeout": 60000,
    }, captured["payload"]
    assert captured["timeout"] == 60000 / 1000.0 + 15.0, captured["timeout"]

    # —— ② solve 额外返回 cookies / user_agent / status_code ——
    sol = solve("https://example.com/")
    assert sol["html"] == "<html>solved</html>"
    assert sol["cookies"] == [{"name": "cf_clearance", "value": "abc123"}]
    assert sol["user_agent"].startswith("Mozilla") and sol["status_code"] == 200

    # —— ③ cfg 覆盖端点 + maxTimeout ——
    class _Cfg:
        flaresolverr_url = "http://fs.local:9000"
        flaresolverr_timeout_ms = 30000

    fetch_via_flaresolverr("https://x/", _Cfg())
    assert captured["endpoint"] == "http://fs.local:9000/v1", captured["endpoint"]
    assert captured["payload"]["maxTimeout"] == 30000, captured["payload"]

    # —— ④ 端点解析:env 覆盖 + 已带 /v1 不重复 + 默认 ——
    _saved = os.environ.pop(FLARESOLVERR_URL_ENV, None)
    try:
        assert _endpoint() == "http://localhost:8191/v1"
        os.environ[FLARESOLVERR_URL_ENV] = "http://envhost:8191/v1"
        assert _endpoint() == "http://envhost:8191/v1"        # 不重复追加 /v1
        os.environ[FLARESOLVERR_URL_ENV] = "http://envhost:7000/"
        assert _endpoint() == "http://envhost:7000/v1"        # 追加 /v1
    finally:
        os.environ.pop(FLARESOLVERR_URL_ENV, None)
        if _saved is not None:
            os.environ[FLARESOLVERR_URL_ENV] = _saved

    # —— ⑤ 各类失败响应 → None(不抛) ——
    _post_json = lambda e, p, t: {"status": "error", "message": "Cloudflare challenge failed"}
    assert fetch_via_flaresolverr("https://x/") is None            # 非 ok
    _post_json = lambda e, p, t: {"status": "ok", "solution": {}}   # 缺 response
    assert fetch_via_flaresolverr("https://x/") is None
    _post_json = lambda e, p, t: {"status": "ok"}                   # 缺 solution
    assert fetch_via_flaresolverr("https://x/") is None
    _post_json = lambda e, p, t: None                              # 网络层失败
    assert fetch_via_flaresolverr("https://x/") is None

    # —— ⑥ 空 url → None(不发请求)——
    assert fetch_via_flaresolverr("") is None and solve(None) is None

    # —— ⑦ 真实错误处理:urlopen 抛 URLError → _post_json 捕获返回 None(绝不崩)——
    _post_json = _real_post_json
    _orig_urlopen = urllib.request.urlopen

    def _boom(*a, **k):
        raise urllib.error.URLError("connection refused")

    urllib.request.urlopen = _boom
    try:
        assert fetch_via_flaresolverr("https://x/") is None
    finally:
        urllib.request.urlopen = _orig_urlopen

    print("FLARESOLVERR_OK")
