"""日志:人类可读日志(run.log + 控制台) + 结构化事件流(JSONL)。

结构化事件是"日志驱动调试"的核心:每条输入、每次源尝试、每次下载都会落一行 JSON,
程序跑完后只需读 attempts.jsonl / summary.json 即可判断效果并定位问题,无需人工逐步盯。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from typing import Any


def setup_logging(out_dir: str, level: str = "INFO") -> logging.Logger:
    os.makedirs(out_dir, exist_ok=True)
    logger = logging.getLogger("fulltext_fetcher")
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    fh = logging.FileHandler(os.path.join(out_dir, "run.log"), encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 控制台:尽量用 UTF-8,避免 Windows GBK 终端中文乱码(不影响文件输出)。
    try:
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    ch = logging.StreamHandler(sys.stderr)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger


class EventLog:
    """线程安全的 JSONL 事件写入器。"""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._f = open(path, "a", encoding="utf-8")

    def emit(self, event: str, **fields: Any) -> None:
        rec = {"ts": round(time.time(), 3), "event": event}
        rec.update(fields)
        line = json.dumps(rec, ensure_ascii=False)
        with self._lock:
            self._f.write(line + "\n")
            self._f.flush()

    def close(self) -> None:
        try:
            with self._lock:
                self._f.close()
        except Exception:
            pass
