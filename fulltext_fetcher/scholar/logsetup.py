"""日志:直接复用父包 `fulltext_fetcher.logsetup`(setup_logging + EventLog JSONL),
并补充本子包的结构化事件名常量(见《谷歌学术爬虫-架构与选型.md》§6)。

复用而非重造:产物目录结构、run.log 格式、EventLog 线程安全 JSONL 写入均与父包一致,
下游各模块统一 `from .logsetup import setup_logging, EventLog` 与事件名常量,避免漂移。
"""
from __future__ import annotations

# re-export 父包实现(单一真源)
from ..logsetup import EventLog, setup_logging  # noqa: F401

# ── Scholar 结构化事件名(§6)——各模块 events.emit(<EVENT>, **fields) 统一使用 ──
EVENT_QUERY = "query"                # raw, kind, q
EVENT_SERP_FETCH = "serp_fetch"      # url, engine, ok, blocked, captcha, proxy, ms
EVENT_SERP_PARSED = "serp_parsed"    # n, has_next
EVENT_BLOCK = "block"                # url, engine, reason
EVENT_CAPTCHA = "captcha"            # provider, ok
EVENT_PROXY_ROTATE = "proxy_rotate"  # from, to, reason
EVENT_DOWNLOAD = "download"          # url, ok, bytes, error
EVENT_OA_FALLBACK = "oa_fallback"    # source, ok
EVENT_RESULT = "result"              # success, source, cited_by, ms, error

SCHOLAR_EVENTS = frozenset({
    EVENT_QUERY, EVENT_SERP_FETCH, EVENT_SERP_PARSED, EVENT_BLOCK, EVENT_CAPTCHA,
    EVENT_PROXY_ROTATE, EVENT_DOWNLOAD, EVENT_OA_FALLBACK, EVENT_RESULT,
})

__all__ = [
    "setup_logging", "EventLog",
    "EVENT_QUERY", "EVENT_SERP_FETCH", "EVENT_SERP_PARSED", "EVENT_BLOCK",
    "EVENT_CAPTCHA", "EVENT_PROXY_ROTATE", "EVENT_DOWNLOAD", "EVENT_OA_FALLBACK",
    "EVENT_RESULT", "SCHOLAR_EVENTS",
]


if __name__ == "__main__":  # 不联网 selftest: python -m fulltext_fetcher.scholar.logsetup
    import json
    import os
    import tempfile

    # —— re-export 可用:setup_logging 返回 logger、EventLog 可写 JSONL ——
    assert callable(setup_logging) and callable(EventLog)

    # —— 事件名常量齐全且唯一 ——
    assert EVENT_SERP_FETCH == "serp_fetch" and EVENT_RESULT == "result"
    assert len(SCHOLAR_EVENTS) == 9, SCHOLAR_EVENTS
    assert EVENT_QUERY in SCHOLAR_EVENTS and EVENT_OA_FALLBACK in SCHOLAR_EVENTS

    # —— EventLog 端到端(临时目录):emit → 读回一行 JSON,含 ts/event/自定义字段 ——
    # 注:Windows 下须先关闭 run.log 的 FileHandler 再清理临时目录,否则文件占用无法删除。
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        log = setup_logging(d, "INFO")
        try:
            log.info("scholar logsetup selftest")
            assert os.path.exists(os.path.join(d, "run.log"))

            ev_path = os.path.join(d, "attempts.jsonl")
            ev = EventLog(ev_path)
            ev.emit(EVENT_SERP_FETCH, url="https://scholar.example/q", engine="curl_cffi",
                    ok=True, blocked=False, ms=12)
            ev.close()
            with open(ev_path, "r", encoding="utf-8") as f:
                rec = json.loads(f.readline())
            assert rec["event"] == "serp_fetch" and rec["engine"] == "curl_cffi"
            assert rec["ok"] is True and "ts" in rec
        finally:
            for h in list(log.handlers):
                try:
                    h.close()
                except Exception:
                    pass
                log.removeHandler(h)

    print("LOGSETUP_OK")
