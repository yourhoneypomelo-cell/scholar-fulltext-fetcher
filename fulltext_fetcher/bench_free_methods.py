"""免费全文候选发现方法的命中率评测台(离线可测)。

给定 (title, doi) 列表,逐一调用各免费「候选发现方法」,统计每方法:命中条目数/命中率、
候选 URL 总数、去重后唯一 URL 数、**唯一贡献**(仅该方法发现、其它方法都没有的 URL 数)、
出错条目数与耗时。用于「跑程序 + 读汇总」判断各免费路线的实际效果与边际价值。

方法约定:每个方法是 callable(title, doi) -> list[str](返回候选 URL,不下载)。
为兼容既有模块入参顺序差异(如 websearch 是 (title, doi)、oa_button 是 (doi, title)),
本评测台**按参数名绑定**调用(``fn(title=..., doi=...)``);仅当函数未用 title/doi 命名时,
才回退按约定位置序 ``fn(title, doi)``。因此各方法只要把参数命名为 title 与 doi(顺序不限)即可。

内置可插拔注册表(全部延迟导入,缺失/导入失败即跳过该法、不崩):
  - websearch    : sources.websearch.search_pdf_candidates
  - oa_button    : sources.oa_button.find_pdf_candidates
  - publisher_oa : sources.publisher_oa.build_pdf_candidates
  - wayback      : sources.wayback.find_archived_pdf

仅用标准库。benchmark() 返回结构化 dict,便于 --json 落盘或父程序接入。
"""
from __future__ import annotations

import inspect
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

Method = Callable[..., List[str]]
Pair = Tuple[Optional[str], Optional[str]]


# ── 默认方法注册表(延迟导入;返回 callable 或 None) ──────────────────────────
def _load_websearch() -> Optional[Method]:
    try:
        from .sources.websearch import search_pdf_candidates
        return search_pdf_candidates
    except Exception:  # noqa: BLE001 — 缺失/WIP 导入错都跳过,不崩
        return None


def _load_oa_button() -> Optional[Method]:
    try:
        from .sources.oa_button import find_pdf_candidates
        return find_pdf_candidates
    except Exception:  # noqa: BLE001
        return None


def _load_publisher_oa() -> Optional[Method]:
    try:
        from .sources.publisher_oa import build_pdf_candidates
        return build_pdf_candidates
    except Exception:  # noqa: BLE001
        return None


def _load_wayback() -> Optional[Method]:
    try:
        from .sources.wayback import find_archived_pdf
        return find_archived_pdf
    except Exception:  # noqa: BLE001
        return None


DEFAULT_METHOD_LOADERS: List[Tuple[str, Callable[[], Optional[Method]]]] = [
    ("websearch", _load_websearch),
    ("oa_button", _load_oa_button),
    ("publisher_oa", _load_publisher_oa),
    ("wayback", _load_wayback),
]


def _make_invoker(fn: Method) -> Callable[[Optional[str], Optional[str]], Any]:
    """把任意方法适配为 (title, doi) 调用:优先按参数名绑定(顺序无关),否则按约定位置序。"""
    try:
        params = inspect.signature(fn).parameters
        names = set(params)
        has_var_kw = any(p.kind == p.VAR_KEYWORD for p in params.values())
    except (TypeError, ValueError):
        names, has_var_kw = set(), False
    if {"title", "doi"} <= names or has_var_kw:
        return lambda title, doi: fn(title=title, doi=doi)
    return lambda title, doi: fn(title, doi)


def _norm_pair(p: Any) -> Pair:
    """把一条输入规整成 (title, doi)。支持 (title,doi) 序列、{title,doi} dict、或单串(自动判 DOI/标题)。"""
    if isinstance(p, dict):
        return (p.get("title"), p.get("doi"))
    if isinstance(p, (list, tuple)):
        title = p[0] if len(p) > 0 else None
        doi = p[1] if len(p) > 1 else None
        return (title, doi)
    s = ("" if p is None else str(p)).strip()
    if s.lower().startswith("10.") and "/" in s:
        return (None, s)
    return (s or None, None)


def _resolve_methods(methods: Any) -> "Dict[str, Method]":
    """methods=None → 默认注册表(缺失跳过);dict → 原样;(name,fn) 序列 → 转 dict。"""
    if methods is None:
        out: Dict[str, Method] = {}
        for name, loader in DEFAULT_METHOD_LOADERS:
            fn = loader()
            if fn is not None:
                out[name] = fn
        return out
    if isinstance(methods, dict):
        return dict(methods)
    return {name: fn for name, fn in methods}


def benchmark(pairs: Sequence[Any], methods: Any = None) -> Dict[str, Any]:
    """对每个方法在 pairs 上评测,返回结构化汇总 dict(见模块 docstring)。"""
    norm: List[Pair] = [_norm_pair(p) for p in (pairs or [])]
    resolved = _resolve_methods(methods)
    n = len(norm)

    per: Dict[str, Dict[str, Any]] = {}
    url_sets: Dict[str, set] = {}
    for name, fn in resolved.items():
        invoke = _make_invoker(fn)
        t0 = time.time()
        total = hits = errs = 0
        urls: set = set()
        for title, doi in norm:
            try:
                res = invoke(title, doi) or []
            except Exception:  # noqa: BLE001 — 单方法单条出错不得拖垮评测
                errs += 1
                res = []
            res = [u for u in res if isinstance(u, str) and u.strip()]
            if res:
                hits += 1
            total += len(res)
            urls.update(res)
        per[name] = {
            "candidates_total": total,
            "unique_urls": len(urls),
            "hit_inputs": hits,
            "hit_rate": round(hits / n, 4) if n else 0.0,
            "error_inputs": errs,
            "elapsed_sec": round(time.time() - t0, 4),
        }
        url_sets[name] = urls

    for name, urls in url_sets.items():
        others: set = set()
        for other, ourls in url_sets.items():
            if other != name:
                others |= ourls
        per[name]["unique_contribution"] = len(urls - others)

    union: set = set()
    for urls in url_sets.values():
        union |= urls
    return {
        "n_inputs": n,
        "method_names": list(resolved.keys()),
        "methods": per,
        "union_unique_urls": len(union),
    }


def format_summary(result: Dict[str, Any]) -> str:
    """把 benchmark() 结果格式化为对齐的文本汇总表。"""
    n = result.get("n_inputs", 0)
    lines = ["===== 免费方法命中率评测(共 %d 条输入)=====" % n,
             "%-14s %6s %8s %6s %6s %9s %5s %8s"
             % ("method", "hit%", "hit/N", "cand", "uniq", "soleUniq", "err", "sec")]
    for name in result.get("method_names", []):
        m = result["methods"][name]
        lines.append("%-14s %5.0f%% %4d/%-3d %6d %6d %9d %5d %8.2f" % (
            name, m["hit_rate"] * 100, m["hit_inputs"], n, m["candidates_total"],
            m["unique_urls"], m["unique_contribution"], m["error_inputs"], m["elapsed_sec"]))
    lines.append("合并唯一 URL 数:%d" % result.get("union_unique_urls", 0))
    return "\n".join(lines)


def _read_pairs(path: str) -> List[Pair]:
    """从文件读入评测输入:每行 'doi' 或 'title' 或 'title<TAB>doi';# 注释与空行跳过。"""
    out: List[Pair] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "\t" in line:
                a, b = line.split("\t", 1)
                out.append((a.strip() or None, b.strip() or None))
            else:
                out.append(_norm_pair(line.strip()))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="fulltext_fetcher.bench_free_methods",
        description="免费候选发现方法命中率评测台:逐法统计产候选率/唯一贡献(不下载)。",
    )
    ap.add_argument("-f", "--input-file", help="每行:DOI 或 标题,或 'title<TAB>doi'")
    ap.add_argument("--json", action="store_true", help="额外把结果以 JSON 打印到 stdout")
    ap.add_argument("--selftest", action="store_true", help="运行不联网自检")
    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.selftest or not args.input_file:
        return _selftest()

    result = benchmark(_read_pairs(args.input_file))
    print(format_summary(result))
    if args.json:
        import json
        print(json.dumps(result, ensure_ascii=False))
    return 0


def _selftest() -> int:
    """不联网自检:用假方法验证评测/汇总/唯一贡献/异常吞噬/按名绑定逻辑。"""
    def m_a(title, doi):          # 有 doi → 2 个候选(其一与 b 重叠)
        return ["https://a.org/%s.pdf" % doi.replace("/", "_"), "https://shared.org/x.pdf"] if doi else []

    def m_b(title, doi):          # 有 doi → 2 个候选(其一与 a 重叠);title-only 不产
        return ["https://b.org/%s.pdf" % doi.replace("/", "_"), "https://shared.org/x.pdf"] if doi else []

    pairs = [("T1", "10.1/a"), ("T2", "10.2/b"), ("Title only", None)]
    res = benchmark(pairs, methods={"a": m_a, "b": m_b})
    assert res["n_inputs"] == 3, res
    a, b = res["methods"]["a"], res["methods"]["b"]
    assert a["hit_inputs"] == 2 and b["hit_inputs"] == 2, res
    assert a["hit_rate"] == round(2 / 3, 4) == 0.6667, a
    assert a["candidates_total"] == 4 and b["candidates_total"] == 4, res
    assert a["unique_urls"] == 3 and b["unique_urls"] == 3, res
    assert a["unique_contribution"] == 2 and b["unique_contribution"] == 2, res  # 各去掉重叠的 shared
    assert res["union_unique_urls"] == 5, res                                    # a×2 + b×2 + shared×1
    assert a["error_inputs"] == 0, res

    # 按参数名绑定:oa_button 风格 (doi, title) 顺序也能被正确调用
    def m_swapped(doi, title):
        return ["https://sw.org/%s" % (doi or "none")]
    assert _make_invoker(m_swapped)("Ti", "10.9/z") == ["https://sw.org/10.9/z"]
    assert benchmark([("Ti", "10.9/z")], methods={"sw": m_swapped})["methods"]["sw"]["candidates_total"] == 1

    # 方法抛异常 → 被吞、计 error_inputs、不崩
    def m_boom(title, doi):
        raise RuntimeError("boom")
    rb = benchmark([("T", "10.1/x")], methods={"boom": m_boom})["methods"]["boom"]
    assert rb["error_inputs"] == 1 and rb["candidates_total"] == 0, rb

    # 空输入 / 单串输入规整
    assert benchmark([], methods={"a": m_a})["n_inputs"] == 0
    assert _norm_pair("10.1/x") == (None, "10.1/x") and _norm_pair("Some Title") == ("Some Title", None)

    # 默认注册表:延迟导入、缺失方法跳过、不崩(仅解析、不调用 → 不联网)
    resolved = _resolve_methods(None)
    assert isinstance(resolved, dict), resolved
    assert all(k in ("websearch", "oa_button", "publisher_oa", "wayback") for k in resolved), resolved

    print(format_summary(res))
    print("BENCH_OK")
    return 0


if __name__ == "__main__":
    import sys
    _args = sys.argv[1:]
    if not _args or "--selftest" in _args or "selftest" in _args:
        raise SystemExit(_selftest())
    raise SystemExit(main(_args))
