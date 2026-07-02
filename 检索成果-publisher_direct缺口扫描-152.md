# still_missing 前缀 × publisher_direct 覆盖/缺口表（P1 缺口扫描 · task-86fbec24 / 会话-152）

- 数据源：`out/still_missing.txt`（628 条，生成 2026-07-02 11:57:04）
- 判定源：`fulltext_fetcher/sources/publisher_direct.py`（机构订阅直链源，默认关闭，仅 `--institutional` 开）
- 复现脚本：`_gap_pubdirect_152.py`（汇总）、`_gap_pubdirect_152_detail.py`（缺口逐条 JSON）
- 判定口径：
  - **static**＝`build_static_candidates(doi)` 非空（纯构造、离线可推直链）
  - **xref**＝前缀属 Crossref 增强社（`10.1016` Elsevier / `10.3390` MDPI）：有 handler，但需 1 次 Crossref 取 PII/坐标才成直链
  - **gap**＝两者皆否：publisher_direct 对该前缀**无任何模板** → 真缺口

## 一、总体结论

| 覆盖类别 | 条数 | 占比 |
|---|---:|---:|
| static（离线可推直链） | 194 | 30.9% |
| xref（需 Crossref 增强） | 381 | 60.7% |
| **有 handler 合计（static+xref）** | **575** | **91.6%** |
| **gap（真缺口，无模板）** | **53** | **8.4%** |

> ⚠️ **重要口径警示**：**“有 handler” ≠ “能下到 PDF”**。publisher_direct 是**机构订阅路径**，直链须经合法机构订阅（EZproxy/SSO）授权，无订阅会返回 401/403/HTML 落地页并被 `download.py` 的 `%PDF` 魔数校验过滤（不产假成功）。故 575 条是**机构订阅理论可及上限**，非免费可得。尤其最大桶 Elsevier `10.1016`（374 条）虽 xref 覆盖，但既有 ROI 备注为“IP/登录墙非 CF、最低 ROI、免费链路已到顶、主力交机构订阅”。

## 二、按 still_missing 分桶

| 桶 | total | static | xref | gap | 类别 |
|---|---:|---:|---:|---:|---|
| elsevier | 379 | 0 | 374 | 5 | PARTIAL（gap＝老 Elsevier 10.1006×5） |
| acs | 95 | 95 | 0 | 0 | ✅ COVERED |
| rsc | 67 | 57 | 0 | 10 | PARTIAL（gap＝遗留 a/b/tf 期） |
| other | 34 | 6 | 7 | 21 | PARTIAL |
| springer | 23 | 14 | 0 | 9 | PARTIAL（gap＝10.1023×6+10.1134×3） |
| wiley | 22 | 22 | 0 | 0 | ✅ COVERED |
| aip | 4 | 0 | 0 | 4 | ❌ GAP |
| iop | 4 | 0 | 0 | 4 | ❌ GAP |

> 桶映射差异：本表把 `10.1116`（AIP/AVS）归 aip，`_shard_stats.json` 归 other，故此处 aip=4 / other=34，对应 shard 的 aip=3 / other=35（差 1 条 `10.1116`）。合计均为 628。

## 三、缺口明细（53 条）

### A) RSC 遗留期（10 条，在 rsc 桶内，属 PARTIAL）
`_RSC_RE=^([cd])(\d)([a-z]{2})` 只覆盖 c 期(2010s)/d 期(2020s)；下列 a/b/tf 老期与非常规后缀无法构造：

```
10.1039/a905548g  10.1039/b103225a  10.1039/b111498k  10.1039/b212220k
10.1039/b403438d  10.1039/b510762h  10.1039/b807428c  10.1039/b915667d
10.1039/c001484b  10.1039/tf9221700607
```

### B) 纯缺口前缀（43 条，24 个前缀，publisher_direct 完全无模板）

| 前缀 | n | 出版商 | 补口可复用性 |
|---|---:|---|---|
| 10.1023 | 6 | Springer/Kluwer | ★可复用 Springer 模板 |
| 10.1006 | 5 | 老 Elsevier(ScienceDirect) | ★可并入 Elsevier xref 分支 |
| 10.1166 | 4 | Amer.Sci.Pub (JNN) | 独立小社 |
| 10.1246 | 4 | CSJ (Chem. Lett.) | 独立 |
| 10.1063 | 3 | AIP | ★Atypon 系可套 /doi/pdf |
| 10.1134 | 3 | Springer/Pleiades | ★可复用 Springer 模板 |
| 10.1017 | 1 | Cambridge | 长尾 |
| 10.1070 | 1 | Turpion/IOP (RCR) | ★IOP 家族 |
| 10.1088 | 1 | IOP | ★IOP 家族 |
| 10.1093 | 1 | OUP (Chem. Lett.) | 长尾 |
| 10.1107 | 1 | IUCr | 长尾 |
| 10.1109 | 1 | IEEE | 长尾 |
| 10.1116 | 1 | AIP/AVS | ★Atypon 系 |
| 10.1149 | 1 | ECS/IOP | ★IOP 家族 |
| 10.1155 | 1 | Hindawi(OA) | 长尾（应走 OA 常规） |
| 10.1515 | 1 | De Gruyter | 长尾 |
| 10.1595 | 1 | Johnson Matthey | 长尾 |
| 10.2113 | 1 | GeoScienceWorld | 长尾 |
| 10.2138 | 1 | Mineral. Soc. Am | 长尾 |
| 10.26599 | 1 | Tsinghua/SciOpen | 长尾（中） |
| 10.35848 | 1 | IOP/JJAP | ★IOP 家族 |
| 10.3866 | 1 | Acta Phys-Chim Sin | 长尾（中） |
| 10.7503 | 1 | CJCU | 长尾（中） |
| 10.11862 | 1 | CJIC | 长尾（中） |

## 四、最高 ROI 补口建议（复用现有出版商模板、近零成本、低风险）

1. **RSC 遗留期 → +10**：⚠️**更正（-141 实测）**：这 10 条老式 RSC DOI（`a905548g`/`b103225a`/…/`tf9221700607`/8 位 `c001484b`）是老编码『{字母}{6 位流水号}{校验位}』，后缀里**不含现代 RSC 两字母刊代码（jcode）**，`_RSC_RE` 对这 10 条全 `match=False`、`static_urls=0`，Crossref alternative-id 亦空——**故扩正则/年份映射拼不出 `articlepdf/{year}/{jcode}/{suffix}`（缺 jcode），此路不通**。可救路径：实现为**一次 Crossref 增强分支 `_rsc_legacy()`**（同 `_elsevier`/`_mdpi` 机制），从 `resource.primary.URL` 首段取 jcode、`published` 取年份。ROI 仍 +10，但工作量/风险从「改正则」上调为「新增 Crossref 分支」；极老 Faraday(1922) PDF 路径存在性有残余不确定但不产假阳。详见《选型2026-publisher_direct补口实现规格-Springer兄弟+老Elsevier+RSC遗留-141.md》§三。
2. **Springer 加兄弟前缀 10.1023(Kluwer)+10.1134(Pleiades) → +9**：直接加进 `_SIMPLE`，复用 `link.springer.com/content/pdf/{doi}.pdf`。
3. **老 Elsevier 10.1006 → +5**：并入 `_elsevier()` 的 Crossref-PII 分支（同 ScienceDirect `/pdfft`）。
4. **AIP 10.1063/10.1116 → +4**：`pubs.aip.org` Atypon `/doi/pdf/{doi}`。
5. **IOP 家族 10.1088/10.1070/10.1149/10.35848 → +4**：`iopscience.iop.org/article/{doi}/pdf`。
6. CSJ 10.1246(+4)、JNN 10.1166(+4)：ROI 较小，可选。

> **建议先做 1+2+3 = +24**：缺口 53 → 29（腰斩），且全部复用已支持出版商的同域模板/同分支，改动小、回归风险低（各社均有离线 selftest 断言可加）。
> 剩余长尾（Cambridge/OUP/IUCr/IEEE/DeGruyter/中日俄小社等约 15 前缀各 1 条）ROI 低，建议押后或交机构订阅 / websearch（走 QC union 门防假阳）。
