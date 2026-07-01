"""§3.12 谷歌学术爬虫子系统 · 不联网端到端自检。

注入 FakeSerpEngine（返回固定 SERP HTML）+ FakeClient（返回结构合法的最小 PDF），驱动**真实**
ScholarPipeline 全链路：
  query.build_query → fetcher.fetch_serp → serp.parse_serp → 选最相关 → download.download_result_pdf
  → naming.build_filename 落盘 → 汇总 summary + 复用父包 report 写 results.csv/report.html。

断言：SERP 解析（被引/pdf_links/标题）、mock 下载落盘、文件名标准化、summary 字段齐全、六产物
生成、断点续跑跳过。纯标准库、不联网、不依赖任何可选反爬库（curl_cffi/nodriver 等一律不需要）。

跑法：python -m fulltext_fetcher.scholar.selftest_e2e   → 打印 SCHOLAR_E2E_OK
      python -m fulltext_fetcher.scholar --selftest      → 同上（cli 委托本函数）
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

from .config import ScholarConfig
from .fetcher import FetchEngine
from .models import FetchOutcome
from .pipeline import ScholarPipeline

# 结构完整、> 默认 min_pdf_bytes(1024) 的最小 PDF（含 %PDF 魔数 + Catalog/Pages/Page +
# xref/trailer/startxref/%%EOF），可过 download 的完整性校验。
_PDF_BYTES = (
    b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
    b"% padding to exceed min_pdf_bytes: " + b"0123456789" * 120 + b"\n"
    b"xref\n0 4\ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n900\n%%EOF\n"
)

_PDF_URL = "https://oa.example.org/attention.pdf"

# 固定 SERP HTML：一条结果，含右侧 [PDF] 直链 + 被引 + 标题/作者/年。
_SERP_HTML = (
    '<html><body><div id="gs_res_ccl_mid">'
    '<div class="gs_r gs_or gs_scl" data-cid="CID1">'
    '  <div class="gs_or_ggsm">'
    f'    <a href="{_PDF_URL}"><span class="gs_ctg2">[PDF]</span> oa.example.org</a>'
    '  </div>'
    '  <div class="gs_ri">'
    '    <h3 class="gs_rt"><a href="https://pub.example.com/attention">'
    '      Attention is all you need</a></h3>'
    '    <div class="gs_a">A Vaswani, N Shazeer - Advances in NeurIPS, 2017 - proceedings.example.com</div>'
    '    <div class="gs_rs">We propose the Transformer, a new network architecture ...</div>'
    '    <div class="gs_fl"><a href="/scholar?cites=1">Cited by 1000</a></div>'
    '  </div>'
    '</div></div></body></html>'
)


class _FakeSerpEngine(FetchEngine):
    """注入引擎：无论查询，恒返回固定 SERP HTML（不联网、不导入任何反爬库）。"""

    name = "curl_cffi"

    def available(self) -> bool:
        return True

    def get(self, target, ctx):  # noqa: ANN001, ARG002
        return FetchOutcome(ok=True, html=_SERP_HTML, final_url=target, status=200,
                            engine="curl_cffi")


class _FakeResp:
    """最小可用假响应（够父包 download_pdf 消费即可）。"""

    def __init__(self, data: bytes, ct: str = "application/pdf", status: int = 200):
        self._d, self.status_code, self.headers = data, status, {"Content-Type": ct}

    def iter_content(self, n):  # noqa: ANN001
        for i in range(0, len(self._d), n):
            yield self._d[i:i + n]

    def close(self) -> None:
        pass


class _FakeClient:
    """按 URL 预设返回的假 HttpClient（对齐父包 get 签名）；未命中 → None。"""

    def __init__(self, routes):
        self._routes = dict(routes)

    def get(self, url, *, params=None, headers=None, stream=False, allow_redirects=True):  # noqa: ANN001
        spec = self._routes.get(url)
        return _FakeResp(*spec) if spec else None

    def get_json(self, url, **kw):  # noqa: ANN001, ARG002
        return None


def _selftest_select_best() -> None:
    """回归 _select_best 的最低相似度阈值(cfg.min_title_score):
    高分选中匹配项;最高分低于阈值 → 回退 SERP 第一条;DOI → 恒第一条;阈值=0 → 旧行为。
    仅读 self.cfg,不触发上下文装配/落盘。"""
    from types import SimpleNamespace

    from .query import title_match_score

    def _res(title: str) -> SimpleNamespace:
        return SimpleNamespace(title=title, pdf_links=[], doi=None, year=None,
                               authors=[], cited_by=None)

    q_title = SimpleNamespace(kind="title", q="deep residual learning for image recognition")
    r_first = _res("quantum entanglement in superconductors")   # 与查询零重叠
    r_weak = _res("residual networks")                          # 弱重叠(Jaccard≈0.14 < 0.2)
    r_match = _res("Deep residual learning for image recognition")  # 完全匹配(Jaccard=1.0)

    pipe = ScholarPipeline(ScholarConfig(min_title_score=0.2))
    # ① 存在高相似度候选 → 选中该候选(即便不在首位)
    assert pipe._select_best([r_first, r_match], q_title, title_match_score) is r_match
    # ② 全部弱匹配(最高分 < 阈值)→ 回退 SERP 第一条
    assert pipe._select_best([r_first, r_weak], q_title, title_match_score) is r_first
    # ③ DOI 检索 → 恒取第一条(不做相似度选择)
    q_doi = SimpleNamespace(kind="doi", q="10.1/x")
    assert pipe._select_best([r_first, r_match], q_doi, title_match_score) is r_first
    # ④ 阈值=0(关闭)→ 任何 >0 匹配都选中(保持旧行为)
    pipe0 = ScholarPipeline(ScholarConfig(min_title_score=0.0))
    assert pipe0._select_best([r_first, r_weak], q_title, title_match_score) is r_weak


def _make_pipeline(out_dir: str, *, routes) -> ScholarPipeline:
    """构造纯 Scholar、零睡眠、注入 fake 引擎/client 的 ScholarPipeline。"""
    cfg = ScholarConfig(
        mode="self", engine_order=["curl_cffi"], out_dir=out_dir, concurrency=1,
        page_interval_low=0.0, page_interval_high=0.0, backoff_base=0.0, backoff_cap=0.0,
        cooldown_after_block=0.0, oa_fallback=False, captcha_enabled=False,
        proxy_enabled=False, email="selftest@example.org", log_level="ERROR",
    )
    return ScholarPipeline(cfg, engines={"curl_cffi": _FakeSerpEngine()},
                           client=_FakeClient(routes), proxy=None)


def run_offline_e2e() -> int:
    d = tempfile.mkdtemp(prefix="scholar_e2e_")
    try:
        pipe = _make_pipeline(d, routes={_PDF_URL: (_PDF_BYTES, "application/pdf", 200)})
        summary = pipe.run(["Attention is all you need", "10.1000/x"])

        # ① summary 字段齐全 + 统计正确
        assert summary["processed"] == 2, summary
        assert summary["success"] == 2, summary
        assert summary["miss"] == 0, summary
        assert abs(summary["success_rate"] - 1.0) < 1e-9, summary
        assert summary["by_source"].get("scholar-pdf") == 2, summary
        assert summary["mode"] == "self", summary
        for k in ("ts", "total_inputs", "skipped_resume", "by_engine", "blocked",
                  "captcha_solved", "proxy_rotations", "elapsed_sec"):
            assert k in summary, (k, summary)

        # ② 每条结果：解析出被引/pdf、成功落盘、文件名标准化
        assert len(pipe.results) == 2, pipe.results
        for fr in pipe.results:
            assert fr.success is True, fr.to_dict()
            assert fr.cited_by == 1000, fr.cited_by
            assert fr.source_used == "scholar-pdf", fr.source_used
            assert fr.pdf_path and os.path.isfile(fr.pdf_path), fr.pdf_path
            assert fr.pdf_bytes == len(_PDF_BYTES), fr.pdf_bytes
            assert fr.n_results == 1, fr.n_results
            assert fr.engine_used == "curl_cffi", fr.engine_used
            assert fr.pdf_url == _PDF_URL, fr.pdf_url

        # 标准化命名：年_首作者姓_标题（两条同源 → 第二条去重加 _2）
        names = sorted(os.path.basename(fr.pdf_path) for fr in pipe.results)
        assert names[0].startswith("2017_Vaswani_Attention"), names
        assert names[1].startswith("2017_Vaswani_Attention") and names[1] != names[0], names

        # ③ 六产物齐全
        for fn in ("summary.json", "metadata.jsonl", "attempts.jsonl", "serp.jsonl",
                   "results.csv", "report.html"):
            assert os.path.isfile(os.path.join(d, fn)), f"缺产物 {fn}"

        # summary.json 落盘自洽
        with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
            disk = json.load(f)
        assert disk["success"] == 2 and disk["processed"] == 2, disk

        # metadata.jsonl 两行、均成功
        with open(os.path.join(d, "metadata.jsonl"), encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        assert len(lines) == 2 and all(json.loads(ln)["success"] for ln in lines), lines

        # ④ 断点续跑：第二次 run 全部跳过、不再下载（空 client 若真下载会失败）
        pipe2 = _make_pipeline(d, routes={})
        s2 = pipe2.run(["Attention is all you need", "10.1000/x"])
        assert s2["skipped_resume"] == 2 and s2["processed"] == 0, s2

        # ⑤ _select_best 最低相似度阈值回归(避免模糊标题误选不相关结果)
        _selftest_select_best()
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("SCHOLAR_E2E_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_offline_e2e())
