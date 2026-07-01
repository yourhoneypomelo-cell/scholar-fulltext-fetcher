"""子包核心数据结构（冻结契约，见《谷歌学术爬虫-架构与选型.md》§3.1）。

全部用 @dataclass 且带 to_dict()，便于序列化进结构化日志 / 复用父包 report。
本文件是全子包地基：字段名/语义一旦冻结不得擅改，变更须经总指挥并同步架构文档。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ScholarResult:
    """一条 Google Scholar 结果（SERP 解析或 SerpApi 解析后的统一视图；字段尽力填充、可空）。"""
    title: Optional[str] = None
    link: Optional[str] = None                     # 主/落地链接
    result_id: Optional[str] = None                # Scholar result_id / cluster 标识
    snippet: Optional[str] = None
    publication_info: Optional[str] = None         # "作者 - 期刊, 年 - 站点" 摘要串
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    cited_by: Optional[int] = None                 # 被引数
    versions: Optional[int] = None                 # 版本数
    cluster_id: Optional[str] = None               # 版本簇 id（取全部版本用）
    pdf_links: List[str] = field(default_factory=list)          # 结果自带 PDF 直链
    resources: List[Dict[str, Any]] = field(default_factory=list)  # 原始 resources(title/format/link)
    position: Optional[int] = None
    origin: str = "serp"                           # 来源路径: 'serp'(自建HTML) | 'serpapi'(商业API)
    doi: Optional[str] = None                      # 若能从链接/富化得到

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScholarQuery:
    """一次 Scholar 检索的规范化描述（由 query 模块构造，供 serp.build_scholar_url 使用）。"""
    raw: str                                       # 原始输入
    kind: str                                      # 'title' | 'doi' | 'freeform'
    q: str                                         # 传给 Scholar 的 q 串
    num: int = 10                                  # 期望条数
    start: int = 0                                 # 分页偏移（每页 10）
    year_low: Optional[int] = None
    year_high: Optional[int] = None
    lang: str = "en"                               # hl 参数
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SerpPage:
    """一页 SERP 的解析产物 + 元信息。"""
    results: List[ScholarResult] = field(default_factory=list)
    has_next: bool = False
    total_hint: Optional[int] = None
    blocked: bool = False                          # 命中验证码/风控页
    raw_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)                        # asdict 递归转换 results 内的 ScholarResult


@dataclass
class FetchOutcome:
    """fetcher 取回一个 URL 的统一信封（无论哪层引擎）。"""
    ok: bool = False
    html: Optional[str] = None
    final_url: Optional[str] = None
    status: Optional[int] = None
    engine: Optional[str] = None                   # 命中层: 'curl_cffi'|'nodriver'|'patchright'|'serpapi'
    blocked: bool = False                          # 命中验证/风控页
    captcha: bool = False
    proxy_used: Optional[str] = None
    elapsed_ms: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScholarFetchResult:
    """一条输入的最终结果（对齐父包 FetchResult，便于复用 report/CSV）。"""
    raw_input: str
    kind: Optional[str] = None
    query: Optional[str] = None
    title: Optional[str] = None
    doi: Optional[str] = None
    success: bool = False                          # 是否下到合规校验通过的 PDF
    pdf_path: Optional[str] = None
    pdf_bytes: int = 0
    pdf_url: Optional[str] = None
    source_used: Optional[str] = None              # 'scholar-pdf'|'oa:unpaywall'|...
    cited_by: Optional[int] = None
    n_results: int = 0
    engine_used: Optional[str] = None              # 取 SERP 命中的反爬层
    blocked: bool = False
    elapsed_ms: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


if __name__ == "__main__":  # 不联网 selftest: python -m fulltext_fetcher.scholar.models
    # —— ScholarResult:默认值 + to_dict + 字段齐全 ——
    r = ScholarResult(title="T", link="https://x/p", cited_by=12,
                      pdf_links=["https://x/p.pdf"], authors=["A", "B"])
    d = r.to_dict()
    assert d["title"] == "T" and d["cited_by"] == 12
    assert d["pdf_links"] == ["https://x/p.pdf"] and d["authors"] == ["A", "B"]
    assert d["origin"] == "serp" and d["resources"] == [] and d["doi"] is None
    _expect = {"title", "link", "result_id", "snippet", "publication_info", "authors",
               "year", "venue", "cited_by", "versions", "cluster_id", "pdf_links",
               "resources", "position", "origin", "doi"}
    assert set(d.keys()) == _expect, set(d.keys()) ^ _expect
    # 可变默认独立(无共享可变默认坑)
    r2 = ScholarResult()
    r2.authors.append("z")
    assert ScholarResult().authors == [], "可变默认必须每实例独立"

    # —— ScholarQuery ——
    q = ScholarQuery(raw="Attention", kind="title", q="Attention", num=5)
    assert q.to_dict()["start"] == 0 and q.lang == "en" and q.extra == {}

    # —— SerpPage:to_dict 递归把 results 转 dict ——
    page = SerpPage(results=[ScholarResult(title="A"), ScholarResult(title="B")], has_next=True)
    pd = page.to_dict()
    assert pd["has_next"] is True and len(pd["results"]) == 2
    assert isinstance(pd["results"][0], dict) and pd["results"][0]["title"] == "A"

    # —— FetchOutcome ——
    fo = FetchOutcome(ok=True, engine="curl_cffi", status=200, html="<html>")
    assert fo.to_dict()["engine"] == "curl_cffi" and fo.blocked is False

    # —— ScholarFetchResult(对齐父包 FetchResult 关键字段) ——
    fr = ScholarFetchResult(raw_input="10.1/x", success=True, source_used="scholar-pdf")
    frd = fr.to_dict()
    assert frd["raw_input"] == "10.1/x" and frd["success"] is True
    assert frd["pdf_bytes"] == 0 and frd["n_results"] == 0 and frd["blocked"] is False

    print("MODELS_OK")
