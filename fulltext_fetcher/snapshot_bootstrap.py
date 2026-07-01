"""官方快照 → 本地 SQLite 的一键引导 + 增量灌库(超大批量/离线场景)。

本脚本是 `ingest.py` 的"引导壳":它**不重复实现**入库逻辑,而是以只读方式复用
`snapshot.build_from_unpaywall/openalex`(即 `python -m fulltext_fetcher.ingest`
底层的同一入库能力),另外补上两件事:

  1. **引导(guide)**:打印/校验官方快照的合法免费获取方式(URL + 许可声明),
     覆盖 OpenAlex data dump(CC0)与 Unpaywall Data Feed。
  2. **增量(--incremental)**:对"已下载到本地"的快照文件灌库时,跳过 DB 中已存在的
     DOI(可选按更新日期 `--since` 过滤),便于按日期/追加文件持续同步。

设计约束:纯标准库(可选 requests,本脚本并不需要);**不代下**数十 GB 的大文件——
只负责"引导 + 对本地已下载文件灌库",避免误触发巨量下载。

用法::

  # 1) 打印获取指引(不联网),可加 --check-env 检测本机 aws CLI 是否就绪
  python -m fulltext_fetcher.snapshot_bootstrap guide
  python -m fulltext_fetcher.snapshot_bootstrap guide --check-env

  # 2) 把本地已下载的快照文件灌入 SQLite(复用 ingest 的入库能力)
  python -m fulltext_fetcher.snapshot_bootstrap ingest \
      --openalex openalex-snapshot/works/part_000.jsonl.gz --db oa.sqlite
  python -m fulltext_fetcher.snapshot_bootstrap ingest \
      --unpaywall unpaywall_feed_2026-06-01.jsonl.gz --db oa.sqlite

  # 3) 增量:只灌 DB 中尚不存在的 DOI(可按更新日期过滤)
  python -m fulltext_fetcher.snapshot_bootstrap ingest \
      --openalex changed_works.jsonl.gz --db oa.sqlite --incremental --since 2026-01-01

  # 4) 离线自检(无网络):造 mock jsonl → 灌库 → 查询 → 断言
  python -m fulltext_fetcher.snapshot_bootstrap selftest
  python -m fulltext_fetcher.snapshot_bootstrap            # 无参数默认自检

灌好的库直接喂给主程序零联网查:
  python -m fulltext_fetcher -f dois.txt --snapshot-db oa.sqlite --email you@uni.edu
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import io
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

from . import ingest, snapshot

# ---------------------------------------------------------------------------
# 获取指引(合法、免费)—— URL 与许可声明
# ---------------------------------------------------------------------------

GUIDE_TEXT = """\
================ 官方批量快照获取指引(合法 · 免费) ================

【OpenAlex 数据转储(强烈推荐,覆盖最广)】
  文档 : https://docs.openalex.org/download-all-data
         (新址 https://developers.openalex.org/download )
  许可 : CC0 1.0 Universal —— 公共领域,任意使用、无需署名。
         https://creativecommons.org/publicdomain/zero/1.0/
  获取 : 托管于 Amazon S3,免费且【无需 AWS 账号】(AWS Open Data 计划承担流量费)。
         安装 AWS CLI 后用匿名访问 --no-sign-request:
           # 只取 works 的 JSON Lines(推荐,单一实体即可满足 DOI→OA 定位):
           aws s3 sync "s3://openalex/data/jsonl/works" "openalex-snapshot/works" --no-sign-request
           # 完整库(约 330GB 压缩 / 解压 ~1.6TB,一般不需要):
           aws s3 sync "s3://openalex" "openalex-snapshot" --no-sign-request
  增量 : 每个实体带 manifest.json 可用于增量同步:
           aws s3 cp "s3://openalex/data/jsonl/works/manifest.json" ./manifest.json --no-sign-request
         免费快照季度更新;每日变更文件 / 月度快照为付费(Changefiles API)。
  灌库 : 下载完成后 →
           python -m fulltext_fetcher.snapshot_bootstrap ingest --openalex <文件.jsonl.gz> --db oa.sqlite

【Unpaywall Data Feed / 快照】
  数据源 : https://unpaywall.org/products/data-feed   (Data Feed:付费,提供每日变更文件与快照)
           https://unpaywall.org/products/snapshot   (免费数据库快照页)
  现状   : 官方已停止制作半年度 Unpaywall 快照,并引导改用 OpenAlex 快照(同为 CC0、覆盖更广)。
  许可   : 以 https://unpaywall.org 当前官方声明为准;Unpaywall 数据历来以开放方式提供。
  兼容   : 本工具的 --unpaywall 解析器兼容 Unpaywall 记录结构
           (best_oa_location.url_for_pdf / oa_locations[].url_for_pdf / oa_status),
           可用于历史 Unpaywall 快照或 Data Feed 变更文件。
  灌库   : python -m fulltext_fetcher.snapshot_bootstrap ingest --unpaywall <文件.jsonl.gz> --db oa.sqlite

【合规提示】以上均为官方公开、合法免费的批量数据;下载与再利用请遵守各自许可
  (OpenAlex = CC0;Unpaywall 以官方页面为准)。本脚本不代下大文件,仅做引导与本地灌库。
==================================================================="""


def guide_text() -> str:
    """返回获取指引文本(供打印或自检断言)。"""
    return GUIDE_TEXT


def check_env() -> Dict[str, Any]:
    """离线检测本机快照下载/灌库前置条件(不联网)。"""
    aws = shutil.which("aws")
    return {
        "aws_cli": aws,
        "aws_cli_ready": bool(aws),
        "gzip_supported": True,  # 标准库自带
        "python": sys.version.split()[0],
    }


def print_guide(with_env: bool = False) -> None:
    print(guide_text())
    if with_env:
        env = check_env()
        print("\n---- 本机环境检查(离线)----")
        if env["aws_cli_ready"]:
            print(f"[ok] 找到 aws CLI:{env['aws_cli']}(可用于下载 OpenAlex 快照)")
        else:
            print("[!]  未找到 aws CLI —— 下载 OpenAlex 快照前请先安装:https://aws.amazon.com/cli/")
        print(f"[ok] gzip 解压:标准库内置")
        print(f"[ok] Python:{env['python']}")


# ---------------------------------------------------------------------------
# 本地文件读取 / 校验
# ---------------------------------------------------------------------------

def _open_text(path: str):
    """按扩展名选择 gzip 或纯文本读取(与 snapshot 模块一致)。"""
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def _iter_records(path: str) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """流式产出 (原始行, 解析后的 dict);容忍数组式 JSON 的行尾逗号与方括号行。"""
    with _open_text(path) as f:
        for line in f:
            s = line.strip().rstrip(",")
            if not s or s in ("[", "]"):
                continue
            try:
                rec = json.loads(s)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield s, rec


def _record_date(rec: Dict[str, Any]) -> Optional[str]:
    """取记录的更新日期(OpenAlex=updated_date,Unpaywall=updated),取前 10 位 YYYY-MM-DD。"""
    d = rec.get("updated_date") or rec.get("updated") or rec.get("updated_at")
    return str(d)[:10] if d else None


def verify_snapshot_file(kind: str, path: str) -> Dict[str, Any]:
    """离线校验本地快照文件:是否存在、首条记录能否解析出 DOI。"""
    info: Dict[str, Any] = {"exists": os.path.exists(path), "kind": kind, "path": path,
                            "sample_doi": None, "ok": False, "message": ""}
    if not info["exists"]:
        info["message"] = "文件不存在"
        return info
    try:
        for _, rec in _iter_records(path):
            info["sample_doi"] = snapshot.normalize_doi(rec.get("doi"))
            break
    except OSError as e:  # 读取/解压失败
        info["message"] = f"读取失败:{e}"
        return info
    if info["sample_doi"]:
        info["ok"] = True
        info["message"] = f"校验通过,示例 DOI:{info['sample_doi']}"
    else:
        info["message"] = "未从首条记录解析出 DOI(请确认文件为 Unpaywall/OpenAlex JSONL)"
    return info


# ---------------------------------------------------------------------------
# DB 只读辅助
# ---------------------------------------------------------------------------

def _count(db_path: str) -> int:
    if not os.path.exists(db_path):
        return 0
    con = sqlite3.connect(db_path)
    try:
        return int(con.execute("SELECT COUNT(*) FROM oa").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def _doi_exists_checker(db_path: str):
    """返回 (check(doi)->bool, close())。若库不存在/表缺失,check 恒为 False。"""
    if not os.path.exists(db_path):
        return (lambda _d: False), (lambda: None)
    con = sqlite3.connect(db_path)
    try:
        con.execute("SELECT 1 FROM oa LIMIT 1")  # 探测表是否存在
    except sqlite3.Error:
        con.close()
        return (lambda _d: False), (lambda: None)

    def check(doi: str) -> bool:
        cur = con.execute("SELECT 1 FROM oa WHERE doi=? LIMIT 1", (doi,))
        return cur.fetchone() is not None

    return check, con.close


# ---------------------------------------------------------------------------
# 增量过滤 + 灌库(复用 snapshot / ingest 的现有入库能力)
# ---------------------------------------------------------------------------

def _build_fn(kind: str) -> Callable[..., int]:
    if kind == "unpaywall":
        return snapshot.build_from_unpaywall
    if kind == "openalex":
        return snapshot.build_from_openalex
    raise ValueError(f"未知 kind:{kind!r}(应为 'unpaywall' 或 'openalex')")


def _filter_new(kind: str, src: str, db_path: str, since: Optional[str],
                out_path: str) -> Dict[str, int]:
    """把 src 中【DB 尚无、且日期 >= since】的记录写入 out_path,返回统计。"""
    seen = skipped_existing = skipped_date = kept = 0
    check, close = _doi_exists_checker(db_path)
    since10 = since[:10] if since else None
    try:
        with open(out_path, "w", encoding="utf-8") as out:
            for raw, rec in _iter_records(src):
                seen += 1
                doi = snapshot.normalize_doi(rec.get("doi"))
                if not doi:
                    continue  # 无 DOI 的记录 build 阶段也会丢弃
                if since10:
                    d = _record_date(rec)
                    if d and d < since10:
                        skipped_date += 1
                        continue
                if check(doi):
                    skipped_existing += 1
                    continue
                out.write(raw + "\n")
                kept += 1
    finally:
        close()
    return {"seen": seen, "skipped_existing": skipped_existing,
            "skipped_date": skipped_date, "kept": kept}


def ingest_snapshot(kind: str, path: str, db: str, *, incremental: bool = False,
                    since: Optional[str] = None, batch: int = 5000,
                    use_ingest_cli: bool = False,
                    log: Any = None) -> Dict[str, Any]:
    """把本地快照文件灌入 SQLite。

    - 普通模式:直接复用 snapshot.build_from_*(可选 use_ingest_cli 走 ingest 的 CLI)。
    - 增量模式:先过滤掉 DB 已有 DOI(及早于 since 的记录)到临时文件,再复用同一入库能力。
    """
    build = _build_fn(kind)  # 触发 kind 校验
    before = _count(db)

    if not incremental:
        if use_ingest_cli:
            rc = ingest.main([f"--{kind}", path, "--db", db, "--batch", str(batch)])
            after = _count(db)
            return {"mode": "full-cli", "rc": rc, "added": after - before,
                    "db_total": after}
        processed = build(path, db, batch=batch, log=log)
        after = _count(db)
        return {"mode": "full", "processed": processed, "added": after - before,
                "db_total": after}

    # 增量:过滤到临时文件后再灌库(不修改既有模块,纯外部编排)
    fd, tmp = tempfile.mkstemp(prefix="snap_inc_", suffix=".jsonl")
    os.close(fd)
    try:
        stats = _filter_new(kind, path, db, since, tmp)
        processed = build(tmp, db, batch=batch, log=log) if stats["kept"] else 0
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)
    after = _count(db)
    return {"mode": "incremental", "processed": processed, "added": after - before,
            "db_total": after, **stats}


# ---------------------------------------------------------------------------
# 离线自检
# ---------------------------------------------------------------------------

_MOCK_UNPAYWALL = [
    {"doi": "10.1/aaa", "oa_status": "gold", "updated": "2026-02-01",
     "best_oa_location": {"url_for_pdf": "https://ex.org/aaa.pdf", "url": "https://ex.org/aaa"},
     "oa_locations": [{"url_for_pdf": "https://ex.org/aaa.pdf"}]},
    {"doi": "10.1/bbb", "oa_status": "green", "updated": "2024-05-01",
     "best_oa_location": {"url_for_pdf": "https://ex.org/bbb.pdf", "url": "https://ex.org/bbb"}},
]

_MOCK_UNPAYWALL_INC = [
    {"doi": "10.1/aaa", "oa_status": "gold", "updated": "2026-02-01",  # 已存在 → 跳过
     "best_oa_location": {"url_for_pdf": "https://ex.org/aaa.pdf", "url": "https://ex.org/aaa"}},
    {"doi": "10.1/ccc", "oa_status": "bronze", "updated": "2026-06-01",  # 新增
     "best_oa_location": {"url_for_pdf": "https://ex.org/ccc.pdf", "url": "https://ex.org/ccc"}},
    {"doi": "10.1/ddd", "oa_status": "closed", "updated": "2019-01-01",  # 早于 since → 跳过
     "best_oa_location": {"url_for_pdf": "https://ex.org/ddd.pdf", "url": "https://ex.org/ddd"}},
]

_MOCK_OPENALEX = [
    {"doi": "https://doi.org/10.2/xyz", "updated_date": "2026-03-01",
     "open_access": {"oa_url": "https://ex.org/xyz", "oa_status": "gold"},
     "best_oa_location": {"pdf_url": "https://ex.org/xyz.pdf"},
     "locations": [{"pdf_url": "https://ex.org/xyz.pdf"}]},
]


def _write_jsonl(path: str, records) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _selftest() -> int:
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "oa.sqlite")
        up1 = os.path.join(td, "up1.jsonl")
        up2 = os.path.join(td, "up2.jsonl")
        oa1 = os.path.join(td, "oa1.jsonl")
        _write_jsonl(up1, _MOCK_UNPAYWALL)
        _write_jsonl(up2, _MOCK_UNPAYWALL_INC)
        _write_jsonl(oa1, _MOCK_OPENALEX)

        # —— 校验器:文件存在且首条能解析出 DOI ——
        v = verify_snapshot_file("unpaywall", up1)
        assert v["ok"] and v["sample_doi"] == "10.1/aaa", v
        assert verify_snapshot_file("unpaywall", os.path.join(td, "nope.jsonl"))["exists"] is False

        # —— 普通灌库(Unpaywall)+ 本地查询 ——
        s1 = ingest_snapshot("unpaywall", up1, db)
        assert s1["mode"] == "full" and s1["processed"] == 2, s1
        assert s1["db_total"] == 2, s1
        rec_a = snapshot.lookup(db, "10.1/aaa")
        assert rec_a and rec_a["pdf_url"] == "https://ex.org/aaa.pdf", rec_a
        assert snapshot.lookup(db, "10.1/bbb")["oa_status"] == "green"
        assert _count(db) == 2

        # —— 增量 + --since:aaa 已存在→跳过,ddd 早于 since→跳过,只灌 ccc ——
        s2 = ingest_snapshot("unpaywall", up2, db, incremental=True, since="2020-01-01")
        assert s2["mode"] == "incremental", s2
        assert s2["seen"] == 3, s2
        assert s2["skipped_existing"] == 1, s2
        assert s2["skipped_date"] == 1, s2
        assert s2["kept"] == 1 and s2["processed"] == 1, s2
        assert snapshot.lookup(db, "10.1/ccc")["pdf_url"] == "https://ex.org/ccc.pdf"
        assert snapshot.lookup(db, "10.1/ddd") is None  # 被日期过滤,未入库
        assert _count(db) == 3

        # —— 增量(不设 since):aaa/ccc 已存在→跳过,补入 ddd ——
        s3 = ingest_snapshot("unpaywall", up2, db, incremental=True)
        assert s3["skipped_existing"] == 2 and s3["skipped_date"] == 0, s3
        assert s3["kept"] == 1, s3
        assert snapshot.lookup(db, "10.1/ddd")["pdf_url"] == "https://ex.org/ddd.pdf"
        assert _count(db) == 4

        # —— OpenAlex 分支 + DOI(URL 形态)归一化 ——
        db_oa = os.path.join(td, "oa2.sqlite")
        s4 = ingest_snapshot("openalex", oa1, db_oa)
        assert s4["processed"] == 1, s4
        rec_x = snapshot.lookup(db_oa, "10.2/xyz")
        assert rec_x and rec_x["pdf_url"] == "https://ex.org/xyz.pdf", rec_x

        # —— 复用 ingest 的 CLI 入库能力(捕获其 stdout 保持自检输出干净)——
        db_cli = os.path.join(td, "oa3.sqlite")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            s5 = ingest_snapshot("unpaywall", up1, db_cli, use_ingest_cli=True)
        assert s5["mode"] == "full-cli" and s5["rc"] == 0, s5
        assert "INGEST_DONE" in buf.getvalue(), buf.getvalue()
        assert snapshot.lookup(db_cli, "10.1/aaa")["pdf_url"] == "https://ex.org/aaa.pdf"

        # —— 增量对空库:全部作为新增 ——
        db_empty = os.path.join(td, "oa4.sqlite")
        s6 = ingest_snapshot("unpaywall", up1, db_empty, incremental=True)
        assert s6["skipped_existing"] == 0 and s6["kept"] == 2, s6
        assert _count(db_empty) == 2

        # —— 引导文本含关键 URL 与许可声明 ——
        g = guide_text()
        for token in ("s3://openalex", "CC0", "--no-sign-request", "unpaywall.org",
                      "data-feed", "download-all-data", "manifest.json"):
            assert token in g, f"引导文本缺少:{token}"
        env = check_env()
        assert "aws_cli_ready" in env and "gzip_supported" in env

    print("SNAPSHOT_BOOTSTRAP_OK")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_ingest(args: argparse.Namespace) -> int:
    kind = "unpaywall" if args.unpaywall else "openalex"
    path = args.unpaywall or args.openalex
    if not os.path.exists(path):
        print(f"错误:文件不存在:{path}", file=sys.stderr)
        return 2

    v = verify_snapshot_file(kind, path)
    print(f"[校验] {v['message']}", file=sys.stderr)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    log = logging.getLogger("snapshot_bootstrap")

    stats = ingest_snapshot(kind, path, args.db, incremental=args.incremental,
                            since=args.since, batch=args.batch,
                            use_ingest_cli=args.use_ingest_cli, log=log)
    detail = " ".join(f"{k}={v}" for k, v in stats.items())
    print(f"SNAPSHOT_BOOTSTRAP_INGEST db={args.db} kind={kind} {detail}")
    return 0


def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:  # 无参数默认自检(便于 `python -m fulltext_fetcher.snapshot_bootstrap`)
        return _selftest()

    p = argparse.ArgumentParser(
        prog="fulltext_fetcher.snapshot_bootstrap",
        description="官方快照→本地 SQLite 的引导 + 增量灌库(复用 ingest/snapshot 现有能力)。",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pg = sub.add_parser("guide", help="打印官方快照获取指引(URL + 许可)")
    pg.add_argument("--check-env", action="store_true", help="附带离线检测本机 aws CLI 等前置条件")

    pi = sub.add_parser("ingest", help="把本地快照文件灌入 SQLite(复用 ingest 入库能力)")
    grp = pi.add_mutually_exclusive_group(required=True)
    grp.add_argument("--unpaywall", help="本地 Unpaywall 快照 JSONL(.gz) 路径")
    grp.add_argument("--openalex", help="本地 OpenAlex works JSONL(.gz) 路径")
    pi.add_argument("--db", required=True, help="输出 SQLite 路径")
    pi.add_argument("--incremental", action="store_true", help="跳过 DB 中已存在的 DOI")
    pi.add_argument("--since", help="仅灌更新日期 >= 该值(YYYY-MM-DD)的记录,配合 --incremental")
    pi.add_argument("--batch", type=int, default=5000, help="批量提交条数(默认 5000)")
    pi.add_argument("--use-ingest-cli", action="store_true",
                    help="普通模式改为直接调用 python -m fulltext_fetcher.ingest 的 CLI 入库")

    sub.add_parser("selftest", help="离线自检(mock 数据灌库→查询→断言)")

    args = p.parse_args(argv)
    if args.cmd == "guide":
        print_guide(with_env=args.check_env)
        return 0
    if args.cmd == "ingest":
        return _cmd_ingest(args)
    if args.cmd == "selftest":
        return _selftest()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
