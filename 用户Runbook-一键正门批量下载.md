# 用户 Runbook · 一键正门批量下载

> 交付：**谷歌学术人机认证-159**（worker）｜2026-07-02  
> 定位：**用户如何跑一键正门**——整合现有文档，不重研。  
> 整合来源：`北极星一键批量下载-主流程与回收结论汇总.md`、`交付收敛核对-run_all一键正门与回收主表归并-149.md`、`run_all.py`、`pyproject.toml`  
> 边界：只产本 Runbook；**不改**代码 / coverage / 黑名单。
> 155 更新（2026-07-03）：run_all 默认统一命名 + 全自动 E2E 实测（§4.2 / §6.5）；仅改 `run_all.py` 一层默认命名模板，核心库 `Config`、coverage 口径、黑名单均未动，selftest 保持 46/0/2。

---

## 〇、30 秒速览

```powershell
cd "e:\AI项目\谷歌学术人机认证"
pip install -e ".[qc]"
$env:OPENALEX_KEY = "你的OpenAlex免费Key"
$env:FULLTEXT_EMAIL = "you@uni.edu"

python run_all.py -f my_papers.txt --email $env:FULLTEXT_EMAIL -o out/my_batch
```

跑完后看终端 **「一页式总结」**，PDF 在 `out/my_batch/fetch/pdfs/`（**默认统一命名** `{year}_{author}_{title}_{doi}`，人类可读、全部落同一文件夹），仍缺的 DOI 在 `out/my_batch/still_missing.txt`（可直接作下一轮输入）。

> **全自动 · 无人值守**：默认不弹浏览器、不需人工登录、不需 AI 介入——一条命令跑到底，每条输入都有明确终态（成功落盘 / 进 still_missing）。强 CF 站（RSC/ACS 等）或机构订阅才需额外开关（见 §3.4 / §7）。

---

## 1. 环境 / 依赖

### 1.1 基础要求

| 项 | 要求 |
|---|---|
| Python | **≥ 3.8**（见 `pyproject.toml`） |
| 操作系统 | Windows / Linux / macOS 均可 |
| 网络 | 需要联网（多源 API + 出版商直链） |

### 1.2 安装

```powershell
# 进入项目根目录
cd "e:\AI项目\谷歌学术人机认证"

# 可编辑安装（推荐）
pip install -e .

# 内容 QC 门（强烈建议：拦 websearch 抓错论文假阳）
pip install -e ".[qc]"

# 可选：读 .xlsx 输入表
pip install -e ".[xlsx]"

# 离线验证环境 OK（不联网）
python run_all.py --selftest          # → RUN_ALL_OK
python tools/build_coverage.py --selftest   # → COVERAGE_OK
python run_all_selftests.py           # 全项目回归（可选）
```

运行期**硬依赖**仅 `requests>=2.28`（见 `fulltext_fetcher/requirements.txt`）。`[qc]` 额外装 `pypdf` + `rapidfuzz`，用于落盘前内容 QC。

### 1.3 必设 / 建议设的环境变量

| 变量 | 是否必设 | 用途 |
|---|---|---|
| **`OPENALEX_KEY`** | **强烈建议** | OpenAlex API 免费 Key；不设则 openalex 源限速更严、命中率下降 |
| **`FULLTEXT_EMAIL`** | 建议 | Unpaywall 礼貌池标识；也可用 `--email` 传参 |
| `CORE_API_KEY` | 可选 | CORE 聚合源（默认源顺序里含 core，无 key 时该源跳过） |

**PowerShell 示例**：

```powershell
$env:OPENALEX_KEY   = "粘贴你的OpenAlex Key"
$env:FULLTEXT_EMAIL  = "you@uni.edu"
```

OpenAlex 免费 Key 申请：见仓内 `检索成果-OpenAlex免费Key注入路径核查与5分钟落地runbook-148.md`（openalex.org 注册即可）。

### 1.4 与 `python -m fulltext_fetcher` 的区别

| 入口 | 适合场景 |
|---|---|
| **`python run_all.py`**（本 Runbook） | **批量 + 跨批续跑 + coverage 报告**（推荐正门） |
| `python -m fulltext_fetcher` | 单条 / 临时查一篇、细调 `--sources` |
| `python run_all_selftests.py` | **自检回归**，不是批量下载 |

勿把 `run_all_selftests.py`（自检）当成 `run_all.py`（下载）。

---

## 2. 输入格式

### 2.1 支持的文件类型

`-f` 清单支持 **`.txt` / `.csv` / `.xlsx`**（复用 `cli._read_input_file`）。

### 2.2 `.txt` 清单（最常用）

- **一行一条**：DOI、arXiv ID、或论文标题均可**混排**
- 以 `#` 开头的行视为注释，跳过
- DOI 可带或不带 `https://doi.org/` 前缀

**样例 `my_papers.txt`**：

```text
# 催化 / CO2 相关样例（DOI + 标题混排）
10.1038/s41929-019-0266-y
10.1021/acscatal.7b01827
Attention is all you need
https://doi.org/10.1016/j.apcatb.2025.126016
1706.03762
```

### 2.3 命令行直接输入

也可不用 `-f`，直接在命令后跟多个参数：

```powershell
python run_all.py "10.1038/nature14539" "1706.03762" -o out/demo
```

### 2.4 去重规则（自动）

1. **输入内去重**：同一 DOI（规范化后）或同一标题（小写）只跑一条  
2. **跨批续跑**（默认 `--resume`）：扫描 `out/` 下已有 coverage，**已在盘上真实成功的 DOI 自动跳过**

---

## 3. 命令（正门用法）

### 3.1 标准批量（推荐）

```powershell
python run_all.py `
  -f my_papers.txt `
  --email you@uni.edu `
  --openalex-key $env:OPENALEX_KEY `
  -o out/my_batch `
  -c 3
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `-f` / `--input-file` | — | 输入清单 |
| `-o` / `--out` | `out/run_all` | **独立输出根目录 RUNROOT**（每次批量建议用新目录名） |
| `--email` | `$FULLTEXT_EMAIL` | Unpaywall 联系邮箱 |
| `--openalex-key` | `$OPENALEX_KEY` | OpenAlex API Key |
| `-c` / `--concurrency` | `3` | 并发数（礼貌真流量，勿盲目加大） |
| `--coverage-root` | `out` | 跨批续跑扫描根 + QC 黑名单所在目录 |
| `--resume` | **开** | 剔除已 covered 的 DOI |
| `--no-resume` | — | 强制全量重跑（不剔除已成功） |
| `--no-qc` | — | ⚠️ 不消费 QC 黑名单 → 净成功率**虚高**（仅调试） |
| `--no-download` | — | 只定位候选、不下载 PDF |
| `--sources` | 全部源 | 逗号分隔自定义源顺序 |
| `--naming-template` | `{year}_{author}_{title}_{doi}` | **默认统一命名**；改模板或设 `"{doi}"` 退回纯 DOI 名 |
| `--route-b` | `off` | 路线 B：`off` / `cf-only` / `all`（需 nodriver + 有头浏览器） |

### 3.2 闭环续跑（North Star 循环）

```powershell
# 第一轮
python run_all.py -f round1.txt --email you@uni.edu -o out/run_all_r1

# 第二轮：用上一轮 still_missing 作输入（--resume 默认仍会跨 out/ 剔已成功）
python run_all.py -f out/run_all_r1/still_missing.txt --email you@uni.edu -o out/run_all_r2
```

### 3.3 仅重算 coverage（不下载）

若已有多个 `out/*/fetch/` 或 `out/*/metadata.jsonl`，可单独：

```powershell
python tools/build_coverage.py --out-root out
# → out/coverage.json + out/still_missing.txt
```

### 3.4 机构订阅（路线 A · 有凭据时）

机构订阅**不走 run_all 专用开关**，仍用 `fulltext_fetcher --institutional`。见 `路线A-机构订阅实测Runbook-凭据到手3步.md`。无凭据则跳过。

---

## 4. 输出说明

### 4.1 目录布局（`-o out/my_batch` 为例）

```
out/my_batch/
├── fetch/                      # 本次下载批次
│   ├── pdfs/                   # ★ PDF 落盘目录
│   │   └── 10.1021_acscatal.xxx.pdf
│   ├── metadata.jsonl          # 每条输入一行 JSON 总账
│   ├── attempts.jsonl          # 结构化事件流（调试）
│   ├── summary.json            # 本次 run 汇总（仅本次 processed）
│   ├── results.csv             # 表格视图
│   ├── report.html             # 浏览器可读报告
│   └── run.log                 # 人类可读日志
├── coverage.json               # 跨批去重 coverage 主库
├── still_missing.txt           # 仍缺 DOI 全集（可续跑）
└── run_all_summary.json        # 本次 run_all 机器可读总结
```

### 4.2 PDF 文件名规则（**默认即统一命名**，155 起）

`run_all.py` 作为「一键正门」**默认就开统一命名**，模板 `{year}_{author}_{title}_{doi}`，直击北极星「输出文件名标准化的系列全文」。155 波真机实测样例：

| 元数据情况 | 落盘文件名（实测样例） |
|---|---|
| 年/作者/标题齐全 | `2015_LeCun_Deep_learning_10.1038_nature14539.pdf` |
| 齐全（长标题自动截断） | `2018_Piwowar_The_state_of_OA_a_large-scale_analysis_..._10.7717_peerj.4375.pdf` |
| 仅有 DOI（元数据缺失）→ 优雅降级为纯 DOI 名 | `10.48550_arxiv.1706.03762.pdf` |

- 占位符：`{year}` `{author}`（首作者姓）`{title}` `{doi}` `{venue}`；非法字符 → `_`，stem 最长 140 字符；同名自动 `_2/_3` 去重。
- **改模板**：`--naming-template "{author}-{year}"`（或设环境变量 `FULLTEXT_NAMING_TEMPLATE`）；**退回旧版纯 DOI 名**：`--naming-template "{doi}"`。
- 兼容性：**核心库 `Config.naming_template` 仍默认 `None`（逐字节向后兼容）**，只有 `run_all` 这层默认统一；单条 `python -m fulltext_fetcher` 不受影响。
- **切换命名不影响 coverage / 续跑 / KPI**：`build_coverage` 只按 `metadata.jsonl` 里 `pdf_path` 的 basename 对盘判成功（与文件名形状无关）。**但仍不要手工改名**——手改会让 `pdf_path` 与磁盘不符、被判 miss。

### 4.3 `metadata.jsonl` 关键字段

每行一条 JSON，常用字段：

| 字段 | 含义 |
|---|---|
| `raw_input` | 原始输入 |
| `doi` / `title` | 解析结果 |
| **`success`** | `true` = 本次下载落盘成功；`false` = miss |
| `pdf_path` | 落盘路径（成功时有值） |
| `pdf_bytes` | 文件大小 |
| `source_used` | 最终命中源（如 `websearch`、`crossref`） |
| **`error`** | 失败原因（如 `no-downloadable-pdf`、`http-403`） |
| `attempts[]` | 各源尝试明细 |

### 4.4 终端「一页式总结」

跑完 `run_all.py` 末尾会打印类似：

```text
========================================================================
run_all 一页式总结  (RUNROOT=out/my_batch, ...)
------------------------------------------------------------------------
输入清单        : 100 条  →  去重后 98 条(去重 -2)
跨批续跑跳过    : 12 条(已在既有 out/ 真实成功)
本次实际下载    : 86 条
------------------------------------------------------------------------
本次结果        : 成功 45 / 处理 86(miss 41),用时 1234s
本次命中源      : websearch=30, crossref=10, ...
------------------------------------------------------------------------
RUNROOT 覆盖(可信): 唯一 DOI 98 | 净成功 52 | still_missing 46 | 净成功率 53.1%
  (QC 剔抓错论文: 原始成功 60 → 剔 8 → 净 52)
QC 黑名单        : 硬黑 51 / 并集 343 DOI
------------------------------------------------------------------------
PDF 目录        : out/my_batch/fetch/pdfs
coverage.json   : out/my_batch/coverage.json
still_missing   : out/my_batch/still_missing.txt  (46 条)
run_all_summary : out/my_batch/run_all_summary.json
========================================================================
```

> **净覆盖率数字**以 `coverage.json` 的 `generated_ts` 为准；**定版权威 = 326/673/32.63%**（2026-07-03 12:50:24，allow=10）。见《基线口径冻结说明-388-173.md》。

---

## 5. 日志判读（成功 / miss / QC 拒）

### 5.1 三层结果，不要混读

| 层级 | 看什么 | 含义 |
|---|---|---|
| **① 本次 run** | 一页式总结「本次结果 成功 X / 处理 Y」 | 仅**本轮新跑**的条目 |
| **② metadata 成功** | `metadata.jsonl` 里 `success:true` | 本次 run 声称下载成功（**可能含抓错论文**） |
| **③ 净 coverage** | 一页式「RUNROOT 覆盖(可信)」或 `coverage.json` | **去重 + PDF 落盘实证 + QC 黑名单剔除** 后的诚实成功 |

日常 KPI 请认 **③**；①② 可能虚高（尤其 websearch 源）。

### 5.2 判定「成功」

同时满足：

1. `metadata.jsonl` → `"success": true`
2. `pdf_path` 指向的文件在 `fetch/pdfs/` **确实存在**
3. 文件头为 `%PDF`（程序已校验）
4. 若启用 QC（默认）：DOI **不在** `out/qc_merge_*_wrong.csv` 黑名单中

### 5.3 判定「miss」（真失败）

常见 `error` 值：

| error | 含义 | 下一步 |
|---|---|---|
| `no-downloadable-pdf` | 各源均无可用 PDF 直链 | 付费墙 → 机构订阅；强 CF → route-B |
| `http-403` / `http-401` | 被出版商拒 | 同上 |
| `not-pdf(...)` | 下到 HTML 登录页/落地页 | 换源或 route-B |
| `claimed_success_but_no_pdf` | metadata 说成功但盘上无文件 | 重跑该 DOI |

`still_missing.txt` = 所有仍 miss 的 DOI 列表（含 QC 改判 miss 的条目）。

### 5.4 判定「QC 拒收」（假成功被剔除）

现象：

- `metadata.jsonl` 里 **`success: true`**（当时下了某个 PDF）
- 但 `coverage.json` 里该 DOI **`status: "miss"`**，且带：
  - `"qc": "hard_reject"` 或 `"soft_reject"`
  - `"error": "qc_hard_reject:wrong-paper(...)"` 等

含义：PDF 在盘上可能是**错论文 / SI 封面 / 无关文档**——已被审计黑名单改判，**不计入净成功**。这是预期行为，不是 bug。

查看 QC 消费情况：一页式总结里 `QC 剔抓错论文: 原始成功 A → 剔 B → 净 C`。

### 5.5 快速人工抽查

1. **浏览器**：打开 `out/my_batch/fetch/report.html`  
2. **表格**：`results.csv`  
3. **逐条**：`metadata.jsonl` 筛 `"success": true`  
4. **净口径**：`coverage.json` → `summary.qc.success_after_qc`

### 5.6 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 成功率突然很高（>70%） | 用了 `--no-qc` 或缺 `[qc]` 依赖 | 装 `pip install -e ".[qc]"`，去掉 `--no-qc` |
| 同一 DOI 被跳过 | `--resume` 认为已 covered |  intentional；要强制重下用 `--no-resume` |
| `Event loop is closed`（Windows） | asyncio  teardown 竞态 | 一般不影响 PDF；见经验记录 |
| 并发写同一 `-o` 报错 | Pipeline 写锁 | 每次批量用**不同** `-o` 目录 |

---

## 6. 最小工作流（复制即用）

```powershell
# 0. 一次性环境
cd "e:\AI项目\谷歌学术人机认证"
pip install -e ".[qc]"
$env:OPENALEX_KEY  = "你的Key"
$env:FULLTEXT_EMAIL = "you@uni.edu"

# 1. 准备 inputs/my_list.txt（一行一条 DOI 或标题）

# 2. 跑批量
python run_all.py -f inputs/my_list.txt `
  --email $env:FULLTEXT_EMAIL `
  --openalex-key $env:OPENALEX_KEY `
  -o out/run_20260702

# 3. 看结果
#    PDF     → out/run_20260702/fetch/pdfs/
#    报告    → out/run_20260702/fetch/report.html
#    仍缺    → out/run_20260702/still_missing.txt

# 4. 续跑（可选）
python run_all.py -f out/run_20260702/still_missing.txt `
  --email $env:FULLTEXT_EMAIL -o out/run_20260702_r2
```

---

## 6.5 全自动 E2E 真机实测（155 波·可复现证据）

用一条命令 + 19 条混合输入（OA / 订阅墙 / 强 CF / Akamai / 标题-only / 坏 DOI / 去重）真跑一遍，**全程无人值守、无浏览器弹窗、无 AI 介入**：

```powershell
python run_all.py -f e2e_mixed_155_input.txt --email you@uni.edu -o out/final_run_155 --no-resume
```

实测结果（`out/final_run_155/run_all_summary.json`）：

| 指标 | 值 |
|---|---|
| 输入 → 去重 | 19 → 18（去重 -1） |
| 净成功 / 处理 | **14 / 18（净成功率 77.8%）** |
| 命中源 | unpaywall=4, websearch=3, europe_pmc=2, openalex/arxiv/preprints/semantic_scholar/crossref 各 1 |
| still_missing | 4（2 book-chapter landing 无内嵌 PDF、1 MDPI http-404、1 坏 DOI no-candidates） |
| 统一命名 | 14 篇全部落 `out/final_run_155/fetch/pdfs/` 单一文件夹；元数据齐全者人类可读、缺失者优雅降级为 DOI 名 |
| selftest | `python run_all_selftests.py` → **PASS=46 FAIL=0 SKIP=2** |

每条输入都有明确终态：成功→统一命名 PDF；失败→`still_missing.txt` + `run_all_detail.tsv` 里带失败原因分桶（`grep '^MISS'` 即见）。输入清单见仓根 `e2e_mixed_155_input.txt`。

---

## 7. 延伸阅读（不在本 Runbook 重复）

| 文档 | 用途 |
|---|---|
| `北极星一键批量下载-主流程与回收结论汇总.md` | 主流程设计与回收结论背景 |
| `基线口径冻结说明-388-173.md` | 净覆盖率 KPI 口径 |
| `程序使用说明.md` | 单条 `fulltext_fetcher` 细参数 |
| `路线A-机构订阅实测Runbook-凭据到手3步.md` | 有机构凭据时 |
| `路线B-浏览器内直下PDF验证Runbook-173.md` | 强 CF 站 `--route-b` |

---

*159｜2026-07-02｜用户前门 Runbook；整合现有文档，未改代码。*
*155｜2026-07-03｜更新：run_all 默认统一命名 `{year}_{author}_{title}_{doi}`（§4.2）；补全自动 E2E 真机实测证据（§6.5，14/18·selftest 46/0/2）。*
