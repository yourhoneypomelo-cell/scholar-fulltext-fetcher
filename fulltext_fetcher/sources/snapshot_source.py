"""snapshot 源:从本地快照 SQLite(由 ingest 灌入)按 DOI 查 OA PDF —— 零联网、零额度、零限速。

仅当 cfg.snapshot_db 指向存在的库时生效;否则返回 [](无开销)。置于源优先级最前,
命中即省去全部在线 API 调用,从根本上绕开免费 API 的额度/限速(且合规)。
"""
from __future__ import annotations

from typing import List

from .. import snapshot as snap
from ..models import Paper, PdfCandidate
from .base import BaseSource, SourceContext, register


@register
class Snapshot(BaseSource):
    name = "snapshot"

    def applicable(self, paper: Paper) -> bool:
        return bool(paper.doi)

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        db = getattr(ctx.cfg, "snapshot_db", None)
        if not db:
            return []
        rec = snap.lookup(db, paper.doi)
        if not rec:
            return []
        out: List[PdfCandidate] = []
        if rec.get("pdf_url"):
            out.append(PdfCandidate(rec["pdf_url"], self.name, "pdf", None, rec.get("oa_status"), 96))
        for u in (rec.get("all_pdfs") or []):
            out.append(PdfCandidate(u, self.name, "pdf", None, rec.get("oa_status"), 86))
        if rec.get("landing_url"):
            out.append(PdfCandidate(rec["landing_url"], self.name, "landing", None, rec.get("oa_status"), 34))
        return out
