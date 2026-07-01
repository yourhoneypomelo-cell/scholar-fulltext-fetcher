# 检索成果 · 补遗：publisher_tdm 伪代码(A3) + BASE 免key 核实清单(A1) + PDF 抽取选型(E2)

> 智库补遗（应用户点名三项）。整理人：谷歌学术人机认证-160（信息检索-智库专家）｜核验：**2026-07-01**。
> 只做**设计/清单/选型**，**不改任何生产代码**；落地交实现者。承接《角度8》附A、《检索成果-绿色OA客户端A1·出版商SDK源码A3·反检测复检》《检索成果-E2本地全文检索选型与E1快照增量补丁》。

---

## 一、A3 · `publisher_tdm` 实现者伪代码（`applicable()`/`find_candidates()` + 下载接线）

> 交 145 将指派的实现者（建议 -153）。**前置契约**（需 145 定）：`PdfCandidate` 增可选 `headers`（《角度8》附A A.1）；`config` 加 `wiley_tdm_token / elsevier_api_key / elsevier_insttoken / springer_key`（默认空、零副作用）。

```python
# sources/publisher_tdm.py（草案；gated、缺 token 整源跳过、零副作用）
from urllib.parse import quote
from ..models import PdfCandidate
from .base import BaseSource, register

_WILEY = ("10.1002", "10.1111")
_ELS   = ("10.1016",)
_SPR   = ("10.1007", "10.1140", "10.1186")

@register
class PublisherTDM(BaseSource):
    name = "publisher_tdm"

    def applicable(self, paper, ctx) -> bool:
        cfg = ctx.cfg
        if not getattr(cfg, "institutional", False):
            return False                      # 机构模式总开关（与 publisher_direct 同）
        return bool(self._token_for(paper.doi or "", cfg))   # 无对应 token → 跳过、零开销

    def find_candidates(self, paper, ctx):
        doi = (paper.doi or "").strip()
        if not doi:
            return []
        prefix = doi.split("/")[0]
        if prefix in _WILEY:  return self._wiley(doi, ctx.cfg)
        if prefix in _ELS:    return self._elsevier(doi, ctx.cfg)
        if prefix in _SPR:    return self._springer(doi, ctx.cfg)
        return []

    def _wiley(self, doi, cfg):
        tok = getattr(cfg, "wiley_tdm_token", None)
        if not tok: return []
        return [PdfCandidate(
            f"https://api.wiley.com/onlinelibrary/tdm/v1/articles/{quote(doi, safe='')}",
            self.name, "pdf", None, None, 74,
            headers={"Wiley-TDM-Client-Token": tok})]   # 下载须 allow_redirects=True

    def _elsevier(self, doi, cfg):
        key = getattr(cfg, "elsevier_api_key", None)
        if not key: return []
        h = {"X-ELS-APIKey": key}
        it = getattr(cfg, "elsevier_insttoken", None)
        if it: h["X-ELS-Insttoken"] = it
        return [PdfCandidate(
            f"https://api.elsevier.com/content/article/doi/{doi}?httpAccept=application/pdf",
            self.name, "pdf", None, None, 74, headers=h)]

    def _springer(self, doi, cfg):
        key = getattr(cfg, "springer_key", None)
        if not key: return []
        return [PdfCandidate(
            f"https://api.springernature.com/openaccess/json?q=doi:{doi}&api_key={key}",
            self.name, "landing", None, None, 70)]   # 返回 JSON→由 landing/解析取全文链

    def _token_for(self, doi, cfg):
        p = (doi or "").split("/")[0]
        if p in _WILEY: return getattr(cfg, "wiley_tdm_token", None)
        if p in _ELS:   return getattr(cfg, "elsevier_api_key", None)
        if p in _SPR:   return getattr(cfg, "springer_key", None)
        return None
```

**下载接线 / 降级 / 顺序**（与仓库既有哲学一致）：
- `pipeline` 透传 `candidate.headers` → `download_pdf(headers=...)`（`_download_pdf_core` 已支持 `headers`）。
- **Wiley 必须跟随重定向**（`allow_redirects=True`，client 默认满足）。
- 降级：无权 401/403/HTML → `download.py` 的 **`%PDF` 魔数 + 大小 + `%%EOF`** 校验自动滤除，**绝不产假成功**。
- 顺序：keyed-TDM(conf 74) → 公网 `/doi/pdf/` 模板(66) → 落地页解析。
- 限速：Wiley 3/s+60/10min、Elsevier 机构级 → per-host 令牌桶交 -168（C4）。

**离线 selftest（假 client、不联网）→ `PUBLISHER_TDM_OK`**：
① `institutional=False` 或无 token → `applicable()=False`、`find_candidates=[]`；
② 有 `wiley_tdm_token` → 候选带 `Wiley-TDM-Client-Token` 头、`confidence=74`、`kind=pdf`；
③ 假 client 断言鉴权头被 `_download_pdf_core` 注入；无权返回 HTML → `%PDF` 校验拦截、不落盘；
④ Elsevier 有 `elsevier_insttoken` 时头含 `X-ELS-Insttoken`。

---

## 二、A1 · BASE「免key」核实清单（给 -156 repositories 审计线）

> **结论**：官方证据显示 **BASE HTTP 接口需申请 API key**，与 `green_oa.py` 的「免 key」假设冲突；现连接器很可能在**未注册 IP / 无 key** 时拿不到结果。请核实并订正。

**官方证据（2026-07-01）**：
- `api.base-search.net` / `baseapi.ub.uni-bielefeld.de`（BASE HTTP Interface 官方页）：**“Before you can start testing and using the interface, you need to apply for an API key via this form.”**
- JabRef Issue #15016 标题即 **“Add base-search.net as fetcher (**requires api key**)”**。
- BASE OAI-PMH 接口（另一条，非 fcgi）**IP 受限**（未注册 IP 报 `restrictedInterface`）。
- 官方示例 `ubffm/ublabs-base-examples/base_api.py`：`PerformSearch` 用 `func+query+format=json`（**未见 key 参数**），但**经 SOCKS5 代理**访问 → 暗示 IP/注册门控。

**本仓现状**：`green_oa.py::Base` 请求 `.../BaseHttpSearchInterface.fcgi`（`PerformSearch`），**未带任何 key**；docstring 称「免 key（与 searx 同路径）」。

**核实清单（-156 执行）**：
1. 读 **BASE Interface Guide PDF**（`base-search.net/about/download/base_interface.pdf`），确认 fcgi 的**认证机制**：key 作为参数？还是注册后 **IP 白名单**？
2. **本机 IP 实测** `green_oa.py::Base`：无 key 是否返回结果？（预期：空 / 错误 / 限流）。
3. 若需 key/IP：① 加 config 字段 `base_api_key`（默认空、gated、无则该源跳过，与 CORE 同哲学）；② 或把 Base 标为「需注册」的可选源；③ **订正 `green_oa.py` docstring 的「免 key」表述**。
4. 与 CORE（需 key）一并纳入「需申请 key 的源」清单，统一 gated。

**影响面佐证**：若 BASE 实际不可用，历史 500 样本里 `base` 源命中应为 0——可对照 `out/summary.json` 的 `base` 源命中数（交 -156 / batch 负责人核对）。

---

## 三、E2 · PDF 正文抽取 2026 选型（供本地全文索引）

> 需求：对 `out/pdfs/*.pdf` 抽正文喂 FTS5；**无 GPU、极简依赖、许可证宽松**。

| 库 | 许可 | 依赖 | 速度(单页) | 文本质量 | 结论 |
|---|---|---|---|---|---|
| **pypdf** | **BSD-3** | 纯 Python，零 C | ~12 ms | 中（偶有空格瑕疵） | **默认首选**——**本仓 D2 已用 pypdf**，零新依赖、许可宽松、够用 |
| pypdfium2 | Apache-2.0 | C(PDFium)，~3 MB wheel | ~4 ms（最快之一） | 好 | **可选加速**（高量索引时），许可宽松 |
| PyMuPDF / pymupdf4llm | **AGPL-3.0** / 商用付费 | C(MuPDF) | 4.6 / 55 ms | 优 / 优+Markdown | **默认不用**（AGPL 传染，同 nodriver 顾虑）；仅在确需 Markdown-for-LLM 且过法务时 |
| pdfplumber | MIT | 纯 Python(pdfminer.six) | ~23 ms | 好（表格最佳） | 仅需**表格抽取**时；FTS 全文索引用不上 |
| pdfminer.six | MIT | 纯 Python | ~17 ms | 细粒度 | 需字符级布局时 |

**结论（E2）**：**默认复用 `pypdf`（BSD-3、本仓已装）抽正文，零新依赖**；可选 `pypdfium2`（Apache-2.0）提速；**避免 PyMuPDF/pymupdf4llm（AGPL）进默认路径**。缺库→降级为「仅索引题录」。与本仓 D2（pypdf）+ 许可纪律一致。

---

## 四、协同与来源

- **交 145**：A3 伪代码 → `publisher_tdm` 实现者（建议 -153）；**BASE 核实清单 → -156**（repositories 审计线）——**⚠️ -156 当前不在名册/离线，请你在其回归或换人时转交**；E2 PDF 抽取选型并入 E2 设计（复用 pypdf）。
- **来源（2026-07-01）**：BASE 官方（`api.base-search.net` 需 key）、JabRef #15016、BASE OAI（IP 受限）、`ubffm/ublabs-base-examples`；`WileyLabs/tdm-client`、`ElsevierDev/elsapy`、`springernature/springernature_api_client`；PDF 抽取 2026 横评（pdf.oxide.fyi / pdfmux / nutrient.io / idp-software：pypdfium2 最快、PyMuPDF AGPL、pypdf BSD-3、pdfplumber 表格）。

---

*核验 2026-07-01｜仅设计/清单/选型，不改代码；落地交实现者（publisher_tdm→建议 -153；BASE 核实→-156，经 145 转交）。*
