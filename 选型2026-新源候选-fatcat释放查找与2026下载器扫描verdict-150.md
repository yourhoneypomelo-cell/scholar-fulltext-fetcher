# 选型2026 · 新源候选 — fatcat release-lookup（DOI-keyed 干净源）+ 2026 下载器扫描 verdict

> 交付：**谷歌学术人机认证-150**（worker · 信息检索-专家智库岗）｜2026-07-02｜用户点名「还有需要检索开源项目挖掘可参考性源码并读源码么」→ 定向扫 2026 新 OA 发现源/下载器。
> 边界：**只新建本 1 份选型参考，未改任何 `.py`**；代码活转实现者/总指挥。已 `grep` 核对仓内 **未集成 fatcat**（0 命中）。
> 结论先说：**扫到 1 个真正值得登记的新源＝Internet Archive `fatcat` release-lookup**（DOI-keyed、零 key、干净）；其余 2026 下载器（paper-fetch/doiget/opencite/auto-paper-harvester）**无一值得整包引入**（均比自建 22 源薄，或依赖出版商 key/机构会话＝已由 A5/route-B 覆盖）。

---

## 〇、TL;DR

- **新源候选（值得登记，交实现者评估接线）**：**`api.fatcat.wiki/v0/release/lookup?doi=<DOI>&expand=files&hide=abstracts,refs`**——Internet Archive 维护的 25M+ OA 论文「release→file」编目，**按 DOI 直查**、**零 key**、只读、返回**每份文件的 `web`（活链）+ `webarchive`（Wayback 直链）+ `sha1` + `mimetype`**。
- **为什么它与现有 `wayback.py` 不重复**：现 `wayback.py` 是「拿 URL 去查 Wayback 可用性/CDX」；**fatcat 是「拿 DOI 查 IA 已编目的文件实体」**——覆盖 IA 主动抓存的那批 OA 副本（含很多 unpaywall 未收的机构库/作者自存稿存档），且**给 SHA1 可校验**。
- **为什么它「干净」（关键）**：fatcat 的 file 实体**由 DOI 权威绑定到 release**（`ext_ids.doi==查询 DOI`）——按经验记录 **L.5 口径属「DOI-keyed 源、0% 假阳」那一类**（同 unpaywall/openalex/crossref），不是 websearch 那种「搜索引擎首个 PDF」。**天然规避 68.5% 错论文假阳。**
- **2026 下载器扫描 verdict**：paper-fetch（6~7 源）/doiget（Rust，OA-first）/opencite（多源+PDF→md）/auto-paper-harvester（TDM key+Playwright 机构兜底）——**均不整包引入**：源覆盖比本仓 22 源薄，novel 处（Wiley/Elsevier/Springer TDM key、机构浏览器兜底）**已被本仓 route-B / A5 覆盖或需付费/机构 key**。仅登记参考。

---

## 一、新源候选：fatcat release-lookup（实读官方 Guide + API 示例）

### 1.1 接口（零 key、只读、DOI 直查）
```
GET https://api.fatcat.wiki/v0/release/lookup?doi=<DOI>&expand=files&hide=abstracts,refs
```
- 命中 HTTP 200 → JSON 含 `ext_ids.doi`（校验＝查询 DOI）、`release_stage`（可筛 `published`）、`files[]`。
- `files[]` 每项：`mimetype`（筛 `application/pdf`）、`sha1`（**可做落盘校验/去重**）、`urls[]`（每项 `{rel, url}`，`rel∈{web, webarchive}`）。
- 官方明确：Unpaywall 是同任务首选；**fatcat 作补充**（IA 存档视角，覆盖 unpaywall 盲区）。

### 1.2 落地骨架（`sources/` 新增，DOI-keyed，纯函数 + 离线 selftest）
```python
# fulltext_fetcher/sources/fatcat.py（骨架;实现/接线交实现者+总指挥）
"""Internet Archive fatcat release-lookup:按 DOI 查 IA 编目的 OA 文件(web+webarchive 直链)。
DOI-keyed → 0 假阳(L.5);零 key、只读。补 unpaywall/wayback 盲区(IA 主动存档的作者自存稿/机构库)。"""
from typing import Any, List
from ..models import Paper, PdfCandidate
from .base import BaseSource, SourceContext, register

_API = "https://api.fatcat.wiki/v0/release/lookup"

def parse_files(data: Any, want_doi: str) -> List[tuple]:
    """纯函数:从 release JSON 抽 (url, kind, sha1)。校验 ext_ids.doi==want_doi(记录级绑定)。绝不抛。"""
    try:
        if (data or {}).get("ext_ids", {}).get("doi", "").lower() != (want_doi or "").lower():
            return []                                   # 记录级 DOI 校验(防错配,呼应 openaire M.5 教训)
        out = []
        for f in (data.get("files") or []):
            if (f.get("mimetype") or "") not in ("application/pdf", ""):
                continue
            sha1 = f.get("sha1")
            # 优先 webarchive(存档稳定)其次 web(活链);webarchive 用 id_ 原始取回
            for u in (f.get("urls") or []):
                url, rel = u.get("url"), u.get("rel")
                if not url:
                    continue
                if rel == "webarchive" and "/web/" in url and "id_/" not in url:
                    url = url.replace("/web/", "/web/", 1)  # 实现者:插 id_ 去工具条(同 wayback._to_id_url)
                out.append((url, "pdf", sha1))
        return out
    except Exception:  # noqa: BLE001
        return []

@register
class Fatcat(BaseSource):
    name = "fatcat"
    requires_doi = True
    def find_candidates(self, paper: Paper, ctx: SourceContext) -> List[PdfCandidate]:
        if not paper.doi:
            return []
        try:
            r = ctx.client.get(_API, params={"doi": paper.doi, "expand": "files",
                                             "hide": "abstracts,refs"})
            if getattr(r, "status_code", 0) != 200:
                return []
            cands = []
            for url, kind, _sha1 in parse_files(r.json(), paper.doi):
                cands.append(PdfCandidate(url=url, source="fatcat", kind=kind, confidence=72))
            return cands
        except Exception:  # noqa: BLE001
            return []
```
> 接线位置建议：DEFAULT_SOURCE_ORDER 里排在 unpaywall/openalex 之后、wayback 之前（DOI-keyed 干净源梯队；比 wayback 的 URL 猜测更精准）。confidence ~72（DOI 绑定、低于真 OA 直链但高于 landing）。**SHA1 可交 download 层做落盘校验/跨源去重**。

### 1.3 ROI（诚实）
- **净增点估：小**（still_missing 主体是订阅墙，fatcat 只覆盖 OA；且与 unpaywall/wayback 有重叠）——但**它是零 key、DOI 干净、可 SHA1 校验的补充**，**捞回的是 IA 主动存档、unpaywall 漏收的作者自存稿/机构库 OA 副本**（每条 1 次 API、成本≈0）。
- **价值定位**：不在量、在「**再加一个 0 假阳的 DOI-keyed 干净兜底**」，且**对 elsevier/RSC 这类 URL 不可推导、wayback 只能靠 doi.org 兜底的桶**，fatcat 可能给出 IA 已存档的直链（wayback.py 现对这些桶覆盖弱，见其 docstring）。
- **风险**：低（只读、零 key、DOI 校验）；`release_stage` 建议筛 published、`webarchive` 链插 `id_` 去工具条（复用 `wayback._to_id_url`）。

---

## 二、2026 下载器全网扫描 verdict（均不整包引入，仅登记）

| 项目 | 时效/热度 | 与本仓对比 | verdict |
|---|---|---|---|
| **Agents365-ai/paper-fetch** | v0.15.1(2026-06)、143★、MIT | 7 源(Unpaywall/S2/arXiv/PMC/bioRxiv/publisher/**Sci-Hub 默认开**)、纯 stdlib、稳定 JSON envelope | **不引**：源比 22 少；**Sci-Hub 默认开=越界**(总指挥已裁定禁 Sci-Hub)。仅其**幂等 JSON envelope/NDJSON** 已登记为 `api.py` 契约借鉴(承开源扫描-2026) |
| **sotashimozono/doiget** | Rust 单二进制、MCP、v0.7(2026-06)、MIT | OA-first(Crossref/Unpaywall/arXiv)、TDM 编译期 gated、签名二进制/SBOM | **不引**：源更薄；Rust 栈与本仓 Python 哲学不合；**永不绕墙**理念与我们一致(可背书)。仅登记其「TDM 按出版商编译期 opt-in」思路(≈我们 A5 gate) |
| **opencite**(VisLab/neuromechanist) | Python、MIT、2026 | 多源并行(OpenAlex/S2/PubMed/arXiv/bioRxiv/OSF/Zenodo/Figshare/Crossref/CORE)+PDF→md | **不引**：源与本仓高度重叠(且我们已有 OSF/Zenodo/CORE)；**PDF→md**(markitdown/mistral)超本仓下载定位，登记为 E2 抽取参考 |
| **Grenzlinie/auto-paper-harvester** | 2026、agent skill | TDM API(Wiley/Elsevier/Springer key)→OA→**Playwright 机构 cookie 兜底**(ACS/RSC/IEEE/AIP/IOP/APS) | **不引**：TDM 需**出版商付费/申请 key**；机构 cookie 兜底**＝我们 A5×route-B 已覆盖**(SciTeX 真源码增量-150)。仅印证「机构会话兜底」方向正确 |

> **共同结论（承开源全网扫描-2026 §E）**：所有成品下载器均**比本仓自建 22 源薄**；其 novel 处不外乎 ①付费 TDM key（Wiley/Elsevier/Springer——非免费、非本波范围）②机构浏览器兜底（已由 A5×route-B 覆盖）③Sci-Hub（越界禁用）。**唯一净新增可接的免费干净源＝fatcat**（本文 §一）。

---

## 三、给总指挥的一句话

**扫 2026 新源/下载器一圈，真正值得动的只有 1 个：登记 `fatcat` release-lookup 为新 DOI-keyed 干净兜底源**（零 key、0 假阳、给 SHA1、补 unpaywall/wayback 盲区，尤其 elsevier/RSC 这类 URL 不可推导桶）——**代码活是加个 `sources/fatcat.py`（骨架已给），ROI 小但零风险零成本、且是「再加一层 0 假阳」**。其余 2026 下载器均不整包引入（薄/需付费 key/越界/已覆盖）。是否排期交总指挥（属常规波、非破局）。

---

## 四、来源

- **fatcat**：`guide.fatcat.wiki/cookbook.html`（Lookup Fulltext URLs by DOI：`/v0/release/lookup?doi=&expand=files&hide=abstracts,refs`、`files[].urls[]{rel:web/webarchive}`、`files[].sha1`、`ext_ids.doi` 校验）、`github.com/internetarchive/fatcat`（AGPLv3 服务端/客户端自动生成许可宽松）、`scholar.archive.org`（25M+ OA 全文）。
- **2026 下载器**：`Agents365-ai/paper-fetch` v0.15.1、`sotashimozono/doiget` v0.7、`VisLab/opencite`、`Grenzlinie/auto-paper-harvester` v0.2（均 2026、GitHub 实读）。
- 本仓核对：`grep fatcat|archive.org|wayback` → 仓内**无 fatcat**、`wayback.py` 是 URL→Wayback 查询（与 fatcat 的 DOI→file 编目互补）；`经验记录 L.5`（DOI-keyed 源 0 假阳）、`M.5`（聚合源须记录级 DOI 校验）；`选型2026-A5...SciTeX真源码增量-150`（机构兜底已覆盖）；`给总指挥-智库本轮成果...`（Sci-Hub 越界、paper-fetch envelope 借鉴）。

---
*核验 2026-07-02｜-150｜工单「2026 新源/下载器定向扫描」｜结论：唯一值得登记的新源＝IA fatcat release-lookup(DOI-keyed 零 key 干净、给 web+webarchive+sha1，补 unpaywall/wayback 盲区)，骨架已给、ROI 小但零风险、代码活交实现者；2026 下载器(paper-fetch/doiget/opencite/auto-paper-harvester)均不整包引入(薄/需付费TDM key/Sci-Hub越界/已被A5×route-B覆盖)。仅新建本 1 份参考，未改任何 .py。*
