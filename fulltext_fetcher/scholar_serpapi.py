"""SerpApi Google Scholar 客户端(可选源、默认关闭、需自备 key)。

路线图 B1「合规命中『谷歌学术检索』字面目标」:以 SerpApi 的 Google Scholar API 作为
一个**可选**客户端,按标题 / DOI 查 Google Scholar 结果(标题、落地链接、
publication_info、被引数、版本数,以及 ``resources`` 里 ``file_format=PDF`` 的直链)。

合规声明
========
SerpApi 是**合规商业 API**:由 SerpApi 替你**合法**访问 Google Scholar、并在其一侧处理
验证码 / 反爬 / 代理。本模块自身**绝不**做任何自建反爬、直抓 Scholar、绕过人机验证的行为
——它只是老实地把检索词交给 SerpApi、再解析 SerpApi 返回的结构化 JSON。

**默认关闭**:未提供 api_key(函数参数或 ``SERPAPI_KEY`` 环境变量)时,:func:`search_scholar`
直接返回 ``{"available": False, "reason": "need SERPAPI_KEY", "results": []}`` 且**不发起任何
网络请求**;因此用户不主动配置并自备 key,本客户端永不激活。

依赖
====
仅依赖 ``requests``(已是本项目既有依赖),且为**延迟导入**:解析与自检路径零依赖、可完全
离线运行。不引入任何新的强制依赖。

CLI
===
    python -m fulltext_fetcher.scholar_serpapi "标题或DOI" --key <SERPAPI_KEY>
    SERPAPI_KEY=xxx python -m fulltext_fetcher.scholar_serpapi "标题或DOI"
    python -m fulltext_fetcher.scholar_serpapi --selftest   # 不联网自检,打印 SCHOLAR_SERPAPI_OK

字段路径依据 SerpApi Google Scholar Organic Results 文档(2026-07 核验):
``organic_results[].{position,title,result_id,link,snippet}``、
``publication_info.{summary,authors[].name}``、
``inline_links.cited_by.total``、``inline_links.versions.total``、
``resources[].{title,file_format,link}``、失败时顶层 ``error``。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

SERPAPI_ENDPOINT = "https://serpapi.com/search"
SERPAPI_ENGINE = "google_scholar"
SERPAPI_KEY_ENV = "SERPAPI_KEY"
DEFAULT_TIMEOUT = 30.0
MAX_NUM = 20  # SerpApi Google Scholar 单页上限


@dataclass
class ScholarResult:
    """一条 Google Scholar 结果(经 SerpApi 解析后的结构化视图,字段尽力填充、可空)。"""

    title: Optional[str] = None
    link: Optional[str] = None                       # 主链接 / 落地页
    result_id: Optional[str] = None
    snippet: Optional[str] = None
    publication_info: Optional[str] = None           # "作者 - 期刊, 年 - 站点" 摘要串
    authors: List[str] = field(default_factory=list)
    cited_by: Optional[int] = None                   # 被引数
    versions: Optional[int] = None                   # 版本数
    pdf_links: List[str] = field(default_factory=list)      # resources 里 file_format=PDF 的直链
    resources: List[Dict[str, Any]] = field(default_factory=list)  # 原始 resources(title/file_format/link)
    position: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _as_int(value: Any) -> Optional[int]:
    """把可能是 int / 数字字符串 / None 的被引数、版本数安全转 int。"""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_result(item: Optional[Dict[str, Any]]) -> ScholarResult:
    """把单条 SerpApi ``organic_result`` 解析为 :class:`ScholarResult`(防御式,绝不抛)。"""
    item = item or {}
    pub = item.get("publication_info") or {}

    authors: List[str] = []
    for a in (pub.get("authors") or []):
        name = (a or {}).get("name")
        if name:
            authors.append(name)

    inline = item.get("inline_links") or {}
    cited_by = _as_int((inline.get("cited_by") or {}).get("total"))
    versions = _as_int((inline.get("versions") or {}).get("total"))

    resources: List[Dict[str, Any]] = []
    pdf_links: List[str] = []
    for res in (item.get("resources") or []):
        res = res or {}
        link = res.get("link")
        fmt = (res.get("file_format") or "").strip()
        resources.append({
            "title": res.get("title"),
            "file_format": fmt or None,
            "link": link,
        })
        if link and fmt.upper() == "PDF":
            pdf_links.append(link)

    return ScholarResult(
        title=item.get("title"),
        link=item.get("link"),
        result_id=item.get("result_id"),
        snippet=item.get("snippet"),
        publication_info=pub.get("summary"),
        authors=authors,
        cited_by=cited_by,
        versions=versions,
        pdf_links=pdf_links,
        resources=resources,
        position=_as_int(item.get("position")),
    )


def parse_organic_results(data: Optional[Dict[str, Any]]) -> List[ScholarResult]:
    """从 SerpApi 完整响应中取 ``organic_results`` 并逐条解析为 :class:`ScholarResult`。"""
    data = data or {}
    return [parse_result(it) for it in (data.get("organic_results") or [])]


def search_scholar(
    query: str,
    api_key: Optional[str] = None,
    num: int = 10,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    session: Any = None,
) -> Dict[str, Any]:
    """用 SerpApi 的 Google Scholar 引擎检索(可选、**默认关闭**、需 key)。

    返回统一信封 dict:

    - 未配置 key(默认关闭)::

        {"available": False, "reason": "need SERPAPI_KEY", "results": []}

    - 成功::

        {"available": True, "query": q, "count": n, "results": [ScholarResult.to_dict(), ...]}

    - 出错(HTTP / JSON / SerpApi error / 网络异常)::

        {"available": True, "error": "...", "results": []}

    :param query: 检索词(论文标题或 DOI)。
    :param api_key: SerpApi key;为空时回落到环境变量 ``SERPAPI_KEY``;仍为空则判定默认关闭。
    :param num: 返回条数(自动夹到 1..20)。
    :param timeout: 单请求超时秒。
    :param session: 可选、拥有 ``.get`` 的对象(如 ``requests.Session``),便于测试/复用连接。

    合规:仅调用 SerpApi 合规商业 API;绝不自建反爬 / 直抓 Scholar。
    """
    key = api_key or os.environ.get(SERPAPI_KEY_ENV)
    if not key:
        # 默认关闭:不联网、明确告知需自备 key。
        return {"available": False, "reason": "need SERPAPI_KEY", "results": []}

    q = (query or "").strip()
    if not q:
        return {"available": True, "error": "empty query", "results": []}

    try:
        import requests  # 延迟导入:解析 / 自检路径零依赖、可离线运行
    except ImportError:
        return {"available": True, "error": "requests not installed", "results": []}

    params = {
        "engine": SERPAPI_ENGINE,
        "q": q,
        "api_key": key,
        "num": max(1, min(int(num or 10), MAX_NUM)),
    }
    getter = session if session is not None else requests
    try:
        resp = getter.get(SERPAPI_ENDPOINT, params=params, timeout=timeout)
    except Exception as exc:  # 网络异常优雅降级,绝不把栈抛给调用方
        return {"available": True, "error": f"request failed: {exc}", "results": []}

    if getattr(resp, "status_code", None) != 200:
        return {"available": True, "error": f"http {getattr(resp, 'status_code', '?')}", "results": []}
    try:
        data = resp.json()
    except ValueError:
        return {"available": True, "error": "invalid json", "results": []}

    if isinstance(data, dict) and data.get("error"):
        # SerpApi 在 key 无效 / 无结果等情形下于顶层放 error 串。
        return {"available": True, "error": str(data["error"]), "results": []}

    results = parse_organic_results(data if isinstance(data, dict) else {})
    return {
        "available": True,
        "query": q,
        "count": len(results),
        "results": [r.to_dict() for r in results],
    }


# ── 不联网自检用的 mock SerpApi 响应(字段路径与真实 API 一致)────────────────
_MOCK_SERPAPI_RESPONSE: Dict[str, Any] = {
    "search_metadata": {"status": "Success"},
    "search_parameters": {"engine": "google_scholar", "q": "attention is all you need"},
    "organic_results": [
        {
            "position": 0,
            "title": "Attention is all you need",
            "result_id": "abc123",
            "link": "https://proceedings.example.com/attention",
            "snippet": "We propose a new simple network architecture, the Transformer ...",
            "publication_info": {
                "summary": "A Vaswani, N Shazeer, N Parmar - Advances in NIPS, 2017 - proceedings.example.com",
                "authors": [
                    {"name": "A Vaswani", "author_id": "aaa"},
                    {"name": "N Shazeer", "author_id": "bbb"},
                ],
            },
            "resources": [
                {"title": "example.com", "file_format": "PDF",
                 "link": "https://example.com/attention.pdf"},
            ],
            "inline_links": {
                "cited_by": {"total": 123456, "link": "https://scholar.example/cites",
                             "cites_id": "111"},
                "versions": {"total": 42, "link": "https://scholar.example/versions",
                             "cluster_id": "222"},
                "related_pages_link": "https://scholar.example/related",
            },
        },
        {
            "position": 1,
            "title": "A paywalled paper without pdf",
            "link": "https://publisher.example.com/paywalled",
            "publication_info": {"summary": "B Author - J Example, 2020 - publisher.example.com"},
            "inline_links": {"cited_by": {"total": "7"}},  # 字符串型总数也应被正确转 int
            "resources": [
                {"title": "publisher.example.com", "file_format": "HTML",
                 "link": "https://publisher.example.com/html"},
            ],
        },
        {  # 极简条目:大部分字段缺失,验证防御式解析不抛异常
            "title": "Bare entry",
        },
    ],
}


def _selftest() -> int:
    """不联网自检:解析 mock SerpApi JSON,断言 PDF 直链 / 被引数等解析正确。"""
    # 1) 解析 mock 响应
    results = parse_organic_results(_MOCK_SERPAPI_RESPONSE)
    assert len(results) == 3, results

    first = results[0]
    assert first.title == "Attention is all you need", first.title
    assert first.link == "https://proceedings.example.com/attention", first.link
    assert first.result_id == "abc123", first.result_id
    assert first.publication_info.startswith("A Vaswani"), first.publication_info
    assert first.authors == ["A Vaswani", "N Shazeer"], first.authors
    assert first.cited_by == 123456, first.cited_by            # 被引数(int)
    assert first.versions == 42, first.versions                # 版本数
    assert first.pdf_links == ["https://example.com/attention.pdf"], first.pdf_links
    assert first.position == 0, first.position

    second = results[1]
    assert second.pdf_links == [], second.pdf_links            # 非 PDF(HTML)资源不进 pdf_links
    assert second.cited_by == 7, second.cited_by               # 字符串 "7" → int 7
    assert second.versions is None, second.versions

    third = results[2]
    assert third.title == "Bare entry", third.title            # 极简条目全部可空、不抛
    assert third.pdf_links == [] and third.resources == [], third
    assert third.cited_by is None and third.authors == [], third

    # 2) to_dict 可 JSON 序列化
    payload = json.dumps([r.to_dict() for r in results], ensure_ascii=False)
    assert "attention.pdf" in payload, payload

    # 3) 默认关闭:无 key 时明确返回 available=False,且完全不联网(临时清空环境变量以稳定断言)
    saved = os.environ.pop(SERPAPI_KEY_ENV, None)
    try:
        off = search_scholar("anything", api_key=None)
        assert off == {"available": False, "reason": "need SERPAPI_KEY", "results": []}, off
    finally:
        if saved is not None:
            os.environ[SERPAPI_KEY_ENV] = saved

    # 4) 空响应 / None 防御
    assert parse_organic_results({}) == [], "empty dict should yield []"
    assert parse_organic_results(None) == [], "None should yield []"

    print("SCHOLAR_SERPAPI_OK")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m fulltext_fetcher.scholar_serpapi",
        description=("SerpApi Google Scholar 客户端(可选、默认关闭、需自备 SERPAPI_KEY)。"
                     "SerpApi 合规访问 Scholar;本模块绝不自建反爬 / 直抓。"),
    )
    ap.add_argument("query", nargs="?", help="检索词:论文标题或 DOI")
    ap.add_argument("--key", default=None,
                    help=f"SerpApi key(不填则读环境变量 {SERPAPI_KEY_ENV})")
    ap.add_argument("--num", type=int, default=10, help="返回条数(1-20,默认 10)")
    ap.add_argument("--selftest", action="store_true", help="不联网自检并退出")
    args = ap.parse_args(argv)

    if args.selftest or not args.query:
        return _selftest()

    resp = search_scholar(args.query, api_key=args.key, num=args.num)
    print(json.dumps(resp, ensure_ascii=False, indent=2))
    if not resp.get("available"):
        print(f"[提示] SerpApi 客户端默认关闭:请用 --key 传入,或设置环境变量 {SERPAPI_KEY_ENV}。",
              file=sys.stderr)
        return 2
    if resp.get("error"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
