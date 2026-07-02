# publisher_direct 缺口补口实现规格 — Springer 兄弟前缀 + 老 Elsevier + RSC 遗留期(+24)

> 交付:**谷歌学术人机认证-141**(worker)｜2026-07-02｜工单来源:总指挥/属主 **-142**(taskId=`task-257fb2da-1de2-4155-a169-7d3c98ef25b6`)
> 上游依据:`检索成果-publisher_direct缺口扫描-152.md`(缺口 53 条)、`A5机构订阅现状与still_missing可救前缀梳理-150.md`
> **边界:纯文档、不改任何 `.py`**。本规格给"可直接照写"的实现点(函数/表/分支)、样例 DOI、离线 selftest 断言期望;代码活由 **publisher_direct 属主**在 route-B checkpoint 过后应用(避免与 -144 当前 route-B 改动撞车)。
> 核验方式:本规格全部 URL 模板、Crossref 字段、`_RSC_RE` 现状均经 `_spec_probe_141.py` / `_spec_probe_xref_141.py` 实测(见文末附录)。

---

## 〇、TL;DR(含对 -152 ROI 备注的一处更正)

| 收口 | 前缀 | 篇数 | 实现路径 | 复用现有? | 风险 | 离线可 selftest? |
|---|---|---:|---|---|---|---|
| **A** Springer 兄弟前缀 | `10.1023`+`10.1134` | **9** | 加进 `_SIMPLE`(纯静态) | ✅ 复用 `link.springer.com/content/pdf/{doi}.pdf` | 极低 | ✅ 完全 |
| **B** 老 Elsevier | `10.1006` | **5** | 扩 `build_pdf_candidates` 前缀门 | ✅ 复用 `_elsevier()` Crossref-PII 分支 | 低 | ✅ 完全 |
| **C** RSC 遗留期 | `10.1039`(a/b/tf/8位c) | **10** | **新增 Crossref 增强分支 `_rsc_legacy()`** | ⚠ 复用 articlepdf **模板/域**,但需 Crossref 取 jcode+year | 中(极老 Faraday 期有残余不确定) | ✅ 完全(假 client) |

**合计 +24(缺口 53 → 29)不变**,但**分层更正**:

- **A+B = +14 是真正"近零成本、回归风险低"** —— 纯静态 / 仅扩一个前缀门,当天可落、离线 selftest 全覆盖。
- **⚠ 对 -152《缺口扫描》§四.1 的更正**:该文建议"RSC 扩遗留期 → +10:`_RSC_RE`/年份映射扩到 a/b 期与 tf"。**实测:此路不通**。10 条 RSC 遗留 DOI(`a905548g`/`b103225a`/`tf9221700607`/8 位 `c001484b` 等)是老式 `{字母}{数字流水}{校验位}` 编码,**DOI 后缀里根本不含 2 字母刊代码**,且 Crossref `alternative-id` 为空 —— 无论怎么扩正则/年份映射都构造不出 `articlepdf/{year}/{jcode}/{suffix}`(缺 `jcode`)。**但**可救:Crossref 的 `resource.primary.URL`(如 `https://pubs.rsc.org/cp/article/1/20/...`)**首段即刊代码**,`published` 给年份 —— 故 RSC 遗留应实现为**一次 Crossref 增强分支**(与 `_elsevier`/`_mdpi` 同机制),而非纯正则扩展。ROI 仍是 +10,但**工作量/风险从"改正则"上调为"新增 Crossref 分支"**。

---

## 一、收口 A — Springer 兄弟前缀 `10.1023`(Kluwer)+ `10.1134`(Pleiades)→ +9

**判定**:两前缀 Crossref `resource.primary.URL` 均落 `link.springer.com`(实测),与既有已支持的 `10.1007`/`10.1140` 同域同 PDF 路径。纯静态、不需联网。

**实现点**:`fulltext_fetcher/sources/publisher_direct.py` 的 `_SIMPLE` 字典**新增两键**(与现有 springer 项同形):

```python
# _SIMPLE 内追加(复用现有 springer 模板/信心值)
"10.1023": ("springer", 66, ("https://link.springer.com/content/pdf/{doi}.pdf",)),
"10.1134": ("springer", 66, ("https://link.springer.com/content/pdf/{doi}.pdf",)),
```

- 无需新 handler:`_static_for()` 已对任意 `_SIMPLE` 键走 `t.format(doi=d)`,自动生效于 `build_static_candidates` 与 `build_pdf_candidates`。
- 保留 DOI 原样(含 `10.1023/a:...` 的冒号与大小写):模板只做 `{doi}` 替换,Springer 对 Kluwer 老 DOI 的 `content/pdf/{doi}.pdf` 兼容(冒号必须保留)。

**样例 DOI(取自 `out/still_missing.txt`)**:

| 前缀 | n | 样例 DOI | 构造出的直链 |
|---|---:|---|---|
| 10.1023 | 6 | `10.1023/a:1015326726898`(Catalysis Letters, 2002) | `https://link.springer.com/content/pdf/10.1023/a:1015326726898.pdf` |
| 10.1134 | 3 | `10.1134/s0036029512010132`(Russian Metallurgy, 2012) | `https://link.springer.com/content/pdf/10.1134/s0036029512010132.pdf` |

**selftest 断言(离线,加入 `_selftest()` ②/③ 附近)**:

```python
assert "https://link.springer.com/content/pdf/10.1023/a:1015326726898.pdf" in urls("10.1023/a:1015326726898")
assert "https://link.springer.com/content/pdf/10.1134/s0036029512010132.pdf" in urls("10.1134/s0036029512010132")
```

---

## 二、收口 B — 老 Elsevier `10.1006`(旧 ScienceDirect)→ +5

**判定**:实测 `10.1006/jcat.1993.1276` 的 Crossref `alternative-id = ['S0021951783712765']`,命中现有 `_PII_RE`(`^[SB][0-9X]{16}$`)。即**既有 `_elsevier()` 分支对 10.1006 完全适用**,只是当前前缀门只放行 `10.1016`。

**实现点**:`build_pdf_candidates()` 里把 Elsevier 前缀判断从单值改为集合(仅此一处,`_elsevier()` 本身不动):

```python
# 现状(publisher_direct.py 约 L224)
if prefix == "10.1016":
    raw += _elsevier(d, ctx)
# 改为
if prefix in ("10.1016", "10.1006"):
    raw += _elsevier(d, ctx)
```

- `_elsevier()` 内部逻辑不变:Crossref `alternative-id` → PII → `sciencedirect.com/science/article/pii/{PII}/pdfft`。
- 属 Crossref 增强(需 `ctx.client`);纯静态 `build_static_candidates("10.1006/...")` 仍返回 `[]`(与 10.1016 一致,符合冻结契约)。

**样例 DOI(全部 5 条,均在 `out/still_missing.txt`)**:`10.1006/jcat.1993.1276`、`10.1006/jcat.1995.1229`、`10.1006/jcat.1996.0092`、`10.1006/jcat.2001.3364`、`10.1006/jcat.2001.3461`(均 J. Catalysis 老卷)。

`10.1006/jcat.1993.1276` → `alternative-id S0021951783712765` → `https://www.sciencedirect.com/science/article/pii/S0021951783712765/pdfft`。

**selftest 断言(离线·复用现有假 client `_Ctx`,加入 ⑧ 附近)**:

```python
els06 = build_pdf_candidates(
    "10.1006/jcat.1993.1276",
    ctx=_Ctx({"message": {"alternative-id": ["S0021951783712765"]}}))
assert els06 and els06[0].url == \
    "https://www.sciencedirect.com/science/article/pii/S0021951783712765/pdfft", els06
assert els06[0].source == "publisher_direct:elsevier"
assert build_static_candidates("10.1006/jcat.1993.1276") == []   # 无 ctx 纯构造仍空
```

---

## 三、收口 C — RSC 遗留期 `10.1039`(a/b/tf 期 + 8 位 c)→ +10 【更正为 Crossref 增强分支】

### 3.1 为何不能靠扩正则(推翻 -152 的原方案)

现有 `_RSC_RE = ^([cd])(\d)([a-z]{2})` 只认"**字母(c/d)+年份位+2 字母刊代码**"的现代 DOI(如 `c0cp00789g`→2010/cp、`d0ta09607e`→2020/ta,实测均正常构造)。10 条遗留 DOI 实测**全部 `regex_match=False`、`static_urls=0`**:

```
a905548g  b103225a  b111498k  b212220k  b403438d
b510762h  b807428c  b915667d  c001484b  tf9221700607
```

结构上它们是老式 `{字母}{6 位数字流水}{校验位}`(如 `b103225a` = b+103225+a)或 `tf{...}`(Trans. Faraday Soc.),**后缀内不含刊代码**,且 Crossref `alternative-id = []`。故 `articlepdf/{year}/{jcode}/{suffix}` 里的 `{jcode}` 无从取得 —— **扩正则/年份映射无法补此口**。

### 3.2 可救路径:从 Crossref `resource.primary.URL` 取 jcode+year

实测 Crossref 对每条遗留 DOI 都给出 landing URL,**首段即刊代码**,`published` 给年份:

| DOI | container | year | resource.primary.URL | 可推 jcode |
|---|---|---:|---|---|
| `10.1039/a905548g` | Phys. Chem. Chem. Phys. | 1999 | `https://pubs.rsc.org/cp/article/1/20/4909-4912/199139` | `cp` |
| `10.1039/b103225a` | Phys. Chem. Chem. Phys. | 2001 | `https://pubs.rsc.org/cp/article/3/21/...` | `cp` |
| `10.1039/c001484b` | Phys. Chem. Chem. Phys. | 2010 | `https://pubs.rsc.org/cp/article/12/33/...` | `cp` |
| `10.1039/tf9221700607` | Trans. Faraday Soc. | 1922 | `https://pubs.rsc.org/tf/article/17/0/607-620/230602` | `tf` |

→ 构造 `https://pubs.rsc.org/en/content/articlepdf/{year}/{jcode}/{suffix}`(与现代 `_rsc()` **同模板同域**,只是 jcode+year 改由 Crossref 提供)。

### 3.3 实现点:新增 Crossref 增强分支 `_rsc_legacy()`(与 `_elsevier`/`_mdpi` 同机制)

```python
_RSC_RESOURCE_RE = re.compile(r"pubs\.rsc\.org/([a-z]{2})/article/", re.I)

def _rsc_legacy(d: str, suffix: str, ctx: Any) -> List[_Cand]:
    """RSC 遗留期(a/b/tf/8位c 等 _RSC_RE 无法解析者):
    经一次 Crossref 从 resource.primary.URL 取刊代码 + published 取年份,
    复用现代 articlepdf 模板构造 PDF 直链。绝不抛。"""
    msg = _crossref_message(d, ctx)
    if not msg:
        return []
    res = ((msg.get("resource") or {}).get("primary") or {}).get("URL") or ""
    m = _RSC_RESOURCE_RE.search(res)
    if not m:
        return []
    jcode = m.group(1).lower()
    year = None
    for k in ("published", "published-print", "published-online", "issued"):
        v = msg.get(k)
        if isinstance(v, dict) and v.get("date-parts"):
            try:
                year = int(v["date-parts"][0][0]); break
            except Exception:  # noqa: BLE001
                pass
    if not year:
        return []
    url = f"https://pubs.rsc.org/en/content/articlepdf/{year}/{jcode}/{suffix.lower()}"
    return [(url, "rsc", 60)]   # 信心值略低于现代静态 rsc(66):经 Crossref 推断、极老期不确定
```

在 `build_pdf_candidates()` 的 ctx 增强块内挂载(仅当纯静态 `_rsc` 没产出、即遗留期时才查 Crossref,避免对现代 RSC 多打一次网):

```python
elif prefix == "10.1039" and not raw:      # 现代 _rsc 已在 _static_for 产出;此处只兜底遗留期
    raw += _rsc_legacy(d, suffix or "", ctx)
```

### 3.4 残余风险(诚实标注)

- **PDF 路径存在性**:`articlepdf/{year}/{jcode}/{suffix}` 对 1999+ 的 PCCP(cp)等结构高度一致、可信;但**极老期(尤其 `tf` Trans. Faraday Soc. 1922)** RSC 是否以同一 articlepdf 路径托管 PDF 未经实证。构造错了也**不产假成功**:`download.py` 的 `%PDF` 魔数校验会把非 PDF(HTML/404)判失败、不落盘。故风险表现为"命中率打折",非"污染 coverage"。
- 建议:落地后对这 10 条(有订阅会话时)做一次真跑核对命中率;若 Faraday 老期普遍 404,可在 `_rsc_legacy` 加 `year >= 1997` 之类下限(PCCP 起始年),把 pre-1997 直接让给 websearch/机构订阅人工。

### 3.5 selftest 断言(离线·假 client)

```python
rsc_leg = build_pdf_candidates(
    "10.1039/a905548g",
    ctx=_Ctx({"message": {
        "resource": {"primary": {"URL": "https://pubs.rsc.org/cp/article/1/20/4909-4912/199139"}},
        "published": {"date-parts": [[1999]]}}}))
assert rsc_leg and rsc_leg[0].url == \
    "https://pubs.rsc.org/en/content/articlepdf/1999/cp/a905548g", rsc_leg
assert rsc_leg[0].source == "publisher_direct:rsc"
# resource.URL 无刊代码 / 无年份 → 空(不误产)
assert build_pdf_candidates("10.1039/a905548g", ctx=_Ctx({"message": {}})) == []
# 现代 RSC 仍走纯静态、不因新分支多查 Crossref(_static_for 已产出 → build_pdf_candidates 的 not raw 为 False)
assert "https://pubs.rsc.org/en/content/articlepdf/2010/cp/c0cp00789g" in urls("10.1039/c0cp00789g")
```

---

## 四、离线 selftest 汇总(全部可在 `python -m fulltext_fetcher.sources.publisher_direct` 验证,仍打印 `PUBLISHER_DIRECT_OK`)

1. **A** Springer 兄弟:`urls("10.1023/a:...")` / `urls("10.1134/s...")` 含 `content/pdf/{doi}.pdf`。
2. **B** 老 Elsevier:假 client → `10.1006/...` 得 `/pdfft`;无 ctx 纯构造为 `[]`。
3. **C** RSC 遗留:假 client(带 `resource.URL`+`published`)→ `articlepdf/{year}/{jcode}/{suffix}`;缺字段为 `[]`;现代 RSC 不受影响。
4. **不产假阳护栏**:所有新构造 URL 均经 `download.py` `%PDF` 魔数校验;无订阅/路径错 → 401/403/HTML → 判失败不落盘(与既有纪律一致)。
5. **机构门不变**:`institutional=False` 时 `PublisherDirectSource.find_candidates` 仍恒返回 `[]`(A/B/C 均在 `--institutional` 后才产候选)。

---

## 五、回归与护栏

- **零副作用**:A 仅加 `_SIMPLE` 两键;B 仅把一个 `==` 改 `in (...)`;C 新增一个函数 + 一个 `elif ... and not raw` 分支。均不触碰现有 14 前缀/Atypon 系/`_elsevier`/`_mdpi` 逻辑,现有 11 项 selftest 断言不受影响。
- **网调预算**:A 纯静态 0 次;B 复用既有 Elsevier 那 1 次 Crossref;C 仅对**遗留 RSC**(现代 RSC 静态已命中、`not raw` 为假)多 1 次 Crossref —— 全项目对 10 条遗留各 +1 次,受 `http_client` 限速/熔断保护。
- **信心值**:A/B 沿用既有(66/72);C 用 60(经 Crossref 推断且极老期存疑,排在现代静态之后)。

---

## 六、交付边界与待接

- 本文**仅规格、未改 `.py`**(遵工单边界)。代码应用**待 route-B checkpoint 过**,由 **-142 派给 publisher_direct 属主**执行(规避与 -144 当前 route-B 改动撞车)。
- **净增口径提醒**:+24 是"机构订阅**理论可及**"的直链补口 —— 需**合法机构订阅会话**(EZproxy/SSO)授权才真能下到 PDF;当前项目**无凭据**(见 -150 缺口 2,路线 A 已封存 ROI=0),故这 24 条在有凭据前**离线可 selftest、真跑仍 0**。收口价值在于"凭据到手即生效、正确性已离线锁定",而非当下净增。
- **给 -152 的更正已同步**(见 §〇):其《缺口扫描》§四.1 的"RSC 扩正则 +10"应改为"RSC 遗留经 Crossref `resource.URL` 取 jcode+year 的增强分支 +10"。

---

## 附录 — 复现探针(用后可删)

- `_spec_probe_141.py`:核验 `_RSC_RE` 对 10 条遗留 RSC 全 `match=False`、现代 RSC 正常构造、目标前缀纯静态现状。
- `_spec_probe_xref_141.py`:对 7 条样例打 Crossref,核验 10.1006 有 PII、10.1039 遗留有 `resource.URL`(含 jcode)+year、10.1023/10.1134 落 `link.springer.com`。

*核验 2026-07-02｜-141｜工单 `task-257fb2da`(publisher_direct +24 补口规格)｜结论:A Springer 兄弟(+9,纯静态)+ B 老 Elsevier(+5,扩前缀门复用 `_elsevier`)= **+14 近零成本低风险**;C RSC 遗留(+10)**更正为 Crossref `resource.URL` 取 jcode+year 的增强分支**(非扩正则),极老 Faraday 期有残余命中不确定但不产假阳。全部离线 selftest 可验。仅新建本 md,未改 .py。*
