"""核心数据结构。全部用 dataclass,便于序列化进结构化日志。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class WorkInput:
    """一条输入及其判定类型。"""
    raw: str
    kind: str          # 'doi' | 'title' | 'arxiv'
    value: str


@dataclass
class Paper:
    """解析后的论文元数据(尽力填充,字段可空)。"""
    doi: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = field(default_factory=list)
    arxiv_id: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    is_oa: Optional[bool] = None
    oa_status: Optional[str] = None
    journal: Optional[str] = None
    resolved_via: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PdfCandidate:
    """某个源给出的一个候选全文链接。"""
    url: str
    source: str
    kind: str = "pdf"          # 'pdf'(直链) | 'render'(渲染端点) | 'landing'(落地页) | 'file'
    version: Optional[str] = None
    license: Optional[str] = None
    confidence: int = 50       # 0-100,直链高、落地页低;用于排序

    def is_direct(self) -> bool:
        return self.kind in ("pdf", "render")


@dataclass
class Attempt:
    """对某个源的一次查询记录(用于 attempts.jsonl 调试)。"""
    source: str
    ok: bool                   # 该源是否给出至少一个候选
    n_candidates: int
    elapsed_ms: int
    error: Optional[str] = None


@dataclass
class FetchResult:
    """一条输入的最终结果。"""
    raw_input: str
    kind: Optional[str] = None
    doi: Optional[str] = None
    title: Optional[str] = None
    success: bool = False
    pdf_path: Optional[str] = None
    pdf_bytes: int = 0
    source_used: Optional[str] = None
    pdf_url: Optional[str] = None
    candidates: int = 0
    attempts: List[Attempt] = field(default_factory=list)
    elapsed_ms: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
