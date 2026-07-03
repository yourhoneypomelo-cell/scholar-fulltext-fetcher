#!/usr/bin/env python3
"""一键回归 runner:对 fulltext_fetcher 全包 compileall + 逐个跑各模块内置 selftest,汇总 PASS/FAIL/SKIP。

用法:
    python run_all_selftests.py

设计:
- 纯标准库;仅以「子进程」方式运行各模块的内置 selftest,绝不修改被测模块。
- 模块文件尚未创建(队友在写)→ 记 SKIP,不计为失败。
- 模块已存在但 selftest 未通过(子进程退出码≠0 或 stdout 缺少约定的 *_OK 标志)→ 记 FAIL。
- 总退出码:仅当「已存在模块」出现真实失败(含 compileall 失败)才为 1,否则 0(SKIP 不影响)。
- 结尾打印汇总表,并输出机器可读的 ALL_SELFTESTS_DONE。

注:各模块 selftest 约定为「不联网、打印一行 <MOD>_OK 表示通过」;cli 需 --selftest 触发。
状态标记(PASS/FAIL/SKIP)与关键 token 全用 ASCII,兼容任意终端编码。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

# 尽力把本脚本自身输出切到 UTF-8(失败也无妨:关键 token 均为 ASCII)。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

ROOT = os.path.dirname(os.path.abspath(__file__))
PKG = "fulltext_fetcher"
PER_CHECK_TIMEOUT = 180  # 单个 selftest 子进程超时(秒),防止误联网/死循环拖垮整体
ONLINE_TIMEOUT = 240     # 联网自检子进程超时(秒):浏览器启动 + 真解一次,需更大余量

# 联网自检开关:默认关(离线 CI 不受影响);置 RUN_ONLINE_SELFTESTS=1 才真跑,否则记 SKIP。
ONLINE_ENABLED = os.environ.get("RUN_ONLINE_SELFTESTS") == "1"

# 数据回归开关:默认关(依赖 out/ 审计产物与已隔离 PDF,非纯离线);置 RUN_DATA_REGRESS=1 才真跑。
DATA_REGRESS_ENABLED = os.environ.get("RUN_DATA_REGRESS") == "1"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

# (显示名, 候选模块[按序取首个存在者], 传给模块的参数, 期望的 OK 标志)
# 候选给多个位置,是为了容忍队友把新模块放到 顶层 或 sources/ 任一处。
CHECKS = [
    ("landing",            ["fulltext_fetcher.landing"],                                                 [],             "SELFTEST_OK"),
    ("cli",                ["fulltext_fetcher.cli"],                                                     ["--selftest"], "CLI_OK"),
    ("resolve",            ["fulltext_fetcher.resolve"],                                                 [],             "RESOLVE_OK"),
    ("http_client",        ["fulltext_fetcher.http_client"],                                             [],             "HTTP_CLIENT_OK"),
    ("aggregators",        ["fulltext_fetcher.sources.aggregators"],                                     [],             "AGGREGATORS_OK"),
    ("report",             ["fulltext_fetcher.report"],                                                  [],             "REPORT_OK"),
    ("download",           ["fulltext_fetcher.download"],                                                [],             "DOWNLOAD_OK"),
    ("pipeline",           ["fulltext_fetcher.pipeline"],                                                [],             "PIPELINE_OK"),
    ("publisher_adapter",  ["fulltext_fetcher.publisher_adapter"],                                       [],             "PUBLISHER_ADAPTER_OK"),
    ("green_oa",           ["fulltext_fetcher.sources.green_oa", "fulltext_fetcher.green_oa"],           [],             "GREEN_OA_OK"),
    ("zotero",             ["fulltext_fetcher.zotero", "fulltext_fetcher.sources.zotero"],               [],             "ZOTERO_OK"),
    ("snapshot_bootstrap", ["fulltext_fetcher.snapshot_bootstrap"],                                      [],             "SNAPSHOT_BOOTSTRAP_OK"),
    ("citations",          ["fulltext_fetcher.citations", "fulltext_fetcher.sources.citations"],         ["selftest"],   "CITATIONS_OK"),
    ("scholar_serpapi",    ["fulltext_fetcher.scholar_serpapi", "fulltext_fetcher.sources.scholar_serpapi"], [],         "SCHOLAR_SERPAPI_OK"),
    # 端到端 selftest(仅子进程运行,绝不编辑该文件)。纳入它以避免 CI 对 e2e 回归「假绿」。
    ("selftest_e2e",       ["fulltext_fetcher.selftest_e2e"],                                            [],             "E2E_OK"),

    # —— Scholar 爬虫子系统 fulltext_fetcher/scholar/(P0-P4 各模块内置 selftest,均不联网)——
    ("scholar.models",     ["fulltext_fetcher.scholar.models"],       [], "MODELS_OK"),
    ("scholar.config",     ["fulltext_fetcher.scholar.config"],       [], "CONFIG_OK"),
    ("scholar.logsetup",   ["fulltext_fetcher.scholar.logsetup"],     [], "LOGSETUP_OK"),
    ("scholar.query",      ["fulltext_fetcher.scholar.query"],        [], "QUERY_OK"),
    ("scholar.serp",       ["fulltext_fetcher.scholar.serp"],         [], "SERP_OK"),
    ("scholar.proxy",      ["fulltext_fetcher.scholar.proxy"],        [], "PROXY_OK"),
    ("scholar.captcha",    ["fulltext_fetcher.scholar.captcha"],      [], "CAPTCHA_OK"),
    ("scholar.fetcher",    ["fulltext_fetcher.scholar.fetcher"],      [], "FETCHER_OK"),
    ("scholar.download",   ["fulltext_fetcher.scholar.download"],     [], "SCH_DOWNLOAD_OK"),
    ("scholar.naming",     ["fulltext_fetcher.scholar.naming"],       [], "NAMING_OK"),
    ("scholar.pipeline",   ["fulltext_fetcher.scholar.pipeline"],     [], "SCHOLAR_PIPELINE_OK"),
    ("scholar.e2e",        ["fulltext_fetcher.scholar.selftest_e2e"], [], "SCHOLAR_E2E_OK"),

    # —— 其它增强模块 ——
    ("aio",                ["fulltext_fetcher.aio"],                  [], "AIO_OK"),
    ("render_fetch",       ["fulltext_fetcher.render_fetch"],         [], "RENDER_OK"),

    # —— 免费拿 PDF 方法(搜索引擎/无头浏览器/出版商直链/存档/Cloudflare;均离线 selftest)——
    ("free_adapters",      ["fulltext_fetcher.sources.free_adapters"],                                    [], "FREE_ADAPTERS_OK"),
    ("websearch",          ["fulltext_fetcher.sources.websearch", "fulltext_fetcher.websearch"],          [], "WEBSEARCH_OK"),
    ("oa_button",          ["fulltext_fetcher.sources.oa_button", "fulltext_fetcher.oa_button"],          [], "OA_BUTTON_OK"),
    ("publisher_oa",       ["fulltext_fetcher.sources.publisher_oa", "fulltext_fetcher.publisher_oa"],    [], "PUBLISHER_OA_OK"),
    ("publisher_direct",   ["fulltext_fetcher.sources.publisher_direct", "fulltext_fetcher.publisher_direct"], [], "PUBLISHER_DIRECT_OK"),
    ("institutional",      ["fulltext_fetcher.selftest_institutional"],                                   [], "INSTITUTIONAL_OK"),
    ("a5_framework",       ["fulltext_fetcher.institutional.selftest_a5_framework"],                      [], "A5_FRAMEWORK_OK"),
    ("assisted_auth",      ["fulltext_fetcher.institutional.assisted_auth"],                              [], "ASSISTED_AUTH_OK"),
    ("ezproxy",            ["fulltext_fetcher.ezproxy"],                                                  [], "EZPROXY_OK"),
    ("wayback",            ["fulltext_fetcher.sources.wayback", "fulltext_fetcher.wayback"],              [], "WAYBACK_OK"),
    ("preprints",          ["fulltext_fetcher.sources.preprints", "fulltext_fetcher.preprints"],          [], "PREPRINTS_OK"),
    ("browser_search",     ["fulltext_fetcher.browser_search"],                                           [], "BROWSER_SEARCH_OK"),
    ("flaresolverr",       ["fulltext_fetcher.flaresolverr"],                                             [], "FLARESOLVERR_OK"),
    ("bench_free_methods", ["fulltext_fetcher.bench_free_methods", "bench_free_methods"],                 [], "BENCH_OK"),

    # —— 北极星主流程 & 覆盖率构建(仓根/tools 脚本,非 fulltext_fetcher 包内;均离线 --selftest)——
    # 各带离线自检:run_all.py --selftest → RUN_ALL_OK;tools/build_coverage.py --selftest → COVERAGE_OK。
    # 以子进程 `python -m <mod>` 运行(与 ONLINE_CHECKS 里 tools.flaresolverr_nodriver 同款),绝不编辑被测脚本。
    ("run_all",            ["run_all"],                                                                   ["--selftest"], "RUN_ALL_OK"),
    ("build_coverage",     ["tools.build_coverage"],                                                      ["--selftest"], "COVERAGE_OK"),
    ("consolidate_delivery", ["tools.consolidate_delivery"],                                              ["--selftest"], "CONSOLIDATE_OK"),
]

# —— 可选「联网」自检(默认 SKIP;需真实浏览器 + 出网)——
# 与上面的离线 CHECKS 分开:仅当环境变量 RUN_ONLINE_SELFTESTS=1 时才真跑,否则一律记 SKIP,
# 绝不影响默认(离线)回归的 PASS/FAIL。用于验证「免 Docker FlareSolverr 变体」端到端可用。
# (显示名, 候选模块, 传参, 期望 OK 标志)
ONLINE_CHECKS = [
    ("flaresolverr_nodriver", ["tools.flaresolverr_nodriver"], ["--selftest"], "FLARESOLVERR_NODRIVER_OK"),
]

# —— 可选「数据」回归(默认 SKIP;需 out/ 审计产物在盘)——
# 防内容 QC 门从「并集(union)」退化回「交集」:重放审计 189 条同域错论文 + 34 条 title 假匹配。
# 依赖 out/qc_merge_union_wrong.csv、各批 metadata.jsonl 与已隔离 PDF,故不进默认离线回归;
# 置 RUN_DATA_REGRESS=1 才真跑(改 QC 门判定逻辑后务必跑一次)。
DATA_REGRESS_CHECKS = [
    ("regress_qc_union_189", ["tools.regress_qc_union_189"], [], "REGRESS_UNION_189_OK"),
]


def _module_file(dotted: str) -> str:
    """点分模块名 → 相对 ROOT 的 .py 文件路径。"""
    return os.path.join(ROOT, *dotted.split(".")) + ".py"


def _resolve_module(candidates):
    """返回首个「文件存在」的候选模块名;都不存在返回 None(→ SKIP)。"""
    for mod in candidates:
        if os.path.isfile(_module_file(mod)):
            return mod
    return None


def _child_env():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"  # 让子进程稳定以 UTF-8 输出,便于抓 *_OK 标志
    env["PYTHONUTF8"] = "1"
    return env


def _run(cmd, timeout=None):
    """跑子进程 → (rc, out, err);超时/异常也归一化为 (rc, out, err),绝不抛出。

    timeout 缺省用 PER_CHECK_TIMEOUT;联网自检等较慢项可传更大值(见 ONLINE_TIMEOUT)。
    """
    to = PER_CHECK_TIMEOUT if timeout is None else timeout
    try:
        proc = subprocess.run(
            cmd, cwd=ROOT, env=_child_env(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=to,
        )
        return (proc.returncode,
                proc.stdout.decode("utf-8", "replace"),
                proc.stderr.decode("utf-8", "replace"))
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout
        out = partial.decode("utf-8", "replace") if isinstance(partial, (bytes, bytearray)) else (partial or "")
        return 124, out, "TIMEOUT after %ss" % to
    except Exception as exc:  # noqa: BLE001 - runner 不得因单次执行异常中断整体
        return 125, "", "runner-exec-error: %r" % (exc,)


def _looks_like_bad_invocation(rc, text):
    """失败是否更像「调用方式不对」(argparse 用法错)而非真实 selftest 失败?

    用于决定是否值得改用其它触发方式重试:argparse 用法错通常 rc==2 且打印 usage;
    而真实断言失败/超时不应重试(重试只会重复失败、白白拖慢)。
    """
    if rc == 2:  # argparse 惯用的「用法错误」退出码
        return True
    low = (text or "").lower()
    return any(k in low for k in (
        "usage:", "unrecognized arguments", "invalid choice",
        "the following arguments are required",
    ))


def _run_selftest(mod, primary_args, flag, timeout=None):
    """跑模块 selftest → (rc, out, err, used_args, ok)。

    各模块 selftest 触发约定并不统一(裸调用 / `--selftest` / `selftest` 位置参数)。
    先用声明的 primary_args;仅当首次失败「看起来是调用方式不对」(argparse 用法错)时,
    才回退尝试其它常见触发方式(selftest / --selftest / 裸调用,去重)。真实断言失败/超时
    不重试,避免拖慢。任一次 rc==0 且含 *_OK 即判通过。timeout 透传给 _run(联网项用更大值)。
    """
    used = list(primary_args)
    rc, out, err = _run([sys.executable, "-m", mod] + used, timeout=timeout)
    if rc == 0 and flag in (out + "\n" + err):
        return rc, out, err, used, True
    if _looks_like_bad_invocation(rc, err) or _looks_like_bad_invocation(rc, out):
        seen = [used]
        for cand in (["selftest"], ["--selftest"], []):
            if cand in seen:
                continue
            seen.append(cand)
            rc2, out2, err2 = _run([sys.executable, "-m", mod] + cand, timeout=timeout)
            if rc2 == 0 and flag in (out2 + "\n" + err2):
                return rc2, out2, err2, cand, True
    return rc, out, err, used, False


def _tail(text, limit=240):
    """把多行输出压成单行短尾,便于并排显示。"""
    text = (text or "").replace("\r", "").strip()
    if not text:
        return ""
    text = " | ".join(ln for ln in text.splitlines() if ln.strip())
    return text[-limit:]


def _emit(name, status, detail):
    print("[%-4s] %-20s %s" % (status, name, detail))


def main() -> int:
    print("=" * 64)
    print("run_all_selftests :: package=%s" % PKG)
    print("python : %s" % sys.version.split()[0])
    print("root   : %s" % ROOT)
    print("=" * 64)

    results = []  # list[(name, status, detail)]

    # 0) 全包字节码编译(语法级健康检查;失败视为真实失败)
    t0 = time.time()
    rc, out, err = _run([sys.executable, "-m", "compileall", "-q", PKG])
    dt = time.time() - t0
    if rc == 0:
        results.append(("compileall", PASS, "exit=0 (%.1fs)" % dt))
    else:
        results.append(("compileall", FAIL, "exit=%d :: %s" % (rc, _tail(err or out))))
    _emit(*results[-1])

    # 1) 逐模块 selftest
    for name, candidates, args, flag in CHECKS:
        mod = _resolve_module(candidates)
        if mod is None:
            results.append((name, SKIP, "module not created yet (WIP): %s" % "|".join(candidates)))
            _emit(*results[-1])
            continue
        t0 = time.time()
        rc, out, err, used, ok = _run_selftest(mod, args, flag)
        dt = time.time() - t0
        shown = mod + ((" " + " ".join(used)) if used else "")
        if ok:
            results.append((name, PASS, "%s via `%s` (%.1fs)" % (flag, shown, dt)))
        else:
            why = []
            if rc != 0:
                why.append("exit=%d" % rc)
            if flag not in (out + "\n" + err):
                why.append("missing %s" % flag)
            results.append((name, FAIL, "%s :: %s" % ("; ".join(why) or "unknown", _tail(err or out))))
        _emit(*results[-1])

    # 1b) 可选联网自检(默认 SKIP;RUN_ONLINE_SELFTESTS=1 才真跑)与
    #     可选数据回归(默认 SKIP;RUN_DATA_REGRESS=1 才真跑,需 out/ 审计产物)
    optional_checks = (
        [(n, c, a, f, ONLINE_ENABLED, "online (set RUN_ONLINE_SELFTESTS=1 to run)", ONLINE_TIMEOUT)
         for n, c, a, f in ONLINE_CHECKS]
        + [(n, c, a, f, DATA_REGRESS_ENABLED, "data-regress (set RUN_DATA_REGRESS=1 to run)", PER_CHECK_TIMEOUT)
           for n, c, a, f in DATA_REGRESS_CHECKS]
    )
    for name, candidates, args, flag, enabled, skip_note, timeout in optional_checks:
        mod = _resolve_module(candidates)
        if mod is None:
            results.append((name, SKIP, "module not found: %s" % "|".join(candidates)))
            _emit(*results[-1])
            continue
        if not enabled:
            results.append((name, SKIP, "%s: %s %s" % (skip_note, mod, " ".join(args))))
            _emit(*results[-1])
            continue
        t0 = time.time()
        rc, out, err, used, ok = _run_selftest(mod, args, flag, timeout=timeout)
        dt = time.time() - t0
        shown = mod + ((" " + " ".join(used)) if used else "")
        if ok:
            results.append((name, PASS, "%s via `%s` (%.1fs)" % (flag, shown, dt)))
        else:
            why = []
            if rc != 0:
                why.append("exit=%d" % rc)
            if flag not in (out + "\n" + err):
                why.append("missing %s" % flag)
            results.append((name, FAIL, "%s :: %s" % ("; ".join(why) or "unknown", _tail(err or out))))
        _emit(*results[-1])

    # 2) 汇总
    n_pass = sum(1 for _, s, _ in results if s == PASS)
    n_fail = sum(1 for _, s, _ in results if s == FAIL)
    n_skip = sum(1 for _, s, _ in results if s == SKIP)
    print("=" * 64)
    print("SUMMARY: PASS=%d  FAIL=%d  SKIP=%d  (total=%d)" % (n_pass, n_fail, n_skip, len(results)))
    if n_fail:
        print("FAILED       : %s" % ", ".join(n for n, s, _ in results if s == FAIL))
    if n_skip:
        print("SKIPPED (WIP): %s" % ", ".join(n for n, s, _ in results if s == SKIP))
    print("=" * 64)
    print("ALL_SELFTESTS_DONE")
    # 仅「已存在模块的真实失败(含 compileall)」→ 非 0;SKIP 不影响。
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
