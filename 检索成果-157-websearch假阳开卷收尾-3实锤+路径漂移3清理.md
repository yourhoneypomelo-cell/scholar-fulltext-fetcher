# 检索成果 · 157 — websearch 假阳开卷「收尾」:新实锤 3 条 + 路径漂移 3 行清理建议(HOLD 待属主 merge)

> 沉淀:2026-07-03｜谷歌学术人机认证-157(原 151,`qc_merge_highconf_wrong.csv` 单一编辑者)｜**纯只读探针 + 移交包**,未改 coverage.json / qc_merge / 任何黑名单。
> 纪律:承 169 开卷 SOP(必对最终落盘 PDF 重新开卷核 expected-doi)+ 176 HOLD 移交范式(产 append,不并发写 qc_merge)。所有数字给证据路径、口径写死。

---

## 〇 一句话结论

对 `out/coverage.json` **01:27:42 快照【历史口径】**(净覆盖 **339/999**;⚠️ 当前权威已定版 **326/673/32.63%@2026-07-03 12:50:24**、OCR14 −13)的 websearch(142)+ allow(10)成功项做全量开卷读盘复扫,新逮到 **3 条 169/176 漏网的 websearch 实锤假阳**(开卷坐实落盘是日文电池文档 / NOAA 天气图 / 日本防灾指南,与期望论文毫无关系)。并入硬黑后 **339 → 336**。另发现 **3 条路径漂移过期硬黑行**(allow_override 已救回真全文,硬黑行冗余)建议清理;OCR 桶 14(=176 既有)维持 HOLD。

---

## 一、扫描口径与覆盖(可复现)

- 探针:`_mon157_websearch_openbook_scan.py`(只读)。目标 = 当前 coverage 中 `status=success` 且 `source=websearch`(142)+ `_qc_paths.allow_dois`(10),去重后 **151** 条。
- 判据(承 169 SOP):`doi_in_body` = 期望 DOI 或其尾号(去标点容错)出现在正文正文 → OK(真);否则按风险细分:
  - `SUSPECT-KEEP`:DOI 未检出但 title_overlap 高 → 大概率真(首页为图/老刊未印),**保留不杀**。
  - `SUSPECT-HIGHRISK`:DOI 未检出 + title_overlap ≤ 0.3 + 正文可读(chars≥200) → **高危错文候选,须开卷终裁**。
  - `SUSPECT-UNREADABLE`:chars<200(近空/乱码) → 转 OCR,不判错。
- 明细:`out/_mon157_websearch_openbook_scan.csv`。

### verdict 分布(151 条)

| verdict | 条数 | 处置 |
|---|---:|---|
| OK(正文含期望 DOI) | 98 | 诚实成功,保留 |
| SUSPECT-KEEP(标题高命中) | 36 | 保留不杀(不误杀) |
| SUSPECT-UNREADABLE(chars=0) | 13 | 转 OCR(=176 OCR 桶) |
| **SUSPECT-HIGHRISK** | **3** | **开卷终裁 → 全部坐实错文(见二)** |
| ERROR(加密不可读) | 1 | `10.1021/acs.iecr.4c02255`(27MB,Standard 加密),转换源/OCR |

### 回归校验:硬黑 DOI 是否仍计 success

3 条命中(`10.3390/catal13091244 / catal16020163 / catal16030270`),但**均属 allow_override 正确救回**(见三),**非误计**。除此之外硬黑名单已被 coverage 正确消费,无回归漏网。

---

## 二、新实锤假阳 3 条(开卷坐实,建议并入 hard 黑名单)

清单文件:`out/_mon157_websearch3_hardblack_append.csv`(格式对齐 `qc_merge_highconf_wrong.csv`)。逐条真身证据:

| DOI | batch | 期望论文(coverage.title) | 落盘实为(开卷) | 关键证据 |
|---|---|---|---|---|
| `10.1016/j.catcom.2018.07.014` | batch7 | Impact of acid treatment of CuO-CeO2 catalysts on the preferential oxidation of CO | **日文·蓄電池変換効率技术文档** | 正文 Shift-JIS 日文,通篇「蓄電池/変換効率/使用可能」,无任何 CuO-CeO2/CO 氧化英文;title_overlap=0.0,20 页 |
| `10.1021/acs.iecr.5c03132` | batch4_p5 | From CO2 to Jet Fuel: Techno-Economic and Life-Cycle Assessment | **NOAA 地面天气分析图** | 正文全是经纬度(20S…160W)、ITCZ、MONSOON TROF、GALE/DSIPT/STNRY、台站码;1 页 16364 字坐标数据,与技术经济评估无关 |
| `10.1021/ie020677q` | batch4_p1 | Kinetic Modeling for Methane Reforming with CO2 over a Mixed-Metal Carbide Catalyst | **日本政府·感震ブレーカー/住宅用分電盤 防灾指南** | 正文日文,「感震ブレーカー/住宅用分電盤/防火地域」,含 bousai.go.jp、meti.go.jp 链接;10 页,与甲烷重整动力学无关 |

- 与 169/176 的关系:前两条 169 曾归入「抽取失败/乱码转 OCR」桶(误以为不可读),**实为可读的错文**;第三条(iecr.5c03132)为 176 之后新进、全新漏网。→ 本轮补齐。
- 影响:3 条当前 status=success/source=websearch/qc=null,正计入 339。并入硬黑 → **339 → 336**(≈33.63%)。

---

## 三、路径漂移过期硬黑行 3 条(建议清理,不影响计数)

`10.3390/catal13091244`、`10.3390/catal16020163`、`10.3390/catal16030270` 同时存在于:
- `qc_merge_highconf_wrong.csv`(旧 attempt 抓错文:nature ML 模型 / acscatal Building Enzymes 等,已 hard 黑);
- `_qc_paths.allow_dois`(route-B 后来取回**真全文**,落 `out/routeB_mdpi/pdfs/`,开卷验真 title_overlap 0.9–1.0、正文含期望 DOI)。

即记忆 **N.5「路径漂移 bug」**:allow_override 正确凌驾 hard 黑名单,故计数无误(这 3 条是真成功)。但硬黑名单里留了 3 条指向旧错 PDF 的**冗余过期行**,数据脏、易误读。
**建议**:属主可删除这 3 条 hard 行(allow 已接管、真全文已验),或加注说明;优先级低。

---

## 四、维持 HOLD 的桶(非本轮处置)

- **OCR 不可验证 14**(本扫 13 条 chars=0 + 1 条加密 ERROR)= 176 既有 OCR 桶,alnum=0 非错文实锤,**转 OCR/换源**后再裁,维持 HOLD。清单见 `out/_mon157_websearch_openbook_scan.csv` 的 `SUSPECT-UNREADABLE`/`ERROR` 行。
- **SUSPECT-KEEP 36**:title_overlap 高、大概率真(DOI 首页为图/老刊未印),**一律保留不误杀**(如 cr970037a、b918763b、susc.2005.08.015 等,与 169 N.4「可能真但 DOI 未抽到」策略一致)。

---

## 五、属主 merge checklist(建议由总指挥 141 统筹,与 149/142 在办 coverage 工作批量一次性 rerun,避免并发抖动)

- [ ] 将 `out/_mon157_websearch3_hardblack_append.csv` 3 行并入 `out/qc_merge_highconf_wrong.csv`。
- [ ]（可选清理)删除 catal13091244 / catal16020163 / catal16030270 的过期 hard 行(allow 已接管)。
- [ ] 重跑 `python tools/build_coverage.py` → 预期 `success_after_qc` **339 → 336**、`hard_list_dois` +3。
- [ ] 更新《基线口径冻结说明-388-173.md》与《项目索引.md》口径脚注(带新 generated_ts)。
- [ ] OCR 桶 14 仍 HOLD,另排 OCR 复核。

---

## 六、交付物索引

| 文件 | 说明 |
|---|---|
| `_mon157_websearch_openbook_scan.py` | 收尾开卷扫描器(只读,含回归校验 + 高危细分) |
| `_mon157_deepread_highrisk.py` | 3 条高危逐条开卷深读(取证) |
| `out/_mon157_websearch_openbook_scan.csv` | 151 条全量明细(verdict/doi_in_body/title_overlap/…) |
| `out/_mon157_websearch3_hardblack_append.csv` | **3 实锤 append(待 merge)** |
| 本文 | 收尾结论 + merge checklist |

---

*157｜2026-07-03｜纯只读探针 + 移交包;未改任何 .py 生产码 / coverage.json / qc_merge / PDF。3 实锤明细见 append CSV,全量见 scan CSV。口径基于 coverage generated_ts 2026-07-03 01:27:42(339/999)。*
