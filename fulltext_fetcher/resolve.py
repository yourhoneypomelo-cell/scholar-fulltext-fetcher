"""输入解析:把原始输入(DOI / 标题 / arXiv id)判类型并解析成 Paper 元数据。

- DOI:直接走 OpenAlex 单条(免费)富化元数据,失败回退 Crossref。
- 标题:多源反查 DOI(Crossref bibliographic → OpenAlex search → Semantic Scholar search),
  按标题 Jaccard 相似度选最佳;任一源达阈值即命中,全部低置信时回退最权威源的第一条;再富化。
- arXiv:记录 arxiv_id;若同时拿到 DOI 顺带富化。
富化会补全 arxiv_id / pmid / pmcid / is_oa 等,供下游各源直接使用(减少重复定位)。
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .models import Paper, WorkInput

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.I)
_ARXIV_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
_ARXIV_OLD_RE = re.compile(r"^[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?$", re.I)


def classify_input(raw: str) -> WorkInput:
    s = (raw or "").strip()
    low = s.lower()
    if low.startswith("arxiv:"):
        return WorkInput(raw, "arxiv", s.split(":", 1)[1].strip())
    if "arxiv.org/" in low:
        tail = s.rstrip("/").split("/")[-1]
        tail = tail.replace(".pdf", "")
        return WorkInput(raw, "arxiv", tail)
    if "doi.org/" in low:
        return WorkInput(raw, "doi", s.split("doi.org/", 1)[1].strip())
    m = _DOI_RE.search(s)
    if m and (low.startswith("10.") or low.startswith("doi:")):
        return WorkInput(raw, "doi", m.group(0))
    if _ARXIV_RE.match(s) or _ARXIV_OLD_RE.match(s):
        return WorkInput(raw, "arxiv", s)
    if m and len(s) - len(m.group(0)) < 5:  # 看起来主要就是个 DOI
        return WorkInput(raw, "doi", m.group(0))
    return WorkInput(raw, "title", s)


def _normalize_doi(doi: str) -> str:
    return doi.strip().rstrip(".,);").lower()


def enrich_via_openalex(doi: str, client: Any, log: Any, cfg: Any) -> Optional[Paper]:
    params = {"mailto": cfg.email}
    if cfg.openalex_key:
        params["api_key"] = cfg.openalex_key
    data = client.get_json(f"https://api.openalex.org/works/doi:{doi}", params=params)
    if not data:
        return None
    ids = data.get("ids") or {}
    pmcid = ids.get("pmcid")
    if pmcid and "/" in pmcid:
        pmcid = pmcid.rstrip("/").split("/")[-1]
    pmid = ids.get("pmid")
    if pmid and "/" in pmid:
        pmid = pmid.rstrip("/").split("/")[-1]
    arxiv_id = None
    loc = data.get("primary_location") or {}
    src = (loc.get("source") or {}) if isinstance(loc, dict) else {}
    if src and (src.get("display_name") or "").lower() == "arxiv":
        landing = loc.get("landing_page_url") or ""
        mm = re.search(r"abs/([^\s/]+)", landing)
        if mm:
            arxiv_id = mm.group(1)
    oa = data.get("open_access") or {}
    authors = []
    for a in (data.get("authorships") or [])[:20]:
        nm = ((a.get("author") or {}).get("display_name"))
        if nm:
            authors.append(nm)
    return Paper(
        doi=doi,
        title=data.get("title") or data.get("display_name"),
        year=data.get("publication_year"),
        authors=authors,
        arxiv_id=arxiv_id,
        pmid=pmid,
        pmcid=pmcid,
        is_oa=oa.get("is_oa"),
        oa_status=oa.get("oa_status"),
        resolved_via="openalex",
    )


def enrich_via_crossref(doi: str, client: Any, log: Any, cfg: Any) -> Optional[Paper]:
    data = client.get_json(f"https://api.crossref.org/works/{doi}", params={"mailto": cfg.email})
    if not data:
        return None
    msg = data.get("message") or {}
    title = (msg.get("title") or [None])[0]
    year = None
    issued = (msg.get("issued") or {}).get("date-parts") or [[None]]
    if issued and issued[0]:
        year = issued[0][0]
    authors = []
    for a in (msg.get("author") or [])[:20]:
        nm = " ".join(x for x in [a.get("given"), a.get("family")] if x)
        if nm:
            authors.append(nm)
    return Paper(doi=doi, title=title, year=year, authors=authors,
                 journal=(msg.get("container-title") or [None])[0], resolved_via="crossref")


# ── 标题 → DOI:多源反查(Crossref → OpenAlex → Semantic Scholar)────────────
# 背景:Crossref search 端点 2026-03 起常 500 / 疑弃用(见 经验记录),单源易整体失灵。
# 故标题反查改为多源回退:任一源按标题 Jaccard 相似度达阈值即命中;全部低置信时,
# 回退到「最先返回候选的源(最权威)的第一条」(沿用旧策略的「最可信第一条」兜底)。
_TITLE_SIM_THRESHOLD = 0.6


def _title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _norm_title(t: str) -> str:
    """标题归一:小写、非词字符折叠为单空格、收尾去空白(供 Jaccard 比较)。"""
    return re.sub(r"\W+", " ", (t or "").lower()).strip()


def _best_candidate(norm_q: str, cands: list) -> tuple:
    """从 [(doi, title)] 候选里按标题 Jaccard 选最佳,返回 (doi, score)。"""
    best_doi, best_score = None, -1.0
    for doi, t in cands:
        score = _title_similarity(norm_q, _norm_title(t))
        if score > best_score:
            best_score, best_doi = score, doi
    return best_doi, best_score


def _doi_from_openalex(doi_url: Optional[str]) -> Optional[str]:
    """OpenAlex 的 doi 字段是 https://doi.org/<doi> 形式,剥成裸 DOI(归一化留给 resolve 阶段)。"""
    if not doi_url:
        return None
    d = doi_url.strip()
    low = d.lower()
    marker = "doi.org/"
    if marker in low:
        d = d[low.index(marker) + len(marker):]
    return d or None


def _crossref_title_candidates(title: str, client: Any, log: Any, cfg: Any) -> list:
    """Crossref bibliographic 反查,返回 [(doi, title)]。"""
    data = client.get_json(
        "https://api.crossref.org/works",
        params={"query.bibliographic": title, "rows": 5, "select": "DOI,title", "mailto": cfg.email},
    )
    items = ((data or {}).get("message") or {}).get("items") or []
    out = []
    for it in items:
        doi = it.get("DOI")
        if doi:
            out.append((doi, (it.get("title") or [""])[0]))
    return out


def _openalex_title_candidates(title: str, client: Any, log: Any, cfg: Any) -> list:
    """OpenAlex /works?search= 反查,返回 [(doi, title)](doi 已剥 https 前缀)。"""
    params = {"search": title, "per-page": 5, "select": "id,doi,display_name", "mailto": cfg.email}
    if cfg.openalex_key:
        params["api_key"] = cfg.openalex_key
    data = client.get_json("https://api.openalex.org/works", params=params)
    out = []
    for it in ((data or {}).get("results") or []):
        doi = _doi_from_openalex(it.get("doi"))
        if doi:
            out.append((doi, it.get("display_name") or it.get("title") or ""))
    return out


def _s2_title_candidates(title: str, client: Any, log: Any, cfg: Any) -> list:
    """Semantic Scholar graph/v1/paper/search 反查,返回 [(doi, title)]。"""
    headers = {"x-api-key": cfg.s2_key} if cfg.s2_key else None
    data = client.get_json(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={"query": title, "limit": 5, "fields": "title,externalIds"},
        headers=headers,
    )
    out = []
    for it in ((data or {}).get("data") or []):
        doi = (it.get("externalIds") or {}).get("DOI")
        if doi:
            out.append((doi, it.get("title") or ""))
    return out


# (via 标签, 候选函数):按可信度/历史命中率排序,依次回退。
_TITLE_SOURCES = (
    ("crossref", _crossref_title_candidates),
    ("openalex", _openalex_title_candidates),
    ("s2", _s2_title_candidates),
)


def title_to_doi(title: str, client: Any, log: Any, cfg: Any) -> tuple:
    """多源反查标题→DOI。返回 (doi, via);全失败返回 (None, None)。

    via ∈ {crossref-title, openalex-title, s2-title}。各源独立吞异常,单源失败 / 低置信
    不影响继续回退下一源;超时由 http_client 的退避与熔断兜底,不会拖垮整体。
    """
    norm_q = _norm_title(title)
    fallback = None  # (doi, via):最先返回候选的源的第一条,作低置信兜底
    for via, fn in _TITLE_SOURCES:
        try:
            cands = fn(title, client, log, cfg)
        except Exception as e:  # noqa: BLE001 - 单源解析异常不得拖垮整体回退
            if log is not None:
                log.warning("标题反查源 %s 异常: %s", via, e)
            cands = []
        if not cands:
            continue
        best_doi, best_score = _best_candidate(norm_q, cands)
        if best_doi and best_score >= _TITLE_SIM_THRESHOLD:
            return best_doi, f"{via}-title"
        if fallback is None:
            fallback = (cands[0][0], f"{via}-title")  # 该源第一条(最可信)留作兜底
    return fallback if fallback else (None, None)


def crossref_title_to_doi(title: str, client: Any, log: Any, cfg: Any) -> Optional[str]:
    """[兼容保留] 仅用 Crossref 单源反查标题→DOI;新代码请改用多源的 title_to_doi。"""
    cands = _crossref_title_candidates(title, client, log, cfg)
    if not cands:
        return None
    best_doi, best_score = _best_candidate(_norm_title(title), cands)
    if best_doi and best_score >= _TITLE_SIM_THRESHOLD:
        return best_doi
    return cands[0][0]  # 兜底取第一条


def resolve_to_paper(work: WorkInput, client: Any, log: Any, cfg: Any) -> Paper:
    if work.kind == "doi":
        doi = _normalize_doi(work.value)
        p = enrich_via_openalex(doi, client, log, cfg) or enrich_via_crossref(doi, client, log, cfg)
        if p:
            return p
        return Paper(doi=doi, resolved_via="none")
    if work.kind == "arxiv":
        aid = work.value.strip()
        doi = f"10.48550/arxiv.{aid.split('v')[0]}"
        p = enrich_via_openalex(doi, client, log, cfg)
        if p:
            p.arxiv_id = p.arxiv_id or aid
            return p
        return Paper(arxiv_id=aid, doi=doi, resolved_via="arxiv-id")
    # title:多源反查 DOI 再富化
    doi, via = title_to_doi(work.value, client, log, cfg)
    if doi:
        doi = _normalize_doi(doi)
        p = enrich_via_openalex(doi, client, log, cfg) or enrich_via_crossref(doi, client, log, cfg)
        if p:
            p.title = p.title or work.value
            return p
        return Paper(doi=doi, title=work.value, resolved_via=via or "crossref-title")
    return Paper(title=work.value, resolved_via="none")


if __name__ == "__main__":  # 纯函数 selftest(不联网): python -m fulltext_fetcher.resolve
    ci = classify_input

    # —— classify_input:DOI 各形态(裸 DOI / doi: 前缀 / doi.org URL)——
    assert ci("10.1038/nature12373").kind == "doi"
    assert ci("10.1038/nature12373").value == "10.1038/nature12373"
    assert ci("doi:10.1234/abcd").kind == "doi"
    assert ci("doi:10.1234/abcd").value == "10.1234/abcd"
    _w = ci("https://doi.org/10.1234/abcd")
    assert (_w.kind, _w.value) == ("doi", "10.1234/abcd"), (_w.kind, _w.value)

    # —— arXiv:前缀 / 纯 id / abs·pdf URL / 旧式分类号 ——
    assert ci("arXiv:2101.00001").kind == "arxiv"
    assert ci("arXiv:2101.00001").value == "2101.00001"
    assert ci("2101.00001").kind == "arxiv"
    _wa = ci("https://arxiv.org/abs/2101.00001")
    assert (_wa.kind, _wa.value) == ("arxiv", "2101.00001"), (_wa.kind, _wa.value)
    assert ci("https://arxiv.org/pdf/2101.00001.pdf").value == "2101.00001"
    assert ci("hep-th/9901001").kind == "arxiv"

    # —— 兜底:普通标题判为 title ——
    assert ci("Attention Is All You Need").kind == "title"
    assert ci("A Survey of Large Language Models").kind == "title"

    # —— 标题 Jaccard 相似度:词集合交并比,词序无关、对称、空串保护 ——
    sim = _title_similarity
    assert sim("a b c", "a b c") == 1.0
    assert sim("a b c d", "a b") == 0.5            # |∩|=2 / |∪|=4
    assert sim("x y", "p q") == 0.0               # 无交集
    assert sim("", "anything") == 0.0             # 空串保护
    assert sim("a b c", "c b a") == 1.0           # 词序无关
    assert sim("a b c", "b c d") == sim("b c d", "a b c")  # 对称

    # —— 标题归一 _norm_title:小写 + 非词字符折叠为空格 + 收尾去空白 + None 保护 ——
    assert _norm_title("Deep, Residual!  Learning") == "deep residual learning"
    assert _norm_title("  A/B  C ") == "a b c"
    assert _norm_title(None) == ""

    # —— OpenAlex doi 剥前缀:https://doi.org/<doi> → 裸 DOI(保留原大小写)——
    assert _doi_from_openalex("https://doi.org/10.1/AbC") == "10.1/AbC"
    assert _doi_from_openalex("http://dx.doi.org/10.2/x") == "10.2/x"
    assert _doi_from_openalex("10.3/already-bare") == "10.3/already-bare"
    assert _doi_from_openalex(None) is None
    assert _doi_from_openalex("") is None

    # —— _best_candidate:按 Jaccard 选最佳,返回 (doi, score) ——
    _bd, _bs = _best_candidate(_norm_title("Attention Is All You Need"),
                               [("10.x/miss", "Totally Different Topic"),
                                ("10.x/hit", "Attention Is All You Need")])
    assert (_bd, _bs) == ("10.x/hit", 1.0), (_bd, _bs)

    # —— 多源标题反查 title_to_doi:构造离线假 client(不联网)——
    class _FakeClient:
        """按 URL 子串返回构造 JSON;记录调用过的 URL;未命中返回 None(模拟单源失败)。"""
        def __init__(self, table):
            self.table = table          # list[(url_substr, json|None)]
            self.calls = []

        def get_json(self, url, **kw):
            self.calls.append(url)
            for sub, resp in self.table:
                if sub in url:
                    return resp
            return None

    class _Cfg:
        email = "t@example.com"
        openalex_key = None
        s2_key = None

    _cfg = _Cfg()
    _T = "Deep Residual Learning for Image Recognition"

    def _cr(doi, title):  # Crossref 响应
        return {"message": {"items": [{"DOI": doi, "title": [title]}]}}

    def _oa(doi, title):  # OpenAlex 响应(doi 带 https 前缀)
        return {"results": [{"id": "https://openalex.org/W1",
                             "doi": "https://doi.org/" + doi, "display_name": title}]}

    def _s2(doi, title):  # Semantic Scholar 响应
        return {"data": [{"paperId": "p1", "title": title, "externalIds": {"DOI": doi}}]}

    # ① Crossref 置信命中(sim>=0.6):立即返回,且不再调用 OpenAlex / S2(短路)
    fc1 = _FakeClient([("crossref.org", _cr("10.cr/hit", _T))])
    assert title_to_doi(_T, fc1, None, _cfg) == ("10.cr/hit", "crossref-title")
    assert all("openalex.org" not in u and "semanticscholar.org" not in u for u in fc1.calls), fc1.calls

    # ② Crossref 低置信 → 回退 OpenAlex 置信命中(并验证 OpenAlex doi 前缀已剥)
    fc2 = _FakeClient([("crossref.org", _cr("10.cr/low", "An Unrelated Cooking Recipe")),
                       ("openalex.org", _oa("10.oa/hit", _T))])
    assert title_to_doi(_T, fc2, None, _cfg) == ("10.oa/hit", "openalex-title")

    # ③ Crossref / OpenAlex 都失败(None) → 回退 Semantic Scholar 命中
    fc3 = _FakeClient([("crossref.org", None), ("openalex.org", None),
                       ("semanticscholar.org", _s2("10.s2/hit", _T))])
    assert title_to_doi(_T, fc3, None, _cfg) == ("10.s2/hit", "s2-title")

    # ④ 三源都低置信 → 兜底取「最权威源(Crossref)的第一条」
    fc4 = _FakeClient([("crossref.org", _cr("10.cr/first", "Quantum Gravity in Two Dimensions")),
                       ("openalex.org", _oa("10.oa/x", "A Study of Bird Migration")),
                       ("semanticscholar.org", _s2("10.s2/x", "Cooking With Cast Iron"))])
    assert title_to_doi(_T, fc4, None, _cfg) == ("10.cr/first", "crossref-title")

    # ⑤ 全部为空 / 失败 → (None, None)
    assert title_to_doi(_T, _FakeClient([]), None, _cfg) == (None, None)

    # ⑥ 单源抛异常被吞,继续回退下一源(crossref 抛错 → openalex 命中)
    class _BoomClient(_FakeClient):
        def get_json(self, url, **kw):
            if "crossref.org" in url:
                self.calls.append(url)
                raise RuntimeError("boom")
            return super().get_json(url, **kw)

    fc6 = _BoomClient([("openalex.org", _oa("10.oa/after-boom", _T))])
    assert title_to_doi(_T, fc6, None, _cfg) == ("10.oa/after-boom", "openalex-title")

    # ⑦ 向后兼容:crossref_title_to_doi 单源行为不变(命中 / 低置信兜底第一条 / 空)
    assert crossref_title_to_doi(_T, _FakeClient([("crossref.org", _cr("10.cr/c", _T))]), None, _cfg) == "10.cr/c"
    fc8 = _FakeClient([("crossref.org", {"message": {"items": [
        {"DOI": "10.cr/first", "title": ["No Words In Common Here At All"]},
        {"DOI": "10.cr/second", "title": ["Another One"]}]}})])
    assert crossref_title_to_doi(_T, fc8, None, _cfg) == "10.cr/first"
    assert crossref_title_to_doi(_T, _FakeClient([("crossref.org", None)]), None, _cfg) is None

    # —— resolve_to_paper 集成(离线):公共入口的多源标题路径 + DOI/arXiv 向后兼容 ——
    # 说明:_FakeClient 按 URL 子串顺序匹配;标题反查命中 .../works(无尾斜杠),单条富化命中
    # .../works/<doi> 或 .../works/doi:<doi>。把「带尾斜杠」的兜底项排在前面,即可让富化调用
    # 命中 None、而标题反查仍命中候选,无需改动 _FakeClient。
    def _oa_work(title, year=2015):  # OpenAlex 单条 works/doi: 富化响应(最小可用)
        return {"title": title, "publication_year": year, "ids": {}, "authorships": [],
                "open_access": {"is_oa": True, "oa_status": "green"}, "primary_location": {}}

    # ⑧ title 路径:Crossref 反查命中 → OpenAlex 富化,resolved_via 变为富化源、补全 is_oa
    fc_r1 = _FakeClient([("api.openalex.org/works/doi:", _oa_work(_T)),
                         ("api.crossref.org/works", _cr("10.cr/hit", _T))])
    _p1 = resolve_to_paper(classify_input(_T), fc_r1, None, _cfg)
    assert (_p1.doi, _p1.resolved_via, _p1.is_oa, _p1.title) == ("10.cr/hit", "openalex", True, _T), \
        (_p1.doi, _p1.resolved_via, _p1.is_oa, _p1.title)

    # ⑨ title 路径:反查命中但两源富化均失败 → 保留反查 via 标签与裸 doi、标题回填输入
    fc_r2 = _FakeClient([("api.crossref.org/works/", None),                  # 富化(尾斜杠)→ None
                         ("api.crossref.org/works", _cr("10.cr/only", _T))])  # 反查候选(无尾斜杠)
    _p2 = resolve_to_paper(classify_input(_T), fc_r2, None, _cfg)
    assert (_p2.doi, _p2.resolved_via, _p2.title) == ("10.cr/only", "crossref-title", _T), \
        (_p2.doi, _p2.resolved_via, _p2.title)

    # ⑩ 向后兼容:DOI 输入路径不变(直接 OpenAlex 富化,不触发标题反查)
    fc_r3 = _FakeClient([("api.openalex.org/works/doi:", _oa_work(_T))])
    _p3 = resolve_to_paper(classify_input("10.1038/nature12373"), fc_r3, None, _cfg)
    assert (_p3.doi, _p3.resolved_via) == ("10.1038/nature12373", "openalex"), (_p3.doi, _p3.resolved_via)
    assert all("crossref.org" not in u for u in fc_r3.calls), fc_r3.calls  # 未走标题反查

    # ⑪ 向后兼容:arXiv 输入路径不变(富化失败 → arxiv-id 兜底,doi=10.48550/arxiv.<id>)
    _p4 = resolve_to_paper(classify_input("2101.00001"), _FakeClient([]), None, _cfg)
    assert (_p4.arxiv_id, _p4.doi, _p4.resolved_via) == \
        ("2101.00001", "10.48550/arxiv.2101.00001", "arxiv-id"), \
        (_p4.arxiv_id, _p4.doi, _p4.resolved_via)

    print("RESOLVE_OK")
