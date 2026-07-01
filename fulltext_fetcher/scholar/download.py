"""§3.8 结果 PDF 下载 + OA 兜底(薄封装,复用父包 fulltext_fetcher)。

职责聚焦"Scholar 结果 → 原文 PDF",下载/校验/文件名等基元一律复用父包,绝不重复造轮子:
  - `download_result_pdf`:遍历一条 ScholarResult 自带的 PDF 直链,逐个交父包
    `fulltext_fetcher.download.download_pdf`(其内部已含 HTML 落地页二次抽链);仍未果时
    对候选落地页可选走 `fulltext_fetcher.render_fetch.render_get_pdf_url`(仅 OA、无头渲染
    兜底,默认无引擎即优雅 no-op)渲染后再抽链下载。
  - `oa_fallback`:结果无可用 PDF 时,在 `cfg.oa_fallback` 打开的前提下,复用父包
    `fulltext_fetcher.sources.build_sources` + `download_pdf` 按 DOI/标题走 OA 源兜底。

两者返回 `(path|None, bytes, err)`,与父包 `download_pdf` 契约逐字对齐,便于上层 pipeline 统一消费。

边界:本模块只读复用父包(download / landing / render_fetch / sources / models / config),
不修改任何父文件;`ctx` 按鸭子类型访问(cfg/client/log/events),不硬依赖 pipeline 的
ScholarContext 具体类,故只依赖 P0(scholar.models)。

不联网自检:python -m fulltext_fetcher.scholar.download  → 打印 SCH_DOWNLOAD_OK
"""
from __future__ import annotations

import os
from typing import Any, List, Optional, Tuple

from ..download import download_pdf
from ..models import Paper, PdfCandidate  # noqa: F401  (Paper 供类型/自检用)
from ..render_fetch import render_get_pdf_url
from .models import ScholarResult

_SCHOLAR_PDF_SOURCE = "scholar-pdf"
_RET = Tuple[Optional[str], int, Optional[str]]


# ── 小工具(全部 best-effort、鸭子类型、绝不因缺字段而崩)──────────────────────
def _pdf_dir(ctx: Any) -> str:
    """落盘目录:优先 ctx.pdf_dir,否则 cfg.out_dir/pdfs(对齐父包 pipeline 约定)。"""
    d = getattr(ctx, "pdf_dir", None)
    if d:
        return d
    out = getattr(getattr(ctx, "cfg", None), "out_dir", None) or "out_scholar"
    return os.path.join(out, "pdfs")


def _emit(ctx: Any, event: str, **fields: Any) -> None:
    """best-effort 结构化事件;无 events 或异常一律静默(绝不影响下载主流程)。"""
    events = getattr(ctx, "events", None)
    if events is None:
        return
    try:
        events.emit(event, **fields)
    except Exception:  # noqa: BLE001 - 事件落盘失败绝不能拖垮下载
        pass


def _download_one(url: str, paper: Any, ctx: Any, idx: int, source: str,
                  *, allow_landing: bool = True) -> _RET:
    """对单个 URL 调父包 download_pdf 的薄封装:统一构造候选 + 传 ctx 上的运行期对象。"""
    cand = PdfCandidate(url=url, source=source, kind="pdf", confidence=90)
    return download_pdf(cand, paper, _pdf_dir(ctx),
                        getattr(ctx, "client", None), getattr(ctx, "cfg", None),
                        getattr(ctx, "log", None), fallback_name=str(idx),
                        allow_landing=allow_landing)


def _render_allowed(paper: Any) -> bool:
    """仅 OA 渲染:paper 明确非 OA(is_oa is False)则不渲染;OA / 未知则允许尝试。"""
    return getattr(paper, "is_oa", None) is not False


def _render_candidates(result: ScholarResult) -> List[str]:
    """渲染候选落地页:结果自带 pdf_links + 主落地链接(去重保序)。"""
    out: List[str] = []
    for u in (list(getattr(result, "pdf_links", None) or []) + [getattr(result, "link", None)]):
        if u and u not in out:
            out.append(u)
    return out


# ── 对外主函数 ───────────────────────────────────────────────────────────────
def download_result_pdf(result: ScholarResult, paper: Any, ctx: Any, idx: int) -> _RET:
    """一条 Scholar 结果 → PDF。返回 (path|None, bytes, err),同父包契约。

    ① 遍历 result.pdf_links,逐个复用父包 download_pdf(自带 landing 二次抽链),命中即短路;
    ② 全部未果且允许(仅 OA)时,对候选落地页可选 render_get_pdf_url 渲染后再抽链下载
       (默认无渲染引擎即优雅 no-op;render_fetch 内置合规守卫,绝不渲染 Scholar 页)。
    """
    seen: set = set()
    last_err: Optional[str] = None

    # ① 结果自带 PDF 直链(download_pdf 内部已处理 HTML 落地页的二次抽链)
    for url in (getattr(result, "pdf_links", None) or []):
        if not url or url in seen:
            continue
        seen.add(url)
        path, nbytes, err = _download_one(url, paper, ctx, idx, _SCHOLAR_PDF_SOURCE)
        _emit(ctx, "download", url=url, ok=bool(path), bytes=nbytes, error=err)
        if path:
            return path, nbytes, None
        last_err = err

    # ② 渲染兜底(可选、仅 OA):渲染后从 DOM 抽 PDF 直链再下一层
    if _render_allowed(paper):
        for url in _render_candidates(result):
            info = render_get_pdf_url(url)
            if not info or not info.get("available"):
                continue  # 无引擎 / 默认关闭 → 优雅跳过
            for purl in (info.get("pdf_links") or []):
                if not purl or purl in seen:
                    continue
                seen.add(purl)
                path, nbytes, err = _download_one(
                    purl, paper, ctx, idx, _SCHOLAR_PDF_SOURCE + "+render",
                    allow_landing=False)
                _emit(ctx, "download", url=purl, ok=bool(path), bytes=nbytes,
                      error=err, via="render")
                if path:
                    return path, nbytes, None
                last_err = err

    return None, 0, last_err or "no-pdf-in-result"


def oa_fallback(paper: Any, ctx: Any, idx: int, *, _sources: Optional[List[Any]] = None) -> _RET:
    """结果无 PDF 时,复用父包 OA 源(build_sources)+ download_pdf 按 DOI/标题兜底。

    仅在 cfg.oa_fallback 为真时启用;返回 (path|None, bytes, err),同父包契约。
    (_sources 仅供自检注入 fake 源;生产不传,自动 build_sources。)
    """
    cfg = getattr(ctx, "cfg", None)
    if not getattr(cfg, "oa_fallback", False):
        return None, 0, "oa-fallback-disabled"

    # 惰性导入父包 OA 机制(仅本兜底路径需要),并派生一个父包 Config 供其消费。
    from ..sources.base import SourceContext

    parent_cfg = _parent_config(cfg)
    client = getattr(ctx, "client", None)
    log = getattr(ctx, "log", None)
    src_ctx = SourceContext(client=client, config=parent_cfg, log=log,
                            events=getattr(ctx, "events", None))
    pdf_dir = _pdf_dir(ctx)

    if _sources is not None:
        sources = list(_sources)
    else:
        from ..sources import build_sources
        sources = build_sources(parent_cfg)

    last_err: Optional[str] = None
    for src in sources:
        name = getattr(src, "name", "?")
        try:
            if not src.applicable(paper):
                continue
            cands = src.find_candidates(paper, src_ctx) or []
        except Exception as e:  # noqa: BLE001 - 单源异常不拖垮兜底(与父包源约定一致)
            _emit(ctx, "oa_fallback", source=name, ok=False, error=str(e))
            last_err = last_err or f"source-error:{name}"
            continue
        direct = sorted([c for c in cands if _is_direct(c)],
                        key=lambda c: getattr(c, "confidence", 0), reverse=True)
        for c in direct:
            path, nbytes, err = download_pdf(c, paper, pdf_dir, client, parent_cfg, log,
                                             fallback_name=str(idx))
            _emit(ctx, "oa_fallback", source=name, ok=bool(path),
                  url=getattr(c, "url", None), error=err)
            if path:
                return path, nbytes, None
            last_err = err
    return None, 0, last_err or "oa-fallback-miss"


def _is_direct(cand: Any) -> bool:
    """候选是否为可直接下载的直链(pdf/render);无 is_direct 的鸭子对象保守视为可试。"""
    fn = getattr(cand, "is_direct", None)
    return fn() if callable(fn) else True


def _parent_config(cfg: Any):
    """从 ScholarConfig 派生父包 Config(只填 OA 兜底相关字段,其余取父默认含 sources 顺序)。"""
    from ..config import Config
    return Config(
        email=getattr(cfg, "email", None) or "anonymous@example.com",
        out_dir=getattr(cfg, "out_dir", None) or "out_scholar",
        min_pdf_bytes=getattr(cfg, "min_pdf_bytes", 1024),
        max_pdf_bytes=getattr(cfg, "max_pdf_bytes", 80 * 1024 * 1024),
        enable_scihub=getattr(cfg, "enable_scihub", False),
    )


# ── 内置不联网 selftest ─────────────────────────────────────────────────────
def _minimal_pdf() -> bytes:
    """结构合法的最小 PDF(含 %PDF + %%EOF,体积够过 min_pdf_bytes)。"""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"xref\n0 4\ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF\n"
    )


class _Resp:
    def __init__(self, data: bytes, ct: str = "application/pdf", status: int = 200):
        self._d, self.status_code, self.headers = data, status, {"Content-Type": ct}

    def iter_content(self, n):
        for i in range(0, len(self._d), n):
            yield self._d[i:i + n]

    def close(self):
        pass


class _Client:
    """按 URL 预设返回的假 client(对齐父包 HttpClient.get 签名)。"""

    def __init__(self, routes):
        self._routes = dict(routes or {})

    def get(self, url, *, params=None, headers=None, stream=False, allow_redirects=True):
        spec = self._routes.get(url)
        return None if spec is None else _Resp(*spec)

    def get_json(self, url, **kw):
        return None


class _Cfg:
    oa_fallback = True
    min_pdf_bytes = 8
    max_pdf_bytes = 80 * 1024 * 1024
    out_dir = "out_scholar"
    email = "selftest@example.org"
    enable_scihub = False


class _Log:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


class _Ctx:
    def __init__(self, client, cfg, pdf_dir):
        self.client, self.cfg, self.pdf_dir = client, cfg, pdf_dir
        self.log, self.events = _Log(), None


class _FakeSource:
    name = "fake-oa"

    def __init__(self, cands):
        self._c = list(cands)

    def applicable(self, paper):
        return True

    def find_candidates(self, paper, ctx):
        return list(self._c)


def _selftest() -> int:
    import tempfile

    good = _minimal_pdf()
    truncated = good[:good.rindex(b"%%EOF")]            # 掐掉 %%EOF:模拟下载被腰斩

    with tempfile.TemporaryDirectory() as d:
        # ① download_result_pdf:合法 PDF 直链 → 落盘、返回 (path, bytes, None)
        url_ok = "https://oa.example.org/paper.pdf"
        ctx = _Ctx(_Client({url_ok: (good, "application/pdf", 200)}), _Cfg(), d)
        res = ScholarResult(title="T", link="https://oa.example.org/abs/1", pdf_links=[url_ok])
        path, nbytes, err = download_result_pdf(res, Paper(title="p1", is_oa=True), ctx, 0)
        assert path and err is None and nbytes == len(good), (path, nbytes, err)
        assert os.path.exists(path), path

        # ② 截断 PDF → 不落盘、path 为 None(渲染兜底无引擎优雅 no-op 后仍失败)
        before = set(os.listdir(d))
        url_bad = "https://oa.example.org/bad.pdf"
        ctx2 = _Ctx(_Client({url_bad: (truncated, "application/pdf", 200)}), _Cfg(), d)
        res2 = ScholarResult(title="T2", pdf_links=[url_bad])
        p2, n2, e2 = download_result_pdf(res2, Paper(title="p2", is_oa=True), ctx2, 1)
        assert p2 is None and e2, (p2, n2, e2)
        assert set(os.listdir(d)) == before, "截断 PDF 不应落盘"

        # ③ oa_fallback 关 → 明确禁用返回
        cfg_off = _Cfg()
        cfg_off.oa_fallback = False
        assert oa_fallback(Paper(doi="10.1/x"), _Ctx(_Client({}), cfg_off, d), 2) == (
            None, 0, "oa-fallback-disabled")

        # ④ oa_fallback 开 + 注入 fake 源 → 命中父包 download_pdf 落盘
        url_oa = "https://oa.example.org/oa.pdf"
        ctx4 = _Ctx(_Client({url_oa: (good, "application/pdf", 200)}), _Cfg(), d)
        src = _FakeSource([PdfCandidate(url=url_oa, source="unpaywall", kind="pdf", confidence=80)])
        p4, n4, e4 = oa_fallback(Paper(doi="10.1/x", is_oa=True), ctx4, 3, _sources=[src])
        assert p4 and e4 is None and n4 == len(good), (p4, n4, e4)
        assert os.path.exists(p4), p4

        # ⑤ oa_fallback 开但源无候选 → 兜底未命中
        p5, n5, e5 = oa_fallback(Paper(doi="10.1/y"), _Ctx(_Client({}), _Cfg(), d), 4,
                                 _sources=[_FakeSource([])])
        assert p5 is None and e5 == "oa-fallback-miss", (p5, n5, e5)

    print("SCH_DOWNLOAD_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
