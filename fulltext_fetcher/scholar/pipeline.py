"""§3.10 编排层:把各模块串成端到端流水线并汇总产物。

单条流程(process_one):
  query.build_query → fetcher.fetch_serp →(serpapi 走 serp.parse_serpapi / 自建走 serp.parse_serp)
  → query.title_match_score 选最相关 → download.download_result_pdf →(未果且开启)download.oa_fallback
  → naming.build_filename 落盘 out_scholar/pdfs/ → 结构化事件 + 记 ScholarFetchResult。
批量(run):断点续跑读 metadata.jsonl(仅跳过已成功);末尾写 summary.json,并复用父包
fulltext_fetcher.report 写 results.csv / report.html。concurrency 默认 1(串行,强合规)。

设计:重依赖(fetcher/download/naming/proxy/http_client/resolve/report)一律**方法内延迟导入**,
使 `import pipeline` 与无输入用法保持轻量、且对并发在建模块健壮。ctx 鸭子兼容 fetcher.FetchContext
(cfg/proxy/log/events/engines)与 download 的期望(client/cfg/log/events/pdf_dir)。

合规:默认代理/打码/Sci-Hub 全关、串行强限速;直抓 Scholar 属灰色,使用者自负(见 fetcher 头部)。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from .config import ScholarConfig
from .logsetup import (
    EVENT_CAPTCHA,
    EVENT_PROXY_ROTATE,
    EVENT_QUERY,
    EVENT_RESULT,
    EVENT_SERP_PARSED,
    EventLog,
    setup_logging,
)
from .models import ScholarFetchResult

# 低置信标题选择事件名(_select_best 回退 SERP 第一条时记录;本层内部事件,非 logsetup 冻结集)。
_EVENT_SELECT = "select"

# §6 事件分流:抓取类事件写 serp.jsonl,下载/兜底类写 attempts.jsonl。
_SERP_JSONL_EVENTS = frozenset({
    "query", "serp_fetch", "serp_parsed", "block", "captcha", "proxy_rotate",
    "result", _EVENT_SELECT,
})


class _EventRouter:
    """按事件名把抓取类事件路由到 serp.jsonl、其余(download/oa_fallback)到 attempts.jsonl。

    对 fetcher/download 暴露统一的 emit(event, **fields);底层两个 EventLog 各自线程安全。
    任何写入异常都被吞掉,绝不影响主流程。
    """

    def __init__(self, attempts_log: Any, serp_log: Any) -> None:
        self._attempts = attempts_log
        self._serp = serp_log
        # 轻量运行期计数器:emit 时按事件名累加,run() 末尾注入 summary(真实计数,替代硬编码 0)。
        self.captcha_solved = 0             # captcha 事件 ok=True 次数
        self.proxy_rotations = 0            # proxy_rotate 事件次数
        self.low_confidence_selections = 0  # select 事件 low_confidence=True 次数

    def emit(self, event: str, **fields: Any) -> None:
        try:
            if event == EVENT_CAPTCHA:
                if fields.get("ok") is True:
                    self.captcha_solved += 1
            elif event == EVENT_PROXY_ROTATE:
                self.proxy_rotations += 1
            elif event == _EVENT_SELECT and fields.get("low_confidence") is True:
                self.low_confidence_selections += 1
        except Exception:  # noqa: BLE001 - 计数异常绝不能影响事件落盘
            pass
        target = self._serp if event in _SERP_JSONL_EVENTS else self._attempts
        try:
            target.emit(event, **fields)
        except Exception:  # noqa: BLE001 - 事件落盘失败绝不能拖垮抓取/下载
            pass

    def close(self) -> None:
        for lg in (self._serp, self._attempts):
            try:
                lg.close()
            except Exception:  # noqa: BLE001
                pass


class ScholarContext:
    """运行期共享对象容器(鸭子兼容 fetcher.FetchContext 与 download 的 ctx 期望)。

    属性:cfg / log / events / client / proxy / engines / pdf_dir。
    """

    def __init__(self, cfg: Any, *, log: Any = None, events: Any = None, client: Any = None,
                 proxy: Any = None, engines: Any = None, pdf_dir: Optional[str] = None) -> None:
        self.cfg = cfg
        self.log = log
        self.events = events
        self.client = client
        self.proxy = proxy
        self.engines = engines
        self.pdf_dir = pdf_dir


class ScholarPipeline:
    """Scholar 抓取→下载编排(默认串行强合规)。

    注入点(测试/复用用,默认自动装配):engines(引擎表)、client(HttpClient)、proxy(ProxyPool)。
    """

    def __init__(self, cfg: ScholarConfig, *, engines: Any = None, client: Any = None,
                 proxy: Any = None) -> None:
        self.cfg = cfg
        self._engines = engines            # None → fetcher.default_engines()
        self._client = client              # None → 构造父包 HttpClient
        self._proxy = proxy                # None → load_proxy_pool(cfg)
        self.ctx: Optional[ScholarContext] = None
        self.results: List[Any] = []
        self._taken: set = set()           # 跨输入的文件名去重集合

    # ────────────────────── 上下文装配 ──────────────────────
    def _build_context(self) -> ScholarContext:
        if self.ctx is not None:
            return self.ctx
        cfg = self.cfg
        out_dir = getattr(cfg, "out_dir", None) or "out_scholar"
        pdf_dir = os.path.join(out_dir, "pdfs")
        os.makedirs(pdf_dir, exist_ok=True)     # 顺带建 out_dir
        log = setup_logging(out_dir, getattr(cfg, "log_level", "INFO"))
        events = _EventRouter(EventLog(os.path.join(out_dir, "attempts.jsonl")),
                              EventLog(os.path.join(out_dir, "serp.jsonl")))
        proxy = self._proxy
        if proxy is None:
            try:
                from .proxy import load_proxy_pool
                proxy = load_proxy_pool(cfg)
            except Exception:  # noqa: BLE001 - 代理装配失败退化为直连
                proxy = None
        client = self._client if self._client is not None else self._make_client(log)
        self.ctx = ScholarContext(cfg, log=log, events=events, client=client,
                                  proxy=proxy, engines=self._engines, pdf_dir=pdf_dir)
        return self.ctx

    def _make_client(self, log: Any) -> Any:
        """由 ScholarConfig 派生父包 Config 并构造 HttpClient;失败返回 None(下载/兜底会优雅失败)。"""
        try:
            from ..config import Config as ParentConfig
            from ..http_client import HttpClient
            pc = ParentConfig(
                email=getattr(self.cfg, "email", None) or "anonymous@example.com",
                out_dir=getattr(self.cfg, "out_dir", None) or "out_scholar",
                timeout=getattr(self.cfg, "timeout", 30.0),
                max_retries=getattr(self.cfg, "max_retries", 3),
                min_pdf_bytes=getattr(self.cfg, "min_pdf_bytes", 1024),
                max_pdf_bytes=getattr(self.cfg, "max_pdf_bytes", 80 * 1024 * 1024),
                enable_scihub=getattr(self.cfg, "enable_scihub", False),
            )
            return HttpClient(pc, log)
        except Exception:  # noqa: BLE001
            return None

    # ────────────────────── 单条处理 ──────────────────────
    def process_one(self, raw: str, idx: int) -> ScholarFetchResult:
        from . import serp as serp_mod
        from .fetcher import fetch_serp
        from .query import build_query, title_match_score

        ctx = self._build_context()
        t0 = time.time()
        fr = ScholarFetchResult(raw_input=raw)

        try:
            q = build_query(raw, self.cfg)
        except Exception as e:  # noqa: BLE001 - 空输入等 → 记失败,不中断整批
            fr.error = f"query-error: {e}"
            fr.elapsed_ms = int((time.time() - t0) * 1000)
            self._emit_result(ctx, fr)
            return fr

        fr.kind = q.kind
        fr.query = q.q
        if q.kind == "doi":
            fr.doi = q.q
        else:
            fr.title = q.q
        ctx.events.emit(EVENT_QUERY, raw=raw, kind=q.kind, q=q.q)

        # 取回 SERP(分层降级 + 反爬由 fetcher 内部处理)
        out = fetch_serp(q, ctx)
        fr.engine_used = getattr(out, "engine", None)
        self._save_serp_snapshot(idx, out)      # 原始 SERP HTML 落盘(ARCH §6),便于校对选择器/复盘

        results: List[Any] = []
        blocked = False
        has_next = False
        if out is not None and getattr(out, "ok", False) and getattr(out, "html", None):
            if (getattr(out, "engine", "") or "") == "serpapi":
                results = self._parse_serpapi(out.html, serp_mod)
            else:
                page = serp_mod.parse_serp(out.html)
                results, blocked, has_next = page.results, page.blocked, page.has_next
        if out is not None and (getattr(out, "blocked", False) or getattr(out, "captcha", False)):
            blocked = True
        fr.blocked = blocked
        fr.n_results = len(results)
        ctx.events.emit(EVENT_SERP_PARSED, n=len(results), has_next=has_next)

        if not results:
            fr.error = "blocked" if blocked else (getattr(out, "error", None) or "no-results")
            fr.elapsed_ms = int((time.time() - t0) * 1000)
            self._emit_result(ctx, fr)
            return fr

        best = self._select_best(results, q, title_match_score)
        fr.cited_by = getattr(best, "cited_by", None)
        if getattr(best, "doi", None):
            fr.doi = best.doi
        if getattr(best, "title", None):
            fr.title = best.title
        fr.pdf_url = (getattr(best, "pdf_links", None) or [None])[0]

        paper = self._build_paper(best, q)

        # ① 结果自带 PDF 直链
        path, nbytes, err = self._download(best, paper, ctx, idx)
        source = "scholar-pdf"
        # ② 未果 → OA 兜底(复用父包 OA 源;先 best-effort 富化补 DOI 提升命中)
        if not path and getattr(self.cfg, "oa_fallback", False):
            paper = self._maybe_enrich_for_oa(paper, best, ctx)
            path, nbytes, oerr = self._oa_fallback(paper, ctx, idx)
            if path:
                source = getattr(paper, "resolved_via", None) or "oa"
                source = f"oa:{source}" if not str(source).startswith("oa") else source
            else:
                err = err or oerr

        if path:
            fr.success = True
            fr.pdf_bytes = nbytes
            fr.source_used = source
            fr.pdf_path = self._finalize_name(path, best, paper, idx, ctx)
        else:
            fr.error = err or "no-pdf"

        fr.elapsed_ms = int((time.time() - t0) * 1000)
        self._emit_result(ctx, fr)
        return fr

    # ────────────────────── 批量运行 ──────────────────────
    def run(self, inputs: List[str]) -> Dict[str, Any]:
        ctx = self._build_context()
        cfg = self.cfg
        out_dir = getattr(cfg, "out_dir", None) or "out_scholar"
        meta_path = os.path.join(out_dir, "metadata.jsonl")
        t0 = time.time()

        done = self._load_done(meta_path) if getattr(cfg, "resume", True) else {}
        self.results = []
        processed = 0
        skipped = 0
        seen: set = set()
        try:
            for i, raw in enumerate(inputs):
                if raw in seen:
                    continue
                seen.add(raw)
                if raw in done:                      # 断点续跑:已成功者直接沿用
                    self.results.append(done[raw])
                    skipped += 1
                    continue
                fr = self.process_one(raw, i)
                self.results.append(fr)
                self._append_metadata(meta_path, fr)
                processed += 1
        finally:
            summary = self._summarize(self.results, total=len(inputs), skipped=skipped,
                                      processed=processed, elapsed=int(time.time() - t0))
            self._write_reports(summary, self.results, out_dir)
            self._close(ctx)
        return summary

    # ────────────────────── 内部工具 ──────────────────────
    def _parse_serpapi(self, html_str: str, serp_mod: Any) -> List[Any]:
        """SerpApi 旁路:fetcher 把响应 JSON 串放 outcome.html;此处解析为 List[ScholarResult]。"""
        try:
            data = json.loads(html_str)
        except Exception:  # noqa: BLE001
            return []
        results = serp_mod.parse_serpapi(data)
        if not results and isinstance(data, dict):      # 兼容不同封装层级
            for key in ("results", "data", "response", "search_results"):
                sub = data.get(key)
                if isinstance(sub, dict):
                    results = serp_mod.parse_serpapi(sub)
                    if results:
                        break
        return results

    def _select_best(self, results: List[Any], q: Any, scorer: Any) -> Any:
        """标题/自由检索按 Jaccard 选最相关;DOI、全零相似度、或最高分低于阈值
        (cfg.min_title_score)→ 取 SERP 第一条(信任 Google 相关性序,避免模糊标题误选不相关结果)。

        当「最高分低于阈值(或全零重叠)」而回退第一条时,该选择视为 low-confidence:
        emit 'select' 事件(low_confidence=True,计入 summary.low_confidence_selections)并 warning,
        以便复盘模糊标题是否误选。**签名/返回值保持不变**(下游与 e2e 直测依赖返回单个结果)。"""
        ref = getattr(q, "q", None) if getattr(q, "kind", None) in ("title", "freeform") else None
        if ref:
            best, best_s = None, 0.0
            for r in results:
                s = scorer(ref, getattr(r, "title", "") or "")
                if s > best_s:
                    best, best_s = r, s
            min_score = float(getattr(self.cfg, "min_title_score", 0.0) or 0.0)
            if best is not None and best_s >= min_score:
                return best
            # 无可信标题匹配 → 回退 SERP 第一条,但标记 low-confidence(有 ctx 时记事件+告警)
            self._note_low_confidence(q, best_s, len(results))
        return results[0]

    def _note_low_confidence(self, q: Any, best_score: float, n_results: int) -> None:
        """标记「低置信标题选择」:emit select 事件 + warning。

        仅在上下文已装配(self.ctx 存在)时动作;_select_best 直测(无 ctx,如 e2e)时静默,
        且任何异常都被吞掉,绝不改变选择结果。"""
        ctx = self.ctx
        if ctx is None:
            return
        min_score = float(getattr(self.cfg, "min_title_score", 0.0) or 0.0)
        try:
            events = getattr(ctx, "events", None)
            if events is not None:
                events.emit(_EVENT_SELECT, low_confidence=True,
                            score=round(float(best_score), 4), threshold=min_score,
                            n=n_results, q=getattr(q, "q", None),
                            kind=getattr(q, "kind", None), fallback="serp-first")
            log = getattr(ctx, "log", None)
            if log is not None:
                log.warning("低置信标题匹配(最高分 %.3f < 阈值 %.3f):回退 SERP 第一条 · q=%r",
                            float(best_score), min_score, getattr(q, "q", None))
        except Exception:  # noqa: BLE001 - 标记/日志失败绝不影响选择结果
            pass

    def _build_paper(self, result: Any, q: Any) -> Any:
        from ..models import Paper
        return Paper(
            doi=getattr(result, "doi", None),
            title=getattr(result, "title", None) or getattr(q, "q", None),
            year=getattr(result, "year", None),
            authors=list(getattr(result, "authors", None) or []),
        )

    def _maybe_enrich_for_oa(self, paper: Any, result: Any, ctx: Any) -> Any:
        """OA 兜底前 best-effort 富化:结果无 DOI 时复用父 resolve 由标题反查 DOI + OA 元数据。"""
        if getattr(paper, "doi", None) or ctx.client is None:
            return paper
        ref = getattr(paper, "title", None) or getattr(result, "title", None)
        if not ref:
            return paper
        try:
            from ..config import Config as ParentConfig
            from ..resolve import classify_input, resolve_to_paper
            pc = ParentConfig(email=getattr(self.cfg, "email", None) or "anonymous@example.com")
            enriched = resolve_to_paper(classify_input(ref), ctx.client, ctx.log, pc)
            if enriched is not None and getattr(enriched, "doi", None):
                enriched.title = enriched.title or getattr(paper, "title", None)
                return enriched
        except Exception:  # noqa: BLE001 - 富化失败保持原 paper
            pass
        return paper

    def _download(self, result: Any, paper: Any, ctx: Any, idx: int):
        from .download import download_result_pdf
        try:
            return download_result_pdf(result, paper, ctx, idx)
        except Exception as e:  # noqa: BLE001
            return None, 0, f"download-error: {e}"

    def _oa_fallback(self, paper: Any, ctx: Any, idx: int):
        from .download import oa_fallback
        try:
            return oa_fallback(paper, ctx, idx)
        except Exception as e:  # noqa: BLE001
            return None, 0, f"oa-error: {e}"

    def _finalize_name(self, path: str, result: Any, paper: Any, idx: int, ctx: Any) -> str:
        """把已下载文件重命名为标准化文件名(naming.build_filename);失败则保留原路径。"""
        try:
            from .naming import build_filename, dedupe_path
            fname = build_filename(result, paper, self.cfg, index=idx, taken=self._taken)
            dest = os.path.join(ctx.pdf_dir, fname)
            if os.path.abspath(dest) != os.path.abspath(path):
                if os.path.exists(dest):
                    dest = dedupe_path(ctx.pdf_dir, fname)
                os.replace(path, dest)
            return dest
        except Exception:  # noqa: BLE001
            return path

    def _save_serp_snapshot(self, idx: int, out: Any) -> None:
        """把取回的原始 SERP HTML 落盘 out_scholar/serp/(ARCH §6);best-effort、绝不影响主流程。

        便于在**非被拦环境**下复盘 Scholar 现行页面结构、校对 serp.py 选择器准确性
        （离线 selftest 用合成 HTML，真实选择器验证依赖此快照）。serpapi 旁路(JSON)不存。
        """
        html = getattr(out, "html", None)
        if not html or (getattr(out, "engine", "") or "") == "serpapi":
            return
        try:
            out_dir = getattr(self.cfg, "out_dir", None) or "out_scholar"
            serp_dir = os.path.join(out_dir, "serp")
            os.makedirs(serp_dir, exist_ok=True)
            eng = str(getattr(out, "engine", "x") or "x")
            status = getattr(out, "status", None)
            fname = ("%d_%s_%s.html" % (idx, eng, status)).replace("/", "_").replace("\\", "_")
            with open(os.path.join(serp_dir, fname), "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:  # noqa: BLE001 - 快照落盘失败绝不能拖垮抓取
            pass

    def _emit_result(self, ctx: Any, fr: ScholarFetchResult) -> None:
        ctx.events.emit(EVENT_RESULT, success=fr.success, source=fr.source_used,
                        cited_by=fr.cited_by, ms=fr.elapsed_ms, error=fr.error)

    def _load_done(self, meta_path: str) -> Dict[str, Any]:
        """读 metadata.jsonl,返回 {raw_input: ScholarFetchResult}(仅已成功者,供续跑跳过)。"""
        done: Dict[str, Any] = {}
        if not os.path.exists(meta_path):
            return done
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    raw = d.get("raw_input")
                    if raw is not None and d.get("success"):
                        done[raw] = self._fr_from_dict(d)
        except Exception:  # noqa: BLE001
            pass
        return done

    def _fr_from_dict(self, d: Dict[str, Any]) -> ScholarFetchResult:
        fr = ScholarFetchResult(raw_input=d.get("raw_input", ""))
        for k, v in d.items():
            if hasattr(fr, k):
                setattr(fr, k, v)
        return fr

    def _append_metadata(self, meta_path: str, fr: ScholarFetchResult) -> None:
        try:
            with open(meta_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(fr.to_dict(), ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass

    def _summarize(self, results: List[Any], *, total: int, skipped: int, processed: int,
                   elapsed: int) -> Dict[str, Any]:
        from collections import Counter
        dicts = [r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in results]
        success = sum(1 for d in dicts if d.get("success"))
        n = len(dicts)
        by_source = Counter(d.get("source_used") for d in dicts
                            if d.get("success") and d.get("source_used"))
        by_engine = Counter(d.get("engine_used") for d in dicts if d.get("engine_used"))
        blocked = sum(1 for d in dicts if d.get("blocked"))
        # 从事件路由器的运行期计数器取真实计数(未装配/自定义 events 时安全退化为 0)。
        ev = getattr(self.ctx, "events", None)
        captcha_solved = int(getattr(ev, "captcha_solved", 0) or 0)
        proxy_rotations = int(getattr(ev, "proxy_rotations", 0) or 0)
        low_confidence = int(getattr(ev, "low_confidence_selections", 0) or 0)
        mode = self.cfg.resolved_mode() if hasattr(self.cfg, "resolved_mode") \
            else getattr(self.cfg, "mode", "self")
        return {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": mode,
            "total_inputs": total,
            "skipped_resume": skipped,
            "processed": processed,
            "success": success,
            "miss": n - success,
            "success_rate": (success / n) if n else 0.0,
            "by_source": dict(by_source),
            "by_engine": dict(by_engine),
            "blocked": blocked,
            "captcha_solved": captcha_solved,
            "proxy_rotations": proxy_rotations,
            "low_confidence_selections": low_confidence,
            "elapsed_sec": elapsed,
        }

    def _write_reports(self, summary: Dict[str, Any], results: List[Any], out_dir: str) -> None:
        try:
            with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass
        try:
            from ..report import write_results_csv, write_summary_html
            write_results_csv(results, os.path.join(out_dir, "results.csv"))
            write_summary_html(summary, results, os.path.join(out_dir, "report.html"))
        except Exception:  # noqa: BLE001 - 报表生成失败不影响已完成的抓取结果
            pass

    def _close(self, ctx: Any) -> None:
        try:
            ctx.events.close()
        except Exception:  # noqa: BLE001
            pass
        log = getattr(ctx, "log", None)
        for h in list(getattr(log, "handlers", []) or []):
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                log.removeHandler(h)
            except Exception:  # noqa: BLE001
                pass


# ────────────────────────────── 不联网 selftest ──────────────────────────────
# 端到端流水线由 fulltext_fetcher.scholar.selftest_e2e(SCHOLAR_E2E_OK)覆盖;此处补充针对
# 「审查 P2」两处改动的**单元级**断言(阈值 low-confidence 行为 + 事件真实计数 + summary 注入),
# 均在本文件边界内、纯标准库、不联网、不落盘。跑法:python -m fulltext_fetcher.scholar.pipeline
def _selftest() -> int:
    from types import SimpleNamespace

    # ① _EventRouter 计数:captcha(仅 ok=True 计) / proxy_rotate / select(仅 low_confidence 计)
    class _NullLog:
        def emit(self, *a: Any, **k: Any) -> None:
            pass

        def close(self) -> None:
            pass

    router = _EventRouter(_NullLog(), _NullLog())
    router.emit(EVENT_CAPTCHA, provider="x", ok=True)
    router.emit(EVENT_CAPTCHA, provider="x", ok=True)
    router.emit(EVENT_CAPTCHA, provider="x", ok=False)          # 失败不计
    router.emit(EVENT_PROXY_ROTATE, **{"from": "a", "to": "b", "reason": "blocked"})
    router.emit(EVENT_PROXY_ROTATE, **{"from": "b", "to": "c", "reason": "blocked"})
    router.emit(EVENT_PROXY_ROTATE, **{"from": "c", "to": "d", "reason": "rotate"})
    router.emit(_EVENT_SELECT, low_confidence=True, score=0.1)
    router.emit(_EVENT_SELECT, low_confidence=False)            # 非低置信不计
    router.emit(EVENT_RESULT, success=True)                     # 无关事件不计
    assert router.captcha_solved == 2, router.captcha_solved
    assert router.proxy_rotations == 3, router.proxy_rotations
    assert router.low_confidence_selections == 1, router.low_confidence_selections

    # ② _select_best:低于阈值 → 回退第一条并 emit low-confidence;达标 → 选中且不记;DOI → 第一条不记
    def _scorer(ref: str, title: str) -> float:
        return 1.0 if ref == title else (0.1 if title else 0.0)

    class _CapEvents:
        def __init__(self) -> None:
            self.seen: List[Any] = []

        def emit(self, event: str, **fields: Any) -> None:
            self.seen.append((event, fields))

    pipe = ScholarPipeline(ScholarConfig(min_title_score=0.2))
    cap = _CapEvents()
    pipe.ctx = ScholarContext(pipe.cfg, log=None, events=cap)
    q_title = SimpleNamespace(kind="title", q="X")
    r0, r1 = SimpleNamespace(title="Y"), SimpleNamespace(title="Z")   # 均弱(0.1 < 0.2)
    assert pipe._select_best([r0, r1], q_title, _scorer) is r0, "低置信应回退 SERP 第一条"
    assert any(e == _EVENT_SELECT and f.get("low_confidence") is True
               for e, f in cap.seen), cap.seen

    cap.seen.clear()
    rm = SimpleNamespace(title="X")                                  # 完全匹配(1.0 ≥ 0.2)
    assert pipe._select_best([r0, rm], q_title, _scorer) is rm, "达标应选中匹配项"
    assert not any(e == _EVENT_SELECT for e, _ in cap.seen), cap.seen  # 达标不记低置信

    cap.seen.clear()
    q_doi = SimpleNamespace(kind="doi", q="10.1/x")
    assert pipe._select_best([r0, rm], q_doi, _scorer) is r0, "DOI 恒取第一条"
    assert not any(e == _EVENT_SELECT for e, _ in cap.seen), cap.seen  # DOI 不记低置信

    # 无 ctx 直测(e2e 场景):低置信也不抛、不 emit,只回退第一条
    pipe_noctx = ScholarPipeline(ScholarConfig(min_title_score=0.2))
    assert pipe_noctx.ctx is None
    assert pipe_noctx._select_best([r0, r1], q_title, _scorer) is r0

    # ③ _summarize:真实计数注入(替代硬编码 0)
    pipe2 = ScholarPipeline(ScholarConfig())
    fake_ev = SimpleNamespace(captcha_solved=5, proxy_rotations=2, low_confidence_selections=3)
    pipe2.ctx = ScholarContext(pipe2.cfg, log=None, events=fake_ev)
    summ = pipe2._summarize([], total=0, skipped=0, processed=0, elapsed=1)
    assert summ["captcha_solved"] == 5 and summ["proxy_rotations"] == 2, summ
    assert summ["low_confidence_selections"] == 3, summ
    for k in ("captcha_solved", "proxy_rotations", "blocked", "by_source", "by_engine"):
        assert k in summ, (k, summ)

    print("SCHOLAR_PIPELINE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
