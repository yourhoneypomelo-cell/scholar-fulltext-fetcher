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
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
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


def _dominant_reason(reasons: List[Optional[str]]) -> Optional[str]:
    """从多次下载失败原因中选出最具代表性的(出现次数最多)一个,用于 result.error 归因。

    无任何具体原因时返回 None(由调用方回退到通用串)。"""
    vals = [r for r in reasons if r]
    if not vals:
        return None
    return Counter(vals).most_common(1)[0][0]


# ── out_dir 并发写保护(batch7 教训:两次并发跑批写同一 out/ 会互相打断)────────────
# 用 out_dir/.lock 上的 OS 建议锁(Windows msvcrt / POSIX fcntl,仅标准库)保护输出目录:
# 属主进程存活期间独占该目录,崩溃/退出时由 OS 自动释放(不留死锁残留,优于"锁文件存在即占用")。
# 只锁 byte 0 作"锁位",pid/时间写在其后(offset>=1、未锁)便于冲突方读出属主。两平台锁都
# 不可用(极少见)时降级为不加锁,绝不因加锁本身阻断主流程。
def _lock_fd_nonblocking(fd: int) -> bool:
    """对已打开 fd 尝试非阻塞独占锁:成功 True;已被他人持有 False;无可用锁实现 True(降级)。"""
    try:
        import msvcrt
    except ImportError:
        msvcrt = None  # type: ignore[assignment]
    if msvcrt is not None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    try:
        import fcntl
    except ImportError:
        return True  # 两平台锁实现都不可用 → 降级为不加锁(不阻断主流程)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock_fd(fd: int) -> None:
    """释放 _lock_fd_nonblocking 加的锁(失败无妨:close / 进程退出时 OS 亦会释放)。"""
    try:
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    except ImportError:
        pass
    except OSError:
        return
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
    except Exception:  # noqa: BLE001
        pass


class Pipeline:
    def __init__(self, cfg: Any):
        self.cfg = cfg
        os.makedirs(cfg.out_dir, exist_ok=True)
        self.log = setup_logging(cfg.out_dir, cfg.log_level)
        # 并发写保护:抢占 out_dir 写锁(冲突→抛错快速失败),须在打开 attempts.jsonl 等产物之前。
        self._acquire_out_lock()
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
        # 默认(retry_failed=False):跳过上次已成功 + 上次"永久失败"的输入;临时失败(超时/5xx/
        # 连接等,见 _is_retriable_error)仍重跑。retry_failed=True 时只跳过已成功、所有失败都重跑。
        retry_failed = getattr(self.cfg, "retry_failed", False)
        if os.path.exists(self._meta_path):
            try:
                with open(self._meta_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        raw = rec.get("raw_input")
                        if raw is None:
                            continue
                        if rec.get("success"):
                            done.add(raw)
                        elif not retry_failed and not _is_retriable_error(rec.get("error")):
                            done.add(raw)
            except OSError:
                pass
        return done

    def _write_meta(self, result: FetchResult) -> None:
        line = json.dumps(result.to_dict(), ensure_ascii=False)
        with self._meta_lock:
            with open(self._meta_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def _acquire_out_lock(self) -> None:
        """抢占 out_dir 独占写锁,阻止另一进程并发写同一输出目录。

        batch7 并发撞车教训:两次并发跑批写同一 out/ 会交错 metadata.jsonl、覆盖/丢失
        summary.json(见 out/batch7 的 recover_note)。冲突(锁被另一存活进程持有)→ 抛
        RuntimeError 让第二个跑批快速失败,不去写坏第一个;锁机制自身任何异常一律降级放行
        (绝不因加锁失败而阻断正常单跑)。锁在进程退出/崩溃时由 OS 自动释放,不留死锁残留。"""
        self._lock_fd = None
        self._lock_path = os.path.join(self.cfg.out_dir, ".lock")
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(self._lock_path, flags, 0o644)
            if os.fstat(fd).st_size == 0:      # 确保有 1 个"锁位"字节,msvcrt 才能锁 byte 0
                os.write(fd, b"\0")
        except OSError as e:                   # 建不了锁文件(只读盘/权限等)→ 降级放行
            self.log.warning("无法创建输出目录锁 %s(降级为不加锁): %s", self._lock_path, e)
            return
        if _lock_fd_nonblocking(fd):
            self._lock_fd = fd
            try:                               # pid/时间写在锁位之后(offset>=1、未锁),便于冲突方读出
                os.lseek(fd, 1, os.SEEK_SET)
                os.write(fd, ("%d %s\n" % (os.getpid(),
                                           time.strftime("%Y-%m-%d %H:%M:%S"))).encode("utf-8"))
            except OSError:
                pass
            return
        owner = ""
        try:
            os.lseek(fd, 1, os.SEEK_SET)
            owner = os.read(fd, 128).decode("utf-8", "replace").split("\n", 1)[0].strip()
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        raise RuntimeError(
            "输出目录 %r 正被另一进程占用(锁属主: %s)。并发写同一 out/ 会互相打断 "
            "metadata/summary(batch7 教训);请改用不同的 -o 输出目录,或等对方结束后再跑。"
            % (self.cfg.out_dir, owner or "未知"))

    def _release_out_lock(self) -> None:
        """释放 out_dir 写锁(幂等):解锁 + 关闭 fd + 尽量删除 .lock 文件。"""
        fd = getattr(self, "_lock_fd", None)
        if fd is None:
            return
        _unlock_fd(fd)
        try:
            os.close(fd)
        except OSError:
            pass
        self._lock_fd = None
        try:
            os.remove(getattr(self, "_lock_path", "") or "")
        except OSError:
            pass

    def __del__(self):
        # 兜底释放:正常路径由 run() 收尾时释放;此处防 run() 未被调用 / 异常路径的 fd 泄漏。
        try:
            self._release_out_lock()
        except Exception:  # noqa: BLE001
            pass

    def _gather_and_download(self, paper: Paper, raw: str, idx: int, result: FetchResult) -> None:
        landing: List[Any] = []
        all_cands: List[Any] = []
        tried_urls: set = set()
        dl_errors: List[Optional[str]] = []  # 累积每次下载失败原因,用于失败归因 download-failed:<主因>
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
                                                  self.cfg, self.log, fallback_name=str(idx),
                                                  events=self.events)
                self.events.emit("download", raw=raw, doi=paper.doi, source=c.source,
                                 url=c.url, kind=c.kind, ok=bool(path), bytes=nbytes, error=derr)
                if path:
                    result.success = True
                    result.pdf_path = path
                    result.pdf_bytes = nbytes
                    result.source_used = c.source
                    result.pdf_url = c.url
                    return  # 短路:第一份成功的直链即停
                dl_errors.append(derr)

        if self.cfg.no_download:
            # success 表示"定位到候选";top 取全局最佳(直链优先、置信度高者)
            ranked = sorted(all_cands, key=lambda c: (c.is_direct(), c.confidence), reverse=True)
            result.success = bool(ranked)
            if ranked:
                top = ranked[0]
                result.pdf_url = top.url
                result.source_used = top.source
            elif not result.error:
                result.error = "no-candidates-located"  # 只定位模式:0 命中也给出原因,不在日志/report 里留空
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
                                                  self.cfg, self.log, fallback_name=str(idx),
                                                  events=self.events)
                self.events.emit("download", raw=raw, doi=paper.doi, source=c.source,
                                 url=c.url, kind=c.kind, ok=bool(path), bytes=nbytes, error=derr)
                if path:
                    result.success = True
                    result.pdf_path = path
                    result.pdf_bytes = nbytes
                    result.source_used = c.source
                    result.pdf_url = c.url
                    return
                dl_errors.append(derr)
        if not result.error:
            if result.candidates == 0:
                result.error = "no-candidates"          # 所有源零命中,连候选都没有
            else:
                reason = _dominant_reason(dl_errors)     # 有候选但下载全失败 → 归因到主因
                result.error = f"download-failed:{reason}" if reason else "no-downloadable-pdf"

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
            with self._res_lock:
                self._results.append(result)  # 与正常路径一致:解析失败也须计入结果,否则 summary/csv/report/results 会少算、成功率虚高
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

    def _browser_fallback_active(self) -> bool:
        """是否启用了任一"重、慢但合法"的浏览器/CF 兜底路径。

        这些路径(FlareSolverr 解 CF、render 渲染、有头浏览器下载、browser_search 源)单条合法耗时
        可达数分钟,须据此放大 straggler"无进展"阈值,避免误杀慢但合法的 CF 尾部条目。
        FlareSolverr 检测口径与 download._flaresolverr_enabled 保持一致(cfg 开关 / 端点 / 环境变量)。"""
        cfg = self.cfg
        if getattr(cfg, "use_flaresolverr", False) or getattr(cfg, "flaresolverr_url", None):
            return True
        if os.environ.get("FLARESOLVERR_URL"):
            return True
        if getattr(cfg, "render_fallback", False) or getattr(cfg, "browser_pdf_download", False):
            return True
        if getattr(cfg, "browser_capture", False):
            return True
        if os.environ.get("FTF_BROWSER_CAPTURE", "").strip().lower() in ("1", "true", "yes"):
            return True
        try:
            if any(getattr(s, "name", "") == "browser_search" for s in self.sources):
                return True
        except Exception:  # noqa: BLE001 - 源列表异常不致命,退化为"未启用"
            pass
        return False

    def _straggler_timeout(self) -> float:
        """尾部卡死看门狗的无进展阈值秒:一段时间内无任何输入完成即判定尾部卡死。
        优先取 cfg.item_timeout(若配置且 >0),否则按 per-request 超时保守放大——
        既容忍最慢的合法单条(多源回退 + 重试),又能兜住真正的无限卡死。

        **CF/浏览器兜底启用时**(FlareSolverr / render_fallback / browser_pdf_download / browser_search 源):
        单条合法耗时会因浏览器解 CF(flaresolverr_timeout_ms)、有头渲染等待、多候选逐个下载/重试
        而涨到数分钟。此时把"无进展"阈值显著放大(≥900s),避免把"慢但合法"的 CF 尾部条目误杀成
        straggler-timeout 假失败(会压低回收率);真卡死仍会在放大后的窗口兜住并照常收尾落盘。
        默认(无浏览器/CF 兜底)行为保持不变(max(180, timeout*8))。"""
        cfg_val = getattr(self.cfg, "item_timeout", 0) or 0
        try:
            cfg_val = float(cfg_val)
        except (TypeError, ValueError):
            cfg_val = 0.0
        if cfg_val > 0:
            return cfg_val
        base = float(getattr(self.cfg, "timeout", 30.0) or 30.0)
        if self._browser_fallback_active():
            fs_s = float(getattr(self.cfg, "flaresolverr_timeout_ms", 60000) or 60000) / 1000.0
            browser_wait = float(getattr(self.cfg, "browser_pdf_wait", 13.0) or 0.0)
            # 单条 CF 合法耗时 ≈ 数×(FS 解题 + 渲染等待 + 下载);取宽裕的"零进展=真卡死"窗口。
            return max(900.0, base * 30.0, (fs_s + browser_wait) * 6.0)
        return max(180.0, base * 8.0)

    def _record_straggler(self, raw: str) -> None:
        """把一条尾部卡死/被放弃的输入记为失败结果并落盘,使 summary/results.csv/report.html
        计入它;error 含 timeout(命中 _RETRIABLE_ERROR_HINTS)→ 续跑时会自动重试该条。"""
        result = FetchResult(raw_input=raw, error="straggler-timeout")
        try:
            result.kind = classify_input(raw).kind
        except Exception:  # noqa: BLE001 - 归类失败不致命
            pass
        self.events.emit("result", raw=raw, success=False, error="straggler-timeout")
        self._write_meta(result)
        with self._res_lock:
            self._results.append(result)

    def run(self, inputs: List[str]) -> Dict[str, Any]:
        run_t0 = time.time()
        todo = [r for r in inputs if r and r not in self._done]
        skipped = len(inputs) - len(todo)
        if skipped:
            self.log.info("断点续跑:跳过 %d 条已成功的输入", skipped)
        self.log.info("开始处理 %d 条输入,并发=%d,源=%s",
                      len(todo), self.cfg.concurrency, ",".join(s.name for s in self.sources))

        if todo:
            straggler_timeout = self._straggler_timeout()
            ex = ThreadPoolExecutor(max_workers=max(1, self.cfg.concurrency))
            futs = {ex.submit(self.process_one, raw, i): raw for i, raw in enumerate(todo)}
            try:
                pending = set(futs)
                while pending:
                    done, pending = wait(pending, timeout=straggler_timeout,
                                         return_when=FIRST_COMPLETED)
                    if not done:
                        # 尾部卡死看门狗:straggler_timeout 秒内零完成 → 判定卡死,记为失败并停止等待,
                        # 保证收尾必写 summary/metadata/csv/report(P1 无人值守:绝不因单条 straggler 整体挂起)。
                        self.log.error(
                            "尾部 %d 条在 %.0fs 内无任何进展,判定卡死(straggler);"
                            "记为失败并停止等待,继续收尾。", len(pending), straggler_timeout)
                        for f in pending:
                            f.cancel()  # 仅能取消尚未启动的;已卡在阻塞 IO 的线程无法强杀,但不再等它
                            self._record_straggler(futs[f])
                        break
                    for fut in done:
                        try:
                            fut.result()
                        except Exception as e:  # noqa: BLE001
                            self.log.error("处理 %s 失败: %s", futs[fut], e)
            except Exception as e:  # noqa: BLE001 - 并发调度阶段异常也绝不中断收尾(P1 无人值守)
                self.log.error("并发执行阶段异常,提前收尾并照常写出汇总: %s", e)
            finally:
                # 不等待卡死线程(wait=False);尽量取消未启动任务(老 Python 无 cancel_futures 时降级)。
                try:
                    ex.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    ex.shutdown(wait=False)

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
        self._release_out_lock()  # 收尾释放 out_dir 写锁(fd 关闭后 Windows 才能删除该目录)
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


if __name__ == "__main__":  # 离线 selftest(不联网): python -m fulltext_fetcher.pipeline
    # 回归锁定「尾部 straggler 看门狗 + 收尾必落盘」这条路径:
    # 用一个永不完成的 fake straggler 驱动 run(),断言即使有卡死条,run() 也会在
    # straggler_timeout 后停止等待、把卡死条记为 straggler-timeout 失败,并且
    # summary.json / metadata.jsonl / results.csv / report.html 一定被写出(P1 无人值守:
    # 绝不因单条 straggler 让整批挂起,收尾一定产出)。全程不联网(process_one 被替换)。
    import shutil
    import tempfile

    from .config import Config

    _tmp = tempfile.mkdtemp(prefix="ftf_pipe_selftest_")
    _release = threading.Event()  # 收尾时释放卡死线程,避免泄漏非守护线程(否则子进程退出会卡)
    try:
        _cfg = Config(out_dir=_tmp, concurrency=2, timeout=1.0)
        _cfg.sources = []          # 覆盖 process_one → 无需真实源,也杜绝任何联网
        _cfg.item_timeout = 1.0    # 让 _straggler_timeout() 取到 1s,秒级触发看门狗(默认 >=180s)
        _pipe = Pipeline(_cfg)

        assert abs(_pipe._straggler_timeout() - 1.0) < 1e-9, _pipe._straggler_timeout()

        # 回归:straggler 无进展阈值的 CF/浏览器感知分支(修「CF 重活下误杀合法尾部」)。
        # 复用 _pipe,临时改 cfg/sources 断言两分支后还原(还原到 item_timeout=1.0,不影响后续 run())。
        _saved_st = (_cfg.item_timeout, _cfg.use_flaresolverr, _cfg.timeout)
        _cfg.item_timeout = 0            # 关顶层 override,走保守放大逻辑
        _cfg.timeout = 30.0
        assert _pipe._browser_fallback_active() is False, "默认应视为未启用浏览器/CF 兜底"
        assert abs(_pipe._straggler_timeout() - 240.0) < 1e-9, _pipe._straggler_timeout()  # max(180, 30*8)
        _cfg.use_flaresolverr = True     # 启用 FlareSolverr → CF 感知放大 ≥900s
        assert _pipe._browser_fallback_active() is True
        assert _pipe._straggler_timeout() >= 900.0, _pipe._straggler_timeout()
        _cfg.use_flaresolverr = False

        class _FakeBrowserSrc:           # 经 browser_search 源也应触发放大
            name = "browser_search"
        _pipe.sources.append(_FakeBrowserSrc())
        assert _pipe._browser_fallback_active() is True
        assert _pipe._straggler_timeout() >= 900.0, _pipe._straggler_timeout()
        _pipe.sources.pop()
        (_cfg.item_timeout, _cfg.use_flaresolverr, _cfg.timeout) = _saved_st  # 还原
        assert abs(_pipe._straggler_timeout() - 1.0) < 1e-9, "还原后应回到 item_timeout=1.0"

        # 并发写保护:_pipe 已持有 out_dir 锁,另开 fd 对同一 .lock 应拿不到锁(第二个并发跑批据此快速失败)
        _fd_held = os.open(os.path.join(_tmp, ".lock"), os.O_RDWR | getattr(os, "O_BINARY", 0))
        try:
            assert _lock_fd_nonblocking(_fd_held) is False, "同 out_dir 并发不应能拿到第二把锁"
        finally:
            os.close(_fd_held)

        def _fake_process_one(raw: str, idx: int) -> FetchResult:
            if raw == "HANG":
                _release.wait(timeout=10)          # 阻塞过 straggler_timeout;末尾释放,10s 兜底防泄漏
                return FetchResult(raw_input=raw)  # 返回值被丢弃(该 future 已被看门狗放弃)
            # 正常快速成功:模拟真实 process_one 的「落盘 + 登记结果」
            _r = FetchResult(raw_input=raw, kind="doi", doi=raw, title="ok",
                             success=True, source_used="fake", pdf_bytes=1234)
            _pipe._write_meta(_r)
            with _pipe._res_lock:
                _pipe._results.append(_r)
            return _r

        _pipe.process_one = _fake_process_one  # type: ignore[assignment]

        _t0 = time.time()
        _summary = _pipe.run(["OK", "HANG"])
        _elapsed = time.time() - _t0

        # ① 看门狗必须远早于 10s 卡死就停止等待(证明没被 straggler 拖死整批)
        assert _elapsed < 8.0, "run() 未在 straggler_timeout 后及时收尾: %.1fs" % _elapsed
        # ② 正常条成功、卡死条记为失败,两条都计入 summary(不漏算、成功率不虚高)
        assert _summary["processed"] == 2, _summary
        assert _summary["success"] == 1, _summary
        assert _summary["miss"] == 1, _summary
        # ③ 收尾四件套一定被写出且非空
        for _fn in ("summary.json", "metadata.jsonl", "results.csv", "report.html"):
            _p = os.path.join(_tmp, _fn)
            assert os.path.isfile(_p) and os.path.getsize(_p) > 0, "缺失/空文件: %s" % _fn
        # ③b 并发写保护:run() 收尾必须已释放 out_dir 锁 → 可再次获锁(否则续跑/重试会被自锁挡死)
        _fd_free = os.open(os.path.join(_tmp, ".lock"),
                           os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0))
        try:
            if os.fstat(_fd_free).st_size == 0:
                os.write(_fd_free, b"\0")
            assert _lock_fd_nonblocking(_fd_free) is True, "run() 收尾后应已释放 out_dir 锁"
            _unlock_fd(_fd_free)
        finally:
            os.close(_fd_free)
        # ④ metadata 里卡死条被记为 straggler-timeout 失败,且命中续跑重试白名单;正常条为成功
        with open(os.path.join(_tmp, "metadata.jsonl"), "r", encoding="utf-8") as _f:
            _recs = [json.loads(_ln) for _ln in _f if _ln.strip()]
        _hang = [r for r in _recs if r.get("raw_input") == "HANG"]
        assert _hang and (not _hang[0]["success"]) and _hang[0]["error"] == "straggler-timeout", _recs
        assert _is_retriable_error(_hang[0]["error"]), "straggler-timeout 应可被续跑重试"
        _ok = [r for r in _recs if r.get("raw_input") == "OK"]
        assert _ok and _ok[0]["success"], _recs

        print("PIPELINE_OK")
    finally:
        _release.set()             # 释放卡死线程 → 其任务完成、线程退出,不泄漏(子进程可正常退出)
        time.sleep(0.2)
        shutil.rmtree(_tmp, ignore_errors=True)
