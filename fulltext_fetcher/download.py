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


def _browser_capture_enabled(cfg: Any) -> bool:
    """浏览器内 JA3 直下 PDF 是否【显式】启用:cfg.browser_capture 或环境变量 FTF_BROWSER_CAPTURE=1。
    默认关(零副作用、需有头 nodriver 与显示环境)。注:route-B 作为默认兜底能力另由
    ``_route_b_auto_fallback_enabled`` 控制(默认开、无引擎优雅 no-op),见 ``_browser_capture_fallback``。"""
    if getattr(cfg, "browser_capture", False):
        return True
    return os.environ.get("FTF_BROWSER_CAPTURE", "").strip().lower() in ("1", "true", "yes")


# 「需浏览器内抓字节」的出版商 host 补集(-157):is_ja3_bound_cf_host 未覆盖、但过盾/过验证后 PDF 走
# 【跨域 CDN attachment / 内联 viewer】的站。MDPI(/pdf?version= attachment,-149/-141 实证方法C 7/7);
# RSC(pubs.rsc.org)/ScienceDirect/Wiley/ACS 已在 render_fetch._JA3_BOUND_CF_HOSTS,其 silverchair 签名
# CDN 由文章页导航后同源 fetch 命中(方法D),故此处只补 is_ja3 未含者。子串匹配(与 _JA3_BOUND 一致)。
_BROWSER_CAPTURE_EXTRA_HOSTS = ("mdpi.com",)


def _needs_browser_capture_host(url: str) -> bool:
    """该 URL host 是否属「需浏览器内抓字节」集:render_fetch 的 JA3 绑定型强 CF 站
    (RSC/ScienceDirect/Wiley/ACS)∪ 过盾后 PDF 走跨域 CDN attachment/inline-viewer 的出版商(MDPI 等)。

    命中者才在标准源全 miss 后走 ``render_download_pdf_bytes``(浏览器内直下)兜底;普通 OA 站不在集内,
    绝不因本兜底平白多走浏览器(护栏③)。缺 render_fetch 时退化为仅补集判定。"""
    try:
        from .render_fetch import is_ja3_bound_cf_host
    except ImportError:
        def is_ja3_bound_cf_host(_u: str) -> bool:
            return False
    if is_ja3_bound_cf_host(url):
        return True
    try:
        host = (urlsplit(url or "").hostname or "").lower()
    except Exception:  # noqa: BLE001 - 畸形 URL 保守视为不匹配
        return False
    return any(h in host for h in _BROWSER_CAPTURE_EXTRA_HOSTS)


def _route_b_auto_fallback_enabled(cfg: Any) -> bool:
    """route-B 抓字节是否作为【默认兜底能力】启用(标准 OA 源全 miss 后,对『需浏览器抓字节』的出版商
    落地页兜底调 ``render_download_pdf_bytes``)。

    默认 True:缺 nodriver / 无显示环境时 ``render_download_pdf_bytes`` 内部优雅 no-op,且 host 集限定
    (``_needs_browser_capture_host``)使普通 OA 站不受影响,故默认开启对普通路径零副作用。
    显式置 ``cfg.route_b_auto_fallback=False`` 可整体回退到「仅显式 browser_capture / env 时才走」的旧语义
    (selftest 即用此关掉,避免装了 nodriver 的 CI 误起真浏览器)。"""
    return bool(getattr(cfg, "route_b_auto_fallback", True))


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


# Windows 保留设备名(不分大小写、忽略扩展名):这些名字即便带扩展名也非法(open 报 [Errno 22])。
_WIN_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str) -> str:
    """任意文本 → 合法且跨平台安全的文件名 stem(不含扩展名)。

    Windows 最严标准(向下兼容 POSIX),避免 DOI 含 ``<>:"/\\|?*``(如老 Wiley
    ``10.1002/1099-0739(200012)14:12<..>``)或控制符时 ``open()`` 报 ``[Errno 22]``:
    - 非 ``[\\w.-]`` 一律折叠为单个 ``_``(``re.UNICODE`` 保留 Unicode 字母/数字)——
      一举清掉全部 Windows 非法字符与 ASCII 控制符;
    - 去首尾 ``_ . 空格``(Windows 会静默截断结尾点/空格 → 找不到文件),限长后再去一次尾;
    - Windows 保留设备名(CON/NUL/COM1…,忽略扩展名、不分大小写)前缀 ``_`` 规避;
    - 兜底空名 → ``paper``。
    """
    name = re.sub(r"[^\w.\-]+", "_", name or "", flags=re.UNICODE)
    name = name.strip("_. ")[:140].strip("_. ")
    if not name:
        return "paper"
    if name.split(".", 1)[0].lower() in _WIN_RESERVED:
        name = "_" + name
    return name


def target_name(paper: Any, fallback: str, cfg: Any = None) -> str:
    """据 paper 元数据构造落盘 PDF 文件名。

    默认(``cfg`` 为空或未设 ``naming_template``)沿用 DOI 净化名,与本参数引入前**逐字节一致**
    (doi.replace('/','_') → arxiv_ → 标题[:80] → fallback,再 sanitize_filename + '.pdf')。
    若 ``cfg.naming_template`` 非空 → 复用 scholar/naming.build_filename 按模板渲染标准化名
    (净化/截断逻辑同源、不重造;result=None → 直接用父包 Paper 的年/作者/标题/DOI 元数据兜底降级)。
    """
    template = getattr(cfg, "naming_template", None) if cfg is not None else None
    if template:
        from .scholar.naming import build_filename   # 延迟导入避免与 naming(其 import 本模块)循环
        return build_filename(None, paper, cfg)
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


def _save(data: bytes, paper: Any, pdf_dir: str, fallback_name: str, cfg: Any = None) -> str:
    os.makedirs(pdf_dir, exist_ok=True)
    fname = target_name(paper, fallback_name, cfg)
    if getattr(cfg, "naming_template", None):
        # 模板模式:复用 naming.dedupe_path 按磁盘现存文件去重(year_author_title 类名撞名概率高于唯一 DOI)。
        # 默认(DOI)分支保持原样(os.path.join,同名覆盖),行为逐字节不变。
        from .scholar.naming import dedupe_path
        path = dedupe_path(pdf_dir, fname)
    else:
        path = os.path.join(pdf_dir, fname)
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


def _safe_log(log: Any, fmt: str, *args: Any) -> None:
    """尽力记一行 info 日志:log 为 None / 无 info / 抛错一律静默(记日志绝不影响主下载流程)。"""
    if log is None:
        return
    info = getattr(log, "info", None)
    if not callable(info):
        return
    try:
        info(fmt, *args)
    except Exception:  # noqa: BLE001 - 记日志失败绝不能影响主流程
        pass


def _safe_warn(log: Any, fmt: str, *args: Any) -> None:
    """尽力记一行 warning 日志(强告警):log 无 warning 则回退 info;任何异常静默(绝不影响主流程)。

    用于 QC 依赖缺失等"必须让操作者看见、绝不能静默"的降级/拒收场景(见 _content_qc_gate)。
    """
    if log is None:
        return
    fn = getattr(log, "warning", None) or getattr(log, "info", None)
    if not callable(fn):
        return
    try:
        fn(fmt, *args)
    except Exception:  # noqa: BLE001 - 记日志失败绝不能影响主流程
        pass


# ────────────────── 内容 QC 门(P0:记 success 前的标题/DOI 比对) ──────────────────
# 背景:审计实锤 websearch 兜底存在系统性"错论文"假阳(如同一 nature PDF 被当成 4 个 RSC DOI 的答案;
# 10.1002/cssc.201601217 落盘成皮肤病 jaad 论文)。根因:下载校验只看 %PDF+体积,不核对"是不是这篇"。
# 据此:对**非 DOI-keyed 来源**(靠自由文本/标题/URL 搜索,或解析任意落地页定位 PDF —— websearch /
# wayback / browser_search 及任何经 +landing 解析者)在落盘记 success 前加一道比对门;**DOI-keyed 源**
# (unpaywall/openalex/publisher_oa/crossref/S2/snapshot… 按 DOI 直取、假阳风险低)默认豁免,避免误杀
# 绿OA预印本/译名/子标题的真命中。总开关 cfg.content_qc(默认 True)可整体回退。
_QC_GATE_SOURCE_MARKERS = ("websearch", "wayback", "browser_search", "landing")


def _source_needs_content_qc(source: Any, cfg: Any) -> bool:
    """该来源是否需过内容 QC 门:cfg.content_qc 开启 且 source 命中非 DOI-keyed marker。

    marker 覆盖复合 source 串(如 "websearch+landing"、"unpaywall+landing")——只要经过自由搜索或
    落地页解析这一步就进门;纯 DOI 直取的源(source 不含任何 marker)一律豁免。cfg 无 content_qc
    字段时默认视为开(getattr 兜底),故 selftest 的精简 cfg 亦按默认启用。

    例外(非正文增强,173):publisher_oa:acs-authorchoice 虽按 DOI 构造(本应豁免),但 recover_b4_cf
    实锤 5/5 全部落到 Supporting Information(URL /doi/pdf/ 却 serve SI),故在 content_qc_non_article
    开启时【强制过门】,交由门④ SI 判识兜住;关闭非正文增强则回退为豁免。
    """
    if not getattr(cfg, "content_qc", True):
        return False
    s = str(source or "").lower()
    if getattr(cfg, "content_qc_non_article", True) and "acs-authorchoice" in s:
        return True
    return any(m in s for m in _QC_GATE_SOURCE_MARKERS)


def _extract_pdf_text_meta(data: bytes, max_pages: int = 2, max_chars: int = 6000):
    """从 PDF 字节抽 (元数据 title, 首 max_pages 页正文文本);缺 pypdf / 任何异常 → (None, None)。

    与 D2 的 _pdf_page_defect 同哲学:延迟取 pypdf(可选依赖),不可用即降级(交由门放行,绝不误杀)。
    """
    reader = _pdf_reader()
    if reader is None:
        return None, None
    import io
    try:
        r = reader(io.BytesIO(data))
        meta_title = None
        try:
            md = r.metadata
            if md and getattr(md, "title", None):
                meta_title = str(md.title)
        except Exception:  # noqa: BLE001 - 元数据缺失/畸形 → 无 meta_title
            meta_title = None
        parts = []
        for pg in r.pages[:max_pages]:
            try:
                parts.append(pg.extract_text() or "")
            except Exception:  # noqa: BLE001 - 单页抽取失败跳过,不影响其它页
                continue
            if sum(len(x) for x in parts) >= max_chars:
                break
        return meta_title, (" ".join(parts))[:max_chars]
    except Exception:  # noqa: BLE001 - 解析失败 → 降级(门放行)
        return None, None


def _pdf_page_count(data: bytes) -> Optional[int]:
    """PDF 页数(pypdf);缺库/任何异常 → None(降级)。

    供门⑤ poster(单页)/ 目录页(<=3 页)判识用。与 _extract_pdf_text_meta 同哲学:页数未知时
    需页数的门不据页数误杀(见 _content_qc_non_article_reject),故此处 None 是安全降级值,绝不误杀。
    """
    reader = _pdf_reader()
    if reader is None:
        return None
    import io
    try:
        return len(reader(io.BytesIO(data)).pages)
    except Exception:  # noqa: BLE001 - 解析失败/惰性异常 → 页数未知
        return None


def _qc_matchers():
    """(延迟、异常安全)复用 151 的 tools/qc_content_match 匹配原语,绝不重复造匹配逻辑。

    取 clean_title / norm_for_doi / is_unextractable / token_set_ratio、阈值 MATCH_HI/MISMATCH_LO
    与 FUZZ_BACKEND(rapidfuzz 或 difflib 兜底)。任何导入失败(缺模块/顶层异常)→ None;
    (Exception, SystemExit) 双兜底防御旧版模块可能的 sys.exit。命中返回 dict 供 _content_qc_verdict 复用。
    注意:matchers 本身不依赖 pypdf(clean_title/token_set_ratio 等纯逻辑),故 _qc_matchers() 返回
    非 None ≠ pypdf 可用;pypdf(抽正文所需)另由 _pdf_reader() 在门内单独校验(见 _content_qc_gate)。
    """
    try:
        from tools.qc_content_match import (  # type: ignore
            FUZZ_BACKEND, MATCH_HI, MISMATCH_LO, clean_title, is_unextractable,
            norm_for_doi, token_set_ratio,
        )
    except (Exception, SystemExit):  # noqa: BLE001 - 防御导入期任何异常/退出
        return None
    return {
        "clean_title": clean_title,
        "norm_for_doi": norm_for_doi,
        "is_unextractable": is_unextractable,
        "token_set_ratio": token_set_ratio,
        "match_hi": MATCH_HI,
        "mismatch_lo": MISMATCH_LO,
        "fuzz_backend": FUZZ_BACKEND,
    }


_QC_BACKEND_WARNED = False


def _qc_warn_degraded_backend(m: Optional[dict], log: Any) -> None:
    """rapidfuzz 缺失时 tools.qc_content_match 自动降级到 difflib:QC 仍生效、仅标题模糊精度略降。

    据此记【一次】软告警(每进程去重),提示装 rapidfuzz 提质;**不**触发 fail-closed(有可用兜底)。
    """
    global _QC_BACKEND_WARNED
    if _QC_BACKEND_WARNED:
        return
    if (m or {}).get("fuzz_backend") == "difflib":
        _QC_BACKEND_WARNED = True
        _safe_warn(log, "content-qc 模糊后端降级为 difflib(rapidfuzz 未安装):标题匹配精度略降、"
                        "QC 仍生效;建议 pip install fulltext_fetcher[qc]。")


# ── 第二信号(跨社"错论文"佐证)所需的出版商映射 ──────────────────────────────
# 判定沿革(两轮校正,定稿=双门 union):第一轮曾疑"标题法过判"而取交集(标题不符 AND 跨社
# 第二信号);第二轮审计逐条交叉验证实锤——content-mismatch(标题分<50)≈100% 准,且 189 条
# 同域错论文(publisher 桶 61 + repository 桶 128:同社他篇,如 Springer DOI→另一篇 Springer
# 论文,URL host 同社、正文 DOI 同社前缀;或仓库托管他篇)跨社信号根本不触发,交集会整批放行。
# 故定稿【并集】:硬拒 = 门①标题明确不符(<mismatch_lo,能抽出正文) OR 门②第二信号(URL 嵌
# 异 DOI / 正文首部异社 DOI / URL host 跨社)。uncertain[mismatch_lo,match_hi) / 扫描件 /
# 门②两侧出版商未知 → 放行打标(不拒)。跨社按【出版商标签】判(非 DOI 前缀:同社多前缀如
# Wiley 10.1002/10.1111 不算跨社)。映射为 QC 专用、比 publisher_adapter 注册表更广;可据审计
# "高置信错论文集"扩充/校准。
_QC_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>?#)\]]+")
_QC_PREFIX_LABELS = {
    "10.1016": "elsevier", "10.1021": "acs", "10.1039": "rsc", "10.1007": "springer",
    "10.1002": "wiley", "10.1111": "wiley", "10.3390": "mdpi", "10.1088": "iop",
    "10.1109": "ieee", "10.1038": "nature", "10.1126": "aaas", "10.1073": "pnas",
    "10.1103": "aps", "10.1063": "aip", "10.1093": "oup", "10.1080": "tandf",
    "10.1177": "sage", "10.1136": "bmj", "10.1371": "plos", "10.1186": "bmc",
    "10.3389": "frontiers", "10.1145": "acm", "10.1049": "iet",
}
_QC_HOST_LABELS = {
    "pubs.acs.org": "acs", "sciencedirect.com": "elsevier", "link.springer.com": "springer",
    "onlinelibrary.wiley.com": "wiley", "pubs.rsc.org": "rsc", "iopscience.iop.org": "iop",
    "mdpi.com": "mdpi", "ieeexplore.ieee.org": "ieee", "nature.com": "nature",
    "science.org": "aaas", "pnas.org": "pnas", "journals.aps.org": "aps",
    "academic.oup.com": "oup", "tandfonline.com": "tandf", "journals.sagepub.com": "sage",
    "journals.plos.org": "plos", "biomedcentral.com": "bmc", "frontiersin.org": "frontiers",
    "dl.acm.org": "acm",
}
_QC_DOI_PREFIX_RE = re.compile(r"\s*(?:https?://(?:dx\.)?doi\.org/|doi:)?\s*(10\.\d{4,9})/", re.I)


def _qc_prefix_label(doi: Any) -> Optional[str]:
    """DOI → 出版商标签(按 10.xxxx 前缀查 _QC_PREFIX_LABELS);未知/非法 → None。"""
    if not doi:
        return None
    m = _QC_DOI_PREFIX_RE.match(str(doi))
    if not m:
        return None
    return _QC_PREFIX_LABELS.get(m.group(1).lower())


def _qc_host_label(url: Any) -> Optional[str]:
    """URL host → 已知出版商标签;非出版商 host(仓储/自存稿/doi.org)→ None(不作跨社佐证)。"""
    try:
        host = (urlsplit(str(url)).hostname or "").lower()
    except Exception:  # noqa: BLE001 - 畸形 URL → 无 host 标签
        return None
    if not host:
        return None
    for h, lab in _QC_HOST_LABELS.items():
        if host == h or host.endswith("." + h):
            return lab
    return None


def _qc_doi_publisher_conflict(url: Any, text: Any, exp_doi: Any, norm_for_doi) -> Tuple[bool, str]:
    """门②(URL/嵌入 DOI 佐证"错论文",独立于标题;专堵 title 假匹配,如 frontiersin / 未来年份 DOI):
      (a) URL 里嵌了一个与期望【不同】的完整 DOI —— URL 是取件来源、无参考文献噪声,最强(异 DOI 即错);
      (b) 正文首 1200 字(规避参考文献区)出现另一家【已知出版商】的 DOI;
      (c) URL host 属另一家【已知出版商】。
    仅在期望 DOI 已确认不在 URL/正文(见 verdict 门前 match 判定)后调用。exp_doi 缺失 → False。
    (b)/(c) 需两侧出版商都已知(高置信,规避误伤);(a) 只需 URL 内 DOI 与期望不同即判。
    """
    if not exp_doi:
        return False, "no-expected-doi"
    en = norm_for_doi(exp_doi)
    for mobj in _QC_DOI_RE.finditer(str(url or "")):
        if norm_for_doi(mobj.group(0)) != en:
            return True, f"url-embeds-different-doi:{mobj.group(0)[:48]}"
    exp_label = _qc_prefix_label(exp_doi)
    if exp_label:
        for mobj in _QC_DOI_RE.finditer(str(text or "")[:1200]):
            lab = _qc_prefix_label(mobj.group(0))
            if lab and lab != exp_label and norm_for_doi(mobj.group(0)) != en:
                return True, f"header-doi-cross-publisher:{lab}!={exp_label}"
    hlab = _qc_host_label(url)
    if exp_label and hlab and hlab != exp_label:
        return True, f"url-host-cross-publisher:{hlab}!={exp_label}"
    return False, "no-conflict"


# ── DOI 命中位置权重(149 实锤假阳:参考文献/引用区里的 DOI 被误当正文命中)────────────────
# 149 开卷复核实锤:内容 QC「① 强正:期望 DOI 出现在正文」把【参考文献/引用区】里出现的 DOI 也当成
# in-text 命中 → 假阳(如 aic.690210612:落盘 PDF 实为他篇正文,只在其参考文献里引到期望 DOI,却被判
# success)。故按位置分区加权:DOI 在【正文/摘要区】命中 = 强证据(保留强正);仅在【参考文献/引用区】
# 命中 = 降权(不作强正,回落标题门①/门④⑤裁定)。URL 内命中另算(取件来源、无参考文献噪声,仍最强,
# 见 _qc_doi_publisher_conflict 注)。
_QC_REFS_HEADING_RE = re.compile(
    r"(?i)(?:references\s+and\s+notes|notes\s+and\s+references|references\s+cited|"
    r"literature\s+cited|\breferences\b|\bbibliography\b|参考文献|引用文献|参考资料)")


def _qc_doi_hit_zone(text: Any, exp_doi_norm: str, norm_for_doi) -> Optional[str]:
    """期望 DOI 在正文文本里的命中区:'body'(正文/摘要,强证据)/'references'(仅参考文献·引用区,
    降权)/None(未命中)。

    以【首个】参考文献区标题(References / Bibliography / 参考文献 …)为界,其后视为参考文献区:
    界前(含无标题时的全文)命中 → body;仅界后命中 → references;两处皆无 → None。未检出标题 →
    全文按 body(保持旧行为、绝不误杀真正文——真正文即便正文/摘要有 DOI 也仍走标题门兜底)。
    纯字符串/正则,绝不抛(exp_doi_norm 已由调用方规范化)。
    """
    if not exp_doi_norm:
        return None
    s = str(text or "")
    if not s:
        return None
    mobj = _QC_REFS_HEADING_RE.search(s)
    if mobj is None:
        return "body" if exp_doi_norm in norm_for_doi(s) else None
    if exp_doi_norm in norm_for_doi(s[:mobj.start()]):
        return "body"
    if exp_doi_norm in norm_for_doi(s[mobj.start():]):
        return "references"
    return None


# ── 门④⑤:非正文版式硬信号(SI / citation-report / poster / 目录页 + 垃圾域黑名单)──────────
# 背景(recover_b4_cf 实锤,见《选型2026-QC并集门增强建议-recover_b4_cf假阳-173.md》M 节):既有并集门
# (门①标题 + 门②跨社/异 DOI)对"同社同 DOI 却拿到 SI / citation-report / poster / 卷期目录(TOC)"
# 零免疫——PDF 首页印着正确标题+DOI,却不是正文。这类"像这篇但不是正文"应从 match 降级为 uncertain
# (默认;可配 hard_reject→mismatch),既不虚增净覆盖,又不误杀真正文(靠首页关键词 + 页数/正文长度阈)。
_QC_NA_ARTICLE_BODY_RE = re.compile(
    r"(?i)\b(abstract|introduction|results?\s+and\s+discussion|"
    r"experimental\s+section|materials\s+and\s+methods)\b")
_QC_NA_SI_HEAD_RE = re.compile(r"(?im)^\s*s-?\d+\s*[.\)]")   # 页首 "S-1." / "S1)" 等 SI 编号
_QC_NA_SI_URL_MARKERS = ("/suppl", "supporting", "_si_", "si_001", "/si/", "supplement")
_QC_NA_CITATION_RE = re.compile(r"(?i)(cited\s+by|references\s+cited|citation\s+report|times\s+cited)")
_QC_NA_POSTER_RE = re.compile(
    r"(?i)(poster\s+session|conference\s+poster|poster\s+template|poster\s+presentation)")
_QC_NA_TOC_RE = re.compile(
    r"(?i)(table\s+of\s+contents|index\s+to\s+volume|author\s+index|\btoc\b|issue\s+of\s+the)")
_QC_NA_DOMAIN_BLACKLIST = ("exaly.com",)   # citation-report 垃圾域(M 节实锤 2 条)


def _qc_url_host(url: Any) -> str:
    """URL → 小写 host(纯提取,不做出版商映射);畸形/空 → ""。"""
    try:
        return (urlsplit(str(url)).hostname or "").lower()
    except Exception:  # noqa: BLE001 - 畸形 URL → 无 host
        return ""


def _content_qc_non_article_reject(url, meta_title, text, source, page_count):
    """门④⑤ + 域黑名单:判 PDF 是否为【非正文版式】(SI / citation-report / poster / 目录页)。

    返回 (hit: bool, reason);命中 reason ∈ {non-article-si, non-article-citation-report,
    non-article-poster, non-article-index-or-toc}。调用方据配置把命中降级为 uncertain(默认)或
    mismatch(hard_reject)。刻意保守以【不误杀真正文】:
      - 真正文(首 3000 字含 Abstract/Introduction/Results and Discussion/… 章节)一律不判非正文
        (故正文末尾附带 SI 章节、正文引用"cited by"均不误杀);
      - 需页数的门(poster==1 / 目录<=3)在 page_count 未知(缺 pypdf)时不据页数误杀。
    纯字符串/正则,绝不抛(调用方另有异常兜底)。
    """
    head = (text or "")[:3000]
    first500 = (text or "")[:500]
    meta_l = str(meta_title or "").lower()
    url_l = str(url or "").lower()
    src_l = str(source or "").lower()
    has_body = bool(_QC_NA_ARTICLE_BODY_RE.search(head))

    # 门④ SI:URL/路径 SI 标记,或首页"Supporting Information"/页首 S-编号,且【无正文章节】
    si_url = any(mk in url_l for mk in _QC_NA_SI_URL_MARKERS)
    si_text = (("supporting information" in first500.lower())
               or ("supporting information" in meta_l)
               or bool(_QC_NA_SI_HEAD_RE.search(first500)))
    if (si_url or si_text) and not has_body:
        return True, "non-article-si"
    # 门④ ACS-authorchoice 特判:该源(recover_b4_cf 5/5 全 SI)+ /doi/pdf/ + 正文以 S-编号开头 → SI
    if ("acs-authorchoice" in src_l and "/doi/pdf/" in url_l
            and _QC_NA_SI_HEAD_RE.search(first500) and not has_body):
        return True, "non-article-si"

    # 门⑤A citation-report:垃圾域 / 路径 /citation-report / 首页引证计数词且无正文章节
    host = _qc_url_host(url)
    if host and any(host == b or host.endswith("." + b) for b in _QC_NA_DOMAIN_BLACKLIST):
        return True, "non-article-citation-report"
    if "/citation-report" in url_l:
        return True, "non-article-citation-report"
    if _QC_NA_CITATION_RE.search(head[:1500]) and not has_body:
        return True, "non-article-citation-report"

    # 门⑤B poster:单页 + 首页/元数据含 poster 关键词 + 无正文章节(页数未知则不判,避免误杀)
    poster_kw = bool(_QC_NA_POSTER_RE.search(head)) or ("poster" in meta_l)
    if poster_kw and page_count == 1 and not has_body:
        return True, "non-article-poster"

    # 门⑤C 目录页/index:首页目录关键词 + 无正文章节 + 页数<=3(未知则放宽为仅关键词+无正文)
    if (_QC_NA_TOC_RE.search((text or "")[:1000]) and not has_body
            and (page_count is None or page_count <= 3)):
        return True, "non-article-index-or-toc"

    return False, "article-or-unknown"


def _content_qc_verdict(url, meta_title, text, exp_title, exp_doi, m,
                        source=None, page_count=None, non_article=True, hard_reject=False):
    """判定 (verdict, score, reason);**双门 union**(总指挥二次校正:审计逐条交叉验证确认标题法
    mismatch 属实、非过判——350 条真错论文 URL 法看不到,故不能只取交集)。

    记 success 需"内容标题匹配 AND URL-DOI 一致",**任一为错即 mismatch**:
      ① 强正:期望 DOI 出现在正文/URL → match(该 PDF 确为这篇,压过下面两门);
      ② 门①内容:能抽出正文且标题分 < mismatch_lo(明确他题)→ mismatch(拦 URL 法看不到的真错论文);
      ③ 门②URL/嵌入:URL 或正文首部佐证异出版商/异 DOI(即便标题模糊命中)→ mismatch(拦 title 假匹配);
      ④ 标题分 >= match_hi → match;
      ⑤ 抽不出正文(扫描)/ 无期望标题 / 中间带 → uncertain(放行打标,绝不误杀 undecidable)。

    非正文门(门④⑤,non_article=True 时启用,173):在【判 match 之前】先跑 _content_qc_non_article_reject,
    若命中 SI / citation-report / poster / 目录页 等非正文版式 → 从 match 降级为 uncertain(默认;
    hard_reject=True 则 mismatch 硬拒)。**非正文优先于 DOI 强正与标题 match**(同社同 DOI 也拦),但
    门①②(明确他题/跨社)属更强的"错论文"信号,仍优先返回 mismatch;真正文(含末尾 SI 章节)不误杀。
    """
    clean_title = m["clean_title"]
    norm_for_doi = m["norm_for_doi"]
    is_unextractable = m["is_unextractable"]
    token_set_ratio = m["token_set_ratio"]
    match_hi = m["match_hi"]
    mismatch_lo = m["mismatch_lo"]

    # 门④⑤ 非正文版式(降级信号):命中则把"本会判 match"降级为 uncertain(默认)/ mismatch(hard_reject)
    na_hit, na_reason = (
        _content_qc_non_article_reject(url, meta_title, text, source, page_count)
        if non_article else (False, "non-article-disabled"))
    na_verdict = "mismatch" if hard_reject else "uncertain"

    doi_refs_only = False                           # 149:期望 DOI 仅在参考文献/引用区命中 → 降权、不作强正
    if exp_doi:
        en = norm_for_doi(exp_doi)
        if en:
            url_hit = en in norm_for_doi(url or "")
            zone = _qc_doi_hit_zone(text, en, norm_for_doi)   # body / references / None
            if url_hit or zone == "body":
                # ① 强正:DOI 在 URL(取件来源、无参考文献噪声)或【正文/摘要区】→ 该 PDF 确为这篇
                if na_hit:                          # 非正文优先于 DOI 强正:同社同 DOI 的 SI/目录也降级
                    return na_verdict, 100.0, na_reason
                return "match", 100.0, "expected-doi-present"
            if zone == "references":
                # 149 假阳:期望 DOI 仅在参考文献/引用区被引 → 不作强正,回落标题门①/门④⑤(下)裁定
                doi_refs_only = True

    exp = clean_title(exp_title)
    meta_score = token_set_ratio(exp, clean_title(meta_title)) if (exp and meta_title) else -1.0
    body_score = token_set_ratio(exp, clean_title(text)) if (exp and text) else -1.0
    score = max(meta_score, body_score)
    scanned = is_unextractable(text)

    # 门①:能抽出正文且标题明确不符(< mismatch_lo)→ mismatch(扫描件不走此门,避免误杀 undecidable)
    if (not scanned) and (0 <= score < mismatch_lo):
        return "mismatch", score, f"content-title-mismatch(<{mismatch_lo})"
    # 门②:URL/嵌入 DOI 异出版商/异 DOI(即便标题命中)→ mismatch
    conflict, why2 = _qc_doi_publisher_conflict(url, text, exp_doi, norm_for_doi)
    if conflict:
        return "mismatch", score, f"url-doi-conflict({why2})"

    if score >= match_hi:
        if na_hit:                                  # 非正文优先于标题 match:标题对但拿到 SI/目录 → 降级
            return na_verdict, score, na_reason
        return "match", score, "title-match"
    # 其余(扫描/中间带/无期望标题)本判 uncertain;若非正文命中,统一用非正文原因(hard_reject 则升为 mismatch)
    if na_hit:
        return na_verdict, score, na_reason
    _rz = "+doi-in-references-only" if doi_refs_only else ""   # 149:标注 DOI 仅参考文献区命中(供审计)
    if scanned:
        return "uncertain", score, "scanned/no-extractable-text" + _rz
    if score < 0:
        return "uncertain", score, "no-expected-title" + _rz
    return "uncertain", score, "partial-title-overlap" + _rz


def _content_qc_gate(data: bytes, paper: Any, source: Any, url: Any, cfg: Any, log: Any,
                     events: Any = None, force: bool = False) -> Optional[str]:
    """内容 QC 门:非 DOI-keyed 来源在记 success 前做标题/DOI 比对(复用 151 匹配原语)。

    返回:判为高置信错论文(mismatch=标题明确不符 OR 跨社第二信号,双门 union)→ 返回
    "content-mismatch(...)" 原因串(调用方据此判失败、不落盘);其余(match / uncertain / 豁免源 /
    无锚点 / 任何异常)→ None(放行)。绝不抛、不误杀 undecidable:抽不出正文(扫描)、
    中间带 [mismatch_lo,match_hi)、无期望标题/DOI 一律放行。uncertain→放行并
    记 qc_uncertain(log + 结构化事件 content_qc,便于 attempts.jsonl 审计);mismatch 同时记事件与
    失败原因。

    **QC 依赖 fail-closed(总指挥 item3)**:本条已需过门却缺关键依赖(tools.qc_content_match 不可
    导入 / pypdf 抽不出正文)时,不再静默放行——默认(cfg.content_qc_require_deps=True)强告警 +
    记事件并返回 "content-qc-deps-missing(...)" 拒收不落盘;置 False 才降级放行并打标 qc_uncertain。
    rapidfuzz 缺失有 difflib 兜底、不视为关键依赖(仅记一次软告警)。

    ``force``(总指挥 P0 item1):route-B 浏览器路径(browser-capture / browser-pdf)落盘前调用时置
    True——**强制过门,越过"DOI-keyed 源豁免"**(RSC/ACS 等 DOI-keyed 源本会豁免,但 route-B 经浏览器
    导航,易落到 SI / 质询插页 / 错页,故与 acs-authorchoice 同理强制核验)。总开关 ``cfg.content_qc``
    仍可整体回退(force 不越过总开关)。
    """
    if not getattr(cfg, "content_qc", True):
        return None                              # 总开关关 → 整体回退(force 亦不越过)
    if not force and not _source_needs_content_qc(source, cfg):
        return None                              # 非强制 且 源豁免(DOI-keyed)→ 放行
    exp_title = getattr(paper, "title", None)
    doi = getattr(paper, "doi", None)
    if not exp_title and not doi:
        return None                              # 无任何可比对锚点 → 放行(不误杀)
    _title = (str(exp_title)[:200] if exp_title else None)

    # ── QC 依赖守卫(fail-closed;总指挥 item3):本条已【需过门】(非豁免源 或 route-B force),但
    #    QC 关键依赖缺失——tools.qc_content_match 不可导入(m is None)或 pypdf 抽不出正文
    #    (_pdf_reader() is None)——则 QC 无从核验"是不是这篇"。旧行为在此静默返回 None(放行)=
    #    错论文假阳回归;现改为**绝不静默**:强告警 + 记结构化事件,并按 cfg.content_qc_require_deps
    #    决定拒收(默认 fail-closed,error=content-qc-deps-missing、不落盘)或降级放行·打标 qc_uncertain。
    #    (rapidfuzz 缺失有 difflib 兜底、QC 仍可用 → 不在此拦,仅由 _qc_warn_degraded_backend 记软告警。)
    m = _qc_matchers()
    if m is None or _pdf_reader() is None:
        dep = "tools.qc_content_match(151模块)" if m is None else "pypdf"
        require = getattr(cfg, "content_qc_require_deps", True)
        _safe_warn(log, "content-qc 关键依赖缺失(%s)但本条需过门 source=%s doi=%s → %s;"
                        "装齐依赖:pip install fulltext_fetcher[qc]。",
                   dep, source, doi,
                   "拒收(fail-closed,不落盘)" if require else "降级放行·打标 qc_uncertain")
        _emit_event(events, "content_qc",
                    verdict=("deps-missing" if require else "uncertain"),
                    source=source, doi=doi, title=_title, score=None,
                    reason=f"qc-deps-missing({dep});{'fail-closed' if require else 'degraded-pass'}")
        if require:
            return f"content-qc-deps-missing({dep})"
        return None
    _qc_warn_degraded_backend(m, log)            # rapidfuzz→difflib 兜底:记一次软告警(不 fail-closed)
    non_article = getattr(cfg, "content_qc_non_article", True)
    hard_reject = getattr(cfg, "content_qc_non_article_hard_reject", False)
    try:
        meta_title, text = _extract_pdf_text_meta(data)
        page_count = _pdf_page_count(data) if non_article else None
        verdict, score, reason = _content_qc_verdict(
            url, meta_title, text, exp_title, doi, m,
            source=source, page_count=page_count,
            non_article=non_article, hard_reject=hard_reject)
    except Exception as e:  # noqa: BLE001 - 门绝不能让主流程崩;任何异常一律放行
        _safe_log(log, "content-qc 异常(放行) source=%s: %s", source, e)
        return None

    if verdict == "mismatch":
        _safe_log(log, "content-qc 判失败(疑似错论文) source=%s doi=%s score=%.1f: %s",
                  source, doi, score, reason)
        _emit_event(events, "content_qc", verdict="mismatch", source=source, doi=doi,
                    title=_title, score=round(float(score), 1), reason=reason)
        return f"content-mismatch(score={score:.1f};{reason})"
    if verdict == "uncertain":
        _safe_log(log, "content-qc 存疑放行·标记 qc_uncertain source=%s doi=%s score=%s: %s",
                  source, doi, (round(float(score), 1) if score >= 0 else "n/a"), reason)
        _emit_event(events, "content_qc", verdict="uncertain", source=source, doi=doi,
                    title=_title, score=(round(float(score), 1) if score >= 0 else None),
                    reason=reason)
    return None


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
    events: Any = None,
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
        # 内容 QC 门(P0):非 DOI-keyed 来源记 success 前核对"是不是这篇";高置信错论文(标题不符+第二信号)→ 判失败不落盘。
        qc = _content_qc_gate(data, paper, getattr(candidate, "source", ""),
                              getattr(candidate, "url", ""), cfg, log, events)
        if qc:
            return None, len(data), qc
        return _save(data, paper, pdf_dir, fallback_name, cfg), len(data), None

    # 非 PDF:若像 HTML 落地页,解析内嵌 PDF 链接再走一层
    if allow_landing and _looks_html(ct, data):
        html = data.decode("utf-8", "replace")
        for purl in extract_pdf_links(html, candidate.url)[:4]:
            if purl == candidate.url:
                continue
            sub = PdfCandidate(purl, candidate.source + "+landing", "pdf",
                               candidate.version, candidate.license, candidate.confidence)
            p, b, _ = _download_pdf_core(sub, paper, pdf_dir, client, cfg, log,
                                         fallback_name, allow_landing=False, headers=headers,
                                         events=events)
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


def _static_pdf_fallbacks(doi, article_url):
    """DOI 构造的出版商 PDF 直链(``publisher_direct.build_static_candidates``),仅保留与文章页
    【同 host】的,作为浏览器内『方法A』页内抽链失败时的直链兜底(-152:RSC articlepdf 文章页常不
    暴露直链)。缺 doi / 解析不出前缀 / 无同域候选 → []。绝不抛。
    """
    if not doi:
        return []
    try:
        from .sources.publisher_direct import build_static_candidates
    except Exception:  # noqa: BLE001 - 导入异常(极端环境)→ 无兜底
        return []
    try:
        host = (urlsplit(str(article_url)).hostname or "").lower()
        out = []
        for c in build_static_candidates(doi):
            cu = getattr(c, "url", "") or ""
            ch = (urlsplit(cu).hostname or "").lower()
            if cu and (not host or ch == host):
                out.append(cu)
        return out
    except Exception:  # noqa: BLE001 - 构造异常绝不外抛
        return []


def _route_b_injection_plan_for(cfg, url):
    """A5:据 cfg(机构订阅字段)+ 目标 URL 构造 route-B 注入计划(纯数据、离线)。

    命中机构白名单(``needs_institution_access`` 同口径)时返回 ``RouteBInjectionPlan``,供
    ``render_download_pdf_bytes(injection_plan=)`` 在浏览器会话内注入机构 Cookie / EZproxy 改写;
    无凭据 / host 未命中 / 缺 institutional 包 → ``None``(零副作用,与未启用逐字节一致)。
    """
    if not getattr(cfg, "institutional", False):
        return None
    try:
        from .institutional.route_b_bridge import plan_route_b_injection_from_config
    except ImportError:
        return None
    try:
        return plan_route_b_injection_from_config(cfg, url)
    except Exception:  # noqa: BLE001 - 注入计划构造异常绝不阻断 route-B 主路径
        return None


def _browser_capture_fallback(
    candidate, paper, pdf_dir, cfg, log, fallback_name,
    *, events=None, _render_fn=None,
):
    """route-B 兜底(-157):『需浏览器抓字节』的出版商(JA3 绑定型强 CF 站 RSC/ScienceDirect/Wiley/ACS,
    以及过盾后 PDF 走跨域 CDN attachment/inline-viewer 的 MDPI 等)——浏览器内经 CDP / 页内 fetch 直下
    PDF 字节(破 curl_cffi 回放 403 与 Akamai bm-verify)。

    触发门(满足其一):显式 ``cfg.browser_capture`` / ``FTF_BROWSER_CAPTURE=1``,或【默认兜底能力】
    ``cfg.route_b_auto_fallback``(默认 True);且 URL host 须属 ``_needs_browser_capture_host``。
    缺 nodriver / 无显示 / 校验不过 → None(优雅 no-op);普通 OA 站不在 host 集内绝不多走浏览器(护栏③)。
    ``_render_fn`` 供 selftest 注入,生产勿传。

    传给 ``render_download_pdf_bytes`` 两项 route-B 生产参数(与 -152 口径对齐):
      · ``pdf_url_fallbacks``:DOI 构造的同域 PDF 直链兜底(方法A 页内抽链失败时用);
      · ``lock_path``:单头串行护栏跨进程锁(``<out_dir>/.route_b.lock``,全组共一机单头浏览器)。

    **落盘前强制过内容 QC 门**(总指挥 P0 item1):route-B 抓到的字节与其它兜底一样,落盘前必过
    ``_content_qc_gate``(同 ``_download_pdf_core``);判 mismatch(疑似错论文 / 非正文版式)→ 不落盘、
    返回 None(交由 attempts.jsonl 的 content_qc 事件审计)。否则 route-B 会绕过 QC 重造系统性假阳。
    """
    url = getattr(candidate, "url", "") or ""
    if not _needs_browser_capture_host(url):
        return None
    if not (_browser_capture_enabled(cfg) or _route_b_auto_fallback_enabled(cfg)):
        return None
    if _is_shadow_library(url) and not getattr(cfg, "enable_scihub", False):
        return None
    try:
        from .render_fetch import render_download_pdf_bytes
    except ImportError:
        return None
    render = _render_fn or render_download_pdf_bytes
    headless = bool(getattr(cfg, "browser_pdf_headless", False))
    timeout = float(getattr(cfg, "timeout", 30.0) or 30.0)
    pdf_url_fallbacks = _static_pdf_fallbacks(getattr(paper, "doi", None), url)
    out_dir = getattr(cfg, "out_dir", None) or "out"
    lock_path = os.path.join(out_dir, ".route_b.lock")
    # A5(路线B 断线补齐):命中机构白名单时构造注入计划(机构 Cookie + EZproxy 改写),随 render 在
    # 【同一 nodriver 会话】内注入(与 B1 同 JA3),让 RSC/ACS/Wiley/ScienceDirect 等 JA3 绑定强 CF 站
    # 在 route-B 上也带机构会话取全文。无凭据 / host 未命中白名单 → None,与未启用逐字节一致(零副作用)。
    injection_plan = _route_b_injection_plan_for(cfg, url)
    try:
        res = render(url, timeout=timeout, min_interval=0.0, headless=headless,
                     pdf_url_fallbacks=pdf_url_fallbacks, lock_path=lock_path,
                     injection_plan=injection_plan)
    except Exception as e:  # noqa: BLE001
        log.info("browser-capture 抓字节异常(忽略) %s: %s", url, e)
        return None
    if not isinstance(res, dict):
        return None
    data = res.get("pdf_bytes")
    if not data or not looks_like_pdf(data):
        return None
    if len(data) < getattr(cfg, "min_pdf_bytes", 1024):
        return None
    defect = pdf_defect(data, deep=getattr(cfg, "pdf_verify_deep", False))
    if defect:
        return None
    # P0 item1:落盘前【强制】过内容 QC(force=True 越过 DOI-keyed 源豁免:route-B 经浏览器导航,
    # RSC/ACS 等 DOI-keyed 源亦易落 SI / 质询插页);mismatch → 不落盘
    qc = _content_qc_gate(data, paper, getattr(candidate, "source", ""), url, cfg, log, events, force=True)
    if qc:
        log.info("browser-capture 内容 QC 判失败,不落盘 %s: %s", url, qc)
        return None
    return _save(data, paper, pdf_dir, fallback_name, cfg), len(data), None


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

    # Akamai 软验证需【有头】真 Chrome(默认有头);尊重全局 FTF_HEADLESS 覆盖;默认有头靠"窗口移出屏幕"不弹窗(-157)。
    try:
        from .render_fetch import _headless_env_override as _hov
        from .render_fetch import _offscreen_args as _off
        _env_hl = _hov()
    except Exception:  # noqa: BLE001 - 取全局无头覆盖失败 → 退回 cfg 默认
        _env_hl = None

        def _off(_hl: bool) -> list:  # 导入失败兜底:不加移屏参数
            return []
    headless = _env_hl if _env_hl is not None else bool(getattr(cfg, "browser_pdf_headless", False))
    wait = float(getattr(cfg, "browser_pdf_wait", 13.0) or 0.0)   # 过 Akamai/渲染等待
    timeout = float(getattr(cfg, "timeout", 30.0) or 30.0)
    dl = tempfile.mkdtemp(prefix="ftf_pdf_")

    async def _go() -> Optional[bytes]:
        browser = await nd.start(headless=headless, browser_args=[
            "--lang=en-US", "--disable-blink-features=AutomationControlled",
            "--window-size=1600,1000", "--no-first-run", "--no-default-browser-check",
            *_off(headless)])
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


def _browser_pdf_download(candidate, paper, pdf_dir, cfg, log, fallback_name, events=None):
    """(可选、默认关)有头真浏览器过 Akamai/JS 软验证并【经浏览器下载】PDF —— 专治 MDPI/金色 OA。

    需 ``cfg.browser_pdf_download=True`` 且有真实显示环境;缺 nodriver / 无显示 / 校验不过 → None。
    默认关:有头浏览器重(~15–25s/篇)、需显示,不进默认/CI 路径(与 render_fallback 同哲学)。

    **落盘前强制过内容 QC 门**(总指挥 P0 item1):与 route-B browser-capture 同,浏览器下载的 PDF
    落盘前必过 ``_content_qc_gate``;判 mismatch → 不落盘、返回 None,避免绕过 QC 重造假阳。
    """
    if not getattr(cfg, "browser_pdf_download", False):
        return None
    url = getattr(candidate, "url", "")
    if _is_shadow_library(url) and not getattr(cfg, "enable_scihub", False):
        return None                               # 合规硬守卫:影子库默认拒绝(浏览器路径亦覆盖)
    data = _nodriver_fetch_pdf_bytes(url, cfg, log)
    if not data or not looks_like_pdf(data):
        return None
    if len(data) < cfg.min_pdf_bytes:
        return None
    if pdf_defect(data, deep=getattr(cfg, "pdf_verify_deep", False)):
        return None
    # P0 item1:落盘前【强制】过内容 QC(force=True 越过 DOI-keyed 源豁免);mismatch → 不落盘
    qc = _content_qc_gate(data, paper, getattr(candidate, "source", ""), url, cfg, log, events, force=True)
    if qc:
        log.info("browser-pdf 内容 QC 判失败,不落盘 %s: %s", url, qc)
        return None
    return _save(data, paper, pdf_dir, fallback_name, cfg), len(data), None


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
      ②b 需浏览器抓字节的强 CF/CDN 站(RSC/ScienceDirect/Wiley/ACS):FlareSolverr 解质询后 curl_cffi
         回放仍 403 时,走浏览器内直下 PDF 字节(``_browser_capture_fallback``→ ``render_download_pdf_bytes``);
      ③ curl_cffi impersonate=chrome 重取(绕 TLS/UA 指纹拦截:MDPI/金色OA 等;缺库自动跳过);
      ④ 出版商适配器(``publisher_adapter``,按 DOI 前缀模板/内容协商/Crossref);
      ⑤ 浏览器渲染兜底(``render_fetch``,可选、默认关、仅 OA);
      ⑤b route-B 默认兜底(-157):标准 OA 源全 miss 后,对『需浏览器抓字节』的出版商落地页
         (``_needs_browser_capture_host``:JA3 强 CF 站 ∪ MDPI 等跨域 CDN attachment/inline-viewer)调
         ``render_download_pdf_bytes`` 浏览器内直下字节。默认启用(``route_b_auto_fallback``,缺 nodriver/
         显示环境时优雅 no-op);②b 已试过则去重跳过;普通 OA 站不在 host 集内不多走浏览器(护栏③);
      ⑥ 有头真浏览器过 Akamai/JS 软验证并经 CDP 下载 PDF(``_browser_pdf_download``,可选、默认关)——
         专治 MDPI 等 Akamai Bot Manager 站(bm-verify:HTTP/curl_cffi/headless 均不可过;需 browser_pdf_download=True)。
    无 DOI / 未知出版商 / 各兜底未命中时,原样返回①的核心结果。

    ``events``(可选,EventLog):命中 Cloudflare 质询且 FlareSolverr【已启用】时,记结构化事件
    ``flaresolverr_recovered``(回收成功)/ ``flaresolverr_failed``(启用但未回收)到 attempts.jsonl
    便于统计。缺省 None / FlareSolverr 未启用 → 不记任何 flaresolverr 事件(零副作用,默认行为不变)。
    """
    result = _download_pdf_core(candidate, paper, pdf_dir, client, cfg, log,
                                fallback_name, allow_landing=allow_landing, events=events)
    if result[0] is not None:
        return result

    is_cf = _is_cf_reason(result[2])
    bc_tried = False   # -157:route-B browser-capture 是否已在 ②b(CF 分支)试过 → ⑤b 用它去重

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
        # ②b 需浏览器抓字节的强 CF/CDN 站:cookie 回放仍 403 → 浏览器内直下 PDF 字节(同一 JA3 出口)
        try:
            bc = _browser_capture_fallback(candidate, paper, pdf_dir, cfg, log, fallback_name,
                                           events=events)
        except Exception as e:  # noqa: BLE001 - 兜底绝不能让主流程崩
            log.info("browser-capture 兜底异常(忽略): %s", e)
            bc = None
        bc_tried = True
        if bc and bc[0]:
            log.info("browser-capture JA3 直下命中: %s", _cf_url)
            _emit_event(events, "browser_capture_recovered", url=_cf_url,
                        source=getattr(candidate, "source", None),
                        bytes=bc[1], reason=result[2])
            return bc
        if _browser_capture_enabled(cfg):
            try:
                from .render_fetch import is_ja3_bound_cf_host as _ja3_host
                if _ja3_host(_cf_url):
                    _emit_event(events, "browser_capture_failed", url=_cf_url,
                                source=getattr(candidate, "source", None), reason=result[2])
            except ImportError:
                pass

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

    # ⑤b route-B 默认兜底(-157,标准 OA 源全 miss 后):对『需浏览器抓字节』的出版商落地页
    #     (MDPI 非 CF/Akamai、RSC/ScienceDirect/Wiley/ACS 等)浏览器内直下 PDF 字节。默认启用
    #     (cfg.route_b_auto_fallback,缺 nodriver/显示时优雅 no-op);普通 OA 站不在 host 集内不受影响
    #     (护栏③);②b(CF 分支)已试过则跳过(bc_tried 去重)。
    if not bc_tried and _needs_browser_capture_host(getattr(candidate, "url", "") or ""):
        try:
            rb = _browser_capture_fallback(candidate, paper, pdf_dir, cfg, log, fallback_name,
                                           events=events)
        except Exception as e:  # noqa: BLE001 - 兜底绝不能让主流程崩
            log.info("route-B 默认兜底异常(忽略): %s", e)
            rb = None
        if rb and rb[0]:
            log.info("route-B 默认兜底(browser-capture)命中: %s", getattr(candidate, "url", "?"))
            _emit_event(events, "browser_capture_recovered", url=getattr(candidate, "url", None),
                        source=getattr(candidate, "source", None), bytes=rb[1], reason=result[2])
            return rb

    # ⑥ 有头真浏览器过 Akamai/JS 软验证并【经浏览器下载】PDF(可选、默认关)——专治 MDPI 等 Akamai 站
    #    (bm-verify:requests/curl_cffi/headless 全过不了,唯有头真 Chrome 过验证后经 CDP 下载可得)。
    try:
        bp = _browser_pdf_download(candidate, paper, pdf_dir, cfg, log, fallback_name, events=events)
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
    route_b_auto_fallback = False   # -157:selftest 默认关 route-B 默认兜底(避免装了 nodriver 的 CI 误起真浏览器)


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

    # ── ⑤e browser-capture JA3 直下:CF 质询 + JA3 host + 启用 → 注入假 render 命中 ──
    class _BCCfg(_SelfCfg):
        browser_capture = True

    class _BCPaper(_SelfPaper):
        doi = "10.1039/d2cc00208f"                     # RSC → build_static_candidates 构 articlepdf

    _bc_kw: dict = {}

    def _fake_bc_render(url, timeout=30.0, **kw):  # noqa: ARG001 - 契约签名
        _bc_kw.clear()
        _bc_kw.update(kw)
        return {"available": True, "pdf_bytes": good, "size": len(good), "note": "ok"}

    # route-B 落盘前强制过内容 QC(P0 item1),故这些用例控制 _extract_pdf_text_meta 以确定 QC 判定。
    _saved_extract_bc = _dl._extract_pdf_text_meta
    try:
        # 正文含期望 DOI → 强制 QC 判 match(expected-doi-present)→ 落盘;并验证直链兜底/锁路径已注入。
        # 用 _dl.* 限定调用(与 ⑦ 一致),确保 patched _extract_pdf_text_meta 被 QC 链路取用(规避 -m 双模块坑)。
        _dl._extract_pdf_text_meta = lambda data, *a, **k: (None, "body text doi 10.1039/d2cc00208f here")
        with tempfile.TemporaryDirectory() as d:
            class _BCCfgOut(_BCCfg):
                out_dir = d
            bcp, bcb, bcerr = _dl._browser_capture_fallback(
                _SelfCand("https://pubs.rsc.org/en/content/articlepdf/2022/cc/d2cc00208f"),
                _BCPaper(), d, _BCCfgOut(), log, "bc", _render_fn=_fake_bc_render)
            assert bcp and bcerr is None and bcb == len(good), (bcp, bcb, bcerr)
            assert os.path.exists(bcp), bcp
            # -152:方法A 直链兜底 = publisher_direct 构造的【同 host】RSC articlepdf 直链
            assert "https://pubs.rsc.org/en/content/articlepdf/2022/cc/d2cc00208f" \
                in _bc_kw.get("pdf_url_fallbacks", []), _bc_kw
            # 单头串行护栏:锁路径落在 out_dir 下的 .route_b.lock
            assert _bc_kw.get("lock_path") == os.path.join(d, ".route_b.lock"), _bc_kw
            # A5(路线B 断线补齐):非机构 cfg → 不构造注入计划(injection_plan=None,零副作用)
            assert _bc_kw.get("injection_plan") is None, _bc_kw

        # A5 接线:机构 cfg + host 命中白名单 → render 收到非空 injection_plan(Cookie 就位、宿主正确);
        #          未命中白名单 → None(route-A/route-B 同门)。仅验 cfg→plan 是否随 render 传入,不发真下载。
        class _BCInstCfg(_BCCfg):
            institutional = True
            institution_cookie = "ezproxy=SELFTESTTOK; sid=xyz"
            institution_domains = ["rsc.org"]
            ezproxy_prefix = "https://login.ezproxy.test.edu/login?url="

        with tempfile.TemporaryDirectory() as d:
            _dl._browser_capture_fallback(
                _SelfCand("https://pubs.rsc.org/en/content/articlepdf/2022/cc/d2cc00208f"),
                _BCPaper(), d, _BCInstCfg(), log, "bc_inst", _render_fn=_fake_bc_render)
            _ip = _bc_kw.get("injection_plan")
            assert _ip is not None and _ip.cookie_count() >= 1, _bc_kw
            assert _ip.rewrite_target_host == "pubs.rsc.org", _ip
            assert _ip.ezproxy_prefix == "https://login.ezproxy.test.edu/login?url=", _ip

        class _BCInstMissCfg(_BCInstCfg):
            institution_domains = ["elsevier.com"]        # host 未命中 → 不注入

        with tempfile.TemporaryDirectory() as d:
            _dl._browser_capture_fallback(
                _SelfCand("https://pubs.rsc.org/en/content/articlepdf/2022/cc/d2cc00208f"),
                _BCPaper(), d, _BCInstMissCfg(), log, "bc_inst_miss", _render_fn=_fake_bc_render)
            assert _bc_kw.get("injection_plan") is None, _bc_kw

        # 无 DOI 的 paper → 无直链兜底(pdf_url_fallbacks 为空);抽不出正文(扫描)→ QC uncertain 放行落盘
        _dl._extract_pdf_text_meta = lambda data, *a, **k: (None, "")
        with tempfile.TemporaryDirectory() as d:
            bcp2, _b2, be2 = _dl._browser_capture_fallback(
                _SelfCand("https://pubs.rsc.org/en/content/articlepdf/2022/cc/d2cc00208f"),
                _SelfPaper(), d, _BCCfg(), log, "bcnodoi", _render_fn=_fake_bc_render)
            assert bcp2 and be2 is None, (bcp2, be2)
            assert _bc_kw.get("pdf_url_fallbacks") == [], _bc_kw

        # P0 item1:route-B 落盘前【强制】过 QC(force 越过 DOI-keyed 源豁免)——正文明显他题 + 跨社 DOI
        #           → mismatch,不落盘、记 content_qc 事件。仅在 QC 匹配原语可用(pypdf+rapidfuzz)时断言。
        if _dl._qc_matchers() is not None:
            _dl._extract_pdf_text_meta = lambda data, *a, **k: (
                "A totally different dermatology study",
                "Journal of the American Academy of Dermatology 10.1016/j.jaad.2019.01.001")
            with tempfile.TemporaryDirectory() as d:
                before = set(os.listdir(d))
                ev_bcqc = _Events()
                bcq = _dl._browser_capture_fallback(
                    _SelfCand("https://pubs.rsc.org/en/content/articlepdf/2022/cc/d2cc00208f"),
                    _BCPaper(), d, _BCCfg(), log, "bcqc", events=ev_bcqc, _render_fn=_fake_bc_render)
                assert bcq is None, bcq                                  # 强制 QC mismatch → 不落盘
                assert set(os.listdir(d)) == before, "route-B QC mismatch 不应落盘"
                assert any(n == "content_qc" and f.get("verdict") == "mismatch"
                           for (n, f) in ev_bcqc.rec), ev_bcqc.rec

            # 控制:content_qc 总开关关 → 强制 QC 亦整体回退 → 即便他题也落盘(证 force 不越过总开关)
            class _BCCfgQCOff(_BCCfg):
                content_qc = False

            with tempfile.TemporaryDirectory() as d:
                bcoff = _dl._browser_capture_fallback(
                    _SelfCand("https://pubs.rsc.org/en/content/articlepdf/2022/cc/d2cc00208f"),
                    _BCPaper(), d, _BCCfgQCOff(), log, "bcoff", _render_fn=_fake_bc_render)
                assert bcoff and bcoff[0], bcoff
    finally:
        _dl._extract_pdf_text_meta = _saved_extract_bc

    # ── ⑤f route-B 落盘出口 QC 硬护栏(P0,总指挥/-147):fake-browser-bytes 离线证据 ──
    #    注入假字节 + 假抽取,断言【两个 route-B 落盘出口(browser-capture / browser-pdf)】对四类坏样本
    #    全部拒收、真正文放行。这是活体冒烟【证不了】的可重跑离线证据:每个 _save() 出口都被 QC 卡住。
    if _dl._qc_matchers() is not None:
        _RSC_URL = "https://pubs.rsc.org/en/content/articlepdf/2022/cc/d2cc00208f"

        class _BCHardReject(_BCCfg):                 # 回收波口径:非正文硬拒(SI/目录/poster → mismatch)
            content_qc_non_article_hard_reject = True

        # 四类 fixture:(名, 抽取出的 (meta_title, text), 期望是否落盘)。DOI 均为 _BCPaper.doi=10.1039/d2cc00208f
        _real = ("Selftest Article", "Abstract. Introduction. Results and discussion. "
                 "doi 10.1039/d2cc00208f. Full body text of the article.")
        _si = ("Supporting Information", "S-1. Supporting Information for 10.1039/d2cc00208f. "
               "Additional characterization data, NMR spectra and figures.")
        _wrongtitle = ("A totally different dermatology study",
                       "Journal of the American Academy of Dermatology 10.1016/j.jaad.2019.01.001")
        _toc = ("Contents", "Table of Contents. Index to Volume 12. 10.1039/d2cc00208f")
        _saved_extract_fb = _dl._extract_pdf_text_meta
        _saved_pc_fb = _dl._pdf_page_count
        try:
            _dl._pdf_page_count = lambda data: 2      # 目录页门⑤C 需页数<=3
            # ── 出口1:_browser_capture_fallback(注入 _render_fn 返回字节)──
            for _name, (_mt, _tx), _expect_save in (
                    ("real", _real, True), ("si", _si, False),
                    ("wrongtitle", _wrongtitle, False), ("toc", _toc, False)):
                _dl._extract_pdf_text_meta = (lambda mt, tx: (lambda data, *a, **k: (mt, tx)))(_mt, _tx)
                with tempfile.TemporaryDirectory() as d:
                    before = set(os.listdir(d))
                    r = _dl._browser_capture_fallback(
                        _SelfCand(_RSC_URL), _BCPaper(), d, _BCHardReject(), log, "fb_" + _name,
                        _render_fn=_fake_bc_render)
                    if _expect_save:
                        assert r and r[0] and os.path.exists(r[0]), (_name, r)
                    else:
                        assert r is None and set(os.listdir(d)) == before, (_name, r, "坏样本不应落盘")
            # 假(非 %PDF)字节:在 QC 之前就被 looks_like_pdf 拒(_render_fn 返回 HTML)
            with tempfile.TemporaryDirectory() as d:
                before = set(os.listdir(d))
                r = _dl._browser_capture_fallback(
                    _SelfCand(_RSC_URL), _BCPaper(), d, _BCHardReject(), log, "fb_fake",
                    _render_fn=lambda *a, **k: {"available": True, "pdf_bytes": b"<html>not a pdf</html>"})
                assert r is None and set(os.listdir(d)) == before, ("fake-bytes", r)

            # ── 出口2:_browser_pdf_download(monkeypatch _nodriver_fetch_pdf_bytes 返回真 %PDF 字节)──
            class _BPCfg(_BCHardReject):
                browser_pdf_download = True

            _saved_fetch = _dl._nodriver_fetch_pdf_bytes
            try:
                _dl._nodriver_fetch_pdf_bytes = lambda url, cfg, log: good   # 真 %PDF,交由 QC 判
                for _name, (_mt, _tx), _expect_save in (
                        ("real", _real, True), ("si", _si, False), ("wrongtitle", _wrongtitle, False)):
                    _dl._extract_pdf_text_meta = (lambda mt, tx: (lambda data, *a, **k: (mt, tx)))(_mt, _tx)
                    with tempfile.TemporaryDirectory() as d:
                        before = set(os.listdir(d))
                        r = _dl._browser_pdf_download(_SelfCand("https://www.mdpi.com/x/pdf"),
                                                      _BCPaper(), d, _BPCfg(), log, "bp_" + _name)
                        if _expect_save:
                            assert r and r[0] and os.path.exists(r[0]), (_name, r)
                        else:
                            assert r is None and set(os.listdir(d)) == before, (_name, r, "browser-pdf 坏样本不应落盘")
            finally:
                _dl._nodriver_fetch_pdf_bytes = _saved_fetch
        finally:
            _dl._extract_pdf_text_meta = _saved_extract_fb
            _dl._pdf_page_count = _saved_pc_fb

    assert _browser_capture_enabled(_SelfCfg()) is False
    # 未显式启用 browser_capture + 默认兜底关(_SelfCfg.route_b_auto_fallback=False)→ no-op(旧 gated 语义)
    assert _browser_capture_fallback(
        _SelfCand("https://pubs.rsc.org/x"), _SelfPaper(), ".", _SelfCfg(), log,
        "bc0", _render_fn=_fake_bc_render) is None
    # -157:MDPI 纳入 capture 集(_needs_browser_capture_host)→ 显式 browser_capture 启用时走 route-B。
    #        无 DOI + 空抽取 → QC uncertain 放行;落 tempdir 勿污染仓库根,专验 host 集扩展生效。
    _saved_extract_mdpi = _dl._extract_pdf_text_meta
    _dl._extract_pdf_text_meta = lambda data, *a, **k: (None, "")
    try:
        with tempfile.TemporaryDirectory() as _d_mdpi:
            _bc_mdpi = _browser_capture_fallback(
                _SelfCand("https://www.mdpi.com/x"), _SelfPaper(), _d_mdpi, _BCCfg(), log,
                "bc1", _render_fn=_fake_bc_render)
            assert _bc_mdpi and _bc_mdpi[0] and os.path.exists(_bc_mdpi[0]), _bc_mdpi
    finally:
        _dl._extract_pdf_text_meta = _saved_extract_mdpi

    _g = globals()
    _saved_bc = _g["_browser_capture_fallback"]
    try:
        with tempfile.TemporaryDirectory() as d:
            def _mock_bc(*a, **k):  # noqa: ARG001 - 契约签名
                p = os.path.join(d, "mock.pdf")
                with open(p, "wb") as fh:
                    fh.write(good)
                return p, len(good), None

            _g["_browser_capture_fallback"] = _mock_bc
            ev_bc = _Events()
            pr_bc, _, _ = download_pdf(
                _SelfCand("https://pubs.rsc.org/en/content/articlepdf/2022/cc/d2cc00208f"),
                _SelfPaper(), d, _CFClient(), _BCCfg(), log, "bc2", events=ev_bc)
            assert pr_bc and "browser_capture_recovered" in [e[0] for e in ev_bc.rec], (pr_bc, ev_bc.rec)
            _g["_browser_capture_fallback"] = lambda *a, **k: None
            ev_bc2 = _Events()
            pr_bc2, _, err_bc2 = download_pdf(
                _SelfCand("https://pubs.rsc.org/en/content/articlepdf/2022/cc/d2cc00208f"),
                _SelfPaper(), d, _CFClient(), _BCCfg(), log, "bc3", events=ev_bc2)
            assert pr_bc2 is None and _is_cf_reason(err_bc2), (pr_bc2, err_bc2)
            assert "browser_capture_failed" in [e[0] for e in ev_bc2.rec], ev_bc2.rec
    finally:
        _g["_browser_capture_fallback"] = _saved_bc

    # ── route-B 默认兜底能力(-157):host 集判定 + 默认启用 + download_pdf ⑤b 接线 ──
    assert _needs_browser_capture_host("https://www.mdpi.com/article/1/pdf")            # MDPI 纳入
    assert _needs_browser_capture_host("https://pubs.rsc.org/en/content/articlepdf/x")  # JA3 集(RSC)
    assert _needs_browser_capture_host("https://www.sciencedirect.com/science/article/pii/X")
    assert not _needs_browser_capture_host("https://example.org/a/pdf")                 # 普通 OA 站不在集内(护栏③)
    assert not _needs_browser_capture_host("")

    # 默认兜底:未开 browser_capture,仅 route_b_auto_fallback=True(生产 config 无此属性时 getattr 亦默认 True)
    #          → 对 capture-host(MDPI)走;显式关(_SelfCfg,False)→ no-op。用空抽取使 QC uncertain 放行。
    class _AutoCfg(_SelfCfg):
        route_b_auto_fallback = True

    _saved_extract_auto = _dl._extract_pdf_text_meta
    _dl._extract_pdf_text_meta = lambda data, *a, **k: (None, "")
    try:
        with tempfile.TemporaryDirectory() as _da:
            _bc_auto = _browser_capture_fallback(
                _SelfCand("https://www.mdpi.com/x"), _SelfPaper(), _da, _AutoCfg(), log,
                "auto_mdpi", _render_fn=_fake_bc_render)
            assert _bc_auto and _bc_auto[0] and os.path.exists(_bc_auto[0]), _bc_auto   # 默认兜底命中
        assert _browser_capture_fallback(                              # 默认兜底关 → 回退旧 gated no-op
            _SelfCand("https://www.mdpi.com/x"), _SelfPaper(), ".", _SelfCfg(), log,
            "auto_off", _render_fn=_fake_bc_render) is None
    finally:
        _dl._extract_pdf_text_meta = _saved_extract_auto

    # download_pdf 默认路径:非 CF 的 MDPI(Akamai)标准源全 miss 后 → ⑤b 兜底 browser-capture,记 recovered;
    #                       普通 OA 站(example.org)不在 host 集 → ⑤b 不触发(护栏③),不记 recovered。
    _saved_core_rb = _g["_download_pdf_core"]
    _saved_bc_rb = _g["_browser_capture_fallback"]
    try:
        _g["_download_pdf_core"] = lambda *a, **k: (None, 0, "no-pdf-found")   # ① 非 CF 失败
        with tempfile.TemporaryDirectory() as d:
            def _mock_bc_rb(cand, *a, **k):  # noqa: ARG001 - 契约签名
                p = os.path.join(d, "rb.pdf")
                with open(p, "wb") as fh:
                    fh.write(good)
                return p, len(good), None

            _g["_browser_capture_fallback"] = _mock_bc_rb
            ev_rb = _Events()
            pr_rb, _, _ = download_pdf(_SelfCand("https://www.mdpi.com/2073-4409/x/pdf"),
                                       _SelfPaper(), d, _SelfClient(good), _SelfCfg(), log,
                                       "rb1", events=ev_rb)
            assert pr_rb and "browser_capture_recovered" in [e[0] for e in ev_rb.rec], (pr_rb, ev_rb.rec)
            ev_no = _Events()
            pr_no, _, _ = download_pdf(_SelfCand("https://example.org/a/pdf"),
                                       _SelfPaper(), d, _SelfClient(good), _SelfCfg(), log,
                                       "rb2", events=ev_no)
            assert "browser_capture_recovered" not in [e[0] for e in ev_no.rec], ev_no.rec
    finally:
        _g["_download_pdf_core"] = _saved_core_rb
        _g["_browser_capture_fallback"] = _saved_bc_rb

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

    # ── ⑦ 内容 QC 门(P0):非 DOI-keyed 来源记 success 前【双门 union】,任一为错即拒 ──
    # 总指挥二次校正:审计逐条交叉验证确认 151 标题法 mismatch 属实(350 条真错论文 URL 法看不到),
    # 故【不能只取交集】。改为 union:① 能抽出正文且标题<50(明确他题)→拒;② URL/正文首部佐证异出版商
    # /异 DOI(即便标题模糊命中,专堵 title 假匹配如 frontiersin/未来年份 DOI)→拒;uncertain/scanned 放行打标。
    # 注:统一走 `_dl.`(真实 fulltext_fetcher.download 模块对象)以便 monkeypatch 与被测函数同处一个
    # 模块命名空间——与 ①b 的 _pdf_reader 打桩同理(`python -m` 下 __main__ 与 _dl 是两份拷贝)。
    _SelfCfgQC = _SelfCfg

    class _CfgQCOff(_SelfCfg):
        content_qc = False

    class _QCCand:
        def __init__(self, source, url):
            self.url, self.source, self.kind = url, source, "pdf"
            self.version = self.license = None
            self.confidence = 1.0

    class _QCPaper:
        # 期望 DOI 用 PLOS(10.1371):QC 出版商映射里"已知",但不在 publisher_adapter 注册表 → 端到端
        # 测试不会触发 publisher 兜底干扰,隔离验证门本身。跨社佐证用 nature(10.1038)。
        doi = "10.1371/journal.pone.0000001"
        arxiv_id = None
        title = "Electrocatalytic CO2 reduction to multicarbon products on copper catalysts"

    _JAAD = "atopic dermatitis a review of skin barrier dysfunction and treatment options in children"
    _MATCH_BODY = "electrocatalytic co2 reduction to multicarbon products on copper catalysts hi"
    _PARTIAL = "multicarbon products electrocatalysis review"   # 与期望标题分≈66(∈[50,70) 中间带)

    # ⑦.0 源分类:非 DOI-keyed(websearch/wayback/browser_search/经 +landing 解析)进门;DOI-keyed 豁免;开关可关
    assert _dl._source_needs_content_qc("websearch", _SelfCfgQC())
    assert _dl._source_needs_content_qc("websearch+landing", _SelfCfgQC())
    assert _dl._source_needs_content_qc("wayback", _SelfCfgQC())
    assert _dl._source_needs_content_qc("browser_search", _SelfCfgQC())
    assert _dl._source_needs_content_qc("unpaywall+landing", _SelfCfgQC())    # 经落地页解析 → 进门
    assert not _dl._source_needs_content_qc("unpaywall", _SelfCfgQC())        # DOI 直取 → 豁免
    assert not _dl._source_needs_content_qc("openalex", _SelfCfgQC())
    assert not _dl._source_needs_content_qc("publisher_oa", _SelfCfgQC())
    assert not _dl._source_needs_content_qc("crossref", _SelfCfgQC())
    assert not _dl._source_needs_content_qc("snapshot", _SelfCfgQC())
    assert not _dl._source_needs_content_qc("websearch", _CfgQCOff())         # 开关关 → 全豁免
    # ⑦.0b 非正文增强(173):publisher_oa:acs-authorchoice 虽 DOI-keyed 也【强制过门】(SI 风险);
    #      置 content_qc_non_article=False → 回退豁免;content_qc=False → 一律豁免
    assert _dl._source_needs_content_qc("publisher_oa:acs-authorchoice", _SelfCfgQC())

    class _CfgNAOff(_SelfCfg):
        content_qc_non_article = False

    assert not _dl._source_needs_content_qc("publisher_oa:acs-authorchoice", _CfgNAOff())  # 增强关→回退豁免
    assert not _dl._source_needs_content_qc("publisher_oa:acs-authorchoice", _CfgQCOff())   # 总开关关→豁免

    _matchers = _dl._qc_matchers()
    if _matchers is not None:
        _V = _dl._content_qc_verdict
        # ⑦.1 verdict 纯逻辑(签名:url, meta_title, text, exp_title, exp_doi, m)——双门 union
        # match:期望 DOI 出现在正文(压过两门)
        v, sc, _r = _V("http://x/a.pdf", None, "see doi 10.1371/journal.pone.0000001 here",
                       "totally unrelated expected title", "10.1371/journal.pone.0000001", _matchers)
        assert v == "match", (v, sc, _r)
        # match:标题强命中 + URL 无冲突
        v, sc, _r = _V("http://x/a.pdf", None, _MATCH_BODY, _QCPaper.title, None, _matchers)
        assert v == "match", (v, sc, _r)
        # 门①:标题明确不符(<50)且能抽出正文、URL 无冲突 → mismatch(拦 URL 法看不到的真错论文)
        v, sc, _r = _V("http://x/paper.pdf", None, _JAAD, _QCPaper.title, _QCPaper.doi, _matchers)
        assert v == "mismatch", (v, sc, _r)
        # 门①·同社错论文(返工关键回归):Springer DOI→另一篇 Springer 论文——URL host 同社
        # (link.springer.com、无嵌入 DOI)、正文 DOI 同社前缀(10.1007)→ 跨社第二信号【不触发】。
        # 旧「交集(标题不符 AND 跨社信号)」在此必放行(错);审计实锤同域错论文 189 条
        # (publisher 61 + repository 128)且 content-mismatch(标题<50)~100% 准 → 并集单信号即硬拒。
        _SPR_DOI = "10.1007/s00542-020-04771-3"
        _SPR_URL = "https://link.springer.com/content/pdf/wrong-paper.pdf"   # 同社 host、无 DOI 嵌入
        _SPR_WRONG = ("microbial electrosynthesis of acetate from carbon dioxide in "
                      "bioelectrochemical systems doi 10.1007/s00253-999-0001-2 springer")
        _conf, _why = _dl._qc_doi_publisher_conflict(_SPR_URL, _SPR_WRONG, _SPR_DOI,
                                                     _matchers["norm_for_doi"])
        assert not _conf, (_conf, _why)   # 先证:同社场景第二信号确实不触发(交集在此必放行)
        v, sc, _r = _V(_SPR_URL, None, _SPR_WRONG, _QCPaper.title, _SPR_DOI, _matchers)
        assert v == "mismatch" and "content-title-mismatch" in _r, (v, sc, _r)  # 并集:标题单信号即拒
        # 门②:标题【强命中】但 URL 嵌异 DOI(nature)→ mismatch(专堵 title 假匹配)
        v, sc, _r = _V("https://repo.example.org/10.1038/s41586-1.pdf", None, _MATCH_BODY,
                       _QCPaper.title, _QCPaper.doi, _matchers)
        assert v == "mismatch", (v, sc, _r)
        # 门②:标题【强命中】但 URL host 跨社(nature.com vs plos)→ mismatch
        v, sc, _r = _V("https://www.nature.com/articles/x.pdf", None, _MATCH_BODY,
                       _QCPaper.title, _QCPaper.doi, _matchers)
        assert v == "mismatch", (v, sc, _r)
        # 门②:即便抽不出正文(scanned),URL 嵌异 DOI 仍 → mismatch(门②独立于内容可读性)
        v, sc, _r = _V("https://repo.org/10.1038/s41586-1.pdf", None, "", _QCPaper.title, _QCPaper.doi, _matchers)
        assert v == "mismatch", (v, sc, _r)
        # uncertain:中间带(≈66)、URL 无冲突 → 放行打标(不误杀)
        v, sc, _r = _V("http://x/a.pdf", None, _PARTIAL, _QCPaper.title, _QCPaper.doi, _matchers)
        assert v == "uncertain", (v, sc, _r)
        # uncertain:抽不出正文、URL 无冲突 → 放行
        v, sc, _r = _V("http://x/a.pdf", None, "", _QCPaper.title, _QCPaper.doi, _matchers)
        assert v == "uncertain", (v, sc, _r)
        # uncertain:无期望标题、URL 无冲突 → 放行
        v, sc, _r = _V("http://x/a.pdf", None, "long extractable readable body text here", "", None, _matchers)
        assert v == "uncertain", (v, sc, _r)
        # 门②(a):期望出版商未知(前缀不在映射)但 URL 嵌异 DOI → 仍 mismatch(异 DOI 即错,不需已知出版商)
        v, sc, _r = _V("https://repo.org/10.1038/s41586-1.pdf", None, "quantum widget synthesis advanced methods",
                       "quantum widget synthesis", "10.9999/unknown.1", _matchers)
        assert v == "mismatch", (v, sc, _r)
        # 门②(b/c):期望出版商未知 + 无 URL DOI + 正文有跨社 DOI → 不冲突(b/c 需两侧已知)→ 标题命中 → match
        v, sc, _r = _V("http://x/a.pdf", None, "quantum widget synthesis 10.1038/s41586-1 methods",
                       "quantum widget synthesis", "10.9999/unknown.1", _matchers)
        assert v == "match", (v, sc, _r)

        # ── ⑦.1c DOI 命中位置权重(149 实锤假阳:参考文献/引用区里的 DOI 不算正文命中)────────────
        _nfd = _matchers["norm_for_doi"]
        _RZ_DOI = "10.1002/aic.690210612"
        _RZ_EN = _nfd(_RZ_DOI)
        _RZ_TITLE = "membrane reactor modeling for catalytic dehydrogenation kinetics"
        # 他篇正文(标题明确不符)+ 期望 DOI 仅出现在参考文献区(引用)——正是 149 aic.690210612 假阳形态
        _RZ_WRONG = ("Photocatalytic hydrogen evolution over cadmium sulfide nanorods under visible light. "
                     "Abstract We study visible-light photocatalysis of water splitting on semiconductor "
                     "nanostructures. Introduction Recent progress in solar fuels has been rapid. "
                     "Results and discussion are presented below. "
                     "References [1] A. Author, AIChE Journal, doi 10.1002/aic.690210612 (1990). [2] more.")
        _RZ_BODY = ("Membrane reactor modeling for catalytic dehydrogenation kinetics. "
                    "Abstract This work presents a reactor model. doi 10.1002/aic.690210612 . "
                    "Introduction background here. References [1] unrelated other work.")
        # helper 直测(确定性,不依赖模糊分):参考文献区 → references;正文区 → body;无参考文献标题 → body;未命中 → None
        assert _dl._qc_doi_hit_zone(_RZ_WRONG, _RZ_EN, _nfd) == "references", "参考文献区 DOI 应判 references"
        assert _dl._qc_doi_hit_zone(_RZ_BODY, _RZ_EN, _nfd) == "body", "正文/摘要区 DOI 应判 body"
        assert _dl._qc_doi_hit_zone("see doi 10.1002/aic.690210612 in the body", _RZ_EN, _nfd) == "body", "无参考文献标题→全文按 body"
        assert _dl._qc_doi_hit_zone("unrelated text without the doi", _RZ_EN, _nfd) is None, "未命中→None"
        # (a) 修复主用例:他篇正文 + 期望 DOI 仅在参考文献区 → 不再强正 → 标题门①判 mismatch(修前:误判 match/expected-doi-present)
        v, sc, _r = _V("http://x/other-paper.pdf", None, _RZ_WRONG, _RZ_TITLE, _RZ_DOI, _matchers)
        assert v == "mismatch" and "content-title-mismatch" in _r, (v, sc, _r)
        # (b) 无回归:同一 DOI 若在【正文/摘要区】(参考文献标题之前)命中 → 仍强正 match
        v, sc, _r = _V("http://x/right-paper.pdf", None, _RZ_BODY, _RZ_TITLE, _RZ_DOI, _matchers)
        assert v == "match" and _r == "expected-doi-present", (v, sc, _r)
        # (c) URL 内含期望 DOI(取件来源、无参考文献噪声)→ 仍强正,即便正文里 DOI 只落在参考文献区
        v, sc, _r = _V("https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/aic.690210612",
                       None, "References doi 10.1002/aic.690210612 (1990).", _RZ_TITLE, _RZ_DOI, _matchers)
        assert v == "match" and _r == "expected-doi-present", (v, sc, _r)
        # (d) 契约锁定(149):参考文献区 DOI + 无期望标题(score=-1,确定性、不依赖模糊分)→ uncertain,
        #     原因【必须】带 +doi-in-references-only 标注(审计依赖此标签区分"DOI 真缺失"vs"仅参考文献命中")
        v, sc, _r = _V("http://x/norefpaper.pdf", None,
                       "some other paper body text here. References doi 10.1002/aic.690210612 (1990).",
                       None, _RZ_DOI, _matchers)
        assert v == "uncertain" and _r == "no-expected-title+doi-in-references-only", (v, sc, _r)
        # (e) 契约锁定(149 审计依赖):参考文献区 DOI + 部分标题重叠(中间带、非他题,复用既有 _PARTIAL≈66)→
        #     uncertain 且 reason【必须】带 +doi-in-references-only(锁死 partial 分支的标签落点,防单行回归)
        v, sc, _r = _V("http://x/partialrefs.pdf", None,
                       _PARTIAL + " References doi " + _QCPaper.doi, _QCPaper.title, _QCPaper.doi, _matchers)
        assert v == "uncertain" and _r == "partial-title-overlap+doi-in-references-only", (v, sc, _r)

        # ── ⑦.1b 门④⑤ 非正文版式(173):即便同社同 DOI(expected-doi-present),SI/citation-report/
        #     poster/目录页 也从 match 降级为 uncertain(默认);hard_reject→mismatch;开关关→回退 match。──
        _EXP_DOI = _QCPaper.doi                                   # 10.1371/journal.pone.0000001(正文内即"同 DOI")
        _NA = lambda url, text, **kw: _V(url, kw.get("meta"), text, _QCPaper.title, _EXP_DOI, _matchers,
                                         source=kw.get("source"), page_count=kw.get("pc"),
                                         non_article=kw.get("na", True), hard_reject=kw.get("hr", False))
        _SI_TEXT = ("S-1. Supporting Information. Additional characterization data and figures. "
                    "doi 10.1371/journal.pone.0000001")
        # 门④ SI 首页 → uncertain(DOI 在正文,强正也被非正文压过)
        v, sc, _r = _NA("https://pubs.acs.org/doi/pdf/x.pdf", _SI_TEXT)
        assert v == "uncertain" and _r == "non-article-si", (v, sc, _r)
        # 门④ SI + hard_reject → mismatch(硬拒)
        v, sc, _r = _NA("https://pubs.acs.org/doi/pdf/x.pdf", _SI_TEXT, hr=True)
        assert v == "mismatch" and _r == "non-article-si", (v, sc, _r)
        # 门④ SI + 非正文增强关(non_article=False)→ 回退:expected-doi-present → match(证明可回退)
        v, sc, _r = _NA("https://pubs.acs.org/doi/pdf/x.pdf", _SI_TEXT, na=False)
        assert v == "match" and _r == "expected-doi-present", (v, sc, _r)
        # 门④ SI · URL 路径 /suppl/ 也命中(无 S-编号亦可,靠 URL 标记)
        v, sc, _r = _NA("https://onlinelibrary.wiley.com/doi/suppl/x_si_001.pdf",
                        "supplementary dataset table s1 10.1371/journal.pone.0000001")
        assert v == "uncertain" and _r == "non-article-si", (v, sc, _r)
        # 门④ ACS-authorchoice 特判:source 命中 + /doi/pdf/ + 正文以 S-编号开头 → SI
        v, sc, _r = _NA("https://pubs.acs.org/doi/pdf/10.x.pdf", _SI_TEXT, source="publisher_oa:acs-authorchoice")
        assert v == "uncertain" and _r == "non-article-si", (v, sc, _r)
        # 正例放行①:真正文(含 Abstract/Introduction)末尾提到 Supporting Information → 不误杀,仍 match
        _REAL_SI = ("Abstract We report electrocatalytic CO2 reduction to multicarbon products. "
                    "Introduction Recent advances ... Supporting Information is available online. "
                    "doi 10.1371/journal.pone.0000001")
        v, sc, _r = _NA("https://pubs.acs.org/doi/pdf/x.pdf", _REAL_SI)
        assert v == "match" and _r == "expected-doi-present", (v, sc, _r)
        # 门⑤A citation-report(首页引证计数词、无正文章节)→ uncertain
        v, sc, _r = _NA("http://x/report.pdf", "Cited by 42. Citation report. 10.1371/journal.pone.0000001")
        assert v == "uncertain" and _r == "non-article-citation-report", (v, sc, _r)
        # 门⑤A 垃圾域 exaly.com(DOI 在 URL)→ uncertain
        v, sc, _r = _NA("https://exaly.com/paper/10.1371/journal.pone.0000001", "arbitrary body text here")
        assert v == "uncertain" and _r == "non-article-citation-report", (v, sc, _r)
        # 门⑤B poster:单页 + poster 关键词 + 无正文 → uncertain(页数从参数传入,不依赖 pypdf)
        v, sc, _r = _NA("http://x/poster.pdf", "POSTER SESSION presented at conference 10.1371/journal.pone.0000001", pc=1)
        assert v == "uncertain" and _r == "non-article-poster", (v, sc, _r)
        # 门⑤B poster 防误杀:同关键词但页数>1(多页正文)→ 不判 poster(此处标题命中弱、DOI 在正文 → 仍 match)
        v, sc, _r = _NA("http://x/multi.pdf", "poster session 10.1371/journal.pone.0000001", pc=8)
        assert v == "match" and _r == "expected-doi-present", (v, sc, _r)
        # 门⑤C 目录页/TOC:目录关键词 + 无正文 + 页数<=3 → uncertain
        v, sc, _r = _NA("http://x/toc.pdf", "Table of Contents Volume 12 Issue 3 10.1371/journal.pone.0000001", pc=2)
        assert v == "uncertain" and _r == "non-article-index-or-toc", (v, sc, _r)
        # 门① 优先于非正文:他题 citation-report(标题<50、DOI 不在正文)→ 仍 mismatch(门①更强,非降级)
        v, sc, _r = _V("http://x/j.pdf", None, _JAAD + " cited by 10 citation report", _QCPaper.title,
                       _QCPaper.doi, _matchers, source="websearch", page_count=1)
        assert v == "mismatch" and "content-title-mismatch" in _r, (v, sc, _r)

        _saved_extract = _dl._extract_pdf_text_meta
        try:
            # ⑦.2 端到端 门①:websearch + 标题明确不符(URL 无冲突)→ content-mismatch、不落盘
            _dl._extract_pdf_text_meta = lambda data, *a, **k: (None, _JAAD)
            with tempfile.TemporaryDirectory() as d:
                before = set(os.listdir(d))
                pqc, nqc, eqc = _dl.download_pdf(_QCCand("websearch", "http://x/ws_wrong.pdf"),
                                                 _QCPaper(), d, _SelfClient(good), _SelfCfgQC(), log, "ws")
                assert pqc is None and eqc and eqc.startswith("content-mismatch("), (pqc, nqc, eqc)
                assert set(os.listdir(d)) == before, "内容标题他题不应落盘"

            # ⑦.2b 端到端 门①·同社错论文:websearch + Springer DOI 拿到另一篇 Springer 论文
            # (URL host 同社 link.springer.com、正文 DOI 同前缀 10.1007 → 跨社信号不触发,旧交集必放行)
            # → 并集凭标题单信号 content-mismatch、不落盘。注:10.1007 在 publisher_adapter 注册表内,
            # 核心拒绝后会走 publisher 兜底 —— 其 content/pdf/{期望DOI}.pdf 模板 URL 天然含期望 DOI
            # (强正门放行属合理:出版商按 DOI serve),故用 _MapClient 让模板 URL 404、仅原候选可取,
            # 逼兜底也拿到同一错文;子候选 source 含 "websearch" marker 同样被门拦 → 兜底不漏错论文。
            class _QCPaperSpr:
                doi = _SPR_DOI
                arxiv_id = None
                title = _QCPaper.title

            _dl._extract_pdf_text_meta = lambda data, *a, **k: (None, _SPR_WRONG)
            _spr_client = _MapClient({_SPR_URL: (good, "application/pdf")},
                                     default=(b"<html>404 not found</html>", "text/html"))
            with tempfile.TemporaryDirectory() as d:
                before = set(os.listdir(d))
                pqs, _ns, eqs = _dl.download_pdf(_QCCand("websearch", _SPR_URL),
                                                 _QCPaperSpr(), d, _spr_client, _SelfCfgQC(), log, "sp")
                assert pqs is None and eqs and eqs.startswith("content-mismatch("), (pqs, _ns, eqs)
                assert "content-title-mismatch" in eqs, eqs   # 确为门①标题单信号拒(非跨社门②)
                assert set(os.listdir(d)) == before, "同社错论文不应落盘(含 publisher 兜底路径)"

            # ⑦.3 端到端 门②:websearch + 标题命中但 URL host 跨社(nature vs plos)→ content-mismatch、不落盘
            _dl._extract_pdf_text_meta = lambda data, *a, **k: (_QCPaper.title, _MATCH_BODY)
            with tempfile.TemporaryDirectory() as d:
                before = set(os.listdir(d))
                pqcx, _nx, eqcx = _dl.download_pdf(
                    _QCCand("websearch", "https://www.nature.com/articles/s41586-1.pdf"),
                    _QCPaper(), d, _SelfClient(good), _SelfCfgQC(), log, "wx")
                assert pqcx is None and eqcx and eqcx.startswith("content-mismatch("), (pqcx, _nx, eqcx)
                assert set(os.listdir(d)) == before, "URL 跨社(title 假匹配)不应落盘"

            # ⑦.4 websearch + 正确论文(标题命中、URL 无冲突)→ 命中,正常落盘
            _dl._extract_pdf_text_meta = lambda data, *a, **k: (_QCPaper.title, _MATCH_BODY)
            with tempfile.TemporaryDirectory() as d:
                pqc2, _n2, eqc2 = _dl.download_pdf(_QCCand("websearch", "http://x/ws_right.pdf"),
                                                   _QCPaper(), d, _SelfClient(good), _SelfCfgQC(), log, "ws2")
                assert pqc2 and eqc2 is None and os.path.exists(pqc2), (pqc2, eqc2)

            # ⑦.5 websearch + 中间带(部分重叠、URL 无冲突)→ uncertain 放行、正常落盘(不误杀)
            _dl._extract_pdf_text_meta = lambda data, *a, **k: (None, _PARTIAL)
            with tempfile.TemporaryDirectory() as d:
                pqc7, _n7, eqc7 = _dl.download_pdf(_QCCand("websearch", "http://x/ws_partial.pdf"),
                                                   _QCPaper(), d, _SelfClient(good), _SelfCfgQC(), log, "wp")
                assert pqc7 and eqc7 is None and os.path.exists(pqc7), (pqc7, eqc7)

            # ⑦.6 websearch + 抽不出正文(扫描/图片、URL 无冲突)→ uncertain 放行(不误杀)
            _dl._extract_pdf_text_meta = lambda data, *a, **k: (None, "")
            with tempfile.TemporaryDirectory() as d:
                pqc3, _n3, eqc3 = _dl.download_pdf(_QCCand("websearch", "http://x/ws_scan.pdf"),
                                                   _QCPaper(), d, _SelfClient(good), _SelfCfgQC(), log, "ws3")
                assert pqc3 and eqc3 is None and os.path.exists(pqc3), (pqc3, eqc3)

            # ⑦.7 DOI-keyed 源(unpaywall)即便标题不符+跨社 DOI → 豁免、照常落盘(避免误杀)
            _dl._extract_pdf_text_meta = lambda data, *a, **k: (
                None, "atopic dermatitis 10.1038/s41586-1 entirely different topic")
            with tempfile.TemporaryDirectory() as d:
                pqc4, _n4, eqc4 = _dl.download_pdf(_QCCand("unpaywall", "http://x/up.pdf"),
                                                   _QCPaper(), d, _SelfClient(good), _SelfCfgQC(), log, "up")
                assert pqc4 and eqc4 is None and os.path.exists(pqc4), (pqc4, eqc4)

            # ⑦.8 开关关(content_qc=False)→ websearch 也豁免、照常落盘(即便双门都会命中)
            _dl._extract_pdf_text_meta = lambda data, *a, **k: (None, _JAAD)
            with tempfile.TemporaryDirectory() as d:
                pqc5, _n5, eqc5 = _dl.download_pdf(
                    _QCCand("websearch", "https://www.nature.com/x.pdf"),
                    _QCPaper(), d, _SelfClient(good), _CfgQCOff(), log, "off")
                assert pqc5 and eqc5 is None and os.path.exists(pqc5), (pqc5, eqc5)

            # ⑦.9 依赖守卫 fail-closed(总指挥 item3):qc_matchers 不可用(缺 pypdf/rapidfuzz/151 模块)
            #      且本条需过门 → 默认 fail-closed 拒收不落盘(绝不静默放行),原因 content-qc-deps-missing、
            #      事件 verdict=deps-missing;仅 content_qc_require_deps=False 才回退降级放行·打标 qc_uncertain。
            class _CfgQCDepsOff(_SelfCfg):
                content_qc_require_deps = False

            _saved_matchers = _dl._qc_matchers
            try:
                _dl._qc_matchers = lambda: None
                _dl._extract_pdf_text_meta = lambda data, *a, **k: (None, _JAAD)
                # 默认(require_deps=True):拒收、不落盘、原因 content-qc-deps-missing、记事件 deps-missing
                with tempfile.TemporaryDirectory() as d:
                    before = set(os.listdir(d))
                    ev6 = _Events()
                    pqc6, _n6, eqc6 = _dl.download_pdf(_QCCand("websearch", "http://x/ws_degrade.pdf"),
                                                       _QCPaper(), d, _SelfClient(good), _SelfCfgQC(), log, "dg", events=ev6)
                    assert pqc6 is None and eqc6 and eqc6.startswith("content-qc-deps-missing("), (pqc6, eqc6)
                    assert set(os.listdir(d)) == before, "缺依赖 fail-closed 不应落盘"
                    _e6 = [f for (n, f) in ev6.rec if n == "content_qc"]
                    assert _e6 and _e6[-1]["verdict"] == "deps-missing", ev6.rec
                # 逃生阀(require_deps=False):降级放行、照常落盘(仍非静默:强告警 + 事件 verdict=uncertain)
                with tempfile.TemporaryDirectory() as d:
                    ev6b = _Events()
                    pqc6b, _n6b, eqc6b = _dl.download_pdf(_QCCand("websearch", "http://x/ws_degrade2.pdf"),
                                                          _QCPaper(), d, _SelfClient(good), _CfgQCDepsOff(), log, "dg2", events=ev6b)
                    assert pqc6b and eqc6b is None and os.path.exists(pqc6b), (pqc6b, eqc6b)
                    _e6b = [f for (n, f) in ev6b.rec if n == "content_qc"]
                    assert _e6b and _e6b[-1]["verdict"] == "uncertain", ev6b.rec
            finally:
                _dl._qc_matchers = _saved_matchers

            # ── ⑦.10 端到端 门④⑤ 非正文(173):默认 uncertain→照常落盘 + 记 content_qc 事件;
            #     hard_reject→content-mismatch 不落盘;acs-authorchoice 强制过门;开关关→回退落盘 ──
            _saved_pc = _dl._pdf_page_count
            try:
                # ⑦.10a SI(websearch)→ uncertain:照常落盘 + content_qc 事件 verdict=uncertain/non-article-si
                _dl._extract_pdf_text_meta = lambda data, *a, **k: (None, _SI_TEXT)
                _dl._pdf_page_count = lambda data: 12
                with tempfile.TemporaryDirectory() as d:
                    ev = _Events()
                    psi, _nsi, esi = _dl.download_pdf(_QCCand("websearch", "https://pubs.acs.org/doi/pdf/x.pdf"),
                                                      _QCPaper(), d, _SelfClient(good), _SelfCfgQC(), log, "si", events=ev)
                    assert psi and esi is None and os.path.exists(psi), (psi, esi)     # uncertain → 照常落盘
                    _e = [f for (n, f) in ev.rec if n == "content_qc"]
                    assert _e and _e[-1]["verdict"] == "uncertain" and _e[-1]["reason"] == "non-article-si", ev.rec

                # ⑦.10b SI + hard_reject cfg → content-mismatch、不落盘
                class _CfgHardReject(_SelfCfg):
                    content_qc_non_article_hard_reject = True

                with tempfile.TemporaryDirectory() as d:
                    before = set(os.listdir(d))
                    phr, _nhr, ehr = _dl.download_pdf(_QCCand("websearch", "https://pubs.acs.org/doi/pdf/x.pdf"),
                                                      _QCPaper(), d, _SelfClient(good), _CfgHardReject(), log, "hr")
                    assert phr is None and ehr and ehr.startswith("content-mismatch(") and "non-article-si" in ehr, (phr, ehr)
                    assert set(os.listdir(d)) == before, "hard_reject 非正文不应落盘"

                # ⑦.10c acs-authorchoice 强制过门(本豁免的 DOI-keyed 源):SI → uncertain 落盘 + 事件
                with tempfile.TemporaryDirectory() as d:
                    ev2 = _Events()
                    pac, _nac, eac = _dl.download_pdf(
                        _QCCand("publisher_oa:acs-authorchoice", "https://pubs.acs.org/doi/pdf/10.x.pdf"),
                        _QCPaper(), d, _SelfClient(good), _SelfCfgQC(), log, "ac", events=ev2)
                    assert pac and eac is None and os.path.exists(pac), (pac, eac)
                    _e2 = [f for (n, f) in ev2.rec if n == "content_qc"]
                    assert _e2 and _e2[-1]["reason"] == "non-article-si", ev2.rec

                # ⑦.10d 目录页 TOC(websearch, 2页)→ uncertain 落盘 + 事件 non-article-index-or-toc
                _dl._extract_pdf_text_meta = lambda data, *a, **k: (
                    None, "Table of Contents Volume 12 Issue 3 10.1371/journal.pone.0000001")
                _dl._pdf_page_count = lambda data: 2
                with tempfile.TemporaryDirectory() as d:
                    ev3 = _Events()
                    ptoc, _nt, etoc = _dl.download_pdf(_QCCand("websearch", "http://x/toc.pdf"),
                                                       _QCPaper(), d, _SelfClient(good), _SelfCfgQC(), log, "toc", events=ev3)
                    assert ptoc and etoc is None and os.path.exists(ptoc), (ptoc, etoc)
                    _e3 = [f for (n, f) in ev3.rec if n == "content_qc"]
                    assert _e3 and _e3[-1]["reason"] == "non-article-index-or-toc", ev3.rec

                # ⑦.10e 非正文增强关(content_qc_non_article=False)→ 回退:SI + DOI 在正文 → match 落盘
                _dl._extract_pdf_text_meta = lambda data, *a, **k: (None, _SI_TEXT)
                with tempfile.TemporaryDirectory() as d:
                    pna, _nna, ena = _dl.download_pdf(_QCCand("websearch", "https://pubs.acs.org/doi/pdf/x.pdf"),
                                                      _QCPaper(), d, _SelfClient(good), _CfgNAOff(), log, "naoff")
                    assert pna and ena is None and os.path.exists(pna), (pna, ena)
            finally:
                _dl._pdf_page_count = _saved_pc
        finally:
            _dl._extract_pdf_text_meta = _saved_extract

    # ── [naming-140] 文件名标准化健壮性:特殊字符 DOI / Windows 非法集 / 控制符 / 保留名 → 合法且可真落盘 ──
    import tempfile as _tf
    _WIN_ILLEGAL = set('<>:"/\\|?*')

    class _NP:                                   # 最小 paper 替身:仅 .doi/.arxiv_id/.title
        def __init__(self, doi=None, arxiv_id=None, title=None):
            self.doi, self.arxiv_id, self.title = doi, arxiv_id, title

    _wiley = "10.1002/1099-0739(200012)14:12<715::AID-RCM4>3.0.CO;2-A"   # 老 Wiley:含 ( ) : < > ;
    _cases = [
        _wiley,
        '10.1/x<y>z:"q|w*e?r',                   # 全 Windows 非法字符集
        "10.2/a\tb\nc",                          # ASCII 控制符
        "CON", "nul", "COM1", "Lpt9",            # Windows 保留设备名
        "10.3/aux.",                             # 结尾点
        "  10.4/spaced  ",                       # 前后空格
    ]
    with _tf.TemporaryDirectory() as _d:
        for _s in _cases:
            _stem = sanitize_filename(_s)
            assert not (_WIN_ILLEGAL & set(_stem)), (_s, _stem)          # 无残留非法字符
            assert _stem == _stem.strip(". "), (_s, _stem)              # 无首尾点/空格(前缀 _ 合法)
            assert _stem.split(".", 1)[0].lower() not in _WIN_RESERVED, (_s, _stem)
            _fn = target_name(_NP(doi=_s), "fb")                        # target_name 真落盘不得抛 [Errno 22]
            assert _fn.endswith(".pdf") and not (_WIN_ILLEGAL & set(_fn)), (_s, _fn)
            with open(os.path.join(_d, _fn), "wb") as _fh:
                _fh.write(b"%PDF-1.4\n%%EOF\n")
    assert sanitize_filename("") == "paper" and sanitize_filename(None) == "paper"
    assert sanitize_filename("....") == "paper"
    assert sanitize_filename("CON") == "_CON" and sanitize_filename("nul.pdf") == "_nul.pdf"
    assert target_name(_NP(doi=_wiley), "fb") == \
        "10.1002_1099-0739_200012_14_12_715_AID-RCM4_3.0.CO_2-A.pdf", target_name(_NP(doi=_wiley), "fb")

    # ── 文件命名模板(主线自定义命名打通)──────────────────────────────────────────
    # 默认 None=DOI 净化名【逐字节不变】(向后兼容硬证);给模板→复用 scholar/naming.build_filename;
    # _save 模板分支按磁盘现存文件去重(_2/_3),默认分支同名覆盖(行为不变)。
    from .config import Config as _CfgT
    from .models import Paper as _PaperT
    _pT = _PaperT(doi="10.1371/journal.pone.0000217", title="Attention Is All You Need",
                  year=2017, authors=["Ashish Vaswani", "Noam Shazeer"])
    _doi_name = "10.1371_journal.pone.0000217.pdf"
    # 向后兼容:cfg=None 与「有 cfg 但 naming_template=None」都必须 == 旧 DOI 净化名
    assert target_name(_pT, "fb") == _doi_name, target_name(_pT, "fb")
    assert target_name(_pT, "fb", _CfgT()) == _doi_name, target_name(_pT, "fb", _CfgT())
    # 模板模式:年_首作者姓_标题(净化/截断同源,不重造)
    _tcfg = _CfgT(naming_template="{year}_{author}_{title}")
    assert target_name(_pT, "fb", _tcfg) == "2017_Vaswani_Attention_Is_All_You_Need.pdf", \
        target_name(_pT, "fb", _tcfg)
    # 自定义模板 + 年作者标题全缺→DOI 兜底(优雅降级,不崩)
    assert target_name(_pT, "fb", _CfgT(naming_template="{author}-{year}")) == "Vaswani-2017.pdf", \
        target_name(_pT, "fb", _CfgT(naming_template="{author}-{year}"))
    assert target_name(_PaperT(doi="10.1/only"), "fb", _tcfg) == "10.1_only.pdf", \
        target_name(_PaperT(doi="10.1/only"), "fb", _tcfg)
    # _save 落盘去重:默认 DOI 分支同名覆盖(单文件);模板分支撞名自动 _2(复用 naming.dedupe_path)
    with _tf.TemporaryDirectory() as _sd:
        _s1 = _save(b"%PDF-1.4\n%%EOF\n", _pT, _sd, "fb")
        _s2 = _save(b"%PDF-1.4\n%%EOF\n", _pT, _sd, "fb")               # 默认:同名覆盖,仍单文件
        assert os.path.basename(_s1) == _doi_name and _s2 == _s1, (_s1, _s2)
        assert len([f for f in os.listdir(_sd) if f.endswith(".pdf")]) == 1, os.listdir(_sd)
    with _tf.TemporaryDirectory() as _sd2:
        _t1 = _save(b"%PDF-1.4\n%%EOF\n", _pT, _sd2, "fb", _tcfg)
        _t2 = _save(b"%PDF-1.4\n%%EOF\n", _pT, _sd2, "fb", _tcfg)       # 模板:撞名 → _2
        assert os.path.basename(_t1) == "2017_Vaswani_Attention_Is_All_You_Need.pdf", _t1
        assert os.path.basename(_t2) == "2017_Vaswani_Attention_Is_All_You_Need_2.pdf", _t2
        assert len([f for f in os.listdir(_sd2) if f.endswith(".pdf")]) == 2, os.listdir(_sd2)

    print("DOWNLOAD_OK")


if __name__ == "__main__":
    _selftest()
