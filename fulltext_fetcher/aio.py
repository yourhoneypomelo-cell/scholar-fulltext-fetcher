"""可选异步并发批量抓取原型（OA 路线图 C4）——纯新增、独立;同步核心 100% 不变。

用途:对大批量(数千条)OA 元数据 / 定位请求,用 httpx.AsyncClient(或 aiohttp)做**有界并发**,
提升吞吐。本模块只负责「并发调度 + 异步 HTTP 取回 + 结果结构与同步 FetchResult 兼容」;
解析/源思路**只读复用**父包纯函数(resolve.classify_input 等),**绝不改**同步核心
(http_client / pipeline / download / sources / cli / __main__)。

依赖:httpx 或 aiohttp 均为**可选依赖、函数内延迟导入**;两者都缺时优雅报不可用
——`async_status()` 返回 `{"available": False, "reason": "need httpx/aiohttp"}`,
`fetch_many_async(..., _fetch=None)` 抛 `AsyncUnavailable`(其 `.info` 即该信封)。不进强制依赖。

Benchmark / 选型说明(定性,供决策):
  - 同步路径(pipeline + ThreadPoolExecutor,默认并发 4–8 + 按域限速):受线程数/阻塞 IO 制约;
    对「定位」阶段(海量小 JSON API 调用)扩展性有限,但对「下载」阶段(大体积 PDF)线程池够用。
  - 异步路径(单事件循环 + AsyncClient + `Semaphore(max_concurrency)`):同等礼貌下,「定位」阶段
    并发可拉到数十~上百,数千条时吞吐显著优于线程池;连接/HTTP2 keep-alive 复用更省握手开销。
  - 结论:**大批量「定位 / 元数据」用异步(本模块)**;**实际 PDF 下载仍走同步核心**
    (稳、可控,已有 %PDF 校验与落地页二次抽链)。异步同样必须礼貌:mailto + 有界并发 +
    (生产再加)每域节流,避免给公共 OA API 造成压力。

自检:python -m fulltext_fetcher.aio  → 不联网 selftest(mock 异步取回),打印 AIO_OK。
"""
from __future__ import annotations

import asyncio
import importlib.util
from typing import Any, Awaitable, Callable, List, Optional

from .models import FetchResult
from .resolve import classify_input

_UNAVAILABLE_REASON = "need httpx/aiohttp"

# 每条输入的异步取回协程签名:async fn(raw, cfg, http_client) -> FetchResult
FetchOne = Callable[[str, Any, Any], Awaitable[FetchResult]]


class AsyncUnavailable(RuntimeError):
    """无可用异步 HTTP 引擎(httpx / aiohttp 均未安装)时抛出;`.info` 为统一不可用信封。"""

    def __init__(self, reason: str = _UNAVAILABLE_REASON) -> None:
        super().__init__(reason)
        self.info = {"available": False, "reason": reason}


def async_status() -> dict:
    """探测异步引擎可用性(仅 find_spec,不导入执行)→ {available, engine} 或 {available, reason}。"""
    for name in ("httpx", "aiohttp"):
        try:
            if importlib.util.find_spec(name) is not None:
                return {"available": True, "engine": name}
        except (ImportError, ValueError):
            continue
    return {"available": False, "reason": _UNAVAILABLE_REASON}


async def fetch_many_async(inputs, cfg, *, max_concurrency: int = 8,
                           _fetch: Optional[FetchOne] = None,
                           _client: Any = None) -> List[FetchResult]:
    """有界并发异步批量抓取 → List[FetchResult](顺序与输入一致)。

    - `max_concurrency`:并发上限(asyncio.Semaphore 约束,即礼貌阀门)。
    - `_fetch`:注入的每条异步取回协程(测试/自定义);None → 用内建 httpx 定位实现。
    - `_client`:注入的异步 client(测试);None 且需真实实现时惰性建 httpx.AsyncClient。
    - 无 httpx/aiohttp 且未注入 `_fetch` → 抛 `AsyncUnavailable`(携带 {available:False, reason})。
    单条异常被吞成失败 FetchResult(error 前缀 `aio-error`),绝不拖垮整批。
    """
    items = list(inputs or [])
    if not items:
        return []
    n = max(1, int(max_concurrency or 1))

    fetch = _fetch
    client = _client
    own_client = False
    if fetch is None:
        if not async_status().get("available"):
            raise AsyncUnavailable()
        fetch = _httpx_locate_fetch
        if client is None:
            client = _new_httpx_client(cfg)
            own_client = True

    sem = asyncio.Semaphore(n)
    results: List[Optional[FetchResult]] = [None] * len(items)

    async def _worker(i: int, raw: str) -> None:
        async with sem:
            try:
                results[i] = await fetch(raw, cfg, client)
            except Exception as e:  # noqa: BLE001 - 单条异常降级为失败 FetchResult
                results[i] = FetchResult(raw_input=raw, error=f"aio-error: {e}")

    try:
        await asyncio.gather(*[_worker(i, raw) for i, raw in enumerate(items)])
    finally:
        if own_client and client is not None:
            aclose = getattr(client, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:  # noqa: BLE001
                    pass

    return [r if r is not None else FetchResult(raw_input=items[i], error="aio-missing")
            for i, r in enumerate(results)]


def run_async_batch(inputs, cfg, *, max_concurrency: int = 8) -> List[FetchResult]:
    """同步便捷入口:内部 `asyncio.run(fetch_many_async(...))`;缺库抛 AsyncUnavailable。"""
    return asyncio.run(fetch_many_async(inputs, cfg, max_concurrency=max_concurrency))


def _new_httpx_client(cfg: Any):
    """惰性建 httpx.AsyncClient(缺库 → AsyncUnavailable)。礼貌 UA / 超时取自 cfg。"""
    try:
        import httpx  # 可选依赖,函数内延迟导入
    except ImportError:
        raise AsyncUnavailable()
    timeout = float(getattr(cfg, "timeout", 30.0) or 30.0)
    ua = getattr(cfg, "ua", None)
    headers = {"User-Agent": ua() if callable(ua) else "fulltext_fetcher-aio/1.0"}
    return httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True)


async def _httpx_locate_fetch(raw: str, cfg: Any, client: Any) -> FetchResult:
    """内建异步「定位」实现:DOI → Unpaywall best_oa_location 查 OA 直链(仅定位,不下载)。

    真实网络路径(离线 selftest 不覆盖):解析输入 → DOI 则异步查 Unpaywall → 命中即
    success + pdf_url;非 DOI 从略(原型聚焦吞吐评估)。下载仍交同步核心。
    """
    wi = classify_input(raw)
    fr = FetchResult(raw_input=raw, kind=wi.kind)
    if wi.kind != "doi":
        fr.error = "aio-prototype: non-DOI locate not implemented"
        return fr
    fr.doi = wi.value
    email = getattr(cfg, "email", None) or "anonymous@example.com"
    try:
        r = await client.get(f"https://api.unpaywall.org/v2/{wi.value}", params={"email": email})
        if getattr(r, "status_code", None) == 200:
            data = r.json()
            loc = (data or {}).get("best_oa_location") or {}
            url = loc.get("url_for_pdf") or loc.get("url")
            if url:
                fr.success, fr.pdf_url, fr.source_used = True, url, "unpaywall(aio)"
                return fr
        fr.error = f"aio-locate-miss(http-{getattr(r, 'status_code', '?')})"
    except Exception as e:  # noqa: BLE001
        fr.error = f"aio-locate-error: {e}"
    return fr


# ────────────────────────── 不联网 selftest ──────────────────────────
def _selftest() -> int:
    from types import SimpleNamespace

    cfg = SimpleNamespace(email="selftest@example.org", timeout=30.0)

    # ① async_status 结构正确;不可用时 reason 规范
    st = async_status()
    assert isinstance(st, dict) and isinstance(st.get("available"), bool), st
    if not st["available"]:
        assert st["reason"] == _UNAVAILABLE_REASON, st

    # ② 有界并发调度:注入 fake 协程,断言峰值并发 == max_concurrency、顺序保持、结构兼容
    def _make_probe():
        state = {"active": 0, "peak": 0}

        async def _probe(raw: str, _cfg: Any, _client: Any) -> FetchResult:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            await asyncio.sleep(0.01)          # 让出事件循环,促成交错
            state["active"] -= 1
            return FetchResult(raw_input=raw, kind="doi", success=True,
                               source_used="fake", pdf_url="u:" + raw)
        return _probe, state

    inputs = [f"10.1/{i}" for i in range(10)]
    probe, state = _make_probe()
    res = asyncio.run(fetch_many_async(inputs, cfg, max_concurrency=4, _fetch=probe))
    assert len(res) == 10 and all(isinstance(r, FetchResult) for r in res), res
    assert [r.raw_input for r in res] == inputs, "顺序必须与输入一致"
    assert all(r.success and r.pdf_url == "u:" + r.raw_input for r in res), res
    assert state["peak"] == 4, ("峰值并发应达上限 4", state["peak"])
    assert hasattr(res[0], "to_dict") and res[0].to_dict()["raw_input"] == "10.1/0"

    # ③ max_concurrency=1 → 串行(峰值 1)
    probe1, state1 = _make_probe()
    r1 = asyncio.run(fetch_many_async(["a", "b", "c"], cfg, max_concurrency=1, _fetch=probe1))
    assert len(r1) == 3 and state1["peak"] == 1, state1

    # ④ 单条异常 → 降级为失败 FetchResult(不抛、不拖垮整批)
    async def _boom(raw: str, _cfg: Any, _client: Any) -> FetchResult:
        raise RuntimeError("kaboom")
    rb = asyncio.run(fetch_many_async(["x", "y"], cfg, max_concurrency=2, _fetch=_boom))
    assert len(rb) == 2 and all((not r.success) and "aio-error" in (r.error or "") for r in rb), rb

    # ⑤ 空输入 → []
    assert asyncio.run(fetch_many_async([], cfg)) == []

    # ⑥ 缺库优雅降级:强制 async_status 不可用 → fetch_many_async(_fetch=None) 抛 AsyncUnavailable。
    # 注:直接改本模块 globals(fetch_many_async 与 async_status 同模块,全局查找即命中),
    # 避免 `python -m` 下 __main__ 与 fulltext_fetcher.aio 是两个模块副本导致 patch 落空(且不触网)。
    _saved = globals()["async_status"]
    globals()["async_status"] = lambda: {"available": False, "reason": _UNAVAILABLE_REASON}
    try:
        raised = False
        try:
            asyncio.run(fetch_many_async(["10.1/x"], cfg))
        except AsyncUnavailable as e:
            raised = True
            assert e.info == {"available": False, "reason": "need httpx/aiohttp"}, e.info
        assert raised, "无异步引擎时应抛 AsyncUnavailable"
    finally:
        globals()["async_status"] = _saved

    # ⑦ 内建 DOI 定位实现:注入 fake httpx 响应(不联网),断言命中 Unpaywall best_oa_location
    class _Resp:
        status_code = 200

        def json(self):
            return {"best_oa_location": {"url_for_pdf": "https://oa.example.org/x.pdf"}}

    class _Client:
        async def get(self, url, params=None):     # 对齐 httpx.AsyncClient.get
            return _Resp()

    fr = asyncio.run(_httpx_locate_fetch("10.1000/abc", cfg, _Client()))
    assert fr.success and fr.pdf_url == "https://oa.example.org/x.pdf", fr
    assert fr.source_used == "unpaywall(aio)" and fr.doi == "10.1000/abc", fr
    # 非 DOI → 原型未实现定位
    fr2 = asyncio.run(_httpx_locate_fetch("Some Free Title", cfg, _Client()))
    assert (not fr2.success) and "non-DOI" in (fr2.error or ""), fr2

    print("AIO_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
