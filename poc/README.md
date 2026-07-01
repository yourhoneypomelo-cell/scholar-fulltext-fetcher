# 角度2 主线 PoC：开放 API「检索 → 定位 OA → 下载入库」

基于《检索成果-角度2-官方开放API替代路线》的最小可用实现。
**全程不碰 Google Scholar、无人机验证、合规**；付费墙内全文无法获取（合理边界），只取开放获取 PDF。

## 安装
```bash
pip install -r requirements.txt
```

## 两个脚本

### 1) `openalex_oa_pipeline.py` —— 单源简版（最小示例）
OpenAlex 检索 + 元数据 + OA 直链 → 缺则 Unpaywall(DOI) 兜底 → 下载入库。
```bash
python openalex_oa_pipeline.py "large language model" --email you@example.com --max 20 --year-from 2024 --oa-only
```
输出：`out/pdfs/*.pdf`、`out/metadata.jsonl`、`out/index.json`

### 2) `scholar_multi_pipeline.py` —— 多源增强版（推荐）
多源检索（OpenAlex + Crossref + Semantic Scholar bulk）→ 按 DOI 合并去重 → 定位 OA（失败用 Unpaywall 兜底重试）→ 下载 → 导出 + 可选 Zotero 入库。
```bash
python scholar_multi_pipeline.py "graph neural network" --email you@example.com --max 25 --sources openalex,crossref,s2 --year-from 2023
```
额外参数：
- `--sources`：逗号分隔，`openalex,crossref,s2`（默认全开）
- `--openalex-key` / `--s2-key`：可选 API key（提速率/配额）
- `--zotero-key --zotero-library [--zotero-type user|group]`：直接写入 Zotero 库

额外产出（在单源版基础上）：
- `out/zotero.csl.json` —— Zotero 可直接「导入」（File → Import）
- `out/references.bib` —— BibTeX 引用

## 实测（2026-07-01）
- 单源版：`"graph neural network" --max 5 --oa-only` → 命中 5、下载 2 个真实 PDF（失败 3 为 HTML 落地页；多源版已加 Unpaywall 兜底重试改善）。
- 多源版：openalex/crossref/s2 各 5 → 合并 15 → `csl.json` / `bib` / `jsonl` 正常导出。

## 说明
- **OpenAlex 2026**：API key 实质必需（无 key 仅约 $0.10/天 demo 额度、`mailto` 礼貌池已废为 key-only）；匿名可跑少量，常规请用 `--api-key`（免费申请、每天送 $1 额度）。
- Unpaywall 10 万次/天、仅非商用免费；**`--email` 必须填真实邮箱**——占位邮箱（如 you@example.com）会被拒返回 422。
- Zotero 入库两法：① 导入 `zotero.csl.json`（零配置）；② Web API 直写（需 key + library id，见 zotero.org/settings/keys）。
- 生产化方向（并发 / 断点续传 / 更多源 / 去重增强）见《检索成果-00-聚合总报告与选型决策》第八节。
