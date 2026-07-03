"""绿色 OA 仓储 / 聚合源:BASE、OSF、ScienceOpen。

在既有聚合源(aggregators.py)与学科仓储(repositories.py)之外,补充三个开放获取覆盖面。
字段路径均按官方接口于 2026-07 核验(见《fulltext_fetcher资料-各源接口速查.md》主表 + 本模块补充):

- BASE(Bielefeld Academic Search Engine):全球最大 OA 元数据聚合之一(400M+ 文档)。
  实时检索接口 `api.base-search.net` 的 fcgi 端点可**免 key** 使用(与 searx/searxng 同路径),
  `&format=json` 返回 Solr 风格结果。按 DOI 命中后取:
    · `dclink` 全文/落地 URL(可能分号分隔多条)
    · `dcoa`  开放获取状态(0=非 OA / 1=OA / 2=未知)
    · `dcdoi` DOI
  仅保留 OA(1)与未知(2)的链接;非 OA(0)跳过。像 PDF 的给 pdf,其余给 landing 交由 landing 回收。

- OSF(Open Science Framework):跨学科预印本仓储。JSON:API 按 DOI 过滤
  `GET api.osf.io/v2/preprints/?filter[doi]={doi}`,从 `data[].relationships.primary_file`
  的 related href 抽出文件 id,拼直下链 `https://osf.io/download/{file_id}`(OSF 新旧下载格式均兼容)。

- ScienceOpen:无公开的 DOI→PDF JSON API(仅 BookMetaHub 的 OAI-PMH 与 Crossref 集成),
  但其**自托管** OA 内容(Crossref 前缀 10.14293)有稳定落地 `hosted-document?doi={doi}`,
  作为低置信 landing 交由 landing 环节回收内嵌 citation_pdf_url;非自托管 DOI 不产候选以免噪声。

约定同其它连接器:内部吞异常、返回 [],绝不抛出影响其它源。仅用标准库 + requests(经 ctx.client)。
"""
from __future__ import annotations

import concurrent.futures
import re
from typing import Any, List, Optional

from ..models import Paper, PdfCandidate
from .base import BaseSource, SourceContext, register


def _first(v: Any) -> Optional[str]:
    """BASE 的 fcgi JSON 字段可能是字符串,也可能是字符串列表;取第一个非空字符串。"""
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, (list, tuple)):
        for it in v:
            if isinstance(it, str) and it.strip():
                return it.strip()
    return None


def _looks_like_pdf(url: str) -> bool:
    u = url.lower()
    return u.endswith(".pdf") or "/pdf" in u or "pdf=" in u or "format=pdf" in u


@register
class Base(BaseSource):
    """BASE 实时检索(api.base-search.net fcgi,PerformSearch + format=json,免 key)。"""

    name = "base"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        data = ctx.client.get_json(
            "https://api.base-search.net/cgi-bin/BaseHttpSearchInterface.fcgi",
            params={
                "func": "PerformSearch",
                "query": f'dcdoi:"{paper.doi}"',
                "format": "json",
                "hits": 5,
                "boost": "oa",  # 让 OA 文档优先返回
            },
        )
        if not data:
            return []
        resp = data.get("response")
        docs = (resp.get("docs") if isinstance(resp, dict) else None) or data.get("docs") or []
        out: List[PdfCandidate] = []
        seen: set = set()
        for d in docs[:5]:
            if not isinstance(d, dict):
                continue
            oa = (_first(d.get("dcoa")) or "").strip()
            if oa == "0":  # 明确非 OA,跳过
                continue
            link_field = _first(d.get("dclink")) or _first(d.get("dcidentifier"))
            if not link_field:
                continue
            for link in re.split(r"[;\s]+", link_field):
                link = link.strip()
                if not link.startswith("http") or link in seen:
                    continue
                seen.add(link)
                if oa == "1" and _looks_like_pdf(link):
                    out.append(PdfCandidate(link, self.name, "pdf", None, None, 66))
                elif oa == "1":
                    out.append(PdfCandidate(link, self.name, "landing", None, None, 34))
                else:  # oa == "2"(未知):低分 landing 兜底
                    out.append(PdfCandidate(link, self.name, "landing", None, None, 22))
        return out[:6]


def _osf_primary_file_id(item: dict) -> Optional[str]:
    """从预印本对象的 primary_file 关系 related href 中抽出文件 id。"""
    rel = (item.get("relationships") or {}).get("primary_file") or {}
    links = rel.get("links") or {}
    related = links.get("related")
    href = related.get("href") if isinstance(related, dict) else related
    if isinstance(href, str):
        m = re.search(r"/files/([^/?#]+)", href)
        if m:
            return m.group(1)
    return None


@register
class Osf(BaseSource):
    """OSF 预印本仓储(api.osf.io/v2/preprints,JSON:API,按 DOI 过滤)。"""

    name = "osf"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        data = ctx.client.get_json(
            "https://api.osf.io/v2/preprints/",
            params={"filter[doi]": paper.doi, "page[size]": 5},
        )
        items = (data or {}).get("data") or []
        out: List[PdfCandidate] = []
        for it in items[:3]:
            if not isinstance(it, dict):
                continue
            file_id = _osf_primary_file_id(it)
            if file_id:
                out.append(PdfCandidate(
                    f"https://osf.io/download/{file_id}", self.name, "pdf", None, None, 72))
            elif it.get("id"):  # 回退:按预印本 guid 直下主文件
                out.append(PdfCandidate(
                    f"https://osf.io/download/{it['id']}", self.name, "pdf", None, None, 52))
        return out


@register
class ScienceOpen(BaseSource):
    """ScienceOpen 自托管 OA 内容(Crossref 前缀 10.14293)的落地页。

    ScienceOpen 无公开 DOI→PDF 的 JSON API;其自托管全文有稳定落地
    `https://www.scienceopen.com/hosted-document?doi={doi}`,作为 landing 候选交由
    landing 环节回收内嵌 citation_pdf_url。其它前缀 ScienceOpen 多仅索引不托管,跳过避免噪声。
    """

    name = "scienceopen"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        doi = (paper.doi or "").strip()
        if not doi or not doi.lower().startswith("10.14293"):
            return []
        url = f"https://www.scienceopen.com/hosted-document?doi={doi}"
        return [PdfCandidate(url, self.name, "landing", None, None, 30)]


# ── 147 五-补:并发绿色 OA 发现(最全 fallback 的绿仓层;承接《总评估-147》五-补)──
# 与 aggregators.fast_oa_trio(免费三件套=最快)互补:此处并发查绿仓源(BASE + OSF),
# 作 fallback 链「…→绿仓→…」的并发化实现。arXiv / PMC / EuropePMC / Zenodo / HAL 已由
# repositories.py 覆盖,不在此重复;仅并发本模块的绿仓源,合并去重、按分降序。
_GREEN_FAST_SOURCES = ("base", "osf")


def _safe_green_find(src: BaseSource, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
    """调单源 find_candidates 并吞其自身异常(单源失败不拖垮并发批)。"""
    try:
        return src.find_candidates(paper, ctx) or []
    except Exception:  # noqa: BLE001
        return []


def fast_green_oa(paper: Paper, ctx: SourceContext, max_workers: int = 2) -> List[PdfCandidate]:
    """并发查绿色 OA 仓储源(BASE + OSF),合并为去重、按分降序的候选(直链优先)。

    单源异常/超时不影响其它源;仅做候选发现,取字节/验 %PDF 交由 download 层或
    aggregators.first_valid_pdf(注入 fetch)完成。
    """
    from .base import REGISTRY
    srcs = [REGISTRY[n]() for n in _GREEN_FAST_SOURCES if n in REGISTRY]
    if not srcs:
        return []
    merged: List[PdfCandidate] = []
    workers = max(1, min(max_workers, len(srcs)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_safe_green_find, s, paper, ctx) for s in srcs]
        for fut in concurrent.futures.as_completed(futs):
            merged.extend(fut.result())
    best: dict = {}
    for c in merged:
        prev = best.get(c.url)
        if prev is None or c.confidence > prev.confidence:
            best[c.url] = c
    uniq = list(best.values())
    uniq.sort(key=lambda c: (0 if c.is_direct() else 1, -int(c.confidence or 0), c.source, c.url))
    return uniq


if __name__ == "__main__":  # 不联网 selftest: python -m fulltext_fetcher.sources.green_oa
    class _FakeClient:
        """按 URL 子串命中返回预置 JSON 的假客户端(不联网)。"""

        def __init__(self, table: dict):
            self._table = table

        def get_json(self, url: str, **_kw):
            for key, val in self._table.items():
                if key in url:
                    return val
            return None

    class _Cfg:
        email = "selftest@example.org"

    class _Ctx:
        def __init__(self, table: dict):
            self.client = _FakeClient(table)
            self.cfg = _Cfg()
            self.log = None
            self.events = None

    _BASE_URL = "BaseHttpSearchInterface"
    _OSF_URL = "api.osf.io/v2/preprints"

    # ── BASE:PDF 直链(OA=1)/ 落地页(OA=1,列表值,测 _first)/ 非 OA(0,跳过) ──
    base_ctx = _Ctx({_BASE_URL: {"response": {"numFound": 3, "docs": [
        {"dcdoi": "10.1000/xyz", "dcoa": "1",
         "dclink": "https://repo.example.org/bitstream/123/fulltext.pdf"},
        {"dcdoi": ["10.1000/xyz"], "dcoa": ["1"],
         "dclink": ["https://repo.example.org/handle/123"]},          # 落地页 + 列表值
        {"dcdoi": "10.1000/xyz", "dcoa": "0",
         "dclink": "https://paywall.example.com/article"},            # 非 OA → 跳过
    ]}}})
    bc = Base().find_candidates(Paper(doi="10.1000/xyz"), base_ctx)
    pdfs = [c for c in bc if c.kind == "pdf"]
    lands = [c for c in bc if c.kind == "landing"]
    assert pdfs and pdfs[0].url.endswith("/fulltext.pdf") and pdfs[0].confidence == 66, bc
    assert any(c.url.endswith("/handle/123") for c in lands), bc          # 列表值被 _first 正确解析
    assert all("paywall" not in c.url for c in bc), bc                    # 非 OA 已剔除
    assert all(c.source == "base" for c in bc)
    # 无数据 / 无匹配 URL → 空(优雅降级)
    assert Base().find_candidates(Paper(doi="10.1/none"), _Ctx({})) == []

    # ── OSF:primary_file → 文件 id → 直下链 ──
    osf_ctx = _Ctx({_OSF_URL: {"data": [
        {"id": "abc12", "type": "preprints",
         "attributes": {"doi": "10.31234/osf.io/abc12", "title": "T"},
         "relationships": {"primary_file": {"links": {"related": {
             "href": "https://api.osf.io/v2/files/666cadbf65e1de5b1b894156/"}}}}},
    ]}})
    oc = Osf().find_candidates(Paper(doi="10.31234/osf.io/abc12"), osf_ctx)
    assert oc and oc[0].url == "https://osf.io/download/666cadbf65e1de5b1b894156", oc
    assert oc[0].kind == "pdf" and oc[0].confidence == 72, oc
    # 回退:无 primary_file 时按 guid 直下
    osf_ctx2 = _Ctx({_OSF_URL: {"data": [{"id": "zz999", "attributes": {}, "relationships": {}}]}})
    oc2 = Osf().find_candidates(Paper(doi="10.31234/osf.io/zz999"), osf_ctx2)
    assert oc2 and oc2[0].url == "https://osf.io/download/zz999" and oc2[0].confidence == 52, oc2
    # 空结果集 → []
    assert Osf().find_candidates(Paper(doi="10.1/none"), _Ctx({_OSF_URL: {"data": []}})) == []

    # ── ScienceOpen:自家前缀给 landing,其它前缀不产候选 ──
    so = ScienceOpen().find_candidates(Paper(doi="10.14293/S2199-1006.1.SOR-.PPTEST.v1"), _Ctx({}))
    assert so and so[0].kind == "landing", so
    assert so[0].url == ("https://www.scienceopen.com/hosted-document?"
                         "doi=10.14293/S2199-1006.1.SOR-.PPTEST.v1"), so
    assert ScienceOpen().find_candidates(Paper(doi="10.1000/other"), _Ctx({})) == []

    # ── 147 五-补:fast_green_oa 并发绿仓(BASE + OSF)合并去重、按分降序 ──
    _fg_ctx = _Ctx({
        _BASE_URL: {"response": {"docs": [
            {"dcdoi": "10.1/x", "dcoa": "1", "dclink": "https://repo.org/full.pdf"}]}},
        _OSF_URL: {"data": [{"id": "gid9", "relationships": {"primary_file": {"links": {
            "related": {"href": "https://api.osf.io/v2/files/FILEID9/"}}}}}]},
    })
    _fg = fast_green_oa(Paper(doi="10.1/x"), _fg_ctx)
    _fg_urls = [c.url for c in _fg]
    assert "https://repo.org/full.pdf" in _fg_urls, _fg_urls        # BASE pdf(66)
    assert "https://osf.io/download/FILEID9" in _fg_urls, _fg_urls  # OSF pdf(72)
    assert len(_fg_urls) == len(set(_fg_urls)), _fg_urls            # 去重
    assert _fg[0].url == "https://osf.io/download/FILEID9", [(c.source, c.confidence) for c in _fg]  # 72>66
    # 无匹配 → 空(优雅降级);单源异常被吞不拖垮
    assert fast_green_oa(Paper(doi="10.none/x"), _Ctx({})) == []

    print("GREEN_OA_OK")
