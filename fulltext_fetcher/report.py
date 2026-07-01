"""运行结果导出:带状态的结果表(CSV)+ 自包含 HTML 报表。

零第三方依赖(标准库 csv + html)。由 pipeline 在每次运行结束后自动生成:
  out/results.csv  —— 每条输入一行,含 success/source/pdf_path/error 等(UTF-8-SIG,Excel 友好)
  out/report.html  —— 总览 + 各源贡献 + 失败原因分布 + 结果明细,浏览器直接打开

设计:纯函数、零依赖、对异常容忍(由 pipeline 包 try 兜底,生成失败不影响主流程)。
"""
from __future__ import annotations

import csv
import html
import time
from collections import Counter
from typing import Any, Dict, List

_CSV_FIELDS = [
    "raw_input", "kind", "doi", "title", "success", "source_used",
    "pdf_path", "pdf_bytes", "candidates", "elapsed_ms", "error", "pdf_url",
]


def _as_dict(r: Any) -> Dict[str, Any]:
    return r.to_dict() if hasattr(r, "to_dict") else dict(r)


def write_results_csv(results: List[Any], path: str) -> None:
    """把结果列表写成带状态的 CSV(utf-8-sig 便于 Excel 直接打开不乱码)。"""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in results:
            d = _as_dict(r)
            w.writerow({k: d.get(k) for k in _CSV_FIELDS})


def _error_kind(err: str) -> str:
    """把细节各异的 error 归并成一类(便于统计):去掉冒号/括号后缀。"""
    if not err:
        return "(unknown)"
    return err.split(":", 1)[0].split("(", 1)[0].strip() or "(unknown)"


def write_summary_html(summary: Dict[str, Any], results: List[Any], path: str) -> None:
    """生成自包含 HTML 报表(总览 + 各源贡献 + 失败原因 + 结果明细)。"""
    dicts = [_as_dict(r) for r in results]

    succ = int(summary.get("success", 0))
    proc = int(summary.get("processed", 0))
    rate = float(summary.get("success_rate", 0.0)) * 100
    elapsed = summary.get("elapsed_sec", 0)
    ts = summary.get("ts") or time.strftime("%Y-%m-%d %H:%M:%S")
    by_source = summary.get("by_source") or {}

    fail: Counter = Counter()
    for d in dicts:
        if not d.get("success"):
            fail[_error_kind(d.get("error") or "")] += 1

    def esc(x: Any) -> str:
        return html.escape("" if x is None else str(x))

    rows_src = "".join(
        f"<tr><td>{esc(k)}</td><td class=num>{esc(v)}</td>"
        f"<td class=num>{(v / succ * 100):.0f}%</td></tr>"
        for k, v in by_source.items()
    ) or "<tr><td colspan=3>(无)</td></tr>"

    rows_fail = "".join(
        f"<tr><td>{esc(k)}</td><td class=num>{esc(v)}</td></tr>"
        for k, v in fail.most_common()
    ) or "<tr><td colspan=2>(无失败)</td></tr>"

    rows_detail = "".join(
        f"<tr class={'ok' if d.get('success') else 'miss'}>"
        f"<td>{esc(d.get('raw_input'))}</td><td>{esc(d.get('doi'))}</td>"
        f"<td>{'OK' if d.get('success') else 'MISS'}</td>"
        f"<td>{esc(d.get('source_used'))}</td><td>{esc(d.get('error'))}</td></tr>"
        for d in dicts
    ) or "<tr><td colspan=5>(无)</td></tr>"

    doc = f"""<!doctype html><html lang=zh><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>fulltext_fetcher 运行报表</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,'Microsoft YaHei',sans-serif;margin:24px;color:#1a1a1a;background:#fafafa}}
 h1{{font-size:20px}} h2{{font-size:15px;margin-top:28px;border-left:4px solid #2563eb;padding-left:8px}}
 .cards{{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0}}
 .card{{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 20px;min-width:120px}}
 .card .v{{font-size:24px;font-weight:700;color:#2563eb}} .card .l{{font-size:12px;color:#6b7280}}
 table{{border-collapse:collapse;width:100%;background:#fff;font-size:13px}}
 th,td{{border:1px solid #e5e7eb;padding:6px 10px;text-align:left;word-break:break-all}}
 th{{background:#f3f4f6}} td.num{{text-align:right;font-variant-numeric:tabular-nums}}
 tr.ok td:nth-child(3){{color:#059669;font-weight:700}} tr.miss td:nth-child(3){{color:#dc2626}}
 .muted{{color:#6b7280;font-size:12px;margin-top:4px}}
</style></head><body>
<h1>fulltext_fetcher 运行报表</h1>
<div class=muted>生成时间 {esc(ts)}</div>
<div class=cards>
 <div class=card><div class=v>{proc}</div><div class=l>处理条数</div></div>
 <div class=card><div class=v>{succ}</div><div class=l>成功下载</div></div>
 <div class=card><div class=v>{rate:.1f}%</div><div class=l>成功率</div></div>
 <div class=card><div class=v>{esc(elapsed)}s</div><div class=l>耗时</div></div>
</div>
<h2>各源成功贡献</h2>
<table><tr><th>源</th><th>成功数</th><th>占成功</th></tr>{rows_src}</table>
<h2>失败原因分布(按最终结果)</h2>
<table><tr><th>原因</th><th>次数</th></tr>{rows_fail}</table>
<p class=muted>更细的逐源/逐次失败见 attempts.jsonl。</p>
<h2>结果明细({proc} 条)</h2>
<table><tr><th>输入</th><th>DOI</th><th>状态</th><th>命中源</th><th>错误</th></tr>{rows_detail}</table>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


if __name__ == "__main__":  # 纯函数 selftest(不联网): python fulltext_fetcher/report.py
    import os
    import tempfile

    # 样例:3 成功(unpaywall×2 / openalex×1)+ 1 失败,覆盖成功率/各源/失败原因/明细四块
    _results = [
        {"raw_input": "10.1111/aaa", "kind": "doi", "doi": "10.1111/aaa",
         "title": "Paper A", "success": True, "source_used": "unpaywall",
         "pdf_path": "out/pdfs/aaa.pdf", "pdf_bytes": 12345, "candidates": 3,
         "elapsed_ms": 120, "error": None, "pdf_url": "https://ex.org/aaa.pdf"},
        {"raw_input": "10.2222/bbb", "kind": "doi", "doi": "10.2222/bbb",
         "title": "Paper B", "success": True, "source_used": "unpaywall",
         "pdf_path": "out/pdfs/bbb.pdf", "pdf_bytes": 22222, "candidates": 2,
         "elapsed_ms": 200, "error": None, "pdf_url": "https://ex.org/bbb.pdf"},
        {"raw_input": "arXiv:2101.00001", "kind": "arxiv",
         "doi": "10.48550/arxiv.2101.00001", "title": "Paper C", "success": True,
         "source_used": "openalex", "pdf_path": "out/pdfs/ccc.pdf", "pdf_bytes": 33333,
         "candidates": 1, "elapsed_ms": 90, "error": None,
         "pdf_url": "https://ex.org/ccc.pdf"},
        {"raw_input": "Some Unfindable Title", "kind": "title", "doi": "",
         "title": "Some Unfindable Title", "success": False, "source_used": None,
         "pdf_path": None, "pdf_bytes": 0, "candidates": 0, "elapsed_ms": 50,
         "error": "HTTP 404: not found", "pdf_url": None},
    ]
    _summary = {
        "processed": 4, "success": 3, "miss": 1, "success_rate": 0.75,
        "elapsed_sec": 2, "ts": "2026-07-01 00:00:00",
        "by_source": {"unpaywall": 2, "openalex": 1},
    }

    with tempfile.TemporaryDirectory() as _d:
        _csv_path = os.path.join(_d, "results.csv")
        _html_path = os.path.join(_d, "report.html")
        write_results_csv(_results, _csv_path)
        write_summary_html(_summary, _results, _html_path)

        # —— CSV:表头一致 + 行数 + 关键字段(含成功/失败状态与错误)——
        with open(_csv_path, "r", encoding="utf-8-sig", newline="") as _f:
            _reader = csv.DictReader(_f)
            assert _reader.fieldnames == _CSV_FIELDS, _reader.fieldnames
            _rows = list(_reader)
        assert len(_rows) == 4, len(_rows)
        assert _rows[0]["raw_input"] == "10.1111/aaa", _rows[0]
        assert _rows[0]["success"] == "True", _rows[0]["success"]
        assert _rows[0]["source_used"] == "unpaywall", _rows[0]
        assert _rows[3]["success"] == "False", _rows[3]["success"]
        assert "404" in _rows[3]["error"], _rows[3]["error"]

        # —— HTML:自包含 + 成功率 / 各源贡献 / 失败原因 / 明细 四大块齐全 ——
        with open(_html_path, "r", encoding="utf-8") as _f:
            _doc = _f.read()
        assert "<!doctype html>" in _doc.lower(), "应为自包含 HTML"
        assert "75.0%" in _doc, "缺成功率"
        assert "成功率" in _doc and "各源成功贡献" in _doc, "缺总览/各源标题块"
        assert "失败原因" in _doc and "结果明细" in _doc, "缺失败原因/明细标题块"
        assert "unpaywall" in _doc and "openalex" in _doc, "缺各源贡献明细"
        assert "HTTP 404" in _doc, "缺失败原因归并(_error_kind)"
        assert "10.1111/aaa" in _doc and "Some Unfindable Title" in _doc, "缺结果明细行"

    print("REPORT_OK")
