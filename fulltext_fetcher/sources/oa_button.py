"""oa.works(前 OpenAccess Button)免费全文发现 API 连接器 —— 按 DOI/标题找可用全文 URL。

接口(自包含,返回 List[str]):
    find_pdf_candidates(doi, title=None, cfg=None) -> list[str]

────────────────────────────────────────────────────────────────────────────
端点核实(2026-07-01 联网核实)
- 历史端点:`GET https://api.oa.works/find?id={DOI}`(id 亦可传 title/url/pmid/pmcid;别名 q)。
  返回 JSON 形如 {"url": "...", "paywall": ...?, "metadata": {...}};其中顶层 `url` 为最佳 OA
  全文链接(源码 find.coffee 里由 best_oa_location.pdf_url / url_for_pdf / url / landing_page_url
  或 EuropePMC 全文列表推导),`metadata` 携带书目信息,并在可得时带 Unpaywall 风格的
  best_oa_location / oa_locations。
- ⚠️ 现状:**该服务已于 2025-11-18 永久停用**(oaworks/api 源码 find.coffee 命中 shutdown 分支
  直接返回 HTTP 410 "This API has been permanently shut down",此前有 503 灰度公告)。
  证据:https://blog.oa.works/sunsetting-the-open-access-button-instantill/ ;本机 live 探测亦超时。
- 因此对公共端点的实时调用会拿到非 200(410)→ 本连接器**优雅返回 []**(与 CORE 无 key 时同理)。
  代码保留完整解析逻辑,便于:① 指向自建的开源 oaworks/api 实例;② 服务若恢复即可用。
  可用 `cfg.oa_button_endpoint` 覆盖为自建端点(默认仍为官方 find 端点)。

约定:失败一律优雅跳过(吞异常、返回 []),绝不抛出影响其它源;仅用标准库 + requests(延迟导入)。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

_DEFAULT_ENDPOINT = "https://api.oa.works/find"
_TIMEOUT = 20.0


def _cfg_get(cfg: Any, name: str, default: Any = None) -> Any:
    return getattr(cfg, name, default) if cfg is not None else default


def _endpoint(cfg: Any) -> str:
    return _cfg_get(cfg, "oa_button_endpoint", None) or _DEFAULT_ENDPOINT


def _user_agent(cfg: Any) -> str:
    email = _cfg_get(cfg, "email", None)
    if email:
        return f"fulltext_fetcher/1.0 (mailto:{email})"
    return "fulltext_fetcher/1.0"


def _fetch_find(ident: str, cfg: Any = None) -> Optional[Dict[str, Any]]:
    """向 oa.works /find 发一次 GET,返回解析后的 JSON(dict)或 None。全程吞异常、绝不抛出。

    非 200(含服务停用后的 410)、网络异常、非 JSON、缺 requests → 一律 None(调用方按无候选处理)。
    """
    try:
        import requests  # 延迟导入:未装 requests 也不致 import 本模块即失败
    except ImportError:
        return None
    params: Dict[str, Any] = {"id": ident}
    email = _cfg_get(cfg, "email", None)
    if email:
        params["email"] = email
    try:
        r = requests.get(
            _endpoint(cfg), params=params,
            headers={"User-Agent": _user_agent(cfg)},
            timeout=_cfg_get(cfg, "timeout", _TIMEOUT) or _TIMEOUT,
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:  # noqa: BLE001 — 网络/解析任何异常都视为「无候选」优雅跳过
        return None


def _extract_candidates(data: Any) -> List[str]:
    """从 /find 响应中提取候选全文 URL(PDF 直链优先,落地页其后);去重、保序、仅 http(s)。"""
    if not isinstance(data, dict):
        return []
    out: List[str] = []

    def add(u: Any) -> None:
        if isinstance(u, str):
            u = u.strip()
            if u.startswith(("http://", "https://")) and u not in out:
                out.append(u)

    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    boa = meta.get("best_oa_location") if isinstance(meta.get("best_oa_location"), dict) else {}
    locs = [loc for loc in (meta.get("oa_locations") or []) if isinstance(loc, dict)]

    # ① PDF 直链优先(pdf_url / url_for_pdf,遍历 top-level / metadata / best_oa / oa_locations)
    for src in (data, meta, boa, *locs):
        add(src.get("pdf_url"))
        add(src.get("url_for_pdf"))
    # ② 其次:通用 OA 全文 URL / 落地页(顶层 url 是 oa.works 主输出)
    add(data.get("url"))
    for src in (boa, meta, *locs):
        add(src.get("url"))
        add(src.get("landing_page_url"))
    return out


def find_pdf_candidates(doi: Optional[str], title: Optional[str] = None,
                        cfg: Any = None, *, _fetch: Any = None) -> List[str]:
    """按 DOI(优先)或标题向 oa.works /find 查可用全文,返回候选 URL 列表(List[str])。

    失败(端点停用/网络/无结果)→ []。`_fetch` 仅供离线 selftest 注入假取回器,勿在生产传入。
    """
    ident = (doi or title or "").strip()
    if not ident:
        return []
    fetch = _fetch or _fetch_find
    return _extract_candidates(fetch(ident, cfg))


if __name__ == "__main__":  # 不联网 selftest: python -m fulltext_fetcher.sources.oa_button
    # 历史 /find 响应形态:顶层 url + metadata(含 Unpaywall 风格 OA 定位)
    mock = {
        "url": "https://europepmc.org/articles/PMC12345",
        "paywall": False,
        "metadata": {
            "doi": "10.1/x", "title": "T",
            "best_oa_location": {
                "pdf_url": "https://pub.org/best.pdf",
                "url": "https://pub.org/best",
                "landing_page_url": "https://pub.org/landing",
            },
            "oa_locations": [
                {"url_for_pdf": "https://a.org/a.pdf", "url": "https://a.org/a"},
                {"url": "https://b.org/landing"},
            ],
        },
    }
    cands = _extract_candidates(mock)
    # PDF 直链在前
    assert "https://pub.org/best.pdf" in cands and "https://a.org/a.pdf" in cands, cands
    assert "https://europepmc.org/articles/PMC12345" in cands, cands
    assert "https://b.org/landing" in cands, cands
    assert len(cands) == len(set(cands)), cands                       # 去重
    assert cands.index("https://a.org/a.pdf") < cands.index("https://b.org/landing"), cands  # 直链优先

    # 顶层仅 url
    assert _extract_candidates({"url": "https://x.org/p.pdf"}) == ["https://x.org/p.pdf"]
    # 空 / 异常 / 非 http 输入 → 安全
    assert _extract_candidates(None) == [] and _extract_candidates({}) == []
    assert _extract_candidates({"url": "ftp://no"}) == []

    # 端到端(注入假取回器,不联网):命中
    got = find_pdf_candidates("10.1/x", _fetch=lambda ident, cfg: mock)
    assert "https://pub.org/best.pdf" in got, got
    # 端点停用/网络失败(取回 None)→ 优雅 []
    assert find_pdf_candidates("10.1/x", _fetch=lambda ident, cfg: None) == []
    # 无 DOI 无标题 → [](且不触发任何取回)
    assert find_pdf_candidates(None, None) == []
    # 仅标题也可作为 id 查询
    assert find_pdf_candidates(None, "some title",
                               _fetch=lambda ident, cfg: {"url": "https://t.org/x.pdf"}) == \
        ["https://t.org/x.pdf"]

    print("OA_BUTTON_OK")
