"""下载与 PDF 校验:解决"落地页冒充 PDF"与"落盘损坏/截断 PDF"两大最常见坑。

校验链:HTTP 200 → Content-Type 不是 html → 内容前若干字节含 %PDF 魔数 → 大小达标
→ 未被明显截断(尾部含 %%EOF)。全部通过才落盘,否则判失败并记录原因(供 attempts.jsonl 调试)。

可选 D2 深度完整性(cfg.pdf_verify_deep=True 且装有 pypdf 时启用):在上面轻量硬指标
之外再确认"结构可解析且页数>0"。默认关闭、缺库降级,行为与既有逐字节一致。

合规硬守卫:除非显式 cfg.enable_scihub,下载 choke 点(_download_pdf_core / 浏览器路径)一律拒绝
sci-hub / libgen 等影子库域名(记 blocked-shadow-library),即使 websearch/wayback/landing 引出也不跟进
(北极星=公开/免费/OA)。
"""
from __future__ import annotations

import importlib.util
import os
import re
from typing import Any, Optional, Tuple
from urllib.parse import quote, urlsplit

from .landing import extract_pdf_links
from .models import PdfCandidate
from .publisher_adapter import by_doi_prefix, pdf_links_from_crossref

_PDF_MAGIC = b"%PDF"
_PDF_EOF = b"%%EOF"
# %%EOF 应在文件末尾;允许其后有少量填充/空白/换行,只在尾窗内查找(下载被截断即会丢失)。
_PDF_TAIL_WINDOW = 2048

# 真实浏览器 UA:很多 OA 主机(MDPI/金色OA 等)对非浏览器 UA(如 fulltext_fetcher/1.0)直接 403,
# 故所有【PDF 下载 GET】统一带浏览器 UA + 同源 Referer + Accept(仅影响下载,不改 OA API 的礼貌 UA)。
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _referer(url: str) -> Optional[str]:
    """同源 Referer(scheme://host/):部分出版商据此放行 PDF 请求。"""
    try:
        parts = urlsplit(url)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}/"
    except Exception:  # noqa: BLE001
        pass
    return None


def _browser_headers(url: str, extra: Optional[dict] = None) -> dict:
    """构造 PDF 下载用的真实浏览器请求头;调用方给的 extra(如出版商 Accept)优先合并。"""
    h = {
        "User-Agent": _BROWSER_UA,
        "Accept": "application/pdf,application/x-pdf,application/octet-stream,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    ref = _referer(url)
    if ref:
        h["Referer"] = ref
    if extra:
        h.update(extra)
    return h


# Cloudflare "Just a moment..." JS 质询(Managed Challenge / IUAM)特征:此类 403/503 的响应体
# 是需执行 JS 才能通过的质询页,普通 HTTP 客户端与 curl_cffi(TLS 指纹伪装)均【无法】通过——
# 实测 pubs.rsc.org(RSC,连金 OA 文章也一样)对脚本一律回此页,故 154 次直连全 403。据此把它
# 与"普通 403"区分:既给准确失败原因(cloudflare-challenge)、也据以跳过对同一质询的无谓重试、
# 改走 FlareSolverr(JS 求解器)兜底。
_CF_CHALLENGE_MARKERS = (
    b"just a moment", b"challenge-platform", b"__cf_chl", b"_cf_chl_opt",
    b"cf-mitigated", b"enable javascript", b"cf-browser-verification",
)


def _is_cloudflare_challenge(status_code: Any, headers: Any, head: Any) -> bool:
    """响应是否为 Cloudflare JS 质询页(需 JS 执行,HTTP / curl_cffi 都过不了)。

    判据(力求精确、绝不误伤普通 403):状态码 403/503,且(响应头 Server 含 cloudflare 或存在
    cf-mitigated 头),且响应体含质询特征串之一。
    """
    try:
        if int(status_code) not in (403, 503):
            return False
    except (TypeError, ValueError):
        return False
    h = headers or {}
    try:
        keys_lower = {str(k).lower() for k in h.keys()}
    except Exception:  # noqa: BLE001
        keys_lower = set()
    try:
        server = str(h.get("Server") or h.get("server") or "").lower()
    except Exception:  # noqa: BLE001
        server = ""
    if "cloudflare" not in server and "cf-mitigated" not in keys_lower:
        return False
    body = head or b""
    if isinstance(body, str):
        body = body.encode("utf-8", "replace")
    low = body.lower()
    return any(m in low for m in _CF_CHALLENGE_MARKERS)


def _is_cf_reason(reason: Any) -> bool:
    """失败原因串是否为 Cloudflare 质询(供上层决定跳过 curl_cffi / publisher 无谓重试)。"""
    return bool(reason) and "cloudflare-challenge" in str(reason)


# 影子库(越界:非公开/免费/OA)域名标记。北极星=公开/免费/OA;sci-hub / libgen 等影子库属越界,
# 默认一律拒绝下载(除非显式 cfg.enable_scihub),即使 websearch/wayback/landing 引出也不跟进。
_SHADOW_LIBRARY_MARKERS = (
    "sci-hub", "scihub",                       # Sci-Hub 及各 TLD/镜像(.se/.st/.ru/.box/.wf/.ee…)
    "libgen", "library.lol", "libgenesis",     # Library Genesis 系
    "annas-archive", "anna-archive",           # Anna's Archive
    "z-lib.", "z-library", "zlibrary", "1lib.", "b-ok.",  # Z-Library 系
)


def _is_shadow_library(url: Any) -> bool:
    """URL 主机名是否属已知影子库(sci-hub/libgen/Anna's Archive/Z-Library 等)。

    仅按主机名 token 精确匹配,力求不误伤合法 OA/出版商域名(如 sciencedirect 不含任何标记)。
    """
    try:
        host = (urlsplit(str(url)).hostname or "").lower()
    except Exception:  # noqa: BLE001 - 畸形 URL 视作非影子库(交由后续 %PDF 校验兜底)
        return False
    if not host:
        return False
    return any(m in host for m in _SHADOW_LIBRARY_MARKERS)


def _cookies_to_header(cookies: Any) -> str:
    """FlareSolverr 返回的 cookies 列表 → Cookie 请求头串(name=value; …)。"""
    if not isinstance(cookies, (list, tuple)):
        return ""
    parts = []
    for c in cookies:
        if isinstance(c, dict) and c.get("name"):
            parts.append(f"{c.get('name')}={c.get('value', '')}")
    return "; ".join(parts)


def _flaresolverr_enabled(cfg: Any) -> bool:
    """FlareSolverr 兜底是否启用:显式 cfg.use_flaresolverr,或配置了端点(cfg.flaresolverr_url /
    环境变量 FLARESOLVERR_URL)。三者皆无(默认)→ False(零副作用、绝不发多余请求)。"""
    if getattr(cfg, "use_flaresolverr", False):
        return True
    if getattr(cfg, "flaresolverr_url", None):
        return True
    return bool(os.environ.get("FLARESOLVERR_URL"))


def _emit_event(events: Any, event: str, **fields: Any) -> None:
    """结构化事件的可选出口:duck-type EventLog.emit,写入 attempts.jsonl 便于统计。

    events 为 None / 无 emit / emit 抛错时一律静默 no-op —— 默认路径(未传 events,如
    scholar.download / selftest)与 FlareSolverr 未启用时【零副作用、零新增事件】。不硬依赖
    logsetup,故 selftest 可注入假收集器验证。
    """
    if events is None:
        return
    emit = getattr(events, "emit", None)
    if not callable(emit):
        return
    try:
        emit(event, **fields)
    except Exception:  # noqa: BLE001 - 记事件绝不能影响主下载流程
        pass


def looks_like_pdf(head: bytes) -> bool:
    if not head:
        return False
    return _PDF_MAGIC in head[:1024]


def pdf_defect(data: bytes, deep: bool = False) -> Optional[str]:
    """轻量(纯标准库、零依赖)PDF 体检:结构可用返回 None,否则返回缺陷原因串。

    只为拦截"明显截断/损坏"(下载被腰斩、半截落地页冒充等),阈值刻意从宽——
    宁可放过存疑文件,也绝不误杀合法而多样的 PDF。只保留最可靠的两条硬指标:
      1) 头部含 %PDF 魔数(与 looks_like_pdf 一致);
      2) 尾窗内含 %%EOF —— 下载被截断最可靠的信号(允许尾部少量填充/空白)。

    刻意【不】把 startxref 或字面 "/Type /Page" 设为否决项:PDF 1.5+ 用对象流
    (ObjStm)/交叉引用流时,页对象常被压缩、明文里根本不出现 "/Type /Page",
    硬性要求会误杀大量真实 PDF。故仅"明显截断(无 %%EOF)"才判 corrupt。

    ``deep``(D2 深度完整性,可选、默认关):在通过上面两条轻量硬指标后,再用纯 Python
    解析库(pypdf)确认"结构可解析且页数>0"(并强制触发首页惰性解析以暴露损坏)。**仅**在
    显式 deep=True 且环境装有 pypdf 时才生效;**库缺失一律降级为放过(返回 None)**,绝不因缺库
    而误杀。默认 deep=False 时与既有逐字节一致(不改任何现有判定);由调用方按 cfg 开关决定是否启用。
    """
    if not data:
        return "empty"
    if _PDF_MAGIC not in data[:1024]:
        return "no-%PDF-magic"
    if _PDF_EOF not in data[-_PDF_TAIL_WINDOW:]:
        return "no-%%EOF(truncated?)"
    if deep:
        return _pdf_page_defect(data)
    return None


def _pdf_reader():
    """返回纯 Python PDF 读取器类(仅 pypdf);未安装 → None(降级)。

    延迟导入(与 curl_cffi / nodriver 同哲学):pypdf 为可选依赖,不进 requirements。
    刻意【只认 pypdf】、不回退 PyPDF2:PyPDF2 已冻结(3.0.1 与 pypdf 3.1.0 同源同代码),
    回退它零额外鲁棒性、且引入不再维护的旧包(经 D2 库调研佐证)。若日后要"强校验截断/损坏",
    应在 deep 层加 pypdfium2(PDFium 内核、对畸形不宽容、许可证干净),而非 pikepdf
    (QPDF 打开即自动修复 → "能开"≠"未截断"、会漏报截断)。
    """
    try:
        from pypdf import PdfReader
        return PdfReader
    except Exception:  # noqa: BLE001 - 可选依赖缺失/导入异常一律视作不可用
        return None


def _pdf_page_defect(data: bytes) -> Optional[str]:
    """(D2)用 PDF 解析库确认结构可解析且页数>0;无解析库则降级为 None(不误杀)。

    贯彻既有"绝不误杀合法而多样 PDF"的哲学:只有解析库【明确】判定无法解析(抛异常)
    或页数为 0 时才回报缺陷;库缺失 / 任何不确定 → None(放过)。仅在 pdf_defect(deep=True)
    时才被调用,故默认路径零副作用、零额外依赖。
    """
    reader = _pdf_reader()
    if reader is None:                              # 未装解析库 → 优雅降级,交回浅层判定(已通过)
        return None
    import io
    try:
        pages = reader(io.BytesIO(data)).pages
        n = len(pages)
        if n > 0:
            _ = pages[0]                            # 强制触发惰性解析:pypdf 惰性,仅 len 可能漏掉损坏
    except Exception:  # noqa: BLE001 - 解析失败/惰性解析暴露损坏即视为明确损坏(仅 deep 开启时走到这)
        return "deep-unparseable"
    return None if n > 0 else "deep-zero-pages"


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
    """统一发起 PDF 下载 GET:注入真实浏览器 UA/Referer/Accept(过非浏览器 UA 拦截 + 内容协商)。

    调用方给的 headers(如出版商 Accept)优先合并。对不接受 headers 关键字的精简/假客户端
    (selftest 用)优雅降级为不带 headers 的调用,契约不变。
    """
    h = _browser_headers(url, headers)
    try:
        return client.get(url, headers=h, stream=True)
    except TypeError:                           # 老/假 client 不接受 headers 关键字
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
    # 合规硬守卫(所有来源统一 choke 点):影子库默认拒绝,除非显式 cfg.enable_scihub。
    # 覆盖顶层候选 + 落地页/curl_cffi/publisher/render 各层子候选(均经本函数发起下载)。
    if _is_shadow_library(getattr(candidate, "url", "")) and not getattr(cfg, "enable_scihub", False):
        return None, 0, "blocked-shadow-library"
    try:
        r = _client_get(client, candidate.url, headers)
    except Exception as e:  # noqa: BLE001
        return None, 0, f"exception:{e}"
    if r is None:
        return None, 0, "no-response(retries-exhausted)"
    try:
        if r.status_code != 200:
            reason = f"http-{r.status_code}"
            if r.status_code in (403, 503):
                sniff = b""
                try:                                # 读一小段质询体用于判定(随后 finally 关闭连接)
                    sniff = next(r.iter_content(8192), b"") or b""
                except Exception:  # noqa: BLE001 - 读质询体失败不影响主判定
                    sniff = b""
                if _is_cloudflare_challenge(r.status_code, r.headers, sniff):
                    reason = f"cloudflare-challenge(http-{r.status_code})"
            return None, 0, reason
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
        defect = pdf_defect(data, deep=getattr(cfg, "pdf_verify_deep", False))
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
    # 礼貌池:带上 mailto(取自 client.cfg.email)路由到 Crossref polite pool,更稳、更少 429。
    email = getattr(getattr(client, "cfg", None), "email", None)
    params = {"mailto": email} if email else None
    try:
        data = getter("https://api.crossref.org/works/" + quote(doi, safe=""), params=params)
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


def _curl_cffi_available() -> bool:
    try:
        return importlib.util.find_spec("curl_cffi") is not None
    except (ImportError, ValueError):
        return False


class _CurlResp:
    """把 curl_cffi 响应适配成本模块期望的响应对象(status_code/headers/iter_content/close)。"""

    def __init__(self, r: Any):
        self._r = r
        self.status_code = getattr(r, "status_code", None)
        self.headers = getattr(r, "headers", {}) or {}

    def iter_content(self, n: int):
        it = getattr(self._r, "iter_content", None)
        if callable(it):
            try:
                yield from it(n)
                return
            except Exception:  # noqa: BLE001 - 流式失败退回整体 content
                pass
        data = getattr(self._r, "content", b"") or b""
        for i in range(0, len(data), n):
            yield data[i:i + n]

    def close(self):
        try:
            self._r.close()
        except Exception:  # noqa: BLE001
            pass


class _CurlCffiClient:
    """用 curl_cffi(impersonate=chrome)取 PDF 的临时 client 适配器(绕 TLS/UA 指纹拦截)。"""

    def __init__(self, cfg: Any):
        self._cfg = cfg

    def get(self, url, headers=None, stream=True):  # noqa: ARG002 - 对齐 client.get 契约
        from curl_cffi import requests as _creq   # 延迟导入(可选依赖)
        imp = getattr(self._cfg, "impersonate", None) or "chrome"
        timeout = getattr(self._cfg, "timeout", 30.0)
        r = _creq.get(url, impersonate=imp, headers=headers or {}, timeout=timeout,
                      stream=True, allow_redirects=True)
        return _CurlResp(r)

    def get_json(self, url, **kw):               # 兼容 _crossref_pdf_urls 探测(此路径不启用)
        return None


def _curl_cffi_fallback(candidate, paper, pdf_dir, cfg, log, fallback_name, allow_landing):
    """用 curl_cffi impersonate=chrome 重取同一候选(含落地页解析)。缺库/关闭/异常 → None。

    专治 MDPI / 金色 OA 等对普通请求(UA / TLS 指纹)返回 403、但对真浏览器指纹放行的主机。
    """
    if not getattr(cfg, "use_curl_cffi", True) or not _curl_cffi_available():
        return None
    try:
        return _download_pdf_core(candidate, paper, pdf_dir, _CurlCffiClient(cfg), cfg, log,
                                  fallback_name, allow_landing=allow_landing)
    except Exception as e:  # noqa: BLE001 - 兜底绝不能让主流程崩
        log.info("curl_cffi 兜底异常(忽略) %s: %s", getattr(candidate, "url", "?"), e)
        return None


def _render_fallback(candidate, paper, pdf_dir, client, cfg, log, fallback_name):
    """(可选、默认关、仅 OA)顶层仍失败时,用 render_fetch 渲染候选落地页后抽 PDF 再下。

    需 cfg.render_fallback 为真且安装了浏览器引擎(render_fetch 内部合规守卫:绝不渲染 Scholar);
    未开启 / 无引擎 → 优雅 no-op 返回 None。
    """
    if not getattr(cfg, "render_fallback", False):
        return None
    try:
        from .render_fetch import render_get_pdf_url
    except ImportError:
        return None
    try:
        info = render_get_pdf_url(getattr(candidate, "url", ""))
    except Exception:  # noqa: BLE001
        return None
    if not info or not info.get("available"):
        return None
    for purl in (info.get("pdf_links") or []):
        if not purl or purl == getattr(candidate, "url", None):
            continue
        sub = PdfCandidate(purl, f"{getattr(candidate, 'source', 'src')}+render", "pdf",
                           getattr(candidate, "version", None),
                           getattr(candidate, "license", None),
                           getattr(candidate, "confidence", 50))
        try:
            p, b, _ = _download_pdf_core(sub, paper, pdf_dir, client, cfg, log,
                                         fallback_name, allow_landing=False)
        except Exception:  # noqa: BLE001
            continue
        if p:
            log.info("render 兜底命中: %s", purl)
            return p, b, None
    return None


def _flaresolverr_fallback(
    candidate, paper, pdf_dir, cfg, log, fallback_name, allow_landing,
    *, _solve=None, _client=None,
):
    """(可选、默认关)用 FlareSolverr 解 Cloudflare JS 质询,拿 cf_clearance + UA 再带其重下 PDF。

    专治 pubs.rsc.org 等【整站 Cloudflare 质询】(连 OA 文章也拦):HTTP / curl_cffi 都过不了,唯有
    JS 求解器(FlareSolverr 无头浏览器)能过。需 cfg.use_flaresolverr 或配置端点(cfg.flaresolverr_url /
    env FLARESOLVERR_URL);未启用 / 未配置 / 连不上 / 未拿到 cf_clearance → 一律优雅返回 None
    (默认零副作用)。``_solve`` / ``_client`` 供 selftest 注入,生产勿传。
    """
    if not _flaresolverr_enabled(cfg):
        return None
    solve = _solve
    if solve is None:
        try:
            from .flaresolverr import solve as _fs_solve
            solve = _fs_solve
        except ImportError:
            return None
    url = getattr(candidate, "url", "") or ""
    if not url:
        return None
    origin = _referer(url) or url                    # 在站点根求解质询即可拿到域级 cf_clearance
    try:
        sol = solve(origin, cfg)
    except Exception as e:  # noqa: BLE001 - 兜底绝不能让主流程崩
        log.info("flaresolverr 求解异常(忽略) %s: %s", origin, e)
        return None
    if not isinstance(sol, dict):
        return None
    cookie = _cookies_to_header(sol.get("cookies"))
    if not cookie:                                    # 没拿到 cookie(cf_clearance),重下必仍被质询
        return None
    headers = {"Cookie": cookie}
    ua = sol.get("user_agent")
    if ua:                                            # cf_clearance 与求解时的 UA 绑定,必须沿用
        headers["User-Agent"] = ua
    dl_client = _client if _client is not None else _CurlCffiClient(cfg)
    try:
        return _download_pdf_core(candidate, paper, pdf_dir, dl_client, cfg, log,
                                  fallback_name, allow_landing=allow_landing, headers=headers)
    except Exception as e:  # noqa: BLE001
        log.info("flaresolverr 重下异常(忽略) %s: %s", url, e)
        return None


# JS:优先取页面内 PDF 直链(MDPI 的「Download PDF」带 ?version=);否则由当前 URL 拼 /pdf。
_FIND_PDF_JS = (
    "(function(){var a=document.querySelector(\"a[href*='/pdf']\");"
    "if(a&&a.href)return a.href;var u=location.href;"
    "if(u.slice(-1)==='/')u=u.slice(0,-1);return u+'/pdf';})()"
)


def _nodriver_fetch_pdf_bytes(url: str, cfg: Any, log: Any) -> Optional[bytes]:
    """用真实(默认有头)浏览器过 Akamai/JS 软验证,再经 CDP 下载拿到 PDF 字节。

    专治 **MDPI 等 Akamai Bot Manager**(bm-verify / ak_bmsc)站点:requests 一律 403、
    curl_cffi 只拿到验证挑战页(2KB)、headless 浏览器亦被检测——唯有**有头真 Chrome** 通过验证后,
    经 CDP ``Page.setDownloadBehavior`` 触发下载才能取到真正 PDF(已实网核实 MDPI 6.5MB PDF)。

    缺 nodriver / 无显示环境 / 任何异常 → None(优雅降级,绝不抛、绝不影响其它下载层)。
    """
    if not url:
        return None
    try:
        import asyncio
        import glob
        import tempfile
        import time as _time

        import nodriver as nd
        from nodriver import cdp
    except Exception:  # noqa: BLE001 - 缺可选依赖 → 跳过
        return None

    headless = bool(getattr(cfg, "browser_pdf_headless", False))  # Akamai 需有头,默认 False=有头
    wait = float(getattr(cfg, "browser_pdf_wait", 13.0) or 0.0)   # 过 Akamai/渲染等待
    timeout = float(getattr(cfg, "timeout", 30.0) or 30.0)
    dl = tempfile.mkdtemp(prefix="ftf_pdf_")

    async def _go() -> Optional[bytes]:
        browser = await nd.start(headless=headless, browser_args=[
            "--lang=en-US", "--disable-blink-features=AutomationControlled",
            "--window-size=1600,1000", "--no-first-run", "--no-default-browser-check"])
        try:
            tab = await browser.get(url)
            await tab.sleep(max(wait, 0.5))                    # 过 Akamai bm-verify / 渲染
            try:
                pdf_url = await tab.evaluate(_FIND_PDF_JS, return_by_value=True)
            except Exception:  # noqa: BLE001
                pdf_url = None
            if not pdf_url or not str(pdf_url).startswith("http"):
                return None
            try:                                               # 允许当前上下文下载到临时目录
                await tab.send(cdp.page.set_download_behavior(behavior="allow", download_path=dl))
            except Exception:  # noqa: BLE001
                try:
                    await tab.send(cdp.browser.set_download_behavior(behavior="allow", download_path=dl))
                except Exception:  # noqa: BLE001
                    return None
            try:
                await tab.get(str(pdf_url))                     # 触发下载(下载会打断导航,忽略异常)
            except Exception:  # noqa: BLE001
                pass
            deadline = _time.time() + max(timeout, 20.0)
            while _time.time() < deadline:
                await tab.sleep(1)
                files = [f for f in glob.glob(os.path.join(dl, "*"))
                         if not f.endswith(".crdownload")]
                if files and os.path.getsize(files[0]) >= 1024:
                    with open(files[0], "rb") as fh:
                        return fh.read()
            return None
        finally:
            try:
                browser.stop()
            except Exception:  # noqa: BLE001
                pass

    try:
        return asyncio.run(_go())
    except Exception as e:  # noqa: BLE001
        if log is not None:
            try:
                log.info("browser-pdf 取字节异常(忽略) %s: %s", url, e)
            except Exception:  # noqa: BLE001
                pass
        return None
    finally:
        try:
            import shutil
            shutil.rmtree(dl, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass


def _browser_pdf_download(candidate, paper, pdf_dir, cfg, log, fallback_name):
    """(可选、默认关)有头真浏览器过 Akamai/JS 软验证并【经浏览器下载】PDF —— 专治 MDPI/金色 OA。

    需 ``cfg.browser_pdf_download=True`` 且有真实显示环境;缺 nodriver / 无显示 / 校验不过 → None。
    默认关:有头浏览器重(~15–25s/篇)、需显示,不进默认/CI 路径(与 render_fallback 同哲学)。
    """
    if not getattr(cfg, "browser_pdf_download", False):
        return None
    if _is_shadow_library(getattr(candidate, "url", "")) and not getattr(cfg, "enable_scihub", False):
        return None                               # 合规硬守卫:影子库默认拒绝(浏览器路径亦覆盖)
    data = _nodriver_fetch_pdf_bytes(getattr(candidate, "url", ""), cfg, log)
    if not data or not looks_like_pdf(data):
        return None
    if len(data) < cfg.min_pdf_bytes:
        return None
    if pdf_defect(data, deep=getattr(cfg, "pdf_verify_deep", False)):
        return None
    return _save(data, paper, pdf_dir, fallback_name), len(data), None


def download_pdf(
    candidate: Any,
    paper: Any,
    pdf_dir: str,
    client: Any,
    cfg: Any,
    log: Any,
    fallback_name: str,
    allow_landing: bool = True,
    events: Any = None,
) -> Tuple[Optional[str], int, Optional[str]]:
    """返回 (落盘路径 | None, 字节数, 错误原因 | None)。

    分层兜底(逐层仅在上一层失败时才试,契约与既有行为一致):
      ① 既有下载 + 落地页解析(``_download_pdf_core``,现已带真实浏览器 UA/Referer);
      ② Cloudflare JS 质询(cloudflare-challenge):HTTP/curl_cffi 都过不了,直接走 FlareSolverr
         求解(``_flaresolverr_fallback``,可选、默认关),并【跳过】对同域必然再被质询的 curl_cffi /
         publisher 无谓重试(实测 pubs.rsc.org 154 次全 403 即此类);
      ③ curl_cffi impersonate=chrome 重取(绕 TLS/UA 指纹拦截:MDPI/金色OA 等;缺库自动跳过);
      ④ 出版商适配器(``publisher_adapter``,按 DOI 前缀模板/内容协商/Crossref);
      ⑤ 浏览器渲染兜底(``render_fetch``,可选、默认关、仅 OA);
      ⑥ 有头真浏览器过 Akamai/JS 软验证并经 CDP 下载 PDF(``_browser_pdf_download``,可选、默认关)——
         专治 MDPI 等 Akamai Bot Manager 站(bm-verify:HTTP/curl_cffi/headless 均不可过;需 browser_pdf_download=True)。
    无 DOI / 未知出版商 / 各兜底未命中时,原样返回①的核心结果。

    ``events``(可选,EventLog):命中 Cloudflare 质询且 FlareSolverr【已启用】时,记结构化事件
    ``flaresolverr_recovered``(回收成功)/ ``flaresolverr_failed``(启用但未回收)到 attempts.jsonl
    便于统计。缺省 None / FlareSolverr 未启用 → 不记任何 flaresolverr 事件(零副作用,默认行为不变)。
    """
    result = _download_pdf_core(candidate, paper, pdf_dir, client, cfg, log,
                                fallback_name, allow_landing=allow_landing)
    if result[0] is not None:
        return result

    is_cf = _is_cf_reason(result[2])

    # ② Cloudflare JS 质询 → FlareSolverr 求解后带 cf_clearance 重下(gated,默认 no-op)
    if is_cf:
        try:
            fs = _flaresolverr_fallback(candidate, paper, pdf_dir, cfg, log,
                                        fallback_name, allow_landing)
        except Exception as e:  # noqa: BLE001 - 兜底绝不能让主流程崩
            log.info("flaresolverr 兜底异常(忽略): %s", e)
            fs = None
        _cf_url = getattr(candidate, "url", "?")
        if fs and fs[0]:
            log.info("flaresolverr 过 Cloudflare 质询命中: %s", _cf_url)
            _emit_event(events, "flaresolverr_recovered", url=_cf_url,
                        source=getattr(candidate, "source", None),
                        bytes=fs[1], reason=result[2])
            return fs
        # 仅当 FlareSolverr 实际启用(已尝试)才记失败事件;默认关时零事件、零副作用。
        if _flaresolverr_enabled(cfg):
            _emit_event(events, "flaresolverr_failed", url=_cf_url,
                        source=getattr(candidate, "source", None), reason=result[2])

    # ③ curl_cffi impersonate 重取(同候选 + 落地页)。CF JS 质询对其亦不可过(实测),跳过省无谓请求。
    if not is_cf:
        cc = _curl_cffi_fallback(candidate, paper, pdf_dir, cfg, log, fallback_name, allow_landing)
        if cc and cc[0]:
            log.info("curl_cffi impersonate 命中: %s", getattr(candidate, "url", "?"))
            return cc

    if not allow_landing:
        return result

    # ④ 出版商适配器增强(既有)。CF 质询下同域 crossref/模板重试必然再被质询 → 跳过。
    if not is_cf:
        try:
            enhanced = _publisher_fallback(candidate, paper, pdf_dir, client, cfg, log, fallback_name)
        except Exception as e:  # noqa: BLE001 - 增强绝不能让主流程崩
            log.info("publisher-adapter 增强异常(忽略): %s", e)
            enhanced = None
        if enhanced and enhanced[0]:
            return enhanced

    # ⑤ 浏览器渲染兜底(可选、默认关、仅 OA)
    try:
        rr = _render_fallback(candidate, paper, pdf_dir, client, cfg, log, fallback_name)
    except Exception as e:  # noqa: BLE001
        log.info("render 兜底异常(忽略): %s", e)
        rr = None
    if rr and rr[0]:
        return rr

    # ⑥ 有头真浏览器过 Akamai/JS 软验证并【经浏览器下载】PDF(可选、默认关)——专治 MDPI 等 Akamai 站
    #    (bm-verify:requests/curl_cffi/headless 全过不了,唯有头真 Chrome 过验证后经 CDP 下载可得)。
    try:
        bp = _browser_pdf_download(candidate, paper, pdf_dir, cfg, log, fallback_name)
    except Exception as e:  # noqa: BLE001 - 兜底绝不能让主流程崩
        log.info("browser-pdf 兜底异常(忽略): %s", e)
        bp = None
    if bp and bp[0]:
        log.info("browser-pdf 过 Akamai 下载命中: %s", getattr(candidate, "url", "?"))
        return bp

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
    use_curl_cffi = False       # selftest 不联网:关闭 curl_cffi 兜底(避免对假 URL 发真实请求)
    render_fallback = False


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

    # ── ①b D2 深度完整性(可选、默认关、缺库降级):默认逐字节不改既有判定 ──
    assert pdf_defect(good, deep=False) is None                       # 默认路径与既有一致
    assert pdf_defect(truncated, deep=False) == "no-%%EOF(truncated?)"
    assert pdf_defect(b"", deep=True) == "empty"                      # 浅层否决先行,不进深度
    assert pdf_defect(b"<html></html>", deep=True) == "no-%PDF-magic"
    import fulltext_fetcher.download as _dl        # 真实模块对象(供 monkeypatch _pdf_reader)
    _saved_reader = _dl._pdf_reader
    try:
        # 缺库:即便开 deep 也降级为 None(绝不误杀合法/多样 PDF)
        _dl._pdf_reader = lambda: None
        assert _dl.pdf_defect(good, deep=True) is None
        assert _dl.pdf_defect(b"%PDF-1.4\nnope\n%%EOF\n", deep=True) is None

        # 装有解析库(用假 reader 确定性覆盖三种深度结果,免装 pypdf 亦可验证)
        class _FakeReader:
            def __init__(self, pages):
                self.pages = pages

        _dl._pdf_reader = lambda: (lambda _s: _FakeReader([object()]))   # 1 页 → 通过
        assert _dl.pdf_defect(good, deep=True) is None
        _dl._pdf_reader = lambda: (lambda _s: _FakeReader([]))           # 0 页 → 判损坏
        assert _dl.pdf_defect(good, deep=True) == "deep-zero-pages"

        def _boom(_s):
            raise ValueError("unparseable")

        _dl._pdf_reader = lambda: _boom                                 # 解析抛异常 → 判损坏
        assert _dl.pdf_defect(good, deep=True) == "deep-unparseable"
    finally:
        _dl._pdf_reader = _saved_reader

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

    # ── ④ Cloudflare JS 质询:精确识别(不误伤普通 403)+ 分类为 cloudflare-challenge ──
    _CHL = (b"<!DOCTYPE html><html><head><title>Just a moment...</title>"
            b"<script>window._cf_chl_opt=...;challenge-platform</script></head>"
            b"<body>enable javascript</body></html>")
    assert _is_cloudflare_challenge(403, {"Server": "cloudflare"}, _CHL)
    assert _is_cloudflare_challenge(503, {"cf-mitigated": "challenge"}, b"...enable JavaScript...")
    assert not _is_cloudflare_challenge(403, {"Server": "nginx"}, _CHL)          # 非 CF 前端 → 不判
    assert not _is_cloudflare_challenge(200, {"Server": "cloudflare"}, _CHL)     # 200 → 不判
    assert not _is_cloudflare_challenge(403, {"Server": "cloudflare"},
                                        b"<html>plain forbidden, no challenge</html>")  # 无特征串
    assert _is_cf_reason("cloudflare-challenge(http-403)") and not _is_cf_reason("http-403")
    assert _cookies_to_header([{"name": "cf_clearance", "value": "T"}, {"name": "a", "value": "b"}]) \
        == "cf_clearance=T; a=b"

    class _CFResp:                                    # 模拟 Cloudflare 质询响应(403 + cloudflare 头 + 质询体)
        status_code = 403
        headers = {"Server": "cloudflare", "Content-Type": "text/html; charset=utf-8"}

        def iter_content(self, n):
            yield _CHL

        def close(self):
            pass

    class _CFClient:
        def get(self, url, stream=True, headers=None):  # noqa: ARG002 - 契约签名
            return _CFResp()

    with tempfile.TemporaryDirectory() as d:
        pcf, ncf, errcf = download_pdf(
            _SelfCand("https://pubs.rsc.org/en/content/articlepdf/2022/cc/d2cc00208f"),
            _SelfPaper(), d, _CFClient(), cfg, log, "cf")
        assert pcf is None and _is_cf_reason(errcf), (pcf, ncf, errcf)   # 归因到 Cloudflare 质询

    # ── ⑤ FlareSolverr 兜底:解质询拿 cf_clearance+UA → 带其重下命中(注入假 solve/client)──
    class _FSCfg(_SelfCfg):
        use_flaresolverr = True

    def _fake_solve(url, _cfg):
        return {"cookies": [{"name": "cf_clearance", "value": "TOK"}],
                "user_agent": "Mozilla/5.0 HeadlessChrome/120", "html": "<html></html>"}

    captured_hdr: dict = {}

    class _FSDlClient:
        """假重下 client:校验带上了 cf_clearance Cookie + 求解 UA,然后吐合法 PDF。"""

        def get(self, url, stream=True, headers=None):  # noqa: ARG002 - 契约签名
            captured_hdr.update(headers or {})
            return _SelfResp(good)

    with tempfile.TemporaryDirectory() as d:
        fp, fb, ferr = _flaresolverr_fallback(
            _SelfCand("https://pubs.rsc.org/en/content/articlepdf/2022/cc/d2cc00208f"),
            _SelfPaper(), d, _FSCfg(), log, "fs", True, _solve=_fake_solve, _client=_FSDlClient())
        assert fp and ferr is None and fb == len(good), (fp, fb, ferr)
        assert "cf_clearance=TOK" in captured_hdr.get("Cookie", ""), captured_hdr
        assert captured_hdr.get("User-Agent", "").endswith("HeadlessChrome/120"), captured_hdr

    # ⑤b gated:未启用(且清空 env)→ None(默认零副作用、绝不发请求);启用判定正确
    _saved_env = os.environ.pop("FLARESOLVERR_URL", None)
    try:
        assert _flaresolverr_enabled(_SelfCfg()) is False
        assert _flaresolverr_fallback(_SelfCand("https://x/y"), _SelfPaper(), ".", _SelfCfg(), log,
                                      "z", True, _solve=_fake_solve, _client=_FSDlClient()) is None
    finally:
        if _saved_env is not None:
            os.environ["FLARESOLVERR_URL"] = _saved_env
    assert _flaresolverr_enabled(_FSCfg()) is True
    assert _flaresolverr_enabled(type("C", (), {"flaresolverr_url": "http://localhost:8191"})()) is True

    # ⑤c 启用但未拿到 cf_clearance cookie → None(不会用无效会话瞎重下)
    with tempfile.TemporaryDirectory() as d:
        none_cookie = _flaresolverr_fallback(
            _SelfCand("https://pubs.rsc.org/x"), _SelfPaper(), d, _FSCfg(), log, "fs2", True,
            _solve=lambda u, c: {"cookies": [], "user_agent": "x"}, _client=_FSDlClient())
        assert none_cookie is None, none_cookie

    # ⑤d 结构化事件(便于 attempts.jsonl 统计):经 download_pdf 的 CF 分支,命中记
    #     flaresolverr_recovered、启用但未回收记 flaresolverr_failed;默认关 → 零 flaresolverr 事件。
    #     用假 events 收集器 + monkeypatch _dl._flaresolverr_fallback 确定性覆盖(不联网)。
    class _Events:
        def __init__(self):
            self.rec = []

        def emit(self, event, **fields):
            self.rec.append((event, fields))

    _saved_fs = _dl._flaresolverr_fallback
    try:
        with tempfile.TemporaryDirectory() as d:
            # 命中 → flaresolverr_recovered(带 url/source/bytes/reason)
            _dl._flaresolverr_fallback = lambda *a, **k: ("x.pdf", len(good), None)
            ev = _Events()
            pr, _, _ = _dl.download_pdf(_SelfCand("https://pubs.rsc.org/x"), _SelfPaper(), d,
                                        _CFClient(), _FSCfg(), log, "e1", events=ev)
            assert pr and "flaresolverr_recovered" in [e[0] for e in ev.rec], (pr, ev.rec)

            # 启用但未回收 → flaresolverr_failed(仍返回 CF 失败原因)
            _dl._flaresolverr_fallback = lambda *a, **k: None
            ev2 = _Events()
            pr2, _, er2 = _dl.download_pdf(_SelfCand("https://pubs.rsc.org/x"), _SelfPaper(), d,
                                           _CFClient(), _FSCfg(), log, "e2", events=ev2)
            assert pr2 is None and _is_cf_reason(er2), (pr2, er2)
            assert "flaresolverr_failed" in [e[0] for e in ev2.rec], ev2.rec

            # 默认关(未启用)+ 清空 env → 零 flaresolverr 事件(零副作用)
            _saved_env3 = os.environ.pop("FLARESOLVERR_URL", None)
            try:
                ev3 = _Events()
                _dl.download_pdf(_SelfCand("https://pubs.rsc.org/x"), _SelfPaper(), d,
                                 _CFClient(), _SelfCfg(), log, "e3", events=ev3)
                assert not any(str(e[0]).startswith("flaresolverr_") for e in ev3.rec), ev3.rec
            finally:
                if _saved_env3 is not None:
                    os.environ["FLARESOLVERR_URL"] = _saved_env3
    finally:
        _dl._flaresolverr_fallback = _saved_fs

    # ── ⑥ 合规硬守卫:影子库(sci-hub/libgen…)默认拒绝,除非显式 enable_scihub ──
    assert _is_shadow_library("https://sci-hub.se/10.1/x") and _is_shadow_library("https://sci-hub.box/x")
    assert _is_shadow_library("http://libgen.rs/x") and _is_shadow_library("https://annas-archive.org/x")
    assert _is_shadow_library("https://z-lib.org/x") and _is_shadow_library("https://zlibrary.org/x")
    assert not _is_shadow_library("https://doi.org/10.1/x")
    assert not _is_shadow_library("https://www.sciencedirect.com/science/article/pii/S00/pdfft")  # 不误伤
    assert not _is_shadow_library("") and not _is_shadow_library(None)
    with tempfile.TemporaryDirectory() as d:
        # 默认(无 enable_scihub)→ 拒绝、不联网、不落盘、原因 blocked-shadow-library
        ps, nsz, es = download_pdf(_SelfCand("https://sci-hub.se/10.1/x.pdf"), _SelfPaper(), d,
                                   _SelfClient(good), _SelfCfg(), log, "sh")
        assert ps is None and es == "blocked-shadow-library", (ps, nsz, es)
        assert os.listdir(d) == [], "影子库不应落盘"

        # 显式 enable_scihub=True → 放行(fake client 吐合法 PDF → 正常落盘)
        class _CfgSci(_SelfCfg):
            enable_scihub = True

        ps2, nsz2, es2 = download_pdf(_SelfCand("https://sci-hub.se/10.1/x.pdf"), _SelfPaper(), d,
                                      _SelfClient(good), _CfgSci(), log, "sh2")
        assert ps2 and es2 is None and nsz2 == len(good), (ps2, nsz2, es2)

    print("DOWNLOAD_OK")


if __name__ == "__main__":
    _selftest()
