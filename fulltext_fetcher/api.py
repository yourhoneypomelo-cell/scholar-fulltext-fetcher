"""对外编程接口(供本程序作为"子程序"被父任务接入 / 交接)。

两种接入方式:
  1) Python 导入(同进程,拿到结构化对象):
        from fulltext_fetcher import fetch_one, fetch_many, FullTextFetcher, Config
        r = fetch_one("10.7717/peerj.4375", email="you@uni.edu")
        print(r.success, r.pdf_path, r.source_used)
  2) 子进程 CLI(跨语言,拿 JSON):
        python -m fulltext_fetcher "10.7717/peerj.4375" --email you@uni.edu --print-json
     stdout 输出 {"summary": {...}, "results": [FetchResult, ...]};日志走 stderr/文件。

返回对象:见 models.FetchResult(可 .to_dict() 转 JSON)。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .config import Config
from .models import FetchResult
from .pipeline import Pipeline


def _make_config(config: Optional[Config], overrides: Dict[str, Any]) -> Config:
    cfg = config or Config()
    for k, v in overrides.items():
        if not hasattr(cfg, k):
            raise TypeError(f"未知配置项: {k}")
        setattr(cfg, k, v)
    return cfg


class FullTextFetcher:
    """可复用抓取器:构造一次,多次调用(父程序持有它批量处理)。

    用法:
        with FullTextFetcher(email="you@uni.edu", out_dir="out", concurrency=8) as ft:
            results, summary = ft.fetch_many(["10.x/y", "some title"])
    """

    def __init__(self, config: Optional[Config] = None, **overrides: Any):
        self.config = _make_config(config, overrides)
        self._pipe = Pipeline(self.config)

    def fetch_many(self, inputs: List[str]) -> Tuple[List[FetchResult], Dict[str, Any]]:
        summary = self._pipe.run(list(inputs))
        return self._pipe.results, summary

    def fetch_one(self, item: str) -> FetchResult:
        """单条抓取,始终返回 FetchResult(不受断点续跑跳过影响)。"""
        return self._pipe.process_one(item, 0)

    def close(self) -> None:
        try:
            self._pipe.events.close()
        except Exception:
            pass

    def __enter__(self) -> "FullTextFetcher":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def fetch_many(
    inputs: List[str], config: Optional[Config] = None, **overrides: Any
) -> Tuple[List[FetchResult], Dict[str, Any]]:
    """一次性批量抓取,返回 (结果列表, 汇总 dict)。"""
    ft = FullTextFetcher(config, **overrides)
    try:
        return ft.fetch_many(inputs)
    finally:
        ft.close()


def fetch_one(item: str, config: Optional[Config] = None, **overrides: Any) -> FetchResult:
    """一次性单条抓取,返回 FetchResult。"""
    ft = FullTextFetcher(config, **overrides)
    try:
        return ft.fetch_one(item)
    finally:
        ft.close()
