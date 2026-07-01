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

    # 并发与网络
    concurrency: int = 4
    timeout: float = 30.0
    max_retries: int = 3
    per_host_interval: float = 0.34  # 每域最小请求间隔(秒),礼貌限速

    # 下载/校验
    min_pdf_bytes: int = 1024
    max_pdf_bytes: int = 80 * 1024 * 1024  # 单文件上限 80MB,防异常大体

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

    def ua(self) -> str:
        return self.user_agent.replace("{email}", self.email)

    def email_is_placeholder(self) -> bool:
        e = (self.email or "").lower()
        return (not e) or e.startswith("anonymous@") or e.endswith("@example.com")
