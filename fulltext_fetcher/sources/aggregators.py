"""聚合类源:以 DOI 为键、直接返回(可能的)PDF 直链。覆盖最广、命中率最高。

字段路径依据《fulltext_fetcher资料-各源接口速查.md》(2026-07 核验)。
"""
from __future__ import annotations

import concurrent.futures
from typing import Any, Callable, List, Optional, Tuple

from ..models import Paper, PdfCandidate
from .base import REGISTRY, BaseSource, SourceContext, register


@register
class Unpaywall(BaseSource):
    name = "unpaywall"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        data = ctx.client.get_json(
            f"https://api.unpaywall.org/v2/{paper.doi}", params={"email": ctx.cfg.email}
        )
        if not data:
            return []
        out: List[PdfCandidate] = []
        best = data.get("best_oa_location") or {}
        if best.get("url_for_pdf"):
            out.append(PdfCandidate(best["url_for_pdf"], self.name, "pdf",
                                    best.get("version"), best.get("license"), 95))
        for loc in (data.get("oa_locations") or []):
            if loc.get("url_for_pdf"):
                out.append(PdfCandidate(loc["url_for_pdf"], self.name, "pdf",
                                        loc.get("version"), loc.get("license"), 82))
            elif loc.get("url"):
                out.append(PdfCandidate(loc["url"], self.name, "landing",
                                        loc.get("version"), loc.get("license"), 30))
        return out


@register
class OpenAlex(BaseSource):
    name = "openalex"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        params = {"mailto": ctx.cfg.email}
        if ctx.cfg.openalex_key:
            params["api_key"] = ctx.cfg.openalex_key
        data = ctx.client.get_json(f"https://api.openalex.org/works/doi:{paper.doi}", params=params)
        if not data:
            return []
        out: List[PdfCandidate] = []
        # 位置级 canonical 直链:best_oa_location / primary_location 的 pdf_url(权威,保留高分)。
        for locname, conf in (("best_oa_location", 93), ("primary_location", 70)):
            loc = data.get(locname) or {}
            if isinstance(loc, dict) and loc.get("pdf_url"):
                out.append(PdfCandidate(loc["pdf_url"], self.name, "pdf",
                                        loc.get("version"), loc.get("license"), conf))
        # open_access.oa_url:免费三件套的 OpenAlex canonical OA 指针(-145 配方核心字段之一)。
        # 口径纠偏(147 五-补):此前当 landing/38 低分,实为 OpenAlex「最接近免费的全文 URL」,
        # 提升为 pdf 直链 72(略高于 primary 的原始 pdf_url,低于 best_oa 93);
        # 下载层对非 PDF 情形有 %PDF 校验 + landing 回收兜底,提升不会引入假成功。
        oa = data.get("open_access") or {}
        if oa.get("oa_url"):
            out.append(PdfCandidate(oa["oa_url"], self.name, "pdf", None, None, 72))
        # locations[].pdf_url:泛位置数组,含镜像/重复/偶发非 PDF(-145 判为 lossy)。
        # 纠偏:从 74 降到 40(保留召回但排在 canonical 之后),不再与真 OA 直链抢先。
        for loc in (data.get("locations") or []):
            if isinstance(loc, dict) and loc.get("pdf_url"):
                out.append(PdfCandidate(loc["pdf_url"], self.name, "pdf",
                                        loc.get("version"), loc.get("license"), 40))
        return out


@register
class OpenAlexContent(BaseSource):
    """OpenAlex Content API:官方缓存全文 PDF(约 6000 万篇,content.openalex.org)。

    需 openalex_key(免费注册):计费按【成功下载】计($0.01/篇;免费档每日 $1 ≈ 100 篇,
    未绑卡超出预算即被拒,不会超扣),404/未缓存不计费。故源序放在全部免费源之后、
    websearch 兜底之前——仅真 miss 才花额度。候选 URL **绝不携带 api_key**(避免泄入
    attempts.jsonl / results.csv / report.html 等产物),由 HttpClient 对
    content.openalex.org 域在请求时单点注入(见 http_client.HttpClient.get)。
    先经 works 单条(免费、不限量)拿 work id 与 has_content/content_urls,再给候选:
    content_urls.pdf(官方权威指针)优先;has_content 明确说无 PDF → 让位(省一次必 404);
    其余按 work id 构造直链,未缓存时下载层 %PDF 校验自然过滤,不产假成功。
    """

    name = "openalex_content"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        key = getattr(ctx.cfg, "openalex_key", None)
        if not key:
            return []          # 该 API 必须带 key;未配置 → 本源静默让位(零请求)
        data = ctx.client.get_json(
            f"https://api.openalex.org/works/doi:{paper.doi}",
            params={"mailto": ctx.cfg.email, "api_key": key},
        )
        if not data:
            return []
        curls = data.get("content_urls")
        if isinstance(curls, dict) and curls.get("pdf"):
            return [PdfCandidate(str(curls["pdf"]), self.name, "pdf", None, None, 85)]
        hc = data.get("has_content")
        hc_pdf = hc.get("pdf") if isinstance(hc, dict) else (hc if isinstance(hc, bool) else None)
        if hc_pdf is False:
            return []
        wid = str(data.get("id") or "").rstrip("/").rsplit("/", 1)[-1].upper()
        if not (wid.startswith("W") and wid[1:].isdigit()):
            return []
        return [PdfCandidate(f"https://content.openalex.org/works/{wid}.pdf",
                             self.name, "pdf", None, None, 85)]


@register
class SemanticScholar(BaseSource):
    name = "semantic_scholar"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        headers = {"x-api-key": ctx.cfg.s2_key} if ctx.cfg.s2_key else None
        data = ctx.client.get_json(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{paper.doi}",
            params={"fields": "openAccessPdf,isOpenAccess,externalIds"},
            headers=headers,
        )
        if not data:
            return []
        oap = data.get("openAccessPdf") or {}
        if oap.get("url"):
            return [PdfCandidate(oap["url"], self.name, "pdf", None, None, 76)]
        return []


# Crossref link[] 多为 TDM(text/data mining)链:面向机器而非读者,普通请求多半 403。
# 已知订阅型出版商域名 + text-mining 用途再分层降权,使其在 --no-download 的全局 top 选择
# 与下载模式的源内尝试顺序中,都排在真 OA 直链与可被 landing 回收的落地页之后。
_CROSSREF_PAYWALL_HOSTS = (
    "api.elsevier.com", "api.wiley.com", "sciencedirect.com", "pubs.acs.org",
    "pubs.rsc.org", "onlinelibrary.wiley.com", "academic.oup.com",
    "tandfonline.com", "journals.sagepub.com",
)


def _score_crossref_link(link: dict):
    """给单个 Crossref link 对象评分,返回 (url, confidence) 或 None(非 PDF / 无 URL)。

    Crossref 为兜底源且 link[] 多为 TDM 链(多 403):故基础分本就低,再对 text-mining /
    similarity-checking 用途与已知订阅出版商域名分层降权。仍保留为低分候选(不丢弃),
    以便 download 拿到 HTML 落地页时交由 landing 二次回收内嵌 PDF(实测可回收一部分)。
    """
    url = link.get("URL")
    if not url:
        return None
    ct = (link.get("content-type") or "").lower()
    if ct == "application/pdf":
        conf = 40
    elif ct in ("unspecified", ""):
        conf = 24
    else:
        return None  # text/xml、text/html、application/xml 等并非 PDF
    intended = (link.get("intended-application") or "").lower()
    if intended in ("text-mining", "similarity-checking"):
        conf -= 12
    ul = url.lower()
    if any(h in ul for h in _CROSSREF_PAYWALL_HOSTS):
        conf -= 10
    return url, max(conf, 5)


@register
class Crossref(BaseSource):
    name = "crossref"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        data = ctx.client.get_json(
            f"https://api.crossref.org/works/{paper.doi}", params={"mailto": ctx.cfg.email}
        )
        if not data:
            return []
        msg = data.get("message") or {}
        out: List[PdfCandidate] = []
        for link in (msg.get("link") or []):
            scored = _score_crossref_link(link)
            if not scored:
                continue
            url, conf = scored
            out.append(PdfCandidate(url, self.name, "pdf",
                                    link.get("content-version"), None, conf))
        return out


@register
class Core(BaseSource):
    name = "core"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        if not ctx.cfg.core_key:
            return []  # CORE 必须 key,无 key 直接跳过
        headers = {"Authorization": f"Bearer {ctx.cfg.core_key}"}
        data = ctx.client.get_json(
            "https://api.core.ac.uk/v3/search/works",
            params={"q": f'doi:"{paper.doi}"', "limit": 3},
            headers=headers,
        )
        if not data:
            return []
        out: List[PdfCandidate] = []
        for res in (data.get("results") or []):
            if res.get("downloadUrl"):
                out.append(PdfCandidate(res["downloadUrl"], self.name, "pdf", None, None, 68))
        return out


@register
class OpenAire(BaseSource):
    name = "openaire"

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        data = ctx.client.get_json(
            "https://api.openaire.eu/search/publications",
            params={"doi": paper.doi, "format": "json"},
        )
        if not data:
            return []
        # 记录级解析(2026-07 修假阳):仅收「记录 pid/DOI == 查询 DOI」的记录自身 URL。
        # 此前对整包 JSON 递归抽 url,连 rels.rel[](引用/相关文献 = 别的论文)的 webresource
        # 一起收 → 邻近记录的错 PDF 被当候选(实证:10.1016/j.susc.2014.02.019 与
        # 10.1016/j.apcata.2013.07.028 都误收筑波仓库 record/38855 的 CARS 光谱 PDF)。
        urls = _openaire_record_urls(data, paper.doi)
        out: List[PdfCandidate] = []
        seen = set()
        for u in urls:
            if u in seen:
                continue
            seen.add(u)
            ul = u.lower()
            # 仅保留像全文/PDF 的链接,丢弃出版商首页等噪声(OpenAIRE 嵌套 JSON 杂质很多)。
            if ul.endswith(".pdf") or "/pdf" in ul or "pdf=" in ul:
                out.append(PdfCandidate(u, self.name, "pdf", None, None, 50))
            elif any(h in ul for h in ("arxiv.org/", "europepmc.org/", "ncbi.nlm.nih.gov/pmc",
                                       "zenodo.org/record", "hal.", "/download")):
                out.append(PdfCandidate(u, self.name, "landing", None, None, 30))
            # 其它(如出版商/机构首页)直接跳过,避免误判
        return out[:6]


def _norm_doi(doi) -> str:
    """归一 DOI 用于比较:去 doi.org/scheme/doi: 前缀、去空白、小写。"""
    d = str(doi or "").strip().lower()
    for pre in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                "http://dx.doi.org/", "doi.org/", "doi:"):
        if d.startswith(pre):
            d = d[len(pre):]
            break
    return d.strip().strip("/")


def _as_list(v) -> list:
    """OpenAIRE 的 XML→JSON 单元素不带数组:统一成 list 遍历。"""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _pid_dois(node) -> List[str]:
    """抽取节点 pid[] 中 classid=doi 的值(已归一;容忍 dict/list、@classid/classid)。"""
    out: List[str] = []
    for p in _as_list((node or {}).get("pid")):
        if not isinstance(p, dict):
            continue
        cid = str(p.get("@classid") or p.get("classid") or "").lower()
        val = p.get("$") or p.get("content") or p.get("value")
        if cid == "doi" and isinstance(val, str) and val.strip():
            out.append(_norm_doi(val))
    return out


def _openaire_record_urls(data, doi) -> List[str]:
    """从 /search/publications JSON 中按【记录级归属】抽 URL(纯函数,防御式)。

    仅当记录 oaf:result 的 pid/DOI == 查询 DOI 才收该记录的 url;其中:
    - rels 子树(引用/相关文献/项目等 = **别的论文**)整棵排除——错 PDF 假阳的根源;
    - children(OpenAIRE dedup 同一实体的成员记录)归属有保证,收;但成员若自带
      「明确 != 查询 DOI」的 pid → 防御性跳过(无法确证归属的不收)。
    """
    want = _norm_doi(doi)
    if not want:
        return []
    urls: List[str] = []
    resp = (data or {}).get("response") or {}
    results = resp.get("results") or {}
    recs = results.get("result") if isinstance(results, dict) else results
    for rec in _as_list(recs):
        if not isinstance(rec, dict):
            continue
        node = ((rec.get("metadata") or {}).get("oaf:entity") or {}).get("oaf:result")
        if not isinstance(node, dict):
            continue
        if want not in _pid_dois(node):
            continue  # 记录不属于查询 DOI(相似检索命中等)→ 整条不收
        own = {k: v for k, v in node.items()
               if str(k).lower() not in ("rels", "children")}
        _collect_urls(own, urls)
        children = node.get("children")
        if isinstance(children, dict):
            rest = {k: v for k, v in children.items() if str(k).lower() != "result"}
            _collect_urls(rest, urls)
            for child in _as_list(children.get("result")):
                if not isinstance(child, dict):
                    continue
                child_dois = _pid_dois(child)
                if child_dois and want not in child_dois:
                    continue  # dedup 成员声称别的 DOI → 归属存疑,不收
                _collect_urls(child, urls)
    return urls


def _collect_urls(node, acc: List[str], depth: int = 0) -> None:
    """在 OpenAIRE 深层嵌套 JSON 中递归提取 webresource/url 链接(防御式)。

    注意:本函数只做「形态抽取」,不判归属;调用方须先按记录级归属裁剪节点
    (见 _openaire_record_urls),绝不可再对整包响应调用(会把 rels 相关文献一起收)。
    """
    if depth > 12 or len(acc) > 30:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            kl = str(k).lower()
            if kl in ("url", "webresourceurl") and isinstance(v, str) and v.startswith("http"):
                acc.append(v)
            elif isinstance(v, str) and kl == "$" and v.startswith("http"):
                acc.append(v)
            else:
                _collect_urls(v, acc, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _collect_urls(item, acc, depth + 1)


# ── 147 五-补:免费三件套并发 OA 发现 + %PDF 取首个(承接《总评估-147》五-补 / -145 §6.5)──
# 定位:「谷歌学术可达 PDF 绝大多数是 OA」——DOI 命中即**并发**查免费三件套(Unpaywall
# url_for_pdf / OpenAlex open_access.oa_url / S2 openAccessPdf.url)拿 canonical 直链,
# 取首个 %PDF 有效者,比串行逐源更快。本层只**发现候选 + 提供纯逻辑 helper**,真正落盘/网络
# 取字节仍由 download 层(其 %PDF 校验/landing 回收/route-B)负责——本函数的 fetch 由调用方注入。
_PDF_MAGIC = b"%PDF"

# 免费三件套的源名(须与本模块 @register 的 name 一致):按 -145 配方的 canonical 字段。
_TRIO_SOURCES: Tuple[str, ...] = ("unpaywall", "openalex", "semantic_scholar")


def looks_like_pdf_bytes(head: Any) -> bool:
    """%PDF 魔数校验(与 download.looks_like_pdf 同口径:前 1024 字节含 b'%PDF')。

    source 层自含一份,便于离线 selftest 与被上层复用;容忍 bytes / str / None。
    """
    if not head:
        return False
    if isinstance(head, str):
        head = head.encode("latin-1", "ignore")
    try:
        return _PDF_MAGIC in bytes(head)[:1024]
    except Exception:  # noqa: BLE001 - 畸形输入一律判非 PDF,绝不抛
        return False


def _safe_find(src: BaseSource, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
    """调单源 find_candidates 并吞掉其自身异常(单源失败绝不拖垮并发批)。"""
    try:
        return src.find_candidates(paper, ctx) or []
    except Exception:  # noqa: BLE001
        return []


def _dedup_rank(cands: List[PdfCandidate]) -> List[PdfCandidate]:
    """去重(按 url 保留最高 confidence)+ 直链优先 + confidence 降序(稳定、可测)。"""
    best: dict = {}
    for c in cands:
        prev = best.get(c.url)
        if prev is None or c.confidence > prev.confidence:
            best[c.url] = c
    uniq = list(best.values())
    uniq.sort(key=lambda c: (0 if c.is_direct() else 1, -int(c.confidence or 0), c.source, c.url))
    return uniq


def fast_oa_trio(paper: Paper, ctx: SourceContext, max_workers: int = 3) -> List[PdfCandidate]:
    """并发查免费三件套(Unpaywall / OpenAlex / Semantic Scholar),合并为去重、按分降序的候选。

    「最快」:三源同时发起(而非串行),单源异常/超时不影响其它源(交由 http_client 退避熔断)。
    仅做**候选发现**,不取字节;结果交给 first_valid_pdf(或既有 download 编排)逐个验 %PDF。
    """
    srcs = [REGISTRY[n]() for n in _TRIO_SOURCES if n in REGISTRY]
    if not srcs:
        return []
    merged: List[PdfCandidate] = []
    workers = max(1, min(max_workers, len(srcs)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_safe_find, s, paper, ctx) for s in srcs]
        for fut in concurrent.futures.as_completed(futs):
            merged.extend(fut.result())
    return _dedup_rank(merged)


def _log_attempt(log: Any, c: PdfCandidate, reason: str) -> None:
    """日志驱动:把每个候选的取回结果打成一行可读日志(source/conf/url/原因),失败不外抛。"""
    if log is None:
        return
    try:
        log.info("fast_oa: source=%s conf=%s url=%s -> %s", c.source, c.confidence, c.url, reason)
    except Exception:  # noqa: BLE001
        pass


def first_valid_pdf(candidates: List[PdfCandidate], fetch: Callable[[str], Any],
                    log: Any = None) -> Tuple[Optional[PdfCandidate], Optional[bytes]]:
    """按序对候选调用注入的 ``fetch(url) -> bytes|None``,返回首个 %PDF 有效的 (candidate, data)。

    全不中返回 (None, None)。每次尝试记一行可读日志(便于"读日志判断每篇为何成/败")。
    ``fetch`` 注入 → 纯逻辑、可完全离线单测;真实网络取字节由调用方(download 层)提供。
    """
    for c in candidates:
        try:
            data = fetch(c.url)
        except Exception as e:  # noqa: BLE001 - 单个 URL 取回异常不得中断整条 fallback
            _log_attempt(log, c, "skip:fetch-error(%s)" % e)
            continue
        if data and looks_like_pdf_bytes(data):
            _log_attempt(log, c, "ok:%%PDF(%d bytes)" % len(data))
            return c, (data if isinstance(data, bytes) else bytes(data))
        _log_attempt(log, c, "skip:not-pdf" if data else "skip:no-data")
    return None, None


if __name__ == "__main__":  # 纯函数 selftest(不联网): python -m fulltext_fetcher.sources.aggregators
    f = _score_crossref_link
    # 普通 application/pdf(非 TDM、非订阅域):基础 40
    assert f({"URL": "https://oa.org/a.pdf", "content-type": "application/pdf"}) == ("https://oa.org/a.pdf", 40)
    # unspecified / 空 content-type:24
    assert f({"URL": "https://oa.org/b", "content-type": "unspecified"}) == ("https://oa.org/b", 24)
    assert f({"URL": "https://oa.org/b2", "content-type": ""}) == ("https://oa.org/b2", 24)
    # 非 PDF 的 content-type 一律跳过
    assert f({"URL": "https://oa.org/c.xml", "content-type": "text/xml"}) is None
    assert f({"URL": "https://oa.org/d", "content-type": "text/html"}) is None
    # 无 URL 跳过
    assert f({"content-type": "application/pdf"}) is None
    assert f({"URL": "", "content-type": "application/pdf"}) is None
    # text-mining / similarity-checking 用途降权:40-12=28
    assert f({"URL": "https://oa.org/e.pdf", "content-type": "application/pdf",
              "intended-application": "text-mining"}) == ("https://oa.org/e.pdf", 28)
    assert f({"URL": "https://oa.org/f.pdf", "content-type": "application/pdf",
              "intended-application": "similarity-checking"})[1] == 28
    # 订阅出版商域名降权:40-10=30
    assert f({"URL": "https://api.elsevier.com/x.pdf",
              "content-type": "application/pdf"}) == ("https://api.elsevier.com/x.pdf", 30)
    # TDM + 订阅域叠加:40-12-10=18
    assert f({"URL": "https://api.elsevier.com/y.pdf", "content-type": "application/pdf",
              "intended-application": "text-mining"}) == ("https://api.elsevier.com/y.pdf", 18)
    # 下界保护:不低于 5 (24-12-10=2 -> 5)
    assert f({"URL": "https://pubs.acs.org/z", "content-type": "unspecified",
              "intended-application": "text-mining"}) == ("https://pubs.acs.org/z", 5)
    # 关键不变量:Crossref 最高基础分(40) 必须低于任一真 OA 直链的最低 confidence
    #   (Core 68 / OpenAlex locations 74 / S2 76 / Unpaywall oa_locations 82),
    #   确保 --no-download 的全局 top 不被 Crossref 兜底链抢占。
    assert f({"URL": "https://oa.org/g.pdf", "content-type": "application/pdf"})[1] < 68

    # ══ OpenAIRE 记录级归属解析(2026-07 修 rels 邻近文献假阳)══════════════════
    # 基础纯函数
    assert _norm_doi("https://doi.org/10.1016/J.SUSC.2014.02.019") == "10.1016/j.susc.2014.02.019"
    assert _norm_doi("doi:10.1/X ") == "10.1/x" and _norm_doi(None) == ""
    assert _as_list(None) == [] and _as_list("a") == ["a"] and _as_list([1, 2]) == [1, 2]
    assert _pid_dois({"pid": {"@classid": "doi", "$": "10.1/A"}}) == ["10.1/a"]
    assert _pid_dois({"pid": [{"@classid": "pmid", "$": "123"},
                              {"@classid": "doi", "$": "10.2/B"}]}) == ["10.2/b"]
    assert _pid_dois({}) == [] and _pid_dois({"pid": "junk"}) == []

    def _rec(pid_dois, own_instances=None, rels=None, children=None):
        """构造一条最小 /search/publications 记录(复刻实网 oaf:entity 结构)。"""
        node = {"pid": [{"@classid": "doi", "$": d} for d in pid_dois]}
        if own_instances:
            node["instance"] = own_instances
        if rels is not None:
            node["rels"] = rels
        if children is not None:
            node["children"] = children
        return {"metadata": {"oaf:entity": {"oaf:result": node}}}

    def _resp(*recs):
        return {"response": {"results": {"result": list(recs)}}}

    _WANT = "10.1016/j.susc.2014.02.019"
    _BAD_38855 = "https://tsukuba.repo.nii.ac.jp/record/38855/files/CPL_655%EF%BC%8F656.pdf"
    # 实证根因复刻:错 PDF 挂在 rels.rel[].instance.fulltext.$(引用/相关文献=别的论文)
    _RELS_WITH_38855 = {"rel": [
        {"instance": {"fulltext": {"$": _BAD_38855}}},
        {"instance": [{"webresource": {"url": {"$": "https://doi.org/10.1016/j.molstruc.2009.10.026"}},
                       "url": {"$": "https://digital.csic.es/bitstream/10261/91676/1/x.pdf"}}]},
    ]}

    class _FakeClient:
        def __init__(self, data): self._data = data
        def get_json(self, url, **kw): return self._data

    class _OACtx:
        def __init__(self, data):
            self.client = _FakeClient(data)
            self.cfg = None; self.log = None; self.events = None

    # ① 实证场景1(10.1016/j.susc.2014.02.019):记录归属正确但自身无 OA 全文,
    #    rels 里挂着 38855 错 PDF → 修复后必须 0 候选(旧代码在此误收 38855)
    d1 = _resp(_rec([_WANT], own_instances=[
        {"webresource": {"url": {"$": "https://doi.org/" + _WANT}}}], rels=_RELS_WITH_38855))
    u1 = _openaire_record_urls(d1, _WANT)
    assert all("38855" not in u and "csic.es" not in u for u in u1), u1
    c1 = OpenAire().find_candidates(Paper(doi=_WANT), _OACtx(d1))
    assert c1 == [], f"susc 记录无 OA 全文,rels 错 PDF 不得成为候选: {[c.url for c in c1]}"

    # ② 实证场景2(10.1016/j.apcata.2013.07.028):children dedup 成员(无 pid)的
    #    handle URL 归属可信、可收;rels 38855 仍必须拒收
    _WANT2 = "10.1016/j.apcata.2013.07.028"
    d2 = _resp(_rec([_WANT2], rels=_RELS_WITH_38855, children={"result": [
        {"instance": {"url": {"$": "http://hdl.handle.net/11336/2054"},
                      "webresource": {"url": {"$": "http://hdl.handle.net/11336/2054"}}}}]}))
    u2 = _openaire_record_urls(d2, _WANT2)
    assert "http://hdl.handle.net/11336/2054" in u2 and all("38855" not in u for u in u2), u2
    assert OpenAire().find_candidates(Paper(doi=_WANT2), _OACtx(d2)) == []  # handle 不像 PDF→不产噪声候选

    # ③ 正向召回不破坏:记录 pid==查询 DOI 时,记录自身 instance 的 PDF/landing 仍能收
    d3 = _resp(_rec([_WANT], own_instances=[
        {"webresource": {"url": {"$": "https://repo.univ.edu/oa/paper.pdf"}}},
        {"url": {"$": "https://arxiv.org/abs/1401.0001"}}], rels=_RELS_WITH_38855))
    c3 = OpenAire().find_candidates(Paper(doi=_WANT), _OACtx(d3))
    assert [c.url for c in c3 if c.kind == "pdf"] == ["https://repo.univ.edu/oa/paper.pdf"], c3
    assert any(c.url == "https://arxiv.org/abs/1401.0001" and c.kind == "landing" for c in c3), c3
    assert all("38855" not in c.url for c in c3), c3
    assert all(c.source == "openaire" for c in c3)

    # ④ 相似检索命中(记录 pid != 查询 DOI)→ 整条不收,即便其 instance 有 PDF
    d4 = _resp(_rec(["10.9999/other.paper"], own_instances=[
        {"webresource": {"url": {"$": "https://repo.other.org/wrong.pdf"}}}]))
    assert _openaire_record_urls(d4, _WANT) == []
    assert OpenAire().find_candidates(Paper(doi=_WANT), _OACtx(d4)) == []

    # ⑤ children 成员自带「明确 != 查询 DOI」的 pid → 该成员防御性跳过;无 pid 成员照收
    d5 = _resp(_rec([_WANT], children={"result": [
        {"pid": {"@classid": "doi", "$": "10.8888/stranger"},
         "instance": {"url": {"$": "https://repo.x.org/stranger.pdf"}}},
        {"instance": {"url": {"$": "https://repo.y.edu/mine.pdf"}}}]}))
    u5 = _openaire_record_urls(d5, _WANT)
    assert "https://repo.y.edu/mine.pdf" in u5 and \
        all("stranger" not in u for u in u5), u5

    # ⑥ 防御式健壮性:空/畸形响应、单记录不带数组、大小写 DOI 均不抛且行为正确
    assert _openaire_record_urls(None, _WANT) == []
    assert _openaire_record_urls({}, _WANT) == []
    assert _openaire_record_urls({"response": {"results": None}}, _WANT) == []
    assert _openaire_record_urls(_resp("junk", None), _WANT) == []
    d6 = {"response": {"results": {"result": _rec([_WANT.upper()], own_instances=[
        {"url": {"$": "https://repo.z.org/ok.pdf"}}])}}}   # 单记录 dict(不带数组)+ 大写 DOI
    assert _openaire_record_urls(d6, _WANT) == ["https://repo.z.org/ok.pdf"]
    assert _openaire_record_urls(d6, "") == [] and _openaire_record_urls(d6, None) == []

    # ══ 147 五-补:免费三件套并发 + oa_url 口径纠偏 + %PDF 取首个 ══════════════════
    # ① looks_like_pdf_bytes:%PDF 魔数(bytes/str/None、前置空白容忍、超 1024 不误判)
    assert looks_like_pdf_bytes(b"%PDF-1.7\nfoo") is True
    assert looks_like_pdf_bytes("%PDF-1.4") is True
    assert looks_like_pdf_bytes(b"<html>login</html>") is False
    assert looks_like_pdf_bytes(b"") is False and looks_like_pdf_bytes(None) is False
    assert looks_like_pdf_bytes(b"   %PDF-1.5") is True          # 前置空白仍在前 1024 内
    assert looks_like_pdf_bytes(b"x" * 2000 + b"%PDF") is False  # 魔数在 1024 之外→不算

    class _OAClient:
        def __init__(self, data): self._data = data
        def get_json(self, url, **kw): return self._data

    class _OACfg:
        email = "t@x.org"; openalex_key = None; s2_key = None

    class _OAlexCtx:
        def __init__(self, data):
            self.client = _OAClient(data); self.cfg = _OACfg(); self.log = None; self.events = None

    # ② OpenAlex oa_url 口径纠偏:oa_url→pdf/72(此前 landing/38);locations[].pdf_url→40
    #    (此前 74,-145 判 lossy);best_oa(93)/primary(70) 保持不变
    _oa_data = {
        "best_oa_location": {"pdf_url": "https://oa.org/best.pdf", "version": "publishedVersion"},
        "primary_location": {"pdf_url": "https://oa.org/primary.pdf"},
        "locations": [{"pdf_url": "https://mirror.org/lossy.pdf"}],
        "open_access": {"oa_url": "https://oa.org/canonical.pdf"},
    }
    _oc = {c.url: c for c in OpenAlex().find_candidates(Paper(doi="10.1/x"), _OAlexCtx(_oa_data))}
    assert _oc["https://oa.org/best.pdf"].confidence == 93, _oc
    assert _oc["https://oa.org/primary.pdf"].confidence == 70, _oc
    assert _oc["https://oa.org/canonical.pdf"].kind == "pdf" and \
        _oc["https://oa.org/canonical.pdf"].confidence == 72, "oa_url 应纠偏为 pdf/72"
    assert _oc["https://mirror.org/lossy.pdf"].confidence == 40, "lossy locations[].pdf_url 应降到 40"
    # oa_url(72) 必须排在 lossy locations(40) 之前(纠偏后的选择序)
    _rk = [c.url for c in _dedup_rank(OpenAlex().find_candidates(Paper(doi="10.1/x"), _OAlexCtx(_oa_data)))]
    assert _rk.index("https://oa.org/canonical.pdf") < _rk.index("https://mirror.org/lossy.pdf"), _rk

    # ③ fast_oa_trio:并发查 Unpaywall+OpenAlex+S2,合并去重、按分降序;单源异常不拖垮
    _trio_table = {
        "unpaywall.org": {"best_oa_location": {"url_for_pdf": "https://up.org/u.pdf", "version": "v"}},
        "openalex.org": _oa_data,
        "semanticscholar.org": {"openAccessPdf": {"url": "https://s2.org/s2.pdf"}},
    }

    class _TrioClient:
        def get_json(self, url, **kw):
            for k, v in _trio_table.items():
                if k in url:
                    return v
            return None

    class _TrioCtx:
        def __init__(self):
            self.client = _TrioClient(); self.cfg = _OACfg(); self.log = None; self.events = None

    _tri = fast_oa_trio(Paper(doi="10.1/x"), _TrioCtx())
    _tri_urls = [c.url for c in _tri]
    assert "https://up.org/u.pdf" in _tri_urls and "https://s2.org/s2.pdf" in _tri_urls, _tri_urls
    assert "https://oa.org/best.pdf" in _tri_urls and "https://oa.org/canonical.pdf" in _tri_urls, _tri_urls
    assert _tri[0].url == "https://up.org/u.pdf", [(c.source, c.confidence) for c in _tri]  # 95 最高
    assert len(_tri_urls) == len(set(_tri_urls)), _tri_urls                                 # 无重复 url

    # ④ first_valid_pdf:注入 fetch → 取首个 %PDF;跳过非 PDF/无数据;命中即停;日志可读
    class _CapLog:
        def __init__(self): self.msgs = []
        def info(self, fmt, *a): self.msgs.append((fmt % a) if a else fmt)

    _served = {"https://miss.org/a.pdf": b"<html>login</html>",       # 非 PDF → 跳过
               "https://ok.org/b.pdf": b"%PDF-1.6\nbytesbytes"}        # %PDF → 命中
    _cands = [PdfCandidate("https://miss.org/a.pdf", "unpaywall", "pdf", None, None, 95),
              PdfCandidate("https://ok.org/b.pdf", "openalex", "pdf", None, None, 72),
              PdfCandidate("https://never.org/c.pdf", "core", "pdf", None, None, 68)]
    _cap = _CapLog()
    _hit, _data = first_valid_pdf(_cands, lambda u: _served.get(u), log=_cap)
    assert _hit is not None and _hit.url == "https://ok.org/b.pdf" and _data.startswith(b"%PDF"), _hit
    assert any("skip:not-pdf" in m for m in _cap.msgs), _cap.msgs
    assert any("ok:%PDF" in m for m in _cap.msgs), _cap.msgs
    assert not any("never.org" in m for m in _cap.msgs), "命中后不应继续尝试后续候选"
    # 全非 PDF → (None, None)
    assert first_valid_pdf(
        [PdfCandidate("https://miss.org/a.pdf", "x", "pdf", None, None, 50)],
        lambda u: _served.get(u)) == (None, None)
    # fetch 抛异常被吞,继续下一个

    def _boom(u):
        if "boom" in u:
            raise RuntimeError("net")
        return _served.get(u)

    _bh, _ = first_valid_pdf(
        [PdfCandidate("https://boom.org/x.pdf", "x", "pdf", None, None, 90),
         PdfCandidate("https://ok.org/b.pdf", "y", "pdf", None, None, 80)], _boom)
    assert _bh is not None and _bh.url == "https://ok.org/b.pdf", _bh

    # ══ OpenAlexContent(官方缓存 PDF,content.openalex.org)══════════════════════
    class _CountClient(_OAClient):
        def __init__(self, data):
            super().__init__(data); self.calls = 0
        def get_json(self, url, **kw):
            self.calls += 1; return self._data

    class _KeyCfg(_OACfg):
        openalex_key = "K"

    class _OCtx:
        def __init__(self, data, cfg):
            self.client = _CountClient(data); self.cfg = cfg; self.log = None; self.events = None

    _P = Paper(doi="10.1/x")
    # ①(默认)无 key → 静默让位:零候选且零请求(该 API 必须 key,别浪费一次调用)
    _c_nokey = _OCtx({"id": "https://openalex.org/W1"}, _OACfg())
    assert OpenAlexContent().find_candidates(_P, _c_nokey) == [] and _c_nokey.client.calls == 0
    # ② content_urls.pdf(官方权威指针)优先原样使用;候选 URL 不得携带 api_key(防泄密)
    _c2 = _OCtx({"id": "https://openalex.org/W1",
                 "content_urls": {"pdf": "https://content.openalex.org/works/W1.pdf"}}, _KeyCfg())
    _r2 = OpenAlexContent().find_candidates(_P, _c2)
    assert [c.url for c in _r2] == ["https://content.openalex.org/works/W1.pdf"], _r2
    assert _r2[0].kind == "pdf" and _r2[0].confidence == 85 and _r2[0].source == "openalex_content"
    assert "api_key" not in _r2[0].url, "候选 URL 绝不携带 api_key(泄入产物)"
    # ③ 无 content_urls → 按 work id 构造直链;小写/带斜杠 id 归一
    _r3 = OpenAlexContent().find_candidates(_P, _OCtx({"id": "https://openalex.org/w3038568908/"},
                                                      _KeyCfg()))
    assert [c.url for c in _r3] == ["https://content.openalex.org/works/W3038568908.pdf"], _r3
    # ④ has_content 明确说无 pdf → 让位(省一次必 404);dict 与 bool 两种形态都识别
    assert OpenAlexContent().find_candidates(
        _P, _OCtx({"id": "https://openalex.org/W1", "has_content": {"pdf": False}}, _KeyCfg())) == []
    assert OpenAlexContent().find_candidates(
        _P, _OCtx({"id": "https://openalex.org/W1", "has_content": False}, _KeyCfg())) == []
    # ⑤ has_content 说有 → 照常构造;查无此 DOI / id 畸形 → 零候选不抛
    assert len(OpenAlexContent().find_candidates(
        _P, _OCtx({"id": "https://openalex.org/W1", "has_content": {"pdf": True}}, _KeyCfg()))) == 1
    assert OpenAlexContent().find_candidates(_P, _OCtx(None, _KeyCfg())) == []
    assert OpenAlexContent().find_candidates(_P, _OCtx({"id": "junk"}, _KeyCfg())) == []

    print("AGGREGATORS_OK")
