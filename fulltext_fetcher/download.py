"""下载与 PDF 校验:解决"落地页冒充 PDF"与"落盘损坏/截断 PDF"两大最常见坑。

校验链:HTTP 200 → Content-Type 不是 html → 内容前若干字节含 %PDF 魔数 → 大小达标
→ 未被明显截断(尾部含 %%EOF)。
全部通过才落盘,否则判失败并记录原因(供 attempts.jsonl 调试)。
"""
from __future__ import annotations

import os
import re
from typing import Any, Optional, Tuple
from urllib.parse import quote

from .landing import extract_pdf_links
from .models import PdfCandidate
from .publisher_adapter import by_doi_prefix, pdf_links_from_crossref

_PDF_MAGIC = b"%PDF"
_PDF_EOF = b"%%EOF"
# %%EOF 应在文件末尾;允许其后有少量填充/空白/换行,只在尾窗内查找(下载被截断即会丢失)。
_PDF_TAIL_WINDOW = 2048


def looks_like_pdf(head: bytes) -> bool:
    if not head:
        return False
    return _PDF_MAGIC in head[:1024]


def pdf_defect(data: bytes) -> Optional[str]:
    """轻量(纯标准库、零依赖)PDF 体检:结构可用返回 None,否则返回缺陷原因串。

    只为拦截"明显截断/损坏"(下载被腰斩、半截落地页冒充等),阈值刻意从宽——
    宁可放过存疑文件,也绝不误杀合法而多样的 PDF。只保留最可靠的两条硬指标:
      1) 头部含 %PDF 魔数(与 looks_like_pdf 一致);
      2) 尾窗内含 %%EOF —— 下载被截断最可靠的信号(允许尾部少量填充/空白)。

    刻意【不】把 startxref 或字面 "/Type /Page" 设为否决项:PDF 1.5+ 用对象流
    (ObjStm)/交叉引用流时,页对象常被压缩、明文里根本不出现 "/Type /Page",
    硬性要求会误杀大量真实 PDF。故仅"明显截断(无 %%EOF)"才判 corrupt。
    """
    if not data:
        return "empty"
    if _PDF_MAGIC not in data[:1024]:
        return "no-%PDF-magic"
    if _PDF_EOF not in data[-_PDF_TAIL_WINDOW:]:
        return "no-%%EOF(truncated?)"
    return None


def sanitize_filename(name: str) -> str:
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)
    return name.strip("_.")[:140] or "paper"


def target_name(paper: Any, fallback: str) -> str:
    base = None
    if getattr(paper, "doi", None):
        base = paper.doi.replace("/", "_")
    elif getattr(paper, "arxiv_id", None):
        base = "arxiv_" + paper.arxiv_id
    elif getattr(paper, "title", None):
        base = paper.title[:80]
    else:
        base = fallback
    return sanitize_filename(base) + ".pdf"


def _save(data: bytes, paper: Any, pdf_dir: str, fallback_name: str) -> str:
    os.makedirs(pdf_dir, exist_ok=True)
    path = os.path.join(pdf_dir, target_name(paper, fallback_name))
    with open(path, "wb") as f:
        f.write(data)
    return path


def _looks_html(ct: str, data: bytes) -> bool:
    if "html" in ct:
        return True
    head = data[:1024].lower()
    return b"<html" in head or b"<!doctype html" in head


def _client_get(client: Any, url: str, headers: Optional[dict] = None):
    """统一发起 GET;仅在给了 headers 时才带上(兼容不接受 headers 关键字的精简/假客户端)。"""
    if headers:
        try:
            return client.get(url, headers=headers, stream=True)
        except TypeError:                       # 老/假 client 不接受 headers 关键字
            return client.get(url, stream=True)
    return client.get(url, stream=True)


def _download_pdf_core(
    candidate: Any,
    paper: Any,
    pdf_dir: str,
    client: Any,
    cfg: Any,
    log: Any,
    fallback_name: str,
    allow_landing: bool = True,
    headers: Optional[dict] = None,
) -> Tuple[Optional[str], int, Optional[str]]:
    """核心下载+校验(既有逻辑不变)。headers 可选透传给 client.get 用于内容协商。

    若拿到的是 HTML 落地页(而非 PDF),用 landing.extract_pdf_links 抠出内嵌 PDF 直链
    再下一层(allow_landing=False 防递归),专治"定位到却返回 HTML"的一大批失败。
    """
    try:
        r = _client_get(client, candidate.url, headers)
    except Exception as e:  # noqa: BLE001
        return None, 0, f"exception:{e}"
    if r is None:
        return None, 0, "no-response(retries-exhausted)"
    try:
        if r.status_code != 200:
            return None, 0, f"http-{r.status_code}"
        ct = (r.headers.get("Content-Type") or "").lower()
        chunks = bytearray()
        too_big = False
        for chunk in r.iter_content(64 * 1024):
            if not chunk:
                continue
            chunks.extend(chunk)
            if len(chunks) > cfg.max_pdf_bytes:
                too_big = True
                break
        if too_big:
            return None, len(chunks), "too-large"
        data = bytes(chunks)
    finally:
        r.close()

    if looks_like_pdf(data):
        if len(data) < cfg.min_pdf_bytes:
            return None, len(data), "too-small"
        defect = pdf_defect(data)
        if defect:
            # 结构不可解析(多为下载被截断/损坏)→ 判失败、不落盘,原因入 attempts。
            return None, len(data), f"corrupt-pdf({defect})"
        return _save(data, paper, pdf_dir, fallback_name), len(data), None

    # 非 PDF:若像 HTML 落地页,解析内嵌 PDF 链接再走一层
    if allow_landing and _looks_html(ct, data):
        html = data.decode("utf-8", "replace")
        for purl in extract_pdf_links(html, candidate.url)[:4]:
            if purl == candidate.url:
                continue
            sub = PdfCandidate(purl, candidate.source + "+landing", "pdf",
                               candidate.version, candidate.license, candidate.confidence)
            p, b, _ = _download_pdf_core(sub, paper, pdf_dir, client, cfg, log,
                                         fallback_name, allow_landing=False, headers=headers)
            if p:
                log.info("落地页解析命中内嵌 PDF: %s", purl)
                return p, b, None
        return None, len(data), f"landing-no-embedded-pdf(ct={ct[:20]})"

    sniff = data[:16].decode("latin-1", "replace")
    return None, len(data), f"not-pdf(head={sniff!r})"


def _crossref_pdf_urls(client: Any, doi: str) -> list:
    """(可选)取 Crossref works.link[] 里的 PDF 链;TDM 链降权靠后。失败一律静默返回 []。

    对齐经验 A.9:Crossref link[] 候选率最高却几乎下不动(多为出版商 TDM 链),故仅作
    最后一档兜底、且 TDM 链排在最后。client 无 get_json / 无网 / 畸形响应都安全降级。
    """
    getter = getattr(client, "get_json", None)
    if not callable(getter):
        return []
    try:
        data = getter("https://api.crossref.org/works/" + quote(doi, safe=""))
    except Exception:  # noqa: BLE001 - 增强路径绝不影响主流程
        return []
    if not data:
        return []
    try:
        return pdf_links_from_crossref(data)
    except Exception:  # noqa: BLE001
        return []


def _publisher_fallback(
    candidate: Any, paper: Any, pdf_dir: str, client: Any, cfg: Any, log: Any,
    fallback_name: str,
) -> Optional[Tuple[Optional[str], int, Optional[str]]]:
    """既有下载失败后,按 DOI 前缀路由到出版商适配器多试一次(可选增强)。

    仅当 paper 有 DOI 且命中已知出版商时启用:依次尝试 (1)已知 PDF 路径模板、
    (2)带正确 Accept 头重试原候选(内容协商)、(3)Crossref link(TDM 降权)。任一命中
    即返回三元组;全不中返回 None(调用方回退到原始失败结果)。绝不抛出、绝不改主流程契约。
    """
    doi = getattr(paper, "doi", None)
    if not doi:
        return None
    adapter = by_doi_prefix(doi)
    if adapter is None:
        return None
    headers = adapter.headers()
    urls: list = list(adapter.pdf_candidates())
    orig = getattr(candidate, "url", None)
    if orig:
        urls.append(orig)                       # 原候选带 Accept: application/pdf 再试(内容协商)
    urls.extend(_crossref_pdf_urls(client, adapter.doi))

    tried: set = set()
    for u in urls:
        if not u or u in tried:
            continue
        tried.add(u)
        sub = PdfCandidate(u, f"{getattr(candidate, 'source', 'src')}+publisher:{adapter.name}",
                           "pdf", getattr(candidate, "version", None),
                           getattr(candidate, "license", None),
                           getattr(candidate, "confidence", 50))
        try:
            p, b, _ = _download_pdf_core(sub, paper, pdf_dir, client, cfg, log,
                                         fallback_name, allow_landing=True, headers=headers)
        except Exception as e:  # noqa: BLE001 - 单个候选异常不影响其它尝试
            log.info("publisher[%s] 尝试异常(忽略) %s: %s", adapter.name, u, e)
            continue
        if p:
            log.info("出版商适配器[%s]命中: %s", adapter.name, u)
            return p, b, None
    return None


def download_pdf(
    candidate: Any,
    paper: Any,
    pdf_dir: str,
    client: Any,
    cfg: Any,
    log: Any,
    fallback_name: str,
    allow_landing: bool = True,
) -> Tuple[Optional[str], int, Optional[str]]:
    """返回 (落盘路径 | None, 字节数, 错误原因 | None)。

    先走既有下载/落地页解析(``_download_pdf_core``);顶层若仍失败,再按 DOI 前缀路由到
    出版商适配器做**一层可选增强**(``publisher_adapter``),回收一部分"定位到却下不动"。
    契约与既有行为完全一致:无 DOI / 未知出版商 / 增强未命中时,原样返回核心结果。
    """
    result = _download_pdf_core(candidate, paper, pdf_dir, client, cfg, log,
                                fallback_name, allow_landing=allow_landing)
    if result[0] is not None or not allow_landing:
        return result
    try:
        enhanced = _publisher_fallback(candidate, paper, pdf_dir, client, cfg, log, fallback_name)
    except Exception as e:  # noqa: BLE001 - 增强绝不能让主流程崩
        log.info("publisher-adapter 增强异常(忽略): %s", e)
        enhanced = None
    if enhanced and enhanced[0]:
        return enhanced
    return result


# ────────────────────────── 内置 selftest(零依赖) ──────────────────────────
def _minimal_pdf() -> bytes:
    """构造一份结构合法的最小 PDF(含 %PDF / 页对象 / startxref / %%EOF)。"""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF\n"
    )


class _SelfResp:
    def __init__(self, data: bytes, ct: str = "application/pdf", status: int = 200):
        self._data, self.status_code, self.headers = data, status, {"Content-Type": ct}

    def iter_content(self, n):
        for i in range(0, len(self._data), n):
            yield self._data[i:i + n]

    def close(self):
        pass


class _SelfClient:
    def __init__(self, data: bytes):
        self._data = data

    def get(self, url, stream=True):  # noqa: ARG002 - 契约签名
        return _SelfResp(self._data)


class _SelfCfg:
    min_pdf_bytes = 8
    max_pdf_bytes = 80 * 1024 * 1024


class _SelfPaper:
    doi = arxiv_id = None
    title = "selftest"


class _SelfCand:
    def __init__(self, url: str):
        self.url, self.source, self.kind = url, "selftest", "pdf"
        self.version = self.license = None
        self.confidence = 1.0


class _SelfLog:
    def info(self, *a, **k):
        pass


def _selftest() -> None:
    # ── ① pdf_defect 纯函数:仅"明显截断(无 %%EOF)"判损坏,其余一律从宽不误杀 ──
    good = _minimal_pdf()
    assert pdf_defect(good) is None, pdf_defect(good)

    truncated = good[:good.rindex(_PDF_EOF)]                 # 掐掉 %%EOF:模拟下载被腰斩
    assert pdf_defect(truncated) == "no-%%EOF(truncated?)", pdf_defect(truncated)

    assert pdf_defect(b"") == "empty"
    assert pdf_defect(b"<html>not a pdf</html>") == "no-%PDF-magic"

    # 防误杀①:缺 startxref 但有 %PDF+%%EOF → 通过(startxref 不作否决)
    no_sx = good.replace(b"startxref\n190\n", b"")
    assert pdf_defect(no_sx) is None, pdf_defect(no_sx)

    # 防误杀②:PDF 1.5+ 对象流/交叉引用流,明文无 "/Type /Page" → 通过(页对象不作否决)
    objstm = (b"%PDF-1.5\n2 0 obj\n<< /Type /ObjStm /N 3 >>\nstream\n..\nendstream\n"
              b"endobj\nstartxref\n123\n%%EOF\n")
    assert pdf_defect(objstm) is None, pdf_defect(objstm)

    # 防误杀③:极简但含 %PDF+%%EOF(无页对象、无 startxref)→ 通过
    assert pdf_defect(b"%PDF-1.7\n(body)\n%%EOF\n") is None

    # 尾部少量填充/空白后仍能识别 %%EOF → 通过
    assert pdf_defect(good + b"\n   \n") is None, pdf_defect(good + b"\n   \n")

    # ── ② download_pdf 端到端契约(fake client):合法落盘,截断不落盘 ──
    import tempfile

    cfg, paper, log = _SelfCfg(), _SelfPaper(), _SelfLog()
    with tempfile.TemporaryDirectory() as d:
        p, n, err = download_pdf(_SelfCand("http://x/ok.pdf"), paper, d,
                                 _SelfClient(good), cfg, log, "1")
        assert p and err is None and n == len(good), (p, n, err)
        assert os.path.exists(p), p

        before = set(os.listdir(d))
        p2, n2, err2 = download_pdf(_SelfCand("http://x/bad.pdf"), paper, d,
                                    _SelfClient(truncated), cfg, log, "2")
        assert p2 is None and err2 and err2.startswith("corrupt-pdf("), (p2, n2, err2)
        assert n2 == len(truncated), (n2, len(truncated))
        assert set(os.listdir(d)) == before, "损坏 PDF 不应落盘"

    # ── ③ 出版商适配器增强:原候选下不动 → 按 DOI 前缀模板回收(不改主契约) ──
    class _MapClient:
        """按 URL 返回不同响应的假 client(接受 headers 关键字);无 get_json → 跳过 Crossref。"""

        def __init__(self, mapping, default):
            self._m, self._d = mapping, default

        def get(self, url, stream=True, headers=None):  # noqa: ARG002 - 契约签名
            data, ct = self._m.get(url, self._d)
            return _SelfResp(data, ct=ct)

    class _DoiPaper:
        doi = "10.1007/s00542-020-04771-3"          # Springer 前缀 → 有 content/pdf 模板
        arxiv_id = None
        title = "springer selftest"

    orig_url = "https://link.springer.com/article/10.1007/s00542-020-04771-3"
    tmpl = "https://link.springer.com/content/pdf/10.1007/s00542-020-04771-3.pdf"
    with tempfile.TemporaryDirectory() as d:
        client = _MapClient(
            {orig_url: (b"<html><body>landing, no embedded pdf</body></html>", "text/html"),
             tmpl: (good, "application/pdf")},
            default=(b"<html>404</html>", "text/html"),
        )
        p3, n3, err3 = download_pdf(_SelfCand(orig_url), _DoiPaper(), d, client, cfg, log, "sp")
        assert p3 and err3 is None and n3 == len(good), (p3, n3, err3)   # 经适配器模板回收
        assert os.path.exists(p3), p3

    # ── ③b 无 DOI / 未知出版商 → 增强不介入,原样返回既有失败(契约不回归) ──
    with tempfile.TemporaryDirectory() as d:
        client = _MapClient({}, default=(b"<html>nope, not a pdf</html>", "text/html"))
        p4, n4, err4 = download_pdf(_SelfCand("http://x/none"), _SelfPaper(), d, client, cfg, log, "n")
        assert p4 is None and err4, (p4, n4, err4)   # 无 DOI → 不触发适配器

    print("DOWNLOAD_OK")


if __name__ == "__main__":
    _selftest()
