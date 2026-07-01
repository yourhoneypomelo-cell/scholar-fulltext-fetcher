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
    # 先关闭旧 handler 再清空:同一命名 logger 被多次 setup(多 Pipeline / 测试反复建实例)时,
    # 仅 clear() 会把旧 FileHandler 从列表摘除却不关闭其文件句柄,导致 run.log 句柄泄漏
    # (Windows 上还会锁住 out_dir 妨碍清理)。
    for h in logger.handlers[:]:
        try:
            h.close()
        except Exception:  # noqa: BLE001 - 关闭旧 handler 不得影响重新初始化日志
            pass
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    # run.log 强制 UTF-8 写入(errors=backslashreplace 兜底:极端不可编码字符降级为转义,
    # 绝不因编码抛错或写坏,保证"跑完读日志判断"始终可读)。
    fh = logging.FileHandler(os.path.join(out_dir, "run.log"), encoding="utf-8",
                             errors="backslashreplace")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 控制台:优先 UTF-8;errors=backslashreplace 做平台安全降级——在 Windows cp936/GBK 等终端上
    # 不因不可编码字符崩溃(reconfigure 不可用时静默退回原编码,由 logging 自身容错兜底)。
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")  # type: ignore[attr-defined]
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
