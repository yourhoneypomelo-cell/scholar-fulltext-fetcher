"""已知 OA 出版商:由 DOI 直接构造 PDF 直链候选(免搜索、纯函数、不联网)。

很多(尤其化学/材料/生医)文献来自**本身开放获取**的出版商,其 PDF 直链可由 DOI 稳定推出,
无需搜索或额外请求。本模块按 **DOI 前缀(+ 期刊代码/ID 细分)→ 出版商** 映射,直接构造候选
直链并附 `confidence`:完全 OA 且模板稳定者给高分;混合刊只对**可识别的 OA 子集**构造、其余
不臆造(避免产生大量坏候选);无稳定直链模板者退化为 doi 落地页(交 landing selector 抽 PDF)。

与既有 `fulltext_fetcher/publisher_adapter.py` 的关系(互补):后者侧重混合/订阅社的取法要素
(Accept 头 / ACS·Springer·Wiley·IOP 模板 / Crossref TDM 解析);本模块侧重**开放获取社**的
DOI→PDF 直链构造。少数混合社(Wiley/ACS/IOP/Springer)模板轻微重叠,接线进 DEFAULT_SOURCE_ORDER
时由总指挥去重/按 confidence 合并。

设计约束:纯函数、零第三方依赖、不联网、绝不抛;返回 `List[PdfCandidate]`(复用父包数据结构,
`source="publisher_oa:<社>"`、含 confidence),便于后续包成 @register 源接入。
文件边界:只改 sources/publisher_oa.py;不改 free_adapters.py / __init__.py / config.py(已接线)。
自带离线 selftest 打印 PUBLISHER_OA_OK。

对外接口(冻结):
    build_pdf_candidates(doi, title=None, cfg=None) -> list[PdfCandidate]
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple
from urllib.parse import quote

from ..models import PdfCandidate

_DOI_URL_RE = re.compile(r"(?i)^\s*(?:https?://(?:dx\.)?doi\.org/|doi:)\s*")
_DOI_SPLIT_RE = re.compile(r"^(10\.\d{4,9})/(.+)$")

# 单条候选:(url, kind, confidence, publisher_name)
_Cand = Tuple[str, str, int, str]


def _normalize_doi(doi: Any) -> str:
    if not doi:
        return ""
    return _DOI_URL_RE.sub("", str(doi).strip()).strip()


def _split_doi(d: str):
    m = _DOI_SPLIT_RE.match(d)
    return (m.group(1), m.group(2)) if m else (None, None)


def _wiley_doi_path(d: str) -> str:
    """Wiley /doi/pdf(direct)/ 路径：保留 prefix/suffix 间 `/`，仅 encode 后缀特殊字符。"""
    prefix, suffix = _split_doi(d)
    if not prefix or suffix is None:
        return quote(d, safe="")
    return f"{prefix}/{quote(suffix, safe='')}"


# ══════════════════════ 全 OA 社:纯 DOI 稳定直链 ══════════════════════
def _frontiers(d: str, suf: str) -> List[_Cand]:
    return [(f"https://www.frontiersin.org/articles/{d}/pdf", "pdf", 80, "frontiers")]


_PLOS_JOURNALS = {
    "pone": "plosone", "pbio": "plosbiology", "pmed": "plosmedicine",
    "pgen": "plosgenetics", "pcbi": "ploscompbiol", "ppat": "plospathogens",
    "pntd": "plosntds", "pclm": "climate", "pdig": "digitalhealth",
    "pwat": "water", "pgph": "globalpublichealth", "pmen": "mentalhealth",
    "pstr": "sustainabilitytransformation", "pcsy": "complexsystems",
}


def _plos(d: str, suf: str) -> List[_Cand]:
    parts = suf.split(".")
    if len(parts) >= 2 and parts[0].lower() == "journal":
        slug = _PLOS_JOURNALS.get(parts[1].lower())
        if slug:
            return [(f"https://journals.plos.org/{slug}/article/file?id={d}&type=printable",
                     "pdf", 82, "plos")]
    return [(f"https://doi.org/{d}", "landing", 40, "plos")]


def _peerj(d: str, suf: str) -> List[_Cand]:
    m = re.match(r"peerj(?:-([a-z]+))?\.(\d+)$", suf, re.I)
    if m:
        seg, num = m.group(1), m.group(2)
        art = f"{seg.lower()}-{num}" if seg else num
        return [(f"https://peerj.com/articles/{art}.pdf", "pdf", 80, "peerj")]
    return [(f"https://doi.org/{d}", "landing", 40, "peerj")]


def _elife(d: str, suf: str) -> List[_Cand]:
    m = re.match(r"elife\.(\d+)", suf, re.I)
    if m:
        nid = m.group(1)
        return [(f"https://elifesciences.org/articles/{nid}.pdf", "pdf", 62, "elife"),
                (f"https://elifesciences.org/articles/{nid}", "landing", 40, "elife")]
    return [(f"https://doi.org/{d}", "landing", 40, "elife")]


def _pnas(d: str, suf: str) -> List[_Cand]:
    return [(f"https://www.pnas.org/doi/pdf/{d}", "pdf", 50, "pnas")]


def _copernicus(d: str, suf: str) -> List[_Cand]:
    # 后缀形如 acp-20-1-2020 → https://acp.copernicus.org/articles/20/1/2020/acp-20-1-2020.pdf
    parts = suf.split("-")
    if len(parts) >= 4 and parts[1].isdigit() and parts[2].isdigit() and parts[3].isdigit():
        journal, vol, page, year = parts[0], parts[1], parts[2], parts[3]
        return [(f"https://{journal}.copernicus.org/articles/{vol}/{page}/{year}/{suf}.pdf",
                 "pdf", 65, "copernicus")]
    return [(f"https://doi.org/{d}", "landing", 40, "copernicus")]


def _beilstein(d: str, suf: str) -> List[_Cand]:
    # Beilstein(BJOC/BJNANO)全 gold OA;PDF 路径需内部 id,不臆造 → doi 落地(landing 可抽 PDF)。
    conf = 55 if re.match(r"(bjoc|bjnano)\.", suf, re.I) else 45
    return [(f"https://doi.org/{d}", "landing", conf, "beilstein")]


# ══════════════════════ 混合社:仅对可识别 OA 子集构造 ══════════════════════
def _springer_content(d: str, name: str, conf: int) -> List[_Cand]:
    """Springer/BMC content/pdf(BMC 全 OA 高分;Springer 混合刊低分,OA 文章可直取、订阅刊 403)。"""
    return [(f"https://link.springer.com/content/pdf/{d}.pdf", "pdf", conf, name)]


# Nature 全 OA 子刊的文章 ID 前缀(命中即高分):Nature Communications / Scientific Reports
# 兼容新式(s41467-*/s41598-*)与旧式(ncomms*/srep*)。其余 10.1038(Nature/Nat Catal 等混合)低分。
_NATURE_OA_PREFIXES = ("s41467", "ncomms", "s41598", "srep")


def _nature(d: str, suf: str) -> List[_Cand]:
    sl = suf.lower()
    if sl.startswith(_NATURE_OA_PREFIXES):
        conf, name = 75, "nature-oa"           # Nat Commun / Sci Rep(全 gold OA)
    else:
        conf, name = 45, "nature"              # 混合(Nature / Nat Catal / npj 等,OA 子集才命中)
    return [(f"https://www.nature.com/articles/{suf}.pdf", "pdf", conf, name)]


# RSC 金 OA 期刊代码(仅对这些构造直链;其余 RSC 多为混合,构造会 403 → 不产候选)。
_RSC_GOLD_OA = {"ra", "sc", "na", "ma", "cb", "dd"}
_RSC_RE = re.compile(r"^([cd])(\d)([a-z]{2})", re.I)


def _rsc(d: str, suf: str) -> List[_Cand]:
    m = _RSC_RE.match(suf)
    if not m:
        return []
    decade_char, year_digit, jcode = m.group(1).lower(), m.group(2), m.group(3).lower()
    if jcode not in _RSC_GOLD_OA:
        return []                               # 非金 OA 刊不臆造(避免坏候选)
    base = 2010 if decade_char == "c" else 2020  # c5..c9=2015-2019, d0..d9=2020-2029
    year = base + int(year_digit)
    url = f"https://pubs.rsc.org/en/content/articlepdf/{year}/{jcode}/{suf.lower()}"
    return [(url, "pdf", 68, "rsc-goldoa")]


# IOP 金 OA 期刊的 ISSN(DOI 后缀以 ISSN 起头):New J. Phys. / Environ. Res. Lett. 等。
_IOP_GOLD_OA_ISSN = {"1367-2630", "1748-9326", "2632-2153", "2515-7655"}


def _iop(d: str, suf: str) -> List[_Cand]:
    issn = suf.split("/", 1)[0].lower()
    if issn in _IOP_GOLD_OA_ISSN:
        return [(f"https://iopscience.iop.org/article/{d}/pdf", "pdf", 66, "iop-oa")]
    return []                                   # 混合 IOP 刊不臆造


# ACS 金 OA 期刊 token(DOI 后缀首段):ACS Omega / Central Science / *Au 等。
_ACS_GOLD_OA = {"acsomega", "acscentsci", "jacsau", "auomega"}
_ACS_AU_RE = re.compile(r"^[a-z]+au\.", re.I)    # JACS Au / ACS *Au 系列(如 acscatalau. 无;au 结尾 token)


def _acs(d: str, suf: str) -> List[_Cand]:
    token = suf.split(".", 1)[0].lower()
    if token in _ACS_GOLD_OA or token.endswith("au"):
        return [(f"https://pubs.acs.org/doi/pdf/{d}", "pdf", 65, "acs-goldoa")]
    # 其余 ACS:AuthorChoice 为条件 OA,doi/pdf 低分(与 publisher_adapter 重叠)
    return [(f"https://pubs.acs.org/doi/pdf/{d}", "pdf", 38, "acs-authorchoice")]


def _wiley_openonline(d: str, suf: str) -> List[_Cand]:
    # OnlineOpen 条件 OA;pdfdirect 对 OA 文章可直取、订阅文章 403 → 低分(与 publisher_adapter 重叠)
    # 遗留 Wiley DOI 含 ( ) : < > ; 等,后缀须 percent-encode,否则 pdfdirect 404/截断。
    enc = _wiley_doi_path(d)
    return [
        (f"https://onlinelibrary.wiley.com/doi/pdfdirect/{enc}", "pdf", 42, "wiley-onlineopen"),
        (f"https://onlinelibrary.wiley.com/doi/pdf/{enc}", "pdf", 42, "wiley-onlineopen"),
    ]


def _mdpi(d: str, suf: str) -> List[_Cand]:
    # MDPI 近乎全 OA,但 PDF 路径需 刊 ISSN + 卷/期/文号,DOI 内文号长度可变(vol 1~2 位歧义),
    # 纯 DOI 无法稳定推直链(臆造会大量 404)。故交 doi 重定向 + landing 的 MDPI selector 抽 /pdf。
    return [(f"https://doi.org/{d}", "landing", 50, "mdpi")]


def _hindawi(d: str, suf: str) -> List[_Cand]:
    return [(f"https://doi.org/{d}", "landing", 42, "hindawi")]


def _sciopen(d: str, suf: str) -> List[_Cand]:
    # SciOpen(Tsinghua Univ Press OA 平台):PDF 直链稳定为 /article/pdf/{doi}(.pdf 亦可)
    return [(f"https://www.sciopen.com/article/pdf/{d}", "pdf", 72, "sciopen")]


# DOI 前缀 → builder
_BUILDERS = {
    "10.3389": _frontiers,                                         # Frontiers(全 OA)
    "10.1371": _plos,                                             # PLOS(全 OA)
    "10.7717": _peerj,                                            # PeerJ(全 OA)
    "10.7554": _elife,                                            # eLife(全 OA)
    "10.1186": lambda d, s: _springer_content(d, "bmc", 80),      # BMC(全 OA)
    "10.1038": _nature,                                          # Nature Portfolio(OA 子刊高分)
    "10.1073": _pnas,                                            # PNAS
    "10.1007": lambda d, s: _springer_content(d, "springer", 50),  # Springer(混合)
    "10.1140": lambda d, s: _springer_content(d, "springer-epj", 48),
    "10.5194": _copernicus,                                       # Copernicus(全 OA)
    "10.3762": _beilstein,                                        # Beilstein(全 OA)
    "10.3390": _mdpi,                                            # MDPI(全 OA,无纯模板→落地)
    "10.1155": _hindawi,                                         # Hindawi(全 OA,无纯模板→落地)
    "10.26599": _sciopen,                                        # SciOpen/Tsinghua OA 平台
    "10.1039": _rsc,                                             # RSC(仅金 OA 刊构造直链)
    "10.1088": _iop,                                             # IOP(仅金 OA 刊构造直链)
    "10.1021": _acs,                                             # ACS(金 OA 高分,其余低分)
    "10.1002": _wiley_openonline,                                # Wiley OnlineOpen(条件 OA 低分)
    "10.1111": _wiley_openonline,
}

COVERED_PUBLISHERS = (
    "Frontiers", "PLOS", "PeerJ", "eLife", "BMC", "Springer", "Nature Portfolio(OA 子刊)",
    "PNAS", "Copernicus", "Beilstein", "MDPI", "Hindawi", "SciOpen", "RSC(金 OA)", "IOP(金 OA)",
    "ACS(AuthorChoice/金 OA)", "Wiley(OnlineOpen)",
)


def build_pdf_candidates(doi: Any, title: Optional[str] = None,
                         cfg: Any = None) -> List[PdfCandidate]:
    """由 DOI 构造已知 OA 出版商的 PDF 直链候选(附 confidence),按可信度降序去重返回。

    未知前缀 / 非法 DOI / 混合社非 OA 子集 → [](调用方走其它源)。title/cfg 暂不参与构造,
    保留以统一签名。绝不抛异常。
    """
    d = _normalize_doi(doi)
    if not d:
        return []
    prefix, suffix = _split_doi(d)
    if not prefix or prefix not in _BUILDERS:
        return []
    try:
        raw = _BUILDERS[prefix](d, suffix or "")
    except Exception:  # noqa: BLE001 - builder 异常绝不外抛
        return []

    seen: set = set()
    cands: List[PdfCandidate] = []
    for url, kind, conf, name in sorted(raw or [], key=lambda t: -t[2]):
        if not url or url in seen:
            continue
        seen.add(url)
        cands.append(PdfCandidate(url=url, source=f"publisher_oa:{name}",
                                  kind=kind, confidence=conf))
    return cands


# ────────────────────────── 不联网 selftest ──────────────────────────
def _selftest() -> int:
    def urls(doi):
        return [c.url for c in build_pdf_candidates(doi)]

    def first(doi):
        cs = build_pdf_candidates(doi)
        return cs[0] if cs else None

    # ① Frontiers / PLOS / PeerJ / eLife(全 OA 纯模板)
    assert first("10.3389/fchem.2020.00001").url == \
        "https://www.frontiersin.org/articles/10.3389/fchem.2020.00001/pdf"
    assert urls("10.1371/journal.pone.0213544") == [
        "https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0213544&type=printable"]
    assert urls("10.1371/journal.pxxx.1") == ["https://doi.org/10.1371/journal.pxxx.1"]
    assert urls("10.7717/peerj.991") == ["https://peerj.com/articles/991.pdf"]
    assert urls("10.7717/peerj-cs.100") == ["https://peerj.com/articles/cs-100.pdf"]
    ecs = build_pdf_candidates("10.7554/eLife.12345")
    assert ecs[0].url == "https://elifesciences.org/articles/12345.pdf" and ecs[0].confidence == 62

    # ② Nature:OA 子刊(新式 s41467-/s41598-、旧式 ncomms/srep)高分;混合刊低分(真实语料 DOI)
    assert first("10.1038/s41467-021-27116-8").url == \
        "https://www.nature.com/articles/s41467-021-27116-8.pdf"
    assert first("10.1038/s41467-021-27116-8").confidence == 75
    assert first("10.1038/srep41207").url == "https://www.nature.com/articles/srep41207.pdf"
    assert first("10.1038/srep41207").confidence == 75            # 旧式 Sci Rep 也识别为 OA
    assert first("10.1038/s41929-019-0266-y").confidence == 45    # Nat Catal(混合)低分
    assert first("10.1038/s41929-019-0266-y").source == "publisher_oa:nature"

    # ③ BMC / Springer:content/pdf(BMC 高分、Springer 混合低分)
    assert first("10.1186/s12864-020-6688-8").confidence == 80
    assert urls("10.1007/s00542-020-04771-3") == [
        "https://link.springer.com/content/pdf/10.1007/s00542-020-04771-3.pdf"]
    assert first("10.1007/s00542-020-04771-3").confidence == 50

    # ④ RSC:仅金 OA 刊(ra/sc/na/ma/cb/dd)构造 articlepdf;混合刊(真实语料 ee/cc/nj/ta/dt/cs)→ []
    assert urls("10.1039/d0sc01234b") == [
        "https://pubs.rsc.org/en/content/articlepdf/2020/sc/d0sc01234b"]
    assert first("10.1039/d0sc01234b").confidence == 68
    assert urls("10.1039/c8ra09577a") == [
        "https://pubs.rsc.org/en/content/articlepdf/2018/ra/c8ra09577a"]     # RSC Advances(金 OA)
    for hybrid in ("10.1039/c3ee44078h", "10.1039/d2cc00208f", "10.1039/d2nj03895a",
                   "10.1039/d5ta09656a", "10.1039/c4dt03470h", "10.1039/c6cs00066e"):
        assert build_pdf_candidates(hybrid) == [], hybrid                    # 混合刊不产坏候选

    # ⑤ IOP:仅金 OA ISSN(NJP 1367-2630 / ERL 1748-9326)构造;其余 → []
    assert urls("10.1088/1748-9326/ab1234") == [
        "https://iopscience.iop.org/article/10.1088/1748-9326/ab1234/pdf"]
    assert build_pdf_candidates("10.1088/0953-8984/28/1/012001") == []       # Condens. Matter(混合)

    # ⑥ ACS:金 OA(acsomega / *au)高分;其余 AuthorChoice 低分(真实语料 jacs/acscatal)
    assert first("10.1021/acsomega.0c01234").confidence == 65
    assert first("10.1021/jacsau.1c00001").confidence == 65                  # JACS Au(金 OA)
    assert first("10.1021/jacs.5c04835").confidence == 38                    # JACS(混合)
    assert first("10.1021/acscatal.7b01827").confidence == 38

    # ⑦ Wiley OnlineOpen / MDPI / Beilstein / Copernicus / Hindawi
    assert first("10.1002/adma.202000000").url == \
        "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/adma.202000000"
    _legacy_wiley = "10.1002/1099-0739(200012)14:12<836::AID-AOC97>3.0.CO;2-C"
    _legacy_enc = _wiley_doi_path(_legacy_wiley)
    _wiley_legacy_urls = urls(_legacy_wiley)
    assert _wiley_legacy_urls[0] == f"https://onlinelibrary.wiley.com/doi/pdfdirect/{_legacy_enc}", _wiley_legacy_urls
    assert "https://onlinelibrary.wiley.com/doi/pdf/" + _legacy_enc in _wiley_legacy_urls
    assert ":12:" not in _wiley_legacy_urls[0] and "%3A" in _wiley_legacy_urls[0]
    assert urls("10.3390/catal16030270") == ["https://doi.org/10.3390/catal16030270"]  # MDPI→落地
    assert first("10.3390/catal16030270").kind == "landing"
    assert first("10.3762/bjoc.16.113").confidence == 55                     # Beilstein 金 OA
    assert urls("10.5194/acp-20-1-2020") == [
        "https://acp.copernicus.org/articles/20/1/2020/acp-20-1-2020.pdf"]
    assert first("10.26599/nr.2025.94907426").url == \
        "https://www.sciopen.com/article/pdf/10.26599/nr.2025.94907426"
    assert first("10.26599/nr.2025.94907426").source == "publisher_oa:sciopen"

    # ⑧ DOI 归一化 / 未知前缀 / 空 → 契约
    assert first(" DOI:10.7717/peerj.42 ").url == "https://peerj.com/articles/42.pdf"
    assert build_pdf_candidates("10.9999/unknown.1") == []
    assert build_pdf_candidates("not-a-doi") == [] and build_pdf_candidates("") == []
    assert build_pdf_candidates(None) == []
    for c in build_pdf_candidates("10.3389/x.1"):
        assert isinstance(c, PdfCandidate) and c.source.startswith("publisher_oa:")
        assert isinstance(c.confidence, int) and c.kind in ("pdf", "landing")

    print("PUBLISHER_OA_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
