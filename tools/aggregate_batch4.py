"""batch4 权威汇总:跨 5 分片(batch4_p1..p5)去重 union「真实成功率」,并与 batch6 去重对比。

为什么需要这个脚本(而不是直接看 summary.json):
- pipeline 的 summary.json 只统计「本次运行 processed 的条数」。断点续跑时 skipped_resume 的
  历史成功不计入 success,故 summary.success 会**低估**真实成功(例:batch6 summary.success=336,
  但 pdfs/ 实有 410、metadata.jsonl 有 1356 行含大量续跑重复)。
- 因此权威口径应以「metadata.jsonl 去重 + pdfs/ 落盘实证」为准,而非 summary.json。

口径定义:
- dedup key:规范化 DOI(优先 doi 字段,回退 raw_input;小写、去 doi.org/doi: 前缀)。
- 「真实成功(real)」:某 DOI 至少有一条 success==true 且其 pdf_path 对应文件**确实存在**于该分片 pdfs/。
- union:5 分片按 DOI 去重后,至少一处真实成功即计 1。
- success_rate = union_real_success / TOTAL_INPUTS(默认 500)。

安全:只读 out/ 下已有产物,只新写 out/batch4_aggregate.json,绝不改动任何其它文件。
可重复:分片仍在跑时可先 dry-run(结果标 final=false);5 片 summary.json 齐后重跑出终值。

用法:
    python tools/aggregate_batch4.py               # 汇总并写 out/batch4_aggregate.json
    python tools/aggregate_batch4.py --no-write     # 只打印,不落盘
    python tools/aggregate_batch4.py --out X.json    # 指定输出路径
    python tools/aggregate_batch4.py --total 500     # 覆盖输入总数(默认 500)
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

OUT_DIR = "out"
BATCH4_SHARDS = [f"batch4_p{i}" for i in range(1, 6)]
BATCH6_DIR = "batch6"
DEFAULT_TOTAL = 500

_DOI_PREFIXES = (
    "https://doi.org/", "http://doi.org/",
    "https://dx.doi.org/", "http://dx.doi.org/", "doi:",
)


def norm_doi(rec: Dict[str, Any]) -> Optional[str]:
    """规范化去重键:优先 doi,回退 raw_input;小写、去常见 DOI 前缀。"""
    for key in ("doi", "raw_input"):
        v = (rec.get(key) or "").strip().lower()
        for pre in _DOI_PREFIXES:
            if v.startswith(pre):
                v = v[len(pre):].strip()
        if v:
            return v
    return None


def basename_of(pdf_path: Optional[str]) -> Optional[str]:
    """取 pdf_path 的文件名。metadata 里是混合分隔符(out/batch4_p1\\pdfs\\x.pdf)。"""
    if not pdf_path:
        return None
    return pdf_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or None


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    """稳健读取 jsonl;跳过空行与半截行(分片仍在写时最后一行可能不完整)。"""
    recs: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return recs
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except ValueError:
                continue
    return recs


def pdf_basenames(shard_full: str) -> Set[str]:
    d = os.path.join(shard_full, "pdfs")
    if not os.path.isdir(d):
        return set()
    return {n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n))}


def load_summary(shard_full: str) -> Optional[Dict[str, Any]]:
    p = os.path.join(shard_full, "summary.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return None


def collect(shard_names: List[str]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """扫描给定分片,返回 (doi -> 最佳记录, 每分片统计)。

    最佳记录按 rank 取:2=真实成功 > 1=仅 metadata 声称成功 > 0=失败。
    """
    best: Dict[str, Dict[str, Any]] = {}
    per_shard: List[Dict[str, Any]] = []
    for name in shard_names:
        full = os.path.join(OUT_DIR, name)
        recs = read_jsonl(os.path.join(full, "metadata.jsonl"))
        pdfs = pdf_basenames(full)
        summ = load_summary(full)
        meta_success = sum(1 for r in recs if r.get("success"))
        per_shard.append({
            "shard": name,
            "exists": os.path.isdir(full),
            "metadata_lines": len(recs),
            "metadata_success_lines": meta_success,
            "pdf_files_on_disk": len(pdfs),
            "has_summary": summ is not None,
            "summary_success": (summ or {}).get("success"),
            "summary_processed": (summ or {}).get("processed"),
        })
        for r in recs:
            doi = norm_doi(r)
            if not doi:
                continue
            bn = basename_of(r.get("pdf_path"))
            real = bool(r.get("success") and bn and bn in pdfs)
            rank = 2 if real else (1 if r.get("success") else 0)
            cur = best.get(doi)
            if cur is None or rank > cur["_rank"]:
                best[doi] = {
                    "_shard": name, "_real": real, "_rank": rank,
                    "success": bool(r.get("success")),
                    "source_used": r.get("source_used"),
                    "error": r.get("error"),
                    "pdf_bytes": r.get("pdf_bytes"),
                }
    return best, per_shard


def real_dois(best: Dict[str, Dict[str, Any]]) -> Set[str]:
    return {doi for doi, r in best.items() if r["_real"]}


def by_source_counts(best: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    c = Counter(r.get("source_used") or "?" for r in best.values() if r["_real"])
    return dict(c.most_common())


def top_errors(best: Dict[str, Dict[str, Any]], n: int = 8) -> Dict[str, int]:
    c = Counter(
        (r.get("error") or "?") for r in best.values()
        if not r["_real"] and r.get("_rank", 0) < 2)
    return dict(c.most_common(n))


def aggregate(total: int) -> Dict[str, Any]:
    best4, per_shard4 = collect(BATCH4_SHARDS)
    best6, per_shard6 = collect([BATCH6_DIR])

    b4_real = real_dois(best4)
    b6_real = real_dois(best6)

    union_real = len(b4_real)
    union_dois_seen = len(best4)
    pdfs_on_disk = sum(ps["pdf_files_on_disk"] for ps in per_shard4)

    final = all(ps["has_summary"] for ps in per_shard4)

    rate_total = (union_real / total) if total else 0.0          # 最终 KPI(分母=输入总数)
    rate_seen = (union_real / union_dois_seen) if union_dois_seen else 0.0  # 当前已处理口径

    # batch4 与 batch6 是否同一输入集,决定「净增/差异」的口径。
    input_overlap = set(best4) & set(best6)
    disjoint = len(input_overlap) == 0
    b6_real_n = len(b6_real)
    b6_rate = (b6_real_n / total) if total else 0.0

    compare: Dict[str, Any] = {
        "input_doi_overlap": len(input_overlap),
        "inputs_disjoint": disjoint,
        "note": (
            "两批输入 DOI 不相交 → 属不同论文集,按【同规模真实成功计数/成功率】口径可比,"
            "而非同输入 DOI 差集。" if disjoint else
            "两批输入 DOI 有交集 → 同时给出同输入 DOI 差集(net_new/regressions)与成功率对比。"
        ),
        "batch6_real_success": b6_real_n,
        "batch6_success_rate": round(b6_rate, 4),
        "batch4_real_success": union_real,
        "batch4_success_rate_over_total": round(rate_total, 4),
        "batch4_success_rate_over_seen": round(rate_seen, 4),
        "delta_success_count_vs_batch6": union_real - b6_real_n,
        "delta_rate_over_total_vs_batch6": round(rate_total - b6_rate, 4),
    }
    if not disjoint:  # 仅同输入时 DOI 差集才有意义
        compare["net_new_dois"] = sorted(b4_real - b6_real)
        compare["regression_dois"] = sorted(b6_real - b4_real)
        compare["net_new_count"] = len(b4_real - b6_real)
        compare["regressions_count"] = len(b6_real - b4_real)
        compare["overlap_count"] = len(b4_real & b6_real)

    src3 = ", ".join(f"{k}={v}" for k, v in list(by_source_counts(best4).items())[:3]) or "无"
    if final:
        conclusion = (
            f"batch4(终值)去重 union 真实成功 {union_real}/{total} = {rate_total:.1%}"
            f"(落盘 pdf {pdfs_on_disk});主力源 {src3};"
            f"对 batch6({b6_real_n}/{total}={b6_rate:.1%}):成功率差 {rate_total - b6_rate:+.1%}、"
            f"计数差 {union_real - b6_real_n:+d}"
            + ("(两批输入不相交,系同规模成功率口径对比)。" if disjoint else "。")
        )
    else:
        conclusion = (
            f"batch4(部分数据·dry-run,已处理 {union_dois_seen}/{total})当前真实成功 {union_real}:"
            f"已处理口径 {rate_seen:.1%}、占总输入 {rate_total:.1%};主力源 {src3};"
            f"batch6 基线 {b6_real_n}/{total}={b6_rate:.1%}"
            + ("(两批输入不相交,为同规模成功率口径对比、非同输入差集)" if disjoint else "")
            + "。待 5 片 summary.json 齐后重跑出终值再做净增定论。"
        )

    return {
        "total_inputs": total,
        "final": final,
        "batch4": {
            "union_real_success": union_real,
            "success_rate_over_total": round(rate_total, 4),
            "success_rate_over_seen": round(rate_seen, 4),
            "pdf_files_on_disk": pdfs_on_disk,
            "distinct_dois_seen": union_dois_seen,
            "reported_success_deduped": sum(1 for r in best4.values() if r["success"]),
            "by_source_real": by_source_counts(best4),
            "top_errors": top_errors(best4),
            "per_shard": per_shard4,
        },
        "batch6": {
            "real_success": b6_real_n,
            "success_rate": round(b6_rate, 4),
            "pdf_files_on_disk": per_shard6[0]["pdf_files_on_disk"],
            "distinct_dois_seen": len(best6),
            "by_source_real": by_source_counts(best6),
            "per_shard": per_shard6,
        },
        "compare_batch4_vs_batch6": compare,
        "conclusion": conclusion,
    }


def _print_human(agg: Dict[str, Any]) -> None:
    b4, b6, cmp = agg["batch4"], agg["batch6"], agg["compare_batch4_vs_batch6"]
    print("=" * 72)
    print(f"batch4 权威汇总  (final={agg['final']}, total_inputs={agg['total_inputs']})")
    print("-" * 72)
    print(f"{'shard':<11}{'meta_lines':>11}{'meta_succ':>10}{'pdfs':>7}{'summary':>9}")
    for ps in b4["per_shard"]:
        print(f"{ps['shard']:<11}{ps['metadata_lines']:>11}{ps['metadata_success_lines']:>10}"
              f"{ps['pdf_files_on_disk']:>7}{str(ps['has_summary']):>9}")
    print("-" * 72)
    print(f"union 真实成功: {b4['union_real_success']}  "
          f"(占输入 {b4['success_rate_over_total']:.1%} of {agg['total_inputs']}, "
          f"已处理口径 {b4['success_rate_over_seen']:.1%} of {b4['distinct_dois_seen']}, "
          f"落盘 pdf {b4['pdf_files_on_disk']})")
    print(f"by_source(real): {b4['by_source_real']}")
    print(f"batch6 real: {b6['real_success']}/{agg['total_inputs']} = {b6['success_rate']:.1%}  "
          f"(pdf {b6['pdf_files_on_disk']}, DOI {b6['distinct_dois_seen']})")
    print(f"vs batch6 → 计数差 {cmp['delta_success_count_vs_batch6']:+d}, "
          f"成功率差(占总) {cmp['delta_rate_over_total_vs_batch6']:+.1%}, "
          f"输入 DOI 交集 {cmp['input_doi_overlap']} (disjoint={cmp['inputs_disjoint']})")
    if not cmp["inputs_disjoint"]:
        print(f"           同输入差集 → 净增 {cmp['net_new_count']} / 回退 {cmp['regressions_count']} / "
              f"交集 {cmp['overlap_count']}")
    print("=" * 72)
    print(agg["conclusion"])


def main() -> None:
    ap = argparse.ArgumentParser(description="batch4 权威汇总(去重 union 真实成功率 + 对 batch6)")
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "batch4_aggregate.json"),
                    help="输出 JSON 路径(默认 out/batch4_aggregate.json)")
    ap.add_argument("--total", type=int, default=DEFAULT_TOTAL, help="输入总数(默认 500)")
    ap.add_argument("--no-write", action="store_true", help="只打印不落盘")
    args = ap.parse_args()

    agg = aggregate(args.total)
    _print_human(agg)

    if not args.no_write:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(agg, f, ensure_ascii=False, indent=2)
        print(f"\n已写出: {args.out}")


if __name__ == "__main__":
    main()
