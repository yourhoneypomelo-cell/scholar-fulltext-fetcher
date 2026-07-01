"""原始输入 → ScholarQuery(《谷歌学术爬虫-架构与选型.md》§3.3)。

职责:把一条原始输入(标题 / DOI / arXiv / 自由检索式)规范化为 ScholarQuery——
判类型复用父包 resolve.classify_input(doi/arxiv → 精确 q;其余 → title / freeform),
并填 num / start(分页) / year_low / year_high / lang。URL 组装在 serp.build_scholar_url,
本模块不产出 URL。

对外接口(冻结,供 cli/pipeline 调用、serp 消费其产物):
- build_query(raw, cfg, page=0) -> ScholarQuery
- normalize_title(t) -> str          # 去噪、折叠空白,供 q
- doi_query(doi) -> str              # DOI 的 Scholar 检索式(直接 q=<裸 doi>)
- title_match_score(a, b) -> float   # 附:标题 Jaccard,供下游从 SERP 候选挑最佳匹配

相似度思路复用 resolve._title_similarity / _norm_title(只读参考、未改动 resolve.py)。
纯标准库、不联网。selftest:python -m fulltext_fetcher.scholar.query
"""
from __future__ import annotations

import re
from typing import Optional

from ..resolve import classify_input
from .config import ScholarConfig
from .models import ScholarQuery

# 常见 DOI 前缀(剥离后得到裸 DOI,供 Scholar 直接检索)。
_DOI_PREFIXES = (
    "https://doi.org/", "http://doi.org/",
    "https://dx.doi.org/", "http://dx.doi.org/",
    "doi:",
)

# 自由检索式标记:含这些运算符/字段的输入按 freeform 处理(不当作论文标题)。
_FREEFORM_FIELD_OPS = ("author:", "intitle:", "allintitle:", "source:")


def normalize_title(t: str) -> str:
    """标题去噪:去首尾空白、折叠内部连续空白为单空格(保留原词形/大小写)。"""
    return re.sub(r"\s+", " ", (t or "").strip())


def doi_query(doi: str) -> str:
    """DOI 的 Scholar 检索式:剥常见前缀与收尾标点,直接返回裸 DOI(大小写保留)。"""
    s = (doi or "").strip()
    low = s.lower()
    for p in _DOI_PREFIXES:
        if low.startswith(p):
            s = s[len(p):]
            break
    return s.strip().rstrip(".,);")


def _looks_freeform(raw: str) -> bool:
    """判断非标识符输入是否为自由检索式(含引号 / 布尔 / 字段运算符)。"""
    s = (raw or "").strip()
    if not s:
        return False
    if '"' in s or "|" in s:
        return True
    if " OR " in s or " AND " in s:          # Scholar 布尔运算符(大写)
        return True
    low = s.lower()
    return any(op in low for op in _FREEFORM_FIELD_OPS)


def build_query(raw: str, cfg: ScholarConfig, page: int = 0) -> ScholarQuery:
    """由原始输入构造 ScholarQuery。

    - doi   → q=裸 DOI(doi_query),kind='doi'
    - arxiv → q=arXiv id(精确),kind='freeform',extra={'arxiv_id': id}
    - 其余  → 含运算符则 kind='freeform'(q 保留运算符);否则 kind='title'(q=normalize_title)
    分页:start = max(0, page) * cfg.num;年份/条数取自 cfg;lang 缺省 'en'。
    raw 为空(无可用 q)时抛 ValueError。
    """
    wi = classify_input(raw)
    extra = {}
    if wi.kind == "doi":
        kind, q = "doi", doi_query(wi.value)
    elif wi.kind == "arxiv":
        kind, q = "freeform", (wi.value or "").strip()
        if q:
            extra["arxiv_id"] = q
    elif _looks_freeform(raw):
        kind, q = "freeform", normalize_title(raw)
    else:
        kind, q = "title", normalize_title(wi.value)

    if not q:
        raise ValueError("build_query 需要非空输入以构造 q")

    num = cfg.num
    start = max(0, page) * num
    lang = getattr(cfg, "lang", None) or "en"
    return ScholarQuery(
        raw=raw, kind=kind, q=q, num=num, start=start,
        year_low=cfg.year_low, year_high=cfg.year_high, lang=lang, extra=extra,
    )


def title_match_score(a: str, b: str) -> float:
    """标题相似度:归一(小写 + 非词字符折叠)后词集合 Jaccard,取值 [0.0, 1.0]。

    词序无关、对称、空串保护。供下游从 Scholar SERP 候选里挑与查询标题最匹配的一条。
    """
    na = re.sub(r"\W+", " ", (a or "").lower()).strip()
    nb = re.sub(r"\W+", " ", (b or "").lower()).strip()
    if not na or not nb:
        return 0.0
    sa, sb = set(na.split()), set(nb.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


if __name__ == "__main__":  # 纯函数 selftest(不联网): python -m fulltext_fetcher.scholar.query
    cfg = ScholarConfig()  # num=10, year_low/high=None

    # —— DOI:裸 DOI / doi: 前缀 / doi.org URL / 收尾标点,kind='doi',q 为裸 DOI ——
    q1 = build_query("10.1038/nature12373", cfg)
    assert isinstance(q1, ScholarQuery) and q1.kind == "doi", q1
    assert q1.q == "10.1038/nature12373", q1
    assert build_query("doi:10.1234/abcd", cfg).q == "10.1234/abcd"
    assert build_query("https://doi.org/10.1000/AbC", cfg).q == "10.1000/AbC"  # 大小写保留
    assert build_query("10.1038/nature12373.", cfg).q == "10.1038/nature12373"  # 收尾标点剥离

    # —— arXiv:精确 id,kind='freeform',extra 记 arxiv_id ——
    qa = build_query("arXiv:2101.00001", cfg)
    assert qa.kind == "freeform" and qa.q == "2101.00001", qa
    assert qa.extra.get("arxiv_id") == "2101.00001", qa
    assert build_query("hep-th/9901001", cfg).extra.get("arxiv_id") == "hep-th/9901001"

    # —— 标题:normalize_title 折叠空白,kind='title' ——
    qt = build_query("  Deep   Residual\tLearning  ", cfg)
    assert qt.kind == "title" and qt.q == "Deep Residual Learning", qt

    # —— freeform:含引号 / 布尔 / 字段运算符 ——
    for ff in ('machine learning OR deep learning', '"exact phrase here"',
               'author:einstein relativity'):
        assert build_query(ff, cfg).kind == "freeform", ff

    # —— 年份/条数/语言:取自 cfg,lang 缺省 en ——
    cfg2 = ScholarConfig(year_low=2010, year_high=2020, num=20)
    q2 = build_query("Attention Is All You Need", cfg2)
    assert (q2.year_low, q2.year_high, q2.num, q2.lang) == (2010, 2020, 20, "en"), q2

    # —— 分页 start = max(0,page) * num ——
    assert build_query("some plain title words", cfg).start == 0
    assert build_query("some plain title words", cfg, page=1).start == 10   # num=10
    assert build_query("some plain title words", cfg, page=3).start == 30
    assert build_query("some plain title words", cfg2, page=2).start == 40  # num=20
    assert build_query("some plain title words", cfg, page=-1).start == 0   # 负页保护

    # —— 空输入 → ValueError ——
    for _bad in ("", "   "):
        try:
            build_query(_bad, cfg)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {_bad!r}")

    # —— normalize_title / doi_query 直测 ——
    assert normalize_title("  A\tB   C ") == "A B C"
    assert normalize_title("") == ""
    assert doi_query("https://doi.org/10.9999/Q") == "10.9999/Q"
    assert doi_query("doi:10.8888/w);") == "10.8888/w"

    # —— title_match_score:归一 + Jaccard,词序无关 / 对称 / 空串保护 ——
    tms = title_match_score
    assert tms("Deep Residual Learning", "deep, residual! learning") == 1.0
    assert tms("a b c d", "a b") == 0.5
    assert tms("x y", "p q") == 0.0
    assert tms("", "anything") == 0.0
    assert tms("a b c", "c b a") == 1.0
    assert tms("a b c", "b c d") == tms("b c d", "a b c")

    print("QUERY_OK")
