# 检索成果 · route-B 回收波发射优先级(A 集 rsc 67 + MDPI 7)

> 交付:**谷歌学术人机认证-140**(执行)｜工单来源:**总指挥 -142**｜2026-07-02。
> 目的:route-B 单头串行、CF 过盾算力宝贵——**先分流「真 OA(值得发射)」vs「订阅墙 no-pdf(注定空跑)」**,避免把过盾算力浪费在注定 no-pdf 的订阅条上。
> **边界**:纯文档、只读,**不改代码、不跑网络**。判定按「刊物 OA 政策 + DOI 期刊码 + 已提交扫描文档(173/143/152/真机冒烟-152)」,不逐条 Unpaywall(需联网的项已标【需 is_oa 核】)。
> 数据源:`out/still_missing_shards/rsc.txt`(67 条)+ `other.txt` 内 `10.3390`(MDPI 7 条);机制证据见《路线B-真机冒烟结果-152.md》。

---

## 〇、TL;DR(给 -142 的一句话)

- **A 集 74 条里,真能落 %PDF 的诚实区间 ≈ 8~14 篇**;其中 **route-B(过 CF)真正贡献的是 RSC 侧 ~3~7 篇**,MDPI 7 篇是全 OA 但**走 Akamai 非 CF、大概率不需 route-B**(另计)。
- **优先发射(高 ROI·真 OA)= 11 篇**:RSC Advances 全 OA 刊 **4 篇**(route-B 已实证 `d5ra08493h` 端到端通)+ MDPI **7 篇**(全 OA)。
- **低优先(预期 no-pdf·订阅墙)= 55 篇**:RSC 订阅/hybrid 刊(cp/cs/dt/jm/cy/ee/nr/cc/nj/se/ta/gc/fd/tf 等)——route-B **能过 CF 但文章本身付费无 OA PDF,no-pdf 是正确结果**,不该占过盾算力。
- **待定(hybrid 可能 author-gold-OA)= 8 篇**:Green Chem/EES/Faraday Disc/NJC/ChemSocRev 中被 -144/-152 探针挑出的候选,**需逐条 Unpaywall `is_oa` 核**后并入优先或低优先。

| 档 | 篇数 | 处置 |
|---|:--:|---|
| 优先发射·真 OA | 11 | RSC Adv 4 + MDPI 7,先发 |
| 待定·需 is_oa 核 | 8 | 联网核 Unpaywall 后归档 |
| 低优先·预期 no-pdf | 55 | 不占过盾算力,或仅抽样验证「no-pdf=正确」 |
| **合计** | **74** | (rsc 67 + MDPI 7) |

---

## 一、优先发射 · 高 ROI · 真 OA(11 篇)

### 1.1 RSC Advances(全 OA 刊,期刊码 `ra`)— 4 篇 · route-B 主目标
> RSC Advances 是 RSC **全金 OA 刊**;`pubs.rsc.org` 属 **JA3 绑定 CF 桶**——正是 route-B 的核心战场。真机冒烟已证 `10.1039/d5ra08493h`:CF 过盾(12–16s)+ B2/方法A 抓 %PDF 484KB + QC match。同刊同域,下列 4 条机制同构。

```
10.1039/c4ra00825a
10.1039/c4ra02037e
10.1039/c4ra14572k
10.1039/c5ra04969e
```
- **发射方式**:route-B —— 过盾(不开 Fetch 拦截)→ `publisher_direct.build_static_candidates` 构 `pubs.rsc.org/en/content/articlepdf/{year}/{jcode}/{suffix}` → **B2/方法A**(导航 PDF URL + Fetch.enable RESPONSE 拦截,过盾后才开)。
- **⚠️ 小 caveat**:这 4 条是 2014–2015 年(RSC Adv 2017 前为 hybrid 期),**建议发射前顺手核一次 `is_oa`**;RSC Advances 即便 hybrid 期多数仍 OA,置信较高,故列入优先。

### 1.2 MDPI(全 OA 刊,前缀 `10.3390`)— 7 篇 · 全 OA 但**非 CF,另计**
> MDPI 全刊金 OA,PDF 免费在 `www.mdpi.com/.../pdf`。**MDPI 走 Akamai 而非 Cloudflare JA3**——大概率**不需 route-B 过盾**,更可能是此前一次抓取偶发失败/候选错。

```
10.3390/app14114959
10.3390/catal10070741
10.3390/catal13091244
10.3390/catal15111028
10.3390/catal16020163
10.3390/catal16030270
10.3390/en11092276
```
- **发射方式**:**优先普通链路重抓**(`publisher_direct` MDPI 模板 / OA 常规),**先不占 route-B 过盾算力**;仅普通链路失败再考虑 route-B。
- **ROI**:7 篇全 OA,预估近乎全可回收(除非 DOI 本身失效)。

---

## 二、待定 · hybrid 可能 author-gold-OA(8 篇)· 需逐条 `is_oa` 核

> 下列属 RSC **hybrid 刊**(Green Chem/EES/Faraday Disc/NJC/Chem Soc Rev):**整刊订阅,但单篇可能作者付费开成金 OA**。这 8 条**正是 -144(`_fs_test_144.py`)/-152(`_find_rsc_oa_152.py`)探针挑出的 is_oa 候选清单**(可追溯证据)——说明前序已疑其可能 OA,但**结论未落定**。

```
10.1039/d0gc00095g   (Green Chem)
10.1039/d0gc02302g   (Green Chem)
10.1039/d2gc02623f   (Green Chem)
10.1039/d5gc03584h   (Green Chem)
10.1039/d3ee02589f   (EES)
10.1039/d5fd00172b   (Faraday Discussions)
10.1039/d2nj03895a   (New J Chem)
10.1039/d0cs00025f   (Chem Soc Rev,综述,最不可能 OA,除非 is_oa 打脸)
```
- **处置**:发射波开跑**前**,对这 8 条跑一次 Unpaywall `is_oa`;`is_oa=True` 且 best PDF 在 `pubs.rsc.org` → 并入 §1.1 优先(route-B B2);`is_oa=False` → 降入 §三低优先。

---

## 三、低优先 · 预期 no-pdf · 订阅墙(55 篇)

> RSC 订阅/hybrid 刊(非 RSC Adv、非 §二候选):route-B **能过 CF,但文章本身无 OA PDF → no-pdf 是正确结果**(与 -152「rsc 多为订阅墙、no-pdf 正确」一致)。**不建议发射**(空耗过盾算力),或仅抽 2~3 条验证「过 CF 后确认无 OA 直链 = no-pdf 正确」以背书结论。

按期刊码分布(55 篇,已扣除 4 RSC Adv + 8 待定):

| 期刊码 | 刊名 | 篇数 | 墙性质 |
|---|---|:--:|---|
| cy | Catal. Sci. Technol. | 13 | hybrid,多订阅 |
| cp | Phys. Chem. Chem. Phys. | 6 | hybrid,多订阅 |
| ta | J. Mater. Chem. A | 5 | hybrid,多订阅 |
| gc | Green Chem.(非 §二候选) | 4 | hybrid,多订阅 |
| nr | Nanoscale | 4 | hybrid,多订阅 |
| dt | Dalton Trans. | 3 | hybrid,多订阅 |
| cc | Chem. Commun. | 3 | hybrid,多订阅 |
| cs | Chem. Soc. Rev. | 3 | 订阅综述 |
| se | Sustain. Energy Fuels | 2 | hybrid |
| ee | Energy Environ. Sci.(c3ee) | 1 | hybrid,多订阅 |
| jm | J. Mater. Chem.(旧) | 1 | 订阅 |
| tf | Trans. Faraday Soc. | 1 | 1922 年老刊,订阅 |
| a/b 期(2010 前) | 各旧刊 | 8 | 老订阅,`_RSC_RE` 亦不覆盖 |
| c001484b(异常码) | 待核 | 1 | 归此桶 |

> 合计 13+6+5+4+4+3+3+3+2+1+1+1+8+1 = **55**;与「67 − 4 RSC Adv − 8 待定 = 55」自洽。
> **补充**:a/b/tf 老期 + `c001484b` 共 **10 条**,`publisher_direct._RSC_RE` 只覆盖 c/d 期,**连直链都构造不出**(见 -152 缺口扫描 §三.A 的同一 10 条清单),即便发射也无 articlepdf 可导航 → 双重「不值得」。

---

## 四、诚实 ROI 一句话(供 -142 发射决策)

> **A 集 74 条,发射波真能落 %PDF 的诚实区间 ≈ 8~14 篇**:
> - **RSC 侧(route-B 真贡献)≈ 3~7 篇** = RSC Advances 4(高置信) + §二待定里核出 is_oa 的 0~3 篇;
> - **MDPI 侧 ≈ 5~7 篇**(全 OA,但走普通/Akamai 链路,**不必占 route-B 过盾算力**);
> - **其余 55 篇订阅墙:no-pdf 是正确结果,不该发射**——把过盾算力压在 §一.1 的 RSC Advances + §二核出的真 OA 上即可。

**发射顺序建议**:① MDPI 7 走普通链路(先清、零过盾成本)→ ② §二 8 条跑 Unpaywall is_oa 核(几秒)→ ③ RSC Advances 4 + 核出的真 OA 一起走 route-B B2 → ④ §三 55 条**跳过或仅抽样**。

---

## 五、证据索引

| 文档 | 贡献 |
|---|---|
| 《路线B-真机冒烟结果-152.md》 | route-B 对 RSC Adv `d5ra08493h` 端到端实证(CF 过 + B2 落 %PDF + QC match);ACS-OA 用 B1、RSC 用 B2 |
| 《检索成果-still_missing628分桶统计刷新-vs173漂移核对-143.md》 | rsc=67、真出版商 CF 墙口径、Elsevier 非 CF |
| 《检索成果-publisher_direct缺口扫描-152.md》 | RSC static 覆盖 57/67、a/b/tf 老期 10 条无模板(构不出 articlepdf) |
| 《检索成果-still_missing-CF-JA3桶ROI深挖-173.md》 | JA3 绑定桶「+5~15 篇」上限、路线B 价值在「JA3 从 0 到 1 + 提质」 |
| `out/still_missing_shards/rsc.txt` / `other.txt` | A 集 67 + MDPI 7 原始 DOI |

---

*核验 2026-07-02｜-140 执行 · -142 工单｜纯文档只读,未改代码、未跑网络。§二 8 条与 §一.1 的 4 条 RSC Adv 的 is_oa 需联网复核后落定优先/低优先。*
