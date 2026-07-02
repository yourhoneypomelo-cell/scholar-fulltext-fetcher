# 验证 · CF/FS-shim 免费回收三桶(acs/wiley/aip)真全文净增结算 + acs-authorchoice SI 假阳定量 + 生产 SI 门漏检定位

> 交付:谷歌学术人机认证-145 ｜ 2026-07-02 ｜ 我的 lane = CF/FS-shim 回收(ACS/wiley/aip 桶)结算
> 口径:**严格诚实、以 PDF 全页内容为准**。复用生产门 `download._content_qc_verdict / _content_qc_non_article_reject`(与 pipeline 完全同逻辑)+ 全页稳健重分类交叉核验。
> 纯读 out/ 与 PDF,**不改任何核心码、不动任何 PDF/metadata**。数据源:`out/rerun_acs_144/fetch/metadata.jsonl`(-144 跑批产物)。
> 关联:经验记录 **M.1③**(acs-authorchoice 5/5 全 SI)、**M.2 / N.5**(跑批 success 率 ≠ 真全文净增)、**N.3**(ACS 不绑 JA3)、`本波回收交付汇总.md`(acs 桶待补数据)。

---

## 〇、一句话

CF/FS-shim「免费回收」三桶(-144 的 acs/wiley/aip,共 120 条 still_missing)跑批 `success=57`,但**内容全页逐条甄别后真·正文净增仅 5 篇**、**flaresolverr 直破 Cloudflare 真救回 = 0**。主桶 rerun_acs_144:`success=56/95(59%)` → **真净增 N=4(4.2%)、假阳 M=52**,其中 **51 篇是 ACS 免费"Supporting Information(SI)"冒充正文**、**1 篇是错文件**(某设备 USER MANUAL 扫描件)。这把经验记录 M.2「recover_b4_cf 真全文 ≈4%」的结论**在 ACS still_missing 全桶上再次证实并放大**。顺带精确定位了生产 SI 门(`_content_qc_non_article_reject`)**漏检 7 条 SI 的三个具体机理**,可直接交门 owner(-140/-147)修。

---

## 一、跑批 success=56 的真实构成(全页内容复核)

| 类别 | 条数 | 说明 |
|---|---:|---|
| **真·正文全文(N)** | **4** | `acscatal.0c04429`(14 页,Abstract/Intro/Results&Disc/Exp/Concl/Ref 全)、`ja509214d`(42 页,多章节)、`acs.energyfuels.5c06101`(7 页)、`acs.langmuir.7b03998`(8 页)——首页均为**论文标题页**(非 SI 封面)、非错文件;后两条正文抽取差(短文/双栏)但首页确为论文标题 |
| **SI 冒充正文(假阳)** | **51** | ACS `pubs.acs.org/doi/pdf/{doi}` 对**非 OA 正文**返回的是**免费的 Supporting Information**;全页扫描确认纯 SI(0 条捆绑正文),其中 44 条生产门已判、7 条被生产门漏判(见 §三) |
| **错文件(假阳)** | **1** | `10.1021/j100144a026` 期望《Thermal and photoinduced dissociation of ethyl iodide》,实得 60 页扫描件「**USER MANUAL for PFMS GPF Module**」——完全无关文档(源=websearch),应判 mismatch |
| 合计 | 56 | acs-authorchoice 54 + wayback 1 + websearch 1 |

- **真·净增 N=4 / 假阳 M=52**;**净增率 = 4/95 ≈ 4.2%**(对比跑批口径 56/95 = 59%,虚高 14×)。逐条甄别表见 `out/rerun_acs_144_screen56_145.csv`,应扣 DOI 见 `out/rerun_acs_144_deduct_dois_145.txt`。
- **flaresolverr_recovered = 0**:by_source 无 flaresolverr;且本机盘点时 8191 无监听、无 nodriver chrome 进程——**这批 56 全是 acs-authorchoice `/doi/pdf/` 直构碰运气,不是 FS 破 CF**。与 M.2 / N.5 「FS 真救 CF=0」一致。
- 其余 **39/95 硬 miss = `cloudflare-challenge(http-403)`**:ACS `/doi/pdf/` 站前置 Cloudflare,多数条目连 SI 都拿不到。

---

## 二、根因:acs-authorchoice 源系统性下到"免费 SI",不是正文

- **机制**:`publisher_oa.py::_acs()`(L167)对所有非金牌 OA 的 ACS DOI 一律构造 `https://pubs.acs.org/doi/pdf/{doi}`(confidence 38, tag `acs-authorchoice`)。对**真 author-choice/OA** 正文,该 URL 给正文(≈4 条);对**订阅正文**,ACS 免费开放的是 **SI**,该 URL(或其重定向)落到 SI PDF → 下载器只校 `%PDF`+体积 → 记 success。
- **量级**:本桶 acs-authorchoice「success」51/55 ≈ **93% 是 SI**,仅 ≈4 条真正文。与 M.1③ recover_b4_cf「5/5 全 SI」同源、样本更大。
- **结论**:`acs-authorchoice` 是**高 SI 假阳源**,其 success **绝不可直接计入全文净覆盖**;必须过硬化 SI 门(见 §三)或在 coverage 侧剔除。

---

## 三、生产 SI 门 `_content_qc_non_article_reject` 漏检 7 条——三个精确机理(给门 owner -140/-147)

生产门对 44/51 SI 判 `non-article-si` 正确;**漏掉 7 条**,逐条定位机理如下(首页首 500 字信号实测):

| DOI | 首页开头 | 漏因 |
|---|---|---|
| `acs.joc.4c00727` | `Supplementary Information …` | **(A) 只认 "supporting information",未认 "supplementary information"** |
| `jacs.0c12689` | `1 Supplementary Information …` | (A) 同上 |
| `acs.jpclett.4c00005` | `S1Supporting Information …` | **(B) `and not has_body` 过度抑制**:SI 前 2 页含 "Introduction/Experimental" 等章节词 → has_body=True → SI 判定被压掉 |
| `acscatal.0c02146` | `S1 Supporting information …` | (B) 同上(has_body=True) |
| `acscatal.6b00397` | `S1 Supporting information for …` | **(C) 空白变体**:抽取出 "Supporting  information"(多空格/换行)→ 字面子串 `"supporting information"` 不命中 |
| `es501021u` | `S1Efficient Utilization…` | **(C) 粘连页码**:仅 "S1" 紧贴标题、无 "Supporting" 短语;S-head 正则 `^\s*s-?\d+\s*[.\)]` 要求数字后跟 `.`/`)`,"S1Efficient" 有字母→不命中 |
| `jacs.2c13784` | `S1SupportingInformationfor …` | (C) **全粘连无空格** "S1SupportingInformationfor" → 短语与 S-head 正则双双失配 |

**建议修法(3 条,保守、不误杀真正文)**:
1. **(A)** SI 短语集合加 `"supplementary information"` / `"supplementary materials"`(与 "supporting information" 并列)。
2. **(B)** 当**首 ~120 字即以 SI 封面标记开头**(`^\s*\d?\s*S-?\d*\s*(supporting|supplementary)\s*info`)时,**优先判 SI,不被 has_body 抑制**(SI 正文常复述 Experimental/Introduction,不能因此放行)。真正文首页是**标题页**,不会以 "Supporting/Supplementary Information" 开头,故不误杀(§一 4 条真正文首 500 字均无此开头)。
3. **(C)** 判 SI 前对首页文本做**空白归一 + 去粘连**(把 "S1Supporting"→"S1 Supporting"、折叠多空格);S-head 正则放宽为容忍数字后紧跟字母的页码前缀 `^\s*s-?\d+(?=\s*[A-Za-z])` **但仅当同页出现 supporting/supplementary 或无正文标题特征时**,避免误伤以 "1 Title…" 开头的正文首页。

> 已附机器可读证据:`out/rerun_acs_144_reclass_145.json`(`prod_leaks` 字段列出 7 条 + 首 60 字)。此 7 条可作**门回归负样本**(修门后必须判 `non-article-si`),对齐 L.6 数据回归风格。

---

## 四、对 coverage 口径的影响(给 -150/-140)

- `out/rerun_acs_144/coverage.json` 现报 `success=15`(全局 QC 黑名单已剔 41)。但全页复核显示**真正文仅 4**(`acscatal.0c04429` / `ja509214d` / `acs.energyfuels.5c06101` / `acs.langmuir.7b03998`,均 acs-authorchoice 真 OA),故该 15 仍**虚高 11**(= 7 门漏 SI + 4 其它)。
- **56 条逐条甄别表**:`out/rerun_acs_144_screen56_145.csv`(每条:verdict / falsepos_type / robust / 生产门 reason / 源 / 页数 / bytes / doi_in_text / 首行)。
- **应从净成功扣除的 52 条假阳 DOI** 已导出:`out/rerun_acs_144_deduct_dois_145.txt`(51 SI-only + 1 wrong-file `j100144a026`),供 `build_coverage` / `qc_move_rejected` 黑名单消费,使净覆盖不被假阳计入。(另 `rerun_acs_144_si_reject_145.txt` = 纯 51 SI 子集。)
- **真净增 N = 4 / 假阳 M = 52 / 合计 56**。**口径提醒**:全局净覆盖(-150 `out/coverage.json` 448/999)**未随本核验变动**——本桶 success 本就没进主库净成功(rerun_acs_144 是独立 -o 目录);此处澄清「acs 桶 CF/FS 回收真·净增 = 4,而非 56/15」,供《本波回收交付汇总.md》第五节「acs FS-shim 重跑净回收数」据实填 **4**,并供正在回写 coverage 的成员按 `deduct_dois` 扣除假阳后再定 +N。

---

## 四·补、wiley / aip 桶同法结算(补齐 CF/FS-shim 三桶)

同法全页复核 -144 的另两桶:

| 桶 | 跑批 success | 真·正文净增 | flaresolverr 真破 CF | 说明 |
|---|---:|---:|---:|---|
| acs(rerun_acs_144) | 56/95 | **4** | 0 | 假阳 52:51 SI + 1 错文件(见 §一~三) |
| wiley(rerun_wiley_144) | 1/22 | **1** | 0 | 唯一 success `10.1002/anie.201406637`(4 页 Angew 通讯,真正文)——来源 **semantic_scholar**(DOI-keyed OA),非 FS 破 CF;其余 21 CF/订阅墙 miss |
| aip(rerun_aip_144) | 0/3 | **0** | 0 | 全 miss |
| **合计** | **57/120** | **5** | **0** | — |

**三桶铁证**:CF/FS-shim「免费回收」波(acs+wiley+aip 共 120 条 still_missing)真·正文净增 **5 篇**,且 **flaresolverr 直破 Cloudflare 真救回 = 0**(5 篇全来自绿 OA 源:acs-authorchoice 真 OA 子集 4 + S2 1)。彻底坐实 N.5 /「CF 免费路线到顶」——**FS-shim 对订阅正文墙无效,真正文仍需机构订阅 A5**。

## 四·补2、【headline 级】主语料 batch6 权威 coverage 混入 34 条 ACS SI 假阳(净覆盖虚高 ~3.4pp)

> rerun_acs_144 是独立 -o 目录、不进主库;但同样的 acs-authorchoice SI 假阳**在主语料 batch6 里进了权威 `out/coverage.json`**,直接虚高 headline 净覆盖。**已全页确认、非误判**。

- **batch6 acs-authorchoice success = 52**,全页复核:SI_STRONG **42** / ARTICLE **1**(`nl200722z`)/ DOUBT 8 / SI_WEAK 1。
- **权威 `out/coverage.json`(success=371/999)里,有 34 条 batch6 acs-authorchoice SI 被计为 `status=success` 且不在现有 QC 黑名单**(union/hard/uncertain 均未覆盖)。**34/34 经全页正文体确认为纯 SI(0 条捆绑正文)**,即铁证假阳。
- **影响**:权威净覆盖 **371 → ~337(-34),净覆盖率 37.1% → ~33.7%(-3.4pp)**。这是 headline 数字,非独立 side-run。
- **产物**:`out/batch6_acs_si_reject_145.txt`(34 条,分 SI_STRONG 33 / SI_WEAK 1;带 coverage_status 列),供 `build_coverage --qc-extra-reject` 或补入 `qc_merge_union_wrong.csv` 消费。
- **另**:batch6 8 条 DOUBT 里 `acs.energyfuels.5c05523`/`acscatal.4c07622`/`acscatal.8b00216`/`acs.energyfuels.5c06101` 首页为论文标题(疑真正文)、`acscatal.8b04720`/`acs.jpcc.6b07849`/`acscatal.7b01827` 首页 SI(疑假阳)——需人核,未纳入上面 34 的铁证集(保守只报强置信)。recover_b4_cf 另有 5 条 acs-authorchoice SI(全已在黑名单,不虚高)。

## 五、给总指挥的结论(ACS 桶 ROI 定性)

1. **ACS still_missing 免费天花板 ≈ 4 篇**(真 author-choice/OA),**非 56**。95 条里 39 CF-403 + 51 免费 SI(≠正文)+ 1 错文件,**90/95 是真订阅墙或 SI**。
2. **route-B 浏览器内直下对本桶边际≈0**:正文在付费墙内,浏览器直下拿到的仍是 SI(SI 本就免费,不需破盾);ACS 不绑 JA3(N.3)故也不是 route-B 的目标桶。真正破 ACS 正文墙**唯一干净途径 = 机构订阅 A5**。
3. **FS-shim 对 ACS 桶的价值**:仅把 39 条 CF-403 里**真 OA/author-choice 子集**救回(极小),对订阅正文无效。**不应为 ACS 桶铺大 FS 走量**。
4. **立即可落地**:硬化 SI 门(§三,-140/-147)+ 把 acs-authorchoice success 强制经硬门(现 `content_qc_non_article_hard_reject` 默认 False → SI 仍落盘打标 uncertain;建议 CF 回收环境置 True),防 SI 再虚增任何 coverage。

---

*核验 2026-07-02 ｜ 谷歌学术人机认证-145 ｜ 证据:`out/rerun_acs_144_qc_scan_145.json`(生产门逐条)、`out/rerun_acs_144_reclass_145.json`(全页稳健重分类 + 门漏检)、`out/rerun_acs_144_si_reject_145.txt`(51 SI DOI)｜ 复扫脚本 `_qc_scan_acs144_145.py` / `_acs_reclassify_145.py`(纯读、可重跑)｜ 已同步总指挥 148。*
