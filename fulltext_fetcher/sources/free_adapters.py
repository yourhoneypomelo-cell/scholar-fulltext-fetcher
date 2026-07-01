"""把免费方法逻辑模块包装成 BaseSource 连接器并注册(集成层,由总指挥统一维护)。

各免费方法模块(websearch / oa_button / publisher_oa / wayback / browser_search)按约定只写
**纯逻辑 + 离线 selftest、不 @register**;本文件是把它们接入源注册表/流水线的唯一集成点,
以避免多人并行改共享文件时相互覆盖。

约定:
- 每个适配器是 BaseSource 子类,``find_candidates(paper, ctx) -> List[PdfCandidate]``,
  内部吞掉一切异常并返回 [](单源失败绝不拖垮流水线,遵守 base.py 契约)。
- 底层免费模块一律**函数内延迟导入**:模块缺失/依赖缺失即优雅降级(该源产 0 候选)。
- ``publisher_oa`` 已直接返回 ``PdfCandidate``,原样透传;其余返回 ``List[str]``,经
  ``_mk_candidates`` 统一包装(按是否形似 PDF 直链give kind/confidence)。

浏览器源 ``browser_search`` 默认**不进 DEFAULT_SOURCE_ORDER**(每条要起无头浏览器、慢且易被限),
仅注册以便 ``--sources ...,browser_search`` 显式开启;其余免费源可进默认顺序(便宜、稳健)。
"""
from __future__ import annotations

from typing import Any, List, Optional

from ..models import Paper, PdfCandidate
from .base import BaseSource, SourceContext, register


def _looks_pdf(url: str) -> bool:
    low = (url or "").lower().split("#", 1)[0].split("?", 1)[0]
    return low.endswith(".pdf") or "/pdf" in low


def _mk_candidates(urls: Any, source: str) -> List[PdfCandidate]:
    """List[str] → List[PdfCandidate](去重保序;PDF 直链高分、其余当落地页低分)。"""
    out: List[PdfCandidate] = []
    seen = set()
    for u in urls or []:
        if not isinstance(u, str):
            continue
        u = u.strip()
        if not u or not u.lower().startswith(("http://", "https://")) or u in seen:
            continue
        seen.add(u)
        is_pdf = _looks_pdf(u)
        out.append(PdfCandidate(url=u, source=source,
                                kind="pdf" if is_pdf else "landing",
                                confidence=60 if is_pdf else 40))
    return out


@register
class PublisherOaSource(BaseSource):
    """已知 OA 出版商:DOI → PDF 直链(纯构造、不联网即产候选)。"""
    name = "publisher_oa"
    requires_doi = True

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        try:
            from . import publisher_oa
            cands = publisher_oa.build_pdf_candidates(paper.doi, paper.title, ctx.cfg)
            return [c for c in (cands or []) if isinstance(c, PdfCandidate)]
        except Exception:  # noqa: BLE001
            return []


@register
class OaButtonSource(BaseSource):
    """oa.works / OpenAccess Button 免费全文 API(官方端点已停用→通常空;可指向自建实例)。"""
    name = "oa_button"
    requires_doi = False

    def applicable(self, paper: Paper) -> bool:
        return bool(paper.doi or paper.title)

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        try:
            from . import oa_button
            urls = oa_button.find_pdf_candidates(paper.doi, paper.title, ctx.cfg)
            return _mk_candidates(urls, "oa_button")
        except Exception:  # noqa: BLE001
            return []


@register
class WebSearchSource(BaseSource):
    """免费搜索引擎(DuckDuckGo/Bing)按标题/DOI 找作者自存稿 / 机构库 PDF。"""
    name = "websearch"
    requires_doi = False

    def applicable(self, paper: Paper) -> bool:
        return bool(paper.doi or paper.title)

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        try:
            from . import websearch
            urls = websearch.search_pdf_candidates(paper.title, paper.doi, ctx.cfg)
            return _mk_candidates(urls, "websearch")
        except Exception:  # noqa: BLE001
            return []


@register
class WaybackSource(BaseSource):
    """Internet Archive / Wayback 存档 PDF 兜底(按 DOI 查 doi.org 存档快照)。"""
    name = "wayback"
    requires_doi = False

    def applicable(self, paper: Paper) -> bool:
        return bool(paper.doi)

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        try:
            from . import wayback
            urls = wayback.find_archived_pdf(paper.doi, None, ctx.cfg)
            return _mk_candidates(urls, "wayback")
        except Exception:  # noqa: BLE001
            return []


@register
class PreprintsSource(BaseSource):
    """化学/材料类预印本服务器:ChemRxiv / Research Square / Preprints.org 预印本 PDF 发现。

    预印本 DOI → 直构 / 取 asset;已发表 DOI + 标题 → 经 Crossref 找预印本版。按 DOI 或标题可用,
    纯逻辑 + 可选 requests 延迟导入,缺库/网络异常一律优雅降级为 0 候选。
    """
    name = "preprints"
    requires_doi = False

    def applicable(self, paper: Paper) -> bool:
        return bool(paper.doi or paper.title)

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        try:
            from . import preprints
            urls = preprints.find_pdf_candidates(paper.doi, paper.title, ctx.cfg)
            return _mk_candidates(urls, "preprints")
        except Exception:  # noqa: BLE001
            return []


@register
class BrowserSearchSource(BaseSource):
    """无头隐身浏览器驱动搜索引擎找 PDF(重、默认不入默认顺序;--sources 显式开启)。"""
    name = "browser_search"
    requires_doi = False

    def applicable(self, paper: Paper) -> bool:
        return bool(paper.doi or paper.title)

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        try:
            from .. import browser_search
            raw = (paper.doi or paper.title or "").strip()
            if not raw:
                return []
            res = browser_search.browser_search_pdfs(raw, cfg=ctx.cfg, log=getattr(ctx, "log", None))
            return _mk_candidates((res or {}).get("candidates"), "browser_search")
        except Exception:  # noqa: BLE001
            return []


def _selftest() -> int:
    """离线 selftest:验证适配器注册 + 候选包装,且空输入不触发任何网络。"""
    class _Ctx:
        cfg = None
        log = None
        client = None
        events = None

    ctx = _Ctx()

    # ① 注册表:6 个免费源均已 @register
    from .base import REGISTRY
    for n in ("publisher_oa", "oa_button", "websearch", "wayback", "preprints", "browser_search"):
        assert n in REGISTRY, ("未注册: %s" % n)

    # ② publisher_oa 适配器:纯构造(不联网)→ Frontiers OA 直链(URL 形如 .../pdf,非 .pdf 结尾)
    pc = PublisherOaSource().find_candidates(Paper(doi="10.3389/fpsyg.2019.00001"), ctx)
    assert pc and any(c.kind == "pdf" and _looks_pdf(c.url) for c in pc), pc
    assert all(isinstance(c, PdfCandidate) for c in pc)

    # ②b preprints 适配器:预印本 DOI 纯构造(不联网)→ Research Square PDF 直链候选
    pp = PreprintsSource().find_candidates(Paper(doi="10.21203/rs.3.rs-275969/v1"), ctx)
    assert pp and any(c.kind == "pdf" and _looks_pdf(c.url) for c in pp), pp
    assert all(isinstance(c, PdfCandidate) and c.source == "preprints" for c in pp), pp

    # ③ _mk_candidates:PDF 直链高分、落地页低分、去重、过滤非 http
    got = _mk_candidates(["https://x.org/a.pdf", "https://x.org/a.pdf",
                          "https://x.org/land", "ftp://no", ""], "t")
    assert [c.url for c in got] == ["https://x.org/a.pdf", "https://x.org/land"], got
    assert got[0].kind == "pdf" and got[0].confidence == 60
    assert got[1].kind == "landing" and got[1].confidence == 40

    # ④ 空输入的联网源 → [](不触发网络):无 doi/title
    empty = Paper()
    assert OaButtonSource().find_candidates(empty, ctx) == []
    assert WebSearchSource().find_candidates(empty, ctx) == []
    assert WaybackSource().find_candidates(empty, ctx) == []
    assert PreprintsSource().find_candidates(empty, ctx) == []
    assert BrowserSearchSource().find_candidates(empty, ctx) == []

    print("FREE_ADAPTERS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
