"""跨批 coverage / still_missing 主库(纯读 out/,只新写两份产物)。

服务北极星「一键出全集 / 续跑」:把散落在多个 out/ 子目录里的每批 metadata.jsonl
聚成一份**按 DOI 去重的规范状态主库**,并导出「仍缺 DOI 全集」直接喂下一轮续跑。

为什么需要它(而非直接看各 summary.json):
- summary.json 只统计「本次运行 processed 的条数」,断点续跑 skipped 的历史成功不计入,
  会**低估**真实成功;且回收/probe 分散在多个 out 目录,单目录口径看不到全局。
- 因此权威口径以「metadata.jsonl 去重 + pdfs/ 落盘实证」为准,**不信 summary.json**
  (与 tools/aggregate_batch4.py 完全同口径,可交叉复核 866/1213≈71.4% 审计基线)。

口径定义(务必对齐审计):
- dedup key:规范化 DOI(优先 doi 字段,回退 raw_input;小写、去 doi.org/doi: 前缀)。
- 「真实成功(success)」:某 DOI 至少有一条 success==true **且**其 pdf_path 的文件名确实存在于
  该批 pdfs/ 目录(basename 落盘实证)。仅 metadata 声称成功但盘上无文件 → 不计成功,
  标 claimed_success_but_no_pdf(属可复下的软缺口 / 审计差异)。
- 跨批合并:success 为**并集**(任一批真实成功即成功);多处成功时取 pdf_bytes 最大的那条,
  附其 source / pdf_path / batch。miss 的 error **取末次**(按各批 metadata.jsonl 的 mtime
  升序、行内顺序,最后一次尝试的失败原因),便于据最新原因决定后续路线。

产物:
- <out_root>/coverage.json    每 DOI 规范状态 + 全局汇总(success/miss/by_source/各批统计)。
- <out_root>/still_missing.txt 仍缺 DOI 全集(每行一条、排序;# 头注释可被 fetcher -f 跳过,
                               可直接作 `python -m fulltext_fetcher -f still_missing.txt` 续跑输入)。

安全:只读 out/ 下已有产物(metadata.jsonl / pdfs/),只新写上面两份;绝不改任何核心码或他人 out_dir。

双入口(供 run_all 一键编排接线;全组唯一『黑名单感知』权威 coverage,勿另起分叉):
  1) CLI:
     python tools/build_coverage.py                       # 扫 out/,消费 QC 黑名单,写 out/coverage.json + still_missing.txt
     python tools/build_coverage.py --no-write            # 只打印全局汇总,不落盘
     python tools/build_coverage.py --print-json          # stdout 输出 summary JSON(供父程序/子进程解析)
     python tools/build_coverage.py --no-qc               # 原始去重口径(不剔抓错论文)
     python tools/build_coverage.py --coverage-json X.json --missing-txt Y.txt
     python tools/build_coverage.py --selftest            # 离线自检 → COVERAGE_OK
  2) import(run_all 直接调用):
     from tools.build_coverage import run_coverage
     res = run_coverage("out")                    # 默认消费 out/qc_merge_*_wrong.csv + qc_uncertain_reject.csv、落盘、返回结果 dict
     print(res["summary"]["success"], res["summary"]["success_rate"])  # 净口径 KPI
     # 关键返回:res["summary"] = {total_unique_dois, success(净), miss, success_rate, qc{...}, crosscheck_per_batch_sum{...}, by_source, ...}
     #          res["records"](按 DOI 排序规范状态)、res["_written"](落盘路径)、res["_qc_paths"]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

OUT_DIR = "out"

# 「嵌套扫描」默认剔除的测试/演示夹具:这些目录(run_all_demo_*/smoke170* 的 fetch/)是冒烟/演示产出,
# 会引入**语料外 DOI**(如 demo 的 arXiv:1706.03762「Attention is all you need」),纳入会污染
# 999 条权威语料的 total/success 口径。仅作用于二级+ 目录的顶层名匹配;一级目录一律照旧收录,
# 以严格保持既有 999/371 审计基线不漂移(含名字里恰好含 smoke 的一级 recover_b4_cf_smoke_179)。
_NESTED_EXCLUDE_SUBSTR = ("demo", "smoke")

# 与 tools/aggregate_batch4.py / tools/dedup_recover_input.py / resolve.py 保持一致的 DOI 前缀清单。
_DOI_PREFIXES = (
    "https://doi.org/", "http://doi.org/",
    "https://dx.doi.org/", "http://dx.doi.org/",
    "https://www.doi.org/", "http://www.doi.org/",
    "doi.org/", "doi:",
)

# claimed success 但盘上无 pdf 时,给 miss 记录合成的 error(便于与真失败区分、后续复下)。
_NO_PDF_ERROR = "success-metadata-but-pdf-missing-on-disk"


def _force_utf8_console() -> None:
    """Windows 控制台默认 GBK 会把中文/统计打成乱码;尽力把 stdout/stderr 切到 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - 老解释器/被重定向时静默降级
            pass


def norm_doi(rec: Dict[str, Any]) -> Optional[str]:
    """规范化去重键:优先 doi,回退 raw_input;小写、去常见 DOI 前缀。空则 None。"""
    for key in ("doi", "raw_input"):
        v = (rec.get(key) or "").strip().strip('"').strip("'").lower()
        changed = True
        while changed:  # 允许 https://doi.org/doi:10.x 之类叠套前缀
            changed = False
            for pre in _DOI_PREFIXES:
                if v.startswith(pre):
                    v = v[len(pre):].strip()
                    changed = True
        if v:
            return v
    return None


def basename_of(pdf_path: Optional[str]) -> Optional[str]:
    """取 pdf_path 的文件名。metadata 里是混合分隔符(out/batch4_p1\\pdfs\\x.pdf)。"""
    if not pdf_path:
        return None
    return pdf_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or None


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    """稳健读取 jsonl:跳过空行与半截行(文件仍被实时追加时末行可能不完整)。"""
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


def read_qc_dois(path: str) -> Set[str]:
    """读取审计 QC 黑名单 CSV(表头含 doi 列),返回规范化裸 DOI 集合。文件缺失→空集。"""
    out: Set[str] = set()
    if not path or not os.path.isfile(path):
        return out
    import csv
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return out
    header = [c.strip().lower() for c in rows[0]]
    doi_i = header.index("doi") if "doi" in header else -1
    body = rows[1:] if doi_i >= 0 else rows            # 无表头则退化为取每行首列
    for r in body:
        raw = r[doi_i] if (0 <= doi_i < len(r)) else (r[0] if r else "")
        d = norm_doi({"doi": raw})
        if d:
            out.add(d)
    return out


def read_doi_list(path: Optional[str]) -> Set[str]:
    """稳健读取「一行一 DOI」清单(供 --qc-allow / --qc-extra-reject 消费下游内容QC 成员的产物)。

    兼容三种常见格式:纯 DOI 每行一条、TSV(doi\\t类型,如 -145 的 rerun_acs_144_deduct_dois_145.txt)、
    CSV(doi,...)。规则:跳过空行与 # 注释行,取每行**首个** tab/逗号/空白 分隔的 token 作 DOI,
    经 norm_doi 归一。文件缺失/为空→空集。与 read_qc_dois(需 doi 表头列)互补:此函数不要求表头。"""
    out: Set[str] = set()
    if not path or not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tok = line.replace("\t", " ").replace(",", " ").split()
            if not tok:
                continue
            d = norm_doi({"doi": tok[0]})
            if d:
                out.add(d)
    return out


def read_doi_lists(paths: Optional[Iterable[str]]) -> Set[str]:
    """合并多个 DOI 清单文件为一个集合(任一缺失优雅跳过)。"""
    out: Set[str] = set()
    for p in (paths or []):
        out |= read_doi_list(p)
    return out


def read_qc_manifest(path: str) -> Tuple[Set[str], Set[str]]:
    """读取 cleanup(165)产的物理归置清单 out/qc_rejected_manifest.csv,返回 (hard, soft) 规范化 DOI 集。

    列:doi,batch,source(hard/soft),status,orig_path,new_path。这是『实际被移出 pdfs/ 的错论文』
    的**地面真相**,与审计 qc_merge_*_wrong.csv 互为印证;文件缺失→(空,空)。"""
    hard: Set[str] = set()
    soft: Set[str] = set()
    if not path or not os.path.isfile(path):
        return hard, soft
    import csv
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        return hard, soft
    header = [c.strip().lower() for c in rows[0]]
    doi_i = header.index("doi") if "doi" in header else 0
    src_i = header.index("source") if "source" in header else -1
    for r in rows[1:]:
        d = norm_doi({"doi": r[doi_i]}) if 0 <= doi_i < len(r) else None
        if not d:
            continue
        src = (r[src_i].strip().lower() if (0 <= src_i < len(r)) else "soft")
        (hard if src == "hard" else soft).add(d)
    return hard, soft


def resolve_qc_sets(out_root: str,
                    hard_path: Optional[str] = None,
                    soft_path: Optional[str] = None,
                    manifest_path: Optional[str] = None,
                    uncertain_path: Optional[str] = None) -> Tuple[Set[str], Set[str]]:
    """汇集全部 QC 排除源为 (hard, soft):审计 qc_merge_highconf_wrong.csv(hard)+ qc_merge_union_wrong.csv
    (union)+ cleanup 物理归置清单 qc_rejected_manifest.csv(按其 source 列分 hard/soft)+ uncertain 拒收
    清单 qc_uncertain_reject.csv(153 对 uncertain 池抽样 40/40 全错,整池按错论文拒收 → 并入 soft/union)。
    各源取并集,互为冗余印证(任一源缺失都优雅降级)。soft 最终并入 hard(union ⊇ hard),便于 build() 归类。"""
    hp = hard_path or os.path.join(out_root, "qc_merge_highconf_wrong.csv")
    sp = soft_path or os.path.join(out_root, "qc_merge_union_wrong.csv")
    mp = manifest_path or os.path.join(out_root, "qc_rejected_manifest.csv")
    up = uncertain_path or os.path.join(out_root, "qc_uncertain_reject.csv")
    hard = read_qc_dois(hp)
    soft = read_qc_dois(sp) | read_qc_dois(up)
    m_hard, m_soft = read_qc_manifest(mp)
    hard |= m_hard
    soft |= m_soft | m_hard
    return hard, soft


def pdf_basenames(dir_full: str) -> Set[str]:
    """某批 pdfs/ 目录里的全部文件名(落盘实证用)。"""
    d = os.path.join(dir_full, "pdfs")
    if not os.path.isdir(d):
        return set()
    return {n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n))}


def is_core_batch(name: str) -> bool:
    """三个「主语料批」:batch4 五分片 + batch6 + batch7。对它们的**逐批(非去重)求和**即审计
    口径 866/1213(把 batch7 的 213 输入当独立批、其 108 成功含与 batch6 重复的部分)。
    回收/probe 目录(recover_*/`*_reprobe_*`/`*_probe_*`)不属主语料,不计入该交叉核对。"""
    return name in ("batch6", "batch7") or name.startswith("batch4_p")


def list_batch_dirs(out_root: str,
                    include_nested: bool = False,
                    exclude_substrings: Tuple[str, ...] = _NESTED_EXCLUDE_SUBSTR,
                    extra_dirs: Optional[Iterable[str]] = None) -> List[str]:
    """out_root 下含 metadata.jsonl 的目录(相对 out_root、正斜杠归一),按 metadata.jsonl 的
    mtime 升序(旧→新),使「miss 取末次」= 最近一次尝试的原因。

    历史 bug:只扫一级 out/<dir>/metadata.jsonl,漏了 run_all 自带的**二级**产出
    out/<dir>/fetch/metadata.jsonl(rerun_*/recover_* 多为此形,甚至 rerun_cf_savable_140/<sub>/fetch
    的三级),导致真实回收下来并已落盘的 PDF 被 coverage 漏计。

    **口径治理(总指挥 -142 定)**:嵌套扫描**默认关闭**,以保证默认(权威)运行仍是「只扫一级」
    的稳定 999/371 基线、不被实验目录污染;仅在**显式开启**时才纳入二级+ 产出,且必须经 QC 门
    才可作权威回写。规则:
      - 一级目录:一律收录(与旧实现逐字等价 → 严格保持审计基线);
      - include_nested=False(**默认**):只扫一级(旧权威行为);
      - include_nested=True(需显式 --nested / flag):额外递归收录二级+ 产出,但剔除顶层名含
        demo/smoke 的测试夹具(见 _NESTED_EXCLUDE_SUBSTR;它们含语料外 DOI 会污染权威口径);
      - extra_dirs:显式强制纳入的相对目录(绕过 demo/smoke 排除、且无视 include_nested,供人工
        定向圈定,如 Step2 只回写 rerun_acs_144/fetch)。
    """
    if not os.path.isdir(out_root):
        return []
    seen: Set[str] = set()
    items: List[Tuple[float, str]] = []

    def _add(rel: str) -> None:
        rel = rel.replace("\\", "/").strip("/")
        if not rel or rel in seen:
            return
        if not os.path.isfile(os.path.join(out_root, rel, "metadata.jsonl")):
            return
        seen.add(rel)
        try:
            mt = os.path.getmtime(os.path.join(out_root, rel, "metadata.jsonl"))
        except OSError:
            mt = 0.0
        items.append((mt, rel))

    # 一级目录:照旧全收(与旧实现等价,保持基线)
    for name in os.listdir(out_root):
        if os.path.isfile(os.path.join(out_root, name, "metadata.jsonl")):
            _add(name)

    # 二级+ 目录:递归发现,剔除 demo/smoke 测试夹具(仅按顶层名判定)
    if include_nested:
        for root, _dirs, files in os.walk(out_root):
            if "metadata.jsonl" not in files:
                continue
            rel = os.path.relpath(root, out_root).replace("\\", "/")
            if rel == "." or "/" not in rel:
                continue  # 根目录 / 一级目录已在上面处理
            top = rel.split("/", 1)[0]
            if any(sub in top for sub in exclude_substrings):
                continue
            _add(rel)

    # 显式强制纳入(绕过 demo/smoke 排除;已收录的自动去重)
    for rel in (extra_dirs or []):
        _add(rel)

    items.sort(key=lambda t: (t[0], t[1]))
    return [rel for _mt, rel in items]


def build(out_root: str,
          qc_hard: Optional[Set[str]] = None,
          qc_soft: Optional[Set[str]] = None,
          *,
          qc_allow: Optional[Set[str]] = None,
          include_nested: bool = False,
          exclude_substrings: Tuple[str, ...] = _NESTED_EXCLUDE_SUBSTR,
          extra_dirs: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """扫描 out_root 下所有批次(含二级+ 嵌套 metadata.jsonl),返回聚合结果(cov 记录 + 各批统计 + 全局汇总)。

    QC 黑名单(来自审计):qc_hard=两法都判错的铁证 DOI,qc_soft=并集(可含 hard)。凡命中者
    即便真实下到 pdf 也**判为抓错论文的假成功**,从 success 剔除、改判 miss(计入 still_missing),
    并标 qc=hard_reject/soft_reject。两集均为已规范化的裸 DOI(与 norm_doi 同口径)。

    qc_allow(白名单/免死金牌):下游**逐条内容QC**已核实为「真正文正确」的 DOI,即便命中审计黑名单
    (hard/union)也**不剔除**(用于纠正 DOI 键黑名单的假阳:同一 DOI 早前抓错、这次经新路线抓对了)。
    仅「解除拦截」,不凭空造成功——DOI 若本就不是落盘真成功,列入白名单也无效。命中者在 records 标
    qc=allow_override,summary.qc.allow_override 计数。优先级最高(白名单 > 黑名单)。

    include_nested/exclude_substrings/extra_dirs 透传 list_batch_dirs(默认递归收录嵌套产出、
    剔除 demo/smoke 夹具);见其 docstring。"""
    qc_hard = qc_hard or set()
    qc_soft = (qc_soft or set()) | qc_hard   # 并集始终包含硬黑,便于 soft=union-hard 归类
    qc_allow = qc_allow or set()
    qc_hard = qc_hard - qc_allow             # 白名单优先级最高:内容QC 已核实真正文,免于黑名单剔除
    qc_soft = qc_soft - qc_allow
    dirs = list_batch_dirs(out_root, include_nested=include_nested,
                           exclude_substrings=exclude_substrings, extra_dirs=extra_dirs)
    cov: Dict[str, Dict[str, Any]] = {}
    per_dir: List[Dict[str, Any]] = []

    for name in dirs:
        full = os.path.join(out_root, name)
        recs = read_jsonl(os.path.join(full, "metadata.jsonl"))
        pdfs = pdf_basenames(full)
        meta_succ = 0
        real_succ = 0
        dir_dois: Set[str] = set()          # 本批去重后的唯一 DOI(≈输入数)
        dir_real: Set[str] = set()          # 本批去重唯一真实成功(pdf 落盘;受 cleanup 移错论文影响)
        dir_meta: Set[str] = set()          # 本批去重唯一 metadata 声称成功(cleanup 不改 metadata → 稳定)
        for r in recs:
            doi = norm_doi(r)
            if not doi:
                continue
            claimed = bool(r.get("success"))
            bn = basename_of(r.get("pdf_path"))
            real = bool(claimed and bn and bn in pdfs)
            if claimed:
                meta_succ += 1
            if real:
                real_succ += 1
            dir_dois.add(doi)
            if real:
                dir_real.add(doi)
            if claimed:
                dir_meta.add(doi)

            e = cov.get(doi)
            if e is None:
                e = cov[doi] = {
                    "doi": doi, "status": "miss",
                    "source": None, "pdf_path": None, "pdf_bytes": 0, "batch": None,
                    "title": r.get("title"), "error": None,
                    "seen_in": [], "n_records": 0, "claimed_success_but_no_pdf": False,
                    "qc": None,
                }
            e["n_records"] += 1
            if name not in e["seen_in"]:
                e["seen_in"].append(name)
            if r.get("title") and not e["title"]:
                e["title"] = r.get("title")

            if real:
                pb = int(r.get("pdf_bytes") or 0)
                if e["status"] != "success" or pb > int(e["pdf_bytes"] or 0):
                    e["status"] = "success"
                    e["source"] = r.get("source_used")
                    e["pdf_path"] = (r.get("pdf_path") or "").replace("\\", "/")
                    e["pdf_bytes"] = pb
                    e["batch"] = name
                    e["error"] = None
            else:
                if claimed:  # 声称成功却盘上无文件:标记(可复下),不计成功
                    e["claimed_success_but_no_pdf"] = True
                if e["status"] != "success":  # 仍缺:error 取末次(最近一批、行内最后)
                    e["error"] = (_NO_PDF_ERROR if claimed else (r.get("error") or "unknown"))
                    e["batch"] = name

        per_dir.append({
            "batch": name,
            "scan_level": "flat" if "/" not in name else "nested",  # 口径治理:每条标 flat/nested 来源,防数字互污
            "is_core_batch": is_core_batch(name),
            "unique_dois": len(dir_dois),                   # 本批去重唯一 DOI(≈该批输入数)
            "unique_real_success": len(dir_real),           # 去重唯一真实成功(pdf 落盘)
            "unique_metadata_success": len(dir_meta),       # 去重唯一 metadata 成功(cleanup 不改 → 稳定复现审计)
            "metadata_lines": len(recs),
            "metadata_success_lines": meta_succ,
            "real_success_lines": real_succ,
            "pdf_files_on_disk": len(pdfs),
        })

    records = sorted(cov.values(), key=lambda r: r["doi"])

    # ── QC 剔除:命中审计黑名单的“成功”其实是抓错论文的假成功 → 改判 miss、计入 still_missing ──
    # 白名单已在函数入口从 qc_hard/qc_soft 扣除,故内容QC 核实为真正文者天然不会进入下面的剔除分支。
    success_before_qc = sum(1 for r in records if r["status"] == "success")
    rej_hard = rej_soft = 0
    n_allow_override = 0
    for r in records:
        if r["status"] != "success":
            continue
        d = r["doi"]
        if d in qc_allow:                         # 白名单命中且确为落盘真成功:标记留证、免剔除
            r["qc"] = "allow_override"
            n_allow_override += 1
            continue
        if d in qc_hard:
            kind, rej_hard = "hard_reject", rej_hard + 1
            reason = "qc_hard_reject:wrong-paper(title-mismatch,both-methods)"
        elif d in qc_soft:
            kind, rej_soft = "soft_reject", rej_soft + 1
            reason = "qc_soft_reject:wrong-paper(audit-union)"
        else:
            continue
        r["qc"] = kind
        r["qc_rejected_source"] = r["source"]     # 留证:被判错的那份(供 cleanup/复核交叉引用)
        r["qc_rejected_pdf_path"] = r["pdf_path"]
        r["status"] = "miss"
        r["source"] = None
        r["pdf_path"] = None
        r["pdf_bytes"] = 0
        r["error"] = reason
        r["batch"] = None

    success = [r for r in records if r["status"] == "success"]
    miss = [r for r in records if r["status"] != "success"]
    by_source = Counter(r["source"] or "?" for r in success)
    by_batch = Counter(r["batch"] or "?" for r in success)
    claimed_no_pdf = [r["doi"] for r in miss if r["claimed_success_but_no_pdf"]]
    total = len(records)

    # 交叉核对:逐批(非去重)求和口径。core = 三主语料批。以 metadata 成功求和(cleanup 不改 metadata)
    # 稳定复现审计 866/1213;另给 on_disk 求和(随 cleanup 移除错论文 PDF 而下降)。
    core_in = sum(d["unique_dois"] for d in per_dir if d["is_core_batch"])
    core_ok_meta = sum(d["unique_metadata_success"] for d in per_dir if d["is_core_batch"])
    core_ok_disk = sum(d["unique_real_success"] for d in per_dir if d["is_core_batch"])
    all_in = sum(d["unique_dois"] for d in per_dir)
    all_ok_meta = sum(d["unique_metadata_success"] for d in per_dir)
    all_ok_disk = sum(d["unique_real_success"] for d in per_dir)
    _dedup_pct = (len(success) / total * 100) if total else 0.0

    summary = {
        "total_unique_dois": total,
        "success": len(success),                       # 净成功(已剔除 QC 假成功)
        "miss": len(miss),                             # 含 QC 判错项(已计入 still_missing)
        "success_rate": round(len(success) / total, 4) if total else 0.0,
        "claimed_success_but_no_pdf": len(claimed_no_pdf),
        "qc": {
            "hard_list_dois": len(qc_hard),
            "union_list_dois": len(qc_soft),
            "allow_list_dois": len(qc_allow),
            "success_before_qc": success_before_qc,
            "rejected_hard": rej_hard,
            "rejected_soft": rej_soft,
            "rejected_total": rej_hard + rej_soft,
            "allow_override": n_allow_override,
            "success_after_qc": len(success),
            "success_rate_after_qc": round(len(success) / total, 4) if total else 0.0,
            "note": (
                f"消费审计 QC 黑名单:原始去重成功 {success_before_qc} 剔除抓错论文 "
                f"{rej_hard + rej_soft}(硬黑 {rej_hard} + 软黑 {rej_soft})→ 净成功 {len(success)}。"
                f"白名单免剔 {n_allow_override}(内容QC 核实真正文、纠黑名单假阳)。"
                "被剔除者改判 miss 并进 still_missing(留 qc_rejected_source/pdf 供复核)。"
                if (qc_hard or qc_soft or qc_allow) else "未启用 QC 黑名单(--no-qc 或文件缺失):success 为原始去重口径,可能含抓错论文假成功。"
            ),
        },
        "by_source": dict(by_source.most_common()),
        "by_success_batch": dict(by_batch.most_common()),
        "crosscheck_per_batch_sum": {
            "core_batches_inputs": core_in,                     # ≈1213(batch4 500 + batch6 500 + batch7 213)
            "core_batches_success_metadata": core_ok_meta,      # ≈866:metadata 逐批求和,复现审计(稳定)
            "core_batches_success_on_disk": core_ok_disk,       # 落盘实证求和(随 cleanup 移错论文 PDF 下降)
            "core_batches_rate_metadata": round(core_ok_meta / core_in, 4) if core_in else 0.0,
            "all_batches_inputs": all_in,
            "all_batches_success_metadata": all_ok_meta,
            "all_batches_success_on_disk": all_ok_disk,
            "note": (
                "逐批求和为**原始(未去重、未 QC)**口径。core 三主语料批的 metadata 成功求和"
                f"={core_ok_meta}/{core_in} 复现审计 866/1213≈71.4%(cleanup 只移 PDF 不改 metadata,故稳定);"
                f"其落盘实证求和={core_ok_disk}(随 cleanup 移除错论文 PDF 下降)。真实『唯一正确论文』净覆盖"
                f"(去重 + pdf 落盘 + 剔 QC 抓错)={len(success)}/{total}≈{_dedup_pct:.1f}%。"
                "差额 = 跨批重复(batch7 多为 batch6 已成功项的重跑)+ 抓错论文假成功(websearch 为主)。"
            ),
        },
    }
    return {
        "generated_ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "out_root": out_root,
        "caliber": ("success = metadata.success AND pdf 文件名存在于 <batch>/pdfs/(不信 summary.json);"
                    "跨批 success 并集(取 pdf_bytes 最大)、miss 取末次原因"),
        "scanned_dirs": per_dir,
        "summary": summary,
        "records": records,
        "_claimed_no_pdf_dois": sorted(claimed_no_pdf),
    }


def still_missing_dois(result: Dict[str, Any]) -> List[str]:
    return sorted(r["doi"] for r in result["records"] if r["status"] != "success")


def write_outputs(result: Dict[str, Any], coverage_json: str, missing_txt: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(coverage_json)) or ".", exist_ok=True)
    with open(coverage_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    miss = still_missing_dois(result)
    os.makedirs(os.path.dirname(os.path.abspath(missing_txt)) or ".", exist_ok=True)
    with open(missing_txt, "w", encoding="utf-8") as f:
        f.write("# still_missing DOIs: %d 条 | 生成 %s\n" % (len(miss), result["generated_ts"]))
        f.write("# 口径: metadata.success AND pdf 落盘;可直接作 fulltext_fetcher -f 输入(# 行会被跳过)\n")
        for d in miss:
            f.write(d + "\n")


def run_coverage(out_root: str = OUT_DIR,
                 *,
                 use_qc: bool = True,
                 qc_hard_path: Optional[str] = None,
                 qc_soft_path: Optional[str] = None,
                 qc_manifest_path: Optional[str] = None,
                 qc_uncertain_path: Optional[str] = None,
                 qc_extra_reject_paths: Optional[Iterable[str]] = None,
                 qc_allow_paths: Optional[Iterable[str]] = None,
                 include_nested: bool = False,
                 exclude_substrings: Tuple[str, ...] = _NESTED_EXCLUDE_SUBSTR,
                 extra_dirs: Optional[Iterable[str]] = None,
                 write: bool = True,
                 coverage_json: Optional[str] = None,
                 missing_txt: Optional[str] = None) -> Dict[str, Any]:
    """run_all 可直接 import 调用的**一站式入口**(与 CLI 共享同一实现,全组唯一权威口径)。

    流程:加载审计 QC 黑名单(默认 <out_root>/qc_merge_highconf_wrong.csv、
    <out_root>/qc_merge_union_wrong.csv 与 <out_root>/qc_uncertain_reject.csv)→ 扫描 out_root
    各批去重聚合 → 剔除抓错论文出净口径 →
    (可选)落盘 coverage.json / still_missing.txt → 返回结果 dict。**静默、无副作用打印**,便于被编排。

    参数:
        out_root      扫描根目录(默认 "out")。
        use_qc        是否消费 QC 黑名单剔错论文(默认 True;False=原始去重口径)。
        qc_hard_path/qc_soft_path/qc_uncertain_path  覆盖默认 QC CSV 路径。
        qc_extra_reject_paths  追加拒收 DOI 清单(并入 union;供下游内容QC 补漏,如 -145 的
                      rerun_acs_144_deduct_dois_145.txt 里生产门漏判的 SI/错文件)。
        qc_allow_paths  白名单 DOI 清单(免剔,纠黑名单假阳;内容QC 已核实真正文者)。优先级最高。
        write         是否落盘产物(默认 True)。
        coverage_json/missing_txt  覆盖默认输出路径。

    返回:build() 的结果 dict。关键字段:
        result["summary"]["total_unique_dois" | "success"(净) | "miss" | "success_rate" | "qc" | ...]
        result["records"](按 DOI 排序的规范状态列表)
        result["_qc_paths"](本次用的 QC 路径与是否存在)
        result["_written"](落盘时的输出路径;write=False 时无此键)
    """
    qc_hard: Set[str] = set()
    qc_soft: Set[str] = set()
    qc_allow: Set[str] = set()
    hp = sp = mp = up = None
    if use_qc:
        hp = qc_hard_path or os.path.join(out_root, "qc_merge_highconf_wrong.csv")
        sp = qc_soft_path or os.path.join(out_root, "qc_merge_union_wrong.csv")
        mp = qc_manifest_path or os.path.join(out_root, "qc_rejected_manifest.csv")
        up = qc_uncertain_path or os.path.join(out_root, "qc_uncertain_reject.csv")
        qc_hard, qc_soft = resolve_qc_sets(out_root, hp, sp, mp, up)
        qc_soft |= read_doi_lists(qc_extra_reject_paths)   # 追加拒收(内容QC 补漏)并入 union
        qc_allow = read_doi_lists(qc_allow_paths)           # 白名单(纠假阳),build 内优先级最高

    result = build(out_root, qc_hard=qc_hard, qc_soft=qc_soft, qc_allow=qc_allow,
                   include_nested=include_nested, exclude_substrings=exclude_substrings,
                   extra_dirs=extra_dirs)
    _sd = result["scanned_dirs"]
    result["_scan"] = {"include_nested": include_nested,
                       "exclude_substrings": list(exclude_substrings),
                       "extra_dirs": list(extra_dirs or []),
                       "caliber": "authoritative(flat-only)" if not include_nested and not (extra_dirs or [])
                                  else "experimental(nested/extra-dirs·须过QC门方可权威回写)",
                       "n_flat_dirs": sum(1 for d in _sd if d.get("scan_level") == "flat"),
                       "n_nested_dirs": sum(1 for d in _sd if d.get("scan_level") == "nested")}
    result["_qc_paths"] = {
        "used": bool(use_qc),
        "hard": hp, "hard_exists": bool(hp and os.path.isfile(hp)),
        "soft": sp, "soft_exists": bool(sp and os.path.isfile(sp)),
        "manifest": mp, "manifest_exists": bool(mp and os.path.isfile(mp)),
        "uncertain": up, "uncertain_exists": bool(up and os.path.isfile(up)),
        "extra_reject": list(qc_extra_reject_paths or []),
        "allow": list(qc_allow_paths or []),
        "allow_dois": sorted(qc_allow),
    }
    if write:
        cj = coverage_json or os.path.join(out_root, "coverage.json")
        mt = missing_txt or os.path.join(out_root, "still_missing.txt")
        write_outputs(result, cj, mt)
        result["_written"] = {"coverage_json": cj, "missing_txt": mt}
    return result


def _print_human(result: Dict[str, Any]) -> None:
    s = result["summary"]
    print("=" * 76)
    print("跨批 coverage 主库  (out_root=%s, 生成 %s)" % (result["out_root"], result["generated_ts"]))
    print("-" * 76)
    print("%-26s%12s%12s%10s%9s" % ("batch", "meta_lines", "meta_succ", "real", "pdfs"))
    for ps in result["scanned_dirs"]:
        print("%-26s%12d%12d%10d%9d" % (
            ps["batch"][:26], ps["metadata_lines"], ps["metadata_success_lines"],
            ps["real_success_lines"], ps["pdf_files_on_disk"]))
    print("-" * 76)
    q = s["qc"]
    print("去重主库(净·已剔 QC 抓错): 唯一 DOI %d | 净成功 %d | 仍缺 %d | 净成功率 %.1f%%  (声称成功无pdf %d)" % (
        s["total_unique_dois"], s["success"], s["miss"], s["success_rate"] * 100,
        s["claimed_success_but_no_pdf"]))
    print("QC 剔除: 原始成功 %d → 剔除抓错 %d(硬 %d+软 %d)→ 净成功 %d%s" % (
        q["success_before_qc"], q["rejected_total"], q["rejected_hard"], q["rejected_soft"],
        q["success_after_qc"],
        ("  [白名单免剔 %d]" % q["allow_override"]) if q.get("allow_override") else ""))
    cc = s["crosscheck_per_batch_sum"]
    print("交叉核对(逐批求和): core metadata %d/%d = %.1f%%(复现审计) | core 落盘 %d | all metadata %d" % (
        cc["core_batches_success_metadata"], cc["core_batches_inputs"],
        cc["core_batches_rate_metadata"] * 100,
        cc["core_batches_success_on_disk"], cc["all_batches_success_metadata"]))
    top = ", ".join(f"{k}={v}" for k, v in list(s["by_source"].items())[:6]) or "无"
    print("主力成功源: " + top)
    print("=" * 76)


def main(argv: Optional[List[str]] = None) -> int:
    _force_utf8_console()
    ap = argparse.ArgumentParser(
        description="跨批 coverage/still_missing 主库(纯读 out/,去重 union 真实成功)。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--out-root", default=OUT_DIR, help="扫描根目录(默认 out)")
    ap.add_argument("--coverage-json", default=None,
                    help="coverage 输出路径(默认 <out-root>/coverage.json)")
    ap.add_argument("--missing-txt", default=None,
                    help="still_missing 输出路径(默认 <out-root>/still_missing.txt)")
    ap.add_argument("--qc-hard", default=None,
                    help="QC 硬黑名单 CSV(默认 <out-root>/qc_merge_highconf_wrong.csv)")
    ap.add_argument("--qc-soft", default=None,
                    help="QC 并集黑名单 CSV(默认 <out-root>/qc_merge_union_wrong.csv)")
    ap.add_argument("--qc-manifest", default=None,
                    help="cleanup 物理归置清单 CSV(默认 <out-root>/qc_rejected_manifest.csv;地面真相冗余源)")
    ap.add_argument("--qc-uncertain", default=None,
                    help="uncertain 拒收清单 CSV(默认 <out-root>/qc_uncertain_reject.csv;153 抽样 40/40 全错 → 整池并入 union)")
    ap.add_argument("--no-qc", action="store_true",
                    help="不消费 QC 黑名单(success 为原始去重口径,可能含抓错论文假成功)")
    ap.add_argument("--nested", action="store_true",
                    help="显式开启二级+ 嵌套扫描(默认关闭=只扫一级权威口径);开启会递归收录 "
                         "out/<dir>/fetch/metadata.jsonl 等嵌套产出(剔 demo/smoke 夹具)。"
                         "实验口径,权威回写前须经 QC 门。")
    ap.add_argument("--extra-dirs", default=None,
                    help="逗号分隔的相对目录,强制纳入(绕过 demo/smoke 排除、无视 --nested),如 "
                         "rerun_acs_144/fetch,rerun_elsevier_143/fetch")
    ap.add_argument("--qc-extra-reject", default=None,
                    help="逗号分隔的追加拒收 DOI 清单文件(并入 union,补生产门漏判),如 "
                         "out/rerun_acs_144_deduct_dois_145.txt")
    ap.add_argument("--qc-allow", default=None,
                    help="逗号分隔的白名单 DOI 清单文件(免剔、纠黑名单假阳;内容QC 已核实真正文者)")
    ap.add_argument("--no-write", action="store_true", help="只打印汇总,不落盘")
    ap.add_argument("--print-json", action="store_true",
                    help="stdout 输出 summary 的 JSON(供 run_all/父程序按 utf-8 解析接入)")
    ap.add_argument("--selftest", action="store_true", help="离线自检后退出")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    extra_dirs = [d.strip() for d in (args.extra_dirs or "").split(",") if d.strip()]
    extra_reject = [d.strip() for d in (args.qc_extra_reject or "").split(",") if d.strip()]
    allow_paths = [d.strip() for d in (args.qc_allow or "").split(",") if d.strip()]

    # CLI 与 import 共享同一实现(run_coverage),确保全组只有一个『黑名单感知』权威口径、不分叉。
    result = run_coverage(
        args.out_root,
        use_qc=not args.no_qc,
        qc_hard_path=args.qc_hard,
        qc_soft_path=args.qc_soft,
        qc_manifest_path=args.qc_manifest,
        qc_uncertain_path=args.qc_uncertain,
        qc_extra_reject_paths=extra_reject or None,
        qc_allow_paths=allow_paths or None,
        include_nested=args.nested,
        extra_dirs=extra_dirs or None,
        write=not args.no_write,
        coverage_json=args.coverage_json,
        missing_txt=args.missing_txt,
    )

    if args.print_json:
        payload = {"summary": result["summary"],
                   "qc_paths": result.get("_qc_paths"),
                   "written": result.get("_written")}
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        except AttributeError:
            sys.stdout.write(data.decode("utf-8"))
        return 0

    sc = result.get("_scan") or {}
    nested_dirs = [d["batch"] for d in result["scanned_dirs"] if "/" in d["batch"]]
    print("扫描模式: %s | 嵌套目录 %d 个%s%s" % (
        "含嵌套(--nested·实验口径)" if sc.get("include_nested") else "仅一级(权威口径·默认)",
        len(nested_dirs),
        ("  [" + ", ".join(nested_dirs[:8]) + ("…" if len(nested_dirs) > 8 else "") + "]") if nested_dirs else "",
        ("  强制纳入:" + ",".join(sc.get("extra_dirs") or [])) if sc.get("extra_dirs") else ""))

    qp = result.get("_qc_paths") or {}
    if qp.get("used"):
        q = result["summary"]["qc"]
        print("QC 排除源(并集): 硬黑 %d | 并集 %d DOI  [csv-hard%s csv-union%s manifest%s uncertain%s]" % (
            q["hard_list_dois"], q["union_list_dois"],
            "" if qp.get("hard_exists") else "缺失", "" if qp.get("soft_exists") else "缺失",
            "" if qp.get("manifest_exists") else "缺失", "" if qp.get("uncertain_exists") else "缺失"))
    _print_human(result)

    w = result.get("_written")
    if w:
        print("已写出: %s  (%d 条记录)" % (w["coverage_json"], result["summary"]["total_unique_dois"]))
        print("已写出: %s  (%d 条仍缺)" % (w["missing_txt"], result["summary"]["miss"]))
    return 0


# ── 离线自检(不联网、不读项目文件;临时造多批 out 目录验证聚合口径)──────────────
def _selftest() -> int:
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="build_coverage_selftest_")
    try:
        root = os.path.join(tmp, "out")
        a = os.path.join(root, "batchA")
        b = os.path.join(root, "batchB")
        os.makedirs(os.path.join(a, "pdfs"))
        os.makedirs(os.path.join(b, "pdfs"))

        def rec(doi, success, source=None, pdf=None, pbytes=0, error=None, title=None):
            return json.dumps({
                "raw_input": doi, "doi": doi, "title": title,
                "success": success, "source_used": source,
                "pdf_path": pdf, "pdf_bytes": pbytes, "error": error,
            }) + "\n"

        # batchA(较旧):d1 真成功(websearch,1000)、d2 miss、d3 真成功(websearch,1500)、
        #               d4 miss(旧因)、d5 声称成功但无文件
        with open(os.path.join(a, "metadata.jsonl"), "w", encoding="utf-8") as f:
            f.write(rec("10.1000/d1", True, "websearch", "out/batchA/pdfs/d1.pdf", 1000, title="P1"))
            f.write(rec("10.1000/d2", False, error="no-candidates"))
            f.write(rec("10.1000/d3", True, "websearch", "out/batchA/pdfs/d3.pdf", 1500))
            f.write(rec("10.1000/d4", False, error="old-timeout"))
            f.write(rec("10.1000/d5", True, "unpaywall", "out/batchA/pdfs/d5.pdf", 900))  # 无文件
        open(os.path.join(a, "pdfs", "d1.pdf"), "w").close()
        open(os.path.join(a, "pdfs", "d3.pdf"), "w").close()
        # 注意:d5.pdf 故意不创建

        # batchB(较新):d1 真成功(unpaywall,3000→更大,应覆盖)、d2 真成功(core,2000→晚批回收)、
        #               d3 miss(回退,应被 union 忽略)、d4 miss(新因,取末次)
        with open(os.path.join(b, "metadata.jsonl"), "w", encoding="utf-8") as f:
            f.write(rec("10.1000/d1", True, "unpaywall", "out/batchB/pdfs/d1.pdf", 3000))
            f.write(rec("10.1000/d2", True, "core", "out/batchB/pdfs/d2.pdf", 2000))
            f.write(rec("10.1000/d3", False, error="regressed-403"))
            f.write(rec("10.1000/d4", False, error="cloudflare-challenge(http-403)"))
        open(os.path.join(b, "pdfs", "d1.pdf"), "w").close()
        open(os.path.join(b, "pdfs", "d2.pdf"), "w").close()

        # mtime:A 旧、B 新 → “取末次”=B
        os.utime(os.path.join(a, "metadata.jsonl"), (1_000_000, 1_000_000))
        os.utime(os.path.join(b, "metadata.jsonl"), (1_000_100, 1_000_100))

        res = build(root)
        s = res["summary"]
        by_doi = {r["doi"]: r for r in res["records"]}

        # 规模:5 唯一 DOI,3 成功(d1/d2/d3),2 仍缺(d4/d5)
        assert s["total_unique_dois"] == 5, s
        assert s["success"] == 3, s
        assert s["miss"] == 2, s
        assert abs(s["success_rate"] - 0.6) < 1e-9, s

        # d1:跨批并集取更大 pdf_bytes → unpaywall/3000/batchB
        assert by_doi["10.1000/d1"]["status"] == "success", by_doi["10.1000/d1"]
        assert by_doi["10.1000/d1"]["source"] == "unpaywall", by_doi["10.1000/d1"]
        assert by_doi["10.1000/d1"]["pdf_bytes"] == 3000, by_doi["10.1000/d1"]
        assert by_doi["10.1000/d1"]["batch"] == "batchB", by_doi["10.1000/d1"]
        # d2:晚批才真成功 → core
        assert by_doi["10.1000/d2"]["status"] == "success", by_doi["10.1000/d2"]
        assert by_doi["10.1000/d2"]["source"] == "core", by_doi["10.1000/d2"]
        # d3:早批成功、晚批回退 → 仍成功(union),源保留 websearch
        assert by_doi["10.1000/d3"]["status"] == "success", by_doi["10.1000/d3"]
        assert by_doi["10.1000/d3"]["source"] == "websearch", by_doi["10.1000/d3"]
        # d4:两批皆 miss,error 取末次(B 的 cloudflare)
        assert by_doi["10.1000/d4"]["status"] == "miss", by_doi["10.1000/d4"]
        assert by_doi["10.1000/d4"]["error"] == "cloudflare-challenge(http-403)", by_doi["10.1000/d4"]
        # d5:声称成功但盘上无文件 → 不计成功、打标、合成 error
        assert by_doi["10.1000/d5"]["status"] == "miss", by_doi["10.1000/d5"]
        assert by_doi["10.1000/d5"]["claimed_success_but_no_pdf"] is True, by_doi["10.1000/d5"]
        assert by_doi["10.1000/d5"]["error"] == _NO_PDF_ERROR, by_doi["10.1000/d5"]
        assert s["claimed_success_but_no_pdf"] == 1, s

        # by_source:每源各 1
        assert res["summary"]["by_source"] == {"unpaywall": 1, "core": 1, "websearch": 1}, s

        # 交叉核对:两批都非 core(batchA/batchB),故 core 求和=0;all 求和=各批唯一成功之和=3+2=5,
        #           而去重主库=3 → 差额 2 即跨批重复(d1/d3 在两批都出现)。
        cc = res["summary"]["crosscheck_per_batch_sum"]
        assert cc["core_batches_inputs"] == 0, cc
        assert cc["core_batches_success_metadata"] == 0 and cc["core_batches_success_on_disk"] == 0, cc
        assert cc["all_batches_inputs"] == 5 + 4, cc          # A 唯一DOI5 + B 唯一DOI4
        assert cc["all_batches_success_metadata"] == 3 + 2, cc  # metadata: A{d1,d3,d5}=3, B{d1,d2}=2
        assert cc["all_batches_success_on_disk"] == 2 + 2, cc   # 落盘: A{d1,d3}=2, B{d1,d2}=2
        pa = {d["batch"]: d for d in res["scanned_dirs"]}
        assert pa["batchA"]["unique_dois"] == 5 and pa["batchA"]["unique_real_success"] == 2, pa["batchA"]
        assert pa["batchA"]["unique_metadata_success"] == 3, pa["batchA"]
        assert pa["batchB"]["unique_dois"] == 4 and pa["batchB"]["unique_real_success"] == 2, pa["batchB"]
        assert pa["batchB"]["unique_metadata_success"] == 2, pa["batchB"]
        assert is_core_batch("batch4_p3") and is_core_batch("batch6") and is_core_batch("batch7")
        assert not is_core_batch("recover_b6_tail") and not is_core_batch("batch7_reprobe_149")

        # 未启用 QC:qc 块应显示 0 剔除、净=原始
        assert res["summary"]["qc"]["rejected_total"] == 0, res["summary"]["qc"]
        assert res["summary"]["qc"]["success_before_qc"] == 3, res["summary"]["qc"]
        assert res["summary"]["qc"]["success_after_qc"] == 3, res["summary"]["qc"]

        # still_missing:排序、恰为 d4/d5,且不含任何成功项
        miss = still_missing_dois(res)
        assert miss == ["10.1000/d4", "10.1000/d5"], miss

        # 落盘产物可用:coverage.json 可解析、still_missing.txt 过滤 # 头后 = miss 集
        cj = os.path.join(tmp, "coverage.json")
        mtxt = os.path.join(tmp, "still_missing.txt")
        write_outputs(res, cj, mtxt)
        with open(cj, "r", encoding="utf-8") as f:
            reloaded = json.load(f)
        assert reloaded["summary"]["success"] == 3, reloaded["summary"]
        with open(mtxt, "r", encoding="utf-8") as f:
            body = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        assert body == ["10.1000/d4", "10.1000/d5"], body

        # ── QC 消费:d3 硬黑、d1 软黑(并集含 d1/d3)→ 二者从 success 剔除、改判 miss 进 still_missing ──
        resq = build(root, qc_hard={"10.1000/d3"}, qc_soft={"10.1000/d1", "10.1000/d3"})
        sq = resq["summary"]
        bq = {r["doi"]: r for r in resq["records"]}
        assert sq["success"] == 1 and sq["miss"] == 4, sq                 # 仅 d2 净成功
        assert abs(sq["success_rate"] - 0.2) < 1e-9, sq
        assert sq["qc"]["success_before_qc"] == 3, sq["qc"]
        assert sq["qc"]["rejected_hard"] == 1 and sq["qc"]["rejected_soft"] == 1, sq["qc"]
        assert sq["qc"]["rejected_total"] == 2 and sq["qc"]["success_after_qc"] == 1, sq["qc"]
        assert bq["10.1000/d3"]["status"] == "miss" and bq["10.1000/d3"]["qc"] == "hard_reject", bq["10.1000/d3"]
        assert bq["10.1000/d3"]["qc_rejected_source"] == "websearch", bq["10.1000/d3"]
        assert "qc_hard_reject" in (bq["10.1000/d3"]["error"] or ""), bq["10.1000/d3"]
        assert bq["10.1000/d1"]["status"] == "miss" and bq["10.1000/d1"]["qc"] == "soft_reject", bq["10.1000/d1"]
        assert bq["10.1000/d2"]["status"] == "success" and bq["10.1000/d2"]["qc"] is None, bq["10.1000/d2"]
        assert sq["by_source"] == {"core": 1}, sq
        assert still_missing_dois(resq) == [
            "10.1000/d1", "10.1000/d3", "10.1000/d4", "10.1000/d5"], still_missing_dois(resq)

        # read_qc_dois:能从带表头 CSV 读出规范化 doi(大小写/前缀归一)
        qc_csv = os.path.join(tmp, "qc.csv")
        with open(qc_csv, "w", encoding="utf-8") as f:
            f.write("batch,doi,verdict_151\n")
            f.write("batchA,https://doi.org/10.1000/D3,mismatch\n")
            f.write("batchB,10.1000/d1,mismatch\n")
        assert read_qc_dois(qc_csv) == {"10.1000/d3", "10.1000/d1"}, read_qc_dois(qc_csv)
        assert read_qc_dois(os.path.join(tmp, "nope.csv")) == set()

        # read_qc_manifest:按 source 列分 hard/soft(大小写归一);缺失→(空,空)
        man_csv = os.path.join(tmp, "manifest.csv")
        with open(man_csv, "w", encoding="utf-8-sig") as f:
            f.write("doi,batch,source,status,orig_path,new_path\n")
            f.write("10.1000/d3,batchA,hard,already_moved,a,b\n")
            f.write("10.1000/dX,batchB,soft,moved,a,b\n")
        mh, ms = read_qc_manifest(man_csv)
        assert mh == {"10.1000/d3"} and ms == {"10.1000/dx"}, (mh, ms)
        assert read_qc_manifest(os.path.join(tmp, "nope.csv")) == (set(), set())
        # resolve_qc_sets:并集 CSV(hard/union)+ manifest(hard/soft)
        rh, rs = resolve_qc_sets(tmp, hard_path=qc_csv, soft_path=qc_csv, manifest_path=man_csv)
        assert "10.1000/d3" in rh, rh
        assert {"10.1000/d1", "10.1000/d3", "10.1000/dx"} <= rs, rs

        # uncertain 拒收清单:并入 soft/union(不进 hard);缺失时优雅降级(上面 rs 未含 dU)
        assert "10.1000/du" not in rs, rs
        unc_csv = os.path.join(tmp, "qc_uncertain_reject.csv")
        with open(unc_csv, "w", encoding="utf-8") as f:
            f.write("batch,doi,verdict_151,title_score,pdf_url,pdf_path,reason\n")
            f.write("batchA,10.1000/dU,uncertain(borderline),58.2,u,p,uncertain_sampled_wrong\n")
        rh2, rs2 = resolve_qc_sets(tmp, hard_path=qc_csv, soft_path=qc_csv,
                                   manifest_path=man_csv, uncertain_path=unc_csv)
        assert "10.1000/du" in rs2 and "10.1000/du" not in rh2, (rh2, rs2)

        # run_coverage(一站式 API·供 run_all import):从 CSV 加载 QC、write=False → 返回净口径、无 _written
        rc = run_coverage(root, use_qc=True, qc_hard_path=qc_csv, qc_soft_path=qc_csv, write=False)
        assert rc["summary"]["qc"]["rejected_total"] == 2, rc["summary"]["qc"]   # d1+d3 命中黑名单
        assert rc["summary"]["success"] == 1, rc["summary"]                       # 仅 d2 净成功
        assert rc["_qc_paths"]["used"] is True and rc["_qc_paths"]["hard_exists"] is True, rc["_qc_paths"]
        assert "_written" not in rc, list(rc.keys())
        # use_qc=False → 不剔除,净=原始 3
        rc2 = run_coverage(root, use_qc=False, write=False)
        assert rc2["summary"]["success"] == 3 and rc2["summary"]["qc"]["rejected_total"] == 0, rc2["summary"]
        # write=True → 落盘并回传路径
        rc3 = run_coverage(root, use_qc=False, write=True,
                           coverage_json=os.path.join(tmp, "c2.json"),
                           missing_txt=os.path.join(tmp, "m2.txt"))
        assert os.path.isfile(rc3["_written"]["coverage_json"]), rc3.get("_written")
        assert os.path.isfile(rc3["_written"]["missing_txt"]), rc3.get("_written")

        # 空目录稳健:不存在的 out_root 返回 0 记录、不抛错
        empty = build(os.path.join(tmp, "nope"))
        assert empty["summary"]["total_unique_dois"] == 0, empty["summary"]

        # ── 嵌套扫描(修 -149 盲区):run_all 自带二级 <dir>/fetch/metadata.jsonl 必须被收录 ──
        # 造一个 rerun 生产目录(二级 fetch,含真实回收 d4 → 应把 d4 从 miss 翻成 success),
        # 一个 demo 夹具(二级 fetch,含语料外 dNEW → 默认必须被剔除,不得污染 total/success)。
        rr = os.path.join(root, "rerun_x_144", "fetch")
        os.makedirs(os.path.join(rr, "pdfs"))
        with open(os.path.join(rr, "metadata.jsonl"), "w", encoding="utf-8") as f:
            f.write(rec("10.1000/d4", True, "publisher_oa", "out/rerun_x_144/fetch/pdfs/d4.pdf", 4096))
        open(os.path.join(rr, "pdfs", "d4.pdf"), "w").close()
        os.utime(os.path.join(rr, "metadata.jsonl"), (1_000_200, 1_000_200))  # 最新 → 排在末尾

        demo = os.path.join(root, "run_all_demo_zzz", "fetch")
        os.makedirs(os.path.join(demo, "pdfs"))
        with open(os.path.join(demo, "metadata.jsonl"), "w", encoding="utf-8") as f:
            f.write(rec("10.1000/dNEW", True, "arxiv", "out/run_all_demo_zzz/fetch/pdfs/dnew.pdf", 5000))
        open(os.path.join(demo, "pdfs", "dnew.pdf"), "w").close()

        smoke = os.path.join(root, "smoke999", "fetch")
        os.makedirs(os.path.join(smoke, "pdfs"))
        with open(os.path.join(smoke, "metadata.jsonl"), "w", encoding="utf-8") as f:
            f.write(rec("10.1000/dSMOKE", True, "smoke", "out/smoke999/fetch/pdfs/ds.pdf", 111))
        open(os.path.join(smoke, "pdfs", "ds.pdf"), "w").close()

        # 显式开启嵌套(剔 demo/smoke):d4 从 miss 翻成 success;dNEW/dSMOKE 语料外 → 不得进入
        rn = build(root, include_nested=True)
        bn = {r["doi"]: r for r in rn["records"]}
        assert bn["10.1000/d4"]["status"] == "success", bn["10.1000/d4"]        # 二级 fetch 被收录
        assert bn["10.1000/d4"]["source"] == "publisher_oa", bn["10.1000/d4"]
        assert bn["10.1000/d4"]["batch"] == "rerun_x_144/fetch", bn["10.1000/d4"]  # 相对路径正斜杠归一
        assert "10.1000/dnew" not in bn, "demo 夹具泄漏进语料"                     # demo 被剔除
        assert "10.1000/dsmoke" not in bn, "smoke 夹具泄漏进语料"                  # smoke 被剔除
        assert rn["summary"]["total_unique_dois"] == 5, rn["summary"]           # 仍是 d1..d5,未被夹具污染
        assert rn["summary"]["success"] == 4, rn["summary"]                     # 原 3 + d4 回收

        # 默认 include_nested=False(权威口径·总指挥定):只扫一级,d4 仍是 miss、总数口径不含任何二级
        ro = build(root)
        bo = {r["doi"]: r for r in ro["records"]}
        assert bo["10.1000/d4"]["status"] == "miss", bo["10.1000/d4"]
        assert ro["summary"]["success"] == 3, ro["summary"]
        nested_names = [d["batch"] for d in ro["scanned_dirs"] if "/" in d["batch"]]
        assert nested_names == [], nested_names

        # extra_dirs:显式强制纳入被排除的 demo 夹具(绕过 exclude、且无视 include_nested)→ dNEW 进入
        re_ = build(root, extra_dirs=["run_all_demo_zzz/fetch"])   # 注意:默认 nested=False 仍能靠 extra_dirs 纳入
        bre = {r["doi"]: r for r in re_["records"]}
        assert "10.1000/dnew" in bre, "extra_dirs 未能强制纳入被排除目录"
        assert "10.1000/dsmoke" not in bre, bre  # 未圈定的 smoke 仍被剔除
        # list_batch_dirs 直接自测:开启 nested 时 mtime 升序、正斜杠、一级+二级都在、demo/smoke 剔除
        ld = list_batch_dirs(root, include_nested=True)
        assert "rerun_x_144/fetch" in ld and ld[-1] == "rerun_x_144/fetch", ld  # 最新排末尾
        assert "batchA" in ld and "batchB" in ld, ld
        assert all("demo" not in x and "smoke" not in x for x in ld), ld
        # 默认(nested 关):只回一级
        assert list_batch_dirs(root) == ["batchA", "batchB"], list_batch_dirs(root)
        # extra_dirs 无视 nested 开关:即便 nested 关,也能定向纳入指定二级目录
        assert "rerun_x_144/fetch" in list_batch_dirs(root, extra_dirs=["rerun_x_144/fetch"]), \
            list_batch_dirs(root, extra_dirs=["rerun_x_144/fetch"])

        # ── 白名单/追加拒收(纠 QC 假阳/补漏,供下游内容QC 成员产物驱动回写)──
        # d1(真成功)本被硬黑;白名单免剔 → 回到 success。d2(真成功)经 extra-reject 追加拒收 → miss。
        ra = build(root, qc_hard={"10.1000/d1"}, qc_soft={"10.1000/d1"},
                   qc_allow={"10.1000/d1"})
        ba = {r["doi"]: r for r in ra["records"]}
        assert ba["10.1000/d1"]["status"] == "success", ba["10.1000/d1"]      # 白名单免死
        assert ba["10.1000/d1"]["qc"] == "allow_override", ba["10.1000/d1"]
        assert ra["summary"]["qc"]["allow_override"] == 1, ra["summary"]["qc"]
        assert ra["summary"]["qc"]["rejected_total"] == 0, ra["summary"]["qc"]  # 唯一黑名单项被白名单救回
        # 白名单不凭空造成功:d_ghost 不是落盘真成功,列白名单也不出现在 success
        rg = build(root, qc_allow={"10.1000/dghost"})
        assert "10.1000/dghost" not in {r["doi"] for r in rg["records"] if r["status"] == "success"}, "白名单不得凭空造成功"

        # read_doi_list:兼容 TSV(doi\t类型)、# 注释、CSV;取首 token 归一
        dl = os.path.join(tmp, "deduct.tsv")
        with open(dl, "w", encoding="utf-8") as f:
            f.write("# comment line\n")
            f.write("10.1000/d2\tSI-only(supporting info)\n")
            f.write("https://doi.org/10.1000/D3 , extra\n")
        assert read_doi_list(dl) == {"10.1000/d2", "10.1000/d3"}, read_doi_list(dl)
        assert read_doi_list(os.path.join(tmp, "nope.tsv")) == set()

        # run_coverage 端到端:extra-reject 追加拒收 d2、allow 救回被黑名单的 d1
        allow_f = os.path.join(tmp, "allow.txt")
        with open(allow_f, "w", encoding="utf-8") as f:
            f.write("10.1000/d1\n")
        # 用一个把 d1/d2 都拉黑的 union csv 作基线,再验证 allow 救 d1、extra-reject 保持 d2 被拒
        union_f = os.path.join(tmp, "union.csv")
        with open(union_f, "w", encoding="utf-8") as f:
            f.write("doi\n10.1000/d1\n")
        rc_a = run_coverage(root, use_qc=True, qc_hard_path=union_f, qc_soft_path=union_f,
                            qc_extra_reject_paths=[dl], qc_allow_paths=[allow_f], write=False)
        bca = {r["doi"]: r for r in rc_a["records"]}
        assert bca["10.1000/d1"]["status"] == "success", bca["10.1000/d1"]     # allow 救回
        assert bca["10.1000/d2"]["status"] == "miss", bca["10.1000/d2"]        # extra-reject 拉黑
        assert rc_a["summary"]["qc"]["allow_override"] == 1, rc_a["summary"]["qc"]
        assert rc_a["_qc_paths"]["allow_dois"] == ["10.1000/d1"], rc_a["_qc_paths"]

        print("COVERAGE_OK")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
