"""从 HTML 落地页提取内嵌的 PDF 直链。

规模化实测痛点:很多源(出版商页、PMC、机构库)返回的是 HTML 落地页而非 PDF
直链,download.py 会判为 landing-page 而下不动。本模块负责"再走一步":把落地页
HTML 里真正的 PDF 地址抠出来,交给下游重试下载。

提取置信度从高到低(分桶,保序去重后拼接):
  1) <meta> 强信号:name/property="citation_pdf_url"(Highwire/Google Scholar 标准,
     最可靠)、bepress_citation_pdf_url(bepress/Digital Commons 机构库)、
     og:pdf / og:pdf:url(Open Graph)。兼容大小写、属性顺序不同、自闭合写法。
  2) JSON-LD(<script type="application/ld+json">)中 encodingFormat=application/pdf
     的 contentUrl/url/downloadUrl —— schema.org ScholarlyArticle 常用,出版商页多见。
  3) <link rel=... type="application/pdf" href="..."> 或 href 指向 PDF 的 <link>。
  4) data-* 属性(data-pdf-url / data-download-url / data-src 等)中指向 PDF 的值。
  5) 出版商专属 selector / 已知 PDF 路径模板(按落地页所属出版商域名启用):
     Elsevier(sciencedirect,/pdfft、/pii/…pdf)、Springer(/content/pdf/…pdf)、
     Wiley(/doi/pdf/、/doi/pdfdirect/)、ACS(/doi/pdf/)、RSC(articlepdf)、
     IEEE(getPDF/stampPDF、/ielx…pdf)、MDPI(…/pdf)。
  6) <a>/<embed>/<iframe> 的 href/src 中以 .pdf 结尾 或 路径含 /pdf 的通用链接。
  7) 纯解析式重定向目标:<meta http-equiv="refresh" content="0;url=…">、
     <link rel="canonical">、内联脚本里的 location.href/replace/assign 跳转——
     仅当目标本身看起来是 PDF 时才纳入(绝不因此发起任何额外网络请求)。
  8) <meta name="DC.identifier"/"DC.relation"> 等弱信号,仅当取值是 PDF 才纳入。
全部经 urljoin 转绝对 URL,按上面顺序去重保序返回。

设计约束:零第三方依赖(仅标准库 html.parser + json + re + urllib.parse);纯函数、
不联网、无副作用;对 None/空/乱码/非字符串输入一律不报错,返回 []。误报无妨——
download.py 仍会用 %PDF 魔数与体积二次校验,本模块只管多给候选。

对外契约(download.py / pipeline 依赖,保持不变):
    extract_pdf_links(html: str, base_url: str) -> List[str]
    返回按置信度从高到低去重后的 PDF 直链绝对 URL 列表。
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import urljoin, urlparse

_LINK_TAGS = ("a", "embed", "iframe")
_SKIP_PREFIXES = ("javascript:", "mailto:", "tel:", "data:")
_PDF_MIME = "application/pdf"

# <meta> 强信号:取值直接当作 PDF 直链(这些键的语义就是"本文 PDF 地址")。
_STRONG_META_KEYS = (
    "citation_pdf_url",
    "bepress_citation_pdf_url",
    "og:pdf",
    "og:pdf:url",
)
# <meta> 弱信号:取值可能是 DOI/HTML,仅当它本身像 PDF 才纳入(低置信度桶)。
_WEAK_META_KEYS = ("dc.identifier", "dc.relation")

# 内联脚本里的显式跳转:location.href/replace/assign、window/document/top/self.location。
# 仅提取被引号包裹的目标 URL;是否采纳再由 _is_pdf_url / 出版商模板过滤。
_JUMP_RE = re.compile(
    r"\b(?:"
    r"window\.location(?:\.href)?|document\.location(?:\.href)?|"
    r"top\.location(?:\.href)?|self\.location(?:\.href)?|"
    r"location\.(?:href|replace|assign)"
    r")\s*(?:=|\()\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)

# 内联脚本缓冲上限:仅用于跳转识别,避免超大内联 JSON/打包脚本撑爆内存。
_SCRIPT_CAP = 262144


def _should_skip(u: str) -> bool:
    """空链接、纯锚点与非 http 资源协议直接丢弃。"""
    low = u.strip().lower()
    if not low or low.startswith("#"):
        return True
    return low.startswith(_SKIP_PREFIXES)


def _is_pdf_url(u: str) -> bool:
    """路径(去掉 ?query 和 #frag 后)以 .pdf 结尾,或含 /pdf 段即视为候选。"""
    path = u.split("#", 1)[0].split("?", 1)[0].lower()
    return path.endswith(".pdf") or "/pdf" in path


def _publisher_of(base_url: str) -> str:
    """由落地页 URL 的域名判定出版商,用于启用其专属 PDF selector。"""
    try:
        host = (urlparse(base_url).hostname or "").lower()
    except Exception:  # noqa: BLE001 - 畸形 base_url 不影响其它桶
        return ""
    if not host:
        return ""
    if "sciencedirect" in host or "elsevier" in host:
        return "elsevier"
    if "springer" in host:  # link.springer.com / rd.springer.com
        return "springer"
    if "wiley" in host:  # onlinelibrary.wiley.com
        return "wiley"
    if host == "acs.org" or host.endswith(".acs.org"):  # pubs.acs.org
        return "acs"
    if "rsc.org" in host:  # pubs.rsc.org
        return "rsc"
    if "ieee" in host:  # ieeexplore.ieee.org
        return "ieee"
    if host == "mdpi.com" or host.endswith(".mdpi.com"):
        return "mdpi"
    return ""


def _is_publisher_pdf(publisher: str, url: str) -> bool:
    """按出版商已知 PDF 路径模板判断某 href 是否为其正文 PDF 直链。

    仅在识别出出版商时启用;命中的链接会被置于高置信度桶(优先于通用 /pdf 链接),
    并能捕捉通用规则漏掉的形态(如 RSC 的 articlepdf、IEEE 的 getPDF.jsp)。
    """
    if not publisher:
        return False
    low = url.strip().lower()
    if not low:
        return False
    path = low.split("#", 1)[0].split("?", 1)[0]
    if publisher == "elsevier":
        # 正文 PDF 的稳定标记是 /pdfft(或 CDN sciencedirectassets);
        # /pii/…/mmc*.pdf 等补充材料交给通用 .pdf 桶,避免抢占正文。
        return "/pdfft" in low or "sciencedirectassets" in low
    if publisher == "springer":
        return "/content/pdf/" in low
    if publisher == "wiley":
        return "/doi/pdf/" in low or "/doi/pdfdirect/" in low
    if publisher == "acs":
        return "/doi/pdf/" in low
    if publisher == "rsc":
        return "articlepdf" in low
    if publisher == "ieee":
        return ("getpdf" in low or "stamppdf" in low
                or (("/ielx" in low or "/iel" in low) and path.endswith(".pdf")))
    if publisher == "mdpi":
        return path.rstrip("/").endswith("/pdf")
    return False


def _parse_meta_refresh(content: str) -> Optional[str]:
    """从 <meta http-equiv=refresh content="N; url=..."> 中抠出跳转目标 URL。"""
    if not content:
        return None
    idx = content.lower().find("url=")
    if idx == -1:
        return None
    target = content[idx + 4:].strip().strip("'\"").strip()
    return target or None


def _dedupe(urls: List[str]) -> List[str]:
    """去重保序:保留每个 URL 的首次出现位置。"""
    seen = set()
    out: List[str] = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _collect_jsonld_pdf(node, acc: List[str], depth: int = 0) -> None:
    """在 JSON-LD 节点中递归找 PDF 资源链接(encodingFormat=application/pdf 或 .pdf URL)。"""
    if depth > 8 or len(acc) > 20:
        return
    if isinstance(node, dict):
        fmt = str(node.get("encodingFormat") or node.get("fileFormat") or "").lower()
        for key in ("contentUrl", "url", "downloadUrl"):
            val = node.get(key)
            if isinstance(val, str) and val.strip():
                v = val.strip()
                # 相对路径也接受(交由 extract_pdf_links 的 urljoin 绝对化)
                if _PDF_MIME in fmt or _is_pdf_url(v):
                    acc.append(v)
        for v in node.values():
            _collect_jsonld_pdf(v, acc, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _collect_jsonld_pdf(item, acc, depth + 1)


class _LinkCollector(HTMLParser):
    """单遍扫描:按置信度分桶收集 meta / JSON-LD / link / data-* / 出版商 / 通用 /
    重定向 / 弱 meta 的 PDF 链接。"""

    def __init__(self, publisher: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self._pub = publisher
        self.meta_urls: List[str] = []       # 1) 强 meta(最高)
        self.jsonld_urls: List[str] = []     # 2) JSON-LD
        self.link_rel_urls: List[str] = []   # 3) <link type=application/pdf>
        self.data_urls: List[str] = []       # 4) data-* 属性
        self.publisher_urls: List[str] = []  # 5) 出版商专属
        self.link_urls: List[str] = []       # 6) 通用 a/embed/iframe
        self.redirect_urls: List[str] = []   # 7) 重定向目标(meta refresh/canonical/JS)
        self.weak_meta_urls: List[str] = []  # 8) 弱 meta(DC.*,最低)
        self._in_jsonld = False
        self._jsonld_buf: List[str] = []
        self._in_script = False
        self._script_buf: List[str] = []
        self._script_len = 0

    def _pub_or_pdf(self, u: str) -> bool:
        """通用 .pdf/含 /pdf,或本页出版商的专属 PDF 模板——都算 PDF 候选。"""
        return _is_pdf_url(u) or _is_publisher_pdf(self._pub, u)

    def _collect_data_attrs(self, attr: dict) -> None:
        """扫描任意标签的 data-* 属性,取值像 PDF 就纳入 data 桶(懒加载/自定义下载按钮常见)。"""
        for k, v in attr.items():
            if not v or not k.startswith("data-"):
                continue
            val = v.strip()
            if not val or _should_skip(val):
                continue
            if self._pub_or_pdf(val):
                self.data_urls.append(val)

    def handle_starttag(self, tag, attrs):  # noqa: ANN001 - HTMLParser 回调签名固定
        # 保留每个属性的首次取值;属性名已被 HTMLParser 统一转小写
        attr = {}
        for k, v in attrs:
            if k is not None and k not in attr:
                attr[k] = v if v is not None else ""

        # data-* 属性对所有标签生效,先扫一遍(不受下面各分支 return 影响)
        self._collect_data_attrs(attr)

        if tag == "meta":
            # ⑦ meta refresh 跳转:content="N; url=..."
            if (attr.get("http-equiv") or "").strip().lower() == "refresh":
                target = _parse_meta_refresh(attr.get("content") or "")
                if target and not _should_skip(target) and self._pub_or_pdf(target):
                    self.redirect_urls.append(target)
                return
            key = (attr.get("name") or attr.get("property") or "").strip().lower()
            content = (attr.get("content") or "").strip()
            if not content:
                return
            if key in _STRONG_META_KEYS:
                self.meta_urls.append(content)
            elif key in _WEAK_META_KEYS and _is_pdf_url(content):
                self.weak_meta_urls.append(content)
            return

        if tag == "script":
            typ = (attr.get("type") or "").strip().lower()
            if typ == "application/ld+json":
                self._in_jsonld = True
                self._jsonld_buf = []
            else:
                self._in_script = True
                self._script_buf = []
                self._script_len = 0
            return

        if tag == "link":
            href = (attr.get("href") or "").strip()
            if not href or _should_skip(href):
                return
            typ = (attr.get("type") or "").strip().lower()
            if typ == _PDF_MIME or _is_pdf_url(href):
                self.link_rel_urls.append(href)
                return
            # ⑦ canonical 指向 PDF(仅出版商模板能识别的形态才补,通用 pdf 已在上面命中)
            rel = (attr.get("rel") or "").strip().lower()
            if "canonical" in rel.split() and _is_publisher_pdf(self._pub, href):
                self.redirect_urls.append(href)
            return

        if tag in _LINK_TAGS:
            u = (attr.get("href") or attr.get("src") or "").strip()
            if not u or _should_skip(u):
                return
            if _is_publisher_pdf(self._pub, u):
                self.publisher_urls.append(u)
            elif _is_pdf_url(u):
                self.link_urls.append(u)

    def handle_data(self, data):  # noqa: ANN001
        if self._in_jsonld:
            self._jsonld_buf.append(data)
        elif self._in_script and self._script_len < _SCRIPT_CAP:
            self._script_buf.append(data)
            self._script_len += len(data)

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag != "script":
            return
        if self._in_jsonld:
            self._in_jsonld = False
            raw = "".join(self._jsonld_buf).strip()
            self._jsonld_buf = []
            if not raw:
                return
            try:
                data = json.loads(raw)
            except Exception:  # noqa: BLE001 - 畸形 JSON-LD 不能影响其它提取
                return
            urls: List[str] = []
            _collect_jsonld_pdf(data, urls)
            self.jsonld_urls.extend(urls)
        elif self._in_script:
            self._in_script = False
            raw = "".join(self._script_buf)
            self._script_buf = []
            self._script_len = 0
            if not raw:
                return
            # ⑦ 内联脚本里的显式 location 跳转,目标像 PDF 才纳入
            for m in _JUMP_RE.finditer(raw):
                target = (m.group(1) or "").strip()
                if target and not _should_skip(target) and self._pub_or_pdf(target):
                    self.redirect_urls.append(target)


def extract_pdf_links(html: str, base_url: str) -> list[str]:
    """从落地页 HTML 提取可能的 PDF 直链,按置信度从高到低去重返回绝对 URL 列表。"""
    if not isinstance(html, str) or not html:
        return []
    base = base_url if isinstance(base_url, str) else ""

    collector = _LinkCollector(publisher=_publisher_of(base))
    try:
        collector.feed(html)
        collector.close()
    except Exception:  # noqa: BLE001 - 极端畸形输入也绝不能让调用方崩
        pass

    absolute: List[str] = []
    # 置信度桶顺序:强 meta > JSON-LD > link[type=pdf] > data-* > 出版商 >
    #               通用 a/embed/iframe > 重定向目标 > 弱 meta(DC.*)
    for u in (collector.meta_urls
              + collector.jsonld_urls
              + collector.link_rel_urls
              + collector.data_urls
              + collector.publisher_urls
              + collector.link_urls
              + collector.redirect_urls
              + collector.weak_meta_urls):
        try:
            absolute.append(urljoin(base, u))
        except Exception:  # noqa: BLE001
            continue
    return _dedupe(absolute)


if __name__ == "__main__":
    # ① citation_pdf_url meta(覆盖大小写 / 属性顺序 / property 变体 / 自闭合)
    h1 = (
        "<html><head>"
        '<META NAME="Citation_Title" CONTENT="Foo">'
        '<meta content="https://ex.com/papers/foo.pdf" name="citation_pdf_url">'
        '<meta property="citation_pdf_url" content="/papers/foo.pdf" />'
        "</head><body>"
        '<a href="/article/9/pdf">PDF</a>'
        "</body></html>"
    )
    r1 = extract_pdf_links(h1, "https://ex.com/article/9")
    assert r1[0] == "https://ex.com/papers/foo.pdf", r1            # meta 最高优先且已绝对化
    assert "https://ex.com/article/9/pdf" in r1, r1               # <a> 含 /pdf 命中
    assert r1.count("https://ex.com/papers/foo.pdf") == 1, r1     # name 与 property 同址去重
    assert r1.index("https://ex.com/papers/foo.pdf") < r1.index(  # 置信度排序:meta 在前
        "https://ex.com/article/9/pdf"
    ), r1

    # ② 相对路径 /article/123/pdf 的 <a> → urljoin 绝对化
    h2 = '<a href="/article/123/pdf">Full Text</a>'
    assert extract_pdf_links(h2, "https://pub.org/x") == [
        "https://pub.org/article/123/pdf"
    ]

    # ③ 无 PDF 链接 → []
    h3 = '<a href="/home">home</a> <a href="mailto:a@b.com">m</a> <a href="#top">t</a>'
    assert extract_pdf_links(h3, "https://pub.org/x") == []

    # ④ embed / iframe 与文档内顺序
    h4 = '<iframe src="https://host/v/doc.pdf"></iframe><embed src="/f/y.pdf">'
    assert extract_pdf_links(h4, "https://host/a/b") == [
        "https://host/v/doc.pdf",
        "https://host/f/y.pdf",
    ]

    # ⑤ .pdf 携带 query 仍应识别
    h5 = '<a href="/files/a.pdf?download=1">d</a>'
    assert extract_pdf_links(h5, "https://x.org/p") == [
        "https://x.org/files/a.pdf?download=1"
    ]

    # ⑥ 健壮性:None / 空 / 非 str / 乱码 一律返回 [] 且不抛异常
    assert extract_pdf_links(None, "https://x") == []
    assert extract_pdf_links("", "https://x") == []
    assert extract_pdf_links(b"<a href=x.pdf>", "https://x") == []
    assert extract_pdf_links("\x00\xff not html <<< >>>", "https://x") == []

    # ⑦ JSON-LD:encodingFormat=application/pdf 的 contentUrl
    h7 = (
        '<script type="application/ld+json">'
        '{"@type":"ScholarlyArticle","name":"X",'
        '"encoding":{"encodingFormat":"application/pdf",'
        '"contentUrl":"https://ex.com/full/x.pdf"}}'
        "</script>"
    )
    assert extract_pdf_links(h7, "https://ex.com/abs/1") == [
        "https://ex.com/full/x.pdf"
    ], extract_pdf_links(h7, "https://ex.com/abs/1")

    # ⑧ <link type="application/pdf"> 即使路径不含 .pdf 也应识别
    h8 = '<link rel="alternate" type="application/pdf" href="/download/567">'
    assert extract_pdf_links(h8, "https://pub.org/x") == [
        "https://pub.org/download/567"
    ], extract_pdf_links(h8, "https://pub.org/x")

    # ⑨ 置信度排序:meta > json-ld > link > a
    h9 = (
        '<a href="/a.pdf">a</a>'
        '<link type="application/pdf" href="/l.pdf">'
        '<script type="application/ld+json">'
        '{"encodingFormat":"application/pdf","contentUrl":"/j.pdf"}</script>'
        '<meta name="citation_pdf_url" content="/m.pdf">'
    )
    r9 = extract_pdf_links(h9, "https://h.org/p")
    assert r9 == [
        "https://h.org/m.pdf",
        "https://h.org/j.pdf",
        "https://h.org/l.pdf",
        "https://h.org/a.pdf",
    ], r9

    # ⑩ 畸形 JSON-LD 不影响其它桶
    h10 = (
        '<script type="application/ld+json">{bad json,,,}</script>'
        '<meta name="citation_pdf_url" content="https://ok.org/x.pdf">'
    )
    assert extract_pdf_links(h10, "https://ok.org/p") == ["https://ok.org/x.pdf"]

    # ===== 以下为本次新增:出版商专属 selector / meta 变体 / 重定向解析 =====

    # ⑪ Elsevier(ScienceDirect):/pdfft 优先于通用 supplementary .pdf(证明出版商桶 > 通用桶)
    h11 = (
        '<a href="/science/article/pii/S00/mmc1.pdf">supplement</a>'
        '<a href="/science/article/pii/S00/pdfft?md5=a">PDF</a>'
    )
    base11 = "https://www.sciencedirect.com/science/article/pii/S00"
    r11 = extract_pdf_links(h11, base11)
    pdfft = "https://www.sciencedirect.com/science/article/pii/S00/pdfft?md5=a"
    supp = "https://www.sciencedirect.com/science/article/pii/S00/mmc1.pdf"
    assert r11[0] == pdfft, r11
    assert supp in r11 and r11.index(pdfft) < r11.index(supp), r11

    # ⑫ Springer:/content/pdf/<doi>.pdf
    h12 = '<a href="/content/pdf/10.1007%2Fs00542-020-04771-3.pdf">Download PDF</a>'
    assert extract_pdf_links(
        h12, "https://link.springer.com/article/10.1007/s00542-020-04771-3"
    ) == ["https://link.springer.com/content/pdf/10.1007%2Fs00542-020-04771-3.pdf"]

    # ⑬ Wiley:pdfdirect 命中,epdf(在线阅读器,非 PDF)不误纳
    h13 = (
        '<a href="/doi/epdf/10.1002/adma.202000000">ePDF reader</a>'
        '<a href="/doi/pdfdirect/10.1002/adma.202000000">PDF</a>'
    )
    assert extract_pdf_links(
        h13, "https://onlinelibrary.wiley.com/doi/10.1002/adma.202000000"
    ) == ["https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/adma.202000000"], \
        extract_pdf_links(h13, "https://onlinelibrary.wiley.com/doi/10.1002/adma.202000000")

    # ⑭ ACS:/doi/pdf/<doi>
    h14 = '<a href="/doi/pdf/10.1021/jacs.0c00000">PDF</a>'
    assert extract_pdf_links(h14, "https://pubs.acs.org/doi/10.1021/jacs.0c00000") == [
        "https://pubs.acs.org/doi/pdf/10.1021/jacs.0c00000"
    ]

    # ⑮ RSC:articlepdf —— 通用规则会漏(不含 .pdf/"/pdf"),必须靠出版商模板
    rsc_href = "/en/content/articlepdf/2020/sc/d0sc00000a"
    assert not _is_pdf_url(rsc_href), "RSC articlepdf 不应被通用规则命中"
    h15 = f'<a href="{rsc_href}">Download PDF</a>'
    assert extract_pdf_links(
        h15, "https://pubs.rsc.org/en/content/articlehtml/2020/sc/d0sc00000a"
    ) == ["https://pubs.rsc.org" + rsc_href]

    # ⑯ IEEE:getPDF.jsp —— 通用规则会漏,靠出版商模板
    ieee_href = "/stamp/stampPDF/getPDF.jsp?tp=&arnumber=8600702"
    assert not _is_pdf_url(ieee_href), "IEEE getPDF.jsp 不应被通用规则命中"
    h16 = f'<a href="{ieee_href}">Full-Text PDF</a>'
    assert extract_pdf_links(h16, "https://ieeexplore.ieee.org/document/8600702") == [
        "https://ieeexplore.ieee.org" + ieee_href
    ]

    # ⑰ MDPI:.../pdf 优先于站内其它 .pdf(logo)
    h17 = (
        '<a href="/img/journals/logo.pdf">brochure</a>'
        '<a href="/2073-4409/9/5/1234/pdf">Download PDF</a>'
    )
    r17 = extract_pdf_links(h17, "https://www.mdpi.com/2073-4409/9/5/1234")
    assert r17[0] == "https://www.mdpi.com/2073-4409/9/5/1234/pdf", r17

    # ⑱ Open Graph:og:pdf 强 meta
    h18 = '<meta property="og:pdf" content="https://ex.org/f/og.pdf">'
    assert extract_pdf_links(h18, "https://ex.org/p") == ["https://ex.org/f/og.pdf"]

    # ⑲ bepress_citation_pdf_url(Digital Commons):取值即视为 PDF,即使不含 .pdf
    h19 = (
        '<meta name="bepress_citation_pdf_url" '
        'content="https://repo.edu/cgi/viewcontent.cgi?article=1&context=x">'
    )
    assert extract_pdf_links(h19, "https://repo.edu/p") == [
        "https://repo.edu/cgi/viewcontent.cgi?article=1&context=x"
    ]

    # ⑳ DC.identifier:仅当取值像 PDF 才纳入;DOI 形态应被忽略
    h20 = (
        '<meta name="DC.identifier" content="https://x.org/paper.pdf">'
        '<meta name="dc.identifier" content="doi:10.1/xyz">'
    )
    assert extract_pdf_links(h20, "https://x.org/a") == ["https://x.org/paper.pdf"], \
        extract_pdf_links(h20, "https://x.org/a")

    # ㉑ meta refresh 跳转到 PDF → 纳入(相对路径也绝对化)
    h21 = '<meta http-equiv="refresh" content="0; url=/redir/final.pdf">'
    assert extract_pdf_links(h21, "https://cdn.org/x") == ["https://cdn.org/redir/final.pdf"]

    # ㉒ meta refresh 跳转到非 PDF(登录页)→ 不纳入
    h22 = '<meta http-equiv="refresh" content="0; url=/login?next=/article">'
    assert extract_pdf_links(h22, "https://cdn.org/x") == []

    # ㉓ data-* 属性(按钮无 href,仅 data-pdf-url)
    h23 = '<a class="btn" data-pdf-url="/dl/secure/9.pdf">Download</a>'
    assert extract_pdf_links(h23, "https://s.org/x") == ["https://s.org/dl/secure/9.pdf"]

    # ㉔ 内联脚本 location.href 跳转到 PDF
    h24 = '<script>window.location.href = "https://host.org/go/paper.pdf";</script>'
    assert extract_pdf_links(h24, "https://host.org/a") == [
        "https://host.org/go/paper.pdf"
    ], extract_pdf_links(h24, "https://host.org/a")

    # ㉕ 综合排序:强meta > jsonld > link > data-* > 出版商 > 通用 > 重定向 > 弱meta
    h25 = (
        '<a href="/gen.pdf">g</a>'
        '<a href="/en/content/articlepdf/1/a/b">pub</a>'
        '<a data-pdf-url="/data/d.pdf">d</a>'
        '<link type="application/pdf" href="/l.pdf">'
        '<script type="application/ld+json">'
        '{"encodingFormat":"application/pdf","contentUrl":"/j.pdf"}</script>'
        '<meta name="citation_pdf_url" content="/m.pdf">'
        '<meta http-equiv="refresh" content="0;url=/r.pdf">'
        '<meta name="DC.identifier" content="/w.pdf">'
    )
    r25 = extract_pdf_links(h25, "https://pubs.rsc.org/x")
    assert r25 == [
        "https://pubs.rsc.org/m.pdf",             # 强 meta
        "https://pubs.rsc.org/j.pdf",             # JSON-LD
        "https://pubs.rsc.org/l.pdf",             # link[type=pdf]
        "https://pubs.rsc.org/data/d.pdf",        # data-*
        "https://pubs.rsc.org/en/content/articlepdf/1/a/b",  # 出版商(RSC)
        "https://pubs.rsc.org/gen.pdf",           # 通用 a
        "https://pubs.rsc.org/r.pdf",             # 重定向(meta refresh)
        "https://pubs.rsc.org/w.pdf",             # 弱 meta(DC.identifier)
    ], r25

    # ㉖ 非出版商域名下,出版商模板不误伤既有排序(回归保护 ⑨ 语义)
    h26 = '<a href="/en/content/articlepdf/1/a/b">x</a>'
    assert extract_pdf_links(h26, "https://random.org/p") == [], \
        extract_pdf_links(h26, "https://random.org/p")

    print("SELFTEST_OK")
