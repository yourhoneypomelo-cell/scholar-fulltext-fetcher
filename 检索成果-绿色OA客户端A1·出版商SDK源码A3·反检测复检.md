# 检索成果 · 绿色OA连接器客户端(A1) + 出版商官方SDK源码(A3) + 反检测复检(#3)

> 智库深挖（应用户点名三项）。整理人：谷歌学术人机认证-160（信息检索-智库专家）｜数据核验：**2026-07-01**。
> 定位（去重）：**先通读本仓源码 + 既有文档**，只报「与现状对比后的增量结论」；只做选型 / 源码模式提炼 / 复检，**不改任何生产代码**。反检测浏览器细节以 158《选型2026-隐身无头浏览器与反检测》为准；A3 端点/限速以《角度8》为准，本文补「官方 SDK 源码级封装模式」。

---

## 〇、TL;DR

- **A1 绿色OA连接器**：**保持本仓 `green_oa.py` 手写连接器**（DOI 驱动、stdlib+requests、零依赖）——现成 OSS 客户端（`osfclient`）面向「鉴权文件管理」而非 DOI→PDF、且加依赖；BASE/CORE **无维护中的 Python OSS 客户端**（仅 R `rbace`/`rcoreoa`）。**两个行动项**：① **核实 BASE fcgi 是否真免 key**（官方文档要 API key + IP 白名单，与 `green_oa.py` 的「免 key」假设冲突）；② 申请**免费 CORE key**（运维）。
- **A3 出版商官方 SDK**：给 `publisher_tdm` 实现者提炼可复用封装模式——**Wiley 最干净**（官方 `wiley-tdm`，MIT、仅 `requests`；token + **必须跟随重定向**）；**Elsevier `elsapy` 带 pandas 重依赖 → 复制 header 模式、勿 import**；Springer key-in-query + OA/TDM 分端点。**建议复制模式而非引重依赖**（Wiley 例外：MIT+仅 requests，可选直用）。
- **#3 反检测复检**：**158 文今日仍准确、无需更新**（nodriver 28/31 零封锁首选、patchright Apache 活跃回退、camoufox 恢复期实验兜底）。唯一增量：社区 fork **`nodriver-reforged`**（2026-06、暗色 Turnstile 模板 + HiDPI `verify_cf`）刚出、0★、单人、未验证 → **观望不采用**。

---

## 一、A1 · 绿色OA连接器：OSS 客户端 vs 本仓 `green_oa.py`

> 本仓 `sources/green_oa.py` 已实现 BASE / OSF / ScienceOpen；`aggregators.py` 有 CORE。本节评估「是否有更好的开源客户端可采用/借鉴」，而非重复其实现。

| 源 | 本仓现状（`green_oa.py`/`aggregators`） | 2026 OSS 客户端 | 契合度 | 结论 |
|---|---|---|---|---|
| **OSF** | `api.osf.io/v2/preprints/?filter[doi]=` → `osf.io/download/{file_id}`（DOI 驱动、无鉴权、零依赖） | **osfclient**（~143★、库+CLI，面向**鉴权**文件 up/down，username/password） | 低（用途不同：文件管理≠DOI→PDF，且加依赖） | **保持自研** |
| **BASE** | `api.base-search.net/.../BaseHttpSearchInterface.fcgi`（`PerformSearch&format=json`，**假设免 key**） | **无 Python 客户端**（仅 R `rbace`/rOpenSci）；官方 `baseapi.ub.uni-bielefeld.de` 明确**需申请 API key + IP 白名单** | — | **保持自研；但⚠️核实 key/IP 要求**——官方要 key，现连接器「免 key」假设可能导致无 key/未白名单时**拿不到结果**（交 -156 repositories 审计线实测确认） |
| **CORE** | `aggregators.Core`（无 key 时 `return []`） | **无维护中的 Python 客户端**（R `rcoreoa` 早期） | — | **保持自研；申请免费 CORE key**（运维/145） |
| **ScienceOpen** | `hosted-document?doi=`（前缀 10.14293 landing） | 无客户端/无公开 DOI→PDF API | — | **保持自研** |

**结论（A1）**：本仓「stdlib+requests、DOI 驱动、零依赖」的手写连接器是**正解**——可用的第三方客户端要么用途不符（osfclient 面向鉴权文件管理）、要么无 Python 维护（BASE/CORE 仅 R），引入只会加依赖、不提命中。**两个真行动项**（非重写）：**(1)** 核实 BASE fcgi 的 key/IP 白名单要求（潜在 bug）；**(2)** 申请免费 CORE key。

---

## 二、A3 · 出版商官方 SDK 源码 → `publisher_tdm` 实现者封装参考

> 承接《角度8》§一 + 附A（端点/限速/契约已给）。本节补「读官方 SDK 源码后」的**可直接借鉴封装模式**，供 145 将指派的 `publisher_tdm` 实现者（建议 -153）照抄。

| 社 | 官方 SDK（许可/依赖） | 取 PDF 端点 + 认证 | 可复用模式（源码级） | 直用 or 复制 |
|---|---|---|---|---|
| **Wiley** ★最干净 | `wiley-tdm`（WileyLabs/tdm-client，**MIT**，v1.1.0 2026-05，Py≥3.10，仅 `requests`） | `GET api.wiley.com/onlinelibrary/tdm/v1/articles/{doi}` + 头 `Wiley-TDM-Client-Token: {UUID}` | `TDMClient()` 读 `TDM_API_TOKEN` env（或 `api_token=`）；**`allow_redirects=True`（必须——Wiley 重定向到 PDF）**；内置限速（3/s + 60/10min）+ 错误处理（Access denied）；IP 判订阅 | **可选直接用**（MIT + 仅 requests，低成本）；或复制这 3 要素 |
| **Elsevier** | `elsapy`（ElsevierDev，官方，~427★，依赖 `requests` + **`pandas`**） | `GET api.elsevier.com/content/article/doi/{doi}?httpAccept=application/pdf` + 头 `X-ELS-APIKey`（+可选 `X-ELS-Insttoken`） | `ElsClient(apikey)` + `client.inst_token=insttoken`；`FullDoc(doi).read(client)`；无权 `view=FULL`/`amsRedirect` 兜作者稿（AM） | **复制 header 模式，勿 import**（elsapy 带 pandas 重依赖，违背本仓极简依赖） |
| **Springer Nature** | `springernature_api_client`（官方，pip） | OA 端点（免费）/ TDM 端点（订阅）；key in query | `tdm.TDMAPI(api_key).search(q=...)` + `save_xml()`；另有 `openaccess` 模块；返回 XML | **复制 key-in-query + OA/TDM 分端点模式** |

**给实现者的统一封装契约（对齐《角度8》附A、本仓哲学）**：
- `applicable()`：对应 token/key **非空才产候选**（否则整源跳过、零开销）；密钥经 `getattr(cfg, "wiley_tdm_token"/"elsevier_api_key"/"springer_key", None)` 兜底、默认关。
- 候选顺序：**keyed-TDM（conf≈74）→ 公网 `/doi/pdf/` 模板（66）→ 落地页解析**；`PdfCandidate` 带鉴权 `headers`（需《角度8》附A 的 `PdfCandidate.headers` 契约）。
- **Wiley 必须跟随重定向**（`allow_redirects=True`）。
- 降级：无权返回 401/403/HTML → 由 `download.py` 的 **`%PDF` 魔数 + 大小 + `%%EOF`** 校验自动滤除，**绝不产假成功**。
- per-host 限速（Wiley 3/s+60/10min、Elsevier 机构级）交 -168 的 C4 异步令牌桶。

**结论（A3）**：Wiley 官方 `wiley-tdm`（MIT+仅 requests）是**唯一值得考虑「直接用」**的 SDK；Elsevier/Springer **复制其 header/端点模式**即可，勿引 pandas 等重依赖。此参考可直接喂给 145 指派的 `publisher_tdm` 实现者。

---

## 三、#3 · 反检测无头浏览器复检（以 158 为准）

> 158《选型2026-隐身无头浏览器与反检测》成稿于 **今日（2026-07-01）**。本节仅复核其时效，不重复其内容。

- **复核一致（无需更新）**：
  - **nodriver**：v0.50.x、**AGPL-3.0**、基准 **28/31 零封锁（首选）**；直连 CDP、系统真 Chrome。
  - **patchright**：Apache-2.0、~3.2k★、活跃（回退）。
  - **camoufox**：MPL-2.0、**~9.6k★**（158 记 ~9,100，现 9,591）、最新 `v150.0.2-beta.25`（2026-05-11）、last push 2026-06-23（活跃）但仍**「恢复期/实验/不宜生产」**；开发在 CloverLabsAI/VulpineOS 分叉。
- **唯一增量**：社区 fork **`nodriver-reforged`**（2026-06-04、AGPL、暗色 Turnstile 模板 + HiDPI/`devicePixelRatio` 缩放 + `verify_cf()` 重试逻辑）——**刚出、0★、单人维护、未经验证** → **观望，不采用**；主力仍用 nodriver 官方。
- **结论（#3）**：158 文**依然是本组反检测浏览器的权威且时效准确**；无材料级变化。与 155（当前跑 batch4）/158 无冲突，本节仅复核确认。

---

## 四、协同与来源

- **交 145 / 实现者**：
  - A1 → 两行动项：BASE key/IP 核实交 **-156**（repositories 审计线）实测；CORE key 申请交**运维/145**。
  - A3 → 封装参考交 **145 将指派的 `publisher_tdm` 实现者（建议 -153）**；`PdfCandidate.headers` 契约需 145 定（《角度8》附A A.1）。
  - #3 → 以 **158 文**为准；`nodriver-reforged` 仅登记观望。
- **来源（2026-07-01 核验）**：`osfclient/osfclient`（GitHub）；BASE HTTP Interface 官方（`baseapi.ub.uni-bielefeld.de`，需 key+IP）；rOpenSci `rbace`/`rcoreoa`；`ElsevierDev/elsapy`（exampleProg/Wiki）；`WileyLabs/tdm-client`（`wiley-tdm` v1.1.0 MIT）+ Wiley Online Library TDM 官方（curl `-L` 跟随重定向）；`springernature/springernature_api_client`（TDMAPI）；Ian L. Paterson《Anti-detect benchmark 2026》；`daijro/camoufox`；`codeisalifestyle/nodriver-reforged`；158《选型2026-隐身无头浏览器与反检测》。

---

*核验 2026-07-01｜定位：A1 客户端选型（保持自研+两行动项）、A3 官方 SDK 源码封装参考（给 publisher_tdm 实现者）、#3 复检（以 158 为准）；仅选型/源码提炼/复检，不改代码。*
