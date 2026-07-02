# 检索成果 · still_missing 620「其他同源 OA 站点」route-B B1 候选梳理（除 MDPI7 / RSC8 外）

> 交付：**谷歌学术人机认证-146**（worker）→ 总指挥 **-144**｜2026-07-02｜taskId=`task-427d53d4-ea6e-4e0b-b1a4-97d6edc353fa`
> 边界：**纯只读分析，只新建本 1 份 md，未改任何 `.py`、未跑网络、未回写 coverage**。数据取自 `out/still_missing.txt`（620，头 2 行注释）、`fulltext_fetcher/sources/publisher_oa.py`（`_BUILDERS`/`COVERED_PUBLISHERS`）、`fulltext_fetcher/render_fetch.py`（`_JA3_BOUND_CF_HOSTS`/B1/B2 机制）、`检索成果-路线B回收波发射优先级-A集rsc67MDPI7-150.md`、`检索成果-still_missing620机制横切分桶与下一波ROI优先级-142.md`、`A5机构订阅现状与still_missing可救前缀梳理-150.md`。
> **口径纪律**：发射/过盾/success ≠ 净增；**"需 route-B"特指"必须过 JA3/强 CF 盾才能拿到同源 PDF 字节"**——普通 OA 站点用 `publisher_oa` 同源直链 + 常规 `http_client` 即可，不占 route-B 有头浏览器算力。

---

## 〇、TL;DR（给总指挥的一页）

- **核心结论（负结果、极省算力）**：除已梳的 **MDPI 7**（走 download.py ⑥ Akamai）+ **RSC 金 OA 8**（走 render b2/b2-fetch）外，still_missing 620 里**没有其他成规模的同源 OA 站点桶**；**适合 route-B B1「同源直取」的新增候选 = 空集（诚实点估 +0）**。A 集（MDPI7+RSC8=15）已把 route-B 的免费增量基本穷尽。
- **数据实证**：经典纯 OA 出版商前缀在 620 中**存量几乎全为 0**——Frontiers `10.3389`=0、PLOS `10.1371`=0、PeerJ `10.7717`=0、eLife `10.7554`=0、BMC `10.1186`=0、Copernicus `10.5194`=0、Beilstein `10.3762`=0、PNAS `10.1073`=0。**仅剩 3 条边缘个案**：Hindawi 1、IUCr 1、Nano Research(SciOpen) 1。
- **代码实证**：`render_fetch._JA3_BOUND_CF_HOSTS` 只含 **4 家强 CF 站**（`pubs.rsc.org` / `sciencedirect` / `onlinelibrary.wiley.com` / `pubs.acs.org`），源码注释明写「**普通 OA 站不必走这条重路径**」；而 `publisher_oa` 已为 **16 家主流 OA 出版商内建同源免费 PDF 直链构造器**（`COVERED_PUBLISHERS`）。→ 普通 OA 站点**已有免费源、设计上就不进 route-B**。
- **为什么 OA 站点几乎不进 still_missing**：它们无强盾、PDF 同源免费，`publisher_oa` 直链一步到位；能滞留的只是「个别撤稿/迁移/缺模板」的长尾例外——修复方式是**常规源重试 / 补 publisher_direct 模板 / A5**，**不是 route-B**。
- **下一波建议**：route-B **不必为「其他同源 OA 站点」单独发射**；剩余 OA 长尾（≤6 条，见 §五/§六）全部走常规免费源 / 补模板 / A5 消化，**route-B B1 专属新增净增 = +0（诚实点估）**，顺带的非-routeB 免费长尾至多 **+1~3**。

---

## 一、方法与判定口径

**数据面**：对 `out/still_missing.txt`（620 条，metadata.success AND pdf 未落盘）做全量前缀分桶，逐一核对所有纯 OA / 混合 OA 出版商前缀的存量（精确正则匹配，非估算）。

**代码面**：核对两处仓内事实——
- `publisher_oa._BUILDERS`：哪些出版商已有**免费 OA 候选构造器**（决定"是否已有免费源即可"）。
- `render_fetch._JA3_BOUND_CF_HOSTS` + B1/B2 机制：route-B 重路径的**唯一适用域**（决定"是否需 route-B"）。

**route-B B1 的严格定义**（`render_fetch.py` L520–548, L736–742）：在**已过 CF 的文章页上下文**里发起 `fetch(pdfUrl).arrayBuffer()`，继承其 cookie + JA3 —— **要求 PDF 与文章页同源**（否则 CSP/跨源 fail，退 B2 Network 域 / b2-fetch）。故 B1 的价值域 = **「强 CF 盾 + 同源免费/金 OA 正文」**。

**逐条判定四问**：① 是否真 OA？② PDF 是否与 landing 同源？③ 是否被强 CF/JA3 盾挡（=route-B 才有价值）？④ 是否已有免费源可拿（=不需 route-B）？四问同时满足「OA + 同源 + 有强盾 + 无既有免费源」才算 route-B B1 的**合格新增候选**。

---

## 二、经典纯 OA 站点存量核查（数据面 · 决定性）

> 存量 = 精确匹配 `out/still_missing.txt` 的条数；构造器 = `publisher_oa._BUILDERS` 是否已内建免费直链；同源性 = 该构造器产出的 PDF URL 是否与文章 landing 同域。

| 出版商 | 前缀 | still_missing 存量 | publisher_oa 构造器 | 免费 PDF 同源性 | 结论 |
|---|---|:--:|---|---|---|
| Frontiers | 10.3389 | **0** | `_frontiers` → `frontiersin.org/articles/{doi}/pdf` | ✅ 同源直链 | 已被免费源摘净、无残留 |
| PLOS | 10.1371 | **0** | `_plos` → `journals.plos.org/.../article/file` | ✅ 同源 | 同上 |
| PeerJ | 10.7717 | **0** | `_peerj` → `peerj.com/articles/{id}.pdf` | ✅ 同源 | 同上 |
| eLife | 10.7554 | **0** | `_elife` → `elifesciences.org/articles/{id}.pdf` | ✅ 同源 | 同上 |
| BMC | 10.1186 | **0** | `_springer_content` → `link.springer.com/content/pdf` | ✅ 同源 | 同上 |
| Copernicus | 10.5194 | **0** | `_copernicus` → `{j}.copernicus.org/.../*.pdf` | ✅ 同源 | 同上 |
| Beilstein | 10.3762 | **0** | `_beilstein` → landing（PDF 需内部 id） | landing 抽取 | 同上 |
| PNAS | 10.1073 | **0** | `_pnas` → `pnas.org/doi/pdf/{doi}` | ✅ 同源 | 同上 |
| **MDPI** | 10.3390 | **7** | `_mdpi` → landing→selector 抽 `/pdf` | ✅ 同源（Akamai） | **已梳（A 集，走 ⑥ 非 B1）** |
| **Hindawi** | 10.1155 | **1** | `_hindawi` → landing | ⚠️ PDF 疑独立下载域 | 边缘个案，见 §四 |

**读数**：`10.3389/10.1371/10.7717/10.7554/10.1186/10.5194/10.3762/10.1073` **全部 0 条**。这正是 §一 代码面的必然结果——**这些站点 `publisher_oa` 已有同源免费直链、无强盾，抓取一步成功 → 根本不会进 still_missing**。它们在 620 中存量为 0，本身就证明「同源 OA 站点桶已被免费源摘干净」。

---

## 三、route-B B1 适用域的代码边界（代码面 · 决定性）

**事实 1 — route-B 重路径只服务 4 家强 CF 站**（`render_fetch.py` L392–397）：

```392:397:fulltext_fetcher/render_fetch.py
# JA3 绑定型强 CF 站(仅这些走浏览器内直下重路径;普通 OA 站不必走这条重路径)
_JA3_BOUND_CF_HOSTS = (
    "pubs.rsc.org", "rsc.org",
    "sciencedirect.com", "pdf.sciencedirectassets.com", "sciencedirectassets.com",
    "onlinelibrary.wiley.com", "pubs.acs.org",
)
```

即 route-B（含 B1）在设计上**只对 RSC / ScienceDirect / Wiley / ACS 启用**；**普通 OA 站点（Frontiers/PLOS/MDPI/Hindawi/…）不走这条重路径**（selftest 亦明确 `assert not is_ja3_bound_cf_host("https://www.mdpi.com/x")`）。MDPI 之所以能救，是走 `download.py` ⑥ `_browser_pdf_download`（过 Akamai 下载环），**不是** render 的 JA3 route-B。

**事实 2 — 4 家强 CF 站里，B1 严格同源直取的免费对象也已见底**：

| 强 CF 站 | still_missing 量 | 免费正文可 B1 直取？ | 归属 |
|---|:--:|---|---|
| **RSC** `pubs.rsc.org` | 67 | 金 OA 8 —— 但 RSC 的 B1 页内 fetch **因 CSP/跨源 fail**，实际走 **b2-fetch**（-152 实证 484KB），非严格 B1 | **A 集已含**（RSC 金 OA 8） |
| **ScienceDirect** | 375 | ❌ 全订阅墙、无免费正文（browser_search 0/10、wayback 0/12 证顶） | A5（凭据 gate） |
| **Wiley** `onlinelibrary.wiley.com` | 22 | OnlineOpen OA 子集**同源**、理论可 B1；但归 **CF-soft / FS-shim 波**（-145/-155），非 route-B 新增 | -145/-155 |
| **ACS** `pubs.acs.org` | 91 | B1 同源已证（acsomega 13.7MB）；**但 still_missing 的 ACS 91 条无一金 OA token**（`acsomega/acscentsci/jacsau/*au` 精确匹配 = 0 命中），全订阅/AuthorChoice（~93% 是 SI 陷阱，O.3）→ **B1 新增 = 0**；免费子集归 -145/-155 | -145/-155（防 SI 假阳） |

**结论**：即使在 route-B 的适用域内，**B1「同源直取」的新增免费对象也 = 0**——RSC 金 OA 已在 A 集（且走 b2-fetch）、ScienceDirect 全订阅、Wiley/ACS 免费子集归 CF-soft/FS-shim 波（-145/-155）。**route-B B1 不产生 A 集之外的新发射对象。**

---

## 四、边缘个案逐条判定（3 条）

| DOI | 出版商/平台 | 是否 OA | 同源？ | 有强盾？ | 需 route-B？ | 处置 | 净增点估 |
|---|---|---|---|---|:--:|---|:--:|
| `10.1155/2014/690514` | **Hindawi**（现属 Wiley） | 是（CC-BY） | ⚠️ PDF 疑独立下载域 `downloads.hindawi.com` / 已迁 `onlinelibrary.wiley.com`（**与 doi landing 不同源**，待联网复核） | 疑 CF（Wiley 系） | **否** | `_hindawi` 已产 landing 候选 → **常规 landing selector / Unpaywall 重试**；2014 老文疑撤稿/迁移，先常规源探 | +0~1 |
| `10.1107/s0108768194013327` | **IUCr**（Acta Cryst B，1994） | **否**（Acta Cryst B 为**订阅刊**；IUCr 的 OA 是 IUCrJ/Acta Cryst E） | — | — | **否** | 订阅老刊 → **A5 / 长尾封存**（route-B 救不了付费墙） | 0 |
| `10.26599/nr.2025.94907426` | **Nano Research**（Tsinghua SciOpen，2025） | 混合刊（该文 OA 状态**待核**） | ✅ SciOpen `sciopen.com` 通常同源 | 疑无强盾 | **否** | 失败大概率是**缺 `10.26599`/SciOpen 模板（no-candidates）**而非被盾挡 → **补 publisher_direct 模板 / 常规抓取**；SciOpen 无 CF-JA3，不必 route-B | +0~1 |

**要点**：3 条边缘个案**无一是 route-B B1 的合格新增候选**——IUCr 非 OA（订阅）；Hindawi 非同源且已有 `_hindawi` 常规候选；Nano Research 是缺模板而非过盾问题。**它们的正确出口是常规免费源 / 补模板 / A5，均不占 route-B 算力。**

---

## 五、顺带清点 · 中文/学会免费平台（非 OA-站点桶、非 route-B）

620 长尾里另有 4 条「**免费全文但无标准 OA 直链、且无强盾**」的条目，属 `publisher_direct` 模板缺口（`no-candidates`），**同样不需 route-B**：

| DOI | 平台 | 免费性 | 出口（非 route-B） |
|---|---|---|---|
| `10.1595/003214097x414166170` | Johnson Matthey（Platinum Metals Rev / Technology Rev，`technology.matthey.com`） | 免费 OA 平台 | 补模板 / 常规源 |
| `10.3866/pku.whxb202304003` | 物理化学学报（`whxb.pku.edu.cn`） | 中文自有平台多免费 | 补模板 / 常规源 |
| `10.7503/cjcu20230268` | 高等学校化学学报 | 中文自有平台 | 补模板 / 常规源 |
| `10.11862/cjic.2023.195` | 无机化学学报 | 中文自有平台 | 补模板 / 常规源 |

> 这批与 `A5-150 §四 缺口3 / -142 §二 publisher_direct 缺口`同源，归 **-141/-153 补口波**（近零代码成本、离线 selftest 可验），**免费净增 +0~4（诚实点估 +1~2）**、**不归 route-B**。

---

## 六、净增与「是否需 route-B」总表（本任务核心交付）

| 桶 | 条数 | 是否 route-B B1 合格候选 | 是否需 route-B | 正确出口 | 免费净增点估 |
|---|:--:|:--:|:--:|---|:--:|
| **经典纯 OA 站点**（Frontiers/PLOS/PeerJ/eLife/BMC/Copernicus/Beilstein/PNAS） | **0** | — | 否 | 已被 `publisher_oa` 同源直链摘净 | 0（无残留） |
| **MDPI** `10.3390` | 7 | 否（走 ⑥ Akamai） | 是（Akamai，非 JA3） | **A 集已含** | （已计 A 集 +5~7） |
| **RSC 金 OA** | 8 | 否（走 b2-fetch） | 是（JA3 强 CF） | **A 集已含** | （已计 A 集 +3~8） |
| **Hindawi** `10.1155` | 1 | ❌ 非同源 | 否 | 常规 landing/Unpaywall 重试 | +0~1 |
| **Nano Research** `10.26599` | 1 | ❌ 缺模板非盾挡 | 否 | 补 SciOpen 模板/常规 | +0~1 |
| **IUCr** `10.1107` | 1 | ❌ 非 OA（订阅） | 否 | A5/封存 | 0 |
| **中文/学会免费** `10.1595/10.3866/10.7503/10.11862` | 4 | ❌ 无盾缺模板 | 否 | 补 publisher_direct 模板/常规 | +0~4 |
| **route-B B1 专属新增（除 MDPI7/RSC8 外）** | **0** | — | — | — | **+0（诚实点估）** |

**一句话**：**除 MDPI7/RSC8 外，route-B B1 的新增同源 OA 候选 = 空集**；剩余 OA 长尾（Hindawi 1 + Nano Research 1 + 中文/学会免费 4 + IUCr 订阅 1，共 7 条）**全部走常规免费源 / 补模板 / A5，不占 route-B 算力**，其中真免费净增诚实点估 **+1~3**（且不需 route-B）。

---

## 七、给总指挥（-144）的收口建议

1. **route-B 下一波不必扩清单**：A 集（`routeB_mdpi.txt` 7 + `routeB_rsc_goldoa.txt` 8 = 15）已穷尽 route-B 的免费增量；**「其他同源 OA 站点」实证为空集，勿为其单独发射有头浏览器**（省算力 = 首要收益）。
2. **剩余 OA 长尾分流**（均非 route-B）：Hindawi 1 + Nano Research 1 → 交常规免费源/补模板波先探（-141/-153）；中文/学会免费 4 → 并入 `publisher_direct` 补口波（-141/-153，近零代码、离线可验）；IUCr 1（订阅）→ A5/封存。
3. **口径护栏**：本梳理是**负结果**——「620 里没有隐藏的 OA 站点大桶」与前作 `-150/-142/-173`「620 = 订阅墙主体(~500) + MDPI7 OA + 长尾」**同阶未漂**；免费天花板仍 ~39~42% 净覆盖，破此上限唯 A5 机构订阅。

---

## 八、来源

- **数据**：`out/still_missing.txt`（620，2026-07-02 18:25:56；全量前缀分桶见附录）；精确匹配核查 `10.3389/10.1371/10.7717/10.7554/10.1186/10.5194/10.3762/10.1073` 各 0 条、`10.1155/10.1107/10.26599` 各 1 条、ACS 金 OA token（`acsomega/acscentsci/jacsau/*au`）0 命中。
- **代码**：`fulltext_fetcher/sources/publisher_oa.py`（`_BUILDERS` 16 构造器 + `COVERED_PUBLISHERS` + 各社 PDF 直链同源性）；`fulltext_fetcher/render_fetch.py`（`_JA3_BOUND_CF_HOSTS` L392–397、B1/B2/b2-fetch 机制 L520–548/L736–748、`is_ja3_bound_cf_host` L413–423、selftest L931–937）。
- **对齐引用（不重画 publisher 桶表）**：`检索成果-路线B回收波发射优先级-A集rsc67MDPI7-150.md`（A 集 15 实跑）、`检索成果-still_missing620机制横切分桶与下一波ROI优先级-142.md`（620 机制横切）、`A5机构订阅现状与still_missing可救前缀梳理-150.md`（A5 可救 Top10 + 缺口）、`经验记录-踩坑与发现.md` N.3/N.4/N.8（ACS 不绑 JA3 / RSC 绑 JA3 / route-B ROI）、O.3（ACS `/doi/pdf` ~93% SI）。

---

### 附录 · still_missing 620 全量前缀分桶（自洽可核验）

| 前缀 | 出版商 | 条数 | 墙型 | route-B B1 相关性 |
|---|---|:--:|---|---|
| 10.1016 | Elsevier(ScienceDirect) | 370 | IP/登录墙(非CF) | ❌ 全订阅、A5 |
| 10.1021 | ACS | 91 | CF-soft(不绑JA3) | 免费子集归 -145/-155（无金OA token） |
| 10.1039 | RSC(含老刊 tf/a/b) | 67 | JA3 强 CF | 金 OA 8 已在 A 集；余 59 订阅→A5 |
| 10.1002+10.1111 | Wiley | 22 | CF-soft | OnlineOpen 子集归 -145/-155 |
| 10.1007+10.1023+10.1134 | Springer 系 | 23 | 常规订阅 | ❌ 全订阅、A5 |
| 10.1006 | Elsevier 旧刊 | 5 | 订阅 | ❌ A5（模板缺口） |
| 10.1063+10.1116 | AIP/AVS | 4 | CF-soft | OA 子集归 -145/-155 |
| 10.1166 | ASP(JNN) | 4 | 订阅小社 | ❌ A5/封存 |
| 10.1246 | CSJ(Chem Lett→OUP) | 4 | 订阅 | ❌ A5/封存 |
| 10.3390 | **MDPI** | **7** | Akamai(真OA) | **A 集（走 ⑥）** |
| 10.1088+10.1149+10.35848 | IOP 家族 | 3 | 订阅(金OA子集小) | 金 OA 常规重跑 |
| 10.1080 | T&F | 3 | CF-soft | OA 子集归 -145/-155 |
| 10.1155 | **Hindawi** | **1** | 疑CF(全OA) | 边缘个案(非同源)→常规 |
| 10.1107 | IUCr | 1 | 订阅 | ❌ 非OA→A5 |
| 10.26599 | Nano Research(SciOpen) | 1 | 疑无盾(混合) | 边缘个案(缺模板)→补模板 |
| 10.1595 | Johnson Matthey | 1 | 免费平台 | 非route-B→补模板 |
| 10.3866 | WHXB(物化学报) | 1 | 中文免费 | 非route-B→补模板 |
| 10.7503 | cjcu(高校化学学报) | 1 | 中文免费 | 非route-B→补模板 |
| 10.11862 | cjic(无机化学学报) | 1 | 中文免费 | 非route-B→补模板 |
| 10.1017 / 10.1038 / 10.1070 / 10.1093 / 10.1109 / 10.1126 / 10.1146 / 10.1515 / 10.2113 / 10.2138 | Cambridge/Nature/Turpion/OUP/IEEE/Science/AnnualRev/DeGruyter/GSW/MinSocAm 各 1 | 10 | 订阅为主 | ❌ 多 A5/封存 |
| **合计** | | **620** | | **route-B B1 新增 = 0** |

> 求和校验：370+91+67+22+23+5+4+4+4+7+3+3+1+1+1+1+1+1+1+10 = **620** ✓（对齐 `coverage.miss=620` / still_missing.txt 头 / shard 并集）。

---
*核验 2026-07-02｜-146 worker · 工单 task-427d53d4｜纯只读、未改 .py / 未跑网｜结论：除 MDPI7(走⑥)/RSC 金OA8(走b2-fetch)外，still_missing 620 中 route-B B1「同源 OA 直取」新增候选 = 空集(+0)——经典纯 OA 前缀(Frontiers/PLOS/PeerJ/eLife/BMC/Copernicus/Beilstein/PNAS)存量全 0(已被 publisher_oa 同源直链摘净)、代码上 _JA3_BOUND_CF_HOSTS 仅 4 家强 CF 站(普通 OA 站不走重路径)、ACS 91 无金OA token；剩余 OA 长尾 7 条(Hindawi/Nano Research/中文学会免费/IUCr)全走常规源/补模板/A5、免费净增诚实 +1~3、不占 route-B 算力。建议 route-B 下一波不扩清单。*
