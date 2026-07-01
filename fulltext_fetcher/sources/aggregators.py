"""聚合类源:以 DOI 为键、直接返回(可能的)PDF 直链。覆盖最广、命中率最高。

字段路径依据《fulltext_fetcher资料-各源接口速查.md》(2026-07 核验)。
"""
from __future__ import annotations

from typing import List

from ..models import Paper, PdfCandidate
from .base import BaseSource, SourceContext, register


@register
class Unpaywall(BaseSource):
    name = "unpaywall"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        data = ctx.client.get_json(
            f"https://api.unpaywall.org/v2/{paper.doi}", params={"email": ctx.cfg.email}
        )
        if not data:
            return []
        out: List[PdfCandidate] = []
        best = data.get("best_oa_location") or {}
        if best.get("url_for_pdf"):
            out.append(PdfCandidate(best["url_for_pdf"], self.name, "pdf",
                                    best.get("version"), best.get("license"), 95))
        for loc in (data.get("oa_locations") or []):
            if loc.get("url_for_pdf"):
                out.append(PdfCandidate(loc["url_for_pdf"], self.name, "pdf",
                                        loc.get("version"), loc.get("license"), 82))
            elif loc.get("url"):
                out.append(PdfCandidate(loc["url"], self.name, "landing",
                                        loc.get("version"), loc.get("license"), 30))
        return out


@register
class OpenAlex(BaseSource):
    name = "openalex"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        params = {"mailto": ctx.cfg.email}
        if ctx.cfg.openalex_key:
            params["api_key"] = ctx.cfg.openalex_key
        data = ctx.client.get_json(f"https://api.openalex.org/works/doi:{paper.doi}", params=params)
        if not data:
            return []
        out: List[PdfCandidate] = []
        for locname, conf in (("best_oa_location", 93), ("primary_location", 70)):
            loc = data.get(locname) or {}
            if isinstance(loc, dict) and loc.get("pdf_url"):
                out.append(PdfCandidate(loc["pdf_url"], self.name, "pdf",
                                        loc.get("version"), loc.get("license"), conf))
        for loc in (data.get("locations") or []):
            if isinstance(loc, dict) and loc.get("pdf_url"):
                out.append(PdfCandidate(loc["pdf_url"], self.name, "pdf",
                                        loc.get("version"), loc.get("license"), 74))
        oa = data.get("open_access") or {}
        if oa.get("oa_url"):
            out.append(PdfCandidate(oa["oa_url"], self.name, "landing", None, None, 38))
        return out


@register
class SemanticScholar(BaseSource):
    name = "semantic_scholar"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        headers = {"x-api-key": ctx.cfg.s2_key} if ctx.cfg.s2_key else None
        data = ctx.client.get_json(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{paper.doi}",
            params={"fields": "openAccessPdf,isOpenAccess,externalIds"},
            headers=headers,
        )
        if not data:
            return []
        oap = data.get("openAccessPdf") or {}
        if oap.get("url"):
            return [PdfCandidate(oap["url"], self.name, "pdf", None, None, 76)]
        return []


# Crossref link[] 多为 TDM(text/data mining)链:面向机器而非读者,普通请求多半 403。
# 已知订阅型出版商域名 + text-mining 用途再分层降权,使其在 --no-download 的全局 top 选择
# 与下载模式的源内尝试顺序中,都排在真 OA 直链与可被 landing 回收的落地页之后。
_CROSSREF_PAYWALL_HOSTS = (
    "api.elsevier.com", "api.wiley.com", "sciencedirect.com", "pubs.acs.org",
    "pubs.rsc.org", "onlinelibrary.wiley.com", "academic.oup.com",
    "tandfonline.com", "journals.sagepub.com",
)


def _score_crossref_link(link: dict):
    """给单个 Crossref link 对象评分,返回 (url, confidence) 或 None(非 PDF / 无 URL)。

    Crossref 为兜底源且 link[] 多为 TDM 链(多 403):故基础分本就低,再对 text-mining /
    similarity-checking 用途与已知订阅出版商域名分层降权。仍保留为低分候选(不丢弃),
    以便 download 拿到 HTML 落地页时交由 landing 二次回收内嵌 PDF(实测可回收一部分)。
    """
    url = link.get("URL")
    if not url:
        return None
    ct = (link.get("content-type") or "").lower()
    if ct == "application/pdf":
        conf = 40
    elif ct in ("unspecified", ""):
        conf = 24
    else:
        return None  # text/xml、text/html、application/xml 等并非 PDF
    intended = (link.get("intended-application") or "").lower()
    if intended in ("text-mining", "similarity-checking"):
        conf -= 12
    ul = url.lower()
    if any(h in ul for h in _CROSSREF_PAYWALL_HOSTS):
        conf -= 10
    return url, max(conf, 5)


@register
class Crossref(BaseSource):
    name = "crossref"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        data = ctx.client.get_json(
            f"https://api.crossref.org/works/{paper.doi}", params={"mailto": ctx.cfg.email}
        )
        if not data:
            return []
        msg = data.get("message") or {}
        out: List[PdfCandidate] = []
        for link in (msg.get("link") or []):
            scored = _score_crossref_link(link)
            if not scored:
                continue
            url, conf = scored
            out.append(PdfCandidate(url, self.name, "pdf",
                                    link.get("content-version"), None, conf))
        return out


@register
class Core(BaseSource):
    name = "core"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        if not ctx.cfg.core_key:
            return []  # CORE 必须 key,无 key 直接跳过
        headers = {"Authorization": f"Bearer {ctx.cfg.core_key}"}
        data = ctx.client.get_json(
            "https://api.core.ac.uk/v3/search/works",
            params={"q": f'doi:"{paper.doi}"', "limit": 3},
            headers=headers,
        )
        if not data:
            return []
        out: List[PdfCandidate] = []
        for res in (data.get("results") or []):
            if res.get("downloadUrl"):
                out.append(PdfCandidate(res["downloadUrl"], self.name, "pdf", None, None, 68))
        return out


@register
class OpenAire(BaseSource):
    name = "openaire"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        data = ctx.client.get_json(
            "https://api.openaire.eu/search/publications",
            params={"doi": paper.doi, "format": "json"},
        )
        if not data:
            return []
        urls: List[str] = []
        _collect_urls(data, urls)
        out: List[PdfCandidate] = []
        seen = set()
        for u in urls:
            if u in seen:
                continue
            seen.add(u)
            ul = u.lower()
            # 仅保留像全文/PDF 的链接,丢弃出版商首页等噪声(OpenAIRE 嵌套 JSON 杂质很多)。
            if ul.endswith(".pdf") or "/pdf" in ul or "pdf=" in ul:
                out.append(PdfCandidate(u, self.name, "pdf", None, None, 50))
            elif any(h in ul for h in ("arxiv.org/", "europepmc.org/", "ncbi.nlm.nih.gov/pmc",
                                       "zenodo.org/record", "hal.", "/download")):
                out.append(PdfCandidate(u, self.name, "landing", None, None, 30))
            # 其它(如出版商/机构首页)直接跳过,避免误判
        return out[:6]


def _collect_urls(node, acc: List[str], depth: int = 0) -> None:
    """在 OpenAIRE 深层嵌套 JSON 中递归提取 webresource/url 链接(防御式)。"""
    if depth > 12 or len(acc) > 30:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            kl = str(k).lower()
            if kl in ("url", "webresourceurl") and isinstance(v, str) and v.startswith("http"):
                acc.append(v)
            elif isinstance(v, str) and kl == "$" and v.startswith("http"):
                acc.append(v)
            else:
                _collect_urls(v, acc, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _collect_urls(item, acc, depth + 1)


if __name__ == "__main__":  # 纯函数 selftest(不联网): python -m fulltext_fetcher.sources.aggregators
    f = _score_crossref_link
    # 普通 application/pdf(非 TDM、非订阅域):基础 40
    assert f({"URL": "https://oa.org/a.pdf", "content-type": "application/pdf"}) == ("https://oa.org/a.pdf", 40)
    # unspecified / 空 content-type:24
    assert f({"URL": "https://oa.org/b", "content-type": "unspecified"}) == ("https://oa.org/b", 24)
    assert f({"URL": "https://oa.org/b2", "content-type": ""}) == ("https://oa.org/b2", 24)
    # 非 PDF 的 content-type 一律跳过
    assert f({"URL": "https://oa.org/c.xml", "content-type": "text/xml"}) is None
    assert f({"URL": "https://oa.org/d", "content-type": "text/html"}) is None
    # 无 URL 跳过
    assert f({"content-type": "application/pdf"}) is None
    assert f({"URL": "", "content-type": "application/pdf"}) is None
    # text-mining / similarity-checking 用途降权:40-12=28
    assert f({"URL": "https://oa.org/e.pdf", "content-type": "application/pdf",
              "intended-application": "text-mining"}) == ("https://oa.org/e.pdf", 28)
    assert f({"URL": "https://oa.org/f.pdf", "content-type": "application/pdf",
              "intended-application": "similarity-checking"})[1] == 28
    # 订阅出版商域名降权:40-10=30
    assert f({"URL": "https://api.elsevier.com/x.pdf",
              "content-type": "application/pdf"}) == ("https://api.elsevier.com/x.pdf", 30)
    # TDM + 订阅域叠加:40-12-10=18
    assert f({"URL": "https://api.elsevier.com/y.pdf", "content-type": "application/pdf",
              "intended-application": "text-mining"}) == ("https://api.elsevier.com/y.pdf", 18)
    # 下界保护:不低于 5 (24-12-10=2 -> 5)
    assert f({"URL": "https://pubs.acs.org/z", "content-type": "unspecified",
              "intended-application": "text-mining"}) == ("https://pubs.acs.org/z", 5)
    # 关键不变量:Crossref 最高基础分(40) 必须低于任一真 OA 直链的最低 confidence
    #   (Core 68 / OpenAlex locations 74 / S2 76 / Unpaywall oa_locations 82),
    #   确保 --no-download 的全局 top 不被 Crossref 兜底链抢占。
    assert f({"URL": "https://oa.org/g.pdf", "content-type": "application/pdf"})[1] < 68
    print("AGGREGATORS_OK")
