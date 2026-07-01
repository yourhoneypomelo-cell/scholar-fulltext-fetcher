"""可选源:Sci-Hub。默认关闭(--enable-scihub 开启)。

⚠️ 合规警告:Sci-Hub 提供未经授权的版权内容,在多数司法辖区不合法,且违反出版商条款。
本项目主线是"走开放获取正门"(Unpaywall/OpenAlex 等),Sci-Hub 仅作为研究用途的最后兜底,
默认禁用。开启与使用所产生的法律/合规风险由使用者自负。

实现说明:Sci-Hub 的 PDF 通常嵌在 HTML 落地页(<embed>/<iframe> 的 src),
需解析 HTML 才能取到真实 PDF 直链。这里做一次轻量解析;解析失败则返回落地页候选。
"""
from __future__ import annotations

import re
from typing import List

from ..models import Paper, PdfCandidate
from .base import BaseSource, SourceContext, register

_EMBED_RE = re.compile(r'(?:src|href)\s*=\s*["\']([^"\']+\.pdf[^"\']*)["\']', re.I)


@register
class SciHub(BaseSource):
    name = "scihub"

    def applicable(self, paper: Paper) -> bool:
        return bool(paper.doi)

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        if not getattr(ctx.cfg, "enable_scihub", False):
            return []
        mirror = (getattr(ctx.cfg, "scihub_mirror", None) or "").rstrip("/")
        if not mirror:
            return []  # 启用但镜像未配置:优雅降级,避免用 None 拼出非法 URL 而崩溃
        url = f"{mirror}/{paper.doi}"
        try:
            r = ctx.client.get(url)
        except Exception:  # noqa: BLE001
            return []
        if r is None or r.status_code != 200:
            return []
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "application/pdf" in ctype:
            return [PdfCandidate(url, self.name, "pdf", None, None, 40)]
        m = _EMBED_RE.search(r.text or "")
        if m:
            pdf_url = m.group(1)
            if pdf_url.startswith("//"):
                pdf_url = "https:" + pdf_url
            elif pdf_url.startswith("/"):
                pdf_url = mirror + pdf_url
            return [PdfCandidate(pdf_url, self.name, "pdf", None, None, 40)]
        return []
