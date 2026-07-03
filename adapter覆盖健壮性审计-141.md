# publisher adapter 覆盖与健壮性审计（141 · 只读）

> 交付：**谷歌学术人机认证-141**（worker）｜task-41fc97fa｜2026-07-03
> 对象：`fulltext_fetcher/publisher_adapter.py`、`sources/publisher_direct.py`、`sources/publisher_oa.py`（各 selftest 均 OK）。
> 边界：**只读审计，未改代码/coverage**；建议供**下一波实施**。承 -174《Wiley pdfdirect URL bug 修复》。

---

## 〇、TL;DR — 总体健壮性评级

**结论：三模块均为生产级健壮**——纯函数、零依赖、**绝不抛异常**、未知前缀/非法 DOI → `[]`、置信度降序去重、离线 selftest 齐全；坏候选由 `download.py` 的 `%PDF` 魔数校验兜底、**不产假成功**。**无 P0 崩溃级缺陷**。风险集中在 **①编码一致性（latent）②三文件工具重复（维护漂移）③OA 白名单/年份启发式时效④少数订阅家缺模板**。

| 级别 | 数量 | 主题 |
|---|--:|---|
| 🟠 **P1（应下波修）** | 3 | 编码仅 Wiley 化（同类 latent bug）；DOI 工具三处重复（Wiley 修复即被迫改 3 处）；adapter↔direct 注册表分叉 |
| 🟡 **P2（优化/时效）** | 5 | RSC 年份启发式 + 金 OA 刊表可能不全；`_ACS_AU_RE` 死代码；pdfdirect/pdf 顺序跨文件不一；OA 白名单需定期刷新；Elsevier PII 仅取 alternative-id |
| ⚪ **Gap（覆盖缺口）** | — | AIP/ECS/IUCr/CSJ 等无静态模板（多订阅/CF → A5，非快赢） |
| ✅ **已修确认** | — | Wiley 遗留 DOI 特殊字符 encode（-174，三文件 selftest 均含 legacy 断言） |

---

## 一、三文件角色（勿混淆）

| 文件 | 角色 | 触发 | 覆盖侧重 |
|---|---|---|---|
| `publisher_adapter.py` | download.py **失败后重试提示**（Accept 头 + 少量稳定模板 + Crossref TDM 解析） | 常开 | 混合/订阅社取法要素 |
| `sources/publisher_direct.py` | **机构订阅直链源**（`@register`） | **仅 `--institutional`** | 订阅/混合社 DOI→直链（含 Crossref 增强：Elsevier PII / MDPI 坐标 / RSC 遗留期） |
| `sources/publisher_oa.py` | **OA 直链源**（`@register`） | 常开 | 仅对可识别 **OA 子集**构造，混合刊 OA 外 `[]` |

> 三者对 ACS/Wiley/Springer/IOP 模板**有意重叠**，接线时按 confidence 去重合并。

---

## 二、逐家覆盖矩阵（现状）

| 出版商 | 前缀 | oa | direct | adapter | OA 判定 / 模板要点 | 现状 |
|---|---|:--:|:--:|:--:|---|---|
| Elsevier | 10.1016/10.1006 | — | ✅(Crossref PII→/pdfft) | 标注 tdm | 无静态模板；PII 取自 `alternative-id` | 稳；见 P2-5 |
| ACS | 10.1021 | ✅ | ✅ | ✅ | 金OA(acsomega/…/*au)高分；**其余全产 conf38 authorchoice** | authorchoice 即 SI 假阳根（下游 QC 处理，非 URL bug） |
| RSC | 10.1039 | ✅(金OA子集) | ✅(年份推断+遗留期 Crossref) | — | 金OA 刊码白名单；`c→2010/d→2020` 年份启发式 | 见 P2-1 |
| Wiley | 10.1002/10.1111 | ✅ | ✅ | ✅ | pdfdirect+pdf；**遗留 DOI 已 encode** | ✅ -174 已修；编码仅此家（P1-1） |
| Springer(+EPJ/Kluwer/Pleiades) | 10.1007/10.1140/10.1023/10.1134 | ✅(1007/1140) | ✅(全 4 前缀) | ✅(1007) | content/pdf/{doi}.pdf | **Kluwer 10.1023 冒号 DOI 未 encode**（P1-1） |
| Nature Portfolio | 10.1038 | ✅(OA 子刊高分) | ✅ | — | s41467/ncomms/s41598/srep→75，余 45 | 稳；npj 金OA 未识别（低分仍构造） |
| MDPI | 10.3390 | ✅(landing) | ✅(Crossref 坐标) | 标注 | DOI 文号长度可变 → 不臆造直链，走 landing/Crossref | 稳（设计合理） |
| IOP | 10.1088 | ✅(金OA ISSN) | **✗** | ✅(模板) | 金OA ISSN 白名单 | **adapter 有模板、direct 无**（P1-3） |
| IEEE | 10.1109 | — | ✗ | ✅(空模板) | 需 arnumber，无 DOI 模板 | 一致返回空（OK） |
| Science/AAAS | 10.1126 | — | ✅ | — | /doi/pdf/{doi} | raw {doi}（P1-1 latent） |
| PNAS | 10.1073 | ✅(conf50) | ✅ | — | /doi/pdf/{doi} | 稳 |
| SAGE/T&F/APS/PNAS/Atypon 系(Physiology/AHA/AnnualRev/Liebert/INFORMS/SIAM) | 10.1177/10.1080/10.1103/10.1152/10.1161/10.1146/10.1089/10.1287/10.1137 | — | ✅ | — | /doi/pdf/{doi}；APS 刊名映射 | raw {doi}（P1-1 latent）；APS 长名优先 ✓ |
| Frontiers/PLOS/PeerJ/eLife/BMC/Copernicus/Beilstein/Hindawi/SciOpen | 10.3389/10.1371/10.7717/10.7554/10.1186/10.5194/10.3762/10.1155/10.26599 | ✅ | — | — | 全 OA 各自模板/landing | 稳；OA 平台改版有 latent 时效风险（低） |

---

## 三、风险点与易错点（逐条 · 文件×行×建议）

### 🟠 P1-1 编码只对 Wiley 生效 → 同类 latent bug（**-174 修的是 Wiley，其余家同构未修**）

- `publisher_adapter.py` **L95**：`doi_for_url = _wiley_doi_path(d) if self.key == "wiley" else d`
- `publisher_direct.py` **L150**：`doi_for_url = _wiley_doi_path(d) if name == "wiley" else d`
- `publisher_oa.py`：`_wiley_doi_path` 仅在 `_wiley_openonline`（L179-186）调用；`_frontiers/_pnas/_acs/_springer_content/_iop/_sciopen` 等 f-string 均塞 **raw `{d}`**。

**问题**：所有 `…/doi/pdf/{doi}`、`content/pdf/{doi}.pdf`、`/article/{doi}/pdf` 模板对含 `< > ; : ( )` 的**遗留 DOI** 会 404/截断——与 -174 修的 Wiley 完全同构。真实命中案例：
- **Springer Kluwer 10.1023**（含冒号，如 `10.1023/a:1015326726898`）——`publisher_direct` selftest **L330 竟断言保留 raw 冒号 URL**，即当前**明确不 encode**，与 Wiley 修复策略矛盾（依赖 Springer 服务端容错，未经真网验证）。
- Science/SAGE/T&F/Atypon 系老刊（<2000 年含 `<>` 的 DOI）同理。

**建议（P1）**：抽一个**通用** `_doi_path(d)`（= 现 `_wiley_doi_path` 逻辑：保留 `prefix/` 间斜杠、`quote(suffix, safe="")`），**对所有 path 内嵌 DOI 的模板统一启用**（不止 Wiley）。现代 clean DOI 输出不变、零回归；遗留 DOI 一并修复。同时补各家 legacy-DOI selftest 断言。

### 🟠 P1-2 DOI 工具三处重复 → 修复漂移风险

`_normalize_doi` / `_split_doi`(或 `_DOI_PREFIX_RE`) / `_wiley_doi_path` 在**三个文件各写一份**。-174 的 Wiley 修复正是被迫**同时改 3 处**——下次任一改动漏一处即静默不一致。

**建议（P1）**：抽 `sources/_doi_utils.py`（或 `publisher_adapter` 内）为**单一真源**，三处 import。附：adapter 用 `_DOI_PREFIX_RE=(10\.\d{4,9})/` + 手工切后缀；两 source 用 `_DOI_SPLIT_RE=^(10\.\d{4,9})/(.+)$`——语义等价但两套实现，合并即消。

### 🟠 P1-3 adapter ↔ publisher_direct 注册表分叉

- IOP：`adapter` 有模板（`iopscience.iop.org/article/{doi}/pdf`，L46），`publisher_direct._SIMPLE` **无 IOP** → 机构模式下 IOP 无静态直链。
- IEEE：`adapter` 有（空模板 L47），`direct` 无。
- Wiley 两链**顺序**：`adapter`=pdfdirect→pdf（L41-42）；`direct`=pdf→pdfdirect（L74-77）；`oa`=pdfdirect→pdf（L184-185）。**三处顺序不一**（影响首选候选）。

**建议（P1）**：明确「谁是模板真源」，或让 `publisher_direct` 复用 adapter 的模板表；统一 pdfdirect/pdf 顺序（建议 pdfdirect 优先——直吐字节、少一跳）。

### 🟡 P2-1 RSC 年份启发式 + 金 OA 刊表时效

- `publisher_direct._rsc`（L119-127）/ `publisher_oa._rsc`（L142-152）：`base=2010 if 'c' else 2020`，即 c0-c9=2010-2019、d0-d9=2020-2029。**边界年可能错**（构造错→miss，不产假成功，低危）。
- `_RSC_RE` 仅认 `[cd]` 开头（L98/L139）；**`b` 世代（2005-2009）无静态**，全落 Crossref 遗留分支（多一次网络）。
- `_RSC_GOLD_OA = {ra,sc,na,ma,cb,dd}`（L138）：可能**漏新金 OA 刊**（如 Energy Adv/RSC Sustainability/Environ Sci: Atmos 等）→ 这些金 OA 刊被当混合、`[]` 不构造（漏免费直链）。

**建议**：金 OA 刊码表加注释「需随 RSC 刊目定期核」；可补 `b` 世代静态映射（base=2005）。

### 🟡 P2-2 `_ACS_AU_RE` 死代码 + `endswith("au")` 过宽

`publisher_oa.py` **L168** 定义 `_ACS_AU_RE` 但**从未引用**；L173 实际用 `token.endswith("au")` 判 *Au 刊——理论上会对任何以 `au` 结尾的 token 误判金 OA（ACS 现无此类，风险低）。**建议**：删死代码，或改用更精确的 *Au 刊 token 集合。

### 🟡 P2-3 ACS authorchoice：对**所有** ACS DOI 产候选（conf 38）

`publisher_oa._acs`（L171-176）：非金 OA 的 ACS 一律产 `pubs.acs.org/doi/pdf/{d}` conf38 `acs-authorchoice`——这正是全项目 **batch6 ACS SI-33 假阳**之源（`/doi/pdf/` 对订阅文常吐 SI 封面）。**非 URL bug**（URL 构造正确），由下游内容 QC 门拦截；此处仅**登记口径联动**，提示保持低分 + QC 门③④⑤不可省。

### 🟡 P2-4 OA 判定为**硬编白名单** → 需定期刷新

Nature OA 前缀（L125）、RSC 金OA 刊码（L138）、IOP 金OA ISSN（L156）、ACS 金OA token（L167）均为**硬编**。出版商新增金 OA 刊后会**静默漏判**（当订阅处理→不构造免费直链）。**建议**：集中成一处常量 + 注释「随刊目季度核」，或加一个「未知子刊落 landing 兜底低分」策略。

### 🟡 P2-5 Elsevier PII 仅取 `alternative-id`

`publisher_direct._elsevier`（L176-186）只从 `alternative-id` 抽 PII；若某记录 PII 仅存于 `resource.primary.URL`（`/pii/Sxxxx`）则漏。**建议**：兜底从 `resource.primary.URL` 正则提 PII（与 `_rsc_legacy` 取刊码同法）。

---

## 四、覆盖缺口（gaps · 语料相关）

| 缺口家 | 前缀 | 语料量级 | 为何未收 | ROI |
|---|---|---|---|---|
| **AIP** | 10.1063/10.1116 | ~3-4（aip 桶） | 需内部 article-id；CF Just-a-moment | 低（订阅/CF → A5/route-B） |
| **ECS** | 10.1149 | 长尾 | IOP 平台托管、需 id | 低（订阅→A5） |
| **IUCr** | 10.1107 | 个案 | 部分金 OA（IUCrJ/Acta E） | 极低（可补 IUCrJ 金 OA landing） |
| **CSJ/OUP/De Gruyter/Cambridge/ASP** | 10.1246/10.1093/10.1515/10.1017/10.1166 | 长尾 | 多订阅 | 极低（A5/无免费解） |

> 结论：缺口家**多为订阅/CF 墙、免费无解 → 归 A5**，非快赢；与全项目「免费天花板 ~40-42%、破局唯 A5」闭环一致。**唯一可考虑的免费补**：IUCrJ 金 OA、RSC 新金 OA 刊码（P2-1）。

---

## 五、改进建议汇总（供下一波实施 · 按 ROI）

1. **【P1·首推】通用 `_doi_path()` 编码**：把 Wiley-only 编码推广到所有 path 内嵌 DOI 的模板（adapter/direct/oa 三处），补 legacy-DOI selftest。零回归、消 latent 404。
2. **【P1】DOI 工具单一真源**：抽 `_doi_utils`，三文件 import；消除「修一处漏两处」。
3. **【P1】注册表收敛**：direct 复用 adapter 模板表；补 direct 的 IOP；统一 pdfdirect/pdf 顺序。
4. **【P2】RSC**：金 OA 刊码表加 `b` 世代静态 + 定期核；年份启发式加注释。
5. **【P2】清死代码 `_ACS_AU_RE`**；`endswith("au")` 收紧。
6. **【P2】Elsevier PII** 兜底从 `resource.primary.URL` 提取。
7. **【P2】OA 白名单**集中 + 季度刷新注记。

> 全部为**健壮性/可维护性/覆盖**优化，**不改净覆盖天花板**（免费直链改进只提「过盾/命中稳定」，订阅墙主体仍 A5-only）。

---

## 六、Wiley bug 已修确认 + 同类扫描结论

-174 修复**正确且到位**（三文件均 encode Wiley 后缀、selftest 含 `10.1002/1099-0739(200012)14:12<836::AID-AOC97>3.0.CO;2-C` legacy 断言、`%3A` 校验）。**但同类隐患未清零**：编码策略**仅绑定 Wiley**（`key=="wiley"` / `name=="wiley"`），其余 path-内嵌-DOI 模板（ACS/Science/Springer-Kluwer/SAGE/T&F/Atypon/IOP/SciOpen）对遗留特殊字符 DOI **仍会 404/截断**（P1-1）。**建议下波把编码通用化以彻底闭合此类 bug**。

---

*141 交付 · 2026-07-03｜只读审计、未改代码/coverage｜结论：三模块生产级健壮、无 P0；风险主为编码仅 Wiley 化(latent)+ 工具三处重复 + 注册表分叉 + OA 白名单时效；缺口家多属 A5-only 非快赢。7 项建议供下波实施，均零净覆盖影响、纯提健壮/可维护。*
