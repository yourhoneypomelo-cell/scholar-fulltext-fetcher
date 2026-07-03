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

文件命名(一键正门默认统一):PDF **默认**以 {year}_{author}_{title}_{doi} 统一模板命名(人类可读 + 可
  溯源),元数据缺失优雅降级、全缺以 {doi} 兜底(等价旧 DOI 净化名,零回归);全部落到 RUNROOT/fetch/pdfs/
  单一文件夹。想退回纯 DOI 名:--naming-template "{doi}"。核心库 Config 仍默认 None(向后兼容),仅 run_all 这层默认统一。

用法:
  python run_all.py -f inputs.txt --email you@uni.edu -o out/run_all
  python run_all.py "10.1371/journal.pone.0000217" "1706.03762" "Attention is all you need" -o out/run_demo
  python run_all.py -f inputs.txt --no-resume            # 不做跨批已covered剔除(强制全跑)
  python run_all.py -f inputs.txt --naming-template "{doi}"  # 退回旧版纯 DOI 净化名
  python run_all.py -f inputs.txt --route-b cf-only      # 一键路径启用路线B(JA3型强CF站浏览器内抓字节;需 nodriver+有头)
  python run_all.py -f inputs.txt --institutional        # 一键接入机构订阅直链源 publisher_direct(路线A;仅合法机构授权者)
  python run_all.py "10.1371/journal.pone.0000217" --explain 10.1371/journal.pone.0000217  # 读日志渲染该条逐源尝试链
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
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))

# ── 一键正门默认统一命名(与 -156 契约对齐;任务[全自动 E2E]:PDF 默认即人类可读、可溯源)──────
# run_all 是「一键正门」,面向"输入 DOI/标题 → 出标准化命名的系列全文"的北极星目标,因此**默认就开
# 统一命名**:{year}_{author}_{title}_{doi}。元数据(年/首作者姓/标题)缺失时 build_filename 优雅降级、
# 全缺则以 {doi} 兜底(等价旧 DOI 净化名),故对"只有 DOI 可解析"的条目落盘名与旧行为一致、零回归。
# 注:**核心库 Config.naming_template 仍默认 None(逐字节向后兼容,零副作用)**;只有 run_all 这一层
# 把默认切成统一模板——单条 `python -m fulltext_fetcher` 不受影响。想退回纯 DOI 名:--naming-template "{doi}"。
# coverage/续跑对文件名不敏感(build_coverage 只按 metadata 的 pdf_path basename 对盘,非按 DOI 形状),
# 故切换命名模板不影响任何 coverage / KPI / 续跑口径(已核 tools/build_coverage.py:real=claimed and bn in pdfs)。
DEFAULT_NAMING_TEMPLATE = "{year}_{author}_{title}_{doi}"


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


# ── 逐条明细(输出层增强·任务[可用性]):把权威 coverage 的去重记录整理成「每条 DOI 一行」的 ──
# 可读 + 可 grep 明细,让用户**不进代码、只读一页式总结 + run_all_detail.tsv** 就能判断每条 DOI 的
# 成败 / 命中源 / 失败原因 / 最终 PDF 路径 + 标准文件名,并可 grep/awk 统计。
# 数据源:run_coverage 返回的 records(净口径:已剔 QC 抓错、跨批并集去重),**只读不改口径**。
_DETAIL_COLUMNS = ["status", "doi", "source", "reason", "pdf_filename", "error", "qc", "title", "pdf_path"]
_MAX_DETAIL_PRINT = 50   # 一页式总结里逐条样例的打印上限(超出提示看 tsv);完整每条恒在 run_all_detail.tsv


def _pdf_basename(pdf_path: Optional[str]) -> str:
    """取 PDF 标准文件名(兼容 out/x\\pdfs\\y.pdf 混合分隔符);无则空串。"""
    if not pdf_path:
        return ""
    return pdf_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def reason_bucket(error: Optional[str]) -> str:
    """把细节各异的失败 error 归并成简短稳定的 bucket(便于按原因 grep/统计);成功项不调用。

    仅服务展示/统计层,**绝不改变 coverage 口径或 error 原文**(原文仍全量落 tsv 的 error 列)。"""
    e = (error or "").lower()
    if not e:
        return "unknown"
    if "qc_" in e or "allow_revoked" in e or "wrong-paper" in e:
        return "qc-reject"
    if "success-metadata-but-pdf" in e or "pdf-missing" in e or "pdf missing" in e:
        return "pdf-missing"
    if "timeout" in e or "timed out" in e or "straggler" in e:
        return "timeout"
    if "cloudflare" in e or "challenge" in e:
        return "cf-403"
    if "404" in e:
        return "http-404"
    if "paywall" in e or "forbidden" in e or "subscription" in e or "403" in e or "401" in e or "402" in e:
        return "paywall"
    if "http-5" in e or "500" in e or "502" in e or "503" in e or "504" in e:
        return "http-5xx"
    if "429" in e or "rate-limit" in e or "too many requests" in e:
        return "rate-limit"
    if "no-response" in e or "connection" in e or "connect" in e or "ssl" in e or "dns" in e:
        return "network"
    if "resolve" in e or "unresolvable" in e:
        return "resolve-fail"
    if "no-candidates" in e or "no-downloadable" in e or "no-source" in e:
        return "no-source"
    if "download-failed" in e:
        return "download-fail"
    if "exception" in e:
        return "exception"
    return "other"


def build_detail_rows(records: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """把 coverage 去重记录(records)整理为逐条明细行:每条 DOI 一行,含
    status/doi/source/reason/pdf_filename/error/qc/title/pdf_path。
    排序:MISS 在前(用户最关心失败)、OK 在后,组内按 doi 升序(稳定、便于 diff)。"""
    rows: List[Dict[str, str]] = []
    for r in records:
        ok = (r.get("status") == "success")
        rows.append({
            "status": "OK" if ok else "MISS",
            "doi": r.get("doi") or "",
            "source": (r.get("source") or "") if ok else "",
            "reason": "" if ok else reason_bucket(r.get("error")),
            "pdf_filename": _pdf_basename(r.get("pdf_path")) if ok else "",
            "error": "" if ok else (r.get("error") or ""),
            "qc": r.get("qc") or "",
            "title": (r.get("title") or "").strip(),
            "pdf_path": (r.get("pdf_path") or "") if ok else "",
        })
    rows.sort(key=lambda d: (d["status"] != "MISS", d["doi"]))
    return rows


def _tsv_cell(value: Any) -> str:
    """TSV 单元格清洗:制表/回车/换行→空格,保证一条 DOI 恒为一行、列不错位(grep/awk 稳)。"""
    return str("" if value is None else value).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def write_detail_tsv(path: str, rows: List[Dict[str, str]]) -> None:
    """落一份可 grep/统计的逐条明细 TSV(表头 + 每条 DOI 一行,UTF-8)。

    status 恒在首列 → `grep '^MISS' run_all_detail.tsv` 看全部失败;`grep -P '\\twebsearch\\t'`
    看某源命中;`awk -F'\\t' 'NR>1{c[$1]++}END{for(k in c)print k,c[k]}'` 统计成败分布。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(_DETAIL_COLUMNS) + "\n")
        for row in rows:
            f.write("\t".join(_tsv_cell(row.get(c)) for c in _DETAIL_COLUMNS) + "\n")


# ── 可复现覆盖口径(总指挥176 补充要求;与 144 对齐)────────────────────────────────────
# 背景(审计145):头条 326 是人工 extra-dirs 口径、一键 run_all 默认 flat 出 312 且不写全局盘 →
# "交付报告的数复现不出 + 漂移"。本组把**一键 run 报告的净覆盖数**做成【从隔离 RUNROOT 独立、
# 确定性复现】:
#   ① 固定 caliber:隔离 -o + flat-only 扫描 + QC(highconf∪union)+ verify_allow=on,显式落进 summary;
#   ② QC 快照:把本次实际消费的 QC 黑名单 CSV 复制进 RUNROOT/qc_snapshot/ 并记 sha256+行数
#      —— 否则全局 out/qc_*.csv 日后变动会让【同一 RUNROOT】重算出不同净数(漂移根因);
#   ③ 自证复现:python run_all.py --verify -o RUNROOT 用快照就地重算,断言 == 原报数,退 0/1。
# 注:caliber 细节(是否并入 manifest/uncertain、flat vs extra-dirs)以 144 牵头定稿为准;本实现把
# "锁定并可复现"的机制做实,caliber 常量集中在 _REPRO_CALIBER,便于按 144 结论一处切换、不改主流程。
_REPRO_CALIBER = {
    "scope": "isolated-runroot",       # 隔离 -o:只对本 RUNROOT 负责,绝不触全局权威盘(红线)
    "scan": "flat-only",               # 只扫一级(RUNROOT/fetch),与 build_coverage 默认权威口径一致
    "qc": "highconf-union",            # 消费 <coverage-root>/qc_merge_{highconf,union}_wrong.csv
    "verify_allow_openbook": True,     # 回写开卷门(no-false-kill)
}
_QC_SNAPSHOT_DIRNAME = "qc_snapshot"


def _sha256_file(path: str) -> Optional[str]:
    """文件 sha256(十六进制);不存在/读失败 → None。用于 QC 黑名单快照的内容指纹(防漂移佐证)。"""
    import hashlib
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _count_lines(path: str) -> Optional[int]:
    """文件非空行数(粗略佐证快照规模);读失败 → None。"""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            return sum(1 for ln in f if ln.strip())
    except OSError:
        return None


def snapshot_qc_files(runroot: str, qc_files: List[Tuple[str, str]]) -> Dict[str, Any]:
    """把本次消费的 QC 黑名单 CSV 复制进 RUNROOT/qc_snapshot/,记录 {role,src,exists,snapshot,sha256,lines}。

    qc_files: [(role, abs_path)];仅复制真实存在者(缺失记 exists=False)。返回可 JSON 序列化的快照
    清单(供 --verify 就地复现 + 审计佐证)。复制/读失败优雅降级(退回对源文件取指纹),绝不阻断主流程。"""
    import shutil
    snap_dir = os.path.join(runroot, _QC_SNAPSHOT_DIRNAME)
    entries: List[Dict[str, Any]] = []
    made = False
    for role, src in qc_files:
        if not src or not os.path.isfile(src):
            entries.append({"role": role, "src": (src or "").replace("\\", "/"),
                            "exists": False, "snapshot": None, "sha256": None, "lines": None})
            continue
        if not made:
            os.makedirs(snap_dir, exist_ok=True)
            made = True
        dst_name = "%s__%s" % (role, os.path.basename(src))
        dst = os.path.join(snap_dir, dst_name)
        try:
            shutil.copyfile(src, dst)
        except OSError:
            dst = None
        entries.append({
            "role": role, "src": src.replace("\\", "/"), "exists": True,
            "snapshot": (os.path.join(_QC_SNAPSHOT_DIRNAME, dst_name).replace("\\", "/")) if dst else None,
            "sha256": _sha256_file(dst or src),
            "lines": _count_lines(dst or src),
        })
    return {"dir": _QC_SNAPSHOT_DIRNAME, "files": entries}


def _snapshot_role_path(runroot: str, repro: Dict[str, Any], role: str) -> Optional[str]:
    """从 summary.reproducibility.qc_snapshot 取某 role 的快照文件绝对路径(供 --verify 复算用);无则 None。"""
    for ent in ((repro.get("qc_snapshot") or {}).get("files") or []):
        if ent.get("role") == role and ent.get("snapshot"):
            return os.path.join(runroot, ent["snapshot"].replace("/", os.sep))
    return None


def _force_utf8_console() -> None:
    """Windows 控制台默认 GBK 会把中文一页式总结/逐条明细打成乱码,伤"只读日志即可判断"。
    尽力把 stdout/stderr 切到 UTF-8(与 tools/build_coverage._force_utf8_console 同款);
    reconfigure 不可用(老解释器/被重定向)时静默降级,绝不因此阻断主流程。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


def _render_page_lines(p: Dict[str, Any]) -> List[str]:
    """把一页式总结渲染成**文本行列表**(单一真源:stdout 打印 + 落 RUNROOT/run_all.log 双写共用)。

    拆出此函数是为了让「屏幕看到的」与「run_all.log 存下的」逐字一致——用户只读日志即可判断
    每条 DOI 的成败 / 命中源 / 失败原因 / PDF 路径,无需回看终端滚屏或进代码。"""
    L: List[str] = []
    line = "=" * 72
    L.append(line)
    L.append("run_all 一页式总结  (RUNROOT=%s, %s)" % (p["runroot"], p["ts"]))
    # QC 虚高硬告警(审计-147 G2):--no-qc / 黑名单缺失 → 顶部醒目 WARN 横幅,避免"净成功率"被误读。
    _qc = p.get("qc", {})
    if _qc.get("warn"):
        L.append("!" * 72)
        L.append("⚠  警告:净成功率可能【虚高】—— %s" % (_qc.get("warn_reason") or "QC 未生效"))
        L.append("⚠  此数字仅供参考;启用 QC 且确保黑名单在位后再据此判断整体效果。")
        L.append("!" * 72)
    L.append("-" * 72)
    L.append("输入清单        : %d 条  →  去重后 %d 条(去重 -%d)" % (
        p["inputs_total"], p["after_dedup"], p["dup_removed"]))
    L.append("跨批续跑跳过    : %d 条(已在既有 out/ 真实成功)" % p["skipped_covered"])
    L.append("本次实际下载    : %d 条" % p["to_run"])
    L.append("-" * 72)
    L.append("本次结果        : 成功 %d / 处理 %d(miss %d),用时 %ss" % (
        p["run_success"], p["run_processed"], p["run_miss"], p["run_elapsed_sec"]))
    if p["run_by_source"]:
        L.append("本次命中源      : " + ", ".join("%s=%d" % (k, v) for k, v in p["run_by_source"].items()))
    L.append("-" * 72)
    cov = p["coverage"]
    qc = p.get("qc", {})
    if qc.get("enabled"):
        sb = qc.get("success_before_qc")
        rej = qc.get("rejected_total")
        qc_note = ""
        if sb is not None and rej is not None:
            qc_note = "  (QC 剔抓错论文: 原始成功 %d → 剔 %d → 净 %d)" % (sb, rej, qc.get("success_after_qc"))
        L.append("RUNROOT 覆盖(可信): 唯一 DOI %d | 净成功 %d | still_missing %d | 净成功率 %.1f%%%s" % (
            cov["total_unique_dois"], cov["success"], cov["miss"], cov["success_rate"] * 100, qc_note))
        L.append("QC 黑名单        : 硬黑 %s / 并集 %s DOI(消费审计 qc_merge_*_wrong.csv,已对齐双门 verdict)" % (
            qc.get("hard_list_dois"), qc.get("union_list_dois")))
    else:
        L.append("RUNROOT 覆盖(盲)  : 唯一 DOI %d | 成功 %d | still_missing %d | 成功率 %.1f%%  [未启用QC,可能虚高]" % (
            cov["total_unique_dois"], cov["success"], cov["miss"], cov["success_rate"] * 100))
    if cov.get("by_source"):
        L.append("覆盖命中源      : " + ", ".join("%s=%d" % (k, v) for k, v in list(cov["by_source"].items())[:6]))

    # ── 逐条明细(净口径):失败原因分桶 + 有限样例(失败优先);完整每条 DOI 见 run_all_detail.tsv ──
    rows = p.get("records") or []
    miss_rows = [r for r in rows if r.get("status") == "MISS"]
    ok_rows = [r for r in rows if r.get("status") == "OK"]
    by_reason = p.get("by_reason") or {}
    L.append("-" * 72)
    if by_reason:
        L.append("失败原因分桶    : " + ", ".join("%s=%d" % (k, v) for k, v in by_reason.items()))
    if miss_rows:
        L.append("失败逐条(前 %d/%d)  [MISS  doi | reason | error]:" % (
            min(_MAX_DETAIL_PRINT, len(miss_rows)), len(miss_rows)))
        for r in miss_rows[:_MAX_DETAIL_PRINT]:
            L.append("  MISS  %-38s | %-11s | %s" % (
                (r["doi"] or "?")[:38], r["reason"] or "-", (r["error"] or "-")[:66]))
        if len(miss_rows) > _MAX_DETAIL_PRINT:
            L.append("  … 其余 %d 条失败见 run_all_detail.tsv(grep '^MISS')" % (len(miss_rows) - _MAX_DETAIL_PRINT))
    if ok_rows:
        L.append("成功逐条(前 %d/%d)  [OK  doi | source | pdf 文件名]:" % (
            min(_MAX_DETAIL_PRINT, len(ok_rows)), len(ok_rows)))
        for r in ok_rows[:_MAX_DETAIL_PRINT]:
            L.append("  OK    %-38s | %-12s | %s" % (
                (r["doi"] or "?")[:38], r["source"] or "-", r["pdf_filename"] or "-"))
        if len(ok_rows) > _MAX_DETAIL_PRINT:
            L.append("  … 其余 %d 条成功见 run_all_detail.tsv" % (len(ok_rows) - _MAX_DETAIL_PRINT))
    L.append("-" * 72)
    if p.get("detail_tsv"):
        L.append("逐条明细(TSV)   : %s" % p["detail_tsv"])
        L.append("                  每条 DOI 一行;grep '^MISS' 看失败 / grep 源名看命中 / awk -F'\\t' 可统计")
    L.append("PDF 目录        : %s" % p["pdf_dir"])
    if p.get("fetch_dir"):
        L.append("fetch 原始日志   : %s  (pipeline 逐条 [OK]/[MISS] run.log + results.csv + attempts.jsonl)" % p["fetch_dir"])
    L.append("coverage.json   : %s" % p["coverage_json"])
    L.append("still_missing   : %s  (%d 条)" % (p["still_missing_txt"], cov["miss"]))
    L.append("run_all_summary : %s" % p["run_all_summary"])
    if p.get("run_all_log"):
        L.append("run_all.log     : %s  (本页快照;只读此文件即可判断每条成败/命中源/失败原因/PDF 路径)" % p["run_all_log"])
    if p.get("reproducibility"):   # 可复现自证(总指挥176):caliber 固定 + QC 快照 + --verify 断言净数可复现
        _rp = p["reproducibility"]
        L.append("可复现口径     : %s" % json.dumps(_rp.get("caliber") or {}, ensure_ascii=False))
        L.append("复现自证       : %s  (断言净数==本页,退 0/1)" % _rp.get("verify_cmd", ""))
    L.append(line)
    return L


def _print_page(payload: Dict[str, Any]) -> str:
    """打印一页式总结到 stdout,并返回其纯文本(供 run() 落 RUNROOT/run_all.log,屏幕/文件同源)。"""
    text = "\n".join(_render_page_lines(payload))
    print("\n" + text + "\n")
    return text


# ── QC 虚高硬告警(审计-147 G2)────────────────────────────────────────────────
# 弱告警("[缺失]"/内嵌一行)易被忽略。这里把「净成功率是否可能虚高」判定成一个显式布尔 + 原因,
# 供一页总结顶部打醒目 WARN 横幅、并落进 run_all_summary.json 的 qc.warn(机器可读)。纯展示层。
def _qc_warn_status(use_qc: bool, hard_missing: bool, soft_missing: bool) -> Tuple[bool, str]:
    """净成功率是否有「虚高」风险 + 原因:
    - 未启用 QC(--no-qc):盲口径,可能把 websearch 抓错论文计为成功 → 必 warn。
    - 启用 QC 但黑名单文件缺失:等同未剔假成功 → warn。
    - 启用且黑名单齐全 → 不 warn。"""
    if not use_qc:
        return True, "已 --no-qc:coverage 为盲口径,可能把 websearch 抓错论文计为成功(净成功率虚高)"
    missing = []
    if hard_missing:
        missing.append("硬黑名单 qc_merge_highconf_wrong.csv")
    if soft_missing:
        missing.append("并集黑名单 qc_merge_union_wrong.csv")
    if missing:
        return True, "QC 黑名单缺失(%s):抓错论文假成功未被剔除,净成功率可能虚高" % "、".join(missing)
    return False, ""


# ── 日志驱动调试:--explain <doi> 从 attempts.jsonl 渲染逐源→逐次尝试链(审计-147 G1)──────────
# attempts.jsonl 由 pipeline 的 EventLog 逐行写:每行 {"ts","event",...}。事件全集可回放一条 DOI 的
# 全生命周期:input/resolved/resolve_error/source/located/download/result + 兜底 content_qc/
# flaresolverr_{recovered,failed}/browser_capture_{recovered,failed}。均带 raw 或 doi → 可按 DOI 聚合。
# 本组开关只【读】日志渲染,不联网、不下载、不改任何数据,兑现"想知道这条为何 miss"的最后一公里。
_EXPLAIN_MAX_FILES = 400   # 扫 attempts.jsonl 的文件上限(防超大 out/ 拖慢;足够覆盖各批)


def iter_attempts_paths(runroot: str, coverage_root: str) -> List[str]:
    """收集要扫描的 attempts.jsonl:RUNROOT/fetch/attempts.jsonl 优先,再补 coverage_root 下各批的
    */**/attempts.jsonl(去重、保序、上限保护);不存在的自动跳过。"""
    seen: Set[str] = set()
    paths: List[str] = []

    def _add(p: str) -> None:
        ap = os.path.abspath(p)
        if ap not in seen and os.path.isfile(ap):
            seen.add(ap)
            paths.append(ap)

    _add(os.path.join(runroot, "fetch", "attempts.jsonl"))
    _add(os.path.join(runroot, "attempts.jsonl"))
    root = coverage_root or "out"
    if os.path.isdir(root):
        for dirpath, _dirs, files in os.walk(root):
            if "attempts.jsonl" in files:
                _add(os.path.join(dirpath, "attempts.jsonl"))
                if len(paths) >= _EXPLAIN_MAX_FILES:
                    break
    return paths


_FALLBACK_EVENTS = ("flaresolverr_recovered", "flaresolverr_failed",
                    "browser_capture_recovered", "browser_capture_failed")


def load_events_for_doi(doi_key: str, paths: List[str], bc: Any) -> List[Dict[str, Any]]:
    """从各 attempts.jsonl 聚合该 DOI 的事件,按 ts 升序。绝不抛(坏行/读不了跳过)。

    多数事件带 doi/raw → 规范化直配;而 FS/route-B 兜底事件(flaresolverr_*/browser_capture_*)只带
    url、不带 doi → 按「该 DOI 的 download/located 里出现过的 url」二次关联纳入(否则会漏掉'兜底为何
    失败')。doi_key 为空 → 返回空(不误聚合全部)。"""
    if not doi_key:
        return []
    hits: List[Dict[str, Any]] = []
    doi_urls: Set[str] = set()
    fallback_pool: List[Dict[str, Any]] = []   # 无 doi 的兜底事件,末尾按 url 关联到本 DOI
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for raw_line in f:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        ev = json.loads(raw_line)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(ev, dict):
                        continue
                    keys = {_norm_key(str(ev.get("doi") or ""), bc),
                            _norm_key(str(ev.get("raw") or ""), bc)}
                    if doi_key in keys:
                        ev["_src_file"] = path
                        hits.append(ev)
                        for u in (ev.get("url"), ev.get("top")):
                            if u:
                                doi_urls.add(str(u))
                    elif str(ev.get("event") or "") in _FALLBACK_EVENTS and ev.get("url"):
                        ev["_src_file"] = path
                        fallback_pool.append(ev)
        except OSError:
            continue
    for ev in fallback_pool:          # 兜底事件按 url 关联到该 DOI(看清 FS/route-B 为何失败)
        if str(ev.get("url")) in doi_urls:
            hits.append(ev)
    hits.sort(key=lambda e: e.get("ts") or 0)
    return hits


def render_explain_lines(doi_raw: str, doi_key: str, events: List[Dict[str, Any]]) -> List[str]:
    """把某 DOI 的事件序列渲染成人类可读的尝试链文本行(纯展示,不改任何数据)。"""
    L: List[str] = []
    bar = "=" * 72

    def _g(ev: Dict[str, Any], *names: str) -> str:
        for n in names:
            v = ev.get(n)
            if v not in (None, ""):
                return str(v)
        return ""

    L.append(bar)
    L.append("run_all --explain : %s" % doi_raw)
    if doi_key and doi_key != (doi_raw or "").strip().lower():
        L.append("  规范化 DOI 键 : %s" % doi_key)
    if not events:
        L.append("-" * 72)
        L.append("未在 attempts.jsonl 找到该 DOI 的任何事件。可能原因:")
        L.append("  · 该 DOI 尚未跑过(先 python run_all.py \"%s\" -o <RUNROOT>)" % doi_raw)
        L.append("  · -o(RUNROOT)或 --coverage-root 指错(attempts.jsonl 在 <RUNROOT>/fetch/)")
        L.append(bar)
        return L

    by_event: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events:
        by_event.setdefault(str(ev.get("event") or "?"), []).append(ev)

    L.append("-" * 72)
    for ev in by_event.get("resolved", []):
        L.append("解析 resolved   : doi=%s | title=%s | via=%s" % (
            _g(ev, "doi") or "-", (_g(ev, "title") or "-")[:56], _g(ev, "via") or "-"))
    for ev in by_event.get("resolve_error", []):
        L.append("解析失败        : %s" % (_g(ev, "error") or "-"))

    srcs = by_event.get("source", [])
    if srcs:
        L.append("逐源定位(%d):" % len(srcs))
        for ev in srcs:
            tag = "OK  " if ev.get("ok") else "MISS"
            L.append("  [%s] %-14s 候选 %-3s %6sms%s" % (
                tag, _g(ev, "source") or "-", _g(ev, "n") or "0", _g(ev, "ms") or "?",
                ("  error=" + _g(ev, "error")) if _g(ev, "error") else ""))
    for ev in by_event.get("located", []):
        L.append("候选汇总 located: 累计候选 %s | top=%s" % (
            _g(ev, "candidates") or "0", (_g(ev, "top") or "-")[:66]))

    dls = by_event.get("download", [])
    if dls:
        L.append("逐次下载(%d):" % len(dls))
        for ev in dls:
            tag = "OK  " if ev.get("ok") else "MISS"
            L.append("  [%s] %-12s %s" % (tag, _g(ev, "source") or "-", (_g(ev, "url") or "-")[:64]))
            extra = []
            if _g(ev, "kind"):
                extra.append("kind=" + _g(ev, "kind"))
            if _g(ev, "bytes"):
                extra.append(_g(ev, "bytes") + "B")
            if _g(ev, "error"):
                extra.append("error=" + _g(ev, "error"))
            if extra:
                L.append("            %s" % "  ".join(extra))

    fallbacks: List[Dict[str, Any]] = []
    for name in ("flaresolverr_recovered", "flaresolverr_failed",
                 "browser_capture_recovered", "browser_capture_failed", "content_qc"):
        fallbacks.extend(by_event.get(name, []))
    if fallbacks:
        L.append("兜底 / 质量事件:")
        for ev in fallbacks:
            e = str(ev.get("event"))
            if e == "content_qc":
                L.append("  content_qc   verdict=%s source=%s %s" % (
                    _g(ev, "verdict") or "-", _g(ev, "source") or "-",
                    (_g(ev, "reason", "detail") or "")[:48]))
            else:
                L.append("  %-26s url=%s %s" % (
                    e, (_g(ev, "url") or "-")[:48], (_g(ev, "error", "note") or "")[:40]))

    L.append("-" * 72)
    finals = by_event.get("result", [])
    if finals:
        ev = finals[-1]
        ok = bool(ev.get("success"))
        L.append("最终结果        : %s | source=%s | %sms%s" % (
            "OK(success)" if ok else "MISS",
            _g(ev, "source") or "-", _g(ev, "ms") or "?",
            ("  error=" + _g(ev, "error")) if (not ok and _g(ev, "error")) else ""))
    else:
        L.append("最终结果        : (无 result 事件——可能仍在跑 / 被中断)")
    for fp in sorted({ev.get("_src_file") for ev in events if ev.get("_src_file")}):
        L.append("来源日志        : %s" % fp)
    L.append(bar)
    return L


def run_explain(doi_raw: str, runroot: str, coverage_root: str, bc: Any) -> int:
    """--explain 入口:聚合→渲染→打印→落 RUNROOT/explain_<doi>.txt。绝不联网、不下载、不改数据。
    返回 0(找到该 DOI 事件)/ 1(未找到,便于脚本判定)。"""
    doi_key = _norm_key(doi_raw or "", bc)
    paths = iter_attempts_paths(runroot, coverage_root)
    events = load_events_for_doi(doi_key, paths, bc)
    text = "\n".join(render_explain_lines(doi_raw, doi_key, events))
    print("\n" + text + "\n")
    try:
        os.makedirs(runroot, exist_ok=True)
        safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in (doi_key or "unknown"))[:80]
        with open(os.path.join(runroot, "explain_%s.txt" % safe), "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass
    return 0 if events else 1


# ── 可复现自证:--verify 从隔离 RUNROOT 确定性复现它自己报告的净覆盖数(总指挥176 补充要求)──────
def run_verify(runroot: str, bc: Any) -> int:
    """读 RUNROOT/run_all_summary.json 取原报数 + QC 快照,用【快照】QC 黑名单(而非全局 out/,防漂移)
    对 RUNROOT 就地重算 coverage(flat-only + verify_allow),断言 (total/success/miss) == 原报数;
    并校验快照 sha256 未被篡改。全程只读重算、不落盘、不联网。返回 0(复现一致)/ 1(不一致或缺产物)。"""
    summ_path = os.path.join(runroot, "run_all_summary.json")
    if not os.path.isfile(summ_path):
        print("run_all --verify: 未找到 %s(先跑一次 run_all 生成产物)" % summ_path, file=sys.stderr)
        return 1
    try:
        with open(summ_path, "r", encoding="utf-8") as f:
            summ = json.load(f)
    except (OSError, ValueError) as e:  # noqa: BLE001
        print("run_all --verify: 读 summary 失败:%r" % e, file=sys.stderr)
        return 1

    reported = summ.get("coverage") or {}
    repro = summ.get("reproducibility") or {}
    use_qc = bool((summ.get("qc") or {}).get("enabled", True))

    # ① 快照完整性:sha256 未变(全局黑名单漂移不影响本 RUNROOT 复现,但快照本身被改则告警)
    integrity_ok = True
    for ent in ((repro.get("qc_snapshot") or {}).get("files") or []):
        rel = ent.get("snapshot")
        if not rel:
            continue
        cur = _sha256_file(os.path.join(runroot, rel.replace("/", os.sep)))
        if ent.get("sha256") and cur != ent.get("sha256"):
            integrity_ok = False
            print("run_all --verify: [WARN] QC 快照被改动 %s(sha256 不符)" % rel)

    # ② 用快照 QC 就地重算(flat-only + verify_allow;write=False 不落盘);快照缺失→退回默认路径(与原跑一致)
    snap_hard = _snapshot_role_path(runroot, repro, "qc_hard")
    snap_soft = _snapshot_role_path(runroot, repro, "qc_soft")
    cov = run_coverage(bc, runroot, use_qc=use_qc,
                       qc_hard_path=snap_hard, qc_soft_path=snap_soft, write=False)
    s = cov["summary"]
    got = {"total_unique_dois": s["total_unique_dois"], "success": s["success"], "miss": s["miss"]}
    want = {"total_unique_dois": reported.get("total_unique_dois"),
            "success": reported.get("success"), "miss": reported.get("miss")}
    match = all(got[k] == want[k] for k in got)

    bar = "=" * 72
    lines = [
        bar,
        "run_all --verify  (RUNROOT=%s)" % runroot,
        "caliber        : %s" % json.dumps(repro.get("caliber") or _REPRO_CALIBER, ensure_ascii=False),
        "原报(summary)  : 唯一 %s | 净成功 %s | miss %s" % (
            want["total_unique_dois"], want["success"], want["miss"]),
        "复算(snapshot) : 唯一 %s | 净成功 %s | miss %s" % (
            got["total_unique_dois"], got["success"], got["miss"]),
        "QC 快照完整性  : %s" % ("OK" if integrity_ok else "CHANGED"),
        "复现结论       : %s" % (
            "REPRODUCIBLE(数一致)" if (match and integrity_ok) else "MISMATCH(不一致)"),
        bar,
    ]
    print("\n" + "\n".join(lines) + "\n")
    return 0 if (match and integrity_ok) else 1


# ── 机构订阅(路线A)源顺序解析(补审计-147 G3)────────────────────────────────────
# 抽成纯函数是为了让「--sources 覆盖 + 机构态自动补插 publisher_direct」这条口径可离线 selftest,
# 且与核心 CLI(fulltext_fetcher/cli.py)逐字节对齐、绝不各起分叉。就地改 cfg.sources、不返回。
def _apply_institutional_sources(cfg: Any, sources_arg: Optional[str]) -> None:
    """据 --sources 覆盖源顺序,再按机构态自动补插 publisher_direct(顺序同核心 CLI:先覆盖、再补插)。

    关键口径:**覆盖必须先于补插**——否则机构态下用户一给 --sources,已注入的 publisher_direct 会被
    整表覆盖冲掉,路线A 反而半残(此前 run_all 的顺序即有此隐患)。publisher_direct 置于兜底 websearch
    之前(有 websearch 时)或追加末尾;非机构态绝不注入,避免每条 DOI 多一次 0 候选空尝试。"""
    if sources_arg:
        cfg.sources = [s.strip() for s in sources_arg.split(",") if s.strip()]
    if cfg.institutional and "publisher_direct" not in cfg.sources:
        if "websearch" in cfg.sources:
            cfg.sources.insert(cfg.sources.index("websearch"), "publisher_direct")
        else:
            cfg.sources.append("publisher_direct")


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
    ap.add_argument("--openalex-key", default=os.environ.get("OPENALEX_KEY"),
                    help="OpenAlex API key(默认取环境变量 OPENALEX_KEY)")
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
    # ── 机构订阅(路线A)一键面(补审计-147 G3)────────────────────────────────────
    # 此前 run_all 无 --institutional 开关面:机构订阅只能靠 env FTF_INSTITUTIONAL / .ftf_*.local.json
    # 隐式启用,"一键正门"对『订阅/混合出版商』这条重路径半残(审计-147 §1.1 机构订阅=⚠部分)。这里把
    # 核心 CLI 已有的机构四件套原样透传,口径与 `python -m fulltext_fetcher --institutional ...` 完全一致
    # (见 fulltext_fetcher/cli.py):启用后 publisher_direct 源自动接入(免费 OA 之后、websearch 之前),
    # 对已合法获取机构授权者构造订阅/混合出版商 PDF 直链;无订阅时直链 401/403 被 %PDF 校验过滤,不产假成功。
    # Cookie/前缀建议走环境变量而非命令行明文,避免留在 shell 历史里(默认取 env,与核心 CLI 同名)。
    ap.add_argument("--institutional", action="store_true",
                    help="启用机构订阅直链源 publisher_direct(路线A;一键接入订阅/混合出版商 PDF 直链)。"
                         "亦可设 FTF_INSTITUTIONAL=1 或 .ftf_institutional.local.json(见 .example);"
                         "仅供拥有合法机构订阅、对内容有访问权者使用;无订阅时直链会 401/403 被 %%PDF 校验过滤")
    ap.add_argument("--ezproxy-prefix", default=os.environ.get("EZPROXY_PREFIX"),
                    help="EZproxy 接入点:前缀式如 \"https://login.ezproxy.uni.edu/login?url=\";"
                         "或主机名改写式代理裸域名 \"ezproxy.uni.edu\"(默认取环境变量 EZPROXY_PREFIX)")
    ap.add_argument("--institution-cookie", default=os.environ.get("INSTITUTION_COOKIE"),
                    help="机构 SSO/EZproxy 登录后的会话 Cookie 串(\"k1=v1; k2=v2\");"
                         "强烈建议用环境变量 INSTITUTION_COOKIE 传入,不留 shell 历史;绝不入日志/产物")
    ap.add_argument("--institution-domain", action="append", default=None, metavar="DOMAIN",
                    help="仅对这些出版商域名启用机构通道(可重复给出,或单值内用逗号分隔,"
                         "如 sciencedirect.com,onlinelibrary.wiley.com);不给=不改写任何域名")
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
    # ── 文件命名模板(主线自定义命名·与 -156 契约对齐;一键正门默认统一命名)──────────────
    # **默认即统一命名** DEFAULT_NAMING_TEMPLATE = "{year}_{author}_{title}_{doi}"(见文件顶部说明):
    # 一键正门直击北极星"输出文件名标准化的系列全文",故默认就给人类可读 + 可溯源的模板名;元数据缺失
    # 优雅降级、全缺以 {doi} 兜底(等价旧 DOI 净化名,零回归)。给自定义模板即覆盖;退回纯 DOI 名传 "{doi}"。
    # run_all 只把它透传给 Config.naming_template(单一真源,同核心 CLI),由 download 层落盘时消费
    # (注入点见 fulltext_fetcher/download.py)。**注:核心库 Config.naming_template 仍默认 None(向后兼容),
    # 只有 run_all 这一层默认切统一模板;单条 `python -m fulltext_fetcher` 不受影响。**
    # 契约固定:Config.naming_template / env FULLTEXT_NAMING_TEMPLATE / 占位符 {year}/{author}/{title}/{doi}/{venue}。
    ap.add_argument("--naming-template",
                    default=os.environ.get("FULLTEXT_NAMING_TEMPLATE") or DEFAULT_NAMING_TEMPLATE,
                    help="文件命名模板(一键正门**默认即统一命名** \"%s\":人类可读 + 可溯源)。"
                         "复用 scholar 命名逻辑(净化/截断/去重同源),占位符 {year}/{author}/{title}/{doi}/{venue};"
                         "字段缺失优雅降级、年/作者/标题全缺时以 {doi} 兜底(等价旧 DOI 净化名,零回归)。"
                         "覆盖:传自定义模板即可;退回**纯 DOI 名**用 --naming-template \"{doi}\";"
                         "亦可用环境变量 FULLTEXT_NAMING_TEMPLATE 设默认" % DEFAULT_NAMING_TEMPLATE)
    # ── 日志驱动调试:--explain <doi> 渲染某条 DOI 的逐源→逐次尝试链(补审计-147 G1)──
    # 补最后一公里:此前想知道"某条为何 miss、各源分别怎么失败"仍需手读 fetch/attempts.jsonl(裸 JSON)。
    # 此开关读 attempts.jsonl(RUNROOT/fetch + --coverage-root 下各批)聚合该 DOI 的结构化事件,按时间
    # 渲染成人类可读的「解析→逐源定位→逐次下载→兜底(FS/route-B/QC)→最终结果」链,兑现"改码→跑→读日志"
    # 的调试闭环。纯读日志、不联网、不下载、不改任何数据。
    ap.add_argument("--explain", metavar="DOI",
                    help="日志驱动调试:读 attempts.jsonl 渲染某条 DOI 的逐源→逐次尝试链"
                         "(为何 miss/各源如何失败),打印并落 RUNROOT/explain_<doi>.txt。不联网、不下载、不改数据。")
    # ── 可复现自证(总指挥176 补充要求)──────────────────────────────────────────────
    # 一键 run 的净覆盖数必须能被【确定性复现】。--verify 读 RUNROOT/run_all_summary.json + qc_snapshot,
    # 就地重算 coverage 并断言 == 原报数(退 0/1)。不联网、不下载、不改数据;与 -o(RUNROOT)配套使用。
    ap.add_argument("--verify", action="store_true",
                    help="确定性复现:用 RUNROOT/qc_snapshot 就地重算 coverage 并断言 == run_all_summary.json 原报数"
                         "(净成功/miss/唯一DOI);退 0(一致)/1(不一致)。需配 -o RUNROOT;不联网/不下载/不改数据。")
    ap.add_argument("--selftest", action="store_true", help="离线自检后退出")
    return ap


def run(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    _force_utf8_console()   # 一页式总结/逐条明细含中文:Windows GBK 控制台先切 UTF-8,防乱码(输出层)

    bc = _load_build_coverage()
    if args.selftest:
        return _selftest(bc)
    if args.verify:    # 可复现自证:用 RUNROOT/qc_snapshot 就地重算并断言 == 原报数(不联网/不下载/不改数据)
        return run_verify(args.out, bc)
    if args.explain:   # 日志驱动调试:只读 attempts.jsonl 渲染某条 DOI 的尝试链(不联网/不下载/不改数据)
        return run_explain(args.explain, args.out, args.coverage_root, bc)

    # 延迟导入重依赖(selftest 不需要)
    from fulltext_fetcher.cli import _read_input_file
    from fulltext_fetcher.config import Config
    from fulltext_fetcher.pipeline import Pipeline

    raw_inputs: List[str] = list(args.inputs)
    if args.input_file:
        try:
            raw_inputs.extend(_read_input_file(args.input_file))
        except SystemExit as e:      # 读取层明确终态(不存在/损坏/缺 openpyxl):打印可读错误 + return 2,不裸 traceback
            print(str(e), file=sys.stderr)
            return 2
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
    qc_warn, qc_warn_reason = _qc_warn_status(
        use_qc, not os.path.isfile(qc_hp), not os.path.isfile(qc_sp))
    if use_qc:
        print("run_all: QC 黑名单 %s%s + %s%s" % (
            qc_hp, "" if os.path.isfile(qc_hp) else " [缺失]",
            qc_sp, "" if os.path.isfile(qc_sp) else " [缺失]"))
    else:
        print("run_all: 已 --no-qc(coverage 为盲口径,可能含抓错论文假成功,数字仅供参考)")
    if qc_warn:   # 审计-147 G2:虚高风险显式告警(屏幕即见;一页总结顶部另有 WARN 横幅)
        print("run_all: [WARN] 净成功率可能虚高 —— %s" % qc_warn_reason)

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
        openalex_key=args.openalex_key,
        out_dir=fetch_dir,
        naming_template=(args.naming_template or None),
        concurrency=args.concurrency,
        timeout=args.timeout,
        resume=args.resume,
        no_download=args.no_download,
        institutional=args.institutional,
        ezproxy_prefix=(args.ezproxy_prefix or None),
        institution_cookie=(args.institution_cookie or None),
        institution_domains=[d.strip() for raw in (args.institution_domain or [])
                             for d in raw.split(",") if d.strip()],
        route_b=args.route_b,
        browser_pdf_headless=args.browser_headless,
        browser_pdf_wait=args.browser_pdf_wait,
    )
    cfg.apply_route_b()      # 据 --route-b 派生 browser_capture / browser_pdf_download(单一真源,同核心 CLI)
    # 机构订阅(路线A)一键面(补审计-147 G3):合并 CLI/env/.ftf_*.local.json 机构凭据到 Config;
    # cli_institutional 透传 --institutional(口径同核心 CLI:cfg.institutional 为真即接入 publisher_direct)。
    from fulltext_fetcher.institutional import bootstrap_institutional_config
    inst_sess = bootstrap_institutional_config(cfg, cli_institutional=args.institutional)
    # --sources 覆盖 + 机构态 publisher_direct 补插(顺序同核心 CLI:先覆盖、再补插;见 _apply_institutional_sources)
    _apply_institutional_sources(cfg, args.sources)
    if cfg.institutional:   # 机构直链源:日志显式告警(读日志即可判断已启用路线A;仅合法机构授权者可用)
        cred = inst_sess.credentials
        src_note = (" 凭据自 FTF 加载(source=%s, provider=%s)" % (cred.source, cred.provider)) \
            if (cred and cred.enabled) else ""
        print("run_all: 已启用机构订阅直链源 publisher_direct(路线A):仅供拥有合法机构订阅、对内容有访问权者"
              "使用;无订阅的直链会 401/403 被 %%PDF 校验过滤,不产假成功。%s" % src_note)
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

    # ④b 可复现自证(总指挥176):把本次消费的 QC 黑名单快照进 RUNROOT/qc_snapshot/ + 记 caliber,
    #     让 `--verify` 日后从隔离 RUNROOT 独立复算出**同一净数**(不受全局 out/qc_*.csv 漂移影响)。
    qc_snapshot = (snapshot_qc_files(runroot, [("qc_hard", qc_hp), ("qc_soft", qc_sp)])
                   if use_qc else {"dir": _QC_SNAPSHOT_DIRNAME, "files": []})
    reproducibility = {
        "caliber": dict(_REPRO_CALIBER, use_qc=use_qc),
        "qc_snapshot": qc_snapshot,
        "verify_cmd": "python run_all.py --verify -o %s" % runroot,
        "note": ("隔离 RUNROOT 自证:--verify 用 qc_snapshot 就地重算,应 == 本 summary 的 "
                 "coverage(total_unique_dois/success/miss);全局黑名单漂移不影响本 RUNROOT 复现。"),
    }

    # ⑤ 逐条明细(输出层):从净口径 records 整理「每条 DOI 一行」→ 落可 grep 的 TSV + 进 payload/json
    detail_rows = build_detail_rows(cov.get("records") or [])
    detail_tsv = os.path.join(runroot, "run_all_detail.tsv")
    write_detail_tsv(detail_tsv, detail_rows)
    by_reason = dict(Counter(r["reason"] for r in detail_rows if r["status"] == "MISS").most_common())

    # ⑥ 一页式总结 + 机器可读落盘
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
            "warn": qc_warn,
            "warn_reason": qc_warn_reason,
            "hard_list_dois": qc_block.get("hard_list_dois"),
            "union_list_dois": qc_block.get("union_list_dois"),
            "success_before_qc": qc_block.get("success_before_qc"),
            "success_after_qc": qc_block.get("success_after_qc", cov_s["success"]),
            "rejected_total": qc_block.get("rejected_total"),
            "qc_paths": cov.get("_qc_paths"),
        },
        "pdf_dir": os.path.join(fetch_dir, "pdfs"),
        "fetch_dir": fetch_dir,
        "coverage_json": coverage_json,
        "still_missing_txt": missing_txt,
        "run_all_summary": os.path.join(runroot, "run_all_summary.json"),
        "run_all_log": os.path.join(runroot, "run_all.log"),
        "detail_tsv": detail_tsv,
        "by_reason": by_reason,
        "records": detail_rows,
        "skipped_covered_samples": skipped_covered[:10],
        "reproducibility": reproducibility,
    }
    with open(payload["run_all_summary"], "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    page_text = _print_page(payload)
    # 一页总结快照落 RUNROOT/run_all.log(输出层增强·任务[可用性]):与屏幕逐字一致,
    # 用户回看时只读此文件即可判断每条 DOI 成败/命中源/失败原因/PDF 路径,无需回滚终端或进代码。
    try:
        with open(payload["run_all_log"], "w", encoding="utf-8") as f:
            f.write(page_text + "\n")
    except OSError:
        pass                      # 落日志失败绝不影响主流程(屏幕已打印、json/tsv 已落盘)
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

    # ⑥ openalex_key 透传(补断点):CLI/env → Config,口径与 fulltext_fetcher/cli.py 一致
    a_oa = parser.parse_args(["10.1/x", "--openalex-key", "test-openalex-key-154"])
    _oa = _Cfg(openalex_key=a_oa.openalex_key)
    assert _oa.openalex_key == "test-openalex-key-154", _oa.openalex_key
    prev = os.environ.pop("OPENALEX_KEY", None)
    try:
        os.environ["OPENALEX_KEY"] = "env-openalex-key-154"
        a_env = build_parser().parse_args(["10.1/x"])
        assert a_env.openalex_key == "env-openalex-key-154", a_env.openalex_key
    finally:
        if prev is None:
            os.environ.pop("OPENALEX_KEY", None)
        else:
            os.environ["OPENALEX_KEY"] = prev

    # ⑦ 逐条明细输出层(任务[可用性]:只读日志即可判断每条 DOI 成败/命中源/失败原因/路径+文件名)
    #    reason_bucket:各类真实 error → 稳定简短桶(仅展示层,不改 coverage 口径/error 原文)
    assert reason_bucket("download-failed:cloudflare-challenge(http-403)") == "cf-403", reason_bucket("download-failed:cloudflare-challenge(http-403)")
    assert reason_bucket("download-failed:http-404") == "http-404"
    assert reason_bucket("download-failed:http-403") == "paywall"       # 无 cloudflare 的 403 归订阅墙
    assert reason_bucket("qc_hard_reject:wrong-paper(title-mismatch,both-methods)") == "qc-reject"
    assert reason_bucket("allow_revoked_openbook:wrong-paper(no-expected-doi)") == "qc-reject"
    assert reason_bucket("success-metadata-but-pdf-missing-on-disk") == "pdf-missing"
    assert reason_bucket("straggler-timeout") == "timeout"
    assert reason_bucket("no-candidates") == "no-source"
    assert reason_bucket("no-candidates-located") == "no-source"
    assert reason_bucket("resolve-failed:boom") == "resolve-fail"
    assert reason_bucket("") == "unknown" and reason_bucket(None) == "unknown"
    #    _pdf_basename:混合分隔符 + 含空格文件名 + 空值
    assert _pdf_basename("out/run/fetch/pdfs/a b.pdf") == "a b.pdf"
    assert _pdf_basename("out\\run\\fetch\\pdfs\\x.pdf") == "x.pdf"
    assert _pdf_basename(None) == "" and _pdf_basename("") == ""

    #    build_detail_rows:每条 DOI 一行,成功给 source+文件名、失败给 reason+error,MISS 排前
    sample_records = [
        {"doi": "10.1/ok1", "status": "success", "source": "unpaywall",
         "pdf_path": "out/r/fetch/pdfs/ok1.pdf", "title": "Good\tPaper\nOne", "error": None, "qc": None},
        {"doi": "10.2/cf", "status": "miss", "source": None, "pdf_path": None,
         "title": "CF paper", "error": "download-failed:cloudflare-challenge(http-403)", "qc": None},
        {"doi": "10.3/qc", "status": "miss", "source": None, "pdf_path": None,
         "title": None, "error": "qc_soft_reject:wrong-paper(audit-union)", "qc": "soft_reject"},
    ]
    rows = build_detail_rows(sample_records)
    assert [r["status"] for r in rows] == ["MISS", "MISS", "OK"], rows       # MISS 先、组内按 doi、OK 殿后
    d = {r["doi"]: r for r in rows}
    assert d["10.1/ok1"]["source"] == "unpaywall" and d["10.1/ok1"]["pdf_filename"] == "ok1.pdf", d["10.1/ok1"]
    assert d["10.1/ok1"]["reason"] == "" and d["10.1/ok1"]["error"] == "", d["10.1/ok1"]
    assert d["10.2/cf"]["reason"] == "cf-403" and d["10.2/cf"]["source"] == "", d["10.2/cf"]
    assert d["10.3/qc"]["reason"] == "qc-reject" and d["10.3/qc"]["qc"] == "soft_reject", d["10.3/qc"]

    #    write_detail_tsv:表头一致、行数一致、MISS 行首可 grep、列数恒定(title 里 \t\n 被清成空格不串列)
    import shutil as _sh
    import tempfile as _tf
    _d = _tf.mkdtemp(prefix="run_all_detail_selftest_")
    try:
        _tsv = os.path.join(_d, "run_all_detail.tsv")
        write_detail_tsv(_tsv, rows)
        with open(_tsv, "r", encoding="utf-8") as _f:
            _lines = _f.read().splitlines()
        assert _lines[0].split("\t") == _DETAIL_COLUMNS, _lines[0]
        assert len(_lines) == 1 + len(rows), _lines
        assert [ln for ln in _lines[1:] if ln.startswith("MISS")].__len__() == 2, _lines
        assert all(len(ln.split("\t")) == len(_DETAIL_COLUMNS) for ln in _lines[1:]), _lines
        _ok_line = [ln for ln in _lines[1:] if ln.startswith("OK")][0]
        assert "unpaywall" in _ok_line and "ok1.pdf" in _ok_line, _ok_line
        assert "Good Paper One" in _ok_line, "title 内的 tab/换行应被清成空格、不得串列: %s" % _ok_line
    finally:
        _sh.rmtree(_d, ignore_errors=True)

    # ⑧ 一页/日志渲染 _render_page_lines(输出层增强:run_all.log 快照与屏幕同源):QC 开/关两分支都不崩,
    #    含失败原因分桶、逐条样例(成败/命中源/失败原因)、TSV 指引与 run_all.log 指针 —— 兑现「只读日志即可判断」。
    _payload = {
        "ts": "2026-01-01 00:00:00", "runroot": "out/x",
        "inputs_total": 3, "after_dedup": 3, "dup_removed": 0, "skipped_covered": 0, "to_run": 3,
        "run_processed": 3, "run_success": 1, "run_miss": 2, "run_elapsed_sec": 1.0,
        "run_by_source": {"unpaywall": 1},
        "coverage": {"total_unique_dois": 3, "success": 1, "miss": 2, "success_rate": 0.3333,
                     "by_source": {"unpaywall": 1}},
        "qc": {"enabled": True, "hard_list_dois": 1, "union_list_dois": 1,
               "success_before_qc": 2, "success_after_qc": 1, "rejected_total": 1},
        "pdf_dir": "out/x/fetch/pdfs", "fetch_dir": "out/x/fetch",
        "coverage_json": "out/x/coverage.json", "still_missing_txt": "out/x/still_missing.txt",
        "run_all_summary": "out/x/run_all_summary.json", "run_all_log": "out/x/run_all.log",
        "detail_tsv": "out/x/run_all_detail.tsv",
        "by_reason": dict(Counter(r["reason"] for r in rows if r["status"] == "MISS").most_common()),
        "records": rows,          # 复用 ⑦ 的 sample_records → build_detail_rows(含 OK / cf-403 / qc-reject)
    }
    _page = "\n".join(_render_page_lines(_payload))
    assert "run_all 一页式总结" in _page and "run_all_detail.tsv" in _page, _page
    assert "out/x/run_all.log" in _page, "run_all.log 指针须进一页/日志(只读日志即可判断): %s" % _page
    assert "失败原因分桶" in _page and "cf-403=1" in _page and "qc-reject=1" in _page, _page
    assert "MISS  10.2/cf" in _page and "OK    10.1/ok1" in _page, _page   # 逐条样例(成败/命中源/原因)进页
    _blind = "\n".join(_render_page_lines({**_payload, "qc": {"enabled": False}}))
    assert "未启用QC" in _blind, _blind                                    # QC 关走盲口径分支不崩

    # ⑨ 日志驱动调试 --explain(审计-147 G1):attempts.jsonl → 某 DOI 逐源/逐次尝试链(含 url 关联兜底)
    _d2 = _tf.mkdtemp(prefix="run_all_explain_selftest_")
    try:
        _fetch2 = os.path.join(_d2, "fetch")
        os.makedirs(_fetch2, exist_ok=True)
        _att = os.path.join(_fetch2, "attempts.jsonl")
        _evlines = [
            {"ts": 1.0, "event": "input", "raw": "10.1021/CF", "kind": "doi", "value": "10.1021/cf"},
            {"ts": 1.1, "event": "resolved", "raw": "10.1021/CF", "doi": "10.1021/cf",
             "title": "A CF Paper", "via": "crossref"},
            {"ts": 1.2, "event": "source", "raw": "10.1021/CF", "doi": "10.1021/cf",
             "source": "unpaywall", "ok": False, "n": 0, "ms": 120, "error": "no-oa"},
            {"ts": 1.3, "event": "source", "raw": "10.1021/CF", "doi": "10.1021/cf",
             "source": "publisher_direct", "ok": True, "n": 1, "ms": 80, "error": None},
            {"ts": 1.4, "event": "download", "raw": "10.1021/CF", "doi": "10.1021/cf",
             "source": "publisher_direct", "url": "https://pubs.x/pdf", "kind": "pdf",
             "ok": False, "bytes": 0, "error": "download-failed:cloudflare-challenge(http-403)"},
            {"ts": 1.5, "event": "flaresolverr_failed", "url": "https://pubs.x/pdf",
             "error": "cf_clearance-bound-ja3"},                         # 无 doi,靠 url 关联
            {"ts": 1.6, "event": "result", "raw": "10.1021/CF", "doi": "10.1021/cf",
             "success": False, "source": None, "ms": 300,
             "error": "download-failed:cloudflare-challenge(http-403)"},
            {"ts": 1.7, "event": "source", "raw": "10.9/other", "doi": "10.9/other",
             "source": "unpaywall", "ok": True, "n": 1, "ms": 10, "error": None},  # 别的 DOI,不应混入
        ]
        with open(_att, "w", encoding="utf-8") as _f:
            for _e in _evlines:
                _f.write(json.dumps(_e, ensure_ascii=False) + "\n")
        _key = _norm_key("10.1021/CF", bc)
        assert _key == "10.1021/cf", _key
        _paths = iter_attempts_paths(_d2, _d2)
        assert os.path.abspath(_att) in [os.path.abspath(p) for p in _paths], _paths
        _events = load_events_for_doi(_key, _paths, bc)
        _names = [e["event"] for e in _events]
        assert _names == ["input", "resolved", "source", "source", "download",
                          "flaresolverr_failed", "result"], _names
        assert not any(e.get("doi") == "10.9/other" for e in _events), _events    # 别的 DOI 不混入
        _ex = "\n".join(render_explain_lines("10.1021/CF", _key, _events))
        assert "run_all --explain : 10.1021/CF" in _ex, _ex
        assert "逐源定位(2)" in _ex and "publisher_direct" in _ex and "unpaywall" in _ex, _ex
        assert "cloudflare-challenge(http-403)" in _ex, _ex
        assert "flaresolverr_failed" in _ex, _ex                          # 兜底事件按 url 关联进链
        assert "最终结果" in _ex and "MISS" in _ex, _ex
        # 找不到的 DOI → 空 + 可读提示(不崩);空 doi_key 保护(绝不聚合全部)
        _none_key = _norm_key("10.404/none", bc)
        assert load_events_for_doi(_none_key, _paths, bc) == [], "无关 DOI 不应聚合到事件"
        assert "未在 attempts.jsonl 找到" in "\n".join(render_explain_lines("10.404/none", _none_key, [])), "空事件应给可读提示"
        assert load_events_for_doi("", _paths, bc) == [], "空 doi_key 必须返回空,绝不聚合全部"
    finally:
        _sh.rmtree(_d2, ignore_errors=True)

    # ⑩ QC 虚高硬告警(审计-147 G2):_qc_warn_status 三态 + 一页顶部 WARN 横幅出现/消失
    assert _qc_warn_status(False, False, False)[0] is True, "--no-qc 必须 warn"
    assert _qc_warn_status(True, True, False)[0] is True, "硬黑名单缺失必须 warn"
    assert _qc_warn_status(True, False, True)[0] is True, "并集黑名单缺失必须 warn"
    assert _qc_warn_status(True, False, False) == (False, ""), "黑名单齐全不应 warn"
    _warn_payload = {**_payload, "qc": {**_payload["qc"], "warn": True,
                                        "warn_reason": "已 --no-qc:盲口径可能虚高"}}
    _warn_page = "\n".join(_render_page_lines(_warn_payload))
    assert "净成功率可能【虚高】" in _warn_page and "已 --no-qc:盲口径可能虚高" in _warn_page, _warn_page
    _nowarn_page = "\n".join(_render_page_lines({**_payload, "qc": {**_payload["qc"], "warn": False}}))
    assert "净成功率可能【虚高】" not in _nowarn_page, _nowarn_page

    # ⑪ 机构订阅(路线A)一键面(补审计-147 G3):--institutional 四件套透传 + publisher_direct 补插
    #    口径须与核心 CLI(fulltext_fetcher/cli.py)逐字节一致:先 --sources 覆盖、再机构态补插 publisher_direct。
    _p = build_parser()
    assert _p.parse_args(["10.1/x"]).institutional is False, "默认必须不启用机构订阅(零副作用)"
    a_inst = _p.parse_args([
        "10.1/x", "--institutional",
        "--ezproxy-prefix", "https://login.ezproxy.uni.edu/login?url=",
        "--institution-cookie", "k1=v1; k2=v2",
        "--institution-domain", "sciencedirect.com,pubs.acs.org",
        "--institution-domain", "onlinelibrary.wiley.com",
    ])
    assert a_inst.institutional is True, vars(a_inst)
    _dom = [d.strip() for raw in (a_inst.institution_domain or []) for d in raw.split(",") if d.strip()]
    assert _dom == ["sciencedirect.com", "pubs.acs.org", "onlinelibrary.wiley.com"], _dom
    _icfg = _Cfg(institutional=a_inst.institutional,
                 ezproxy_prefix=(a_inst.ezproxy_prefix or None),
                 institution_cookie=(a_inst.institution_cookie or None),
                 institution_domains=_dom)
    assert _icfg.institutional and _icfg.ezproxy_prefix.endswith("login?url="), vars(_icfg)
    assert _icfg.institution_cookie == "k1=v1; k2=v2" and _icfg.institution_domains == _dom, vars(_icfg)
    #   机构态 + --sources(含 websearch、不含 publisher_direct):必须仍补插 publisher_direct(证明"先覆盖再补插";
    #   否则 --sources 会把订阅直链源整表冲掉→路线A 半残)。这是此前 run_all 顺序的隐患,本波对齐核心 CLI 修复。
    _isrc = _Cfg(institutional=True)
    _apply_institutional_sources(_isrc, "unpaywall,websearch")
    assert _isrc.sources == ["unpaywall", "publisher_direct", "websearch"], _isrc.sources
    #   机构态但源里无 websearch → publisher_direct 追加末尾(兜底顺序)
    _asrc = _Cfg(institutional=True); _asrc.sources = ["unpaywall", "green_oa"]
    _apply_institutional_sources(_asrc, None)
    assert _asrc.sources == ["unpaywall", "green_oa", "publisher_direct"], _asrc.sources
    #   非机构态:绝不注入 publisher_direct(避免每条 DOI 多一次 0 候选空尝试)
    _nsrc = _Cfg(institutional=False)
    _apply_institutional_sources(_nsrc, "unpaywall,websearch")
    assert "publisher_direct" not in _nsrc.sources, _nsrc.sources
    #   幂等:再次调用不重复注入(补插仅在缺失时发生)
    _apply_institutional_sources(_isrc, None)
    assert _isrc.sources.count("publisher_direct") == 1, _isrc.sources

    # ⑫ 文件命名模板透传(与 -156 --naming-template 契约对齐 + 一键正门默认统一命名)
    #    关键口径:**核心库 Config 默认仍 None(逐字节向后兼容)**;只有 run_all 这层默认切统一模板
    #    DEFAULT_NAMING_TEMPLATE="{year}_{author}_{title}_{doi}"。给模板 → 覆盖;env FULLTEXT_NAMING_TEMPLATE 优先于内置默认。
    assert _Cfg().naming_template is None, "核心库 Config 默认命名模板必须仍为 None(向后兼容,单条 CLI 不受影响)"
    assert DEFAULT_NAMING_TEMPLATE == "{year}_{author}_{title}_{doi}", DEFAULT_NAMING_TEMPLATE
    _prev_nt = os.environ.pop("FULLTEXT_NAMING_TEMPLATE", None)
    try:
        # 默认不给且无 env → 一键正门默认统一命名(而非 None):这是本波"建议默认就开统一命名"的落地点
        assert build_parser().parse_args(["10.1/x"]).naming_template == DEFAULT_NAMING_TEMPLATE, \
            "run_all 默认应为统一命名模板(建议默认就开统一命名)"
        # 显式自定义模板 → 覆盖内置默认
        _a_nt = build_parser().parse_args(["10.1/x", "--naming-template", "{year}_{author}_{title}"])
        assert _a_nt.naming_template == "{year}_{author}_{title}", _a_nt.naming_template
        assert _Cfg(naming_template=(_a_nt.naming_template or None)).naming_template == \
            "{year}_{author}_{title}", _a_nt.naming_template
        # 退回纯 DOI 名(等价旧默认):--naming-template "{doi}"
        _a_doi = build_parser().parse_args(["10.1/x", "--naming-template", "{doi}"])
        assert _a_doi.naming_template == "{doi}", _a_doi.naming_template
        # env FULLTEXT_NAMING_TEMPLATE 优先于内置默认(与核心 CLI 一致)
        os.environ["FULLTEXT_NAMING_TEMPLATE"] = "{author}-{year}"
        assert build_parser().parse_args(["10.1/x"]).naming_template == "{author}-{year}", \
            "env FULLTEXT_NAMING_TEMPLATE 应优先于内置默认统一模板"
    finally:
        if _prev_nt is None:
            os.environ.pop("FULLTEXT_NAMING_TEMPLATE", None)
        else:
            os.environ["FULLTEXT_NAMING_TEMPLATE"] = _prev_nt

    # ⑬ 可复现自证(总指挥176 补充要求):QC 快照(sha256/行数)+ --verify 从隔离 RUNROOT 独立复算净数 ==
    #    原报数。造一个最小 RUNROOT(fetch/metadata.jsonl + pdfs + qc_snapshot union),验证:一致→0、
    #    篡改报数→1(MISMATCH)、篡改快照→1(完整性)。全离线、临时目录,不动真实 out/。
    assert "--verify" in build_parser().format_help(), "run_all 必须暴露 --verify(可复现自证)"
    assert build_parser().parse_args(["--verify", "-o", "out/x"]).verify is True, "‑‑verify 应可解析"
    #    _sha256_file/_count_lines:内容指纹 + 行数,缺文件→None
    _dv = _tf.mkdtemp(prefix="run_all_verify_selftest_")
    try:
        _qc = os.path.join(_dv, "u.csv")
        with open(_qc, "w", encoding="utf-8") as _f:
            _f.write("doi\n10.1000/d2\n")
        assert _sha256_file(_qc) and len(_sha256_file(_qc)) == 64, "sha256 应为 64 位 hex"
        assert _sha256_file(os.path.join(_dv, "nope.csv")) is None, "缺文件 sha256→None"
        assert _count_lines(_qc) == 2 and _count_lines(os.path.join(_dv, "nope.csv")) is None, _count_lines(_qc)
        #    snapshot_qc_files:复制进 RUNROOT/qc_snapshot、记 sha256/行数;缺失项 exists=False
        _rr = os.path.join(_dv, "RUN")
        os.makedirs(_rr, exist_ok=True)
        _snap = snapshot_qc_files(_rr, [("qc_hard", os.path.join(_dv, "absent.csv")), ("qc_soft", _qc)])
        _byrole = {e["role"]: e for e in _snap["files"]}
        assert _byrole["qc_hard"]["exists"] is False and _byrole["qc_hard"]["snapshot"] is None, _byrole["qc_hard"]
        assert _byrole["qc_soft"]["exists"] is True and _byrole["qc_soft"]["sha256"] == _sha256_file(_qc), _byrole["qc_soft"]
        assert os.path.isfile(os.path.join(_rr, _byrole["qc_soft"]["snapshot"].replace("/", os.sep))), _byrole["qc_soft"]

        #    造 RUNROOT/fetch:d1 真成功(pdf 在盘)、d2 真成功但被 union 剔、d3 miss → 净成功 1/总 3/miss 2
        _fetch = os.path.join(_rr, "fetch")
        os.makedirs(os.path.join(_fetch, "pdfs"), exist_ok=True)
        with open(os.path.join(_fetch, "metadata.jsonl"), "w", encoding="utf-8") as _f:
            _f.write(json.dumps({"raw_input": "10.1000/d1", "doi": "10.1000/d1", "success": True,
                                 "source_used": "unpaywall", "pdf_path": "out/RUN/fetch/pdfs/d1.pdf",
                                 "pdf_bytes": 10}) + "\n")
            _f.write(json.dumps({"raw_input": "10.1000/d2", "doi": "10.1000/d2", "success": True,
                                 "source_used": "websearch", "pdf_path": "out/RUN/fetch/pdfs/d2.pdf",
                                 "pdf_bytes": 10}) + "\n")
            _f.write(json.dumps({"raw_input": "10.1000/d3", "doi": "10.1000/d3", "success": False,
                                 "error": "no-candidates"}) + "\n")
        open(os.path.join(_fetch, "pdfs", "d1.pdf"), "w").close()
        open(os.path.join(_fetch, "pdfs", "d2.pdf"), "w").close()

        def _write_summary(_success):   # 写一份 summary(coverage 报 _success)+ 复用上面的 union 快照
            _payload = {
                "coverage": {"total_unique_dois": 3, "success": _success, "miss": 3 - _success},
                "qc": {"enabled": True},
                "reproducibility": {"caliber": dict(_REPRO_CALIBER, use_qc=True), "qc_snapshot": _snap},
            }
            with open(os.path.join(_rr, "run_all_summary.json"), "w", encoding="utf-8") as _sf:
                json.dump(_payload, _sf, ensure_ascii=False)

        _write_summary(1)                         # 原报净成功 1(d2 被 union 剔)
        assert run_verify(_rr, bc) == 0, "快照 union 剔 d2 → 复算净成功 1 == 原报 → 应 REPRODUCIBLE(0)"
        _write_summary(2)                         # 原报净成功 2(错报)→ 复算仍 1 → MISMATCH
        assert run_verify(_rr, bc) == 1, "复算净数与原报不一致 → 应 MISMATCH(1)"
        _write_summary(1)                         # 改回一致,再验"快照被篡改"→ 完整性失败(1)
        _snap_soft = os.path.join(_rr, _byrole["qc_soft"]["snapshot"].replace("/", os.sep))
        with open(_snap_soft, "a", encoding="utf-8") as _f:
            _f.write("10.1000/d1\n")              # 篡改快照(sha256 变)
        assert run_verify(_rr, bc) == 1, "快照 sha256 被篡改 → 完整性失败 → 1"
        #    缺 summary → 1(优雅失败,不抛)
        assert run_verify(os.path.join(_dv, "NOPE"), bc) == 1, "缺 run_all_summary.json → 1"
    finally:
        _sh.rmtree(_dv, ignore_errors=True)

    # ⑧ 输入健壮性(承 -167 + cli 修复):run_all 复用 cli._read_input_file——GBK 不崩、不存在文件走明确终态,
    #    且 run() 调用点对读取失败 return 2(不裸 traceback+exit 1)。
    import tempfile as _tf8
    from fulltext_fetcher.cli import _read_input_file as _rif8
    with _tf8.TemporaryDirectory() as _d8:
        _pg = os.path.join(_d8, "gbk_runall.txt")
        with open(_pg, "w", encoding="gbk") as _f8:
            _f8.write("石墨烯综述\n10.1021/jacs.0c00000\n")
        assert _rif8(_pg) == ["石墨烯综述", "10.1021/jacs.0c00000"], _rif8(_pg)
        _nope = os.path.join(_d8, "nope_runall_selftest.txt")
        try:
            _rif8(_nope)
            raise AssertionError("not-found 应抛 SystemExit(明确终态)")
        except SystemExit as _e8:
            assert "不存在" in str(_e8), str(_e8)
        assert run(["-f", _nope]) == 2, "run() 对不存在输入文件应 return 2(非裸 traceback)"

    print("RUN_ALL_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
