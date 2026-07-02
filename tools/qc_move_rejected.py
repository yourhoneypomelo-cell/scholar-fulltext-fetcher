#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QC cleanup: move QC-misjudged (wrong-content) PDFs from out/<batch>/pdfs/ to
out/<batch>/rejected/ so the mainline corpus reflects the audited clean caliber.

- Consumes two audit CSVs (same schema, both produced by tools/qc_content_match.py):
    out/qc_merge_highconf_wrong.csv  -> 54 hard evidences   (source=hard)
    out/qc_merge_union_wrong.csv     -> 391 union (superset) (source=soft unless in hard)
- MOVE (not delete): PDFs are kept under rejected/ for later review.
- Idempotent: rerunning does not re-move; already-moved / missing entries are recorded.
- Does NOT touch metadata.jsonl (downstream 147 derives the clean caliber from CSVs).

Writes out/qc_rejected_manifest.csv with columns:
    doi, batch, source, status, orig_path, new_path

Usage:
    python tools/qc_move_rejected.py            # perform the move
    python tools/qc_move_rejected.py --dry-run  # report only, move nothing
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
from collections import Counter, OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARD_CSV = os.path.join(ROOT, "out", "qc_merge_highconf_wrong.csv")
UNION_CSV = os.path.join(ROOT, "out", "qc_merge_union_wrong.csv")
MANIFEST = os.path.join(ROOT, "out", "qc_rejected_manifest.csv")

_SEG = re.compile(r"([\\/])pdfs([\\/])")


def norm_rel(pdf_path: str) -> str:
    """Normalize a CSV pdf_path to a forward-slash relative path (key)."""
    return pdf_path.replace("\\", "/").strip()


def dest_raw(pdf_path: str) -> str:
    """Rewrite the '/pdfs/' segment to '/rejected/', preserving original separators."""
    return _SEG.sub(r"\1rejected\2", pdf_path)


def read_paths(csv_path: str):
    """Yield (key, doi, batch, raw_pdf_path) for each data row."""
    # utf-8-sig: the merge CSVs carry a UTF-8 BOM; strip it so the first
    # column ("batch") is not read as "\ufeffbatch".
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        for rec in csv.DictReader(fh):
            raw = (rec.get("pdf_path") or "").strip()
            if not raw:
                continue
            yield norm_rel(raw), (rec.get("doi") or "").strip(), (rec.get("batch") or "").strip(), raw


def build_worklist():
    """Ordered dedup by normalized pdf_path; source=hard if in highconf else soft."""
    hard_keys = {k for k, *_ in read_paths(HARD_CSV)}
    work: "OrderedDict[str, dict]" = OrderedDict()
    # union first (superset), then fold in any hard-only stragglers for safety
    for src_csv in (UNION_CSV, HARD_CSV):
        if not os.path.isfile(src_csv):
            print(f"[warn] missing input CSV: {src_csv}", file=sys.stderr)
            continue
        for key, doi, batch, raw in read_paths(src_csv):
            if key in work:
                continue
            work[key] = {
                "doi": doi,
                "batch": batch,
                "raw": raw,
                "source": "hard" if key in hard_keys else "soft",
            }
    return work, hard_keys


def move_one(rel_key: str, raw: str, dry: bool):
    """Return (status, new_path_or_empty)."""
    src_abs = os.path.normpath(os.path.join(ROOT, rel_key))
    new_raw = dest_raw(raw)
    dst_rel = norm_rel(new_raw)
    dst_abs = os.path.normpath(os.path.join(ROOT, dst_rel))

    if "pdfs" not in rel_key.split("/"):
        return "bad_path", ""

    if os.path.isfile(src_abs):
        if os.path.exists(dst_abs):
            # Would clobber an existing rejected file; skip to stay non-destructive.
            return "conflict_dst_exists", new_raw
        if not dry:
            os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
            shutil.move(src_abs, dst_abs)
        return ("would_move" if dry else "moved"), new_raw
    if os.path.isfile(dst_abs):
        return "already_moved", new_raw
    return "missing", ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report only; move nothing")
    args = ap.parse_args()

    work, hard_keys = build_worklist()
    n_hard = sum(1 for v in work.values() if v["source"] == "hard")
    n_soft = sum(1 for v in work.values() if v["source"] == "soft")
    print(f"worklist: {len(work)} unique pdf_path  (hard={n_hard}, soft={n_soft}; "
          f"hard-csv keys={len(hard_keys)})")

    status_ctr: Counter = Counter()
    batch_moved: Counter = Counter()
    rows = []
    for key, meta in work.items():
        status, new_raw = move_one(key, meta["raw"], args.dry_run)
        status_ctr[status] += 1
        if status in ("moved", "would_move"):
            batch_moved[meta["batch"]] += 1
        rows.append({
            "doi": meta["doi"],
            "batch": meta["batch"],
            "source": meta["source"],
            "status": status,
            "orig_path": meta["raw"],
            "new_path": new_raw,
        })

    if not args.dry_run:
        with open(MANIFEST, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["doi", "batch", "source", "status", "orig_path", "new_path"])
            w.writeheader()
            w.writerows(rows)

    print("\n== status ==")
    for st, c in sorted(status_ctr.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {st:22s} {c}")
    print("\n== moved per batch ==")
    for b, c in sorted(batch_moved.items()):
        print(f"  {b:28s} {c}")
    moved_total = status_ctr.get("moved", 0) + status_ctr.get("would_move", 0)
    print(f"\ntotal moved{' (dry)' if args.dry_run else ''}: {moved_total}")
    if not args.dry_run:
        print(f"manifest: out/qc_rejected_manifest.csv ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
