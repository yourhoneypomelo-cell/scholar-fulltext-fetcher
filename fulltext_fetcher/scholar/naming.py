"""文献元数据 → 标准化、安全、唯一的 PDF 文件名（对齐《谷歌学术爬虫-架构与选型.md》§3.9）。

北极星目标「输出文件名标准化的系列文献原文」的落地件。核心契约（§3.9）：

- ``build_filename(result, paper, cfg, *, index=None, taken=None) -> str``
    按 ``cfg.naming_template``（默认 ``{year}_{author}_{title}``）取 年 / 首作者姓 / 标题，
    逐字段 ``slugify`` 后套模板 → **复用父包 ``fulltext_fetcher.download.sanitize_filename``**
    去非法字符/限长 → 加 ``.pdf``。字段缺失优雅降级（折叠空占位产生的分隔符）；年/作者/标题
    全缺时用 DOI 兜底，再不行用 ``paper``（给了 ``index`` 则 ``paper_{index}``）。传入 ``taken``
    集合则同名自动加 ``_2/_3…`` 去重并回填集合。
- ``slugify(text, maxlen=80) -> str``
    任意文本 → 文件名安全片段：空白折叠、去路径分隔符、非 ``[\\w.-]`` 转 ``_``、
    杜绝 ``..`` 穿越、折叠连续 ``_``、限长、Unicode 字母安全。

设计约束（承袭父包/子包风格）：``from __future__ import annotations``；中文 docstring；
**只读复用**父 ``download.sanitize_filename``（不改 download.py）；仅标准库 + 父基元；
模块自带离线 selftest 打印 ``NAMING_OK``。运行：``python -m fulltext_fetcher.scholar.naming``。

文件边界：本次仅改 ``fulltext_fetcher/scholar/naming.py``。
"""
from __future__ import annotations

import os
import re
from typing import Any, Optional

from ..download import sanitize_filename          # 复用父包基元（只读，不改 download.py）
from .models import ScholarResult

DEFAULT_TEMPLATE = "{year}_{author}_{title}"

_TITLE_SLUG_MAX = 80    # 标题 slug 上限（slugify 默认）
_AUTHOR_SLUG_MAX = 40
_YEAR_RE = re.compile(r"(1[6-9]\d\d|20\d\d|21\d\d)")   # 合理年份 1600–2199


class _Blank(dict):
    """format_map 用：模板引用了未知占位符时返回空串，避免 KeyError。"""

    def __missing__(self, key: str) -> str:  # noqa: D401
        return ""


def slugify(text: str, maxlen: int = 80) -> str:
    """任意文本 → 文件名安全 slug 片段。

    规则与父 ``download.sanitize_filename`` 同源（``[\\w.-]`` + ``re.UNICODE``），另加硬化：
    显式去 ``/`` ``\\`` 分隔符、把连续点折叠为 ``_``（杜绝 ``..`` 穿越）、折叠连续 ``_``、限长。
    保留单个点，便于 DOI（如 ``10.1038``）等自然含点的标识可读。
    """
    if text is None:
        return ""
    s = re.sub(r"\s+", " ", str(text)).strip()
    if not s:
        return ""
    s = s.replace("/", "_").replace("\\", "_")
    s = re.sub(r"[^\w.\-]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"\.{2,}", "_", s)       # 杜绝 '..'
    s = re.sub(r"_{2,}", "_", s)        # 折叠连续下划线
    s = s.strip("_.")
    if len(s) > maxlen:
        s = s[:maxlen].strip("_.")
    return s


def _surname(name: Any) -> str:
    """从单个作者全名取姓氏：'Last, First' 取逗号前；'First … Last' 取末词。"""
    name = str(name).strip()
    if not name:
        return ""
    if "," in name:
        return name.split(",", 1)[0].strip()
    toks = name.split()
    return toks[-1] if toks else name


def _first_author_surname(result: Optional[ScholarResult], paper: Any) -> str:
    """首作者姓氏：优先 result.authors，回退 paper.authors；兼容 str / dict(family/last/…) 元素。"""
    authors = None
    if result is not None and getattr(result, "authors", None):
        authors = result.authors
    elif paper is not None and getattr(paper, "authors", None):
        authors = paper.authors
    if not authors:
        return ""
    first = authors[0] if isinstance(authors, (list, tuple)) else authors
    if isinstance(first, dict):
        for k in ("family", "last", "last_name", "surname"):
            if first.get(k):
                return str(first[k]).strip()
        return _surname(first.get("name") or first.get("full") or "")
    return _surname(first)


def _year(result: Optional[ScholarResult], paper: Any) -> str:
    """4 位年份：优先 result/paper.year，回退 result.publication_info 里的年份串。"""
    for src in (result, paper):
        if src is None:
            continue
        y = getattr(src, "year", None)
        if y:
            m = _YEAR_RE.search(str(y))
            if m:
                return m.group(1)
    if result is not None:
        pi = getattr(result, "publication_info", None)
        if pi:
            m = _YEAR_RE.search(str(pi))
            if m:
                return m.group(1)
    return ""


def _title(result: Optional[ScholarResult], paper: Any) -> str:
    if result is not None and getattr(result, "title", None):
        return str(result.title)
    if paper is not None and getattr(paper, "title", None):
        return str(paper.title)
    return ""


def _doi(result: Optional[ScholarResult], paper: Any) -> str:
    for src in (result, paper):
        if src is not None and getattr(src, "doi", None):
            return str(src.doi)
    return ""


def build_filename(result: Optional[ScholarResult], paper: Any, cfg: Any,
                   *, index: Optional[int] = None,
                   taken: Optional[set] = None) -> str:
    """把一条结果/论文元数据渲染为标准化、安全、（可）唯一的 PDF 文件名。见模块 docstring。"""
    template = getattr(cfg, "naming_template", None) or DEFAULT_TEMPLATE

    fields = {
        "year": slugify(_year(result, paper), maxlen=8),
        "author": slugify(_first_author_surname(result, paper), maxlen=_AUTHOR_SLUG_MAX),
        "title": slugify(_title(result, paper), maxlen=_TITLE_SLUG_MAX),
    }
    # 额外占位符（自定义模板可用；缺失即空，不会 KeyError）
    fields["doi"] = slugify(_doi(result, paper), maxlen=60)
    venue = getattr(result, "venue", None) if result is not None else None
    if not venue and paper is not None:
        venue = getattr(paper, "journal", None)
    fields["venue"] = slugify(venue, maxlen=_AUTHOR_SLUG_MAX)
    fields["index"] = "" if index is None else str(index)

    try:
        stem = template.format_map(_Blank(fields))
    except Exception:  # noqa: BLE001 - 畸形模板不致命：回退默认三段拼接
        stem = "_".join(p for p in (fields["year"], fields["author"], fields["title"]) if p)

    # 折叠空字段留下的分隔符残留 + 再次杜绝 '..'（即便来自自定义模板）
    stem = re.sub(r"\.{2,}", "_", stem)
    stem = re.sub(r"_{2,}", "_", stem).strip("_. ")

    if not stem:                                   # 年/作者/标题全缺 → DOI 兜底
        stem = fields["doi"]
    if not stem and index is not None:             # 再兜底：带序号的 paper
        stem = f"paper_{index}"

    stem = sanitize_filename(stem)                 # 复用父包：去非法 + strip + [:140] + or 'paper'

    if taken is None:
        return f"{stem}.pdf"

    name = f"{stem}.pdf"
    n = 2
    while name in taken:                           # 同名去重：_2/_3…
        name = f"{stem}_{n}.pdf"
        n += 1
    taken.add(name)
    return name


def dedupe_path(dir_path: str, filename: str) -> str:
    """（便利函数）返回 dir_path 下不与既有文件冲突的完整路径；重名加 _2/_3…。

    对 filename 取 basename 防目录穿越；仅按磁盘现存文件判重（不保证并发原子性）。
    ``build_filename`` 的内存 ``taken`` 去重是主路径；本函数供落盘阶段按实际磁盘二次兜底。
    """
    filename = os.path.basename(str(filename))
    if not filename or filename in (".", ".."):
        filename = "paper.pdf"
    root, ext = os.path.splitext(filename)
    if not root:                                   # 形如 '.pdf' 的退化输入
        root, ext = filename, ""
    candidate = os.path.join(dir_path, filename)
    i = 2
    while os.path.exists(candidate):
        candidate = os.path.join(dir_path, f"{root}_{i}{ext}")
        i += 1
    return candidate


if __name__ == "__main__":  # 离线 selftest: python -m fulltext_fetcher.scholar.naming
    import tempfile

    from .config import ScholarConfig
    from ..models import Paper

    cfg = ScholarConfig()                          # naming_template = "{year}_{author}_{title}"
    assert cfg.naming_template == DEFAULT_TEMPLATE, cfg.naming_template

    # ① 字段齐全：年_首作者姓_标题
    r1 = ScholarResult(title="Attention Is All You Need",
                       authors=["Ashish Vaswani", "Noam Shazeer"], year=2017)
    assert build_filename(r1, None, cfg) == "2017_Vaswani_Attention_Is_All_You_Need.pdf", \
        build_filename(r1, None, cfg)

    # ② 缺作者 → 年_标题（空占位折叠，不留 '__'/前后 '_'）
    r2 = ScholarResult(title="No Author", year=2020, authors=[])
    assert build_filename(r2, None, cfg) == "2020_No_Author.pdf", build_filename(r2, None, cfg)

    # ③ 缺年 → 姓_标题；年从 publication_info 兜底
    r3 = ScholarResult(title="No Year", authors=["Ada Lovelace"])
    assert build_filename(r3, None, cfg) == "Lovelace_No_Year.pdf", build_filename(r3, None, cfg)
    r3b = ScholarResult(title="From PubInfo", authors=["Ada Lovelace"],
                        publication_info="A Lovelace - Some Journal, 1998 - site.org")
    assert build_filename(r3b, None, cfg) == "1998_Lovelace_From_PubInfo.pdf", \
        build_filename(r3b, None, cfg)

    # ④ 超长标题 → sanitize 限长；整名 <=144 且正常收尾
    r4 = ScholarResult(title="word " * 100, authors=["Zed"], year=2022)
    lt = build_filename(r4, None, cfg)
    assert len(lt) <= 144 and lt.startswith("2022_Zed_") and lt.endswith(".pdf"), (len(lt), lt)

    # ⑤ 非法字符 + 路径穿越中和（无 '/'、'\\'、'..'，仍以 .pdf 收尾）
    r5 = ScholarResult(title='a/b\\c:*?"<>|../../etc/passwd', authors=["X"], year=2020)
    ic = build_filename(r5, None, cfg)
    assert "/" not in ic and "\\" not in ic and ".." not in ic, ic
    assert ic.startswith("2020_X_") and ic.endswith(".pdf"), ic

    # ⑥ Unicode 作者/标题字母安全保留（dict 作者元素）
    r6 = ScholarResult(title="Café Models", authors=[], year=2021)
    r6.authors = [{"family": "García", "given": "José"}]   # type: ignore[list-item]
    assert build_filename(r6, None, cfg) == "2021_García_Café_Models.pdf", \
        build_filename(r6, None, cfg)

    # ⑦ DOI 回退（年/作者/标题全缺）
    r7 = ScholarResult(doi="10.1038/nature12373")
    assert build_filename(r7, None, cfg) == "10.1038_nature12373.pdf", build_filename(r7, None, cfg)

    # ⑧ result=None → 用父包 Paper 兜底（含 Unicode）
    p8 = Paper(title="From Paper", year=2019, authors=["Kurt Gödel"])
    assert build_filename(None, p8, cfg) == "2019_Gödel_From_Paper.pdf", \
        build_filename(None, p8, cfg)

    # ⑨ 全空 → paper.pdf；给 index → paper_{index}.pdf
    assert build_filename(None, None, cfg) == "paper.pdf"
    assert build_filename(None, None, cfg, index=5) == "paper_5.pdf"

    # ⑩ 重名去重：taken 集合中同名自动加 _2/_3，并回填集合
    taken: set = set()
    n1 = build_filename(r1, None, cfg, taken=taken)
    n2 = build_filename(r1, None, cfg, taken=taken)
    n3 = build_filename(r1, None, cfg, taken=taken)
    assert n1 == "2017_Vaswani_Attention_Is_All_You_Need.pdf", n1
    assert n2 == "2017_Vaswani_Attention_Is_All_You_Need_2.pdf", n2
    assert n3 == "2017_Vaswani_Attention_Is_All_You_Need_3.pdf", n3
    assert {n1, n2, n3} <= taken and len(taken) == 3, taken

    # ⑪ 自定义模板（含额外占位符 {doi}）—— 未知占位符不崩、按模板渲染
    cfg2 = ScholarConfig(naming_template="{author}-{year}")
    assert build_filename(r1, None, cfg2) == "Vaswani-2017.pdf", build_filename(r1, None, cfg2)

    # ⑫ slugify 直测：限长 / 去分隔符 / 折叠
    assert slugify("Hello, World!") == "Hello_World"
    assert slugify("a/b\\c") == "a_b_c"
    assert slugify("x" * 200, maxlen=10) == "x" * 10
    assert slugify("  ..evil../..  ") == "evil"
    assert slugify("") == "" and slugify(None) == ""

    # ⑬ dedupe_path：磁盘重名加 _2/_3，且 basename 防穿越
    with tempfile.TemporaryDirectory() as d:
        fn = "2017_Vaswani.pdf"
        p1 = dedupe_path(d, fn)
        assert p1 == os.path.join(d, fn), p1
        open(p1, "w").close()
        p2 = dedupe_path(d, fn)
        assert p2 == os.path.join(d, "2017_Vaswani_2.pdf"), p2
        pp = dedupe_path(d, "../../evil.pdf")
        assert os.path.dirname(pp) == d and "evil" in os.path.basename(pp), pp

    # ⑭ 特殊字符 DOI(老 Wiley,含 ( ) : < > ;)→ build_filename 合法且可真落盘(不抛 [Errno 22])
    _wiley = "10.1002/1099-0739(200012)14:12<715::AID-RCM4>3.0.CO;2-A"
    _win_illegal = set('<>:"/\\|?*')
    fn14 = build_filename(ScholarResult(doi=_wiley), None, cfg)
    assert not (_win_illegal & set(fn14)), fn14
    assert fn14 == "10.1002_1099-0739_200012_14_12_715_AID-RCM4_3.0.CO_2-A.pdf", fn14
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, fn14), "wb") as _fh:    # Windows 真落盘:非法字符未清则报 [Errno 22]
            _fh.write(b"%PDF-1.4\n%%EOF\n")
    assert slugify('a<b>c:d"e|f*g?h') == "a_b_c_d_e_f_g_h", slugify('a<b>c:d"e|f*g?h')

    print("NAMING_OK")
