"""官方批量快照 → 本地 SQLite 索引(合法的"无额度/无限速/无 key"路线)。

免费 API 有每日额度与限速;**官方快照/数据转储**则可全量下载到本地,DOI 本地秒查,
彻底不受额度/限速约束且完全合规(OpenAlex 快照 CC0、Unpaywall Data Feed、S2 Datasets、CORE dump)。

本模块负责:把 Unpaywall / OpenAlex 的 JSONL(.gz) 快照流式灌入一张 SQLite 表,
并提供 by-DOI 的本地查询,供 sources/snapshot_source.py 在抓取时零联网定位 OA PDF。

表结构:oa(doi PRIMARY KEY, pdf_url, landing_url, oa_status, all_pdfs[JSON])
"""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple


def _open_text(path: str):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    d = str(doi).strip().lower()
    for p in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if d.startswith(p):
            d = d[len(p):]
            break
    return d or None


def _init_db(db_path: str) -> sqlite3.Connection:
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        "CREATE TABLE IF NOT EXISTS oa ("
        "doi TEXT PRIMARY KEY, pdf_url TEXT, landing_url TEXT, oa_status TEXT, all_pdfs TEXT)"
    )
    con.commit()
    return con


def _flush(con: sqlite3.Connection, rows: List[Tuple]) -> None:
    con.executemany(
        "INSERT OR REPLACE INTO oa (doi,pdf_url,landing_url,oa_status,all_pdfs) VALUES (?,?,?,?,?)",
        rows,
    )
    con.commit()


def _row_from_unpaywall(rec: Dict[str, Any]) -> Optional[Tuple]:
    doi = normalize_doi(rec.get("doi"))
    if not doi:
        return None
    best = rec.get("best_oa_location") or {}
    all_pdfs = [loc["url_for_pdf"] for loc in (rec.get("oa_locations") or [])
                if isinstance(loc, dict) and loc.get("url_for_pdf")]
    return (doi, best.get("url_for_pdf"), best.get("url"), rec.get("oa_status"),
            json.dumps(all_pdfs, ensure_ascii=False) if all_pdfs else None)


def _row_from_openalex(rec: Dict[str, Any]) -> Optional[Tuple]:
    doi = normalize_doi(rec.get("doi"))
    if not doi:
        return None
    best = rec.get("best_oa_location") or {}
    oa = rec.get("open_access") or {}
    all_pdfs = [loc["pdf_url"] for loc in (rec.get("locations") or [])
                if isinstance(loc, dict) and loc.get("pdf_url")]
    return (doi, best.get("pdf_url") if isinstance(best, dict) else None,
            oa.get("oa_url"), oa.get("oa_status"),
            json.dumps(all_pdfs, ensure_ascii=False) if all_pdfs else None)


def _build(jsonl_path: str, db_path: str, row_fn, batch: int, log: Any) -> int:
    con = _init_db(db_path)
    n = 0
    rows: List[Tuple] = []
    try:
        with _open_text(jsonl_path) as f:
            for line in f:
                line = line.strip().rstrip(",")  # 容忍数组式 JSON 的行尾逗号
                if not line or line in ("[", "]"):
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                row = row_fn(rec)
                if not row:
                    continue
                rows.append(row)
                n += 1
                if len(rows) >= batch:
                    _flush(con, rows)
                    rows = []
                    if log:
                        log.info("已入库 %d 条 ...", n)
        if rows:
            _flush(con, rows)
    finally:
        con.close()
    return n


def build_from_unpaywall(jsonl_path: str, db_path: str, batch: int = 5000, log: Any = None) -> int:
    return _build(jsonl_path, db_path, _row_from_unpaywall, batch, log)


def build_from_openalex(jsonl_path: str, db_path: str, batch: int = 5000, log: Any = None) -> int:
    return _build(jsonl_path, db_path, _row_from_openalex, batch, log)


def lookup(db_path: str, doi: str) -> Optional[Dict[str, Any]]:
    d = normalize_doi(doi)
    if not d or not os.path.exists(db_path):
        return None
    con = sqlite3.connect(db_path)
    try:
        cur = con.execute(
            "SELECT pdf_url, landing_url, oa_status, all_pdfs FROM oa WHERE doi=?", (d,))
        row = cur.fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not row:
        return None
    pdf_url, landing_url, oa_status, all_pdfs = row
    return {
        "pdf_url": pdf_url,
        "landing_url": landing_url,
        "oa_status": oa_status,
        "all_pdfs": json.loads(all_pdfs) if all_pdfs else [],
    }
