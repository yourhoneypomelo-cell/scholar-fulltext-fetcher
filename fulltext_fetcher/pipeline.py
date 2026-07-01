"""编排器:输入 → 解析 → 多源回退定位 → 下载校验 → 落盘 + 结构化汇总。

策略(兼顾高成功率与高速率):
- 并发:ThreadPoolExecutor 跨输入并行;共享 HttpClient 做按域限速,既快又不触发风控。
- 单条内按源优先级回退:逐源拿候选,直链(pdf/render)即时尝试下载,一旦成功就短路停止
  (省掉后续源的请求 = 提速);落地页候选累积到最后再兜底尝试。
- 断点续跑:已成功的输入(读 out/metadata.jsonl)默认跳过。
- 全程结构化事件落 attempts.jsonl,跑完读 summary.json 即可判断效果。
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from .download import download_pdf
from .http_client import HttpClient
from .logsetup import EventLog, setup_logging
from .models import Attempt, FetchResult, Paper
from .resolve import classify_input, resolve_to_paper
from .sources import build_sources
from .sources.base import SourceContext


# 断点续跑时视为"临时/可恢复"的失败:这些重跑值得重试,其余失败默认视为永久而跳过。
_RETRIABLE_ERROR_HINTS = (
    "no-response", "retries-exhausted", "timeout", "timed out",
    "http-429", "http-5", "exception", "connection",
)


def _is_retriable_error(err: Optional[str]) -> bool:
    """最终 error 是否属于"临时失败"(值得续跑重试);其余视为永久。"""
    if not err:
        return False
    e = err.lower()
    return any(h in e for h in _RETRIABLE_ERROR_HINTS)


class Pipeline:
    def __init__(self, cfg: Any):
        self.cfg = cfg
        os.makedirs(cfg.out_dir, exist_ok=True)
        self.log = setup_logging(cfg.out_dir, cfg.log_level)
        self.events = EventLog(os.path.join(cfg.out_dir, "attempts.jsonl"))
        self.client = HttpClient(cfg, self.log)
        self.client.set_host_interval("export.arxiv.org", 3.0)  # arXiv API 要求 >=3s/次
        self.sources = build_sources(cfg)
        self.ctx = SourceContext(self.client, cfg, self.log, self.events)
        self.pdf_dir = os.path.join(cfg.out_dir, "pdfs")
        self._meta_path = os.path.join(cfg.out_dir, "metadata.jsonl")
        self._meta_lock = threading.Lock()
        self._results: List[FetchResult] = []
        self._res_lock = threading.Lock()
        self._done = self._load_done()

    @property
    def results(self) -> List[FetchResult]:
        """本次运行已得到的结果(供编程接口/父程序读取)。"""
        with self._res_lock:
            return list(self._results)

    def _load_done(self) -> set:
        done = set()
        if not getattr(self.cfg, "resume", True):
            return done
        if os.path.exists(self._meta_path):
            try:
                with open(self._meta_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        if rec.get("success"):
                            done.add(rec.get("raw_input"))
            except OSError:
                pass
        return done

    def _write_meta(self, result: FetchResult) -> None:
        line = json.dumps(result.to_dict(), ensure_ascii=False)
        with self._meta_lock:
            with open(self._meta_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def _gather_and_download(self, paper: Paper, raw: str, idx: int, result: FetchResult) -> None:
        landing: List[Any] = []
        all_cands: List[Any] = []
        tried_urls: set = set()
        for src in self.sources:
            if not src.applicable(paper):
                continue
            t = time.time()
            err: Optional[str] = None
            try:
                cands = src.find_candidates(paper, self.ctx) or []
            except Exception as e:  # noqa: BLE001
                cands, err = [], str(e)
            dt = int((time.time() - t) * 1000)
            result.attempts.append(Attempt(src.name, bool(cands), len(cands), dt, err))
            self.events.emit("source", raw=raw, doi=paper.doi, source=src.name,
                             ok=bool(cands), n=len(cands), ms=dt, error=err)
            result.candidates += len(cands)
            all_cands.extend(cands)

            direct = sorted([c for c in cands if c.is_direct()],
                            key=lambda c: c.confidence, reverse=True)
            landing.extend([c for c in cands if not c.is_direct()])

            if self.cfg.no_download:
                continue
            for c in direct:
                if c.url in tried_urls:
                    continue
                tried_urls.add(c.url)
                path, nbytes, derr = download_pdf(c, paper, self.pdf_dir, self.client,
                                                  self.cfg, self.log, fallback_name=str(idx))
                self.events.emit("download", raw=raw, doi=paper.doi, source=c.source,
                                 url=c.url, kind=c.kind, ok=bool(path), bytes=nbytes, error=derr)
                if path:
                    result.success = True
                    result.pdf_path = path
                    result.pdf_bytes = nbytes
                    result.source_used = c.source
                    result.pdf_url = c.url
                    return  # 短路:第一份成功的直链即停

        if self.cfg.no_download:
            # success 表示"定位到候选";top 取全局最佳(直链优先、置信度高者)
            ranked = sorted(all_cands, key=lambda c: (c.is_direct(), c.confidence), reverse=True)
            result.success = bool(ranked)
            if ranked:
                top = ranked[0]
                result.pdf_url = top.url
                result.source_used = top.source
            self.events.emit("located", raw=raw, doi=paper.doi, candidates=result.candidates,
                             top=(ranked[0].url if ranked else None))
            return

        # 兜底:尝试落地页候选(可能 302 到真实 PDF)
        if not self.cfg.oa_only:
            for c in sorted(landing, key=lambda c: c.confidence, reverse=True):
                if c.url in tried_urls:
                    continue
                tried_urls.add(c.url)
                path, nbytes, derr = download_pdf(c, paper, self.pdf_dir, self.client,
                                                  self.cfg, self.log, fallback_name=str(idx))
                self.events.emit("download", raw=raw, doi=paper.doi, source=c.source,
                                 url=c.url, kind=c.kind, ok=bool(path), bytes=nbytes, error=derr)
                if path:
                    result.success = True
                    result.pdf_path = path
                    result.pdf_bytes = nbytes
                    result.source_used = c.source
                    result.pdf_url = c.url
                    return
        if not result.error:
            result.error = "no-downloadable-pdf"

    def process_one(self, raw: str, idx: int) -> FetchResult:
        t0 = time.time()
        work = classify_input(raw)
        result = FetchResult(raw_input=raw, kind=work.kind)
        self.events.emit("input", raw=raw, kind=work.kind, value=work.value)
        try:
            paper = resolve_to_paper(work, self.client, self.log, self.cfg)
        except Exception as e:  # noqa: BLE001
            result.error = f"resolve-failed:{e}"
            result.elapsed_ms = int((time.time() - t0) * 1000)
            self.events.emit("resolve_error", raw=raw, error=str(e))
            self._write_meta(result)
            return result

        result.doi = paper.doi
        result.title = paper.title
        self.events.emit("resolved", raw=raw, doi=paper.doi, title=paper.title,
                         arxiv=paper.arxiv_id, pmcid=paper.pmcid, via=paper.resolved_via)
        if not (paper.doi or paper.arxiv_id or paper.title):
            result.error = "unresolvable-input"
        else:
            self._gather_and_download(paper, raw, idx, result)

        result.elapsed_ms = int((time.time() - t0) * 1000)
        self.events.emit("result", raw=raw, doi=paper.doi, success=result.success,
                         source=result.source_used, ms=result.elapsed_ms, error=result.error)
        self.log.info("[%s] %s -> %s (%s, %dms)", "OK" if result.success else "MISS",
                      (result.doi or result.title or raw)[:70],
                      result.source_used or result.error, result.kind, result.elapsed_ms)
        self._write_meta(result)
        with self._res_lock:
            self._results.append(result)
        return result

    def run(self, inputs: List[str]) -> Dict[str, Any]:
        run_t0 = time.time()
        todo = [r for r in inputs if r and r not in self._done]
        skipped = len(inputs) - len(todo)
        if skipped:
            self.log.info("断点续跑:跳过 %d 条已成功的输入", skipped)
        self.log.info("开始处理 %d 条输入,并发=%d,源=%s",
                      len(todo), self.cfg.concurrency, ",".join(s.name for s in self.sources))

        if todo:
            with ThreadPoolExecutor(max_workers=max(1, self.cfg.concurrency)) as ex:
                futs = {ex.submit(self.process_one, raw, i): raw for i, raw in enumerate(todo)}
                for fut in as_completed(futs):
                    try:
                        fut.result()
                    except Exception as e:  # noqa: BLE001
                        self.log.error("处理 %s 失败: %s", futs[fut], e)

        summary = self._summary(run_t0, len(inputs), skipped)
        with open(os.path.join(self.cfg.out_dir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        try:
            from . import report
            report.write_results_csv(self._results, os.path.join(self.cfg.out_dir, "results.csv"))
            report.write_summary_html(summary, self._results,
                                      os.path.join(self.cfg.out_dir, "report.html"))
        except Exception as e:  # noqa: BLE001 - 报表生成失败不应影响主流程
            self.log.warning("生成 results.csv/report.html 失败: %s", e)
        self.events.close()
        self.log.info("完成。成功 %d/%d (%.0f%%),用时 %.1fs。详见 %s",
                      summary["success"], summary["processed"],
                      100 * summary["success_rate"], summary["elapsed_sec"], self.cfg.out_dir)
        return summary

    def _summary(self, run_t0: float, total_inputs: int, skipped: int) -> Dict[str, Any]:
        res = self._results
        success = sum(1 for r in res if r.success)
        by_source: Dict[str, int] = {}
        for r in res:
            if r.success and r.source_used:
                by_source[r.source_used] = by_source.get(r.source_used, 0) + 1
        processed = len(res)
        return {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_inputs": total_inputs,
            "skipped_resume": skipped,
            "processed": processed,
            "success": success,
            "miss": processed - success,
            "success_rate": (success / processed) if processed else 0.0,
            "by_source": dict(sorted(by_source.items(), key=lambda kv: kv[1], reverse=True)),
            "elapsed_sec": round(time.time() - run_t0, 1),
            "no_download": self.cfg.no_download,
            "oa_only": self.cfg.oa_only,
        }
