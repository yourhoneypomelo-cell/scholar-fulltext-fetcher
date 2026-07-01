"""把官方批量快照灌入本地 SQLite,供 `--snapshot-db` 零额度/零限速本地查询。

用法:
  # Unpaywall Data Feed/snapshot(JSONL,通常 .jsonl.gz)
  python -m fulltext_fetcher.ingest --unpaywall unpaywall_snapshot.jsonl.gz --db oa.sqlite
  # OpenAlex works 快照(JSONL,可与上面并入同一库)
  python -m fulltext_fetcher.ingest --openalex openalex_works.jsonl.gz --db oa.sqlite

之后:
  python -m fulltext_fetcher -f dois.txt --snapshot-db oa.sqlite --email you@uni.edu
  → DOI 先走本地快照(零联网),未命中再回退在线源。

快照获取(合法、免费):
  - OpenAlex snapshot(CC0):https://docs.openalex.org/download-all-data
  - Unpaywall Data Feed/snapshot:https://unpaywall.org/products/data-feed
  - Semantic Scholar Datasets / CORE data dump 亦可(本工具直接支持 Unpaywall/OpenAlex 两种 JSON 结构)。
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from . import snapshot


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="fulltext_fetcher.ingest",
        description="把 Unpaywall/OpenAlex 快照灌入本地 SQLite(供 --snapshot-db 零限速本地查)。",
    )
    p.add_argument("--unpaywall", help="Unpaywall snapshot JSONL(.gz) 路径")
    p.add_argument("--openalex", help="OpenAlex works JSONL(.gz) 路径")
    p.add_argument("--db", required=True, help="输出 SQLite 路径")
    p.add_argument("--batch", type=int, default=5000, help="批量提交条数(默认 5000)")
    args = p.parse_args(argv)

    if not (args.unpaywall or args.openalex):
        print("错误:至少提供 --unpaywall 或 --openalex 之一", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    log = logging.getLogger("ingest")

    total = 0
    if args.unpaywall:
        log.info("开始入库 Unpaywall:%s", args.unpaywall)
        n = snapshot.build_from_unpaywall(args.unpaywall, args.db, batch=args.batch, log=log)
        log.info("Unpaywall 完成,%d 条", n)
        total += n
    if args.openalex:
        log.info("开始入库 OpenAlex:%s", args.openalex)
        n = snapshot.build_from_openalex(args.openalex, args.db, batch=args.batch, log=log)
        log.info("OpenAlex 完成,%d 条", n)
        total += n

    print(f"INGEST_DONE db={args.db} records~{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
