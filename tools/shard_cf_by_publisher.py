"""把「CF 回收清单」按出版商 DOI 前缀预分片,为 Phase-2 只对能救的社扩量做就绪。

背景(与 145/156 对齐):
- 仓内 tools/flaresolverr_nodriver.py(免 Docker,nodriver)端到端可用;145 冒烟已证
  ACS 的 CF403 可真解为 PDF、RSC 仍 403。故 CF 扩量要**按出版商分桶**,只对能救的社跑。
- 本工具只做「跑前分片」:先按最新成功集去重(避免 batch7 式重复下载),再把剩余 DOI
  按注册前缀切成每社一份清单,直接可作 fulltext_fetcher / CF 回收跑的 -f 输入。

去重口径:直接复用 tools/dedup_recover_input.py(与回收跑、resolve.py 完全一致)——
  扫描 out/ 下**所有** metadata.jsonl 的 success==true 记录作为「最新成功集」,把清单里
  已成功的剔除;只保留「真正还需回收」的,再分片。

分片口径(注册前缀 10.XXXX):
    10.1021 → acs      → acs_10.1021.txt
    10.1039 → rsc      → rsc_10.1039.txt
    10.1002 → wiley    → wiley_10.1002.txt
    10.1016 → elsevier → elsevier_10.1016.txt
    其它/非 DOI        → other.txt

交叉校验:remaining 应为 still_missing.txt(success AND pdf 落盘 的更严口径)的子集;
  若出现 remaining 里有、still_missing 里没有的条目,说明成功集口径不一致,单独列出预警。

安全:只读输入清单与各 metadata.jsonl / still_missing.txt;只写 --out-dir(默认 out/cf_shards)
  下的新文件。不下载、不改核心码、不动他人 out 目录。

用法:
    # 默认:input=out/batch4_recovery_cf.txt,扫描 out/ 作成功集,写 out/cf_shards/
    python tools/shard_cf_by_publisher.py

    # 指定输入/输出/成功集扫描目录
    python tools/shard_cf_by_publisher.py --input out/batch4_recovery_cf.txt \
        --scan out --out-dir out/cf_shards --still-missing out/still_missing.txt

    # 离线自检(不联网、不读项目文件)
    python tools/shard_cf_by_publisher.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional, Set, Tuple

# 复用 dedup_recover_input 的 DOI 归一/去重/成功集收集逻辑(口径与回收跑一致)。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dedup_recover_input as dr  # noqa: E402  # type: ignore[import-not-found]

# 注册前缀 → (出版商标签, 输出文件名)。顺序即报告展示顺序。
SHARD_MAP: "Dict[str, Tuple[str, str]]" = {
    "10.1021": ("acs", "acs_10.1021.txt"),
    "10.1039": ("rsc", "rsc_10.1039.txt"),
    "10.1002": ("wiley", "wiley_10.1002.txt"),
    "10.1016": ("elsevier", "elsevier_10.1016.txt"),
}
OTHER_LABEL = "other"
OTHER_FILE = "other.txt"
# 输出文件固定顺序(5 个都会写,空的也写空文件,保证 Phase-2 路径可预期)。
ORDERED_FILES: List[Tuple[str, str]] = [
    ("acs", "acs_10.1021.txt"),
    ("rsc", "rsc_10.1039.txt"),
    ("wiley", "wiley_10.1002.txt"),
    ("elsevier", "elsevier_10.1016.txt"),
    (OTHER_LABEL, OTHER_FILE),
]


def prefix_of(entry: str) -> Optional[str]:
    """取 DOI 注册前缀 10.XXXX(经 canon_key 归一);非 DOI 返回 None。"""
    k = dr.canon_key(entry)
    if not k or k[0] != "doi":
        return None
    return k[1].split("/", 1)[0]


def classify(entry: str) -> Tuple[str, str]:
    """把一条清单项分到 (label, filename);未匹配前缀或非 DOI → other。"""
    p = prefix_of(entry)
    if p and p in SHARD_MAP:
        return SHARD_MAP[p]
    return (OTHER_LABEL, OTHER_FILE)


def shard(remaining: List[str]) -> "Dict[str, List[str]]":
    """按 filename 分桶(保序);始终含全部 5 个桶(可能为空)。"""
    buckets: Dict[str, List[str]] = {fname: [] for _lbl, fname in ORDERED_FILES}
    for e in remaining:
        _label, fname = classify(e)
        buckets[fname].append(e)
    return buckets


def _load_still_missing_keys(path: str) -> Optional[Set[dr.Key]]:
    """把 still_missing.txt 读成规范化键集合;文件不存在返回 None(跳过交叉校验)。"""
    if not path or not os.path.exists(path):
        return None
    keys: Set[dr.Key] = set()
    for e in dr.read_list_entries(path):
        k = dr.canon_key(e)
        if k:
            keys.add(k)
    return keys


def run(input_path: str, meta_args: List[str], scan_dirs: List[str],
        still_missing_path: Optional[str]) -> Dict[str, object]:
    """读清单 → 收集成功集去重 → 分片 → 交叉校验,返回完整结果字典(供 CLI/测试复用)。"""
    entries = dr.read_list_entries(input_path)
    meta_paths = dr.resolve_meta_paths(meta_args, scan_dirs)
    success_keys, per_file = dr.collect_success_keys(meta_paths)
    remaining, removed, stats = dr.dedup_entries(entries, success_keys)
    stats["meta_files"] = per_file

    buckets = shard(remaining)

    # 交叉校验:remaining 应 ⊆ still_missing(更严口径)。列出不在 still_missing 的条目。
    sm_keys = _load_still_missing_keys(still_missing_path) if still_missing_path else None
    not_in_still_missing: List[str] = []
    if sm_keys is not None:
        for e in remaining:
            k = dr.canon_key(e)
            if k and k not in sm_keys:
                not_in_still_missing.append(e)

    return {
        "remaining": remaining,
        "removed": removed,
        "buckets": buckets,
        "dedup_stats": stats,
        "still_missing_keys": (len(sm_keys) if sm_keys is not None else None),
        "not_in_still_missing": not_in_still_missing,
    }


def write_outputs(out_dir: str, buckets: "Dict[str, List[str]]", removed: List[str],
                  stats: Dict[str, object], extra: Dict[str, object]) -> None:
    """写 5 个分片文件 + 审计文件 _removed_already_success.txt + _shard_stats.json。"""
    os.makedirs(out_dir, exist_ok=True)
    for _label, fname in ORDERED_FILES:
        body = "\n".join(buckets.get(fname, []))
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
            f.write(body + ("\n" if body else ""))
    # 审计:被判「已成功」剔除的条目(呼应 batch7 教训,便于复核)。
    rem_body = "\n".join(removed)
    with open(os.path.join(out_dir, "_removed_already_success.txt"), "w", encoding="utf-8") as f:
        f.write(rem_body + ("\n" if rem_body else ""))
    # 统计 JSON(便于流水线记录/回报)。
    per_shard = {label: len(buckets.get(fname, [])) for label, fname in ORDERED_FILES}
    stats_out = {
        "input": extra.get("input"),
        "per_shard": per_shard,
        "remaining_total": stats.get("remaining_to_recover"),
        "already_success_removed": stats.get("already_success_removed"),
        "duplicates_in_input": stats.get("duplicates_in_input"),
        "input_lines": stats.get("input_lines"),
        "input_unique": stats.get("input_unique"),
        "success_keys_total": stats.get("success_keys_total"),
        "still_missing_keys": extra.get("still_missing_keys"),
        "not_in_still_missing": extra.get("not_in_still_missing"),
        "meta_files": stats.get("meta_files"),
        "files": {label: fname for label, fname in ORDERED_FILES},
    }
    with open(os.path.join(out_dir, "_shard_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats_out, f, ensure_ascii=False, indent=2)


def _print_report(out_dir: str, buckets: "Dict[str, List[str]]", stats: Dict[str, object],
                  extra: Dict[str, object]) -> None:
    print("=" * 64, file=sys.stderr)
    print("CF 回收清单按出版商预分片", file=sys.stderr)
    print("-" * 64, file=sys.stderr)
    print(f"  输入清单        : {extra.get('input')}", file=sys.stderr)
    print(f"  清单读入        : {stats.get('input_lines')} 行 "
          f"(唯一 {stats.get('input_unique')}, 清单内重复 {stats.get('duplicates_in_input')})",
          file=sys.stderr)
    print(f"  成功集键数      : {stats.get('success_keys_total')} "
          f"(扫描 {len(stats.get('meta_files', []))} 个 metadata.jsonl)", file=sys.stderr)
    print(f"  已成功·剔除     : {stats.get('already_success_removed')}", file=sys.stderr)
    print(f"  ▶ 还需回收合计  : {stats.get('remaining_to_recover')}", file=sys.stderr)
    print("-" * 64, file=sys.stderr)
    print("  分片(各社条数):", file=sys.stderr)
    for label, fname in ORDERED_FILES:
        n = len(buckets.get(fname, []))
        print(f"    {label:<9}{n:>4}  → {os.path.join(out_dir, fname)}", file=sys.stderr)
    nism = extra.get("not_in_still_missing") or []
    smk = extra.get("still_missing_keys")
    print("-" * 64, file=sys.stderr)
    if smk is None:
        print("  still_missing 交叉校验: 跳过(未找到 still_missing.txt)", file=sys.stderr)
    elif not nism:
        print(f"  still_missing 交叉校验: OK(remaining 全部 ⊆ still_missing,{smk} 键)",
              file=sys.stderr)
    else:
        print(f"  still_missing 交叉校验: 预警 {len(nism)} 条不在 still_missing:", file=sys.stderr)
        for e in nism:
            print(f"      ! {e}", file=sys.stderr)
    print("=" * 64, file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    dr._force_utf8_console()
    ap = argparse.ArgumentParser(
        description="把 CF 回收清单按出版商前缀预分片(跑前先按最新成功集去重)。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--input", default=os.path.join("out", "batch4_recovery_cf.txt"),
                    help="待分片的 CF 回收清单(默认 out/batch4_recovery_cf.txt)")
    ap.add_argument("--scan", nargs="*", default=["out"], metavar="DIR",
                    help="递归扫描这些目录下所有 metadata.jsonl 作成功集(默认 out)")
    ap.add_argument("--meta", nargs="*", default=[], metavar="PATH",
                    help="额外的 metadata.jsonl 或 out 目录(与 --scan 合并)")
    ap.add_argument("--out-dir", default=os.path.join("out", "cf_shards"),
                    help="分片输出目录(默认 out/cf_shards)")
    ap.add_argument("--still-missing", default=os.path.join("out", "still_missing.txt"),
                    help="用于交叉校验的 still_missing.txt(默认 out/still_missing.txt)")
    ap.add_argument("--selftest", action="store_true", help="运行离线自检后退出")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if not os.path.exists(args.input):
        ap.error(f"输入清单不存在: {args.input}")

    result = run(args.input, args.meta, args.scan, args.still_missing)
    extra = {
        "input": args.input,
        "still_missing_keys": result["still_missing_keys"],
        "not_in_still_missing": result["not_in_still_missing"],
    }
    write_outputs(args.out_dir, result["buckets"], result["removed"],
                  result["dedup_stats"], extra)
    _print_report(args.out_dir, result["buckets"], result["dedup_stats"], extra)
    print(f"已写出 5 个分片 + 审计/统计 → {args.out_dir}", file=sys.stderr)
    return 0


# ── 离线自检(不联网、不读项目文件)──────────────────────────────────────────
def _selftest() -> int:
    import shutil
    import tempfile

    # ① 前缀提取 & 分类
    assert prefix_of("10.1021/acs.iecr.9b01153") == "10.1021"
    assert prefix_of("https://doi.org/10.1039/C0GC00516A") == "10.1039"
    assert prefix_of("Some Plain Title") is None
    assert classify("10.1021/x")[1] == "acs_10.1021.txt"
    assert classify("10.1039/x")[1] == "rsc_10.1039.txt"
    assert classify("10.1002/x")[1] == "wiley_10.1002.txt"
    assert classify("10.1016/x")[1] == "elsevier_10.1016.txt"
    assert classify("10.3390/x")[1] == "other.txt"
    assert classify("just a title")[1] == "other.txt"

    tmp = tempfile.mkdtemp(prefix="shard_cf_selftest_")
    try:
        out = os.path.join(tmp, "out")
        d = os.path.join(out, "recover_b4_cf")
        os.makedirs(d)
        # 成功集:acs/x1 已成功(应从清单剔除);其它未成功
        with open(os.path.join(d, "metadata.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"raw_input": "10.1021/x1", "doi": "10.1021/x1",
                                "success": True, "source_used": "flaresolverr"}) + "\n")
            f.write(json.dumps({"raw_input": "10.1016/y1", "doi": "10.1016/y1",
                                "success": False, "error": "cf403"}) + "\n")
        # 清单:含各社 + 一条已成功(acs/x1)+ 清单内重复(elsevier/y1)+ 一条非 DOI
        list_path = os.path.join(tmp, "cf.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            f.write("\n".join([
                "# cf 回收(自检)",
                "10.1021/x1",          # 已成功 → 剔除
                "10.1021/x2",          # acs 保留
                "10.1039/z1",          # rsc 保留
                "10.1002/w1",          # wiley 保留
                "10.1016/y1",          # elsevier 保留
                "10.1016/y1",          # 清单内重复 → 计一次
                "10.3390/o1",          # other 保留
                "A Plain Title",       # other(非 DOI)保留
                "",
            ]))
        # still_missing:含除 acs/x1 外的全部(x1 已成功不在其中)
        sm = os.path.join(out, "still_missing.txt")
        with open(sm, "w", encoding="utf-8") as f:
            f.write("\n".join([
                "# still_missing (自检)",
                "10.1021/x2", "10.1039/z1", "10.1002/w1", "10.1016/y1",
                "10.3390/o1", "a plain title", "",
            ]))

        res = run(list_path, meta_args=[], scan_dirs=[out], still_missing_path=sm)
        st = res["dedup_stats"]
        assert st["already_success_removed"] == 1, st          # 只 acs/x1
        assert st["duplicates_in_input"] == 1, st              # elsevier/y1 重复
        assert st["remaining_to_recover"] == 6, st             # x2,z1,w1,y1,o1,title
        b = res["buckets"]
        assert b["acs_10.1021.txt"] == ["10.1021/x2"], b
        assert b["rsc_10.1039.txt"] == ["10.1039/z1"], b
        assert b["wiley_10.1002.txt"] == ["10.1002/w1"], b
        assert b["elsevier_10.1016.txt"] == ["10.1016/y1"], b
        assert b["other.txt"] == ["10.3390/o1", "A Plain Title"], b
        # 交叉校验:remaining 全在 still_missing → 无预警
        assert res["not_in_still_missing"] == [], res["not_in_still_missing"]

        # 写盘并复核 5 个文件都在、行数对
        out_dir = os.path.join(tmp, "shards")
        write_outputs(out_dir, b, res["removed"], st,
                      {"input": list_path, "still_missing_keys": res["still_missing_keys"],
                       "not_in_still_missing": res["not_in_still_missing"]})
        for _lbl, fname in ORDERED_FILES:
            assert os.path.exists(os.path.join(out_dir, fname)), fname
        assert os.path.exists(os.path.join(out_dir, "_removed_already_success.txt"))
        assert os.path.exists(os.path.join(out_dir, "_shard_stats.json"))
        with open(os.path.join(out_dir, "acs_10.1021.txt"), encoding="utf-8") as f:
            assert f.read().splitlines() == ["10.1021/x2"]

        print("SHARD_CF_OK")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
