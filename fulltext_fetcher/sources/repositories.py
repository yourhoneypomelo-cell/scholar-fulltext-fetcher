"""学科/通用仓储类源:arXiv / Europe PMC / PMC / bioRxiv·medRxiv / DOAJ / Zenodo / HAL。

很多源能用 DOI、PMCID、arXiv id 或标题中的任一种作为入口,因此部分源 requires_doi=False。
"""
from __future__ import annotations

import re
from typing import List
from urllib.parse import quote

from ..models import Paper, PdfCandidate
from .base import BaseSource, SourceContext, register


@register
class Arxiv(BaseSource):
    name = "arxiv"
    requires_doi = False

    def applicable(self, paper: Paper) -> bool:
        # 有 arxiv_id / arxiv DOI → 适用;仅当"无 DOI 的纯标题输入"才做标题搜索。
        # 已发表论文(有非 arXiv DOI)跳过 arXiv 标题搜索:命中率极低且 3s/次很慢。
        if paper.arxiv_id:
            return True
        if paper.doi and "10.48550/arxiv." in paper.doi.lower():
            return True
        return bool(paper.title and not paper.doi)

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        aid = paper.arxiv_id
        if not aid and paper.doi and "10.48550/arxiv." in paper.doi.lower():
            aid = paper.doi.lower().split("arxiv.", 1)[1]
        if not aid and paper.title and not paper.doi:
            r = ctx.client.get(
                "http://export.arxiv.org/api/query",
                params={"search_query": f'ti:"{paper.title}"', "max_results": 1},
            )
            if r is not None and r.status_code == 200:
                aid = _parse_arxiv_id(r.text)
        if not aid:
            return []
        aid = aid.strip()
        return [PdfCandidate(f"https://arxiv.org/pdf/{aid}", self.name, "pdf", None, None, 90)]


def _parse_arxiv_id(atom_xml: str):
    m = re.search(r"<id>https?://arxiv\.org/abs/([^<]+)</id>", atom_xml)
    if m:
        return m.group(1)
    return None


@register
class EuropePMC(BaseSource):
    name = "europe_pmc"
    requires_doi = False

    def applicable(self, paper: Paper) -> bool:
        return bool(paper.doi or paper.pmcid or paper.title)

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        out: List[PdfCandidate] = []
        pmcid = paper.pmcid
        if not pmcid:
            if paper.doi:
                query = f'DOI:"{paper.doi}"'
            elif paper.title:
                query = f'TITLE:"{paper.title}"'
            else:
                return []
            data = ctx.client.get_json(
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                params={"query": query, "format": "json", "resultType": "core", "pageSize": 1},
            )
            results = ((data or {}).get("resultList") or {}).get("result") or []
            if not results:
                return []
            r0 = results[0]
            pmcid = r0.get("pmcid")
            for f in ((r0.get("fullTextUrlList") or {}).get("fullTextUrl") or []):
                if f.get("documentStyle") == "pdf" and f.get("url"):
                    out.append(PdfCandidate(f["url"], self.name, "pdf", None, None, 80))
        if pmcid:
            out.append(PdfCandidate(
                f"https://europepmc.org/articles/{pmcid}?pdf=render", self.name, "render", None, None, 85))
            out.append(PdfCandidate(
                f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf",
                self.name, "pdf", None, None, 68))
        return out


@register
class PMC(BaseSource):
    name = "pmc"
    requires_doi = False

    def applicable(self, paper: Paper) -> bool:
        return bool(paper.pmcid or paper.doi)

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        pmcid = paper.pmcid
        if not pmcid and paper.doi:
            data = ctx.client.get_json(
                "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/",
                params={"ids": paper.doi, "format": "json"},
            )
            recs = (data or {}).get("records") or []
            if recs:
                pmcid = recs[0].get("pmcid")
        if not pmcid:
            return []
        # NCBI 网页 PDF 路径对脚本常 403,置信度低;Europe PMC 的 render 更可靠(已在上面覆盖)。
        return [PdfCandidate(
            f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/", self.name, "pdf", None, None, 42)]


@register
class BioRxiv(BaseSource):
    name = "biorxiv"

    def applicable(self, paper: Paper) -> bool:
        return bool(paper.doi and paper.doi.startswith("10.1101/"))

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        out: List[PdfCandidate] = []
        for server, site in (("biorxiv", "www.biorxiv.org"), ("medrxiv", "www.medrxiv.org")):
            data = ctx.client.get_json(
                f"https://api.biorxiv.org/details/{server}/{paper.doi}/na/json")
            coll = (data or {}).get("collection") or []
            if coll:
                ver = str(coll[-1].get("version", "1"))
                out.append(PdfCandidate(
                    f"https://{site}/content/{paper.doi}v{ver}.full.pdf",
                    self.name, "pdf", ver, None, 85))
                break
        return out


@register
class Doaj(BaseSource):
    name = "doaj"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        data = ctx.client.get_json(
            f"https://doaj.org/api/v4/search/articles/doi:{quote(paper.doi, safe='')}")
        if not data:
            return []
        out: List[PdfCandidate] = []
        for res in (data.get("results") or [])[:1]:
            for link in ((res.get("bibjson") or {}).get("link") or []):
                if link.get("type") == "fulltext" and link.get("url"):
                    ct = (link.get("content_type") or "").upper()
                    if ct == "PDF":
                        out.append(PdfCandidate(link["url"], self.name, "pdf", None, None, 60))
                    else:
                        out.append(PdfCandidate(link["url"], self.name, "landing", None, None, 26))
        return out


@register
class Zenodo(BaseSource):
    name = "zenodo"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        data = ctx.client.get_json("https://zenodo.org/api/records", params={"q": f'doi:"{paper.doi}"'})
        hits = ((data or {}).get("hits") or {}).get("hits") or []
        out: List[PdfCandidate] = []
        for h in hits[:1]:
            for f in (h.get("files") or []):
                link = (f.get("links") or {}).get("self")
                key = (f.get("key") or "").lower()
                if not link:
                    continue
                if key.endswith(".pdf"):
                    out.append(PdfCandidate(link, self.name, "pdf", None, None, 58))
                else:
                    out.append(PdfCandidate(link, self.name, "file", None, None, 28))
        return out


@register
class Hal(BaseSource):
    name = "hal"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        data = ctx.client.get_json(
            "https://api.archives-ouvertes.fr/search/",
            params={"q": f'doiId_s:"{paper.doi}"', "fl": "fileMain_s,files_s", "wt": "json"},
        )
        docs = ((data or {}).get("response") or {}).get("docs") or []
        out: List[PdfCandidate] = []
        for d in docs[:1]:
            if d.get("fileMain_s"):
                out.append(PdfCandidate(d["fileMain_s"], self.name, "pdf", None, None, 70))
            for f in (d.get("files_s") or []):
                out.append(PdfCandidate(f, self.name, "pdf", None, None, 48))
        return out
