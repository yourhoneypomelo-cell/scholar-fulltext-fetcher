# 验证 · QC 并集门对 route-B 产出「无假阳 / 无假杀」（回收波前置）

> 交付：谷歌学术人机认证 · worker **-147**｜taskId=`task-97d72613-4418-4b26-885d-3815b182bba8`｜2026-07-02
> 触发：总指挥派单——route-B 回收波（ACS-OA 走 B1、RSC 走 B2、Akamai/MDPI 走 ⑥）开跑前，确认内容 QC 并集门对 route-B 真实出版商 %PDF 产出【无假阳（收错不拦）/无假杀（真全文误拒）】。
> 边界：**只读 / 只跑，未改任何 `.py`/metadata/PDF**。pypdf 3.17.4 / rapidfuzz 3.14.5 / Py 3.11.2。
> 复现脚本（只读）：`_tmp_routeb_qc_regress_147.py`（本次新建·route-B 专项）、`_tmp_routeb_cf_paywall_147.py`（CF/付费墙/错文章闸位）、`_tmp_verify_gate_live_147.py`（真门 end-to-end）、`_tmp_regress_fixtures_147.py`（§9.7 fixture）、`RUN_DATA_REGRESS=1 python run_all_selftests.py`（含并集门数据回归）。

---

## 〇、TL;DR（给总指挥 / 145 / 144）

- **门逻辑本身：无假杀 ✅ + 无假阳基本 ✅。** 拿磁盘上真实 ACS/RSC/Elsevier/Wiley 全文喂 `_content_qc_gate`（含 `hard_reject=True` + route-B 会用的最严 source 串）：**真全文 0/5 被拒**；已知非正文/错论文 **4/5 被拒**，唯一漏网是同题他刊 `cctc.200900261`（= 门③ 未实现，147 已登记的老缺口）。
- **⚠️ P0 结构缺口（本次核出、载荷性结论）：route-B 落盘路径【绕过内容 QC 门】。** `download_pdf` 分层里 route-B 走的是 **②b `_browser_capture_fallback`**（ACS-OA B1 / RSC B2）与 **⑥ `_browser_pdf_download`**（Akamai/MDPI），这两个函数校验 `%PDF`+体积+结构后**直接 `_save()`，从不调用 `_content_qc_gate`**（该门只在核心下载路径 ① `_download_pdf_core` 里跑）。**=> 回收波若直接用 route-B 产出记 success，内容 QC 门对它零作用**——recover_b4_cf 那类 SI/错论文假阳会裸奔落盘。
- **结论**：QC 门「能不能判对 route-B 产出」= 能（无假杀、基本无假阳）；但「回收波跑起来时会不会真的判」= **不会**，除非把 route-B 落盘接过 QC 门。**属需改生产代码，先报总指挥，未自行改动。**

---

## 一、route-B 产出走哪条路 / 哪道门管它

`download_pdf`（`fulltext_fetcher/download.py`）分层兜底：

```
① _download_pdf_core ────────────► 落盘前调用 _content_qc_gate（门①②④⑤）✅
② is_cf → _flaresolverr_fallback（解 CF 质询后仍走 _download_pdf_core → 过门）✅
②b JA3 → _browser_capture_fallback → render_download_pdf_bytes   ← route-B(B1/B2)  ✗ 直接 _save，不过门
③ curl_cffi_fallback（→ _download_pdf_core → 过门）✅
④ _publisher_fallback（→ _download_pdf_core → 过门）✅
⑤ _render_fallback（→ _download_pdf_core → 过门）✅
⑥ _browser_pdf_download（Akamai/MDPI 有头 CDP 下载）  ← route-B(Akamai)  ✗ 直接 _save，不过门
```

- **A 组结构检查实测**（`_tmp_routeb_qc_regress_147.py` 源码级 `inspect`）：

| 落盘函数 | 调 `_save` | 调 `_content_qc_gate` |
|---|:--:|:--:|
| `_download_pdf_core`（①，含 FS/curl/publisher/render 回流） | ✅ | **✅ 过门** |
| `_browser_capture_fallback`（②b，route-B B1/B2） | ✅ | **✗ 不过门** |
| `_browser_pdf_download`（⑥，route-B Akamai） | ✅ | **✗ 不过门** |

- `pipeline.py` 仅调 `download_pdf`，success 路径**无第二道 QC**（内容 QC 只此一处）。
- runbook（`路线B-浏览器内直下PDF验证Runbook-173.md` 第 5 步）也把内容 QC 定为**跑完后人工 `tools/qc_content_match.py`** 的后置步骤，未接进 route-B 下载链——与本结构结论一致。

---

## 二、QC 回归结果表（真 PDF PASS / 假阳被拦）

> 口径：把磁盘真实 PDF（`out/recover_b4_cf/{pdfs,rejected}/`）喂 `_content_qc_gate`，**模拟 route-B 会用的 source 串**（ACS-OA→`publisher_oa:acs-authorchoice` 强制过门；RSC/Elsevier→最严 `websearch`），`hard_reject=True`。**这是「若门作用于 route-B 会如何判」的直接证据。**

### B · 无假杀：真实出版商全文（142 v2 人工开卷 ground-truth）

| DOI | 社 | source(模拟) | soft | hard_reject | 判定 |
|---|---|---|---|---|---|
| 10.1021/acs.iecr.5c04764 | ACS | publisher_oa:acs-authorchoice | pass | pass | **未误杀 ✅** |
| 10.1039/c1gc15503b | RSC | websearch | pass | pass | **未误杀 ✅** |
| 10.1016/j.apcatb.2021.120319 | Elsevier | websearch | pass | pass | **未误杀 ✅** |
| 10.1016/j.apcata.2015.10.041 | Elsevier | websearch | pass | pass | **未误杀 ✅** |
| 10.1002/ep.670220410 | Wiley | websearch | pass | pass | **未误杀 ✅** |

**真全文误杀 = 0/5**（ACS/RSC 正是 B1/B2 目标社）。护栏：DOI-in-text → match 强正 + `has_body`（首3000字含 Abstract/Introduction/…）挡住非正文误判。

### C · 无假阳：已知非正文 / 错论文（hard_reject 应拒）

| DOI | 类型 | source(模拟) | hard_reject | 备注 |
|---|---|---|---|---|
| 10.1021/acsanm.1c00959 | SI | publisher_oa:acs-authorchoice | **REJECT ✅** | 门④ SI |
| 10.1021/acscatal.8b02371 | SI | publisher_oa:acs-authorchoice | **REJECT ✅** | 门④ SI |
| 10.1021/acs.chemrev.7b00776 | citation-report | websearch | **REJECT ✅** | 门⑤A |
| 10.1016/j.jcou.2018.01.028 | poster | websearch | **REJECT ✅** | 门⑤B |
| 10.1002/cctc.200900261 | 同题他刊 | websearch | **漏(pass) ⚠️** | 门③ 未实现（147 老缺口） |

**假阳拦截 = 4 拒 / 1 漏**；漏网仅同题他刊，非新问题。

### 全量 end-to-end（`_tmp_verify_gate_live_147.py`，recover_b4_cf 34 条 success）

- `hard_reject=True`：真实拒盘 25/29 非真全文假阳（**86%**），**真全文误杀 0/5**。
- 142 干净口径（逃逸门①②的 9 条 auto-match）：门④⑤ 拒 8/9（SI×5 + citation-report×2 + poster×1），唯一漏 = `cctc.200900261`（门③）。

---

## 三、防退化 / 不误杀回归（既有，本次复跑通过）

| 回归 | 命令 | 结果 |
|---|---|---|
| **全套 selftest + 并集门数据回归**（-142 点名） | `RUN_DATA_REGRESS=1 python run_all_selftests.py` | **PASS=43 FAIL=0 SKIP=1**；其中 `regress_qc_union_189` = **REGRESS_UNION_189_OK**（46.2s） |
| 并集不退化回交集（189 同域错论文 + 34 title 假匹配） | `python -m tools.regress_qc_union_189` | 同域桶可重放 58 条并集全拒（旧交集必漏）；title 假匹配桶可重放 33 条门②全拒、0 漏 |
| §9.7 四正例不误杀 + SI 反例 | `python _tmp_regress_fixtures_147.py` | 四正例全 `match` ✅；SI-only 反例 `mismatch` ✅ |

> 唯一 SKIP = `flaresolverr_nodriver`（online，默认 SKIP，与本任务无关）。

### 三类假阳分别在哪道闸被拦（`_tmp_routeb_cf_paywall_147.py`，回应 -142 点名）

| 假阳类型 | 是否 %PDF | 被拦位置 | route-B 会不会漏 |
|---|:--:|---|:--:|
| **CF 挑战页**（title=`Just a moment`） | 否 | `looks_like_pdf=False` → 记 not-pdf；route-B 端 `_is_pdf_bytes=False` + `_BLOCK_SIGNALS` 命中 → `blocked:challenge-page` | **不漏**（连 %PDF 都不是，落不了盘） |
| **付费墙 HTML**（Access Denied/Get Access） | 否 | `looks_like_pdf=False` → 记 not-pdf/landing；route-B 端 `_is_pdf_bytes=False` | **不漏** |
| **错文章**（真 %PDF、他刊他题） | 是 | 仅内容 QC 门①拦（实测 `cssc.201601217` → `content-mismatch(score=47.7)`） | **会漏**（route-B 绕过内容 QC 门） |

> 关键：内容 QC 门只在 `looks_like_pdf(data)=True` 时才跑。CF 挑战页/付费墙 HTML 是**非 %PDF**，在更前面的 %PDF 魔数闸（及 route-B 自身的 `_is_pdf_bytes`/`_BLOCK_SIGNALS`）就被拦，两条路径都不会误当 PDF 落盘 → 这两类**无假阳**。真正需要内容 QC 门、而 route-B 会漏的，是**错文章（真 %PDF 他刊他题）**——正是 §四缺口①的动机。而 -152 实证的真 PDF（ACS Omega `acsomega.6c04195` 17页/13.7MB DOI命中、RSC `d5ra08493h`）属真全文，DOI-in-text→match，必 PASS（与 §二 B 组 ACS/RSC 真全文 0 误杀同理；这两件当前不在本机磁盘，故以同社在盘真全文 `iecr.5c04764`/`c1gc15503b` 代证）。

> §9.7 附带诊断：Nature 式 **"Supplementary Information"** 当前门④文本判识**未命中**（门④只认 "supporting information"）——147 已登记的 P1 门④用词缺口，route-B 若回收 Nature 系 SI 需留意。

---

## 四、缺口清单（按优先级；均须改生产代码，已报总指挥，未自行改动）

1. **P0 · route-B 落盘绕过内容 QC 门（本次核出，回收波直接受影响）。**
   `_browser_capture_fallback`（②b）与 `_browser_pdf_download`（⑥）落盘前不过 `_content_qc_gate`。**建议**：在这两个函数 `_save()` 之前接一道内容 QC——复用 `_content_qc_gate(data, paper, source, url, cfg, log, events)` 即可（B 组已证真全文 0 误杀、C 组已证能拦 SI/citation/poster）。**要点**：route-B 的 candidate.source 多为 DOI 绑定源，`_source_needs_content_qc` 可能豁免它 → 需**对 route-B 产出强制过门**（或至少强制跑非正文门④⑤ + DOI/标题比对），否则接了也豁免；回收波应置 `content_qc_non_article_hard_reject=True`（硬拒不落盘）。
2. **P0 · 门③（同题他刊 meta-doi）仍未实现。** 即便门作用于 route-B，`cctc.200900261` 一类（首页印对标题+DOI、正文却是他刊）仍漏。→ 落 173 §9.4 `meta-doi-mismatch`（读 `reader.metadata['/doi']` + XMP `prism:doi`，`norm(meta_doi)!=norm(exp_doi)` 即拒；注意 ACS SI 元数据也带母文 DOI，门④须独立保留以免放行）。
3. **P0 运维 · 门全链依赖 pypdf。** 运行时缺 pypdf → `_qc_matchers()` 返 None → 门静默 no-op、100% 放行（142 §9.3 实锤 12 条错论文即此根因）。回收波机器**必须装 pypdf**（本核验环境 3.17.4 已装）。
4. **P1 · 门④ SI 用词缺口。** 补 `"supplementary information"` + `"in the format provided by the authors"`（Nature/多家用词），保持 `not has_body` 护栏（实测不误杀）。

---

## 五、结论

- **【无假杀】✅**：QC 门对 route-B 目标社真全文（ACS/RSC/Elsevier/Wiley）零误杀（0/5，hard_reject 下亦然）。
- **【无假阳】基本 ✅**：hard_reject 下拦下 SI/citation-report/poster；唯一漏网是同题他刊（门③ 未实现，老缺口）。
- **【但门当前对 route-B 产出不生效】⚠️**：route-B 走 ②b/⑥ 兜底直接落盘，**结构上绕过 QC 门**。回收波开跑前，需（a）把 route-B 落盘接过内容 QC 门并对其强制过门 + `hard_reject`，或（b）沿用 runbook §5 的**跑后 `tools/qc_content_match.py` 复扫 + 隔离**作为补偿。二者至少落一个，否则 route-B 的 success 无内容级防假阳。

*核验 2026-07-02｜worker -147｜taskId=`task-97d72613`｜证据脚本（只读，复跑零差异）：`_tmp_routeb_qc_regress_147.py` / `_tmp_verify_gate_live_147.py` / `_tmp_regress_fixtures_147.py` / `tools/regress_qc_union_189.py`｜未改任何 .py/metadata/PDF。*
