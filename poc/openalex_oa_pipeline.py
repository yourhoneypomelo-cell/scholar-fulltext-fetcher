#!/usr/bin/env python3
"""角度2 主线 PoC：开放学术 API「检索 → 定位 OA 全文 → 下载入库」流水线。

数据源：
  - OpenAlex  （发现 + 结构化元数据 + 开放获取直链）
  - Unpaywall （当 OpenAlex 未直接给出 PDF 时，用 DOI 兜底定位 OA 全文）

设计依据见同目录《检索成果-角度2-官方开放API替代路线》：开放 API 不存在人机验证，
合规、稳定、字段齐全。仅依赖 requests；OpenAlex 基础检索匿名可用，带 --email
进入礼貌池更稳更快。付费墙内全文无法获取（合理边界），本工具只取开放获取 PDF。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

OPENALEX_WORKS = "https://api.openalex.org/works"
UNPAYWALL_BASE = "https://api.unpaywall.org/v2/"
DEFAULT_TIMEOUT = 30


def _session(email: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {"User-Agent": f"scholar-oa-poc/1.0 (mailto:{email or 'anonymous@example.com'})"}
    )
    return s


def search_openalex(sess, query, email, max_results=25, year_from=None,
                    oa_only=False, api_key=None, page_size=50, pause=1.0):
    """游标分页拉取 OpenAlex works，返回精简后的记录列表。"""
    filters = []
    if year_from:
        filters.append(f"from_publication_date:{year_from}-01-01")
    if oa_only:
        filters.append("is_oa:true")

    params = {"search": query, "cursor": "*"}
    if filters:
        params["filter"] = ",".join(filters)
    if email:
        params["mailto"] = email
    if api_key:
        params["api_key"] = api_key

    out = []
    while len(out) < max_results:
        params["per-page"] = min(page_size, max_results - len(out))
        r = sess.get(OPENALEX_WORKS, params=params, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        if not results:
            break
        for w in results:
            out.append(_slim_work(w))
            if len(out) >= max_results:
                break
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break
        params["cursor"] = cursor
        time.sleep(pause)
    return out


def _slim_work(w: dict) -> dict:
    oa = w.get("open_access") or {}
    best = w.get("best_oa_location") or {}
    primary = w.get("primary_location") or {}
    doi = (w.get("doi") or "").replace("https://doi.org/", "") or None
    authors = [a.get("author", {}).get("display_name")
               for a in (w.get("authorships") or [])]
    pdf_url = best.get("pdf_url") or primary.get("pdf_url") or oa.get("oa_url")
    return {
        "openalex_id": w.get("id"),
        "doi": doi,
        "title": w.get("display_name"),
        "year": w.get("publication_year"),
        "authors": [a for a in authors if a],
        "is_oa": oa.get("is_oa", False),
        "oa_status": oa.get("oa_status"),
        "cited_by_count": w.get("cited_by_count"),
        "pdf_url": pdf_url,
        "landing_page": primary.get("landing_page_url"),
    }


def unpaywall_pdf(sess, doi, email):
    """用 DOI 向 Unpaywall 兜底定位 OA PDF 直链；失败返回 None。"""
    if not doi or not email:
        return None
    try:
        r = sess.get(f"{UNPAYWALL_BASE}{doi}", params={"email": email},
                     timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return None
        loc = (r.json() or {}).get("best_oa_location") or {}
        return loc.get("url_for_pdf")
    except requests.RequestException:
        return None


def _safe_name(s: str, maxlen=120) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff\- ]+", "_", s or "untitled").strip()
    return (s[:maxlen] or "untitled").rstrip(". ")


def download_pdf(sess, url, dest: Path) -> bool:
    """流式下载 PDF；跳过明显的 HTML 错误页；落地小于 1KB 视为失败。"""
    try:
        with sess.get(url, stream=True, timeout=DEFAULT_TIMEOUT) as r:
            if r.status_code != 200:
                return False
            if "html" in r.headers.get("Content-Type", "").lower():
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 14):
                    if chunk:
                        f.write(chunk)
        return dest.exists() and dest.stat().st_size > 1024
    except requests.RequestException:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="开放 API 学术检索→定位 OA→下载入库 PoC（角度2 主线）")
    ap.add_argument("query", help='检索关键词，例如 "large language model"')
    ap.add_argument("--email", required=True,
                    help="你的真实邮箱（Unpaywall 必填且拒占位邮箱；OpenAlex 2026 mailto 已弱化，建议配 --api-key）")
    ap.add_argument("--max", type=int, default=25, help="最多处理多少条（默认 25）")
    ap.add_argument("--year-from", type=int, default=None, help="起始出版年（含）")
    ap.add_argument("--oa-only", action="store_true", help="只要开放获取文献")
    ap.add_argument("--api-key", default=None, help="OpenAlex API key（可选）")
    ap.add_argument("--out", default="out", help="输出目录（默认 ./out）")
    ap.add_argument("--no-download", action="store_true", help="只拉元数据、不下载 PDF")
    args = ap.parse_args(argv)

    sess = _session(args.email)
    out_dir = Path(args.out)
    pdf_dir = out_dir / "pdfs"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/3] OpenAlex 检索：{args.query!r} ...", file=sys.stderr)
    try:
        works = search_openalex(sess, args.query, args.email, max_results=args.max,
                                year_from=args.year_from, oa_only=args.oa_only,
                                api_key=args.api_key)
    except requests.HTTPError as e:
        print(f"OpenAlex 请求失败：{e}", file=sys.stderr)
        return 2
    print(f"      命中 {len(works)} 条。", file=sys.stderr)

    print("[2/3] 定位 OA 全文并下载入库 ...", file=sys.stderr)
    records, n_pdf = [], 0
    for i, w in enumerate(works, 1):
        pdf_url = w["pdf_url"]
        if not pdf_url and w["doi"]:
            pdf_url = unpaywall_pdf(sess, w["doi"], args.email)
            w["pdf_url"] = pdf_url
        status = "no-oa"
        if pdf_url and not args.no_download:
            fname = f"{i:03d}_{_safe_name(w['title'])}.pdf"
            if download_pdf(sess, pdf_url, pdf_dir / fname):
                w["pdf_file"] = (pdf_dir / fname).as_posix()
                n_pdf += 1
                status = "downloaded"
            else:
                status = "download-failed"
        elif pdf_url:
            status = "oa-found"
        print(f"  [{i:>3}/{len(works)}] {status:<15} {(w['title'] or '')[:70]}",
              file=sys.stderr)
        records.append(w)
        time.sleep(0.5)

    with open(out_dir / "metadata.jsonl", "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    summary = {
        "query": args.query,
        "total": len(records),
        "with_oa": sum(1 for r in records if r.get("pdf_url")),
        "downloaded": n_pdf,
    }
    with open(out_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[3/3] 完成：命中 {summary['total']}，有 OA 链接 {summary['with_oa']}，"
          f"成功下载 PDF {summary['downloaded']}。输出在 {out_dir}/", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
