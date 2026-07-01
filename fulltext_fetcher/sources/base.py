"""源连接器基类与注册表。

每个源是一个 BaseSource 子类,实现 find_candidates(paper, ctx) -> List[PdfCandidate]。
约定:连接器内部必须吞掉自身异常并返回 [](由编排器统一计时与记录),
不要抛异常影响其它源——单源失败绝不能拖垮整条流水线。
"""
from __future__ import annotations

from typing import Any, Dict, List, Type

from ..models import Paper, PdfCandidate


class SourceContext:
    """传给连接器的运行上下文(共享 http client / 配置 / 日志)。"""

    def __init__(self, client: Any, config: Any, log: Any, events: Any):
        self.client = client
        self.cfg = config
        self.log = log
        self.events = events


class BaseSource:
    name: str = "base"
    requires_doi: bool = True  # 多数源以 DOI 为输入键

    def applicable(self, paper: Paper) -> bool:
        if self.requires_doi:
            return bool(paper.doi)
        return True

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        raise NotImplementedError


REGISTRY: Dict[str, Type[BaseSource]] = {}


def register(cls: Type[BaseSource]) -> Type[BaseSource]:
    REGISTRY[cls.name] = cls
    return cls
