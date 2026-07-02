"""run_all —— 一键编排器:输入清单(标题/DOI 混合)→ 跨批去重/续跑 → 下载 → coverage/still_missing → 一页式总结。

直击北极星:『输入标题/DOI → 全程程序化 → 标准化文件名 → 一键批量出全文 + 覆盖报告』。
本文件是**包装器**:只 import 现有 `fulltext_fetcher.Pipeline` / `cli._read_input_file` 与
`tools/build_coverage.py`,**不改** pipeline.py / cli.py / build_coverage.py 任何逻辑。

流程:
  1) 读输入清单(.txt/.csv/.xlsx,复用 cli._read_input_file;标题与 DOI 可混排)。
  2) 输入内去重(按规范化 DOI;非 DOI 的标题按小写去重)。
  3) 跨批续跑(--resume,默认开):扫已有 out/(--coverage-root)的 coverage,
     把「已真实成功(有 pdf 落盘)的 DOI」从本次输入剔除,避免重复下载。
  4) 调 Pipeline 下载剩余输入到 RUNROOT/fetch/(独立子目录,自带 out_dir 写锁保护)。
  5) 末尾调 tools/build_coverage.py 对 RUNROOT 生成 RUNROOT/coverage.json + RUNROOT/still_missing.txt,
     **消费审计 QC 黑名单**(coverage-root/qc_merge_{highconf,union}_wrong.csv,来自 147 内容比对 +
     双门 verdict 合并):把 websearch「抓错论文」的假成功改判 miss,得**可信净成功率**(而非把
     每条 %PDF 在盘都算成功的虚高口径)。--no-qc 可退回盲口径(不建议;仅调试)。
  6) 打印一页式总结(输入总数 / 去重 / 跨批已covered跳过 / 本次成功·miss / 可信覆盖净成功 / still_missing / 按源),
     并落一份 RUNROOT/run_all_summary.json。

产物布局(RUNROOT 由 -o 指定,独立目录):
  RUNROOT/fetch/           pdfs/ + metadata.jsonl + summary.json + results.csv + report.html + run.log
  RUNROOT/coverage.json    去重 coverage 主库(build_coverage 口径:metadata.success 且 pdf 落盘)
  RUNROOT/still_missing.txt 仍缺 DOI 全集(可直接作下一轮 -f 输入)
  RUNROOT/run_all_summary.json 本次编排的机器可读总结

用法:
  python run_all.py -f inputs.txt --email you@uni.edu -o out/run_all
  python run_all.py "10.1371/journal.pone.0000217" "1706.03762" "Attention is all you need" -o out/run_demo
  python run_all.py -f inputs.txt --no-resume            # 不做跨批已covered剔除(强制全跑)
  python run_all.py -f inputs.txt --route-b cf-only      # 一键路径启用路线B(JA3型强CF站浏览器内抓字节;需 nodriver+有头)
  python run_all.py --selftest                            # 离线自检(不联网)→ RUN_ALL_OK

护栏:新文件、不改核心码;每次用独立 -o(pipeline 的 out_dir 写锁会阻止并发写同一目录)。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_build_coverage() -> Any:
    """按文件路径加载 tools/build_coverage.py(tools 非包,故用 importlib 直接载)。"""
    path = os.path.join(_HERE, "tools", "build_coverage.py")
    spec = importlib.util.spec_from_file_location("build_coverage", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _norm_key(line: str, bc: Any) -> str:
    """输入行的去重键:规范化 DOI(优先);非 DOI(标题/arXiv)回退小写裁剪串。"""
    k = bc.norm_doi({"raw_input": line})
    return k or (line or "").strip().lower()


def dedup_inputs(lines: List[str], bc: Any) -> Tuple[List[str], int]:
    """输入内去重(保序)。返回 (去重后列表, 去掉的重复数)。"""
    seen: Set[str] = set()
    out: List[str] = []
    for ln in lines:
        if not ln or not ln.strip():
            continue
        key = _norm_key(ln, bc)
        if key in seen:
            continue
        seen.add(key)
        out.append(ln.strip())
    return out, len(lines) - len(out)


def filter_already_covered(lines: List[str], success_dois: Set[str], bc: Any) -> Tuple[List[str], List[str]]:
    """跨批续跑:剔除「已真实成功」的 DOI 输入。返回 (待跑, 跳过)。标题类无法判定→保留待跑。"""
    todo: List[str] = []
    skipped: List[str] = []
    for ln in lines:
        key = _norm_key(ln, bc)
        if key in success_dois:
            skipped.append(ln)
        else:
            todo.append(ln)
    return todo, skipped


def run_coverage(bc: Any, out_root: str, *, use_qc: bool,
                 qc_hard_path: Optional[str] = None, qc_soft_path: Optional[str] = None,
                 write: bool, coverage_json: Optional[str] = None,
                 missing_txt: Optional[str] = None) -> Dict[str, Any]:
    """调 147 的权威一站式 build_coverage.run_coverage(全组唯一『黑名单感知』净口径);
    旧版无该入口时退回 read_qc_dois + build(qc)+write_outputs,行为等价、绝不另起分叉逻辑。"""
    fn = getattr(bc, "run_coverage", None)
    if fn is not None:
        return fn(out_root, use_qc=use_qc, qc_hard_path=qc_hard_path, qc_soft_path=qc_soft_path,
                  write=write, coverage_json=coverage_json, missing_txt=missing_txt)
    qc_hard: Set[str] = set()
    qc_soft: Set[str] = set()
    if use_qc:
        hp = qc_hard_path or os.path.join(out_root, "qc_merge_highconf_wrong.csv")
        sp = qc_soft_path or os.path.join(out_root, "qc_merge_union_wrong.csv")
        qc_hard, qc_soft = bc.read_qc_dois(hp), bc.read_qc_dois(sp)
    try:
        res = bc.build(out_root, qc_hard=qc_hard, qc_soft=qc_soft)
    except TypeError:  # 更旧版 build(out_root) 无 qc 形参
        res = bc.build(out_root)
    if write:
        cj = coverage_json or os.path.join(out_root, "coverage.json")
        mt = missing_txt or os.path.join(out_root, "still_missing.txt")
        bc.write_outputs(res, cj, mt)
        res["_written"] = {"coverage_json": cj, "missing_txt": mt}
    return res


def global_success_dois(cov: Dict[str, Any]) -> Set[str]:
    """从一次 coverage 结果里取「已真实成功(净·已剔 QC 抓错)」的规范化 DOI 集合(跨批续跑用)。

    被 QC 判「抓错论文」的假成功状态已是 miss → 不在此集合 → 下一轮仍会重取,不把错论文当已完成。"""
    return {r["doi"] for r in cov.get("records", []) if r.get("status") == "success"}


def _print_page(payload: Dict[str, Any]) -> None:
    p = payload
    line = "=" * 72
    print("\n" + line)
    print("run_all 一页式总结  (RUNROOT=%s, %s)" % (p["runroot"], p["ts"]))
    print("-" * 72)
    print("输入清单        : %d 条  →  去重后 %d 条(去重 -%d)" % (
        p["inputs_total"], p["after_dedup"], p["dup_removed"]))
    print("跨批续跑跳过    : %d 条(已在既有 out/ 真实成功)" % p["skipped_covered"])
    print("本次实际下载    : %d 条" % p["to_run"])
    print("-" * 72)
    print("本次结果        : 成功 %d / 处理 %d(miss %d),用时 %ss" % (
        p["run_success"], p["run_processed"], p["run_miss"], p["run_elapsed_sec"]))
    if p["run_by_source"]:
        print("本次命中源      : " + ", ".join("%s=%d" % (k, v) for k, v in p["run_by_source"].items()))
    print("-" * 72)
    cov = p["coverage"]
    qc = p.get("qc", {})
    if qc.get("enabled"):
        sb = qc.get("success_before_qc")
        rej = qc.get("rejected_total")
        qc_note = ""
        if sb is not None and rej is not None:
            qc_note = "  (QC 剔抓错论文: 原始成功 %d → 剔 %d → 净 %d)" % (sb, rej, qc.get("success_after_qc"))
        print("RUNROOT 覆盖(可信): 唯一 DOI %d | 净成功 %d | still_missing %d | 净成功率 %.1f%%%s" % (
            cov["total_unique_dois"], cov["success"], cov["miss"], cov["success_rate"] * 100, qc_note))
        print("QC 黑名单        : 硬黑 %s / 并集 %s DOI(消费审计 qc_merge_*_wrong.csv,已对齐双门 verdict)" % (
            qc.get("hard_list_dois"), qc.get("union_list_dois")))
    else:
        print("RUNROOT 覆盖(盲)  : 唯一 DOI %d | 成功 %d | still_missing %d | 成功率 %.1f%%  [未启用QC,可能虚高]" % (
            cov["total_unique_dois"], cov["success"], cov["miss"], cov["success_rate"] * 100))
    if cov.get("by_source"):
        print("覆盖命中源      : " + ", ".join("%s=%d" % (k, v) for k, v in list(cov["by_source"].items())[:6]))
    print("-" * 72)
    print("PDF 目录        : %s" % p["pdf_dir"])
    print("coverage.json   : %s" % p["coverage_json"])
    print("still_missing   : %s  (%d 条)" % (p["still_missing_txt"], cov["miss"]))
    print("run_all_summary : %s" % p["run_all_summary"])
    print(line + "\n")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="run_all",
        description="一键编排:输入清单→跨批去重/续跑→下载→coverage/still_missing→一页式总结(包装 Pipeline,不改核心码)。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("inputs", nargs="*", help="标题 / DOI / arXiv id(可多个;与 -f 合并)")
    ap.add_argument("-f", "--input-file", help="输入清单文件(.txt/.csv/.xlsx;复用 cli 解析)")
    ap.add_argument("-o", "--out", default="out/run_all", help="独立输出根目录 RUNROOT(默认 out/run_all)")
    ap.add_argument("--email", default=os.environ.get("FULLTEXT_EMAIL", ""), help="联系邮箱(Unpaywall 用)")
    ap.add_argument("-c", "--concurrency", type=int, default=3, help="并发(默认 3,礼貌真流量)")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--resume", dest="resume", action="store_true", default=True,
                    help="跨批续跑:剔除既有 out/ 已真实成功的 DOI(默认开)")
    ap.add_argument("--no-resume", dest="resume", action="store_false",
                    help="关闭跨批续跑(本次全跑,不剔除已 covered)")
    ap.add_argument("--coverage-root", default="out",
                    help="跨批续跑扫描根 + QC 黑名单所在根(默认 out)")
    ap.add_argument("--no-qc", action="store_true",
                    help="不消费审计 QC 黑名单(coverage 退回盲口径,可能把 websearch 抓错论文当成功→虚高)")
    ap.add_argument("--qc-hard", default=None,
                    help="QC 硬黑名单 CSV(默认 <coverage-root>/qc_merge_highconf_wrong.csv)")
    ap.add_argument("--qc-soft", default=None,
                    help="QC 并集黑名单 CSV(默认 <coverage-root>/qc_merge_union_wrong.csv)")
    ap.add_argument("--no-download", action="store_true", help="只定位不下载(快速验证源命中)")
    ap.add_argument("--sources", help="逗号分隔源及顺序(默认全部)")
    # ── 路线B 浏览器内直下 PDF(破 JA3 绑定型强 CF / Akamai;可选、默认 off)──
    # 补断点①:此前 run_all 一键路径不透传 route-b,JA3 型强 CF 站(RSC/ACS/Wiley/ScienceDirect/MDPI)
    # 在一键流下恒 miss。这里把核心 CLI 已有的三档开关透传到 Config.apply_route_b(),口径与
    # `python -m fulltext_fetcher --route-b ...` 完全一致(见 fulltext_fetcher/cli.py)。
    ap.add_argument("--route-b", choices=["off", "cf-only", "all"], default="off",
                    help="路线B 浏览器内直下 PDF:off(默认,全关)| cf-only(仅 RSC/ACS/Wiley/"
                         "ScienceDirect 等 JA3 绑定型强 CF 站,浏览器内抓字节)| all(再加有头浏览器过 "
                         "Akamai 下载,治 MDPI)。需装 nodriver + 有头显示环境;单头串行 + 落盘前强制内容 QC。")
    ap.add_argument("--browser-headless", action="store_true",
                    help="路线B 浏览器无头运行(默认有头:过 CF/Akamai 通过率更高;无头需 xvfb 等虚拟显示)")
    ap.add_argument("--browser-pdf-wait", type=float, default=13.0,
                    help="路线B 有头浏览器过验证/渲染的等待秒(默认 13;--route-b all 时生效)")
    ap.add_argument("--selftest", action="store_true", help="离线自检后退出")
    return ap


def run(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    bc = _load_build_coverage()
    if args.selftest:
        return _selftest(bc)

    # 延迟导入重依赖(selftest 不需要)
    from fulltext_fetcher.cli import _read_input_file
    from fulltext_fetcher.config import Config
    from fulltext_fetcher.pipeline import Pipeline

    raw_inputs: List[str] = list(args.inputs)
    if args.input_file:
        raw_inputs.extend(_read_input_file(args.input_file))
    if not raw_inputs:
        print("错误:未提供输入。示例:python run_all.py -f inputs.txt --email you@uni.edu -o out/run_all",
              file=sys.stderr)
        return 2

    runroot = args.out
    fetch_dir = os.path.join(runroot, "fetch")
    os.makedirs(runroot, exist_ok=True)

    # ⓪ QC 黑名单路径(可信口径关键:剔 websearch「抓错论文」假成功;文件在全局 coverage-root)
    use_qc = not args.no_qc
    qc_hp = args.qc_hard or os.path.join(args.coverage_root, "qc_merge_highconf_wrong.csv")
    qc_sp = args.qc_soft or os.path.join(args.coverage_root, "qc_merge_union_wrong.csv")
    if use_qc:
        print("run_all: QC 黑名单 %s%s + %s%s" % (
            qc_hp, "" if os.path.isfile(qc_hp) else " [缺失]",
            qc_sp, "" if os.path.isfile(qc_sp) else " [缺失]"))
    else:
        print("run_all: 已 --no-qc(coverage 为盲口径,可能含抓错论文假成功,数字仅供参考)")

    # ① 输入内去重
    deduped, dup_removed = dedup_inputs(raw_inputs, bc)
    # ② 跨批续跑:剔除已真实成功(经 147 权威 run_coverage 的净口径:抓错论文假成功不算 covered→会重取)
    skipped_covered: List[str] = []
    to_run = deduped
    if args.resume:
        gcov = run_coverage(bc, args.coverage_root, use_qc=use_qc,
                            qc_hard_path=qc_hp, qc_soft_path=qc_sp, write=False)
        to_run, skipped_covered = filter_already_covered(deduped, global_success_dois(gcov), bc)

    print("run_all: 输入 %d → 去重 %d → 跨批跳过 %d → 待跑 %d(RUNROOT=%s)" % (
        len(raw_inputs), len(deduped), len(skipped_covered), len(to_run), runroot))

    # ③ 调 Pipeline 下载到 RUNROOT/fetch
    cfg = Config(
        email=args.email or "anonymous@example.com",
        out_dir=fetch_dir,
        concurrency=args.concurrency,
        timeout=args.timeout,
        resume=args.resume,
        no_download=args.no_download,
        route_b=args.route_b,
        browser_pdf_headless=args.browser_headless,
        browser_pdf_wait=args.browser_pdf_wait,
    )
    cfg.apply_route_b()      # 据 --route-b 派生 browser_capture / browser_pdf_download(单一真源,同核心 CLI)
    if args.sources:
        cfg.sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if cfg.browser_capture or cfg.browser_pdf_download:
        print("run_all: 已启用路线B 浏览器内直下(--route-b=%s):需 nodriver + 有头显示环境,单头串行(全组共一机);"
              "缺依赖/无显示时优雅 no-op。仅对已合法获取、有权访问的 OA/订阅内容使用。" % args.route_b)

    run_summary: Dict[str, Any] = {
        "processed": 0, "success": 0, "miss": 0, "success_rate": 0.0,
        "by_source": {}, "elapsed_sec": 0.0,
    }
    if to_run:
        pipe = Pipeline(cfg)
        run_summary = pipe.run(to_run)
    else:
        print("run_all: 待跑为 0(全部已 covered 或去重后为空),跳过下载,仅重算 coverage。")
        os.makedirs(fetch_dir, exist_ok=True)

    # ④ 末尾调 147 权威 run_coverage 对 RUNROOT 生成**可信** coverage/still_missing(消费全局 QC 黑名单)
    coverage_json = os.path.join(runroot, "coverage.json")
    missing_txt = os.path.join(runroot, "still_missing.txt")
    cov = run_coverage(bc, runroot, use_qc=use_qc, qc_hard_path=qc_hp, qc_soft_path=qc_sp,
                       write=True, coverage_json=coverage_json, missing_txt=missing_txt)
    cov_s = cov["summary"]
    qc_block = cov_s.get("qc") or {}

    # ⑤ 一页式总结 + 机器可读落盘
    payload = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "runroot": runroot,
        "inputs_total": len(raw_inputs),
        "after_dedup": len(deduped),
        "dup_removed": dup_removed,
        "skipped_covered": len(skipped_covered),
        "to_run": len(to_run),
        "run_processed": run_summary.get("processed", 0),
        "run_success": run_summary.get("success", 0),
        "run_miss": run_summary.get("miss", 0),
        "run_elapsed_sec": run_summary.get("elapsed_sec", 0.0),
        "run_by_source": run_summary.get("by_source", {}),
        "coverage": {
            "total_unique_dois": cov_s["total_unique_dois"],
            "success": cov_s["success"],
            "miss": cov_s["miss"],
            "success_rate": cov_s["success_rate"],
            "by_source": cov_s.get("by_source", {}),
        },
        "qc": {
            "enabled": use_qc,
            "hard_list_dois": qc_block.get("hard_list_dois"),
            "union_list_dois": qc_block.get("union_list_dois"),
            "success_before_qc": qc_block.get("success_before_qc"),
            "success_after_qc": qc_block.get("success_after_qc", cov_s["success"]),
            "rejected_total": qc_block.get("rejected_total"),
            "qc_paths": cov.get("_qc_paths"),
        },
        "pdf_dir": os.path.join(fetch_dir, "pdfs"),
        "coverage_json": coverage_json,
        "still_missing_txt": missing_txt,
        "run_all_summary": os.path.join(runroot, "run_all_summary.json"),
        "skipped_covered_samples": skipped_covered[:10],
    }
    with open(payload["run_all_summary"], "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _print_page(payload)
    return 0


# ── 离线自检(不联网、不动磁盘:只验去重 + 跨批续跑过滤的纯逻辑)────────────────────
def _selftest(bc: Any) -> int:
    # ① 去重:DOI 前缀归一 + 大小写 + 标题去重;保序
    lines = [
        "10.1000/AAA",
        "https://doi.org/10.1000/aaa",     # 同一 DOI(前缀+大小写)→ 去重
        "Attention Is All You Need",
        "attention is all you need",        # 同标题(大小写)→ 去重
        "10.1000/bbb",
        "",                                  # 空行 → 丢
    ]
    deduped, removed = dedup_inputs(lines, bc)
    assert deduped == ["10.1000/AAA", "Attention Is All You Need", "10.1000/bbb"], deduped
    assert removed == 3, removed  # 1 空 + 1 DOI 重复 + 1 标题重复

    # ② 跨批续跑过滤:已成功 DOI 被剔除;标题类无法判定→保留;DOI 前缀不同也能匹配
    success = {"10.1000/aaa"}   # 规范化后的成功 DOI
    todo, skipped = filter_already_covered(deduped, success, bc)
    assert skipped == ["10.1000/AAA"], skipped
    assert todo == ["Attention Is All You Need", "10.1000/bbb"], todo

    # ③ _norm_key:DOI 归一、标题回退小写
    assert _norm_key("HTTP://doi.org/10.5/X", bc) == "10.5/x", _norm_key("HTTP://doi.org/10.5/X", bc)
    assert _norm_key("Some Title", bc) == "some title", _norm_key("Some Title", bc)

    # ④ 全空/无成功集稳健
    assert dedup_inputs([], bc) == ([], 0)
    t2, s2 = filter_already_covered(["10.9/z"], set(), bc)
    assert t2 == ["10.9/z"] and s2 == [], (t2, s2)

    # ⑤ 路线B 参数透传(补断点①):--route-b 三档 → Config.apply_route_b() 派生 browser_capture/
    #    browser_pdf_download,口径须与核心 CLI 完全一致;默认 off 时两者皆 False(零副作用)。
    from fulltext_fetcher.config import Config as _Cfg
    parser = build_parser()
    a_def = parser.parse_args(["10.1/x"])
    assert a_def.route_b == "off" and a_def.browser_headless is False and a_def.browser_pdf_wait == 13.0, vars(a_def)
    _off = _Cfg(route_b=a_def.route_b); _off.apply_route_b()
    assert _off.browser_capture is False and _off.browser_pdf_download is False, vars(_off)
    a_cf = parser.parse_args(["10.1/x", "--route-b", "cf-only"])
    _cf = _Cfg(route_b=a_cf.route_b); _cf.apply_route_b()
    assert _cf.browser_capture is True and _cf.browser_pdf_download is False, vars(_cf)
    a_all = parser.parse_args(["10.1/x", "--route-b", "all", "--browser-headless", "--browser-pdf-wait", "20"])
    assert a_all.browser_headless is True and a_all.browser_pdf_wait == 20.0, vars(a_all)
    _all = _Cfg(route_b=a_all.route_b, browser_pdf_headless=a_all.browser_headless,
                browser_pdf_wait=a_all.browser_pdf_wait); _all.apply_route_b()
    assert _all.browser_capture is True and _all.browser_pdf_download is True, vars(_all)
    assert _all.browser_pdf_headless is True and _all.browser_pdf_wait == 20.0, vars(_all)

    print("RUN_ALL_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
