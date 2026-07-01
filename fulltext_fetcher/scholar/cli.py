"""§3.11 命令行入口:``python -m fulltext_fetcher.scholar [输入...] [选项]``。

把输入(位置参数 或 ``-f`` 文件)与开关映射到 ``ScholarConfig``,交 ``ScholarPipeline`` 批量执行。
默认最安全:代理/打码/Sci-Hub 全关、串行强限速(见 config/fetcher 头部合规声明)。

- ``-f`` 文件读取直接**复用父包** ``fulltext_fetcher.cli._read_input_file``(.txt/.csv/.xlsx,自动识别
  doi/title 列),避免重造。
- ``--selftest`` 委托 ``selftest_e2e.run_offline_e2e``(P4 交付,**延迟导入**;未就绪则友好提示)。
- 无任何输入 → 打印用法并返回 2(不构造流水线、不触发重依赖)。
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .config import ScholarConfig


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fulltext_fetcher.scholar",
        description=("谷歌学术爬虫:输入 标题/DOI →(避免或自动过人机验证)抓元数据 + 下载 Scholar 可及 "
                     "PDF → 文件名标准化落盘。默认最安全:代理/打码/Sci-Hub 全关、串行强限速。"),
        epilog='示例: python -m fulltext_fetcher.scholar "Attention is all you need" --num 5',
    )
    p.add_argument("inputs", nargs="*", help="标题 / DOI / arXiv id(可多个)")
    p.add_argument("-f", "--input-file",
                   help="从文件读取输入:.txt 逐行(# 注释)/ .csv / .xlsx 自动识别 doi,title 列")
    p.add_argument("--mode", choices=["auto", "serpapi", "self"], default=None,
                   help="auto(有 SerpApi key 走商业合规,否则自建)| serpapi | self(默认 auto)")
    p.add_argument("--serpapi-key", default=None, help="SerpApi key(缺省回落环境变量 SERPAPI_KEY)")
    p.add_argument("--proxy", action="store_true",
                   help="启用住宅代理(翼A,默认关=直连);代理池经环境变量 SCHOLAR_PROXIES(逗号分隔)")
    p.add_argument("--captcha", action="store_true", help="启用打码(翼B,默认关;灰色+持续付费)")
    p.add_argument("--captcha-provider", choices=["2captcha", "capsolver"], default=None,
                   help="打码服务商(配合 --captcha / --captcha-key)")
    p.add_argument("--captcha-key", default=None, help="打码服务 key")
    p.add_argument("--engine-order", default=None,
                   help="自建引擎降级顺序(逗号分隔,如 curl_cffi,nodriver)")
    p.add_argument("--num", type=int, default=None, help="每条输入期望结果数(默认 10)")
    p.add_argument("--year-from", type=int, default=None, help="起始年 as_ylo")
    p.add_argument("--year-to", type=int, default=None, help="截止年 as_yhi")
    p.add_argument("-o", "--out", default=None, help="输出目录(默认 out_scholar)")
    p.add_argument("-c", "--concurrency", type=int, default=None, help="并发(默认 1,强合规串行)")
    p.add_argument("--oa-fallback", action="store_true",
                   help="启用 OA 兜底(默认关=纯 Scholar 优先;开启后结果无 PDF 时复用父包 OA 源兜底)")
    p.add_argument("--enable-scihub", action="store_true", help="启用 Sci-Hub 兜底(注意:合规风险,默认关)")
    p.add_argument("--email", default=None, help="联系邮箱(供 OA 兜底 Unpaywall;建议真实邮箱)")
    p.add_argument("--print-json", action="store_true", help="stdout 输出 JSON({summary,results})")
    p.add_argument("--log-level", default=None, choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    p.add_argument("--selftest", action="store_true", help="运行不联网端到端自检(委托 selftest_e2e)")
    return p


def config_from_args(args: argparse.Namespace) -> ScholarConfig:
    """把已解析的命令行参数映射为 ScholarConfig(仅覆盖用户显式给出的项,其余用默认)。"""
    kw: dict = {}
    if args.mode is not None:
        kw["mode"] = args.mode
    if args.serpapi_key is not None:
        kw["serpapi_key"] = args.serpapi_key
    if args.engine_order:
        kw["engine_order"] = [s.strip() for s in args.engine_order.split(",") if s.strip()]
    if args.num is not None:
        kw["num"] = args.num
    if args.year_from is not None:
        kw["year_low"] = args.year_from
    if args.year_to is not None:
        kw["year_high"] = args.year_to
    if args.out is not None:
        kw["out_dir"] = args.out
    if args.concurrency is not None:
        kw["concurrency"] = args.concurrency
    if args.oa_fallback:
        kw["oa_fallback"] = True
    if args.enable_scihub:
        kw["enable_scihub"] = True
    if args.email is not None:
        kw["email"] = args.email
    if args.log_level is not None:
        kw["log_level"] = args.log_level
    if args.proxy:
        kw["proxy_enabled"] = True
    if args.captcha:
        kw["captcha_enabled"] = True
    if args.captcha_provider is not None:
        kw["captcha_provider"] = args.captcha_provider
    if args.captcha_key is not None:
        kw["captcha_key"] = args.captcha_key
    return ScholarConfig(**kw)


def _no_input(parser: argparse.ArgumentParser) -> int:
    parser.print_help(sys.stderr)
    print('\n错误:未提供任何输入。示例:\n'
          '  python -m fulltext_fetcher.scholar "Attention is all you need"\n'
          '  python -m fulltext_fetcher.scholar -f titles.txt --num 5', file=sys.stderr)
    return 2


def _print_summary(summary: dict, out_dir: str) -> None:
    print("\n===== 谷歌学术爬虫 运行汇总 =====")
    print(f"模式 {summary.get('mode')} | 处理 {summary.get('processed')} 条,"
          f"成功 {summary.get('success')},失败 {summary.get('miss')},"
          f"成功率 {summary.get('success_rate', 0) * 100:.0f}%,用时 {summary.get('elapsed_sec')}s")
    if summary.get("by_source"):
        print("命中来源:", ", ".join(f"{k}={v}" for k, v in summary["by_source"].items()))
    if summary.get("by_engine"):
        print("取回引擎:", ", ".join(f"{k}={v}" for k, v in summary["by_engine"].items()))
    print(f"产物目录:{out_dir}/  (pdfs/ + metadata.jsonl + attempts.jsonl + serp.jsonl + "
          f"summary.json + results.csv + report.html + run.log)")


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.selftest:
        import importlib
        try:
            # 动态相对导入:selftest_e2e 由 P4 交付,此刻可能尚不存在(用字符串名避免静态误报)。
            _e2e = importlib.import_module(".selftest_e2e", __package__)
        except ImportError as e:
            print(f"selftest_e2e 尚未就绪(由 P4 交付): {e}", file=sys.stderr)
            return 2
        return int(_e2e.run_offline_e2e())

    inputs: List[str] = list(args.inputs)
    if args.input_file:
        from ..cli import _read_input_file             # 复用父包读取器(.txt/.csv/.xlsx)
        inputs.extend(_read_input_file(args.input_file))
    if not inputs:
        return _no_input(parser)

    cfg = config_from_args(args)

    from .pipeline import ScholarPipeline              # 延迟导入:仅有输入时才拉起重栈
    pipe = ScholarPipeline(cfg)
    summary = pipe.run(inputs)

    if args.print_json:
        import json
        payload = {
            "summary": summary,
            "results": [r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in pipe.results],
        }
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        except AttributeError:
            sys.stdout.write(data.decode("utf-8"))
    else:
        _print_summary(summary, getattr(cfg, "out_dir", None) or "out_scholar")

    return 0 if (summary.get("success", 0) > 0 or summary.get("processed", 0) == 0) else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(main(["--selftest"]))
    raise SystemExit(main())
