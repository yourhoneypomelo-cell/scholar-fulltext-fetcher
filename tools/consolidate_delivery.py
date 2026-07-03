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


def _parse_crossref_message(msg):
    """从 Crossref works message 提取 (year, first_author_surname)；缺失位返回 None。纯函数、离线可测。"""
    if not isinstance(msg, dict):
        return None, None
    year = None
    for key in ("published", "issued", "published-print", "published-online"):
        node = msg.get(key)
        if isinstance(node, dict):
            dp = node.get("date-parts")
            if isinstance(dp, list) and dp and isinstance(dp[0], list) and dp[0]:
                try:
                    year = int(dp[0][0])
                    break
                except (TypeError, ValueError):
                    pass
    surname = None
    authors = msg.get("author")
    if isinstance(authors, list) and authors:
        a0 = authors[0]
        if isinstance(a0, dict):
            surname = a0.get("family") or a0.get("name")
    return year, (surname or None)


def _crossref_fetch(doi, mailto, timeout):
    """查 Crossref works/{doi} → message dict；任何异常/非 200 → None（优雅降级，绝不抛）。"""
    try:
        import requests
        from urllib.parse import quote
    except Exception:  # noqa: BLE001
        return None
    url = "https://api.crossref.org/works/" + quote(str(doi), safe="")
    params = {"mailto": mailto} if mailto else None
    headers = {"User-Agent": "fulltext_fetcher-consolidate/1.0 (mailto:%s)" % (mailto or "anonymous")}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return None
        return (r.json() or {}).get("message")
    except Exception:  # noqa: BLE001 - 网络/解析异常 → 降级
        return None


def enrich_meta_from_crossref(dois, meta, mailto, timeout, cache_path, log=None):
    """对缺 year/author 的 DOI 查 Crossref 补全，写回 meta（就地）。带磁盘缓存（幂等、可续跑）。

    只补 year/authors，不覆盖已有值；任何失败留空（后续渲染优雅降级为 {title}_{doi}）。
    """
    cache = {}
    if cache_path and os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cache = {}
    filled = 0
    queried = 0
    for doi in dois:
        m = meta.get(doi) or {}
        if m.get("year") and m.get("authors"):
            continue
        if doi in cache:
            cr = cache[doi]
        else:
            msg = _crossref_fetch(doi, mailto, timeout)
            y, s = _parse_crossref_message(msg)
            cr = {"year": y, "author": s}
            cache[doi] = cr
            queried += 1
            if cache_path and queried % 20 == 0:
                try:
                    json.dump(cache, open(cache_path, "w", encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    pass
        m = dict(m)
        if cr.get("year") and not m.get("year"):
            m["year"] = cr["year"]
        if cr.get("author") and not m.get("authors"):
            m["authors"] = [cr["author"]]
        meta[doi] = m
        if cr.get("year") or cr.get("author"):
            filled += 1
        if log and queried and queried % 25 == 0:
            log("crossref enrich 进度：已查询 %d 条，补全 %d 条" % (queried, filled))
    if cache_path:
        try:
            json.dump(cache, open(cache_path, "w", encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"queried": queried, "filled": filled}


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


def build_plan(coverage_path, out_root, template, *, enrich=False, mailto=None,
               timeout=20.0, cache_path=None, log=None):
    """产出 [(doi, src_path, new_name)]：仅 status=success 且 pdf_path 存在于盘的记录。

    ``enrich=True`` 时对缺 year/author 的成功 DOI 查 Crossref 补全（联网、幂等缓存）——程序自动完成，
    无需人工；任何条目查询失败即留空，渲染优雅降级为 {title}_{doi}。
    """
    from fulltext_fetcher.scholar.naming import build_filename

    with open(coverage_path, encoding="utf-8") as f:
        cov = json.load(f)
    meta = load_meta_index(out_root)
    succ = [r for r in cov.get("records", []) if r.get("status") == "success"]
    enrich_stats = None
    if enrich:
        want = [r.get("doi") for r in succ
                if r.get("doi") and not (meta.get(r["doi"], {}).get("year")
                                         and meta.get(r["doi"], {}).get("authors"))]
        enrich_stats = enrich_meta_from_crossref(want, meta, mailto, timeout, cache_path, log=log)
    cfg = _NameCfg(template)
    taken = set()
    plan = []
    skipped_no_disk = []
    for rec in succ:
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
        auth0 = ""
        if isinstance(paper.authors, (list, tuple)) and paper.authors:
            a0 = paper.authors[0]
            auth0 = a0.get("family") or a0.get("name") or "" if isinstance(a0, dict) else str(a0)
        elif paper.authors:
            auth0 = str(paper.authors)
        plan.append({
            "doi": doi, "src": src, "new_name": new_name,
            "year": paper.year or "", "author": auth0,
            "title": paper.title or "", "journal": paper.journal or "",
        })
    return plan, skipped_no_disk, enrich_stats


def run(coverage_path, dest, template, do_copy=True, *, enrich=False, mailto=None,
        timeout=20.0, log=None):
    out_root = os.path.dirname(os.path.abspath(coverage_path)) or "out"
    cache_path = os.path.join(dest, "_crossref_enrich_cache.json") if enrich else None
    if enrich and do_copy:
        os.makedirs(dest, exist_ok=True)
    plan, skipped, enrich_stats = build_plan(
        coverage_path, out_root, template,
        enrich=enrich, mailto=mailto, timeout=timeout, cache_path=cache_path, log=log)
    pdf_dir = os.path.join(dest, "pdfs")
    if do_copy:
        os.makedirs(pdf_dir, exist_ok=True)
    names = [it["new_name"] for it in plan]
    assert len(names) == len(set(names)), "命名撞车（build_filename taken 去重应保证唯一）"
    copied = 0
    for it in plan:
        dst = os.path.join(pdf_dir, it["new_name"])
        if do_copy:
            shutil.copy2(it["src"], dst)
            copied += 1
    if do_copy:
        # ① 机器可读 manifest（doi→新名→原路径），供程序回溯
        man_path = os.path.join(dest, "manifest.csv")
        with open(man_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["doi", "new_name", "src_path"])
            w.writeheader()
            for it in plan:
                w.writerow({"doi": it["doi"], "new_name": it["new_name"], "src_path": it["src"]})
        # ② 人类可读 manifest（年/作者/标题/DOI/文件名），供人核对
        read_path = os.path.join(dest, "manifest_readable.csv")
        with open(read_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["year", "author", "title", "doi", "journal", "filename"])
            w.writeheader()
            for it in sorted(plan, key=lambda x: (str(x["year"]) or "0", str(x["author"]).lower())):
                w.writerow({"year": it["year"], "author": it["author"], "title": it["title"],
                            "doi": it["doi"], "journal": it["journal"], "filename": it["new_name"]})
        # 落盘校验：目录内 PDF 数应 == 计划数
        on_disk = len([n for n in os.listdir(pdf_dir) if n.lower().endswith(".pdf")])
        assert on_disk == len(plan), f"落盘校验失败：磁盘 {on_disk} != 计划 {len(plan)}"
    res = {
        "planned": len(plan),
        "copied": copied,
        "skipped_no_disk": len(skipped),
        "dest_pdfs": pdf_dir,
        "template": template,
    }
    if enrich_stats is not None:
        res["enrich"] = enrich_stats
    return res


def _selftest():
    import tempfile
    from fulltext_fetcher.scholar.naming import build_filename

    # 命名规则：year/author 缺失 → 优雅降级为 {title}_{doi}
    cfg = _NameCfg("{year}_{author}_{title}_{doi}")
    n1 = build_filename(None, _Paper(doi="10.1/abc", title="Cool Paper"), cfg, taken=set())
    # year/author 缺失 → 优雅降级为 {title}_{doi}；doi 的 '/' 净化为 '_'（点保留）
    assert n1.endswith(".pdf") and "cool" in n1.lower() and "10.1_abc" in n1.lower(), n1
    # 补全 year/author 后 → 完整 {year}_{author}_{title}_{doi}
    n2 = build_filename(None, _Paper(doi="10.1/abc", title="Cool Paper", year=2021,
                                     authors=["Vaswani"]), cfg, taken=set())
    assert n2.lower().startswith("2021_vaswani_cool"), n2

    # Crossref message 解析（纯函数、离线）：抽 year + 首作者姓
    y, s = _parse_crossref_message({
        "issued": {"date-parts": [[2019, 5, 1]]},
        "author": [{"family": "Zhang", "given": "Wei"}, {"family": "Li"}],
    })
    assert y == 2019 and s == "Zhang", (y, s)
    assert _parse_crossref_message({}) == (None, None)
    assert _parse_crossref_message(None) == (None, None)

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
        assert "enrich" not in res, res            # 未开 --enrich → 不查网络
        files = os.listdir(os.path.join(dest, "pdfs"))
        assert len(files) == 1 and files[0].endswith(".pdf"), files
        assert os.path.exists(os.path.join(dest, "manifest.csv"))
        # 人类可读 manifest 也应生成，且含 year/author/title/doi/filename 列
        read_csv = os.path.join(dest, "manifest_readable.csv")
        assert os.path.exists(read_csv), read_csv
        rows = list(csv.DictReader(open(read_csv, encoding="utf-8-sig")))
        assert len(rows) == 1 and rows[0]["doi"] == "10.1/abc" and rows[0]["title"] == "Cool Paper", rows
        assert set(rows[0].keys()) == {"year", "author", "title", "doi", "journal", "filename"}, rows[0]

        # enrich 幂等缓存离线验证：预置缓存命中 → 不发网络即补全 year/author、重命名带年/作者
        meta = {"10.1/abc": {"title": "Cool Paper"}}
        cache = os.path.join(d, "_cache.json")
        json.dump({"10.1/abc": {"year": 2021, "author": "Vaswani"}}, open(cache, "w", encoding="utf-8"))
        st = enrich_meta_from_crossref(["10.1/abc"], meta, None, 5.0, cache)
        assert st["queried"] == 0, st              # 命中缓存 → 零网络
        assert meta["10.1/abc"]["year"] == 2021 and meta["10.1/abc"]["authors"] == ["Vaswani"], meta
    print("CONSOLIDATE_OK")
    return 0


def main():
    ap = argparse.ArgumentParser(description="汇总已成功 PDF 到单一文件夹并统一命名")
    ap.add_argument("--coverage", default="out/coverage.json", help="权威 coverage.json 路径")
    ap.add_argument("--dest", default="out/_delivery", help="交付根目录（PDF 落 <dest>/pdfs/）")
    ap.add_argument("--template", default="{year}_{author}_{title}_{doi}",
                    help="统一命名模板（占位符 {year}/{author}/{title}/{doi}/{venue}）")
    ap.add_argument("--dry-run", action="store_true", help="只算计划、不拷贝")
    ap.add_argument("--enrich", action="store_true",
                    help="对缺 year/author 的成功 DOI 查 Crossref 自动补全后再命名（联网、幂等缓存）")
    ap.add_argument("--mailto", default=os.environ.get("FULLTEXT_EMAIL"),
                    help="Crossref 礼貌池邮箱（--enrich 时用；默认取 FULLTEXT_EMAIL）")
    ap.add_argument("--timeout", type=float, default=20.0, help="单条 Crossref 查询超时秒")
    ap.add_argument("--selftest", action="store_true", help="离线自检 → CONSOLIDATE_OK")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()

    def _safe_log(s):
        try:
            print("  " + s)
        except UnicodeEncodeError:  # Windows GBK 控制台遇非 GBK 字符 → 降级替换,绝不崩
            enc = sys.stdout.encoding or "utf-8"
            print(("  " + s).encode(enc, "replace").decode(enc, "replace"))

    log = _safe_log if args.enrich else None
    res = run(args.coverage, args.dest, args.template, do_copy=not args.dry_run,
              enrich=args.enrich, mailto=args.mailto, timeout=args.timeout, log=log)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    tail = ""
    if res.get("enrich"):
        tail = f"；Crossref 补全 {res['enrich']['filled']} 条（查询 {res['enrich']['queried']}）"
    print(f"\n汇总 {res['copied']}/{res['planned']} 份 → {res['dest_pdfs']}"
          f"（统一命名 {res['template']}；盘上缺失跳过 {res['skipped_no_disk']}{tail}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
