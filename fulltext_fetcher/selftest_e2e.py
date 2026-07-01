"""Pipeline 编排器端到端 mock 集成测试(不联网)。

用一个假 HttpClient 替换 Pipeline 内部 client(依赖注入,不改业务代码),驱动真实的
`解析 → 多源回退 → 直链短路 → landing 落地页兜底 → 报表生成 → 断点续跑` 全链路,
并对编排行为做断言。覆盖:
  ① 第一个源直链命中即短路(后续源不再被尝试);
  ② 第一个源直链 403 → 回退到下一个源成功;
  ③ 源给的"直链"返回 HTML 落地页 → landing 抠出内嵌 PDF 直链并二次下载成功;
  ④ 全源无候选 → result 失败且 error 合理、attempts 记录所有被试源;
  ⑤ run() 跑完 out_dir 生成 summary.json / results.csv / report.html 且字段正确;
  ⑥ 断点续跑:已成功输入第二次运行被跳过(不再发起任何请求);
  ⑦ 断点续跑失败分流:上次「永久失败」默认跳过、临时失败默认重跑,--retry-failed 时永久失败也重跑。

跑法: python -m fulltext_fetcher.selftest_e2e   → 打印 E2E_OK
约束:纯标准库 + 现有包、零联网、只新增本文件;**未修改 config.py / http_client.py**
(谷歌学术人机认证-152 正在为这两个文件加 EZproxy 可选字段,本测试只 import 不改,
用 mock client 完全替代网络层)。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

from .config import Config
from .pipeline import Pipeline

# 结构完整的最小 PDF：%PDF 魔数 + Catalog/Pages/Page 对象 + 内容流 + xref/trailer/
# startxref/%%EOF，且远大于 cfg.min_pdf_bytes(1024)。满足 download 增强后的完整性校验
# （防截断/损坏：需含 %%EOF、startxref、/Type /Page 等结构标记，见 D2）。
_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"%\xe2\xe3\xcf\xd3\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
    b"/Resources << >> /Contents 4 0 R >>\nendobj\n"
    b"4 0 obj\n<< /Length 45 >>\nstream\n"
    b"BT /F1 12 Tf 72 720 Td (selftest pdf) Tj ET\n"
    b"endstream\nendobj\n"
    b"% padding to exceed cfg.min_pdf_bytes(1024): " + b"0123456789" * 120 + b"\n"
    b"xref\n0 5\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000117 00000 n \n"
    b"0000000210 00000 n \n"
    b"trailer\n<< /Size 5 /Root 1 0 R >>\n"
    b"startxref\n1400\n"
    b"%%EOF\n"
)
# HTML 落地页:内嵌 citation_pdf_url,供 landing.extract_pdf_links 抠出内嵌 PDF 直链。
_LANDING_HTML = (
    "<html><head>"
    '<meta name="citation_pdf_url" content="https://pdf.test/embedded.pdf">'
    "</head><body>full text landing page</body></html>"
).encode("utf-8")


class _FakeResp:
    """最小可用的假 requests.Response:够 download.py 消费即可。"""

    def __init__(self, status: int, content_type: str, body: bytes):
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self._body = body

    def iter_content(self, chunk_size: int = 65536):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def json(self):
        return json.loads(self._body.decode("utf-8"))

    def close(self) -> None:
        pass


class FakeClient:
    """按 URL 预设返回的假 HttpClient(stub get / get_json),并记录全部调用。

    - get_json(url): 命中 json_routes 返回 dict,否则 None(模拟无数据 / 非 200)。
    - get(url):      命中 get_routes 返回 _FakeResp,否则 None(模拟 no-response)。
    调用历史(json_calls / get_calls)用于断言"短路 / 回退 / landing 抠链"是否真的发生。
    """

    def __init__(self, json_routes=None, get_routes=None):
        self.json_routes = dict(json_routes or {})
        self.get_routes = dict(get_routes or {})
        self.json_calls = []
        self.get_calls = []

    def set_host_interval(self, *args, **kwargs) -> None:
        # Pipeline.__init__ 会对真 client 调一次;注入后保留为 no-op 以兼容接口。
        pass

    def get_json(self, url, **kw):
        self.json_calls.append(url)
        return self.json_routes.get(url)

    def get(self, url, *, params=None, headers=None, stream=False, allow_redirects=True):
        self.get_calls.append(url)
        spec = self.get_routes.get(url)
        if spec is None:
            return None
        status, content_type, body = spec
        return _FakeResp(status, content_type, body)


def _oa(doi: str) -> str:
    return f"https://api.openalex.org/works/doi:{doi}"


def _up(doi: str) -> str:
    return f"https://api.unpaywall.org/v2/{doi}"


def _cr(doi: str) -> str:
    return f"https://api.crossref.org/works/{doi}"


def _make_pipeline(out_dir: str, fake: FakeClient, **cfg_over) -> Pipeline:
    """构造 Pipeline 并把内部 client 替换为 fake(覆盖 resolve / 各源 / download 三处)。"""
    cfg = Config(out_dir=out_dir, concurrency=1, email="selftest@example.org",
                 sources=["unpaywall", "openalex", "crossref"], log_level="ERROR",
                 **cfg_over)
    pipe = Pipeline(cfg)      # 内部会造一个真 HttpClient(仅建对象、不发请求)
    pipe.client = fake        # resolve_to_paper / download_pdf 用
    pipe.ctx.client = fake    # 各源 find_candidates 经 ctx.client 用
    return pipe


def _release(pipe: Pipeline) -> None:
    """释放文件句柄(EventLog + 日志 FileHandler),便于 Windows 下删除临时目录。"""
    try:
        pipe.events.close()
    except Exception:
        pass
    for h in list(getattr(pipe.log, "handlers", [])):
        try:
            h.close()
        except Exception:
            pass
        try:
            pipe.log.handlers.remove(h)
        except Exception:
            pass


def _teardown(pipe: Pipeline, out_dir: str) -> None:
    _release(pipe)
    shutil.rmtree(out_dir, ignore_errors=True)


def test_shortcircuit() -> None:
    """① unpaywall 直链命中即短路:openalex / crossref 源不再被执行。"""
    doi = "10.1000/short"
    fake = FakeClient(
        json_routes={
            _oa(doi): {"title": "Short Paper"},                       # resolve 富化用
            _up(doi): {"best_oa_location": {"url_for_pdf": "https://pdf.test/short.pdf"}},
        },
        get_routes={"https://pdf.test/short.pdf": (200, "application/pdf", _PDF_BYTES)},
    )
    d = tempfile.mkdtemp(prefix="e2e_sc_")
    pipe = _make_pipeline(d, fake)
    try:
        r = pipe.process_one(doi, 0)
        assert r.success is True, r.error
        assert r.source_used == "unpaywall", r.source_used
        assert [a.source for a in r.attempts] == ["unpaywall"], [a.source for a in r.attempts]
        assert _cr(doi) not in fake.json_calls, "短路失败:crossref 源不应被调用"
        assert r.pdf_path and os.path.isfile(r.pdf_path), r.pdf_path
    finally:
        _teardown(pipe, d)


def test_fallback() -> None:
    """② 第一个源(unpaywall)直链 403 → 回退到下一个源(openalex)直链成功。"""
    doi = "10.1000/fallback"
    fake = FakeClient(
        json_routes={
            _oa(doi): {"title": "FB", "best_oa_location": {"pdf_url": "https://pdf.test/ok2.pdf"}},
            _up(doi): {"best_oa_location": {"url_for_pdf": "https://pdf.test/403.pdf"}},
        },
        get_routes={
            "https://pdf.test/403.pdf": (403, "application/pdf", b""),
            "https://pdf.test/ok2.pdf": (200, "application/pdf", _PDF_BYTES),
        },
    )
    d = tempfile.mkdtemp(prefix="e2e_fb_")
    pipe = _make_pipeline(d, fake)
    try:
        r = pipe.process_one(doi, 0)
        assert r.success is True, r.error
        assert r.source_used == "openalex", r.source_used
        assert [a.source for a in r.attempts] == ["unpaywall", "openalex"], \
            [a.source for a in r.attempts]
        assert "https://pdf.test/403.pdf" in fake.get_calls, "未尝试第一个源的 403 直链"
        assert "https://pdf.test/ok2.pdf" in fake.get_calls, "未回退到第二个源直链"
    finally:
        _teardown(pipe, d)


def test_landing() -> None:
    """③ 源给的直链返回 HTML 落地页 → landing 抠出内嵌 PDF 直链并二次下载成功。"""
    doi = "10.1000/landing"
    fake = FakeClient(
        json_routes={
            _oa(doi): {"title": "LP"},
            _up(doi): {"best_oa_location": {"url_for_pdf": "https://landing.test/page"}},
        },
        get_routes={
            "https://landing.test/page": (200, "text/html; charset=utf-8", _LANDING_HTML),
            "https://pdf.test/embedded.pdf": (200, "application/pdf", _PDF_BYTES),
        },
    )
    d = tempfile.mkdtemp(prefix="e2e_lp_")
    pipe = _make_pipeline(d, fake)
    try:
        r = pipe.process_one(doi, 0)
        assert r.success is True, r.error
        assert r.source_used == "unpaywall", r.source_used
        assert "https://landing.test/page" in fake.get_calls, "未请求落地页"
        assert "https://pdf.test/embedded.pdf" in fake.get_calls, "landing 抠链未触发二次下载"
        assert r.pdf_path and os.path.isfile(r.pdf_path), r.pdf_path
    finally:
        _teardown(pipe, d)


def test_miss() -> None:
    """④ 全源无候选:result 失败、error 合理,attempts 记录所有被试源。"""
    doi = "10.1000/miss"
    fake = FakeClient(json_routes={}, get_routes={})  # 所有 get_json → None
    d = tempfile.mkdtemp(prefix="e2e_miss_")
    pipe = _make_pipeline(d, fake)
    try:
        r = pipe.process_one(doi, 0)
        assert r.success is False, r.source_used
        assert r.error == "no-candidates", r.error   # 全源零候选 → 精确归因(替代旧的通用 no-downloadable-pdf)
        assert [a.source for a in r.attempts] == ["unpaywall", "openalex", "crossref"], \
            [a.source for a in r.attempts]
    finally:
        _teardown(pipe, d)


def test_artifacts_and_summary() -> None:
    """⑤ run() 跑混合输入后:summary 统计正确,三个产物文件生成且字段正确。"""
    ok_doi = "10.1000/arta"
    miss_doi = "10.1000/artb"
    fake = FakeClient(
        json_routes={
            _oa(ok_doi): {"title": "A"},
            _up(ok_doi): {"best_oa_location": {"url_for_pdf": "https://pdf.test/arta.pdf"}},
        },
        get_routes={"https://pdf.test/arta.pdf": (200, "application/pdf", _PDF_BYTES)},
    )
    d = tempfile.mkdtemp(prefix="e2e_art_")
    pipe = _make_pipeline(d, fake)
    try:
        summary = pipe.run([ok_doi, miss_doi])
        assert summary["processed"] == 2, summary
        assert summary["success"] == 1, summary
        assert summary["miss"] == 1, summary
        assert abs(summary["success_rate"] - 0.5) < 1e-9, summary
        assert summary["by_source"] == {"unpaywall": 1}, summary

        for fn in ("summary.json", "results.csv", "report.html"):
            assert os.path.isfile(os.path.join(d, fn)), f"缺产物 {fn}"

        with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
            disk = json.load(f)
        assert disk["success"] == 1 and disk["processed"] == 2, disk

        import csv as _csv
        with open(os.path.join(d, "results.csv"), encoding="utf-8-sig", newline="") as f:
            rows = list(_csv.DictReader(f))
        assert len(rows) == 2, len(rows)
        assert {row["raw_input"] for row in rows} == {ok_doi, miss_doi}, rows

        with open(os.path.join(d, "report.html"), encoding="utf-8") as f:
            doc = f.read()
        assert "50.0%" in doc, "report.html 缺成功率"
        assert "OK" in doc and "MISS" in doc, "report.html 缺状态明细"
    finally:
        _teardown(pipe, d)


def test_resume() -> None:
    """⑥ 断点续跑:已成功输入第二次运行被跳过,且不再发起任何请求。"""
    doi = "10.1000/resume"
    routes_json = {
        _oa(doi): {"title": "R"},
        _up(doi): {"best_oa_location": {"url_for_pdf": "https://pdf.test/resume.pdf"}},
    }
    routes_get = {"https://pdf.test/resume.pdf": (200, "application/pdf", _PDF_BYTES)}
    d = tempfile.mkdtemp(prefix="e2e_rs_")

    fake1 = FakeClient(json_routes=routes_json, get_routes=routes_get)
    pipe1 = _make_pipeline(d, fake1)
    try:
        s1 = pipe1.run([doi])
        assert s1["success"] == 1 and s1["skipped_resume"] == 0, s1
    finally:
        _release(pipe1)  # 关句柄但保留 out_dir(metadata.jsonl 供第二次读)

    fake2 = FakeClient(json_routes=routes_json, get_routes=routes_get)
    pipe2 = _make_pipeline(d, fake2)
    try:
        s2 = pipe2.run([doi])
        assert s2["skipped_resume"] == 1, s2
        assert s2["processed"] == 0, s2
        assert fake2.json_calls == [] and fake2.get_calls == [], \
            (fake2.json_calls, fake2.get_calls)
    finally:
        _teardown(pipe2, d)


def test_resume_retry_failed() -> None:
    '''⑦ 断点续跑失败分流:上次「永久失败」默认跳过、临时失败默认重跑;--retry-failed 时永久失败也重跑。'''
    perm_doi = '10.1000/perm'       # 上次永久失败(download-failed:http-403,不命中 _RETRIABLE_ERROR_HINTS)
    trans_doi = '10.1000/trans'     # 上次临时失败(no-response,命中 _RETRIABLE_ERROR_HINTS)
    d = tempfile.mkdtemp(prefix='e2e_rf_')

    def _seed(records) -> None:
        with open(os.path.join(d, 'metadata.jsonl'), 'w', encoding='utf-8') as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + chr(10))

    # (A) 默认 retry_failed=False:永久失败跳过、临时失败重跑
    _seed([
        {'raw_input': perm_doi, 'success': False, 'error': 'download-failed:http-403'},
        {'raw_input': trans_doi, 'success': False, 'error': 'no-response'},
    ])
    fake_a = FakeClient(json_routes={}, get_routes={})   # 重跑者拿空路由→再次 miss,但会产生调用
    pipe_a = _make_pipeline(d, fake_a)                   # resume 默认 True、retry_failed 默认 False
    try:
        s = pipe_a.run([perm_doi, trans_doi])
        assert s['skipped_resume'] == 1, s              # 仅跳过 1 条(永久失败)
        assert s['processed'] == 1, s                   # 仅重跑 1 条(临时失败)
        assert not any(perm_doi in u for u in fake_a.json_calls), fake_a.json_calls
        assert any(trans_doi in u for u in fake_a.json_calls), fake_a.json_calls
    finally:
        _release(pipe_a)   # 关句柄、保留 out_dir 供 (B) 读

    # (B) retry_failed=True(--retry-failed):永久失败也重跑
    _seed([{'raw_input': perm_doi, 'success': False, 'error': 'download-failed:http-403'}])
    fake_b = FakeClient(json_routes={}, get_routes={})
    pipe_b = _make_pipeline(d, fake_b, retry_failed=True)
    try:
        s2 = pipe_b.run([perm_doi])
        assert s2['skipped_resume'] == 0, s2            # 永久失败不再跳过
        assert s2['processed'] == 1, s2
        assert any(perm_doi in u for u in fake_b.json_calls), fake_b.json_calls
    finally:
        _teardown(pipe_b, d)


def main() -> int:
    test_shortcircuit()
    test_fallback()
    test_landing()
    test_miss()
    test_artifacts_and_summary()
    test_resume()
    test_resume_retry_failed()
    print("E2E_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
