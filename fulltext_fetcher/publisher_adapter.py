"""按 DOI 前缀路由的出版商适配器：封装各社更可能成功的取 PDF 策略。

规模化实测（见 检索成果-数据-规模化验证报告.md 与 经验记录 A.9）显示:一大批"定位到候选却
下不动"的失败来自出版商落地页 403 / HTML 落地页 / Crossref 的高噪声 TDM 链。本模块按 DOI
前缀识别出版商,给出**更可能成功**的取法要素,交由 download.py 在既有下载失败后多试一次:

  (a) 正确的 ``Accept: application/pdf`` 请求头（部分出版商据此做内容协商直接吐 PDF）;
  (b) 已知 PDF 路径模板（仅对能由 DOI 稳定推出直链的社收录:ACS/Springer/Wiley/IOP;
      其余社路径需内部 ID 或会话,不臆造模板,交给 header 重试 + 落地页解析 + Crossref 兜底);
  (c) 是否倾向需要 TDM 的标注（``tdm`` 布尔;**仅标注、默认不强求任何凭据**）;
  (d) ``pdf_links_from_crossref``:从 Crossref ``works.link[]`` 抽 PDF 链的**纯解析器**,
      对 ``intended-application=text-mining/similarity-checking`` 的 TDM 链**降权靠后**
      （对齐经验 A.9:TDM 链候选率最高却几乎下不动,保留为低优先级、不丢弃）。

设计约束:**纯函数、零第三方依赖、不联网**（仅标准库 re/dataclasses/typing）;可选增强,
绝不改变既有成功路径;未知前缀返回 ``None``(调用方走默认逻辑)。自带离线 selftest 打印
``PUBLISHER_ADAPTER_OK``。运行:``python -m fulltext_fetcher.publisher_adapter``。

对外接口:
- ``by_doi_prefix(doi) -> PublisherAdapter | None``
- ``PublisherAdapter.headers() -> dict`` / ``.pdf_candidates(doi=None) -> list[str]``
- ``pdf_links_from_crossref(work_json, downgrade_tdm=True) -> list[str]``
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

_ACCEPT_PDF = "application/pdf"
_TDM_APPS = ("text-mining", "similarity-checking")   # Crossref 里典型的 TDM 用途标记

# DOI 前缀 → (出版商名, PDF 直链模板元组, 是否倾向需要 TDM 凭据的标注)
# 模板仅收录"能由 DOI 稳定推出直链"的社;其余留空(靠 header 重试 + 落地页解析 + Crossref)。
_REGISTRY: Dict[str, tuple] = {
    "10.1016": ("Elsevier", (), True),                         # ScienceDirect 需会话,无稳定模板
    "10.1021": ("ACS", ("https://pubs.acs.org/doi/pdf/{doi}",), True),
    "10.1039": ("RSC", (), True),                              # 路径需内部 articleId,无 DOI 模板
    "10.1007": ("Springer", ("https://link.springer.com/content/pdf/{doi}.pdf",), False),
    "10.1002": ("Wiley", ("https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}",
                          "https://onlinelibrary.wiley.com/doi/pdf/{doi}"), True),
    "10.1111": ("Wiley", ("https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}",
                          "https://onlinelibrary.wiley.com/doi/pdf/{doi}"), True),
    "10.3390": ("MDPI", (), False),                            # OA;靠 doi 重定向落地 + landing 的 MDPI selector
    "10.1088": ("IOP", ("https://iopscience.iop.org/article/{doi}/pdf",), False),
    "10.1109": ("IEEE", (), True),                             # 需 arnumber,无 DOI 模板
}

_DOI_PREFIX_RE = re.compile(r"(10\.\d{4,9})/")
_DOI_URL_RE = re.compile(r"(?i)^\s*(?:https?://(?:dx\.)?doi\.org/|doi:)\s*")


def _normalize_doi(doi: Any) -> str:
    """去掉 ``https://doi.org/`` / ``doi:`` 前缀与首尾空白;保留 DOI 后缀原样(大小写敏感)。"""
    if not doi:
        return ""
    d = str(doi).strip()
    d = _DOI_URL_RE.sub("", d).strip()
    return d


@dataclass(frozen=True)
class PublisherAdapter:
    """某出版商的取 PDF 策略要素(由 by_doi_prefix 构造;不联网、无副作用)。"""
    key: str                        # 内部键(小写),如 'springer'
    name: str                       # 展示名,如 'Springer'
    prefix: str                     # 命中的 DOI 前缀,如 '10.1007'
    doi: str                        # 归一化后的完整 DOI
    tdm: bool = False               # 标注:是否倾向需 TDM 凭据(默认不强求凭据)
    accept: str = _ACCEPT_PDF
    templates: tuple = ()           # PDF 直链模板(含 {doi} 占位)

    def headers(self) -> Dict[str, str]:
        """出版商更可能直接吐 PDF 的请求头(内容协商)。"""
        return {"Accept": self.accept}

    def pdf_candidates(self, doi: Optional[str] = None) -> List[str]:
        """按已知模板生成 PDF 直链候选;无模板的社返回 []。"""
        d = _normalize_doi(doi) if doi else self.doi
        if not d:
            return []
        out: List[str] = []
        for t in self.templates:
            try:
                out.append(t.format(doi=d))
            except Exception:  # noqa: BLE001 - 模板异常不致命
                continue
        return out


def by_doi_prefix(doi: Any) -> Optional[PublisherAdapter]:
    """按 DOI 前缀路由到出版商适配器;未知前缀 / 非法 DOI 返回 None(走默认逻辑)。"""
    d = _normalize_doi(doi)
    if not d:
        return None
    m = _DOI_PREFIX_RE.match(d)
    if not m:
        return None
    prefix = m.group(1)
    spec = _REGISTRY.get(prefix)
    if not spec:
        return None
    name, templates, tdm = spec
    return PublisherAdapter(key=name.lower(), name=name, prefix=prefix, doi=d,
                            tdm=tdm, templates=templates)


def pdf_links_from_crossref(work_json: Any, downgrade_tdm: bool = True) -> List[str]:
    """从 Crossref ``works`` 响应抽 PDF 链;TDM 链(text-mining/similarity-checking)降权靠后。

    接受完整响应 ``{"message": {...}}`` 或直接的 message dict。判定为 PDF 的条件:
    ``content-type == application/pdf`` 或 URL(去 query 后)以 ``.pdf`` 结尾。去重保序;
    非 TDM 链在前、TDM 链在后(对齐经验 A.9:TDM 链高噪声、几乎下不动,保留为低优先级)。
    """
    if not isinstance(work_json, dict):
        return []
    msg = work_json.get("message", work_json)
    if not isinstance(msg, dict):
        return []
    links = msg.get("link") or []
    if not isinstance(links, (list, tuple)):
        return []
    primary: List[str] = []
    tdm: List[str] = []
    for ln in links:
        if not isinstance(ln, dict):
            continue
        url = str(ln.get("URL") or "").strip()
        if not url:
            continue
        ct = str(ln.get("content-type") or ln.get("content_type") or "").lower()
        path = url.split("#", 1)[0].split("?", 1)[0].lower()
        if ct != _ACCEPT_PDF and not path.endswith(".pdf"):
            continue
        ia = str(ln.get("intended-application") or ln.get("intended_application") or "").lower()
        if downgrade_tdm and ia in _TDM_APPS:
            tdm.append(url)
        else:
            primary.append(url)
    seen: set = set()
    out: List[str] = []
    for u in primary + tdm:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


if __name__ == "__main__":  # 离线 selftest: python -m fulltext_fetcher.publisher_adapter
    # ① 前缀路由正确(覆盖任务点名的各社)
    assert by_doi_prefix("10.1016/j.cell.2020.01.001").name == "Elsevier"
    assert by_doi_prefix("10.1021/jacs.0c00000").name == "ACS"
    assert by_doi_prefix("10.1039/d0sc00000a").name == "RSC"
    assert by_doi_prefix("10.1007/s00542-020-04771-3").name == "Springer"
    assert by_doi_prefix("10.1002/adma.202000000").name == "Wiley"
    assert by_doi_prefix("10.1111/jace.17000").name == "Wiley"
    assert by_doi_prefix("10.3390/app10051234").name == "MDPI"
    assert by_doi_prefix("10.1088/1748-9326/abcdef").name == "IOP"
    assert by_doi_prefix("10.1109/TPAMI.2020.1234567").name == "IEEE"

    # ② 未知前缀 / 非法 DOI → None
    assert by_doi_prefix("10.9999/unknown.prefix") is None
    assert by_doi_prefix("not-a-doi") is None
    assert by_doi_prefix("") is None
    assert by_doi_prefix(None) is None

    # ③ DOI 归一化:URL 形式 / doi: 前缀 / 首尾空白
    assert by_doi_prefix("https://doi.org/10.1007/x").name == "Springer"
    assert by_doi_prefix(" DOI:10.1021/x ").name == "ACS"
    assert by_doi_prefix("http://dx.doi.org/10.1002/y").name == "Wiley"
    assert by_doi_prefix("https://doi.org/10.1007/x").doi == "10.1007/x"

    # ④ 头生成正确
    a = by_doi_prefix("10.1007/x")
    assert a.headers() == {"Accept": "application/pdf"}, a.headers()

    # ⑤ 模板生成正确(有稳定 DOI 直链的社)
    assert by_doi_prefix("10.1007/s1").pdf_candidates() == [
        "https://link.springer.com/content/pdf/10.1007/s1.pdf"]
    assert by_doi_prefix("10.1021/jacs.0c1").pdf_candidates() == [
        "https://pubs.acs.org/doi/pdf/10.1021/jacs.0c1"]
    assert by_doi_prefix("10.1002/adma.1").pdf_candidates() == [
        "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/adma.1",
        "https://onlinelibrary.wiley.com/doi/pdf/10.1002/adma.1"]
    assert by_doi_prefix("10.1088/1/2").pdf_candidates() == [
        "https://iopscience.iop.org/article/10.1088/1/2/pdf"]
    # pdf_candidates 可传入覆盖 DOI
    assert by_doi_prefix("10.1007/a").pdf_candidates("10.1007/b") == [
        "https://link.springer.com/content/pdf/10.1007/b.pdf"]

    # ⑥ 无稳定模板的社 → 空候选(靠 header 重试 + 落地页解析 + Crossref)
    assert by_doi_prefix("10.1039/d0").pdf_candidates() == []
    assert by_doi_prefix("10.3390/app1").pdf_candidates() == []
    assert by_doi_prefix("10.1016/j.x").pdf_candidates() == []
    assert by_doi_prefix("10.1109/x").pdf_candidates() == []

    # ⑦ TDM 标注(仅标注、默认不强求凭据)
    assert by_doi_prefix("10.1016/j.x").tdm is True    # Elsevier(订阅/TDM 为主)
    assert by_doi_prefix("10.3390/x").tdm is False     # MDPI(OA)
    assert by_doi_prefix("10.1007/x").tdm is False     # Springer(多 OA,content/pdf 可直取)

    # ⑧ Crossref 解析:PDF 链抽取 + TDM 降权靠后 + 去重 + 非 PDF 忽略
    work = {"message": {"link": [
        {"URL": "https://x/tdm.pdf", "content-type": "application/pdf",
         "intended-application": "text-mining"},
        {"URL": "https://x/main.pdf", "content-type": "application/pdf",
         "intended-application": "syndication"},
        {"URL": "https://x/page.html", "content-type": "text/html",
         "intended-application": "text-mining"},
        {"URL": "https://x/bytail.PDF", "content-type": "unspecified"},
        {"URL": "https://x/main.pdf", "content-type": "application/pdf"},   # 重复
    ]}}
    got = pdf_links_from_crossref(work)
    assert got == ["https://x/main.pdf", "https://x/bytail.PDF", "https://x/tdm.pdf"], got
    # 不降权时 TDM 保持原序
    got2 = pdf_links_from_crossref(work, downgrade_tdm=False)
    assert got2 == ["https://x/tdm.pdf", "https://x/main.pdf", "https://x/bytail.PDF"], got2
    # 边界:空/畸形一律 []
    assert pdf_links_from_crossref({"message": {"link": []}}) == []
    assert pdf_links_from_crossref({}) == []
    assert pdf_links_from_crossref(None) == []
    assert pdf_links_from_crossref({"message": {"link": [{"foo": "bar"}, "junk"]}}) == []

    print("PUBLISHER_ADAPTER_OK")
