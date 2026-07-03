"""收口：把散落在各历史批次 out/<batch>/pdfs/ 里的已成功 PDF **汇总到单一交付文件夹**，
并按【统一命名规则】`{year}_{author}_{title}_{doi}` 重命名（缺字段优雅降级，与生产管线同源）。

背景：368 份净成功 PDF 分散在 16 个历史批次目录、且多用早期「DOI 净化名」（如 10.1002_x.pdf），
不符合一键正门的默认统一命名。`run_all.py --resume` 只跳过已成功、不回拷历史 PDF，故需本工具做
一次确定性汇总（纯本地文件操作、不联网、不改权威 coverage/黑名单）。

命名复用 `fulltext_fetcher.scholar.naming.build_filename`（与 run_all 默认模板同一实现）：
元数据 title 取自各批 metadata.jsonl（按 DOI 首见），year/author 缺失即空、优雅降级为
`{title}_{doi}`（doi 唯一，天然免撞名）。可选 --enrich 从 Crossref 补 year/author（联网）。

用法：
  python tools/consolidate_delivery.py --coverage out/coverage.json --dest out/_delivery
  python tools/consolidate_delivery.py --selftest      # 离线自检 → CONSOLIDATE_OK
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


class _Paper:
    """build_filename 消费的最小 paper 形态（父包 Paper 的字段子集）。"""
    def __init__(self, doi=None, title=None, year=None, authors=None, journal=None):
        self.doi = doi
        self.title = title
        self.year = year
        self.authors = authors
        self.journal = journal
        self.arxiv_id = None


class _NameCfg:
    def __init__(self, template):
        self.naming_template = template


def load_meta_index(out_root):
    """扫 out_root 下所有 metadata.jsonl，按 DOI 首见收成功记录的元数据（title/year/authors）。"""
    idx = {}
    pattern = os.path.join(out_root, "**", "metadata.jsonl")
    for f in glob.glob(pattern, recursive=True):
        try:
            fh = open(f, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                doi = r.get("doi")
                if doi and doi not in idx:
                    idx[doi] = r
    return idx


def build_plan(coverage_path, out_root, template):
    """产出 [(doi, src_path, new_name)]：仅 status=success 且 pdf_path 存在于盘的记录。"""
    from fulltext_fetcher.scholar.naming import build_filename

    with open(coverage_path, encoding="utf-8") as f:
        cov = json.load(f)
    meta = load_meta_index(out_root)
    cfg = _NameCfg(template)
    taken = set()
    plan = []
    skipped_no_disk = []
    for rec in cov.get("records", []):
        if rec.get("status") != "success":
            continue
        doi = rec.get("doi")
        src = rec.get("pdf_path")
        if not src or not os.path.exists(src):
            skipped_no_disk.append(doi)
            continue
        m = meta.get(doi, {})
        paper = _Paper(
            doi=doi,
            title=m.get("title") or rec.get("title"),
            year=m.get("year"),
            authors=m.get("authors"),
            journal=m.get("venue") or m.get("journal"),
        )
        new_name = build_filename(None, paper, cfg, taken=taken)
        plan.append((doi, src, new_name))
    return plan, skipped_no_disk


def run(coverage_path, dest, template, do_copy=True):
    out_root = os.path.dirname(os.path.abspath(coverage_path)) or "out"
    plan, skipped = build_plan(coverage_path, out_root, template)
    pdf_dir = os.path.join(dest, "pdfs")
    if do_copy:
        os.makedirs(pdf_dir, exist_ok=True)
    names = [n for _, _, n in plan]
    assert len(names) == len(set(names)), "命名撞车（build_filename taken 去重应保证唯一）"
    copied = 0
    manifest_rows = []
    for doi, src, new_name in plan:
        dst = os.path.join(pdf_dir, new_name)
        if do_copy:
            shutil.copy2(src, dst)
            copied += 1
        manifest_rows.append({"doi": doi, "new_name": new_name, "src_path": src})
    if do_copy:
        man_path = os.path.join(dest, "manifest.csv")
        with open(man_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["doi", "new_name", "src_path"])
            w.writeheader()
            w.writerows(manifest_rows)
        # 落盘校验：目录内 PDF 数应 == 计划数
        on_disk = len([n for n in os.listdir(pdf_dir) if n.lower().endswith(".pdf")])
        assert on_disk == len(plan), f"落盘校验失败：磁盘 {on_disk} != 计划 {len(plan)}"
    return {
        "planned": len(plan),
        "copied": copied,
        "skipped_no_disk": len(skipped),
        "dest_pdfs": pdf_dir,
        "template": template,
    }


def _selftest():
    import tempfile
    from fulltext_fetcher.scholar.naming import build_filename

    # 命名规则：year/author 缺失 → 优雅降级为 {title}_{doi}
    cfg = _NameCfg("{year}_{author}_{title}_{doi}")
    n1 = build_filename(None, _Paper(doi="10.1/abc", title="Cool Paper"), cfg, taken=set())
    # year/author 缺失 → 优雅降级为 {title}_{doi}；doi 的 '/' 净化为 '_'（点保留）
    assert n1.endswith(".pdf") and "cool" in n1.lower() and "10.1_abc" in n1.lower(), n1

    with tempfile.TemporaryDirectory() as d:
        # 造 out_root：一个 batch/pdfs + metadata.jsonl + coverage.json
        b = os.path.join(d, "batchX")
        pdfs = os.path.join(b, "pdfs")
        os.makedirs(pdfs)
        p1 = os.path.join(pdfs, "10.1_abc.pdf")
        open(p1, "wb").write(b"%PDF-1.4 test\n%%EOF")
        with open(os.path.join(b, "metadata.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"doi": "10.1/abc", "title": "Cool Paper", "success": True}) + "\n")
        cov = {"records": [
            {"doi": "10.1/abc", "status": "success", "pdf_path": p1},
            {"doi": "10.2/missing", "status": "success", "pdf_path": os.path.join(pdfs, "gone.pdf")},
            {"doi": "10.3/x", "status": "miss", "pdf_path": None},
        ]}
        cov_path = os.path.join(d, "coverage.json")
        json.dump(cov, open(cov_path, "w", encoding="utf-8"))
        dest = os.path.join(d, "_delivery")
        res = run(cov_path, dest, "{year}_{author}_{title}_{doi}", do_copy=True)
        assert res["planned"] == 1, res            # 只有 10.1/abc 落盘可汇总
        assert res["copied"] == 1, res
        assert res["skipped_no_disk"] == 1, res    # 10.2/missing 盘上无文件
        files = os.listdir(os.path.join(dest, "pdfs"))
        assert len(files) == 1 and files[0].endswith(".pdf"), files
        assert os.path.exists(os.path.join(dest, "manifest.csv"))
    print("CONSOLIDATE_OK")
    return 0


def main():
    ap = argparse.ArgumentParser(description="汇总已成功 PDF 到单一文件夹并统一命名")
    ap.add_argument("--coverage", default="out/coverage.json", help="权威 coverage.json 路径")
    ap.add_argument("--dest", default="out/_delivery", help="交付根目录（PDF 落 <dest>/pdfs/）")
    ap.add_argument("--template", default="{year}_{author}_{title}_{doi}",
                    help="统一命名模板（占位符 {year}/{author}/{title}/{doi}/{venue}）")
    ap.add_argument("--dry-run", action="store_true", help="只算计划、不拷贝")
    ap.add_argument("--selftest", action="store_true", help="离线自检 → CONSOLIDATE_OK")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    res = run(args.coverage, args.dest, args.template, do_copy=not args.dry_run)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print(f"\n汇总 {res['copied']}/{res['planned']} 份 → {res['dest_pdfs']}"
          f"（统一命名 {res['template']}；盘上缺失跳过 {res['skipped_no_disk']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
