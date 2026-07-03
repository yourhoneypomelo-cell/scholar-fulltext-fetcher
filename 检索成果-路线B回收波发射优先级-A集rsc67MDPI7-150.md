# 检索成果 · 路线B 回收波发射优先级一页纸（A 集：RSC 67 + MDPI 7）

> 交付：**谷歌学术人机认证-150**（worker · 信息检索-专家智库岗）｜2026-07-02｜工单来源：总指挥 148 **task-b291b688**（当前第一优先）。
> 用途：**给回收波排序**——route-B 过盾算力有限（全局 concurrency=1、每条 ~15–45s 有头浏览器），**绝不能把算力浪费在注定 `no-pdf` 的订阅墙条目上**。本页把 A 集 74 条拆成【真 OA 子集＝值得 route-B 发射】vs【订阅墙＝route-B 必 no-pdf、不发射、留 route-A】，给发射顺序 + 预筛法 + 命令。
> 边界：**新建本 1 份 md + 3 份发射清单 txt（数据产物），未改任何库 `.py`/产物**（预筛用一次性脚本跑完已删，逻辑＝调仓内 `publisher_oa.build_pdf_candidates`）。数据取自 `out/still_missing_shards/{rsc.txt,other.txt}`、`publisher_oa._rsc/_mdpi`、`经验记录 N.3/N.4/N.8`、`A5机构订阅现状与still_missing可救前缀梳理-150.md`（still_missing 628，2026-07-02）。
>
> ⚠️ **净覆盖率口径统一（✅ 定版 326）**：本文 still_missing 分母 **628**（@11:48 快照）为**【历史口径】**（MDPI7 已回写、后续多轮 merge 至定版 326）。**当前权威 = `out/coverage.json` `summary`：326 success / 673 miss / 999 = 32.63%**（generated_ts 2026-07-03 12:50:24，allow_override=10）。RSC67/MDPI7 发射优先级结论仍有效。唯一权威 + RSC 待并入项见 **《基线口径冻结说明-388-173.md》**。
> **前作互证**：本页与 -140/-142 已交的 `检索成果-routeB回收波发射优先级-142.md` 同题；区别＝-142 是纯文档手工分桶（未跑、未产清单），**本轮把预筛机械跑实、产出可直接 `-f` 的发射清单 txt，且机械结果与 -142 手工分桶零差异**（4 RSC 金OA + 7 MDPI + 8 待 is_oa 复核）——互为交叉验证。
> **实跑产物（本目录，已含 is_oa 联网复核终稿）**：`routeB_mdpi.txt`（**7**，先发）、`routeB_rsc_goldoa.txt`（**8**＝4 RSC Advances 离线金OA + 4 is_oa 复核命中，次发）、`routeB_rsc_subscription.txt`（**59**，不发/留 A5）。**route-B 发射波合计 = RSC 8 + MDPI 7 = 15。**
> **is_oa 复核结果（2026-07-02 Unpaywall，8 条 [NEED_is_oa]）**：命中 4（`d0gc02302g` bronze、`d2gc02623f`/`d3ee02589f`/`d5fd00172b` hybrid，均托管 `pubs.rsc.org/en/content/articlepdf/...` → 并入发射）；closed 4（`d0gc00095g`/`d5gc03584h`/`d2nj03895a`/`d0cs00025f` → 留 A5）。

---

## 〇、TL;DR（可直接照排）

| 优先级 | 桶 | 条数（**实跑离线预筛**） | route-B 路径 | 为什么这个序 |
|:--:|---|:--:|---|---|
| **① 先发** | **MDPI 10.3390** | **7** | ⑥ `_browser_pdf_download`（有头过 **Akamai**，非 CF/JA3） | **全真 OA**、候选已定位（`www.mdpi.com/.../pdf`）、只卡 Akamai 下载环 → route-B 命中率最高、最该先拿 |
| **② 次发** | **RSC 真 OA**（4 RSC Advances 离线金OA + 4 is_oa 复核命中） | **8**（`c4ra00825a`/`c4ra02037e`/`c4ra14572k`/`c5ra04969e` + `d0gc02302g`/`d2gc02623f`/`d3ee02589f`/`d5fd00172b`） | ②b `_browser_capture_fallback` → B2（RSC articlepdf 需 `Fetch.enable` 导航拦截，N.8） | JA3 绑定 CF 桶的**真 OA 部分**，route-B 唯一能救；机制已闭环（-152 `d5ra08493h`） |
| **③ 不发（留 route-A）** | **RSC 订阅墙 / closed** | **59** | —— | **route-B 对订阅墙返 `no-pdf` 是正确行为、非 bug**（N.8 边界）；投算力必浪费 → 留机构订阅 A5 |

> **实跑结论（离线预筛 + is_oa 联网复核，已终稿）**：rsc 67 → route-B 发射 **8**（离线金OA 4 + is_oa 命中 4）/ 留 A5 **59**；MDPI **7** 全发。**route-B 发射波合计 = 8 + 7 = 15**。离线金OA 4 条与 -142/-140 手工分桶零差异；8 条 hybrid 经 Unpaywall 复核**命中 4 closed 4**（把 -142「待定 8」落定）。

> **诚实 ROI（务必带上，防高估）**：JA3 绑定型 CF 后的真 OA/免费正文桶规模本就小（**~5–15**，N.4/-173）；route-B 全量 still_missing 净增**点估 +20 篇（+2pp）**。**RSC 在 batch6 口径净 MISS≈0**（websearch 已从别处兜回），单为 RSC 上 CF 破盾**边际≈0**。**A 集价值在「点亮 JA3 机制 + 从权威落地页直下提质（绕 websearch 68.5% 假阳）」，不在清空 still_missing。** 本页排序的**首要收益是「省算力」**（别烧在 ③ 上），其次才是拿回 ①②的真 OA。

---

## 一、A 集画像（74 = RSC 67 + MDPI 7）

| 桶 | 前缀 | 墙型（经验记录 N.3/K/H.3） | route-B 能救性 | 落点代码 |
|---|---|---|---|---|
| **MDPI** | 10.3390 | **Akamai Bot Manager 403**（**非 CF**）；真 OA，候选 `www.mdpi.com/.../pdf` 已定位、卡下载环（6×`http-403`+1 landing，见 `本波回收交付汇总 §二`） | ★★★ **全可救**（真 OA，只需过 Akamai） | `download.py` ⑥ `_browser_pdf_download`（有头）；候选来自 `publisher_oa._mdpi`→landing selector 抽 `/pdf` |
| **RSC** | 10.1039 | **JA3 绑定 CF + 订阅**：`cf_clearance` 绑 TLS 指纹，curl_cffi 回放必 403（N.3 锤死） | ★★☆ **仅金 OA 子集可救**；订阅墙 route-B 也拿不到（付费墙物理边界） | 金 OA→`download.py` ②b→`render_download_pdf_bytes` B2（articlepdf）；订阅→无候选/no-pdf |

**关键分辨（决定发不发射）**：
- **MDPI 7**：桶内**全部真 OA**（MDPI 近乎全 OA）→ **全发射**。
- **RSC 67**：**只有金 OA 刊是真 OA**（RSC Advances=`ra`、Chem Sci=`sc`、Nanoscale Adv=`na`、Mater Adv=`ma`、Chem Biol=`cb`、Digital Discovery=`dd`）；**其余 RSC 前缀（`ee`/`cc`/`nj`/`ta`/`dt`/`cs`…）是混合/订阅刊 → route-B 也救不了**（是付费墙，不是过盾问题）。

---

## 二、真 OA 子集预筛法（零成本离线 + 联网复核两道，发射前必做）

**目的**：把 rsc 67 拆成【金 OA→发射】【订阅→不发射】，避免 route-B 烧算力在必 no-pdf 的订阅条。

### 第一道 · 离线零请求（首选，仓内已有能力）
用 **DOI 后缀期刊代码**判金 OA——`publisher_oa._rsc()` 的既有逻辑（`_RSC_GOLD_OA={ra,sc,na,ma,cb,dd}`，`_RSC_RE=^([cd])(\d)([a-z]{2})`）：
- 后缀 `d5ra08493h`→jcode=`ra`→**金 OA、发射**；`c4ra00825a`→`ra`→金 OA。
- 后缀 `d2ee01234a`→`ee`→**订阅、不发射**；`c6cs00066e`→`cs`→订阅。
- **实操**：对 rsc 67 每条 DOI，`build_pdf_candidates(doi)` **非空即金 OA（发射）、空即订阅（不发射）**——零请求、零成本、可离线跑出发射清单。（这也正是 `_find_rsc_oa_152.py`/`_oa_check_144.py` 探针在做的事，可复用。）

### 第二道 · 联网复核（可选、更准，防漏判）
金 OA 刊里也可能有个别非 OA 文章 → 对第一道筛出的金 OA 子集，用 **Unpaywall `is_oa`** 复核（`_oa_check_144.py` 已实现：`GET api.unpaywall.org/v2/{doi}?email=` 看 `is_oa` + `best_oa_location.url_for_pdf` 是否托管 `pubs.rsc.org`）。`is_oa=False` 的从发射清单剔除（留 A5）。
> MDPI 7 同理可 Unpaywall 复核，但 MDPI 近乎全 OA，第一道即可全发。

---

## 三、发射顺序 + 命令（承 route-B-150 §六 checklist + N.1/N.8 铁律）

**前置**（N.5/N.8 运维铁律，缺一必假阳或误判）：
1. **装 `pypdf`**（否则内容 QC 门静默 no-op、100% 放行 → 假阳回潮）；置 `content_qc` 开、`content_qc_non_article_hard_reject=True`。
2. **单机单头浏览器、route-B 全局 concurrency=1**（N.8 #1：多 shim/多头浏览器争用会把 CF 过盾拖成 0 产出）。
3. **过盾纪律**（N.8 #2）：过盾期不开 CDP Fetch/Network 拦截、以 `cf_clearance`+可见文案判过盾、B1 优先 B2 兜底、CDP 双键 monkeypatch。

**顺序**：① MDPI 7（真 OA、Akamai、最稳）→ ② RSC 金 OA 子集（articlepdf、B2）→ ③ 订阅墙**不发**。

```powershell
# 预筛(离线)：对 rsc67 逐条 build_pdf_candidates，非空=金OA写入发射清单 routeB_rsc_goldoa.txt
#   (复用 _find_rsc_oa_152.py / publisher_oa._rsc 逻辑；MDPI7 直接全量入 routeB_mdpi.txt)

# 发射(route-B 默认能力，cf-only，单头串行)：
python -m fulltext_fetcher -f routeB_mdpi.txt        -o out\routeB_A_mdpi  --email you@org.edu --route-b cf-only -c 1
python -m fulltext_fetcher -f routeB_rsc_goldoa.txt  -o out\routeB_A_rsc   --email you@org.edu --route-b cf-only -c 1
#   (若 --route-b CLI 尚未落地[route-B-150 §三待-144/-153]，暂用 env：$env:FTF_BROWSER_CAPTURE="1" 开 ②b)
```

**验收口径**（每条落盘必核）：
- `pdf_bytes[:4]==b"%PDF"` + size 合理 + **`tools/qc_content_match.classify` 非 mismatch**（page-1 DOI＝期望 DOI）。
- RSC 订阅条应落 `no-pdf`/`blocked:challenge-page`（**不得误报假 %PDF**）——这是正确行为，不计失败。
- 真命中经 `_agg_recover_150.py`/`build_coverage` 体检并入净覆盖（source=render/browser_capture 属 DOI 绑定、过内容 QC 后计入）。

---

## 四、给总指挥的一句话排期

**预筛已跑实、清单已产**：route-B 只对 **MDPI 7（先发、走 Akamai）+ RSC 真 OA 8（次发、B2 articlepdf）= 15 条**发射（concurrency=1、装 pypdf、cf-only）；**RSC 其余 59 条订阅/closed 留 route-A（A5，凭据 gate）不发**。清单三份已落 `routeB_mdpi.txt`/`routeB_rsc_goldoa.txt`/`routeB_rsc_subscription.txt`，可直接 `-f`。首要收益是**省算力**（59 条订阅不空跑）；**发射 15 ≠ 回收 15**——真 %PDF 命中按 N.4 诚实口径仍在 +5~15 区间，价值在点亮 JA3 + 从权威落地页提质，非清空 still_missing。

---

## 五、来源

- 桶与墙型：`本波回收交付汇总.md §二/§三`（MDPI 7 Akamai 可救未救、RSC 67 JA3）、`A5机构订阅现状与still_missing可救前缀梳理-150.md §三`（rsc 67/MDPI 7 分桶，分母 628）、`经验记录-踩坑与发现.md` **N.3**（ACS 不绑 JA3 / RSC 绑 JA3）、**N.4/N.8**（route-B B1/B2 + 过盾铁律 + 诚实 ROI）、**K/H.3**（Akamai/CF 桶）。
- 金 OA 判定：`fulltext_fetcher/sources/publisher_oa.py`（`_rsc` `_RSC_GOLD_OA={ra,sc,na,ma,cb,dd}`、`_mdpi`）、探针 `_find_rsc_oa_152.py`/`_oa_check_144.py`（Unpaywall `is_oa` 复核）。
- 发射能力与开关：`选型2026-route-B默认能力集成方案-设计草案-150.md`（cf-only + concurrency=1 + CLI）、`download.py`（②b/⑥）、`render_fetch.py`（`is_ja3_bound_cf_host`/B1/B2）、`路线B-浏览器内直下PDF验证Runbook-173.md`。

---
*核验 2026-07-02｜-150｜工单 task-b291b688「route-B 回收波发射优先级一页纸」｜结论：A 集 74=MDPI 7(真 OA·Akamai·先发)+RSC 67；离线预筛(build_pdf_candidates)+Unpaywall is_oa 复核已跑实 → **route-B 发射波 15 = MDPI 7 + RSC 真 OA 8**(4 RSC Advances + 4 is_oa 命中 hybrid)，RSC 其余 **59 留 A5 不发**；清单三份已产可直接 -f。首要收益=省算力(59 订阅不空跑)；发射 15≠回收 15，真命中按 N.4 诚实口径 +5~15、价值在点亮 JA3+提质。新建 1 md + 3 发射清单 txt，一次性预筛脚本已删，未改任何库 .py。*
