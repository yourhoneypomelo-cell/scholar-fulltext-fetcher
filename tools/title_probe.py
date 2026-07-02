"""北极星『输入标题』路径端到端验证:标题 → resolve(title→DOI) → 下载。

用途:回答『输入的是论文标题(而非 DOI),系统能否①把标题正确解析到 DOI、②再走通下载拿到
正确的 PDF』。做法是从**已成功且高可信**的历史 metadata 里取「真值 (标题, DOI)」对——
只取 kind=doi 且 source_used 为 DOI-keyed(非 websearch/wayback/browser_search/landing)的成功
记录,这类记录的 title 是「用该 DOI 富化出来的」,故 (标题↔DOI) 权威可作真值。把这些**标题**
当输入喂回 pipeline(全新 -o),再把解析出的 DOI 与真值 DOI 对比,得到解析命中率/端到端正确率。

两个子命令:
  pick     从历史 metadata 选 N 篇代表性标题,写 titles_probe.txt(输入) + titles_probe_truth.json(真值)
  analyze  读 out/title_probe/metadata.jsonl,与真值对比,给命中率/端到端正确率/失败模式(打印+JSON)

命中口径:
  - 严格命中(strict): 解析出的 DOI == 真值 DOI(归一后)。这是诚实的『标题→DOI』命中率。
  - 软命中(soft)    : DOI 不同,但解析结果的富化标题与真值标题 Jaccard≥0.6 —— 多为同一篇的
                       不同 DOI(预印本/勘误/版本),单列出来供判读,不掩盖严格口径。
  - 端到端正确 PDF  : 严格命中 AND 成功落盘 pdf(文件确实在盘)。

安全:pick 只读历史 metadata;analyze 只读 out/title_probe/*;两者只写你用参数指定的输出文件。
  本工具**不联网、不下载**;真正的抓取由 `python -m fulltext_fetcher -f titles_probe.txt -o out/title_probe`
  完成(那一步才联网)。

用法:
    python tools/title_probe.py pick --n 20 -o titles_probe.txt --truth titles_probe_truth.json
    python -m fulltext_fetcher -f titles_probe.txt -o out/title_probe --email you@uni.edu
    python tools/title_probe.py analyze --truth titles_probe_truth.json --meta out/title_probe/metadata.jsonl
    python tools/title_probe.py --selftest
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

# 复用 resolve 的标题归一/相似度,口径与 pipeline 完全一致(严禁另造匹配逻辑)。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fulltext_fetcher.resolve import _norm_title, _title_similarity  # noqa: E402  # type: ignore

_DEFAULT_CORPORA = ["out/batch4_p1", "out/batch4_p2", "out/batch4_p3", "out/batch4_p4",
                    "out/batch4_p5", "out/batch6", "out/batch7"]
# 非 DOI-keyed(靠自由文本/落地页,假阳风险高)——取真值时排除,确保 title↔DOI 权威。
_QC_MARK = ("websearch", "wayback", "browser_search", "landing")
# 前缀 → 出版商标签(仅用于分层挑选 & 报告展示)。
_PUB = {
    "10.1021": "acs", "10.1016": "elsevier", "10.1002": "wiley", "10.1039": "rsc",
    "10.1038": "nature", "10.3390": "mdpi", "10.1126": "science", "10.3389": "frontiers",
    "10.1007": "springer", "10.1103": "aps", "10.1073": "pnas", "10.1186": "bmc",
    "10.1021/": "acs",
}
# source_used 命中即视为「OA 取得」(用于 OA/付费混样,近似)。
_OA_SOURCES = ("publisher_oa", "unpaywall", "europe_pmc", "openaire", "zenodo",
               "preprints", "hal", "arxiv", "pmc", "core", "doaj")
# 挑选时的出版商优先顺序(保证覆盖主流社,不被 ACS 淹没)。
_PUB_ORDER = ["elsevier", "acs", "wiley", "rsc", "nature", "mdpi", "science",
              "springer", "frontiers", "aps", "pnas", "bmc", "other"]


def norm_doi(doi: Optional[str]) -> str:
    """DOI 归一:小写 + 去尾部标点(与 resolve._normalize_doi 一致)。"""
    return (doi or "").strip().rstrip(".,);").lower()


def pub_of(doi: Optional[str]) -> str:
    m = re.match(r"(10\.\d{4,9})", norm_doi(doi))
    return _PUB.get(m.group(1), "other") if m else "other"


def oa_hint(source: Optional[str]) -> str:
    s = str(source or "").lower()
    return "oa" if any(x in s for x in _OA_SOURCES) else "mixed"


def era_hint(doi: Optional[str]) -> str:
    """粗略新旧:Elsevier 老式 S/纯数字刊号、或明显 20xx 前后。仅供报告参考(metadata 无年份)。"""
    d = norm_doi(doi)
    suf = d.split("/", 1)[1] if "/" in d else ""
    if re.match(r"(s?0|0)\d", suf) or re.match(r"s\d", suf):
        return "old"          # 10.1016/0920-.. 或 10.1016/s0926-.. 等旧刊号
    m = re.search(r"(19|20)(\d{2})", suf)
    if m:
        yr = int(m.group(0)[:4])
        return "old" if yr < 2015 else "new"
    return "unknown"


def clean_title(t: Optional[str]) -> str:
    """把 metadata 里的标题清成『人会粘贴的样子』:反转义 HTML 实体、去 <sub>/<i> 等标签、并空白。"""
    s = html.unescape(t or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    recs: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return recs
    for line in open(path, "r", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except ValueError:
            continue
    return recs


# ── pick:选代表性标题 + 真值 ─────────────────────────────────────────────────
def collect_truth_pool(corpora: List[str]) -> List[Dict[str, Any]]:
    """从各 metadata.jsonl 收「权威真值」候选:success & kind=doi & DOI-keyed & 有 doi/title。"""
    pool: List[Dict[str, Any]] = []
    seen_doi: set = set()
    seen_title: set = set()
    for d in corpora:
        for r in _read_jsonl(os.path.join(d, "metadata.jsonl")):
            if not (r.get("success") and r.get("doi") and r.get("title")):
                continue
            if r.get("kind") != "doi":
                continue
            su = str(r.get("source_used") or "").lower()
            if any(m in su for m in _QC_MARK):
                continue
            doi = norm_doi(r.get("doi"))
            title = clean_title(r.get("title"))
            nt = _norm_title(title)
            if not doi or not title or len(nt) < 12:      # 太短的标题判重不可靠,跳过
                continue
            if doi in seen_doi or nt in seen_title:
                continue
            seen_doi.add(doi)
            seen_title.add(nt)
            pool.append({"title": title, "true_doi": doi, "publisher": pub_of(doi),
                         "oa_hint": oa_hint(su), "era": era_hint(doi),
                         "source_used": r.get("source_used")})
    return pool


def select_diverse(pool: List[Dict[str, Any]], n: int, max_per_pub: int = 3) -> List[Dict[str, Any]]:
    """分层挑选:按出版商轮转、每社≤max_per_pub、社内交替 oa/mixed 且尽量含 old,凑够 n。"""
    by_pub: Dict[str, List[Dict[str, Any]]] = {}
    for r in pool:
        by_pub.setdefault(r["publisher"], []).append(r)
    # 社内排序:oa 与 mixed 交替、old 优先靠前(doi 升序时旧刊号天然靠前)。
    for pub, lst in by_pub.items():
        lst.sort(key=lambda r: (r["oa_hint"] != "oa", r["era"] != "old", r["true_doi"]))
    order = [p for p in _PUB_ORDER if p in by_pub] + [p for p in by_pub if p not in _PUB_ORDER]
    picked: List[Dict[str, Any]] = []
    idx = {p: 0 for p in order}
    count = {p: 0 for p in order}
    while len(picked) < n:
        progressed = False
        for p in order:
            if len(picked) >= n:
                break
            if count[p] >= max_per_pub:
                continue
            lst = by_pub[p]
            if idx[p] < len(lst):
                picked.append(lst[idx[p]])
                idx[p] += 1
                count[p] += 1
                progressed = True
        if not progressed:
            break
    return picked


def do_pick(args: argparse.Namespace) -> int:
    pool = collect_truth_pool(args.scan)
    if not pool:
        print("错误:真值候选池为空(未找到符合条件的成功记录)。", file=sys.stderr)
        return 1
    picked = select_diverse(pool, args.n, args.max_per_pub)
    # 写输入清单(仅标题,每行一条)。
    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("# title-probe 输入:每行一个论文标题(由 tools/title_probe.py pick 生成)\n")
        for r in picked:
            f.write(r["title"] + "\n")
    # 写真值 JSON。
    with open(args.truth, "w", encoding="utf-8") as f:
        json.dump({"count": len(picked), "items": picked}, f, ensure_ascii=False, indent=2)

    from collections import Counter
    print("=" * 64, file=sys.stderr)
    print(f"已选 {len(picked)} 篇标题 → {args.output}(真值 → {args.truth})", file=sys.stderr)
    print("  出版商:", dict(Counter(r["publisher"] for r in picked)), file=sys.stderr)
    print("  OA/付费:", dict(Counter(r["oa_hint"] for r in picked)), file=sys.stderr)
    print("  新旧  :", dict(Counter(r["era"] for r in picked)), file=sys.stderr)
    print("  候选池总量:", len(pool), file=sys.stderr)
    print("=" * 64, file=sys.stderr)
    print(f"下一步: python -m fulltext_fetcher -f {args.output} -o out/title_probe --email you@uni.edu",
          file=sys.stderr)
    return 0


# ── analyze:对比真值 ─────────────────────────────────────────────────────────
def analyze(truth_items: List[Dict[str, Any]], meta_recs: List[Dict[str, Any]],
            meta_dir: str) -> Dict[str, Any]:
    """把真值与 out/title_probe 结果按归一标题对齐,逐条判 strict/soft/端到端,并汇总。"""
    by_title: Dict[str, Dict[str, Any]] = {}
    for r in meta_recs:
        by_title[_norm_title(clean_title(r.get("raw_input") or r.get("title")))] = r

    rows: List[Dict[str, Any]] = []
    for t in truth_items:
        nt = _norm_title(t["title"])
        rec = by_title.get(nt)
        true_doi = norm_doi(t["true_doi"])
        row: Dict[str, Any] = {
            "title": t["title"], "publisher": t.get("publisher"),
            "oa_hint": t.get("oa_hint"), "era": t.get("era"),
            "true_doi": true_doi, "resolved_doi": None, "success": False,
            "strict_hit": False, "soft_hit": False, "e2e_correct": False,
            "failure_mode": "no-metadata-record", "detail": "",
        }
        if rec is not None:
            resolved = norm_doi(rec.get("doi"))
            got_title = clean_title(rec.get("title"))
            # pdf 存在性:pdf_path 可能是绝对/相对;稳妥用 os.path.exists 原样 + basename 兜底。
            pp = rec.get("pdf_path")
            pdf_ok = bool(pp) and (
                os.path.exists(pp)
                or os.path.exists(os.path.join(meta_dir, "pdfs", os.path.basename(pp)))
                or os.path.exists(os.path.join(meta_dir, os.path.basename(pp)))
            )
            success = bool(rec.get("success")) and pdf_ok
            strict = bool(resolved) and resolved == true_doi
            soft_sim = _title_similarity(_norm_title(t["title"]), _norm_title(got_title)) if got_title else 0.0
            soft = strict or (bool(resolved) and soft_sim >= 0.6)
            row.update({
                "resolved_doi": resolved or None, "success": success,
                "strict_hit": strict, "soft_hit": soft,
                "e2e_correct": strict and success,
                "resolved_title": got_title, "soft_sim": round(soft_sim, 2),
                "source_used": rec.get("source_used"), "error": rec.get("error"),
            })
            if not resolved:
                row["failure_mode"] = "resolve-not-found"
            elif strict:
                row["failure_mode"] = "ok" if success else f"download-failed({rec.get('error')})"
            elif soft:
                row["failure_mode"] = "resolve-diff-doi-same-paper" if success \
                    else f"resolve-diff-doi+download-failed({rec.get('error')})"
            else:
                row["failure_mode"] = "resolve-wrong"
            row["detail"] = f"got={resolved} sim={row['soft_sim']} src={rec.get('source_used')}"
        rows.append(row)

    n = len(rows)
    from collections import Counter
    summ = {
        "n": n,
        "strict_resolve_hits": sum(r["strict_hit"] for r in rows),
        "soft_resolve_hits": sum(r["soft_hit"] for r in rows),
        "e2e_correct_pdf": sum(r["e2e_correct"] for r in rows),
        "downloaded_any": sum(r["success"] for r in rows),
        "strict_resolve_hit_rate": round(sum(r["strict_hit"] for r in rows) / n, 3) if n else 0,
        "soft_resolve_hit_rate": round(sum(r["soft_hit"] for r in rows) / n, 3) if n else 0,
        "e2e_correct_pdf_rate": round(sum(r["e2e_correct"] for r in rows) / n, 3) if n else 0,
        "failure_modes": dict(Counter(r["failure_mode"] for r in rows)),
        "by_publisher": dict(Counter(r["publisher"] for r in rows)),
    }
    return {"summary": summ, "rows": rows}


def do_analyze(args: argparse.Namespace) -> int:
    truth = json.load(open(args.truth, encoding="utf-8"))
    items = truth["items"] if isinstance(truth, dict) else truth
    meta_recs = _read_jsonl(args.meta)
    meta_dir = os.path.dirname(os.path.abspath(args.meta))
    res = analyze(items, meta_recs, meta_dir)
    s = res["summary"]
    print("=" * 72, file=sys.stderr)
    print("标题输入路径 端到端结果(对比真值)", file=sys.stderr)
    print("-" * 72, file=sys.stderr)
    print(f"  样本 N            : {s['n']}", file=sys.stderr)
    print(f"  严格解析命中      : {s['strict_resolve_hits']}/{s['n']} "
          f"({s['strict_resolve_hit_rate']*100:.0f}%)  [解析DOI==真值DOI]", file=sys.stderr)
    print(f"  软解析命中        : {s['soft_resolve_hits']}/{s['n']} "
          f"({s['soft_resolve_hit_rate']*100:.0f}%)  [含同篇不同DOI]", file=sys.stderr)
    print(f"  端到端正确 PDF    : {s['e2e_correct_pdf']}/{s['n']} "
          f"({s['e2e_correct_pdf_rate']*100:.0f}%)  [严格命中 AND 落盘]", file=sys.stderr)
    print(f"  任意成功落盘      : {s['downloaded_any']}/{s['n']}", file=sys.stderr)
    print("-" * 72, file=sys.stderr)
    print("  失败模式分布:", file=sys.stderr)
    for k, v in sorted(s["failure_modes"].items(), key=lambda kv: -kv[1]):
        print(f"    {v:>3}  {k}", file=sys.stderr)
    print("-" * 72, file=sys.stderr)
    print("  逐条:", file=sys.stderr)
    for r in res["rows"]:
        flag = "OK " if r["e2e_correct"] else ("~  " if r["soft_hit"] else "XX ")
        print(f"    {flag}[{r['publisher']:<9}{r['era']:<4}] {r['failure_mode']}", file=sys.stderr)
        print(f"         真值 {r['true_doi']}  →  解析 {r.get('resolved_doi')}  "
              f"(sim={r.get('soft_sim')}, src={r.get('source_used')})", file=sys.stderr)
        print(f"         « {r['title'][:90]} »", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"已写出分析 JSON → {args.out_json}", file=sys.stderr)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")      # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")      # type: ignore[attr-defined]
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="标题输入路径端到端验证(pick / analyze)。",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    if argv is None:
        argv = sys.argv[1:]
    if "--selftest" in argv:
        return _selftest()
    sub = ap.add_subparsers(dest="cmd", required=True)

    pk = sub.add_parser("pick", help="选代表性标题 + 真值")
    pk.add_argument("--scan", nargs="*", default=_DEFAULT_CORPORA, metavar="DIR")
    pk.add_argument("--n", type=int, default=20)
    pk.add_argument("--max-per-pub", type=int, default=3)
    pk.add_argument("-o", "--output", default="titles_probe.txt")
    pk.add_argument("--truth", default="titles_probe_truth.json")
    pk.set_defaults(func=do_pick)

    an = sub.add_parser("analyze", help="对比真值给命中率/失败模式")
    an.add_argument("--truth", default="titles_probe_truth.json")
    an.add_argument("--meta", default="out/title_probe/metadata.jsonl")
    an.add_argument("--out-json", default="out/title_probe/_title_probe_analysis.json")
    an.set_defaults(func=do_analyze)

    args = ap.parse_args(argv)
    return args.func(args)


# ── 离线自检(不联网、不读项目文件)──────────────────────────────────────────
def _selftest() -> int:
    import shutil
    import tempfile

    assert pub_of("10.1021/acs.iecr.9b01153") == "acs"
    assert pub_of("10.1016/j.jcou.2021.101493") == "elsevier"
    assert oa_hint("publisher_oa:acs-authorchoice") == "oa"
    assert oa_hint("crossref") == "mixed"
    assert clean_title("Highly Active Ni/La<sub>2</sub>O<sub>3</sub> for CO&amp;X") == \
        "Highly Active Ni/La 2 O 3 for CO&X"
    assert era_hint("10.1016/s0926-860x(00)00611-6") == "old"

    tmp = tempfile.mkdtemp(prefix="title_probe_selftest_")
    try:
        # 构造历史成功集(真值池):两条 DOI-keyed 成功 + 一条 websearch(应被排除)
        d = os.path.join(tmp, "out", "b")
        os.makedirs(d)
        with open(os.path.join(d, "metadata.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"raw_input": "10.1021/x1", "kind": "doi", "doi": "10.1021/x1",
                                "title": "Copper Catalysts for CO2 Reduction to Ethylene",
                                "success": True, "source_used": "unpaywall"}) + "\n")
            f.write(json.dumps({"raw_input": "10.1016/y1", "kind": "doi", "doi": "10.1016/y1",
                                "title": "Nickel Ceria Reverse Water Gas Shift Kinetics Study",
                                "success": True, "source_used": "crossref"}) + "\n")
            f.write(json.dumps({"raw_input": "some title", "kind": "title", "doi": "10.9/z",
                                "title": "Should Be Excluded Websearch Hit Paper",
                                "success": True, "source_used": "websearch+landing"}) + "\n")
        pool = collect_truth_pool([d])
        assert len(pool) == 2, pool
        picked = select_diverse(pool, 5)
        assert len(picked) == 2, picked

        # 模拟 pipeline 结果 out/title_probe/metadata.jsonl:
        #  - x1: 标题正确解析回 10.1021/x1 且落盘 → 端到端正确
        #  - y1: 解析到"错 DOI"(标题也不同) → resolve-wrong
        tp = os.path.join(tmp, "out", "title_probe")
        os.makedirs(os.path.join(tp, "pdfs"))
        pdf1 = os.path.join(tp, "pdfs", "x1.pdf")
        open(pdf1, "wb").write(b"%PDF-1.4 test")
        meta = os.path.join(tp, "metadata.jsonl")
        with open(meta, "w", encoding="utf-8") as f:
            f.write(json.dumps({"raw_input": "Copper Catalysts for CO2 Reduction to Ethylene",
                                "kind": "title", "doi": "10.1021/x1",
                                "title": "Copper Catalysts for CO2 Reduction to Ethylene",
                                "success": True, "pdf_path": pdf1,
                                "source_used": "unpaywall"}) + "\n")
            f.write(json.dumps({"raw_input": "Nickel Ceria Reverse Water Gas Shift Kinetics Study",
                                "kind": "title", "doi": "10.5/wrong",
                                "title": "A Completely Different Paper About Bird Migration",
                                "success": True, "pdf_path": None,
                                "source_used": "crossref"}) + "\n")
        res = analyze(pool, _read_jsonl(meta), tp)
        s = res["summary"]
        assert s["n"] == 2, s
        assert s["strict_resolve_hits"] == 1, s
        assert s["e2e_correct_pdf"] == 1, s
        fm = s["failure_modes"]
        assert fm.get("ok") == 1 and fm.get("resolve-wrong") == 1, fm

        print("TITLE_PROBE_OK")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
