"""谷歌学术爬虫子系统 fulltext_fetcher/scholar/。

目标：输入标题/DOI → 避免或自动过人机验证 → 抓元数据 + Scholar 可及 PDF 链接
→ 下载为文件名标准化的原文 → 全程程序化、结构化日志闭环。

本子包在《谷歌学术爬虫-架构与选型.md》（ARCH 产出）指导下分模块实现：
query / serp / fetcher / proxy / captcha / download / naming / pipeline / cli 等。
接口以架构文档为准；本文件在地基（models/config/logsetup）就绪后 re-export 冻结契约，
便于 `from fulltext_fetcher.scholar import ScholarResult, ScholarConfig` 等直用。
"""
from __future__ import annotations

from .config import ScholarConfig
from .models import (
    FetchOutcome,
    ScholarFetchResult,
    ScholarQuery,
    ScholarResult,
    SerpPage,
)

__all__ = [
    "ScholarConfig",
    "ScholarResult",
    "ScholarQuery",
    "SerpPage",
    "FetchOutcome",
    "ScholarFetchResult",
]
