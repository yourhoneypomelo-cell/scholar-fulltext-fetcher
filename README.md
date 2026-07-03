# 谷歌学术人机认证 · 全文批量下载「一键正门」

> **一句话**：**输入 DOI / 标题 → 一条命令 → 全网可及的免费开放获取（OA）全文 PDF，统一命名落到单一文件夹 + 覆盖率报告。** 全程程序化、无人值守。
>
> 本仓库含两部分：
> 1. **`fulltext_fetcher` 生产工具（一键正门）** —— 见下方「快速上手」。
> 2. **七角度「过 Scholar 人机认证」选型调研（研究档）** —— 见 [附录 A](#附录-a七角度过-scholar-人机认证选型调研研究档)。

---

## 一键正门 · 3 步出全文

### 1) 安装

```powershell
cd "e:\AI项目\谷歌学术人机认证"
pip install -e ".[qc]"     # 推荐：核心 + 内容 QC（拦"下到错论文"假阳）
```

### 2) 设环境变量（建议）

```powershell
$env:OPENALEX_KEY   = "你的 OpenAlex 免费 Key"   # 强烈建议：不设则 openalex 源限速更严
$env:FULLTEXT_EMAIL = "you@uni.edu"              # Unpaywall 礼貌池标识
```

### 3) 一条命令跑批量

```powershell
python run_all.py -f examples/sample_dois.txt --email $env:FULLTEXT_EMAIL -o out/example_run
```

跑完看终端 **「一页式总结」**；PDF 在 `out/example_run/fetch/pdfs/`（**默认统一命名** `{year}_{author}_{title}_{doi}`，人类可读、全部落同一文件夹），仍缺的 DOI 在 `out/example_run/still_missing.txt`（可直接作下一轮 `-f` 输入）。示例输入见 [`examples/sample_dois.txt`](examples/sample_dois.txt)。

---

## 它做什么

- **输入**：DOI / arXiv id / 论文标题，可**混排**；支持 `.txt` / `.csv` / `.xlsx`（`.xlsx` 需 `[xlsx]` 扩展）。
- **多源回退定位 OA 全文**：OpenAlex / Unpaywall / Crossref / Semantic Scholar / Europe PMC / arXiv / 预印本 / 出版商直链 … + websearch 兜底。
- **落盘前内容 QC**：抽 PDF 首两页正文 + 元数据标题做模糊匹配，拦「下到错论文」的系统性假阳（**默认 fail-closed**）。
- **统一命名 + 跨批去重/续跑 + 覆盖率报告**：`coverage.json` / `still_missing.txt` / 一页式总结 / 逐条明细 `run_all_detail.tsv`。
- **全自动 · 无人值守**：默认不弹浏览器、不需人工登录、不需 AI 介入——一条命令跑到底，每条输入都有明确终态（成功落盘 / 进 `still_missing`）。强 CF 站或机构订阅才需额外开关（见下）。

> **边界**：只取**免费开放获取**全文；**付费墙内全文任何免费路线都拿不到**——靠机构订阅（路线 A）解决，不在本工具强求。

---

## 安装与依赖

运行期**硬依赖仅 `requests`**；其余能力按需装「扩展组」（缺失时对应路径**优雅降级、不崩**）。权威依赖定义见 [`pyproject.toml`](pyproject.toml) 的 `[project.optional-dependencies]`。

| 安装命令 | 装了什么 | 用途 |
|---|---|---|
| `pip install -e .` | 核心 `requests>=2.28` | 最小可跑（多源 OA 定位 + HTTP 直下） |
| `pip install -e ".[qc]"` | + `pypdf` `rapidfuzz` | **内容 QC 门**（拦抓错论文假阳；生产推荐） |
| `pip install -e ".[cf]"` | + `curl_cffi` | CF/TLS 指纹增强（CF-soft 站命中率↑） |
| `pip install -e ".[xlsx]"` | + `openpyxl` | 读 `.xlsx` 输入表 |
| `pip install -e ".[render]"` | + `playwright` | 渲染型落地页取直链 |
| `pip install -e ".[browser]"` | + `nodriver`（⚠️ AGPL-3.0，需有头 Chrome） | 路线 B 浏览器内直下（JA3 型强 CF） |
| `pip install -e ".[full]"` | = `[qc,cf,browser,xlsx]` | 生产全量一键装齐 |

离线自检环境是否 OK（不联网）：

```powershell
python run_all.py --selftest              # → RUN_ALL_OK
python tools/build_coverage.py --selftest # → COVERAGE_OK
```

> Python **≥ 3.8**；Windows / Linux / macOS 均可。OCR 不是打包依赖（历史 OCR 桶为一次性探针处置，非运行期扩展）。

---

## 环境变量

| 变量 | 是否必设 | 用途 |
|---|---|---|
| **`OPENALEX_KEY`** | 强烈建议 | OpenAlex API 免费 Key；不设则该源限速更严、命中率下降（也可用 `--openalex-key` 传参） |
| **`FULLTEXT_EMAIL`** | 建议 | Unpaywall 礼貌池标识（也可用 `--email` 传参） |
| `CORE_API_KEY` | 可选 | CORE 聚合源；无 key 时该源自动跳过 |

---

## 输入 / 输出

**输入**（`-f` 清单或命令行直接跟参数）：一行一条 DOI / arXiv id / 标题，可混排；`#` 开头为注释；DOI 带不带 `https://doi.org/` 前缀均可。

**输出**（以 `-o out/example_run` 为例）：

```
out/example_run/
├── fetch/
│   ├── pdfs/                 # ★ PDF 落盘目录（统一命名，全部同一文件夹）
│   ├── metadata.jsonl        # 每条输入一行 JSON 总账
│   ├── attempts.jsonl        # 结构化事件流（--explain 消费）
│   ├── results.csv / report.html / run.log
├── coverage.json             # 跨批去重 coverage 主库（净口径）
├── still_missing.txt         # 仍缺 DOI 全集（可直接续跑）
├── run_all_detail.tsv        # 逐条明细（grep '^MISS' 看失败）
└── run_all_summary.json      # 本次 run 机器可读总结
```

**PDF 命名**：默认 `{year}_{author}_{title}_{doi}`（元数据缺失优雅降级、全缺以 `{doi}` 兜底）；退回纯 DOI 名用 `--naming-template "{doi}"`。

---

## 常用命令

```powershell
# 标准批量（推荐正门）
python run_all.py -f my_papers.txt --email you@uni.edu --openalex-key $env:OPENALEX_KEY -o out/my_batch -c 3

# 闭环续跑：用上一轮 still_missing 作输入（--resume 默认仍会跨 out/ 剔已成功）
python run_all.py -f out/my_batch/still_missing.txt --email you@uni.edu -o out/my_batch_r2

# 强 CF 站（RSC/ACS/Wiley/ScienceDirect 等）：路线 B 浏览器内直下（需 [browser] + 有头显示）
python run_all.py -f my_papers.txt --route-b cf-only -o out/my_batch

# 机构订阅直链（路线 A；仅合法机构授权者）
python run_all.py -f my_papers.txt --institutional -o out/my_batch

# 调试某条为何 miss（只读日志、不联网）
python run_all.py --explain 10.1021/jacs.6b11736 -o out/my_batch

# 确定性复现本次净覆盖数
python run_all.py --verify -o out/my_batch
```

单条 / 临时查一篇用 `python -m fulltext_fetcher`；批量正门用 `python run_all.py`。勿把 `run_all_selftests.py`（自检回归）当成 `run_all.py`（下载）。

---

## 深入阅读

| 文档 | 用途 |
|---|---|
| [`用户Runbook-一键正门批量下载.md`](用户Runbook-一键正门批量下载.md) | **完整参数 / 日志判读 / FAQ / E2E 实测**（正门使用手册） |
| `基线口径冻结说明-388-173.md` | 净覆盖率 KPI 口径（唯一权威） |
| `路线A-机构订阅实测Runbook-凭据到手3步.md` | 有机构凭据时（路线 A） |
| `路线B-浏览器内直下PDF验证Runbook-173.md` | 强 CF 站 `--route-b`（路线 B） |
| `程序使用说明.md` | 单条 `fulltext_fetcher` 细参数 |

---

## 合规声明

- **仅供研究自用**，只获取**免费开放获取**内容。
- 直抓 Google Scholar 违反其 ToS 与 `robots.txt`；本工具**主线走官方开放 API（无验证码、合规）**，不直抓 Scholar（合规守卫永不渲染 Scholar）。
- **付费墙内全文任何免费路线都拿不到**——属合理边界，靠机构订阅 / 馆际互借解决。
- 路线 B 浏览器内直下 / 机构订阅通道仅供**已合法获取访问权**者使用。

---
---

# 附录 A：七角度「过 Scholar 人机认证」选型调研（研究档）

> 整理人：谷歌学术人机认证-152｜2026-07-01。以下为本仓早期「过 Scholar 人机检测、抓元数据 + 下 PDF」的系统性选型调研，作为研究背景保留；生产落地请用上方「一键正门」。

> **一句话结论**：**能用「角度2 官方开放 API」（OpenAlex / Semantic Scholar / Crossref / Unpaywall）就别去抓 Scholar**——开放 API 根本没有验证码、合规、免费/低价，且已在 `poc/` 实测可跑；只有非要 Scholar 原生口径（被引/版本）时，才考虑「角度4 付费买断」或「角度1+3+6 自建斗法」。付费墙内全文任何路线都拿不到。

## A.1 这是什么

从 **7 个角度** 系统检索了"过 Scholar 人机认证、抓元数据 + 下 PDF"的全部可行路线，聚合成一份**结论先行的选型决策书**，并附一套**可运行的最小实现（`poc/`）**——**只给方向，细节一律指向 `00` 主报告**。

## A.2 怎么读（推荐顺序）

1. **先看** [`检索成果-00b-一页决策速览.md`](检索成果-00b-一页决策速览.md) —— 一页纸决策树 + 速查表 + 三条铁律，30 秒选定路线。
2. **再读** [`检索成果-00-聚合总报告与选型决策.md`](检索成果-00-聚合总报告与选型决策.md) —— 完整论证：七角度全景、决策分层、落地工作流、选型矩阵、合规风险。
3. **按需翻** 对应的 `检索成果-角度1~7-*.md` —— 仅在需要某条路线的实现细节时再看。
4. **要动手** 直接进 [`poc/`](poc/) 跑主线最小实现。

## A.3 文件清单

| 文件 | 一句话作用 | 整理人 |
| --- | --- | --- |
| `检索成果-00-聚合总报告与选型决策.md` | 七角度总聚合 + 选型决策书（**主报告**） | 150 |
| `检索成果-00b-一页决策速览.md` | 一页纸决策图（决策树 + 速查表 + 三铁律） | 150 |
| `检索成果-角度1-GitHub开源项目直检.md` | GitHub 可直接 clone 的爬取/下载项目总目录 | 152 |
| `检索成果-角度2-官方开放API替代路线.md` | 官方开放 API 替代（**主线·首选**） | 144 |
| `检索成果-角度3-反爬与反reCAPTCHA技术深度.md` | 分层反爬技术栈（三层 + 两翼） | 144 |
| `检索成果-角度4-商业抓取与第三方ScholarAPI服务.md` | 商业 / 第三方 Scholar API（付费买断免战） | 150 |
| `检索成果-角度5-即用型工具与平台.md` | 即用型工具 & 平台（免代码） | 152 |
| `检索成果-角度6-代理基础设施.md` | 代理基础设施（住宅/移动代理 + 自建池） | 152 |
| `检索成果-角度7-中文社区与镜像站.md` | 中文社区与镜像站（人工/低量转嫁） | 151 |
| `检索成果-99-交叉核对与一致性审计.md` | 跨文档交叉引用核对 + 术语/结论统一记录 | 152 |
| `检索成果-98-数据与链接复核.md` | 数据与链接复核记录（148 维护中） | 148 |
| `poc/` | 角度2 主线可运行实现（检索 → 定位 OA → 下载 → 入库） | 150 |
| `poc/self_built_stack/` | 角度1+3+6 自建栈可运行样例（默认 dry-run·py_compile 通过） | 152 |

> 各产物均由对应成员产出；`检索成果-00` 第八节收口清单为最新状态的唯一权威。

## A.4 poc 快速上手

```bash
cd poc
pip install -r requirements.txt   # 仅依赖 requests
```

**单源最小示例**（OpenAlex 检索 + Unpaywall 兜底）：

```bash
python openalex_oa_pipeline.py "large language model" --email you@example.com --max 20 --year-from 2024 --oa-only
```

**多源增强版（推荐，可选 Zotero 入库）**：

```bash
python scholar_multi_pipeline.py "graph neural network" --email you@example.com --max 25 --sources openalex,crossref,s2 --year-from 2023
```

产出：`out/pdfs/*.pdf`、`out/metadata.jsonl`、`out/index.json`（多源版另出 `out/zotero.csl.json` / `out/references.bib`）。完整参数、实测记录与 Zotero 入库说明见 [`poc/README.md`](poc/README.md)。

> **自建斗法对照样例**（角度1+3+6：`scholarly` + 反爬位 + 代理位，**默认 dry-run、强合规警告、不真抓 Scholar**）见 [`poc/self_built_stack/`](poc/self_built_stack/)——仅供「确需直抓 Scholar」时参考，主线仍力荐角度2。

## A.5 七角度一句话索引

| 角度 | 一句话定位 | 路线性质 |
| --- | --- | --- |
| **1** | GitHub 现成爬取/下载载体（scholarly / PyPaperBot / paperscraper…） | 自建·**载体** |
| **2** | 官方开放 API 替代（OpenAlex / S2 / Crossref / Unpaywall） | **主线·首选** |
| **3** | 反爬 / 反 reCAPTCHA 分层技术栈（curl_cffi → nodriver → 代理 → 打码） | 自建·**技术备线** |
| **4** | 商业 / 第三方 Scholar API 与一体化解锁服务 | **付费·买断免战** |
| **5** | 即用型工具 & 平台（Publish or Perish / Zotero / AI 学术搜索） | 终端·**免代码** |
| **6** | 代理基础设施（住宅/移动代理对比 + 自建代理池） | 自建·**资源底座** |
| **7** | 中文社区与镜像站（烂番薯等） | 人工·**低量转嫁** |

## A.6 合规声明（研究档）

- **仅供研究自用**。直抓 Google Scholar 违反其 ToS 与 `robots.txt`，全程灰色（涉及角度 **1/3/4/6/7**）。
- **唯一白色合规路线 = 角度2 开放 API**（官方鼓励调用、无验证码），亦为本项目力荐的主线。
- 商业服务商的"法律盾"（SerpApi 等）只**部分缓释**风险，**不等于免责**。
- **付费墙内全文任何路线都拿不到**——属合理边界，靠机构订阅 / 馆际互借解决，不在本课题强求。

---

> 生产落地用「一键正门」（本文顶部）；研究背景见附录 A。详细论证见 `检索成果-00-聚合总报告与选型决策.md`。
