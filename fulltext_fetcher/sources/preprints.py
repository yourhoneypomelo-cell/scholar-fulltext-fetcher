"""化学/材料类预印本服务器全文发现:ChemRxiv / Research Square / Preprints.org。

用途:本项目语料以催化/化工/材料为主,作者常把同一工作的预印本版发在**化学类预印本服务器**上。
既有 `repositories.py` 覆盖了 arXiv / bioRxiv·medRxiv,但缺化学类预印本;本模块补齐这一真实缺口:
给定(已发表论文的)DOI + 标题,尽力找到其**预印本 PDF 直链**。

发现策略(能按 DOI 直定就直定,否则按标题搜公开 API):
- **输入 DOI 本身就是预印本 DOI** → 直接定位:
    · ChemRxiv(前缀 10.26434)→ 调 ChemRxiv 公开 API 取 asset 直链;
    · Research Square(10.21203,新式 rs.3.rs-<id>/v<n>)→ 由 id/版本构造 PDF 直链;
    · Preprints.org(10.20944,preprints<YYYYMM>.<NNNN>.v<V>)→ 构造 /download 直链。
- **按标题找预印本版**(已发表论文的 DOI 属出版商,故主路径是标题检索):
    · 主路径 **Crossref**(公开 API):按标题检索 `type:posted-content`,过滤到三家的 DOI 前缀
      (10.26434 / 10.21203 / 10.20944)——RS/Preprints.org 由 DOI 构造 PDF 直链,ChemRxiv 命中的
      DOI 再经 cambridge.org 回补取 asset 直链。快、稳、一次调用覆盖三家。
    · 可选 ChemRxiv 原生 term 检索 `…/public-api/v1/items?term=<标题>`:**默认关闭**
      (chemrxiv.org 常被 Cloudflare 拦且慢,发现能力已被 Crossref 覆盖);
      置 `cfg.preprints_use_chemrxiv_search=True` 显式开启。标题一律模糊匹配以避免张冠李戴。

实网核实(2026-07-01):chemrxiv.org 被 Cloudflare 拦(403 challenge),故 ChemRxiv 的 DOI 精确查
优先走同后端镜像 cambridge.org(稳定 200,asset.original.url 为可下载 PDF,已核实);Research Square
新式 DOI 构造的 `…/vN.pdf` 已核实可下载;Preprints.org 的 `…/download` 亦受 Cloudflare 保护,直链正确
但需项目的浏览器/flaresolverr 取回层才能落地(本模块仅产候选,不负责下载)。

对外接口(与其它免费模块对齐,返回 List[str]):
    find_pdf_candidates(doi, title=None, cfg=None) -> list[str]

设计约束(遵循本项目免费模块约定):
- 纯逻辑 + 离线 selftest;**不 @register**、**不改** sources/__init__.py 与 free_adapters.py
  (集成由总指挥统一做,参照 oa_button.py / websearch.py)。
- 可选依赖 `requests` **函数内延迟导入**;缺库 / 网络异常 / 非 200 / 非 JSON → 一律优雅降级返回 []。
- 绝不抛异常拖垮其它源;URL 去重保序、仅 http(s)。
- 离线纯解析/构造逻辑自带 selftest(注入假取回器,不联网),打印 PREPRINTS_OK。

config(可选,均非必需;无则用默认):
    cfg.email                          —— 若提供则用于 Crossref/ChemRxiv 的 mailto UA(更礼貌、更少限流)。
    cfg.timeout                        —— 单次请求超时秒数(默认 20)。
    cfg.preprints_use_chemrxiv_search  —— True 则额外启用 ChemRxiv 原生 term 检索(默认 False)。
"""
from __future__ import annotations

import difflib
import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

# ── 预印本服务器 DOI 前缀 ──
_PREFIX_CHEMRXIV = "10.26434"
_PREFIX_RESEARCHSQUARE = "10.21203"
_PREFIX_PREPRINTS_ORG = "10.20944"
_PREPRINT_PREFIXES = (_PREFIX_CHEMRXIV, _PREFIX_RESEARCHSQUARE, _PREFIX_PREPRINTS_ORG)

# ChemRxiv 走 Cambridge Open Engage 后端。chemrxiv.org 常被 Cloudflare 拦(403 challenge),
# cambridge.org 为同后端镜像且对脚本稳定可达 → DOI 精确查优先用它。
_CHEMRXIV_DOI_BASES = (
    "https://www.cambridge.org/engage/coe/public-api/v1",     # 稳定:DOI 精确查
    "https://chemrxiv.org/engage/chemrxiv/public-api/v1",     # 原生备用
)
# term 关键词检索仅用 chemrxiv.org 原生端点:其 term 为 ChemRxiv 范围内相关性检索;而 cambridge.org
# 的 coe 端点 term 跨社区且非相关性排序(易出无关项),故标题检索不用它,交由 Crossref 兜底。
_CHEMRXIV_SEARCH_BASES = (
    "https://chemrxiv.org/engage/chemrxiv/public-api/v1",
)
_CROSSREF_WORKS = "https://api.crossref.org/works"

_TIMEOUT = 20.0
_UA_BASE = "fulltext_fetcher/1.0"

_DOI_URL_RE = re.compile(r"(?i)^\s*(?:https?://(?:dx\.)?doi\.org/|doi:)\s*")
_TAG_RE = re.compile(r"<[^>]+>")
_NONALNUM_RE = re.compile(r"[^a-z0-9]+")
_WS_RE = re.compile(r"\s+")

# Research Square 新式 DOI:10.21203/rs.3.rs-<id>/v<n>(文章 id 即 rs-<id>,可直构 PDF)
_RS_NEW_RE = re.compile(r"(?i)rs\.3\.(rs-\d+)(?:/v(\d+))?")
# Preprints.org DOI:10.20944/preprints<YYYYMM>.<NNNN>.v<V>
_PREPRINTS_RE = re.compile(r"(?i)preprints(\d{6})\.(\d+)(?:\.v(\d+))?")

_Get = Callable[[str, Optional[Dict[str, Any]], Any], Optional[Any]]


# ────────────────────────── 通用工具(纯函数)──────────────────────────
def _cfg_get(cfg: Any, name: str, default: Any = None) -> Any:
    return getattr(cfg, name, default) if cfg is not None else default


def _normalize_doi(doi: Any) -> str:
    if not doi:
        return ""
    return _DOI_URL_RE.sub("", str(doi).strip()).strip().rstrip(".,);")


def _doi_prefix(d: str) -> str:
    return d.split("/", 1)[0] if "/" in d else ""


def _norm_title(t: Any) -> str:
    if not t:
        return ""
    s = _TAG_RE.sub(" ", str(t)).lower()
    return _WS_RE.sub(" ", _NONALNUM_RE.sub(" ", s)).strip()


def _title_match(a: Any, b: Any, threshold: float = 0.86) -> bool:
    """标题模糊匹配:归一(去 HTML/标点、小写)后相等 / 互相包含 / 相似度≥阈值。"""
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb or len(na) < 8 or len(nb) < 8:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= threshold


# ────────────────────────── HTTP(requests 延迟导入,绝不抛)──────────────────────────
def _user_agent(cfg: Any) -> str:
    email = _cfg_get(cfg, "email", None)
    return f"{_UA_BASE} (mailto:{email})" if email else _UA_BASE


def _http_get_json(url: str, params: Optional[Dict[str, Any]] = None,
                   cfg: Any = None) -> Optional[Any]:
    """GET 一次并解析 JSON。缺 requests / 非 200 / 网络或解析异常 → None(优雅降级)。"""
    try:
        import requests  # 可选依赖:函数内延迟导入
    except ImportError:
        return None
    try:
        r = requests.get(
            url, params=params,
            headers={"User-Agent": _user_agent(cfg), "Accept": "application/json"},
            timeout=_cfg_get(cfg, "timeout", _TIMEOUT) or _TIMEOUT,
        )
        if getattr(r, "status_code", None) != 200:
            return None
        return r.json()
    except Exception:  # noqa: BLE001 — 网络/解析异常一律视为无结果
        return None


# ────────────────────────── ChemRxiv(原生公开 API)──────────────────────────
def _chemrxiv_asset_urls(item: Any) -> List[str]:
    """从 ChemRxiv item 提取 PDF 直链:asset.original.url,退化到 asset.url。"""
    if not isinstance(item, dict):
        return []
    asset = item.get("asset")
    if not isinstance(asset, dict):
        return []
    orig = asset.get("original")
    if isinstance(orig, dict) and isinstance(orig.get("url"), str):
        return [orig["url"]]
    if isinstance(asset.get("url"), str):
        return [asset["url"]]
    return []


def _chemrxiv_item_from_payload(data: Any) -> Any:
    """/items/doi/{doi} 返回 {"item": {...}} 或直接 {...}。"""
    if isinstance(data, dict):
        return data.get("item") if isinstance(data.get("item"), dict) else data
    return None


def chemrxiv_by_doi(doi: str, cfg: Any, get: _Get) -> List[str]:
    d = _normalize_doi(doi)
    if not d:
        return []
    # DOI 里的 '/' 必须保留(端点按原样 DOI 匹配;编码成 %2F 会 404)。
    path = quote(d, safe="/")
    for base in _CHEMRXIV_DOI_BASES:
        data = get(f"{base}/items/doi/{path}", None, cfg)
        urls = _chemrxiv_asset_urls(_chemrxiv_item_from_payload(data))
        if urls:
            return urls
    return []


def chemrxiv_by_title(title: str, cfg: Any, get: _Get, limit: int = 6) -> List[str]:
    if not title:
        return []
    for base in _CHEMRXIV_SEARCH_BASES:
        data = get(f"{base}/items", {"term": title, "limit": limit}, cfg)
        hits = data.get("itemHits") if isinstance(data, dict) else None
        if not isinstance(hits, list):
            continue
        out: List[str] = []
        for h in hits:
            item = h.get("item") if isinstance(h, dict) and isinstance(h.get("item"), dict) else h
            if not isinstance(item, dict):
                continue
            if not _title_match(title, item.get("title")):
                continue
            out.extend(_chemrxiv_asset_urls(item))
        if out:
            return out
    return []


# ────────────────────────── Research Square / Preprints.org(DOI 直构)──────────────────────────
def researchsquare_pdf_urls(doi: str) -> List[str]:
    """Research Square 新式 DOI → PDF 直链(附 latest.pdf 兜底版本漂移)。"""
    m = _RS_NEW_RE.search(_normalize_doi(doi))
    if not m:
        return []
    art, ver = m.group(1), m.group(2)
    urls: List[str] = []
    if ver:
        urls.append(f"https://www.researchsquare.com/article/{art}/v{ver}.pdf")
    urls.append(f"https://www.researchsquare.com/article/{art}/latest.pdf")
    return urls


def preprints_org_pdf_urls(doi: str) -> List[str]:
    """Preprints.org DOI → 稿件 /download 直链(缺版本默认 v1)。"""
    m = _PREPRINTS_RE.search(_normalize_doi(doi))
    if not m:
        return []
    ym, num, ver = m.group(1), m.group(2), (m.group(3) or "1")
    return [f"https://www.preprints.org/manuscript/{ym}.{num}/v{ver}/download"]


# ────────────────────────── Crossref(按标题找 RS/Preprints.org/ChemRxiv 预印本 DOI)──────────────────────────
def crossref_preprint_urls(title: str, cfg: Any, get: _Get, rows: int = 6) -> List[str]:
    if not title:
        return []
    params: Dict[str, Any] = {
        "query.bibliographic": title,
        "rows": rows,
        "filter": "type:posted-content",
        "select": "DOI,title,prefix",
    }
    email = _cfg_get(cfg, "email", None)
    if email:
        params["mailto"] = email             # 礼貌池:路由到 Crossref polite pool,更稳、更少 429
    data = get(_CROSSREF_WORKS, params, cfg)
    items = ((data or {}).get("message") or {}).get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out: List[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        doi = _normalize_doi(it.get("DOI"))
        if not doi:
            continue
        titles = it.get("title") if isinstance(it.get("title"), list) else []
        if not any(_title_match(title, t) for t in titles):
            continue
        prefix = _doi_prefix(doi)
        if prefix == _PREFIX_RESEARCHSQUARE:
            out.extend(researchsquare_pdf_urls(doi))
        elif prefix == _PREFIX_PREPRINTS_ORG:
            out.extend(preprints_org_pdf_urls(doi))
        elif prefix == _PREFIX_CHEMRXIV:
            out.extend(chemrxiv_by_doi(doi, cfg, get))
    return out


# ────────────────────────── 对外接口 ──────────────────────────
def find_pdf_candidates(doi: Optional[str] = None, title: Optional[str] = None,
                        cfg: Any = None, *, _get_json: Optional[_Get] = None) -> List[str]:
    """按 DOI/标题在化学类预印本服务器找预印本 PDF 候选,返回去重保序的 URL 列表(不下载)。

    - 输入 DOI 本身是预印本 DOI → 直定;否则按标题经各家公开 API / Crossref 找预印本版。
    - 无 DOI 无标题、或全程无命中 → [](优雅降级,绝不抛)。
    - `_get_json` 仅供离线 selftest 注入假取回器 get(url, params, cfg)->json|None;生产勿传。
    """
    get = _get_json or _http_get_json
    out: List[str] = []
    try:
        d = _normalize_doi(doi)
        prefix = _doi_prefix(d)
        if prefix == _PREFIX_CHEMRXIV:
            out.extend(chemrxiv_by_doi(d, cfg, get))
        elif prefix == _PREFIX_RESEARCHSQUARE:
            out.extend(researchsquare_pdf_urls(d))
        elif prefix == _PREFIX_PREPRINTS_ORG:
            out.extend(preprints_org_pdf_urls(d))

        t = (title or "").strip()
        if t:
            # 主路径:Crossref 按标题发现 RS / Preprints.org / ChemRxiv 预印本 DOI(快、稳、覆盖三家),
            # ChemRxiv 命中再经 cambridge.org 取 asset 直链。
            try:
                out.extend(crossref_preprint_urls(t, cfg, get))
            except Exception:  # noqa: BLE001 — 单条路径失败不拖垮整体
                pass
            # 可选:ChemRxiv 原生 term 检索。chemrxiv.org 常被 Cloudflare 拦截且响应慢,而其发现能力
            # 已被上面的 Crossref 覆盖,故**默认关闭**;需要时置 cfg.preprints_use_chemrxiv_search=True
            # 开启(适用于 chemrxiv.org 可达 / 走浏览器代理层的环境)。
            if _cfg_get(cfg, "preprints_use_chemrxiv_search", False):
                try:
                    out.extend(chemrxiv_by_title(t, cfg, get))
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001 — 顶层兜底:任何意外都优雅返回已得候选
        pass

    seen: set = set()
    res: List[str] = []
    for u in out:
        if not isinstance(u, str):
            continue
        u = u.strip()
        if not u or not u.lower().startswith(("http://", "https://")) or u in seen:
            continue
        seen.add(u)
        res.append(u)
    return res


# ────────────────────────── 不联网 selftest ──────────────────────────
def _selftest() -> int:
    # ① DOI 归一化 / 前缀
    assert _normalize_doi(" https://doi.org/10.26434/chemrxiv-2023-abc ") == "10.26434/chemrxiv-2023-abc"
    assert _normalize_doi("DOI:10.21203/rs.3.rs-123/v1;") == "10.21203/rs.3.rs-123/v1"
    assert _doi_prefix("10.20944/preprints202301.0001.v1") == "10.20944"

    # ② 标题模糊匹配(含 HTML 标签、标点、大小写差异 → 仍匹配;不同论文 → 不匹配)
    assert _title_match("CO<sub>2</sub> Hydrogenation over Co Catalysts",
                        "CO2 hydrogenation over co catalysts")
    assert _title_match("Selective Catalytic Reduction of NOx by Ammonia",
                        "Selective catalytic reduction of NO_x by ammonia.")
    assert not _title_match("A study of copper zinc catalysts", "Totally unrelated graphene paper")
    assert not _title_match("short", "short")           # 过短不匹配,避免误判

    # ③ Research Square 新式 DOI → 直构 PDF(含 latest 兜底);老式/非法 → []
    rs = researchsquare_pdf_urls("10.21203/rs.3.rs-275969/v1")
    assert rs == ["https://www.researchsquare.com/article/rs-275969/v1.pdf",
                  "https://www.researchsquare.com/article/rs-275969/latest.pdf"], rs
    assert researchsquare_pdf_urls("10.21203/rs.2.23921/v1") == []      # 老式:文章 id≠DOI 号,不臆造
    assert researchsquare_pdf_urls("10.1021/jacs.5c04835") == []

    # ④ Preprints.org DOI → /download(缺版本默认 v1)
    assert preprints_org_pdf_urls("10.20944/preprints202301.0001.v2") == [
        "https://www.preprints.org/manuscript/202301.0001/v2/download"]
    assert preprints_org_pdf_urls("10.20944/preprints202408.1234") == [
        "https://www.preprints.org/manuscript/202408.1234/v1/download"]

    # ⑤ ChemRxiv asset 抽取:original.url 优先,退化 asset.url
    assert _chemrxiv_asset_urls({"asset": {"original": {"url": "https://cr.org/a.pdf"}}}) == \
        ["https://cr.org/a.pdf"]
    assert _chemrxiv_asset_urls({"asset": {"url": "https://cr.org/b.pdf"}}) == ["https://cr.org/b.pdf"]
    assert _chemrxiv_asset_urls({"asset": {}}) == [] and _chemrxiv_asset_urls(None) == []

    # ⑥ 端到端(注入假取回器,不联网):按 URL/params 分流各 API 的固定响应
    TITLE = "Selective CO2 Hydrogenation to Methanol over Copper Catalysts"
    CR_ASSET = "https://chemrxiv.org/engage/api-gateway/chemrxiv/assets/doi/original/paper.pdf"
    CR_ASSET2 = "https://chemrxiv.org/engage/api-gateway/chemrxiv/assets/term/original/paper.pdf"

    def fake_get(url: str, params: Optional[Dict[str, Any]], cfg: Any):
        if "/items/doi/" in url:                        # ChemRxiv DOI 精确查(Crossref 命中后回补)
            return {"item": {"title": TITLE, "asset": {"original": {"url": CR_ASSET}}}}
        if url.endswith("/items"):                       # ChemRxiv 原生 term 关键词检索
            return {"itemHits": [
                {"item": {"title": TITLE, "asset": {"original": {"url": CR_ASSET2}}}},
                {"item": {"title": "An unrelated paper about lithium batteries",
                          "asset": {"original": {"url": "https://cr.org/BAD.pdf"}}}},
            ]}
        if url == _CROSSREF_WORKS:                       # Crossref 找 RS/Preprints.org/ChemRxiv 预印本
            return {"message": {"items": [
                {"DOI": "10.26434/chemrxiv-2099-abcde", "title": [TITLE]},      # → 回补取 asset
                {"DOI": "10.21203/rs.3.rs-999888/v1", "title": [TITLE]},
                {"DOI": "10.20944/preprints202405.0777.v1", "title": [TITLE]},
                {"DOI": "10.99999/not-a-preprint", "title": [TITLE]},           # 非预印本前缀 → 忽略
                {"DOI": "10.21203/rs.3.rs-111/v1", "title": ["A totally different unrelated title"]},
            ]}}
        return None

    # 默认路径(不开原生 term 检索):Crossref 聚合 ChemRxiv(回补 asset)+ RS + Preprints.org
    got = find_pdf_candidates("10.1021/acscatal.0c01584", TITLE, _get_json=fake_get)
    assert CR_ASSET in got, got                                    # ChemRxiv:Crossref→DOI 回补 asset
    assert "https://www.researchsquare.com/article/rs-999888/v1.pdf" in got, got
    assert "https://www.preprints.org/manuscript/202405.0777/v1/download" in got, got
    assert CR_ASSET2 not in got, "默认不应触发原生 term 检索"
    assert "https://cr.org/BAD.pdf" not in got, got               # 无关项不会出现
    assert all(not u.endswith("rs-111/v1.pdf") for u in got), got  # 标题不匹配的 RS 项被过滤
    assert all("not-a-preprint" not in u for u in got), got       # 非预印本前缀被忽略
    assert len(got) == len(set(got)), got                          # 去重

    # ⑥b ChemRxiv 原生 term 检索 / DOI 精确查:直接测(标题过滤掉无关项)
    assert chemrxiv_by_title(TITLE, None, fake_get) == [CR_ASSET2]
    assert chemrxiv_by_doi("10.26434/x", None, fake_get) == [CR_ASSET]

    # ⑥c 打开 cfg.preprints_use_chemrxiv_search → 额外并入原生 term 命中(仍不含无关项)
    class _Cfg:
        preprints_use_chemrxiv_search = True

    got_on = find_pdf_candidates("10.1021/x", TITLE, cfg=_Cfg(), _get_json=fake_get)
    assert CR_ASSET in got_on and CR_ASSET2 in got_on, got_on
    assert "https://cr.org/BAD.pdf" not in got_on, got_on

    # ⑦ 输入 DOI 即预印本 DOI → 直定(纯构造,不需取回器)
    assert find_pdf_candidates("10.21203/rs.3.rs-42/v3", None, _get_json=lambda *a: None) == [
        "https://www.researchsquare.com/article/rs-42/v3.pdf",
        "https://www.researchsquare.com/article/rs-42/latest.pdf"]
    assert find_pdf_candidates("10.20944/preprints202401.0009.v1", None,
                               _get_json=lambda *a: None) == [
        "https://www.preprints.org/manuscript/202401.0009/v1/download"]
    assert find_pdf_candidates("10.26434/chemrxiv-2024-xyz", None, _get_json=fake_get) == [CR_ASSET]

    # ⑧ 优雅降级:无输入 → [](且不触发取回);取回全 None → []
    def _boom(*_a, **_k):
        raise AssertionError("无 doi/title 时不应发起任何请求")
    assert find_pdf_candidates(None, None, _get_json=_boom) == []
    assert find_pdf_candidates("", "", _get_json=_boom) == []
    assert find_pdf_candidates("10.1021/x", "Some Real Enough Paper Title",
                               _get_json=lambda *a: None) == []

    print("PREPRINTS_OK")
    return 0


if __name__ == "__main__":  # 不联网 selftest: python -m fulltext_fetcher.sources.preprints
    raise SystemExit(_selftest())
