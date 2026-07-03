"""运行配置。所有可调参数集中在此,便于日志驱动地迭代。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# 默认源优先级顺序(直链命中率/速度/稳定性综合排序)。
# 聚合类(直接给 PDF 直链、覆盖广)优先,其后是学科仓储,最后是兜底。
DEFAULT_SOURCE_ORDER: List[str] = [
    "snapshot",         # 本地快照库(若配置 --snapshot-db):零额度/零限速/零 key,命中即省全部在线调用
    "unpaywall",        # 直接给 url_for_pdf,免费,覆盖最广
    "openalex",         # 单条按 DOI 免费,pdf_url 字段
    "publisher_oa",     # 已知 OA 出版商:DOI→PDF 直链纯构造(Frontiers/PLOS/PeerJ/eLife/BMC/MDPI…),便宜高质
    "oa_button",        # oa.works/OpenAccess Button 免费全文 API(官方端点已停用→通常空;可指向自建实例)
    "europe_pmc",       # 生物医学 OA,render PDF 稳定
    "arxiv",            # 预印本直链,命中即高质量
    "biorxiv",          # 10.1101 预印本
    "preprints",        # 化学/材料类预印本:ChemRxiv/Research Square/Preprints.org(DOI 直构或标题经 Crossref)
    "semantic_scholar", # openAccessPdf
    "pmc",              # PMCID → PDF(过渡期)
    "core",             # 需 key,36M+ 全文
    "base",             # BASE:400M+ OA 聚合索引(免 key fcgi 实时检索)
    "crossref",         # link[] TDM,多为兜底
    "doaj",             # 纯 OA 期刊
    "openaire",         # 聚合兜底
    "hal",              # 法国仓储
    "osf",              # OSF 预印本仓储(primary_file 直下)
    "zenodo",           # 数据/附件/部分论文
    "scienceopen",      # ScienceOpen 自托管 OA 落地页(前缀 10.14293)
    "openalex_content", # OpenAlex 官方缓存 PDF(~60M 篇,需 openalex_key;成功下载才计费,
                        # 免费档 $1/天≈100 篇):置于全部免费源之后、websearch 前,真 miss 才花额度
    "websearch",        # 免费搜索引擎(DuckDuckGo/Bing)找作者自存稿/机构库 PDF(兜底、真 miss 才触发)
    "wayback",          # Internet Archive/Wayback 存档 PDF 兜底
    # "browser_search", # 无头隐身浏览器驱动搜索引擎(重、易被限):默认关,--sources ...,browser_search 显式开启
    # "scihub",         # 可选、默认关闭、合规风险,见 --enable-scihub
]


@dataclass
class Config:
    """fulltext_fetcher 的全部运行参数。"""

    # 身份/凭据(均为可选,但强烈建议填真实 email)
    email: str = "anonymous@example.com"
    openalex_key: Optional[str] = None
    s2_key: Optional[str] = None
    core_key: Optional[str] = None

    # 本地快照库(由 python -m fulltext_fetcher.ingest 灌入):配置后零额度/零限速本地查 DOI
    snapshot_db: Optional[str] = None

    # 输出
    out_dir: str = "out"

    # ── 文件命名模板(可选;默认 None = 旧行为逐字节不变:DOI 净化名)──────────────────
    # 默认 None → 主线落盘沿用 download.target_name 的 DOI 净化名(doi.replace('/','_') → sanitize_filename),
    # 与本参数引入前完全一致(向后兼容,零副作用)。设为含占位符的模板串(如 "{year}_{author}_{title}"
    # 或 "{year}_{author}_{title}_{doi}")→ 复用 scholar/naming.build_filename,按 resolve 出的 Paper 元数据
    # (年 / 首作者姓 / 标题 / DOI / venue)渲染标准化、安全、去重后的文件名——净化/截断/去重逻辑与 scholar
    # 子系统同源(不重造):字段缺失优雅降级(折叠空占位分隔符),年 / 作者 / 标题全缺时以 DOI 兜底;落盘时
    # 按磁盘现存文件自动加 _2/_3 去重(模板名撞名概率高于唯一 DOI)。占位符:year/author/title/doi/venue。
    naming_template: Optional[str] = None

    # 并发与网络
    concurrency: int = 4
    timeout: float = 30.0
    max_retries: int = 3
    per_host_interval: float = 0.34  # 每域最小请求间隔(秒),礼貌限速

    # 下载/校验
    min_pdf_bytes: int = 1024
    max_pdf_bytes: int = 80 * 1024 * 1024  # 单文件上限 80MB,防异常大体

    # 内容 QC 门(P0,默认开):对**非 DOI-keyed 来源**(websearch/wayback/browser_search 及经 +landing
    # 解析者)在记 success 前核对"是不是这篇",拦截"下到错论文"的系统性假阳。**双门 union**(总指挥经
    # 审计逐条交叉验证校正:标题法 mismatch 属实、非过判,350 条真错论文 URL 法看不到,故不能只取交集):
    # 记 success 需"内容标题匹配 AND URL-DOI 一致",**任一为错即判失败**:① 能抽出正文且标题分<50(明确
    # 他题)→ error=content-mismatch;② URL/正文首部佐证异出版商或异 DOI(即便标题模糊命中,专堵 title
    # 假匹配如 frontiersin/未来年份 DOI)→ error=content-mismatch;均不落盘。期望 DOI 出现在正文/URL→放行。
    # **uncertain(中间带)/scanned(抽不出正文)/无锚点 → 放行打标 qc_uncertain,绝不误杀 undecidable**。
    # DOI-keyed 源(unpaywall/openalex/publisher_oa/crossref/S2/snapshot…)一律豁免。复用 tools/qc_content_match
    # (pypdf 抽首2页文本+元数据 title × rapidfuzz 模糊)。**缺依赖行为见下方 content_qc_require_deps
    # (默认 fail-closed:需过门却缺 pypdf/模块→拒收不落盘,绝不静默放行)**。置 False→整体回退。
    content_qc: bool = True

    # ── 内容 QC 门·非正文版式增强(P0,默认开;可独立于 content_qc 回退)──────────────────
    # 背景(recover_b4_cf 实锤,见《选型2026-QC并集门增强建议-recover_b4_cf假阳-173.md》):既有并集门
    # (门①标题 + 门②跨社/异 DOI)对"同社同 DOI 却拿到的是 Supporting Information / citation-report /
    # poster / 卷期目录(TOC)"这类【非正文版式】零免疫——首页印着正确标题+DOI,却不是正文 PDF。本增强补一
    # 类"非正文硬信号":命中即【降级为 uncertain】(默认;照常落盘但标 qc_uncertain、不再虚增 match),
    # 靠首页关键词 + 页数/正文长度阈区分,真正文(含末尾 SI 章节)不误杀。置 False → 该增强整体回退,
    # 且 acs-authorchoice 强制过门亦随之关闭。
    content_qc_non_article: bool = True
    # 非正文命中后的判定档:默认 False → uncertain(降级放行、照常落盘打标 qc_uncertain);置 True →
    # mismatch(硬拒不落盘,对齐 173 §六 checklist 的 verdict=mismatch)。仅在 content_qc_non_article 开启时生效。
    content_qc_non_article_hard_reject: bool = False

    # ── 内容 QC 门·依赖守卫 fail-closed(P0,默认开)──────────────────────────────
    # 背景(总指挥 item3):QC 复用 pypdf(抽首2页正文+元数据 title)与 rapidfuzz(标题模糊匹配)。旧行为
    # 是二者缺失即 try/except 静默降级放行 → QC 变"盲判",错论文照记 success = 假阳回归。本守卫改为
    # **fail-closed**:当 content_qc 启用、且本条【需过门】(非 DOI-keyed 源 或 route-B force),但关键
    # 依赖缺失(tools.qc_content_match 不可导入 / pypdf 抽不出正文)时,给强告警并【拒收不落盘】
    # (error=content-qc-deps-missing),绝不静默 PASS。
    # 注:rapidfuzz 缺失有 difflib 兜底、QC 仍可用(仅标题模糊精度略降)→ 只记一次软告警,**不**触发
    # fail-closed。置 False → 回退旧「缺依赖=降级放行·打标 qc_uncertain」(仍非静默:强告警+记事件),
    # 供无 pypdf 环境或需最大召回时用。装齐依赖:pip install fulltext_fetcher[qc]。
    content_qc_require_deps: bool = True

    # 行为开关
    oa_only: bool = False        # 仅尝试开放获取(跳过低置信落地页)
    no_download: bool = False    # 只定位不下载(快速验证源命中)
    resume: bool = True          # 断点续跑:跳过 out_dir 中已成功的输入
    retry_failed: bool = False   # 续跑时也重试"永久失败"(默认只重试超时/5xx 等临时失败)
    enable_scihub: bool = False  # 合规风险,默认关闭
    scihub_mirror: str = "https://sci-hub.se"

    # ── Cloudflare JS 质询求解(FlareSolverr,可选、默认关闭)────────────────────
    # 少数出版商整站用 Cloudflare "Just a moment" JS 质询(如 pubs.rsc.org / RSC,连 OA 文章也拦):
    # 普通 HTTP 与 curl_cffi(TLS 伪装)都过不了,需 JS 求解器。启用后下载遇质询会经自托管
    # FlareSolverr 解出 cf_clearance + UA 再带其重下(详见 flaresolverr.py 的 docker 启动说明)。
    # 默认三项皆关/空 → 下载行为与未启用逐字节一致(遇质询仅记 cloudflare-challenge 原因,不发多余请求)。
    use_flaresolverr: bool = False              # 总开关;或配置下面端点 / 环境变量 FLARESOLVERR_URL 亦启用
    flaresolverr_url: Optional[str] = None      # 端点,如 "http://localhost:8191"(留空→用 env 或默认)
    flaresolverr_timeout_ms: int = 60000        # 浏览器侧解质询最大等待(毫秒)

    # ── 路线B「浏览器内直下 PDF」(可选、默认全关)──────────────────────────────
    # 破 JA3 绑定型强 CF(RSC/ScienceDirect/ACS/Wiley:curl_cffi 回放仍 403)与 Akamai(MDPI):在【同一
    # 浏览器会话】内经 CDP 抓 PDF 字节 / 下载,TLS/JA3 天然一致。三档(``route_b``):
    #   off     :全关(默认,零副作用、零额外依赖);
    #   cf-only :仅对 JA3 绑定型强 CF 站走浏览器内抓字节(``browser_capture``);
    #   all     :再加有头浏览器过 Akamai 经 CDP 下载(``browser_pdf_download``,治 MDPI 等)。
    # **绝不默认 all**。全组共一机单头浏览器,route-B 已内建 concurrency=1 硬护栏(BoundedSemaphore(1) +
    # out/.route_b.lock)与【落盘前强制内容 QC】。需装可选依赖 nodriver + 有头显示环境;缺则优雅 no-op。
    # ``browser_capture`` / ``browser_pdf_download`` 由 ``apply_route_b()`` 据 ``route_b`` 派生(单一真源);
    # 也兼容环境变量 ``FTF_BROWSER_CAPTURE=1`` 单独启用 cf-only 抓字节(见 download._browser_capture_enabled)。
    route_b: str = "off"                        # off | cf-only | all(CLI: --route-b)
    browser_capture: bool = False               # 强 CF 站浏览器内抓字节(由 route_b 派生;env 亦可单独启用)
    browser_pdf_download: bool = False          # 有头浏览器过 Akamai 经 CDP 下载(由 route_b=all 派生)
    browser_pdf_headless: bool = False          # 浏览器是否无头(默认 False=有头:过 CF/Akamai 通过率更高)
    browser_pdf_wait: float = 13.0              # 有头浏览器过验证/渲染等待秒(route_b=all 时生效)

    # ── 机构订阅 / EZproxy 接入(可选,默认全部关闭;对开放 API 正门零影响)──
    # 合规声明:以下选项仅供拥有【合法机构订阅】的用户、对其【有权访问】的内容使用,
    # 用于在已获授权前提下经机构 EZproxy/SSO 正常取用全文;不得用于绕过付费墙或任何访问授权。
    # 三者全为 None/空(默认)时,HTTP 行为与未启用时逐字节一致。详见 机构订阅集成设计.md。
    institutional: bool = False               # 机构订阅总开关(--institutional):启用后接入 publisher_direct 源,
                                              # 对订阅/混合出版商也构造 PDF 直链(经机构授权取全文);默认关,
                                              # 无订阅时这些直链返回 401/403,由下载器 %PDF 校验自动过滤,不产假成功
    ezproxy_prefix: Optional[str] = None      # EZproxy 登录前缀,如 "https://login.ezproxy.example.edu/login?url="
    institution_cookie: Optional[str] = None  # 机构 SSO/Shibboleth 登录后的会话 Cookie 串,如 "k1=v1; k2=v2"
    institution_domains: List[str] = field(default_factory=list)  # 仅对这些出版商域名启用机构访问;空=不主动改写任何域名

    # 源选择(默认全开,按 DEFAULT_SOURCE_ORDER)
    sources: List[str] = field(default_factory=lambda: list(DEFAULT_SOURCE_ORDER))

    log_level: str = "INFO"
    user_agent: str = "fulltext_fetcher/1.0 (https://example.org; mailto:{email})"

    def apply_route_b(self) -> None:
        """据 ``route_b`` 模式派生 ``browser_capture`` / ``browser_pdf_download``(单一真源)。

        off → 两者皆 False;cf-only → 仅 browser_capture;all → 两者皆 True。未知值一律按 off 处理
        (**绝不因误配而默认开**)。CLI 构造 Config 后调用一次;直接构造 Config 的调用方(含 selftest)
        若显式设了 browser_* 而不调用本方法,则以显式值为准(向后兼容)。
        """
        mode = (self.route_b or "off").strip().lower().replace("_", "-")
        self.browser_capture = mode in ("cf-only", "all")
        self.browser_pdf_download = mode == "all"

    def ua(self) -> str:
        return self.user_agent.replace("{email}", self.email)

    def email_is_placeholder(self) -> bool:
        e = (self.email or "").lower()
        return (not e) or e.startswith("anonymous@") or e.endswith("@example.com")
