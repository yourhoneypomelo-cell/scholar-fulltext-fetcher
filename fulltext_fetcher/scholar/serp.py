"""Google Scholar SERP 解析层(对齐《谷歌学术爬虫-架构与选型.md》§3.4)。

本模块是「与取回 HTML 用什么反爬/浏览器库」完全解耦的**纯解析层**:上游 fetcher 取回结果页
HTML(或 SerpApi 的 JSON)后交本模块结构化。对标父包 ``fulltext_fetcher/landing.py`` 的设计:

  - **零第三方依赖**:仅标准库 ``html.parser`` + ``urllib.parse`` + ``re``(re 仅用于已抽出的
    文本片段,HTML 结构一律走 ``html.parser``);
  - **纯函数、不联网、无副作用**;对 None/空/乱码/畸形一律优雅返回(空 ``SerpPage`` / ``[]``),
    **绝不抛异常**;
  - 误报无妨,宁多给字段也不崩(下游会再校验)。

对外契约(冻结,以 ``scholar.models`` 为唯一真源):

    build_scholar_url(q: ScholarQuery) -> str          # 拼 q/hl/as_ylo/as_yhi/start/as_sdt
    parse_serp(html: str) -> SerpPage                  # 纯 html.parser 解析 .gs_r/.gs_ri
    parse_serpapi(data: dict) -> List[ScholarResult]   # 迁移自 B1 scholar_serpapi
    detect_captcha(html, url=None, status=None) -> bool # 验证码/风控页识别(供上游判阻断)

SERP 选择器依据(Google Scholar 现行 HTML,2026-07 核验):
  - 结果块  : div.gs_r[data-cid]         data-cid → result_id
  - 标题/链接: h3.gs_rt > a(href)         内联标签([PDF]/[CITATION] 等)会被剥离
  - 作者/刊/年: div.gs_a                   "作者 - 期刊, 年 - 站点" → publication_info/authors/venue/year
  - 摘要    : div.gs_rs
  - 被引/版本: div.gs_fl 内 <a>           "Cited by N" / "All N versions"(cluster= → cluster_id)
  - 右侧 PDF : div.gs_or_ggsm / gs_ggs(d) 内 <a[href]> → pdf_links(按 [PDF] 标签/后缀判定)

防御性回退(降低 Scholar 结构小改导致 0 结果的风险;误报无妨,契约不变):
  - 结果块  : 除 div.gs_r[data-cid] 外,兼容无 data-cid 的 gs_r(result_id=None);
              gs_r 外壳缺失时以裸 gs_ri 作块起点。
  - PDF     : 已知资源容器未取到直链时,兜底扫描全块 <a>,收 [PDF] 标签或 .pdf 后缀链接。
  - 标题    : h3.gs_rt 缺失/改名时,兜底取块内首个「非 [PDF]/[CITATION] 的站外链接」。
"""
from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from .models import ScholarQuery, ScholarResult, SerpPage

SCHOLAR_BASE = "https://scholar.google.com/scholar"

# 验证码 / 风控页标志(全部小写匹配)。命中任一即判为被拦。
_CAPTCHA_MARKERS = (
    "unusual traffic",
    "detected unusual traffic",
    "our systems have detected",
    "not a robot",
    "please show you're not a robot",
    "gs_captcha",
    "/sorry/",
    "g-recaptcha",
    "recaptcha",
    "sending automated queries",
    "can't process your request",
    "<title>sorry</title>",
    "<title>sorry...</title>",
)

# HTML 空元素(无闭合标签):不计入标签栈深度,避免深度漂移。
_VOID = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})

# —— 文本级正则(只作用于已从 HTML 抽出的纯文本,不用于解析标签)——
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_CITED_RE = re.compile(r"cited by\s+([\d,]+)", re.I)
_VERSIONS_RE = re.compile(r"\b(\d[\d,]*)\s+versions?\b", re.I)
_BRACKET_RE = re.compile(r"\[([^\]]+)\]")
_PURE_BRACKET_RE = re.compile(r"^\[[^\]]*\]$")


# ────────────────────────────── 文本小工具 ──────────────────────────────
def _norm(s: Optional[str]) -> str:
    """压缩空白 + 去首尾空白(对 None 安全)。"""
    return re.sub(r"\s+", " ", s or "").strip()


def _to_int_any(v: Any) -> Optional[int]:
    """把 int / 数字串 / 带千分位串 安全转 int;失败返回 None。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        pass
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _absolutize(href: Optional[str]) -> Optional[str]:
    """相对链接 → 绝对(以 scholar.google.com 为基);空/锚点返回 None。"""
    if not href:
        return None
    href = _html.unescape(str(href).strip())
    if not href or href.startswith("#"):
        return None
    try:
        return urljoin(SCHOLAR_BASE, href)
    except Exception:  # noqa: BLE001 - 畸形 href 不拖累其它字段
        return None


def _is_external(url: Optional[str]) -> bool:
    """URL 是否为站外链接(非 scholar.google.*)。

    用于标题兜底:h3.gs_rt 缺失时扫描全块 <a>,须排除 Save/Cite/Cited by/versions 等
    站内(/scholar 相对链接绝对化后落在 scholar.google.com)功能链接。
    """
    if not url:
        return False
    try:
        net = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return False
    return bool(net) and "scholar.google" not in net


def _bracket_label(text: Optional[str]) -> Optional[str]:
    """取文本里第一个 ``[XXX]`` 的 XXX(大写);无则 None。用于识别 [PDF]/[HTML]/[BOOK]。"""
    if not text:
        return None
    m = _BRACKET_RE.search(text)
    return m.group(1).strip().upper() if m else None


def _is_bracket_label(text: Optional[str]) -> bool:
    """整段文本是否就是一个 ``[XXX]`` 标签(用于排除标题里的 [PDF] 型伪链接)。"""
    return bool(_PURE_BRACKET_RE.match((text or "").strip()))


def _strip_leading_bracket(text: Optional[str]) -> str:
    """剥掉标题前导的 ``[CITATION]`` / ``[BOOK]`` 等标签。"""
    return re.sub(r"^\s*\[[^\]]*\]\s*", "", text or "").strip()


def _query_param(href: Optional[str], name: str) -> Optional[str]:
    """从 URL 查询串里取某参数值(如 versions 链接里的 cluster=)。"""
    if not href:
        return None
    try:
        vals = parse_qs(urlparse(_html.unescape(str(href))).query).get(name)
        return vals[0] if vals else None
    except Exception:  # noqa: BLE001
        return None


def _parse_pubinfo(text: str):
    """解析 "作者, 作者 - 期刊, 年 - 站点" → (authors, venue, year)。"""
    text = _norm(text)
    if not text:
        return [], None, None
    segs = [s.strip() for s in text.split(" - ")]
    authors_str = segs[0] if segs else ""
    middle = segs[1] if len(segs) >= 2 else ""
    ym = _YEAR_RE.search(middle) or _YEAR_RE.search(text)
    year = int(ym.group(0)) if ym else None
    venue = re.sub(r",?\s*\b(?:19|20)\d{2}\b.*$", "", middle).strip() if middle else ""
    authors = [a.strip() for a in authors_str.split(",") if a.strip()] if authors_str else []
    return authors, (venue or None), year


# ────────────────────────────── HTML 解析器 ──────────────────────────────
class _SerpParser(HTMLParser):
    """流式 html.parser:逐块提取 Google Scholar 结果,产出 List[ScholarResult]。

    用标签栈跟踪深度;各字段区域(标题/作者/摘要/页脚/右侧 PDF 容器)记录开启深度,
    在其标签闭合(深度回落)时结算。任何单块异常都被 parse_serp 兜底,不影响整页。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: List[ScholarResult] = []
        self.has_next: bool = False
        self._tagstack: List[str] = []
        self._cur: Optional[Dict[str, Any]] = None
        self._block_depth: Optional[int] = None
        self._field: Optional[str] = None          # 'title' | 'pubinfo' | 'snippet'
        self._field_depth: Optional[int] = None
        self._buf: List[str] = []
        self._pdf_open: List[int] = []             # 右侧资源容器的开启深度栈(可嵌套)
        self._footer_depth: Optional[int] = None
        self._in_a: bool = False
        self._a_href: Optional[str] = None
        self._a_text: List[str] = []
        self._a_kind: Optional[str] = None         # 'title' | 'pdf' | 'footer'

    # -- 区块生命周期 --
    def _start_block(self, cid: Optional[str], depth: int) -> None:
        self._cur = {
            "data_cid": cid, "rt_text": None, "rt_anchors": [], "all_anchors": [],
            "pubinfo": None, "snippet": None, "cited_by": None,
            "versions": None, "cluster_id": None, "pdf_links": [], "resources": [],
        }
        self._block_depth = depth
        self._field = None
        self._field_depth = None
        self._buf = []
        self._pdf_open = []
        self._footer_depth = None
        self._in_a = False
        self._a_href = None
        self._a_text = []
        self._a_kind = None

    def _finish_block(self) -> None:
        b = self._cur or {}
        self._cur = None
        self._block_depth = None
        self._field = None
        self._field_depth = None
        self._buf = []
        self._pdf_open = []
        self._footer_depth = None
        self._in_a = False
        if not b:
            return
        link: Optional[str] = None
        title: Optional[str] = None
        for href, text in b["rt_anchors"]:
            if href and text and not _is_bracket_label(text):
                link = _absolutize(href)
                title = text
                break
        if title is None:
            title = _strip_leading_bracket(b["rt_text"] or "") or None
        # 兜底①(标题):h3.gs_rt 缺失/改名时,取块内首个「非 [PDF]/[CITATION] 的站外链接」。
        if title is None and link is None:
            for href, text in b["all_anchors"]:
                if _is_bracket_label(text) or _bracket_label(text) in ("PDF", "CITATION"):
                    continue
                u = _absolutize(href)
                if not u or not _is_external(u) or u.lower().endswith(".pdf"):
                    continue
                t = _strip_leading_bracket(text)
                if t:
                    link, title = u, t
                    break
        # 兜底②(PDF):已知资源容器(gs_or_ggsm/gs_ggsd 等)未取到直链时,扫描全块 <a>,
        # 收 [PDF] 标签或 .pdf 后缀的链接(严格判定,避免把普通标题误当 PDF)。
        if not b["pdf_links"]:
            for href, text in b["all_anchors"]:
                u = _absolutize(href)
                if not u:
                    continue
                if u.lower().endswith(".pdf") or _bracket_label(text) == "PDF":
                    if u not in b["pdf_links"]:
                        b["pdf_links"].append(u)
                    if not any(r.get("link") == u for r in b["resources"]):
                        b["resources"].append(
                            {"title": text or None, "file_format": "PDF", "link": u})
        authors, venue, year = _parse_pubinfo(b["pubinfo"] or "")
        # 无 data-cid 且完全无信息的块(可能是被兜底规则误纳的非结果 gs_r 容器)不产出;
        # 带 data-cid 的块一律保留,保持既有语义不变。
        if (b["data_cid"] is None and title is None and link is None
                and not b["pubinfo"] and not b["snippet"] and not b["pdf_links"]):
            return
        self.results.append(ScholarResult(
            title=title,
            link=link,
            result_id=b["data_cid"] or None,
            snippet=b["snippet"] or None,
            publication_info=b["pubinfo"] or None,
            authors=authors,
            year=year,
            venue=venue,
            cited_by=b["cited_by"],
            versions=b["versions"],
            cluster_id=b["cluster_id"],
            pdf_links=b["pdf_links"],
            resources=b["resources"],
            position=None,
            origin="serp",
        ))

    def _open_field(self, name: str, depth: int) -> None:
        self._field = name
        self._field_depth = depth
        self._buf = []

    def _close_field(self) -> None:
        text = _norm("".join(self._buf))
        if self._field == "title":
            self._cur["rt_text"] = text
        elif self._field == "pubinfo":
            self._cur["pubinfo"] = text
        elif self._field == "snippet":
            self._cur["snippet"] = text
        self._field = None
        self._field_depth = None
        self._buf = []

    def _start_anchor(self, href: Optional[str]) -> None:
        self._in_a = True
        self._a_href = href
        self._a_text = []
        if self._field == "title":
            self._a_kind = "title"
        elif self._pdf_open:
            self._a_kind = "pdf"
        elif self._footer_depth is not None:
            self._a_kind = "footer"
        else:
            self._a_kind = None

    def _finish_anchor(self) -> None:
        text = _norm(" ".join(self._a_text))
        href = self._a_href
        kind = self._a_kind
        self._in_a = False
        self._a_href = None
        self._a_text = []
        self._a_kind = None
        if self._cur is None:
            return
        self._cur["all_anchors"].append((href, text))  # 供标题/PDF 兜底扫描
        if kind == "title":
            self._cur["rt_anchors"].append((href, text))
        elif kind == "pdf":
            url = _absolutize(href)
            if url:
                fmt = _bracket_label(text)
                self._cur["resources"].append(
                    {"title": text or None, "file_format": fmt, "link": url})
                is_pdf = (fmt == "PDF") or ("PDF" in text.upper()) or url.lower().endswith(".pdf")
                if is_pdf and url not in self._cur["pdf_links"]:
                    self._cur["pdf_links"].append(url)
        elif kind == "footer":
            if self._cur["cited_by"] is None:
                mc = _CITED_RE.search(text)
                if mc:
                    self._cur["cited_by"] = _to_int_any(mc.group(1))
            if self._cur["versions"] is None:
                mv = _VERSIONS_RE.search(text)
                if mv:
                    self._cur["versions"] = _to_int_any(mv.group(1))
                    cid = _query_param(href, "cluster")
                    if cid:
                        self._cur["cluster_id"] = cid

    # -- HTMLParser 回调 --
    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in _VOID:
            return
        ad = dict(attrs)
        class_val = ad.get("class") or ""
        classes = class_val.split()
        if "gs_ico_nav_next" in class_val:
            self.has_next = True
        self._tagstack.append(tag)
        depth = len(self._tagstack)

        # 结果块起始:首选 div.gs_r[data-cid];防御性兜底兼容 ——
        #   ① 有 gs_r 但无 data-cid 的结果块(result_id=None);
        #   ② gs_r 外壳被改名/缺失、仅剩 gs_ri 时,以 gs_ri 作块起点(仅当当前不在块内)。
        if tag == "div" and (
            "gs_r" in classes or (self._cur is None and "gs_ri" in classes)
        ):
            if self._cur is not None:
                self._finish_block()
            self._start_block(ad.get("data-cid"), depth)
            return
        if self._cur is None:
            return

        if tag == "h3" and "gs_rt" in classes:
            self._open_field("title", depth)
        elif tag == "div" and "gs_a" in classes:
            self._open_field("pubinfo", depth)
        elif tag == "div" and "gs_rs" in classes:
            self._open_field("snippet", depth)
        elif tag == "div" and any(
            c in ("gs_or_ggsm", "gs_ggsm", "gs_ggsd", "gs_ggs") for c in classes
        ):
            self._pdf_open.append(depth)
        elif tag == "div" and "gs_fl" in classes:
            self._footer_depth = depth

        if tag == "a":
            self._start_anchor(ad.get("href"))

    def handle_startendtag(self, tag, attrs):  # noqa: ANN001 - <x/> 自闭合
        if tag in _VOID:
            return
        # 非空自闭合元素:开即闭,不影响区域深度(极少见于 Scholar)。
        if tag == "a":
            self._start_anchor(dict(attrs).get("href"))
            self._finish_anchor()

    def handle_data(self, data):  # noqa: ANN001
        if self._cur is None:
            return
        if self._field is not None:
            self._buf.append(data)
        if self._in_a:
            self._a_text.append(data)

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in _VOID:
            return
        if self._in_a and tag == "a":
            self._finish_anchor()
        if tag in self._tagstack:
            while self._tagstack:
                if self._tagstack.pop() == tag:
                    break
        depth = len(self._tagstack)
        if self._cur is None:
            return
        if (self._field is not None and self._field_depth is not None
                and depth < self._field_depth):
            self._close_field()
        while self._pdf_open and depth < self._pdf_open[-1]:
            self._pdf_open.pop()
        if self._footer_depth is not None and depth < self._footer_depth:
            self._footer_depth = None
        if self._block_depth is not None and depth < self._block_depth:
            self._finish_block()


# ────────────────────────────── 对外 API ──────────────────────────────
def build_scholar_url(q: ScholarQuery) -> str:
    """由 ScholarQuery 组装 Google Scholar 结果页 URL(q/hl/as_ylo/as_yhi/start/as_sdt)。"""
    params: List = [("q", getattr(q, "q", None) or "")]
    lang = getattr(q, "lang", None)
    if lang:
        params.append(("hl", lang))
    ylo = getattr(q, "year_low", None)
    if ylo:
        params.append(("as_ylo", str(ylo)))
    yhi = getattr(q, "year_high", None)
    if yhi:
        params.append(("as_yhi", str(yhi)))
    start = getattr(q, "start", 0) or 0
    if start:
        params.append(("start", str(start)))
    params.append(("as_sdt", "0,5"))
    return SCHOLAR_BASE + "?" + urlencode(params)


def parse_serp(html: str) -> SerpPage:
    """解析 Google Scholar SERP HTML → SerpPage(含 List[ScholarResult])。

    - None / 空 / 非字符串 / 无结果 → 空 SerpPage(blocked=False);
    - 命中验证码/风控页 → SerpPage(blocked=True, results=[]);
    - 绝不抛异常。
    """
    if not isinstance(html, str) or not html:
        return SerpPage(results=[], blocked=False)
    if detect_captcha(html):
        return SerpPage(results=[], blocked=True)
    parser = _SerpParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - 解析异常不得抛给调用方
        pass
    try:
        if parser._cur is not None:      # 兜底:HTML 缺闭合标签导致的悬挂块
            parser._finish_block()
    except Exception:  # noqa: BLE001
        pass
    results = parser.results
    for i, r in enumerate(results):
        r.position = i
    return SerpPage(results=results, has_next=parser.has_next,
                    total_hint=None, blocked=False)


def _serpapi_result(item: Optional[Dict[str, Any]], position_fallback: Optional[int] = None
                    ) -> ScholarResult:
    """把单条 SerpApi ``organic_result`` 映射为 ScholarResult(防御式,绝不抛)。"""
    item = item or {}
    pub = item.get("publication_info") or {}
    api_authors: List[str] = []
    for a in (pub.get("authors") or []):
        name = (a or {}).get("name")
        if name:
            api_authors.append(name)
    inline = item.get("inline_links") or {}
    cited_by = _to_int_any((inline.get("cited_by") or {}).get("total"))
    versions_d = inline.get("versions") or {}
    versions = _to_int_any(versions_d.get("total"))
    cluster_id = versions_d.get("cluster_id")
    resources: List[Dict[str, Any]] = []
    pdf_links: List[str] = []
    for res in (item.get("resources") or []):
        res = res or {}
        link = res.get("link")
        fmt = (res.get("file_format") or "").strip()
        resources.append({"title": res.get("title"), "file_format": fmt or None, "link": link})
        if link and fmt.upper() == "PDF":
            pdf_links.append(link)
    summary = pub.get("summary")
    parsed_authors, venue, year = _parse_pubinfo(summary or "")
    pos = _to_int_any(item.get("position"))
    return ScholarResult(
        title=item.get("title"),
        link=item.get("link"),
        result_id=item.get("result_id"),
        snippet=item.get("snippet"),
        publication_info=summary,
        authors=api_authors or parsed_authors,
        year=year,
        venue=venue,
        cited_by=cited_by,
        versions=versions,
        cluster_id=cluster_id,
        pdf_links=pdf_links,
        resources=resources,
        position=pos if pos is not None else position_fallback,
        origin="serpapi",
    )


def parse_serpapi(data: Dict[str, Any]) -> List[ScholarResult]:
    """解析 SerpApi Google Scholar 完整响应的 ``organic_results`` → List[ScholarResult]。

    迁移自 B1 ``scholar_serpapi.parse_organic_results``,字段收敛到 scholar.models.ScholarResult。
    对 None / 非 dict / 缺字段一律优雅处理,绝不抛异常。
    """
    if not isinstance(data, dict):
        return []
    out: List[ScholarResult] = []
    for i, item in enumerate(data.get("organic_results") or []):
        try:
            out.append(_serpapi_result(item, i))
        except Exception:  # noqa: BLE001 - 单条异常跳过,不拖累整批
            continue
    return out


def detect_captcha(html: Optional[str], url: Optional[str] = None,
                   status: Optional[int] = None) -> bool:
    """页面/响应是否为验证码 / 风控 / 阻断页(供上游 fetcher 判断是否升级/退避/冷却)。

    命中任一即 True:
      - status ∈ {403, 429, 503}(Google 对机器人的典型阻断/限流码);
      - url 含 ``/sorry/``(Google 的人机验证跳转);
      - html 含 "unusual traffic" / "not a robot" / gs_captcha / g-recaptcha 等标志。
    对 None/空 输入返回 False。
    """
    if status is not None:
        try:
            if int(status) in (403, 429, 503):
                return True
        except (TypeError, ValueError):
            pass
    if url and "/sorry/" in str(url).lower():
        return True
    if isinstance(html, str) and html:
        low = html.lower()
        return any(marker in low for marker in _CAPTCHA_MARKERS)
    return False


# ────────────────────────────── 不联网 selftest ──────────────────────────────
def _selftest() -> int:
    # ① build_scholar_url —— 全参数 + 缺省省略
    q = ScholarQuery(raw="Attention", kind="title", q="attention is all you need",
                     num=10, start=10, year_low=2015, year_high=2020, lang="en")
    url = build_scholar_url(q)
    assert url.startswith("https://scholar.google.com/scholar?"), url
    assert "q=attention+is+all+you+need" in url, url
    assert "hl=en" in url and "as_ylo=2015" in url and "as_yhi=2020" in url, url
    assert "start=10" in url and "as_sdt=0%2C5" in url, url
    q2 = ScholarQuery(raw="x", kind="freeform", q="x")   # start=0、无年份
    url2 = build_scholar_url(q2)
    assert "start=" not in url2 and "as_ylo=" not in url2 and "as_yhi=" not in url2, url2
    assert "q=x" in url2 and "hl=en" in url2 and "as_sdt=0%2C5" in url2, url2

    # ② parse_serp —— mock SERP HTML(含右侧[PDF]、被引、All N versions、多作者、内联<b>标签)
    r1 = (
        '<div class="gs_r gs_or gs_scl" data-cid="CID111" data-rp="0">'
        '  <div class="gs_or_ggsm">'
        '    <a href="https://ex.org/paper1.pdf"><span class="gs_ctg2">[PDF]</span> ex.org</a>'
        '  </div>'
        '  <div class="gs_ri">'
        '    <h3 class="gs_rt"><a href="https://pub.example.com/p1">'
        '      Attention is <b>all</b> you need</a></h3>'
        '    <div class="gs_a">A Vaswani, N Shazeer, N Parmar - '
        '      Advances in NeurIPS, 2017 - proceedings.example.com</div>'
        '    <div class="gs_rs">We propose a new simple network architecture, '
        '      the <b>Transformer</b> ...</div>'
        '    <div class="gs_fl gs_flb">'
        '      <a href="/scholar?q=x">Save</a>'
        '      <a href="/scholar?cites=999&amp;as_sdt=5">Cited by 123456</a>'
        '      <a href="/scholar?cluster=CID111&amp;hl=en">All 42 versions</a>'
        '    </div>'
        '  </div>'
        '</div>'
    )
    # 右侧只有 [HTML](真 Scholar 的 gs_ggs>gs_ggsd 结构):不应进 pdf_links;被引小;无版本
    r2 = (
        '<div class="gs_r gs_or gs_scl" data-cid="CID222" data-rp="1">'
        '  <div class="gs_ggs gs_fl"><div class="gs_ggsd">'
        '    <a href="https://pub.example.com/full.html">'
        '      <span class="gs_ctg2">[HTML]</span> example.com</a>'
        '  </div></div>'
        '  <div class="gs_ri">'
        '    <h3 class="gs_rt"><a href="https://pub.example.com/p2">A study of something</a></h3>'
        '    <div class="gs_a">B Author, C Writer - J Example, 2020 - example.com</div>'
        '    <div class="gs_rs">Some snippet text here.</div>'
        '    <div class="gs_fl gs_flb"><a href="/scholar?cites=111">Cited by 7</a></div>'
        '  </div>'
        '</div>'
    )
    # [CITATION] 条目:无标题链接、无被引/PDF
    r3 = (
        '<div class="gs_r gs_or gs_scl" data-cid="CID333" data-rp="2">'
        '  <div class="gs_ri">'
        '    <h3 class="gs_rt"><span class="gs_ctu">[CITATION]</span> An offline-only cited work</h3>'
        '    <div class="gs_a">D Person - 1999</div>'
        '  </div>'
        '</div>'
    )
    # —— 结构变体(防御性回退)——
    # 变体①:无 data-cid 的 gs_r 结果块;PDF 直链不在已知容器,而是块内 a[href$=.pdf]。
    r4 = (
        '<div class="gs_r gs_or gs_scl">'                       # 缺 data-cid → result_id=None
        '  <div class="gs_ri">'
        '    <h3 class="gs_rt"><a href="https://pub.example.com/p4">'
        '      A resilient paper without data-cid</a></h3>'
        '    <div class="gs_a">E Editor - J Robust, 2021 - example.org</div>'
        '    <div class="gs_rs">Snippet four.</div>'
        '    <div class="gs_misc_wrap">'                        # 非已知 PDF 容器
        '      <a href="https://files.example.org/p4.pdf">Download full text</a>'
        '    </div>'
        '  </div>'
        '</div>'
    )
    # 变体②:标题容器改名(非 h3.gs_rt);标题须回退取「首个非 [PDF] 的站外链接」。
    r5 = (
        '<div class="gs_r gs_or gs_scl" data-cid="CID555">'
        '  <div class="gs_ri">'
        '    <div class="gs_newtitle">'
        '      <a href="https://files.example.org/p5.pdf"><span>[PDF]</span> files.example.org</a>'
        '      <a href="https://pub.example.com/p5">A paper whose title tag changed</a>'
        '    </div>'
        '    <div class="gs_a">F Founder - J New, 2022 - example.com</div>'
        '  </div>'
        '</div>'
    )
    # 变体③:gs_r 外壳缺失,仅剩裸 gs_ri;标题带内联 <b> 标签。
    r6 = (
        '<div class="gs_ri">'
        '  <h3 class="gs_rt"><a href="https://pub.example.com/p6">'
        '    Deep <b>Residual</b> Learning</a></h3>'
        '  <div class="gs_a">G Guru - CVPR, 2016 - example.com</div>'
        '  <div class="gs_rs">Snippet six.</div>'
        '</div>'
    )
    page = f"<html><body><div id='gs_res_ccl_mid'>{r1}{r2}{r3}{r4}{r5}{r6}</div></body></html>"
    sp = parse_serp(page)
    assert isinstance(sp, SerpPage) and sp.blocked is False, sp
    assert len(sp.results) == 6, len(sp.results)
    a, b, c, d, e, f = sp.results

    assert a.title == "Attention is all you need", a.title
    assert a.link == "https://pub.example.com/p1", a.link
    assert a.result_id == "CID111", a.result_id
    assert a.pdf_links == ["https://ex.org/paper1.pdf"], a.pdf_links
    assert a.cited_by == 123456, a.cited_by
    assert a.versions == 42, a.versions
    assert a.cluster_id == "CID111", a.cluster_id
    assert a.authors == ["A Vaswani", "N Shazeer", "N Parmar"], a.authors
    assert a.venue == "Advances in NeurIPS" and a.year == 2017, (a.venue, a.year)
    assert (a.publication_info or "").startswith("A Vaswani"), a.publication_info
    assert "Transformer" in (a.snippet or ""), a.snippet
    assert a.position == 0 and a.origin == "serp", (a.position, a.origin)

    assert b.pdf_links == [], b.pdf_links            # [HTML] 侧栏不算 PDF
    assert b.cited_by == 7 and b.versions is None, (b.cited_by, b.versions)
    assert b.cluster_id is None, b.cluster_id
    assert b.year == 2020 and b.venue == "J Example", (b.year, b.venue)
    assert b.link == "https://pub.example.com/p2" and b.result_id == "CID222", b
    assert b.position == 1, b.position

    assert c.link is None, c.link
    assert c.title == "An offline-only cited work", c.title
    assert c.cited_by is None and c.pdf_links == [], c
    assert c.year == 1999 and c.authors == ["D Person"], (c.year, c.authors)
    assert c.result_id == "CID333", c.result_id

    # 变体①:无 data-cid 仍解析;PDF 走 a[href$=.pdf] 兜底
    assert d.result_id is None, d.result_id
    assert d.title == "A resilient paper without data-cid", d.title
    assert d.link == "https://pub.example.com/p4", d.link
    assert d.pdf_links == ["https://files.example.org/p4.pdf"], d.pdf_links
    assert d.year == 2021 and d.venue == "J Robust", (d.year, d.venue)
    assert d.position == 3, d.position

    # 变体②:标题容器改名 → 标题回退到首个非 [PDF] 站外链接;[PDF] 链接进 pdf_links
    assert e.result_id == "CID555", e.result_id
    assert e.title == "A paper whose title tag changed", e.title
    assert e.link == "https://pub.example.com/p5", e.link
    assert e.pdf_links == ["https://files.example.org/p5.pdf"], e.pdf_links
    assert e.year == 2022 and e.venue == "J New", (e.year, e.venue)

    # 变体③:仅裸 gs_ri(无 gs_r 外壳)仍成块;标题内联 <b> 被正确拼接
    assert f.result_id is None, f.result_id
    assert f.title == "Deep Residual Learning", f.title
    assert f.link == "https://pub.example.com/p6", f.link
    assert f.pdf_links == [], f.pdf_links
    assert f.year == 2016 and f.venue == "CVPR", (f.year, f.venue)
    assert f.position == 5, f.position

    # 健壮性:空 / None / bytes / 无结果 → 空 SerpPage、不抛
    assert parse_serp("").results == [] and parse_serp("").blocked is False
    assert parse_serp(None).results == []            # type: ignore[arg-type]
    assert parse_serp(b"<div>").results == []         # type: ignore[arg-type]
    assert parse_serp("<html><body>no results</body></html>").results == []

    # ③ 验证码页 → SerpPage.blocked=True、results=[]
    cap_html = ("<html><body>Our systems have detected unusual traffic from your computer "
                "network. Please show you're not a robot.<div id=\"gs_captcha\"></div>"
                "<div class=\"g-recaptcha\"></div></body></html>")
    sp_cap = parse_serp(cap_html)
    assert sp_cap.blocked is True and sp_cap.results == [], sp_cap

    # ④ detect_captcha(html/url/status 多信号)
    assert detect_captcha("Our systems have detected unusual traffic ...") is True
    assert detect_captcha('<div id="gs_captcha"></div>') is True
    assert detect_captcha("<div class='g-recaptcha'>") is True
    assert detect_captcha("normal page", url="https://www.google.com/sorry/index?q=1") is True
    assert detect_captcha("", status=429) is True and detect_captcha("", status=503) is True
    assert detect_captcha(page) is False
    assert detect_captcha("") is False and detect_captcha(None) is False

    # ⑤ parse_serpapi —— 迁移自 B1,映射到 scholar.models.ScholarResult
    serpapi_data: Dict[str, Any] = {
        "organic_results": [
            {
                "position": 0, "title": "Attention is all you need", "result_id": "abc123",
                "link": "https://proceedings.example.com/attention",
                "snippet": "We propose ... the Transformer ...",
                "publication_info": {
                    "summary": "A Vaswani, N Shazeer - Advances in NIPS, 2017 - proceedings.example.com",
                    "authors": [{"name": "A Vaswani"}, {"name": "N Shazeer"}],
                },
                "resources": [{"title": "example.com", "file_format": "PDF",
                               "link": "https://example.com/attention.pdf"}],
                "inline_links": {"cited_by": {"total": 123456},
                                 "versions": {"total": 42, "cluster_id": "clu42"}},
            },
            {
                "position": 1, "title": "A paywalled paper",
                "link": "https://publisher.example.com/paywalled",
                "publication_info": {"summary": "B Author - J Example, 2020 - publisher.example.com"},
                "inline_links": {"cited_by": {"total": "7"}},   # 字符串型总数也应转 int
                "resources": [{"title": "publisher", "file_format": "HTML",
                               "link": "https://publisher.example.com/html"}],
            },
            {"title": "Bare entry"},                            # 极简条目:防御式不抛
        ]
    }
    sr = parse_serpapi(serpapi_data)
    assert len(sr) == 3 and all(isinstance(x, ScholarResult) for x in sr), sr
    assert sr[0].origin == "serpapi", sr[0].origin
    assert sr[0].title == "Attention is all you need" and sr[0].result_id == "abc123", sr[0]
    assert sr[0].authors == ["A Vaswani", "N Shazeer"], sr[0].authors
    assert sr[0].cited_by == 123456 and sr[0].versions == 42, (sr[0].cited_by, sr[0].versions)
    assert sr[0].cluster_id == "clu42", sr[0].cluster_id
    assert sr[0].pdf_links == ["https://example.com/attention.pdf"], sr[0].pdf_links
    assert sr[0].year == 2017 and sr[0].venue == "Advances in NIPS", (sr[0].year, sr[0].venue)
    assert sr[0].position == 0, sr[0].position
    assert sr[1].pdf_links == [] and sr[1].cited_by == 7 and sr[1].versions is None, sr[1]
    assert sr[1].year == 2020, sr[1].year
    assert sr[2].title == "Bare entry" and sr[2].pdf_links == [] and sr[2].authors == [], sr[2]
    assert parse_serpapi({}) == [] and parse_serpapi(None) == []  # type: ignore[arg-type]

    print("SERP_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
