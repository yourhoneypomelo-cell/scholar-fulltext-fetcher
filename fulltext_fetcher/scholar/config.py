"""子包运行配置（冻结契约，见《谷歌学术爬虫-架构与选型.md》§3.2 与 §4 默认值）。

所有可调参数集中在此；默认值刻意偏保守、以「避免触发」为纲：代理 / 打码 / Sci-Hub
默认全关，Scholar 抓取默认串行 + 强限速。契约一旦冻结不得擅改。
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

SERPAPI_KEY_ENV = "SERPAPI_KEY"
PROXIES_ENV = "SCHOLAR_PROXIES"


@dataclass
class ScholarConfig:
    """fulltext_fetcher/scholar 的全部运行参数。"""

    # —— 模式 —— 'serpapi'(商业合规) | 'self'(自建反爬) | 'auto'(有 key 走 serpapi 否则 self)
    mode: str = "auto"
    serpapi_key: Optional[str] = None              # 回落环境变量 SERPAPI_KEY

    # —— 自建取回：引擎降级顺序 ——
    engine_order: List[str] = field(default_factory=lambda: ["curl_cffi", "nodriver"])
    impersonate: str = "chrome"                    # curl_cffi impersonate 目标
    browser_engine: str = "nodriver"              # 'nodriver'|'patchright'|'seleniumbase'
    user_agent: str = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    # ↑ requests 降级取回时的 UA;curl_cffi 用 impersonate 自带匹配指纹,不用此值。默认与 fetcher._UA 一致。

    # —— SERP 结果选择 ——
    min_title_score: float = 0.2                    # _select_best 最低标题相似度(Jaccard);最高分低于此值 → 回退 SERP 第一条(信任 Google 相关性序，避免模糊标题误选不相关结果)

    # —— 限速/退避/冷却（合规、避免触发；默认偏保守，见 §4）——
    page_interval_low: float = 45.0                # 两次 Scholar 页请求最小抖动下界(秒)
    page_interval_high: float = 90.0              # 抖动上界(秒)
    rotate_ip_every_low: int = 5                   # 每 N 次请求换 IP/会话(下界)
    rotate_ip_every_high: int = 15                # (上界)
    backoff_base: float = 2.0                      # 指数退避底
    backoff_cap: float = 60.0                      # 单次退避上限(秒)
    cooldown_after_block: float = 900.0           # 命中风控后冷却(秒, 默认 15min)
    max_retries: int = 3
    timeout: float = 30.0

    # —— 翼A 代理（默认关=直连）——
    proxy_enabled: bool = False
    proxy_pool: List[str] = field(default_factory=list)   # 或经 env SCHOLAR_PROXIES

    # —— 翼B 打码（默认关）——
    captcha_enabled: bool = False
    captcha_provider: Optional[str] = None         # '2captcha'|'capsolver'
    captcha_key: Optional[str] = None

    # —— 下载 / 兜底 ——
    oa_fallback: bool = False                      # 默认关=纯 Scholar；仅 --oa-fallback 显式开启才用父包 OA 源兜底
    enable_scihub: bool = False                    # 合规风险, 默认关
    min_pdf_bytes: int = 1024
    max_pdf_bytes: int = 80 * 1024 * 1024

    # —— 批量/输出 ——
    out_dir: str = "out_scholar"
    concurrency: int = 1                           # Scholar 抓取默认串行(强合规)
    num: int = 10
    year_low: Optional[int] = None
    year_high: Optional[int] = None
    resume: bool = True
    naming_template: str = "{year}_{author}_{title}"
    email: str = "anonymous@example.com"           # 供 OA 兜底(Unpaywall 需真实邮箱)
    log_level: str = "INFO"

    # ── 便捷方法(不改字段语义，仅封装 env 回退与派生判断)──────────────────────
    def serpapi_key_effective(self) -> Optional[str]:
        """SerpApi key:显式配置优先，否则回落环境变量 SERPAPI_KEY。"""
        return self.serpapi_key or os.environ.get(SERPAPI_KEY_ENV)

    def proxies_effective(self) -> List[str]:
        """代理池:显式 proxy_pool 优先，否则读环境变量 SCHOLAR_PROXIES(逗号分隔)。"""
        if self.proxy_pool:
            return list(self.proxy_pool)
        raw = os.environ.get(PROXIES_ENV) or ""
        return [p.strip() for p in raw.split(",") if p.strip()]

    def resolved_mode(self) -> str:
        """把 'auto' 落地为实际模式:有 SerpApi key → 'serpapi',否则 'self'。"""
        if self.mode != "auto":
            return self.mode
        return "serpapi" if self.serpapi_key_effective() else "self"

    def email_is_placeholder(self) -> bool:
        e = (self.email or "").lower()
        return (not e) or e.startswith("anonymous@") or e.endswith("@example.com")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


if __name__ == "__main__":  # 不联网 selftest: python -m fulltext_fetcher.scholar.config
    c = ScholarConfig()
    # —— §3.2/§4 关键默认值 ——
    assert c.mode == "auto"
    assert c.engine_order == ["curl_cffi", "nodriver"]
    assert c.impersonate == "chrome" and c.browser_engine == "nodriver"
    assert c.user_agent.startswith("Mozilla/5.0") and "Chrome/" in c.user_agent
    assert c.min_title_score == 0.2
    assert c.page_interval_low == 45.0 and c.page_interval_high == 90.0
    assert c.rotate_ip_every_low == 5 and c.rotate_ip_every_high == 15
    assert c.backoff_base == 2.0 and c.backoff_cap == 60.0
    assert c.cooldown_after_block == 900.0
    assert c.proxy_enabled is False and c.captcha_enabled is False
    assert c.oa_fallback is False and c.enable_scihub is False
    assert c.out_dir == "out_scholar" and c.concurrency == 1
    assert c.naming_template == "{year}_{author}_{title}"
    assert c.min_pdf_bytes == 1024 and c.max_pdf_bytes == 80 * 1024 * 1024
    assert c.to_dict()["mode"] == "auto"

    # 可变默认独立
    c.engine_order.append("patchright")
    assert ScholarConfig().engine_order == ["curl_cffi", "nodriver"]

    # —— env 回退与派生模式(用临时环境变量，测完还原)——
    _saved_key = os.environ.pop(SERPAPI_KEY_ENV, None)
    _saved_px = os.environ.pop(PROXIES_ENV, None)
    try:
        assert ScholarConfig().serpapi_key_effective() is None
        assert ScholarConfig().resolved_mode() == "self"          # auto 无 key → self
        os.environ[SERPAPI_KEY_ENV] = "K"
        assert ScholarConfig().serpapi_key_effective() == "K"
        assert ScholarConfig().resolved_mode() == "serpapi"       # auto 有 key → serpapi
        assert ScholarConfig(mode="self").resolved_mode() == "self"  # 显式模式不被覆盖
        assert ScholarConfig(serpapi_key="X").serpapi_key_effective() == "X"  # 显式优先
        os.environ[PROXIES_ENV] = "http://a:1, http://b:2 ,"
        assert ScholarConfig().proxies_effective() == ["http://a:1", "http://b:2"]
        assert ScholarConfig(proxy_pool=["http://c:3"]).proxies_effective() == ["http://c:3"]
    finally:
        os.environ.pop(SERPAPI_KEY_ENV, None)
        os.environ.pop(PROXIES_ENV, None)
        if _saved_key is not None:
            os.environ[SERPAPI_KEY_ENV] = _saved_key
        if _saved_px is not None:
            os.environ[PROXIES_ENV] = _saved_px

    assert ScholarConfig().email_is_placeholder() is True
    assert ScholarConfig(email="me@uni.edu").email_is_placeholder() is False

    print("CONFIG_OK")
