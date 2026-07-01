"""引用指标源(免费合规):给定 DOI / 标题 → 被引数 + 版本 / 相关记录。

对齐 Google Scholar 原生口径中的「被引次数 / All N versions」。本模块为**独立能力**,
本轮不接入主流程(pipeline / sources 注册表),仅提供纯函数 + 自测,便于后续集成拍统一接线。

数据源(均为免费 API,礼貌 mailto / 可选 key):
  1. OpenAlex          /works/doi:<doi> 或 /works?filter=title.search:<t>
                       → cited_by_count、locations[](版本)、related_works(相关记录)
  2. Semantic Scholar  Graph API /paper/DOI:<doi> 或 /paper/search
                       → citationCount(回退口径,可选 x-api-key)

设计约束:
  - 纯 requests,不依赖项目内 http_client / sources(保持独立、可离线单测)。
  - 全程容错:网络异常 / 非 200 / JSON 解析失败 → {"available": False, "error": ...},绝不抛出。
  - CLI: python -m fulltext_fetcher.citations "10.1038/xxxxx"
         python -m fulltext_fetcher.citations selftest   # 离线自测(打印 CITATIONS_OK)
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

import requests

OPENALEX_WORKS = "https://api.openalex.org/works"
S2_GRAPH_PAPER = "https://api.semanticscholar.org/graph/v1/paper"
S2_FIELDS = "citationCount,referenceCount,externalIds,title,year"

_DEFAULT_EMAIL = "anonymous@example.com"
_TIMEOUT = 30.0
_UA = "fulltext_fetcher-citations/1.0 (mailto:{email})"


def _ua(email: Optional[str]) -> str:
    return _UA.format(email=email or _DEFAULT_EMAIL)


def _clean_doi(doi: Optional[str]) -> str:
    """归一化 DOI:去空白、剥离 https://doi.org/ 与 doi: 前缀。"""
    d = (doi or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if d.lower().startswith(prefix):
            d = d[len(prefix):]
            break
    return d.strip()


def _http_get_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Optional[Any]:
    """GET → JSON;任何异常 / 非 200 / 非 JSON → None(绝不抛)。

    单独抽出以便离线 selftest 通过 monkeypatch 本函数注入假响应。
    """
    try:
        r = requests.get(url, params=params, headers=headers, timeout=_TIMEOUT)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


# ── 解析(纯函数,可直接单测)────────────────────────────────────────────────
def _parse_openalex(work: Any) -> Optional[Dict[str, Any]]:
    """解析 OpenAlex work JSON → 指标 dict;无有效被引字段 → None。"""
    if not isinstance(work, dict):
        return None
    cited = work.get("cited_by_count")
    if not isinstance(cited, int):
        return None
    versions: List[Dict[str, Any]] = []
    for loc in (work.get("locations") or []):
        if not isinstance(loc, dict):
            continue
        src = loc.get("source")
        versions.append({
            "source": src.get("display_name") if isinstance(src, dict) else None,
            "version": loc.get("version"),
            "landing_page_url": loc.get("landing_page_url"),
            "pdf_url": loc.get("pdf_url"),
            "is_oa": loc.get("is_oa"),
        })
    vc = work.get("locations_count")
    versions_count = vc if isinstance(vc, int) else len(versions)
    related = [w for w in (work.get("related_works") or []) if isinstance(w, str)]
    return {
        "available": True,
        "cited_by_count": cited,
        "versions": versions,
        "versions_count": versions_count,
        "related_ids": related,
        "source": "openalex",
        "id": work.get("id"),
    }


def _parse_semantic_scholar(paper: Any) -> Optional[Dict[str, Any]]:
    """解析 Semantic Scholar paper JSON → 指标 dict;无 citationCount → None。"""
    if not isinstance(paper, dict):
        return None
    cited = paper.get("citationCount")
    if not isinstance(cited, int):
        return None
    ext = paper.get("externalIds") if isinstance(paper.get("externalIds"), dict) else {}
    return {
        "available": True,
        "cited_by_count": cited,
        "versions": [],  # S2 无版本聚合口径
        "versions_count": 0,
        "related_ids": [],
        "source": "semantic_scholar",
        "id": paper.get("paperId") or ext.get("DOI"),
    }


# ── 取数(HTTP + 解析)────────────────────────────────────────────────────
def _fetch_openalex(
    doi: Optional[str] = None, title: Optional[str] = None, email: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    headers = {"User-Agent": _ua(email)}
    params: Dict[str, Any] = {"mailto": email or _DEFAULT_EMAIL}
    if doi:
        data = _http_get_json(f"{OPENALEX_WORKS}/doi:{_clean_doi(doi)}", params, headers)
        work = data if (isinstance(data, dict) and data.get("id")) else None
    elif title:
        params.update({"filter": f"title.search:{title}", "per_page": 1})
        data = _http_get_json(OPENALEX_WORKS, params, headers)
        results = data.get("results") if isinstance(data, dict) else None
        work = results[0] if (isinstance(results, list) and results) else None
    else:
        return None
    return _parse_openalex(work)


def _fetch_semantic_scholar(
    doi: Optional[str] = None, title: Optional[str] = None, s2_key: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    headers = {"User-Agent": _ua(None)}
    if s2_key:
        headers["x-api-key"] = s2_key
    if doi:
        data = _http_get_json(
            f"{S2_GRAPH_PAPER}/DOI:{_clean_doi(doi)}", {"fields": S2_FIELDS}, headers
        )
        paper = data if (isinstance(data, dict) and "citationCount" in data) else None
    elif title:
        data = _http_get_json(
            f"{S2_GRAPH_PAPER}/search", {"query": title, "limit": 1, "fields": S2_FIELDS}, headers
        )
        results = data.get("data") if isinstance(data, dict) else None
        paper = results[0] if (isinstance(results, list) and results) else None
    else:
        return None
    return _parse_semantic_scholar(paper)


def get_citation_metrics(
    doi: Optional[str] = None,
    title: Optional[str] = None,
    email: Optional[str] = None,
    s2_key: Optional[str] = None,
) -> Dict[str, Any]:
    """查询被引数 + 版本 / 相关记录。优先 OpenAlex,回退 Semantic Scholar。

    参数:
      doi    : DOI(优先键,命中率与准确度最高)
      title  : 标题(无 DOI 时的回退检索键)
      email  : OpenAlex mailto 礼貌池邮箱(建议填真实邮箱)
      s2_key : Semantic Scholar API key(可选,提高额度)

    返回 dict(**永不抛异常**):
      成功 → {"available": True, "cited_by_count": int,
              "versions": [ {source, version, landing_page_url, pdf_url, is_oa}, ... ],
              "versions_count": int, "related_ids": [str, ...],
              "source": "openalex" | "semantic_scholar", "id": str,
              "doi": <入参>, "title": <入参>}
      失败 → {"available": False, "error": <原因>, "doi": <入参>, "title": <入参>}
    """
    if not doi and not title:
        return {"available": False, "error": "need doi or title", "doi": doi, "title": title}

    for fetch in (
        lambda: _fetch_openalex(doi=doi, title=title, email=email),
        lambda: _fetch_semantic_scholar(doi=doi, title=title, s2_key=s2_key),
    ):
        try:
            result = fetch()
        except Exception as exc:  # 防御:任何未预期异常都降级为「无此源结果」,继续回退
            result = None
            _last_error = repr(exc)  # noqa: F841 (仅用于就地排查)
        if result is not None:
            result["doi"] = doi
            result["title"] = title
            return result

    return {
        "available": False,
        "error": "no metrics from OpenAlex or Semantic Scholar",
        "doi": doi,
        "title": title,
    }


# ── CLI ──────────────────────────────────────────────────────────────────
def _main(argv: List[str]) -> int:
    doi: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    s2_key: Optional[str] = None
    positionals: List[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--title", "--email", "--s2-key") and i + 1 < len(argv):
            val = argv[i + 1]
            i += 2
        elif arg.startswith(("--title=", "--email=", "--s2-key=")):
            arg, val = arg.split("=", 1)
            i += 1
        else:
            positionals.append(arg)
            i += 1
            continue
        if arg == "--title":
            title = val
        elif arg == "--email":
            email = val
        elif arg == "--s2-key":
            s2_key = val
    if positionals:
        doi = positionals[0]
    if not doi and not title:
        print(
            'usage: python -m fulltext_fetcher.citations "10.xxxx/xxx" '
            '[--title "..."] [--email you@org] [--s2-key KEY]\n'
            "       python -m fulltext_fetcher.citations selftest",
            file=sys.stderr,
        )
        return 2
    res = get_citation_metrics(doi=doi, title=title, email=email, s2_key=s2_key)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("available") else 1


# ── 离线自测(不联网,monkeypatch HTTP)────────────────────────────────────
def _selftest() -> None:
    real = _http_get_json

    def patch(fn) -> None:
        globals()["_http_get_json"] = fn

    _OA = {
        "id": "https://openalex.org/W123",
        "cited_by_count": 42,
        "locations_count": 3,
        "locations": [
            {"version": "publishedVersion", "is_oa": True,
             "landing_page_url": "https://pub/x", "pdf_url": "https://pub/x.pdf",
             "source": {"display_name": "Journal X"}},
            {"version": "submittedVersion", "is_oa": True,
             "landing_page_url": "https://arxiv.org/abs/1", "pdf_url": "https://arxiv.org/pdf/1",
             "source": {"display_name": "arXiv"}},
            "not-a-dict-should-be-skipped",
        ],
        "related_works": ["https://openalex.org/W9", "https://openalex.org/W8", 123],
    }
    _S2 = {"paperId": "S2abc", "citationCount": 7, "externalIds": {"DOI": "10.1/x"}}

    try:
        # 1) 纯解析:OpenAlex
        p = _parse_openalex(_OA)
        assert p and p["cited_by_count"] == 42 and p["source"] == "openalex", p
        assert p["versions_count"] == 3, p["versions_count"]
        assert len(p["versions"]) == 2, p["versions"]  # 非 dict 的 location 被跳过
        assert p["versions"][1]["source"] == "arXiv", p["versions"][1]
        assert p["related_ids"] == ["https://openalex.org/W9", "https://openalex.org/W8"], p["related_ids"]
        assert _parse_openalex({"id": "x"}) is None      # 无 cited_by_count
        assert _parse_openalex("nope") is None           # 非 dict

        # 2) 纯解析:Semantic Scholar
        q = _parse_semantic_scholar(_S2)
        assert q and q["cited_by_count"] == 7 and q["source"] == "semantic_scholar", q
        assert q["versions"] == [] and q["versions_count"] == 0, q
        assert q["id"] == "S2abc", q
        assert _parse_semantic_scholar({"paperId": "y"}) is None

        # 3) get_citation_metrics 走 OpenAlex(monkeypatch HTTP)
        patch(lambda url, params=None, headers=None: _OA if "openalex.org" in url else None)
        r = get_citation_metrics(doi="10.1234/abc", email="me@test.org")
        assert r["available"] is True and r["source"] == "openalex", r
        assert r["cited_by_count"] == 42 and r["doi"] == "10.1234/abc", r

        # 4) OpenAlex 无数据 → 回退 Semantic Scholar
        def _fallback(url, params=None, headers=None):
            if "openalex.org" in url:
                return None
            if "semanticscholar.org" in url:
                return _S2
            raise AssertionError("unexpected url: " + url)
        patch(_fallback)
        r2 = get_citation_metrics(doi="10.1234/abc")
        assert r2["available"] is True and r2["source"] == "semantic_scholar", r2
        assert r2["cited_by_count"] == 7, r2

        # 5) 两源皆无 → available False(且不抛)
        patch(lambda *a, **k: None)
        r3 = get_citation_metrics(doi="10.1234/none")
        assert r3["available"] is False and "error" in r3, r3

        # 6) 缺 doi/title → available False
        r4 = get_citation_metrics()
        assert r4["available"] is False and r4["error"] == "need doi or title", r4

        # 7) 标题检索路径(OpenAlex results 包裹 / S2 data 包裹)
        patch(lambda url, params=None, headers=None: {"results": [_OA]} if "openalex.org" in url else None)
        r5 = get_citation_metrics(title="Deep Residual Learning")
        assert r5["available"] is True and r5["cited_by_count"] == 42 and r5["title"], r5

        patch(lambda url, params=None, headers=None: {"data": [_S2]} if "semanticscholar.org" in url else None)
        r6 = get_citation_metrics(title="Attention Is All You Need")
        assert r6["available"] is True and r6["source"] == "semantic_scholar", r6

        # 8) DOI 归一化
        assert _clean_doi("https://doi.org/10.1/x") == "10.1/x"
        assert _clean_doi("doi:10.2/y") == "10.2/y"
        assert _clean_doi("  10.3/z  ") == "10.3/z"

        # 9) 单源异常也被吞掉、继续回退
        def _oa_raises(url, params=None, headers=None):
            if "openalex.org" in url:
                raise RuntimeError("boom")
            return _S2
        patch(_oa_raises)
        r7 = get_citation_metrics(doi="10.1234/abc")
        assert r7["available"] is True and r7["source"] == "semantic_scholar", r7
    finally:
        globals()["_http_get_json"] = real

    print("CITATIONS_OK")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "selftest":
        _selftest()
    else:
        raise SystemExit(_main(sys.argv[1:]))
