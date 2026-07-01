"""One-off: build recover_b6_els_wayback_input.txt for the wayback probe (task-8228f11f).

Reuse the 5 DOIs 143 already tested via browser_search (subset_elsevier_probe_149.txt)
for a clean same-DOI cross-method comparison, then top up with more Elsevier A-class
(prefix 10.1016, success=false, candidates>=1) MISS entries from out/batch6/metadata.jsonl
until we reach ~12 DOIs.
"""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBSET = os.path.join(ROOT, "subset_elsevier_probe_149.txt")
B6_META = os.path.join(ROOT, "out", "batch6", "metadata.jsonl")
OUT = os.path.join(ROOT, "recover_b6_els_wayback_input.txt")
TARGET = 12


def read_subset() -> list[str]:
    dois: list[str] = []
    with open(SUBSET, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                dois.append(s)
    return dois


def elsevier_a_from_b6() -> list[str]:
    """Elsevier A-class MISS = doi prefix 10.1016, success False, candidates>=1."""
    picked: list[str] = []
    if not os.path.exists(B6_META):
        return picked
    with open(B6_META, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            doi = (rec.get("doi") or "").strip()
            if not doi.startswith("10.1016/"):
                continue
            if rec.get("success"):
                continue
            if int(rec.get("candidates") or 0) < 1:
                continue
            picked.append(doi)
    return picked


def main() -> None:
    subset = read_subset()
    seen = {d.lower() for d in subset}
    merged = list(subset)
    extra_pool = elsevier_a_from_b6()
    added = []
    for d in extra_pool:
        if len(merged) >= TARGET:
            break
        if d.lower() in seen:
            continue
        seen.add(d.lower())
        merged.append(d)
        added.append(d)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# batch6 Elsevier A-class (websearch hit / had candidate, download failed) "
                "wayback cross-method probe vs 143 browser_search 0/10\n")
        f.write(f"# {len(subset)} reused from subset_elsevier_probe_149.txt (same DOIs 143 tested) "
                f"+ {len(added)} topped up from out/batch6 A-class MISS\n")
        for d in merged:
            f.write(d + "\n")

    print(f"subset_reused={len(subset)} extra_pool={len(extra_pool)} added={len(added)} total={len(merged)}")
    print("REUSED:")
    for d in subset:
        print("  ", d)
    print("ADDED:")
    for d in added:
        print("  ", d)


if __name__ == "__main__":
    main()
