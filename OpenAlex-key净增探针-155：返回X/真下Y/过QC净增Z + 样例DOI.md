# OpenAlex-key 净增探针-155：返回 X / 真下 Y / 过 QC 净增 Z + 样例 DOI

**执行**：-174（实测）｜**coverage 未改**（340 定版，待下波 -155 merge）  
**输入**：`out/still_missing.txt` **659** 条｜**OPENALEX_KEY**：已设（len=22，User env）

## 三层结论（诚实分层）

| 层级 | 符号 | 结果 | 说明 |
|------|------|------|------|
| API 返回 OA `pdf_url` | **X** | **25 / 659 (3.8%)** | 带 key 扫全量 still_missing；全程无 429 |
| 真下到 `%PDF` | **Y** | **1 / 25 (4%)** | 仅 `openalex` 源、Pipeline 单跑 |
| 开卷 QC 净增 | **Z** | **1 / 25 (4%)** | 标题/DOI match + 非 SI/非错文 |

**对比 coverage 基线**：历史 `openalex` 成功 **31** 篇（全库净口径，非本探针子集）。

### 与「无 key」对照（子集 25 条）

对 X=25 的 DOI **逐条匿名再查**：无 key 时 **25/25 同样返回 `pdf_url`**（key-only 增量 **0**）。

→ **结论**：在本 still_missing 子集上，**key 不增加 OpenAlex 元数据面的新 pdf_url**；净增来自 **Pipeline 能把其中 1 条真正下下来**（落地页→内嵌 PDF），而非 API 字段解锁。

## 真净增样例（Z=1）

| DOI | 标题（Crossref） | 下载路径 | QC |
|-----|------------------|----------|-----|
| `10.1039/c4ra14572k` | Porous ternary Fe-based catalysts for the oxidative dehydrogenation of ethylbenzene… | OpenAlex → landing → `repositorio.ufc.br` 内嵌 PDF | match 100 |

PDF：`out/openalex_key_probe_174/dl/pdfs/`（同 run metadata）

## X=25 但 Y≠25 的主因（下载失败桶）

| 失败模式 | 约数 | 代表 DOI |
|----------|------|----------|
| RSC **cloudflare-challenge** http-403 | ~12 | `10.1039/d1ta08016d`, `10.1039/d0gc02302g` … |
| Elsevier **http-403** / 非 PDF 头（JPEG 封面） | ~8 | `10.1016/j.cej.2009.02.013`, `10.1016/j.apcata.2014.02.033` … |
| landing 无内嵌 PDF | 3 | `10.1149/1945-7111/acc6f7`, `10.1246/cl.200692`, `10.35848/1347-4065/ad280f` |
| Wiley CF | 1 | `10.1002/adts.202501922` |
| Hindawi CF | 1 | `10.1155/2014/690514` |

→ OpenAlex **返回 ≠ 可下**；RSC/Elsevier 订阅项占大头，与路线 B / 机构通道 ROI 一致。

## 产物路径

| 文件 | 内容 |
|------|------|
| `out/openalex_key_probe_160/openalex_scan.jsonl` | 659 条 API 扫描（phase1） |
| `out/openalex_key_probe_174/dl/` | 25 候选下载 + metadata |
| `out/openalex_key_probe_174/summary.json` | X/Y/Z + qc_rows |
| `_openalex_key_probe_160.py` / `_openalex_key_probe_phase2_174.py` | 可复跑脚本 |

## 建议

1. **回写**：若纳入下波 coverage，仅 **`10.1039/c4ra14572k`**（Z=1）；**174 未写库**。
2. **ROI**：对 still_missing 全量扫 OpenAlex **API 面收益极低**（X=25，且 key 不增字段）；真回收仍靠 CF/机构/route-B。
3. **run_all 缺口**：`run_all.py` 已透传 `openalex_key` 参数，但一键路径仍建议确认与 CLI 同口径（见 148 runbook）。

## 自检命令

```bash
python _openalex_key_probe_160.py          # phase1 扫描（~80s）
python _openalex_key_probe_phase2_174.py   # phase2 下载+QC（独立 dl 目录）
```
