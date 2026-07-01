"""机构订阅直链源(publisher_direct):按 DOI 前缀构造订阅/混合出版商的 PDF 直链候选。

与 ``publisher_oa``(开放获取直链)互补——``publisher_oa`` 只对可识别的 **OA 子集**构造、对订阅/
混合刊刻意返回 ``[]`` 以免产生大量坏候选;本源正相反,面向**拥有合法机构订阅**的用户,对订阅/
混合出版商也按 DOI 稳定推出 PDF 直链(经机构 EZproxy/SSO 授权后即可直取)。因此本源**默认关闭**,
仅当 ``cfg.institutional=True``(CLI ``--institutional``)时才产候选。

覆盖出版商(DOI 前缀→PDF 直链模板):
  - 10.1038  Nature Portfolio     nature.com/articles/{suffix}.pdf
  - 10.1126  Science/AAAS         science.org/doi/pdf/{doi}
  - 10.1002/10.1111  Wiley        onlinelibrary.wiley.com/doi/pdf|pdfdirect/{doi}
  - 10.1007/10.1140  Springer     link.springer.com/content/pdf/{doi}.pdf
  - 10.1021  ACS                  pubs.acs.org/doi/pdf/{doi}
  - 10.1073  PNAS                 pnas.org/doi/pdf/{doi}
  - 10.1177  SAGE                 journals.sagepub.com/doi/pdf/{doi}
  - 10.1080  Taylor & Francis     tandfonline.com/doi/pdf/{doi}
  - 10.1039  RSC                  pubs.rsc.org/en/content/articlepdf/{year}/{journal}/{id}
  - 10.1103  APS(Physical Review) journals.aps.org/{jcode}/pdf/{doi}
  - 10.1016  Elsevier             先查 Crossref 拿 PII → sciencedirect.com/science/article/pii/{pii}/pdfft
  - 10.3390  MDPI                 先查 Crossref 拿 ISSN/卷/期/文号 → mdpi.com/{issn}/{vol}/{issue}/{artno}/pdf
  - 另含 metapub FindIt 风格的 Atypon 系扩展(APS Physiology/AHA/Annual Reviews/Liebert/INFORMS/SIAM)

合规声明:本源仅供拥有【合法机构订阅】、对相应内容【有权访问】的用户使用,用于在已获授权前提下
经机构 EZproxy/SSO 正常取用全文;**不得用于绕过付费墙或任何访问授权**。无有效订阅时,这些直链会
返回 401/403 或 HTML 落地页,由 ``download.py`` 的 ``%PDF`` 魔数校验自动过滤,**不会产生假成功**。

安全约束:纯构造为主(仅 Elsevier/MDPI 为拿精确路径经 ``ctx.client`` 查一次 Crossref,已限速/熔断);
绝不抛异常(单源失败不拖垮流水线,遵守 base.py 契约);未知前缀/非法 DOI/未开机构模式 → ``[]``。
自带离线 selftest 打印 ``PUBLISHER_DIRECT_OK``。运行:``python -m fulltext_fetcher.sources.publisher_direct``。

对外接口(冻结):
    build_static_candidates(doi) -> list[PdfCandidate]                # 纯构造、不联网
    build_pdf_candidates(doi, ctx=None) -> list[PdfCandidate]         # 纯构造 + (可选)Crossref 增强
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from ..models import Paper, PdfCandidate
from .base import BaseSource, SourceContext, register

_DOI_URL_RE = re.compile(r"(?i)^\s*(?:https?://(?:dx\.)?doi\.org/|doi:)\s*")
_DOI_SPLIT_RE = re.compile(r"^(10\.\d{4,9})/(.+)$")

# 单条候选:(url, publisher_name, confidence)
_Cand = Tuple[str, str, int]


def _normalize_doi(doi: Any) -> str:
    if not doi:
        return ""
    return _DOI_URL_RE.sub("", str(doi).strip()).strip()


def _split_doi(d: str) -> Tuple[Optional[str], Optional[str]]:
    m = _DOI_SPLIT_RE.match(d)
    return (m.group(1), m.group(2)) if m else (None, None)


# ── 简单模板社:直接 {doi} / 取 DOI 后缀即可稳定推直链 ──────────────────────
# prefix → (name, confidence, (url 模板含 {doi} 占位, ...))
_SIMPLE: dict = {
    "10.1126": ("science", 66, ("https://www.science.org/doi/pdf/{doi}",)),
    "10.1002": ("wiley", 66, ("https://onlinelibrary.wiley.com/doi/pdf/{doi}",
                              "https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}")),
    "10.1111": ("wiley", 66, ("https://onlinelibrary.wiley.com/doi/pdf/{doi}",
                              "https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}")),
    "10.1007": ("springer", 68, ("https://link.springer.com/content/pdf/{doi}.pdf",)),
    "10.1140": ("springer", 66, ("https://link.springer.com/content/pdf/{doi}.pdf",)),
    "10.1021": ("acs", 66, ("https://pubs.acs.org/doi/pdf/{doi}",)),
    "10.1073": ("pnas", 66, ("https://www.pnas.org/doi/pdf/{doi}",)),
    "10.1177": ("sage", 66, ("https://journals.sagepub.com/doi/pdf/{doi}",)),
    "10.1080": ("tandf", 66, ("https://www.tandfonline.com/doi/pdf/{doi}",)),
    # ── metapub FindIt 风格扩展:Atypon 系 /doi/pdf/{doi} 路径稳定 ──
    "10.1152": ("physiology", 62, ("https://journals.physiology.org/doi/pdf/{doi}",)),
    "10.1161": ("aha", 62, ("https://www.ahajournals.org/doi/pdf/{doi}",)),
    "10.1146": ("annualreviews", 62, ("https://www.annualreviews.org/doi/pdf/{doi}",)),
    "10.1089": ("liebert", 62, ("https://www.liebertpub.com/doi/pdf/{doi}",)),
    "10.1287": ("informs", 60, ("https://pubsonline.informs.org/doi/pdf/{doi}",)),
    "10.1137": ("siam", 60, ("https://epubs.siam.org/doi/pdf/{doi}",)),
}

# ── RSC:由 DOI 后缀推 年份 + 刊代码(机构订阅覆盖全刊,不限金 OA)──
_RSC_RE = re.compile(r"^([cd])(\d)([a-z]{2})", re.I)

# ── APS Physical Review:由 DOI 后缀首段刊名映射到 URL 刊代码(长名优先匹配)──
_APS_JOURNALS: Tuple[Tuple[str, str], ...] = (
    ("PhysRevLett", "prl"), ("PhysRevX", "prx"), ("PhysRevApplied", "prapplied"),
    ("PhysRevMaterials", "prmaterials"), ("PhysRevFluids", "prfluids"),
    ("PhysRevAccelBeams", "prab"), ("PhysRevPhysEducRes", "prper"),
    ("PhysRevResearch", "prresearch"), ("RevModPhys", "rmp"),
    ("PhysRevA", "pra"), ("PhysRevB", "prb"), ("PhysRevC", "prc"),
    ("PhysRevD", "prd"), ("PhysRevE", "pre"), ("PhysRev", "pr"),
)

# Elsevier PII(去分隔符后):S/B + 16 位(末位可为校验位 X)
_PII_RE = re.compile(r"^[SB][0-9X]{16}$", re.I)
_ISSN_RE = re.compile(r"^\d{4}-\d{3}[\dxX]$")


def _rsc(d: str, suffix: str) -> List[_Cand]:
    m = _RSC_RE.match(suffix)
    if not m:
        return []
    decade, ydigit, jcode = m.group(1).lower(), m.group(2), m.group(3).lower()
    base = 2010 if decade == "c" else 2020   # c5..c9=2015-2019, d0..d9=2020-2029
    year = base + int(ydigit)
    url = f"https://pubs.rsc.org/en/content/articlepdf/{year}/{jcode}/{suffix.lower()}"
    return [(url, "rsc", 66)]


def _aps(d: str, suffix: str) -> List[_Cand]:
    for pat, code in _APS_JOURNALS:
        if suffix.startswith(pat):
            return [(f"https://journals.aps.org/{code}/pdf/{d}", "aps", 64)]
    return []


def _static_for(prefix: str, d: str, suffix: str) -> List[_Cand]:
    """纯构造(不联网):按 DOI 前缀返回订阅出版商 PDF 直链候选。"""
    if prefix == "10.1038":
        return [(f"https://www.nature.com/articles/{suffix}.pdf", "nature", 70)]
    if prefix == "10.1039":
        return _rsc(d, suffix)
    if prefix == "10.1103":
        return _aps(d, suffix)
    spec = _SIMPLE.get(prefix)
    if not spec:
        return []
    name, conf, tmpls = spec
    out: List[_Cand] = []
    for t in tmpls:
        try:
            out.append((t.format(doi=d), name, conf))
        except Exception:  # noqa: BLE001 - 模板异常不致命
            continue
    return out


# ── 需一次 Crossref 查询的社(Elsevier PII / MDPI 精确坐标)────────────────
def _crossref_message(doi: str, ctx: Any) -> Optional[dict]:
    client = getattr(ctx, "client", None)
    if client is None or not hasattr(client, "get_json"):
        return None
    cfg = getattr(ctx, "cfg", None)
    email = getattr(cfg, "email", None) or "anonymous@example.com"
    try:
        data = client.get_json(f"https://api.crossref.org/works/{doi}", params={"mailto": email})
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    msg = data.get("message")
    return msg if isinstance(msg, dict) else None


def _elsevier(d: str, ctx: Any) -> List[_Cand]:
    """Elsevier:Crossref alternative-id 里取 PII → ScienceDirect /pdfft 正文直链。"""
    msg = _crossref_message(d, ctx)
    if not msg:
        return []
    for aid in (msg.get("alternative-id") or []):
        pii = re.sub(r"[^0-9A-Za-z]", "", str(aid))
        if _PII_RE.match(pii):
            url = f"https://www.sciencedirect.com/science/article/pii/{pii.upper()}/pdfft"
            return [(url, "elsevier", 72)]
    return []


def _mdpi(d: str, ctx: Any) -> List[_Cand]:
    """MDPI:Crossref 取 ISSN + 卷 + 期 + 文号 → mdpi.com/{issn}/{vol}/{issue}/{artno}/pdf。"""
    msg = _crossref_message(d, ctx)
    if not msg:
        return []
    issn = next((str(s).strip() for s in (msg.get("ISSN") or [])
                 if _ISSN_RE.match(str(s).strip())), None)
    vol = str(msg.get("volume") or "").strip()
    iss = str(msg.get("issue") or "").strip()
    art = str(msg.get("article-number") or "").strip()
    if not (issn and vol and iss and art):
        return []
    return [(f"https://www.mdpi.com/{issn}/{vol}/{iss}/{art}/pdf", "mdpi", 60)]


def _wrap(raw: List[_Cand]) -> List[PdfCandidate]:
    """(url,name,conf) 列表 → List[PdfCandidate];按 confidence 降序、去重保序。"""
    seen: set = set()
    out: List[PdfCandidate] = []
    for url, name, conf in sorted(raw or [], key=lambda t: -t[2]):
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(PdfCandidate(url=url, source=f"publisher_direct:{name}",
                                kind="pdf", confidence=conf))
    return out


def build_static_candidates(doi: Any) -> List[PdfCandidate]:
    """纯构造(不联网)的订阅出版商 PDF 直链候选;未知前缀/非法 DOI → []。绝不抛。"""
    d = _normalize_doi(doi)
    if not d:
        return []
    prefix, suffix = _split_doi(d)
    if not prefix:
        return []
    return _wrap(_static_for(prefix, d, suffix or ""))


def build_pdf_candidates(doi: Any, ctx: Any = None) -> List[PdfCandidate]:
    """订阅出版商 PDF 直链候选:纯构造 + (给了 ctx.client 时)Elsevier/MDPI 的一次 Crossref 增强。

    ctx 为 None 时退化为 build_static_candidates(不联网)。绝不抛异常。
    """
    d = _normalize_doi(doi)
    if not d:
        return []
    prefix, suffix = _split_doi(d)
    if not prefix:
        return []
    raw: List[_Cand] = list(_static_for(prefix, d, suffix or ""))
    if ctx is not None:
        try:
            if prefix == "10.1016":
                raw += _elsevier(d, ctx)
            elif prefix == "10.3390":
                raw += _mdpi(d, ctx)
        except Exception:  # noqa: BLE001 - 增强失败退回纯构造结果
            pass
    return _wrap(raw)


@register
class PublisherDirectSource(BaseSource):
    """机构订阅直链源:仅在 cfg.institutional=True 时产候选(--institutional 开启)。"""
    name = "publisher_direct"
    requires_doi = True

    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        try:
            if not getattr(getattr(ctx, "cfg", None), "institutional", False):
                return []                       # 默认关闭:未开机构模式绝不产候选
            return build_pdf_candidates(paper.doi, ctx=ctx)
        except Exception:  # noqa: BLE001 - 单源失败绝不拖垮流水线
            return []


# ────────────────────────── 不联网 selftest ──────────────────────────
def _selftest() -> int:
    from .base import REGISTRY

    # ① 注册成功
    assert "publisher_direct" in REGISTRY, REGISTRY.keys()

    def urls(doi: str) -> List[str]:
        return [c.url for c in build_static_candidates(doi)]

    # ② 简单模板社:Nature(取后缀)/ Science / PNAS / ACS / SAGE / T&F(/doi/pdf/{doi})
    assert "https://www.nature.com/articles/s41586-020-2649-2.pdf" in urls("10.1038/s41586-020-2649-2")
    assert "https://www.science.org/doi/pdf/10.1126/science.abc1234" in urls("10.1126/science.abc1234")
    assert "https://www.pnas.org/doi/pdf/10.1073/pnas.2000000117" in urls("10.1073/pnas.2000000117")
    assert "https://pubs.acs.org/doi/pdf/10.1021/jacs.0c00000" in urls("10.1021/jacs.0c00000")
    assert "https://journals.sagepub.com/doi/pdf/10.1177/0001839216655772" in urls("10.1177/0001839216655772")
    assert "https://www.tandfonline.com/doi/pdf/10.1080/00000000.2020.1234567" in urls("10.1080/00000000.2020.1234567")

    # ③ Springer content/pdf;Wiley 同时给 pdf + pdfdirect
    assert "https://link.springer.com/content/pdf/10.1007/s00542-020-04771-3.pdf" in urls("10.1007/s00542-020-04771-3")
    wu = urls("10.1002/adma.202000000")
    assert "https://onlinelibrary.wiley.com/doi/pdf/10.1002/adma.202000000" in wu
    assert any("pdfdirect" in x for x in wu), wu

    # ④ RSC:由后缀推 年份+刊代码(混合刊如 ee/cc 也构造——机构订阅可及)
    assert "https://pubs.rsc.org/en/content/articlepdf/2020/sc/d0sc01234b" in urls("10.1039/d0sc01234b")
    assert "https://pubs.rsc.org/en/content/articlepdf/2018/ee/c8ee01234a" in urls("10.1039/c8ee01234a")
    assert urls("10.1039/zzz") == []                       # 无法解析后缀 → 空

    # ⑤ APS:刊名→刊代码(PhysRevLett 优先于 PhysRev)
    assert "https://journals.aps.org/prl/pdf/10.1103/PhysRevLett.120.123456" in urls("10.1103/PhysRevLett.120.123456")
    assert "https://journals.aps.org/prb/pdf/10.1103/PhysRevB.101.014001" in urls("10.1103/PhysRevB.101.014001")

    # ⑥ source 标签 / kind 契约
    for c in build_static_candidates("10.1038/s41586-020-2649-2"):
        assert isinstance(c, PdfCandidate) and c.source.startswith("publisher_direct:") and c.kind == "pdf"

    # ⑦ 未知前缀 / 非法 DOI / 空 → []
    assert build_static_candidates("10.9999/unknown.1") == []
    assert build_static_candidates("not-a-doi") == [] and build_static_candidates("") == []
    assert build_pdf_candidates(None) == []

    # ⑧ Elsevier:用假 client 从 Crossref alternative-id 提 PII → /pdfft
    class _Cli:
        def __init__(self, data: Any):
            self._d = data

        def get_json(self, url: str, **kw: Any) -> Any:
            return self._d

    class _Ctx:
        def __init__(self, data: Any, inst: bool = True):
            self.client = _Cli(data)
            self.cfg = type("C", (), {"institutional": inst, "email": "a@b.c"})()
            self.log = None
            self.events = None

    els = build_pdf_candidates(
        "10.1016/j.cell.2020.01.001",
        ctx=_Ctx({"message": {"alternative-id": ["S0092-8674(20)30001-1"]}}))
    assert els and els[0].url == \
        "https://www.sciencedirect.com/science/article/pii/S0092867420300011/pdfft", els
    assert els[0].source == "publisher_direct:elsevier"
    # 无 PII → 空
    assert build_pdf_candidates("10.1016/x", ctx=_Ctx({"message": {}})) == []

    # ⑨ MDPI:用假 client 从 Crossref 取 ISSN/卷/期/文号 → /pdf
    md = build_pdf_candidates(
        "10.3390/catal16030270",
        ctx=_Ctx({"message": {"ISSN": ["2073-4344"], "volume": "16",
                              "issue": "3", "article-number": "270"}}))
    assert md and md[0].url == "https://www.mdpi.com/2073-4344/16/3/270/pdf", md
    # 缺字段 → 空
    assert build_pdf_candidates("10.3390/x", ctx=_Ctx({"message": {"ISSN": ["2073-4344"]}})) == []

    # ⑩ 机构开关:institutional=False → 适配器产 [];True → 有候选
    off = PublisherDirectSource().find_candidates(
        Paper(doi="10.1038/s41586-020-2649-2"), _Ctx(None, inst=False))
    assert off == [], off
    on = PublisherDirectSource().find_candidates(
        Paper(doi="10.1038/s41586-020-2649-2"), _Ctx(None, inst=True))
    assert on and all(isinstance(c, PdfCandidate) for c in on), on

    # ⑪ Elsevier/MDPI 在无 ctx(纯构造)时不产候选(需 Crossref)
    assert build_static_candidates("10.1016/j.cell.2020.01.001") == []
    assert build_static_candidates("10.3390/catal16030270") == []

    print("PUBLISHER_DIRECT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
