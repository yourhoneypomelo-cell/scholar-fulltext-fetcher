#!/usr/bin/env python3
"""数据回归(纯读、可重跑):防内容 QC 门从「并集(union)」退化回「交集」。

背景(经验记录 L.3):审计实锤 189 条**同域错论文**(publisher 61 + repository 128:同社他篇/
仓库托管他篇)跨社第二信号不触发,旧「交集(标题不符 AND 跨社信号)」会整批放行;并集单信号
即硬拒。另有 34 条 151 判 match/uncertain 但 url_wrong=True 的 **title 假匹配**(标题分≥50 却
是另一篇文),须由门②(URL/嵌入 DOI 跨社)兜住。本脚本把两桶逐条重放到 download.py 现门:

  检查①(189 同域桶):qc_merge_union_wrong.csv 里 verdict_151==mismatch 且下载域属
      publisher/repository 桶 → 现门应**全拒**;并模拟旧交集口径对照,断言交集确实会漏
      (证明现实现是并集,不是交集)。
  检查②(34 假匹配桶):verdict_151∈{match,uncertain} 的行(审计已定性 url_wrong 错论文)
      → 现门应**全拒**(门②独立于标题)。

依赖数据:out/qc_merge_union_wrong.csv + 各批 metadata.jsonl(期望标题)+ 被隔离到
rejected/ 的 PDF(resolve_pdf_path 兜底)。数据缺失 → 显式报错退出(数据回归,不装 PASS)。
护栏:纯读 out/,不写任何文件,不联网。

用法:python -m tools.regress_qc_union_189    (run_all_selftests 里由 RUN_DATA_REGRESS=1 触发)
通过标志:REGRESS_UNION_189_OK
"""
from __future__ import annotations

import csv
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import fulltext_fetcher.download as dl                      # noqa: E402
from tools.qc_content_match import (                         # noqa: E402
    _source_bucket, _url_domain, extract_pdf, resolve_pdf_path,
)

CSV = os.path.join(ROOT, "out", "qc_merge_union_wrong.csv")


def load_expected_titles() -> dict:
    """doi → 期望 title(取自各批 metadata.jsonl;CSV 里没有完整期望标题)。"""
    titles: dict = {}
    for meta in glob.glob(os.path.join(ROOT, "out", "*", "metadata.jsonl")):
        try:
            with open(meta, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    d = (rec.get("doi") or "").lower()
                    if d and rec.get("title") and d not in titles:
                        titles[d] = rec["title"]
        except Exception:  # noqa: BLE001
            continue
    return titles


def _replay(row: dict, titles: dict, m: dict):
    """CSV 行 → (verdict, score, reason) | None(PDF/标题缺失,无法重放)。"""
    exp_title = titles.get(row["doi"].lower())
    if not exp_title:
        return None
    path, _loc = resolve_pdf_path(row["pdf_path"])
    if not path:
        return None
    meta_title, text, err = extract_pdf(path)
    if err is not None:
        return None
    return dl._content_qc_verdict(row["pdf_url"], meta_title, text, exp_title, row["doi"], m)


def main() -> int:
    if not os.path.isfile(CSV):
        print(f"BLOCKED: 缺数据文件 {CSV}(本回归依赖审计产物,不可脱数据运行)", file=sys.stderr)
        return 2
    m = dl._qc_matchers()
    if m is None:
        print("BLOCKED: 缺 pypdf/rapidfuzz/tools.qc_content_match,无法回归", file=sys.stderr)
        return 2
    titles = load_expected_titles()
    rows = list(csv.DictReader(open(CSV, encoding="utf-8-sig")))

    # ── 检查①:189 同域错论文桶(publisher+repository)→ 并集全拒;旧交集必漏 ──
    same_domain = [r for r in rows if r["verdict_151"] == "mismatch"
                   and _source_bucket(_url_domain(r["pdf_url"])) in ("publisher", "repository")]
    union_reject = inter_reject = skipped = 0
    leaked = []
    for r in same_domain:
        res = _replay(r, titles, m)
        if res is None:
            skipped += 1
            continue
        verdict, score, reason = res
        if verdict == "mismatch":
            union_reject += 1
        else:
            leaked.append((r["doi"], verdict, round(score, 1), reason))
        # 旧交集口径对照:标题不符(门①) AND 第二信号(门②) 同时成立才拒
        path, _ = resolve_pdf_path(r["pdf_path"])
        _mt, text, _err = extract_pdf(path)
        conflict, _why = dl._qc_doi_publisher_conflict(r["pdf_url"], text, r["doi"], m["norm_for_doi"])
        exp = m["clean_title"](titles.get(r["doi"].lower()))
        score_t = max(
            m["token_set_ratio"](exp, m["clean_title"](_mt)) if (exp and _mt) else -1.0,
            m["token_set_ratio"](exp, m["clean_title"](text)) if (exp and text) else -1.0,
        )
        title_bad = (not m["is_unextractable"](text)) and (0 <= score_t < m["mismatch_lo"])
        if title_bad and conflict:
            inter_reject += 1

    n1 = len(same_domain) - skipped
    print(f"[1] 同域错论文桶: {len(same_domain)} 条(可重放 {n1}) | 并集拒 {union_reject} | "
          f"旧交集拒 {inter_reject}(漏 {union_reject - inter_reject})")
    for t in leaked[:10]:
        print("    并集放行(异常,需人核):", t)
    ok1 = n1 > 0 and union_reject == n1 and union_reject > inter_reject

    # ── 检查②:34 条 title 假匹配桶(151 判 match/uncertain 但审计定性 url_wrong)→ 门②全拒 ──
    fake_match = [r for r in rows if r["verdict_151"] in ("match", "uncertain")]
    g2_reject = g2_pass = g2_skip = 0
    passed = []
    for r in fake_match:
        res = _replay(r, titles, m)
        if res is None:
            g2_skip += 1
            continue
        verdict, score, reason = res
        if verdict == "mismatch":
            g2_reject += 1
        else:
            g2_pass += 1
            passed.append((r["doi"], verdict, round(score, 1), reason))
    n2 = len(fake_match) - g2_skip
    print(f"[2] title假匹配桶: {len(fake_match)} 条(可重放 {n2}) | 门②拒 {g2_reject} | 放行 {g2_pass}")
    for t in passed[:10]:
        print("    门②放行(异常,需人核):", t)
    ok2 = n2 > 0 and g2_pass == 0

    if ok1 and ok2:
        print("REGRESS_UNION_189_OK")
        return 0
    print("REGRESS_UNION_189_FAIL", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
