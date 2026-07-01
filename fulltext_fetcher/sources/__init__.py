"""源连接器子包。导入各连接器模块以注册到 REGISTRY。"""
from __future__ import annotations

from typing import Any, List

from .base import REGISTRY, BaseSource, SourceContext, register  # noqa: F401
from . import snapshot_source  # noqa: F401  (导入触发注册)
from . import aggregators  # noqa: F401
from . import repositories  # noqa: F401
from . import green_oa  # noqa: F401
from . import scihub  # noqa: F401


def build_sources(cfg: Any) -> List[BaseSource]:
    """按 cfg.sources 顺序构建已启用的连接器实例。"""
    out: List[BaseSource] = []
    for name in cfg.sources:
        cls = REGISTRY.get(name)
        if cls is None:
            continue
        out.append(cls())
    return out
