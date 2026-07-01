"""回收跑前去重辅助:按最新 metadata 剔除清单里「已成功」的条目,避免 batch7 式重复下载。

问题背景(batch7 教训):
- pipeline 的断点续跑靠 out/metadata.jsonl 里的 raw_input 判重,但那只是「单个 out 目录内」的判重。
- 一份「待回收清单」往往是某个时点导出的失败集;若在其之后,别的 out 目录(或同目录后几轮)
  又自恢复了大量成功,这份清单就**过期**了——直接拿去跑,会把已成功的再抓一遍。
- batch7 就是如此:输入用的是 13:14 的 213 条失败,但 batch6 跑到 13:40 又自恢复很多,
  结果 batch7 里 106 条与 batch6 重复、净增仅 2。

本工具在「开跑之前」用**最新、可跨多个 out 目录**的成功集,把清单里已成功的条目去掉,
只留「真正还需回收」的,直接喂给下一轮回收跑(输出即 --input-file 可读的每行一条 txt)。

匹配口径(与 tools/aggregate_batch4.py、fulltext_fetcher/resolve.py 对齐):
- DOI:小写、去 https://doi.org/·dx.doi.org·doi: 等前缀、去尾部标点 .,;) 后,按裸 DOI 比较。
- 标题/其它:小写、非词字符折叠为单空格后比较(同 resolve._norm_title)。
- 一条 metadata 记录只要 success==true,就把它 doi / raw_input / title 三者的规范化键都计入
  「成功集」;清单条目命中其中任一键即视为已成功、予以剔除。这样即便清单给的是 DOI、而当初
  是以标题输入跑成功的(反之亦然),只要 DOI 对得上就能判重。
- 已知局限:纯离线不联网,无法把「清单里的标题」反查成 DOI;若某标题当初是以 DOI 输入成功、
  且解析出的标题与清单里的写法差异较大,可能漏判(对 DOI 清单无影响)。

安全:只读清单与各 metadata.jsonl;只写你用 -o / --stats-json 指定的输出文件(默认仅打印到屏幕)。

用法:
    # 用一个或多个 metadata.jsonl(或直接给 out 目录)去重,结果打印到屏幕
    python tools/dedup_recover_input.py batch7_failed_dois.txt --meta out/batch6 out/batch7

    # 递归扫描 out/ 下所有 metadata.jsonl 作为成功集,写出新清单
    python tools/dedup_recover_input.py recover.txt --scan out -o recover_next.txt

    # 顺带把统计写成 JSON(便于流水线记录/回报)
    python tools/dedup_recover_input.py recover.txt --scan out -o next.txt --stats-json next.stats.json

    # 离线自检(不联网、不读项目文件,跨多个临时 out 目录验证去重)
    python tools/dedup_recover_input.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

# 与 aggregate_batch4.py / resolve.py 保持一致的 DOI 前缀清单(小写比较)。
_DOI_PREFIXES = (
    "https://doi.org/", "http://doi.org/",
    "https://dx.doi.org/", "http://dx.doi.org/",
    "https://www.doi.org/", "http://www.doi.org/",
    "doi.org/", "doi:",
)
# 裸 DOI 形态判定(同 resolve._DOI_RE 的 10.<注册号>/<后缀>)。
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")

Key = Tuple[str, str]  # ("doi", 裸doi) 或 ("text", 归一标题)


def _strip_doi(s: Optional[str]) -> str:
    """小写 + 去 DOI URL/doi: 前缀 + 去尾部标点。对任意字符串安全(非 DOI 原样小写返回)。"""
    v = (s or "").strip().strip('"').strip("'").lower()
    changed = True
    while changed:  # 允许 https://doi.org/doi:10.x 之类叠套前缀
        changed = False
        for pre in _DOI_PREFIXES:
            if v.startswith(pre):
                v = v[len(pre):].strip()
                changed = True
    return v.rstrip(".,;)")


def _norm_title(s: Optional[str]) -> str:
    """标题归一:小写、非词字符折叠为单空格、收尾去空白(与 resolve._norm_title 一致)。"""
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


def canon_key(s: Optional[str]) -> Optional[Key]:
    """把一个原始字符串(DOI 或标题)规范化成可比较的键;空串返回 None。

    先按 DOI 归一,若归一后形如裸 DOI 则记 ("doi", 裸doi),否则记 ("text", 归一标题)。
    """
    if not s or not str(s).strip():
        return None
    d = _strip_doi(str(s))
    if _DOI_RE.match(d):
        return ("doi", d)
    t = _norm_title(str(s))
    return ("text", t) if t else None


def record_success_keys(rec: Dict[str, Any]) -> Set[Key]:
    """一条(成功的)metadata 记录贡献的全部规范化键:doi / raw_input / title 各取其一。"""
    keys: Set[Key] = set()
    for field in ("doi", "raw_input", "title"):
        k = canon_key(rec.get(field))
        if k:
            keys.add(k)
    return keys


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    """稳健读取 jsonl:跳过空行与半截行(文件仍被管线实时追加时,末行可能不完整)。"""
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


# ── 读取待回收清单(与 fulltext_fetcher/cli.py 的输入读取口径一致)──────────────
def _read_text_lines(path: str) -> List[str]:
    out: List[str] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


def _extract_from_rows(rows: List[List[str]]) -> List[str]:
    """从二维表里抽输入:有 doi/title 表头则优先 doi、回退 title;否则取每行首个非空非注释单元格。"""
    if not rows:
        return []
    header = [str(c or "").strip().lower() for c in rows[0]]
    doi_i = header.index("doi") if "doi" in header else -1
    title_i = header.index("title") if "title" in header else -1
    out: List[str] = []
    if doi_i >= 0 or title_i >= 0:
        for r in rows[1:]:
            val = ""
            if 0 <= doi_i < len(r) and str(r[doi_i]).strip():
                val = str(r[doi_i]).strip()
            elif 0 <= title_i < len(r) and str(r[title_i]).strip():
                val = str(r[title_i]).strip()
            if val:
                out.append(val)
    else:
        for r in rows:
            for c in r:
                cell = str(c or "").strip()
                if cell and not cell.startswith("#"):
                    out.append(cell)
                    break
    return out


def _read_csv(path: str) -> List[str]:
    import csv
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [[(c if c is not None else "") for c in row] for row in csv.reader(f)]
    return _extract_from_rows(rows)


def _read_xlsx(path: str) -> List[str]:
    try:
        import openpyxl  # 可选依赖
    except ImportError:
        raise SystemExit("读取 .xlsx 需要 openpyxl:pip install openpyxl(或先另存为 .csv/.txt)")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = [[("" if c.value is None else str(c.value)).strip() for c in row]
            for row in ws.iter_rows()]
    wb.close()
    return _extract_from_rows(rows)


def read_list_entries(path: str) -> List[str]:
    """按扩展名读取待回收清单:.csv/.xlsx 识别 doi/title 列,其它按每行一条(# 注释)。"""
    low = path.lower()
    if low.endswith(".csv"):
        return _read_csv(path)
    if low.endswith((".xlsx", ".xlsm")):
        return _read_xlsx(path)
    return _read_text_lines(path)


# ── 收集成功集(可跨多个 out 目录)─────────────────────────────────────────────
def resolve_meta_paths(meta_args: List[str], scan_dirs: List[str]) -> List[str]:
    """把 --meta(文件或目录)与 --scan(递归找 metadata.jsonl)展开成去重后的路径列表。"""
    paths: List[str] = []
    for m in meta_args or []:
        paths.append(os.path.join(m, "metadata.jsonl") if os.path.isdir(m) else m)
    for d in scan_dirs or []:
        for root, _dirs, files in os.walk(d):
            if "metadata.jsonl" in files:
                paths.append(os.path.join(root, "metadata.jsonl"))
    seen: Set[str] = set()
    uniq: List[str] = []
    for p in paths:
        ap = os.path.normcase(os.path.normpath(os.path.abspath(p)))
        if ap not in seen:
            seen.add(ap)
            uniq.append(p)
    return uniq


def collect_success_keys(meta_paths: List[str]) -> Tuple[Set[Key], List[Dict[str, Any]]]:
    """扫描各 metadata.jsonl,汇总所有 success==true 记录的规范化键;并返回每文件统计。"""
    keys: Set[Key] = set()
    per_file: List[Dict[str, Any]] = []
    for p in meta_paths:
        recs = read_jsonl(p)
        succ = 0
        for r in recs:
            if r.get("success"):
                ks = record_success_keys(r)
                if ks:
                    keys |= ks
                    succ += 1
        per_file.append({
            "path": p,
            "exists": os.path.exists(p),
            "records": len(recs),
            "success_records": succ,
        })
    return keys, per_file


def dedup_entries(entries: List[str], success_keys: Set[Key]) -> Tuple[List[str], List[str], Dict[str, Any]]:
    """按成功集剔除清单里已成功的条目,并对清单自身去重(保序、保留原始写法)。

    返回 (remaining, removed, stats):
      remaining = 真正还需回收(去重后、未成功)的原始字符串,保输入顺序;
      removed   = 因已成功而被剔除的原始字符串(首次出现者);
      stats     = 计数明细。
    """
    remaining: List[str] = []
    removed: List[str] = []
    seen: Set[Key] = set()
    dup_in_input = 0
    blank_or_bad = 0
    for e in entries:
        k = canon_key(e)
        if k is None:
            blank_or_bad += 1
            continue
        if k in seen:
            dup_in_input += 1
            continue
        seen.add(k)
        if k in success_keys:
            removed.append(e)
        else:
            remaining.append(e)
    stats = {
        "input_lines": len(entries),
        "input_unique": len(seen),
        "duplicates_in_input": dup_in_input,
        "blank_or_unparseable": blank_or_bad,
        "already_success_removed": len(removed),
        "remaining_to_recover": len(remaining),
        "success_keys_total": len(success_keys),
    }
    return remaining, removed, stats


def run(list_path: str, meta_args: List[str], scan_dirs: List[str]) -> Dict[str, Any]:
    """纯函数编排:读清单 → 收集成功集 → 去重,返回完整结果字典(供 CLI 与测试复用)。"""
    entries = read_list_entries(list_path)
    meta_paths = resolve_meta_paths(meta_args, scan_dirs)
    success_keys, per_file = collect_success_keys(meta_paths)
    remaining, removed, stats = dedup_entries(entries, success_keys)
    stats["meta_files"] = per_file
    return {"remaining": remaining, "removed": removed, "stats": stats}


def _print_stats(stats: Dict[str, Any]) -> None:
    print("=" * 64, file=sys.stderr)
    print("回收清单去重", file=sys.stderr)
    print("-" * 64, file=sys.stderr)
    for ps in stats.get("meta_files", []):
        flag = "" if ps["exists"] else "  (缺失!)"
        print(f"  meta: {ps['path']}{flag}  记录 {ps['records']}, 成功 {ps['success_records']}",
              file=sys.stderr)
    print("-" * 64, file=sys.stderr)
    print(f"  清单读入        : {stats['input_lines']} 行 "
          f"(去重后唯一 {stats['input_unique']}, 清单内重复 {stats['duplicates_in_input']}, "
          f"空/无法解析 {stats['blank_or_unparseable']})", file=sys.stderr)
    print(f"  成功集键数      : {stats['success_keys_total']}", file=sys.stderr)
    print(f"  已成功·剔除     : {stats['already_success_removed']}", file=sys.stderr)
    print(f"  ▶ 真正还需回收  : {stats['remaining_to_recover']}", file=sys.stderr)
    print("=" * 64, file=sys.stderr)


def _force_utf8_console() -> None:
    """Windows 控制台默认 GBK 会把中文统计打成乱码;尽力把 stdout/stderr 切到 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - 老解释器/被重定向时静默降级
            pass


def main(argv: Optional[List[str]] = None) -> int:
    _force_utf8_console()
    ap = argparse.ArgumentParser(
        description="回收跑前:按最新 metadata(可跨多个 out 目录)剔除清单里已成功的条目。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("list_path", nargs="?", help="待回收清单(.txt 每行一条 / .csv / .xlsx)")
    ap.add_argument("--meta", nargs="*", default=[], metavar="PATH",
                    help="一个或多个 metadata.jsonl,或 out 目录(自动取其 metadata.jsonl)")
    ap.add_argument("--scan", nargs="*", default=[], metavar="DIR",
                    help="递归扫描这些目录下所有 metadata.jsonl 作为成功集")
    ap.add_argument("-o", "--output", metavar="PATH",
                    help="输出「真正还需回收」清单(每行一条);缺省打印到 stdout")
    ap.add_argument("--stats-json", metavar="PATH", help="把统计明细写成 JSON")
    ap.add_argument("--selftest", action="store_true", help="运行离线自检后退出")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if not args.list_path:
        ap.error("需要提供待回收清单路径(或用 --selftest)")
    if not os.path.exists(args.list_path):
        ap.error(f"清单文件不存在: {args.list_path}")
    if not args.meta and not args.scan:
        print("warning: 未提供 --meta / --scan,成功集为空 → 仅对清单本身去重。", file=sys.stderr)

    result = run(args.list_path, args.meta, args.scan)
    _print_stats(result["stats"])

    body = "\n".join(result["remaining"])
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(body + ("\n" if body else ""))
        print(f"已写出 {result['stats']['remaining_to_recover']} 条 → {args.output}", file=sys.stderr)
    else:
        if body:
            print(body)

    if args.stats_json:
        os.makedirs(os.path.dirname(os.path.abspath(args.stats_json)) or ".", exist_ok=True)
        with open(args.stats_json, "w", encoding="utf-8") as f:
            json.dump(result["stats"], f, ensure_ascii=False, indent=2)
        print(f"已写出统计 → {args.stats_json}", file=sys.stderr)
    return 0


# ── 离线自检(不联网、不读项目文件;跨多个临时 out 目录验证去重)──────────────
def _selftest() -> int:
    import shutil
    import tempfile

    # ① 规范化键:大小写/前缀/尾标点归一,DOI 与标题分流
    assert canon_key("10.1016/j.jcou.2013.10.003") == ("doi", "10.1016/j.jcou.2013.10.003")
    assert canon_key("https://DOI.ORG/10.1016/J.X.1") == ("doi", "10.1016/j.x.1")
    assert canon_key("doi:10.1234/AbC.") == ("doi", "10.1234/abc")
    assert canon_key("  10.1234/xyz);  ") == ("doi", "10.1234/xyz")
    assert canon_key("Deep, Residual!  Learning") == ("text", "deep residual learning")
    assert canon_key("") is None and canon_key(None) is None and canon_key("   ") is None
    # 位数不足的 10.x/ 不视为 DOI(与 resolve._DOI_RE 的 \d{4,9} 对齐),按标题处理
    assert canon_key("10.1/x")[0] == "text"
    # DOI 与其 URL 形态归一到同一键(判重的关键)
    assert canon_key("10.1234/x") == canon_key("https://doi.org/10.1234/x")

    tmp = tempfile.mkdtemp(prefix="dedup_recover_selftest_")
    try:
        # 两个独立 out 目录,各自标记不同条目成功 → 验证「跨多个 out 目录」并集去重
        dir_a = os.path.join(tmp, "out", "batch6")
        dir_b = os.path.join(tmp, "out", "batch7")
        os.makedirs(dir_a)
        os.makedirs(dir_b)

        # A:d1 成功(多轮重复,含一条失败旧记录);d2 失败;一条标题输入成功(doi 为空)
        with open(os.path.join(dir_a, "metadata.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"raw_input": "10.1016/d1", "doi": "10.1016/d1",
                                "success": False, "error": "no-downloadable-pdf"}) + "\n")
            f.write(json.dumps({"raw_input": "10.1016/d1", "doi": "10.1016/d1",
                                "title": "Paper One", "success": True,
                                "source_used": "websearch"}) + "\n")
            f.write(json.dumps({"raw_input": "10.1016/d2", "doi": "10.1016/d2",
                                "success": False, "error": "no-candidates"}) + "\n")
            f.write(json.dumps({"raw_input": "A Great Title About CO2",
                                "doi": None, "title": "A Great Title About CO2",
                                "success": True, "source_used": "openalex"}) + "\n")
        # B:d3 成功(仅存在于第二个目录)
        with open(os.path.join(dir_b, "metadata.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"raw_input": "10.1021/d3", "doi": "10.1021/d3",
                                "success": True, "source_used": "unpaywall"}) + "\n")

        # 清单:d1(大写+URL 形态,测归一)、d2(失败→保留)、d3(仅 B 成功→剔除)、
        #       d4(从未出现→保留)、标题(A 里成功→剔除)、d1 重复(清单内去重)
        list_path = os.path.join(tmp, "recover.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            f.write("\n".join([
                "# 待回收清单(自检)",
                "https://doi.org/10.1016/D1",
                "10.1016/d2",
                "10.1021/d3",
                "10.1039/d4",
                "a great title about co2",
                "10.1016/d1",
                "",
            ]))

        # 用 --scan 递归两个目录
        res = run(list_path, meta_args=[], scan_dirs=[os.path.join(tmp, "out")])
        st = res["stats"]

        # 成功集应含 d1 / d3 / 标题(text)/ Paper One(title)/ d2? 否(d2 全失败不计)
        assert st["success_keys_total"] >= 4, st
        # 剔除:d1(A成功)+ d3(B成功)+ 标题(A成功) = 3
        assert st["already_success_removed"] == 3, st
        # 保留:d2(失败)+ d4(未见) = 2,且保序、保留清单原始写法
        assert res["remaining"] == ["10.1016/d2", "10.1039/d4"], res["remaining"]
        # 清单内 d1 重复被计一次
        assert st["duplicates_in_input"] == 1, st
        assert st["input_unique"] == 5, st  # D1,d2,d3,d4,title(d1 重复不算)
        assert st["blank_or_unparseable"] == 0, st

        # 扫到两个 metadata.jsonl,各 1 个/多个成功
        assert len([m for m in st["meta_files"] if m["exists"]]) == 2, st["meta_files"]

        # ② 单独用 --meta 指目录也应等价(跨目录并集)
        res2 = run(list_path, meta_args=[dir_a, dir_b], scan_dirs=[])
        assert res2["remaining"] == ["10.1016/d2", "10.1039/d4"], res2["remaining"]

        # ③ 只给 A(不含 d3)→ d3 应保留,证明「过期清单/缺目录」时不会误删未成功项
        res3 = run(list_path, meta_args=[dir_a], scan_dirs=[])
        assert "10.1021/d3" in res3["remaining"], res3["remaining"]
        assert res3["remaining"] == ["10.1016/d2", "10.1021/d3", "10.1039/d4"], res3["remaining"]

        print("DEDUP_RECOVER_OK")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
