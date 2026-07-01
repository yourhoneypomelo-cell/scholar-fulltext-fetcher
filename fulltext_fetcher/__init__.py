"""fulltext_fetcher — 输入 DOI/标题，全自动榨干全网可及免费全文资源并下载入库。

设计目标(对应北极星目标):
- 输入 DOI / 标题(单条、多条或批量文件) → 解析元数据 → 多源回退定位 OA 全文 → 校验下载入库。
- 全局程序化 + 日志驱动:运行程序 + 读结构化日志(attempts.jsonl / summary.json)即可判断效果并迭代,无需人工逐步介入。
- 高成功率(13+ 免费源回退 + 直链优先打分 + 落地页校验)+ 高速率(按域限速的并发)。

主要模块:
- config:运行配置          - models:数据结构
- logsetup:结构化日志       - http_client:带重试/限速/校验的 HTTP
- resolve:输入→元数据       - sources/*:各源连接器
- download:下载与 PDF 校验   - pipeline:编排器   - cli:命令行入口
"""

__version__ = "1.0.0"

# 公共编程接口(供父程序接入/交接,见 接入与交接说明.md)
from .config import Config, DEFAULT_SOURCE_ORDER
from .models import FetchResult, Paper, PdfCandidate, Attempt, WorkInput
from .api import FullTextFetcher, fetch_one, fetch_many

__all__ = [
    "__version__",
    "Config",
    "DEFAULT_SOURCE_ORDER",
    "FetchResult",
    "Paper",
    "PdfCandidate",
    "Attempt",
    "WorkInput",
    "FullTextFetcher",
    "fetch_one",
    "fetch_many",
]
