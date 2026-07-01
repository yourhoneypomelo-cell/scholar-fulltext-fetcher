"""代理池（翼A，默认关=直连）。见《谷歌学术爬虫-架构与选型.md》§3.6 / §4。

合规缺省:代理默认关闭(`proxy_enabled=False`)即**直连**;仅当用户显式提供住宅代理池
(`cfg.proxy_pool` 或环境变量 `SCHOLAR_PROXIES`)且启用时才轮换使用。命中风控时由上层
调用 `rotate()` 换 IP、`report_block()` 拉黑失效代理。纯标准库、无第三方依赖。

契约(ARCH §3.6):`ProxyPool.available/current/rotate/report_block` + `load_proxy_pool(cfg)`。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set

PROXIES_ENV = "SCHOLAR_PROXIES"


class ProxyPool:
    """住宅代理池:轮换 + 拉黑。默认关(`enabled=False`)或空池 → `available()=False`(直连)。

    - `available()`：是否有可用代理(已启用且至少一个未被拉黑)。
    - `current()`：当前代理 URL(如 `http://user:pass@host:port`)或 `None`(直连)。
    - `rotate()`：轮换到下一个未拉黑代理并返回(命中风控/到达轮换阈值时调用);无可用 → `None`。
    - `report_block(proxy)`：标记该代理被封 → 从轮换中剔除(拉黑降权);对 `None`/不在池内的项无副作用。
    """

    def __init__(self, proxies: Optional[List[str]] = None, enabled: bool = False) -> None:
        seen: Set[str] = set()
        order: List[str] = []
        for raw in (proxies or []):
            p = (raw or "").strip()
            if p and p not in seen:      # 去重保序
                seen.add(p)
                order.append(p)
        self._order: List[str] = order
        self._enabled: bool = bool(enabled)
        self._blocked: Set[str] = set()
        self._pos: int = 0

    def _has_active(self) -> bool:
        return any(p not in self._blocked for p in self._order)

    def available(self) -> bool:
        return self._enabled and self._has_active()

    def current(self) -> Optional[str]:
        if not self.available():
            return None
        n = len(self._order)
        for i in range(n):               # 从 _pos 起找首个未拉黑者(只读，不推进)
            cand = self._order[(self._pos + i) % n]
            if cand not in self._blocked:
                return cand
        return None

    def rotate(self) -> Optional[str]:
        if not self.available():
            return None
        n = len(self._order)
        for i in range(1, n + 1):        # 从 _pos 之后找下一个未拉黑者并推进
            j = (self._pos + i) % n
            cand = self._order[j]
            if cand not in self._blocked:
                self._pos = j
                return cand
        return None

    def report_block(self, proxy: Optional[str]) -> None:
        if proxy and proxy in self._order:
            self._blocked.add(proxy)

    def stats(self) -> Dict[str, Any]:   # 供日志/调试
        return {
            "enabled": self._enabled,
            "total": len(self._order),
            "blocked": len(self._blocked),
            "active": sum(1 for p in self._order if p not in self._blocked),
        }


def load_proxy_pool(cfg: Any) -> ProxyPool:
    """按配置装配代理池。

    来源优先级(**复用 `config.proxies_effective()` 作单一真源**):`cfg.proxy_pool` 非空则取之,
    否则读环境变量 `SCHOLAR_PROXIES`(逗号分隔、去空白空项)。该方法缺失时回退等价的鸭子类型解析,
    使本模块不硬依赖 config 的具体实现。**空池 → 禁用(直连)**;`proxy_enabled=False` 亦为直连。
    """
    enabled = bool(getattr(cfg, "proxy_enabled", False))
    eff = getattr(cfg, "proxies_effective", None)
    if callable(eff):
        proxies = list(eff() or [])
    else:
        proxies = list(getattr(cfg, "proxy_pool", None) or [])
        if not proxies:
            raw = os.environ.get(PROXIES_ENV) or ""
            proxies = [p.strip() for p in raw.split(",") if p.strip()]
    if not proxies:                       # 空池 → 直连
        enabled = False
    return ProxyPool(proxies, enabled)


if __name__ == "__main__":  # 不联网 selftest: python -m fulltext_fetcher.scholar.proxy
    import types

    def _cfg(enabled: bool, pool: List[str], *, with_eff: bool = True) -> Any:
        """构造 ScholarConfig-like 假配置;with_eff 决定是否带 proxies_effective(测两条装配路径)。"""
        ns = types.SimpleNamespace(proxy_enabled=enabled, proxy_pool=list(pool))
        if with_eff:
            def _eff(_pool: List[str] = list(pool)) -> List[str]:
                if _pool:
                    return list(_pool)
                raw = os.environ.get(PROXIES_ENV) or ""
                return [p.strip() for p in raw.split(",") if p.strip()]
            ns.proxies_effective = _eff
        return ns

    A, B, C = "http://a:1", "http://b:2", "http://c:3"

    # ① 默认关 / 空池 → 直连
    p = load_proxy_pool(_cfg(False, []))
    assert p.available() is False and p.current() is None and p.rotate() is None, "disabled → direct"

    # proxy_enabled=True 但空池且无 env → 强制直连
    os.environ.pop(PROXIES_ENV, None)
    assert load_proxy_pool(_cfg(True, [])).available() is False, "empty pool → direct"

    # ② 给定池 → 轮换顺序(round-robin, 保序)
    p = load_proxy_pool(_cfg(True, [A, B, C]))
    assert p.available() is True
    assert p.current() == A, p.current()
    assert p.rotate() == B and p.rotate() == C and p.rotate() == A, "round-robin wrap"

    # ③ report_block → 拉黑剔除, 轮换跳过被封
    p.report_block(B)
    assert p.current() == A                        # 仍在 A
    assert p.rotate() == C                         # 跳过 B → C
    assert p.rotate() == A                         # 回到 A
    assert p.stats()["blocked"] == 1 and p.stats()["active"] == 2

    # ④ 全部拉黑 → available False, 直连
    p.report_block(A)
    p.report_block(C)
    assert p.available() is False and p.current() is None and p.rotate() is None, "all blocked → direct"

    # ⑤ report_block 容错:None / 不在池内 → 无副作用
    q = load_proxy_pool(_cfg(True, [A, B]))
    q.report_block(None)
    q.report_block("http://not-in-pool:9")
    assert q.stats()["blocked"] == 0 and q.available() is True

    # ⑥ 去重保序:重复项只保留一个
    d = load_proxy_pool(_cfg(True, [A, A, B, A]))
    assert d.current() == A and d.rotate() == B and d.rotate() == A, "dedup preserve order"

    # ⑦ env 回退(proxies_effective 路径):cfg.proxy_pool 空 → 读 SCHOLAR_PROXIES(去空白/空项/重复)
    os.environ[PROXIES_ENV] = " http://x:1 , http://y:2 ,, http://x:1 "
    pe = load_proxy_pool(_cfg(True, []))
    assert pe.current() == "http://x:1" and pe.rotate() == "http://y:2" and pe.rotate() == "http://x:1"
    os.environ.pop(PROXIES_ENV, None)

    # ⑧ 鸭子类型回退路径(cfg 无 proxies_effective):pool 与 env 均支持
    assert load_proxy_pool(_cfg(True, [A, B], with_eff=False)).current() == A
    os.environ[PROXIES_ENV] = "http://z:1"
    assert load_proxy_pool(_cfg(True, [], with_eff=False)).current() == "http://z:1"
    os.environ.pop(PROXIES_ENV, None)

    # ⑨ 与真实 ScholarConfig(P0)集成对齐;config 未就绪则跳过,不影响 PROXY_OK
    try:
        from .config import ScholarConfig
    except ImportError:
        ScholarConfig = None  # type: ignore[assignment]
    if ScholarConfig is not None:
        _saved = os.environ.pop(PROXIES_ENV, None)
        try:
            assert load_proxy_pool(ScholarConfig()).available() is False           # 默认关 → 直连
            rp = load_proxy_pool(ScholarConfig(proxy_enabled=True, proxy_pool=[A, B]))
            assert rp.available() is True and rp.current() == A and rp.rotate() == B
            os.environ[PROXIES_ENV] = "http://e:1"
            assert load_proxy_pool(ScholarConfig(proxy_enabled=True)).current() == "http://e:1"
        finally:
            os.environ.pop(PROXIES_ENV, None)
            if _saved is not None:
                os.environ[PROXIES_ENV] = _saved

    print("PROXY_OK")
