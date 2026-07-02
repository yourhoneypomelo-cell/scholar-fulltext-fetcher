# 路线B · 浏览器内直下 PDF 验证 Runbook

> 交付：**信息检索-专家智库 · 谷歌学术人机认证-173**｜2026-07-02  
> 触发：ROI 深挖完成后用户直派「基于 ROI 起草浏览器内直下 PDF 验证 Runbook」。  
> 依据：`检索成果-still_missing-CF-JA3桶ROI深挖-173.md`、`ROI-路线B-render_fetch.md`（-144）、`选型2026-强CF浏览器内直下PDF实现者骨架-renderfetch-CDP.md`（-177）。  
> 边界：**只新建本 1 份 runbook**；不改 `.py`。实现与冒烟脚本已在仓内（`render_fetch.py`、`download.py`、`_smoke_render_bytes.py`）。

---

## 〇、验证目标（跑完应能回答什么）

| 问题 | 通过标准 |
|---|---|
| **机制是否端到端通？** | 至少 1 条 **ACS-OA**（不绑 JA3 的 CF 后 OA）抓到 `%PDF` 且 size ≥ 100KB |
| **JA3 型站是否「不误报」？** | RSC/ScienceDirect **订阅墙** DOI 应返回 `no-pdf` / `blocked:`，**不得**落盘 HTML/假 `%PDF` |
| **JA3 型站是否有免费 OA 可救？** | 若有 green OA 样本，应抓到 `%PDF`；若无则 `no-pdf` 即正确（非 bug） |
| **与 curl_cffi 回放对比** | 同一 RSC URL：FS 解 CF + curl 回放 **403**；页内直下 **≠403 或 no-pdf**（证明走不同路径） |
| **内容 QC** | 成功样本须 **DOI-in-text 或标题 match**（勿只信 `%PDF`） |

**诚实预期**（ROI 口径）：全量 still_missing 净增点估 **+20 篇（+2pp）**；本 runbook 只验**机制**，不验批量覆盖率。

---

## 第 0 步：环境自检（5 分钟，离线 + 依赖）

### 0.1 依赖

```powershell
cd "E:\AI项目\谷歌学术人机认证"
pip install -r fulltext_fetcher/requirements.txt
python -c "import nodriver; print('nodriver', nodriver.__version__)"
```

- **必需**：`nodriver`（仓内基准 0.50.3+）
- **可选**：`pypdf` + `rapidfuzz`（内容 QC 人工复核用）

### 0.2 显示环境（有头模式）

路线B **默认有头**（`headless=False`），CF 通过率显著高于无头。

- **Windows 桌面**：直接在本机 PowerShell 跑即可（会弹出 Chrome 窗口）。
- **无显示器 / CI**：需虚拟显示；本 runbook **不建议**在无头环境做 JA3 验收（仅跑离线 selftest）。

### 0.3 离线 selftest（不联网、不启浏览器）

```powershell
python -m fulltext_fetcher.render_fetch --selftest
python run_all_selftests.py
```

期望：`RENDER_OK`；`run_all_selftests.py` → **PASS 全绿**（含 `render_fetch` 字节扩展点 mock 用例）。

---

## 第 1 步：单 URL 冒烟（CLI，~1 分钟/条）

**用法**：传 **文章页 URL**（`https://doi.org/<doi>` 或出版商文章页），**不要**传 `pdf.sciencedirectassets.com/...md5=` 短链。

### 1.1 ACS-OA happy path（证机制通）

```powershell
python -m fulltext_fetcher.render_fetch `
  "https://doi.org/10.1021/acsanm.1c00959" `
  --capture-bytes --timeout 90 `
  --save "out/runbook_b/10.1021_acsanm.1c00959.pdf"
```

**期望 JSON**（stdout）：

```json
{
  "available": true,
  "note": "ok",
  "has_pdf_bytes": true,
  "is_pdf": true,
  "size": <大于 100000>
}
```

stderr 应出现 `[已落盘] out/runbook_b/...`。

### 1.2 RSC 订阅墙（证不误报）

```powershell
python -m fulltext_fetcher.render_fetch `
  "https://doi.org/10.1039/c1gc15503b" `
  --capture-bytes --timeout 90
```

**期望**：`is_pdf: false`；`error` 为 `no-pdf:...` 或 `blocked:...`（**不是**假 `%PDF`）。退出码 **1**。

### 1.3 合规守卫（Scholar 必须拒）

```powershell
python -m fulltext_fetcher.render_fetch `
  "https://scholar.google.com/scholar?q=test" `
  --capture-bytes
```

**期望**：`error` 含 `refused:`；**绝不**启动抓取。

---

## 第 2 步：批量小样冒烟（`_smoke_render_bytes.py`，~3–5 分钟）

仓内临时脚本（覆盖 ACS-OA + RSC 各 1 条）：

```powershell
$env:SMOKE_TIMEOUT = "90"
python _smoke_render_bytes.py
```

**期望输出**：

```
SUMMARY: total=2  pdf_ok=1  blocked=0  no_pdf=1  err/other=0
saved PDFs -> out\render_bytes_smoke
SMOKE_DONE
```

- **ACS-OA**：`is_pdf=True`，size > 0，head=`%PDF-`
- **RSC 订阅**：`is_pdf=False`，note 含 `no-pdf` 或 `blocked`

**扩展样本**（可选，自行改 `SAMPLE` 列表或命令行循环）：

| 标签 | DOI | 预期 |
|---|---|---|
| ACS-OA | `10.1021/acsanm.1c00959` | ✅ PDF |
| RSC 订阅 | `10.1039/c1gc15503b` | no-pdf/blocked |
| RSC OA（若有） | 从 still_missing 挑 1 条 green OA | ✅ 或 no-pdf（视是否有免费全文） |
| Elsevier SD | `10.1016/j.apcatb.2021.120319` | 多为 no-pdf（IP/登录墙，非 JA3 主矛盾） |

---

## 第 3 步：与 download 管线集成验证（可选，实现者）

验证 `download.py` 在 CF/JA3 失败分支是否路由到 `render_download_pdf_bytes`：

```powershell
# 需 cfg：browser_pdf_download 或 render_fallback + JA3 域检测
# 具体 flag 以 cli.py / Config 为准；示例（单条、独立 out）：
python -m fulltext_fetcher "10.1021/acsanm.1c00959" `
  --email you@uni.edu `
  -o out/runbook_b_pipeline `
  --browser-pdf-download
```

检查 `out/runbook_b_pipeline/metadata.jsonl`：

- `success: true`
- `source_used` 含 browser/render 相关标记
- `pdfs/` 下文件 `%PDF` 魔数 + 体积达标

> ⚠️ 集成路径 flag 名以当前 `cli.py --help` 为准；本 runbook 不硬编码可能变动的参数。

---

## 第 4 步：JA3 对照实验（证「页内直下 ≠ curl 回放」）

**目的**：复现 -179/-145 发现——FS 已拿 `cf_clearance`，curl_cffi 回放 RSC 仍 403。

1. 启 FS shim（另开终端）：

```powershell
python tools/flaresolverr_nodriver.py --port 8191
$env:FLARESOLVERR_URL = "http://127.0.0.1:8191"
```

2. 对 RSC `articlepdf` URL 用 **普通 download**（走 FS→curl 回放）→ 记录 `attempts.jsonl` 中 `cloudflare-challenge` / 403。

3. 对 **同一 DOI 文章页** 用 **第 1 步 `--capture-bytes`** → 记录是否 `is_pdf` 或至少 error **不是**「curl 回放 403 同一链路」。

**判定**：

- 回放链 403 + 页内直下 no-pdf → **订阅墙**（无免费 PDF，两路都正确）
- 回放链 403 + 页内直下 **有 PDF** → **JA3 死结被路线B 解开**（高价值样本，务必存档 DOI + PDF hash）

---

## 第 5 步：内容 QC（必做，防假阳）

对第 1–2 步所有 `is_pdf=True` 的落盘文件：

```powershell
python tools/qc_content_match.py --help
# 或人工：pypdf 抽首页，核对 DOI/标题与期望 DOI 一致
```

**硬拒信号**（见经验记录 M 节）：

- 首页含 `Supporting Information` / `S-1` → **SI 附件，非正文**
- `citation-report.pdf` / exaly.com → **引用报告**
- 1 页 + `poster template` → **海报**
- 文内 DOI ≠ 期望 DOI → **同题他刊/错论文**

**Runbook 通过附加条件**：ACS-OA 成功样本 QC verdict = **match**。

---

## 通过 / 不通过判定表

| 级别 | 条件 |
|---|---|
| **P0 通过（可合并主线）** | 0.3 selftest 全绿 + 1.1 ACS-OA 落 PDF + 1.2 RSC 不误报 + 5 步 QC match |
| **P1 通过（可开 still_missing 小批回收）** | P0 + 至少 1 条 JA3 域 **真 OA** 被路线B 独有救回（或证伪：该 DOI 确无免费全文） |
| **不通过** | 抓到 HTML/非 PDF 却 `is_pdf=true`；Scholar 未 refused；selftest FAIL |

---

## 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `need nodriver` | 未安装 nodriver | `pip install nodriver` |
| 窗口闪退 / `capture failed` | 无显示、Chrome 路径 | 本机有头跑；查 Chrome 是否安装 |
| 长时间 hang | CF 质询 + 超时不足 | `--timeout 120`；straggler 阈值见 pipeline CF 感知 ≥900s |
| `blocked:just a moment` | CF 未过 | 改有头；同 origin 重试；必要时 camoufox 受控升级 |
| `no-pdf` on 应有 OA | 订阅墙无免费版 | **正确行为**，非实现 bug |
| 落盘 PDF 但 QC mismatch | websearch 类假阳 | 拒收；加强内容闸门 |

---

## 产物清单（验收归档）

每次完整跑通应留存：

```
out/runbook_b/
  *.pdf                    # 成功样本
  runbook_notes.txt        # 手工记录：DOI、耗时、error、QC verdict
out/render_bytes_smoke/    # _smoke_render_bytes.py 输出
```

---

## 与 ROI / 排期关系

| ROI 项 | 本 runbook 覆盖 |
|---|---|
| 路线B +20 篇点估 | 第 2–4 步验机制；批量回收另开 `-f still_missing.txt` 子集 |
| FS shim ACS 桶 | 第 4 步对照；ACS 可走 FS 回放，不必强走路线B |
| ~300 订阅墙 | 第 1.2/2 步 `no-pdf` **预期行为** |
| QC 闸门 | **第 5 步必做** |

---

## 证据索引

- `fulltext_fetcher/render_fetch.py` — `render_download_pdf_bytes()`、`--capture-bytes` CLI
- `fulltext_fetcher/download.py` — `_browser_capture_fallback`、`_nodriver_fetch_pdf_bytes`
- `_smoke_render_bytes.py` — 2 条 ACS/RSC 小样
- `tools/flaresolverr_nodriver.py` — 第 4 步对照
- `tools/qc_content_match.py` — 第 5 步内容 QC

---

*核验 2026-07-02｜信息检索-专家智库 · -173｜路线B 验证 Runbook，供实现者/运维照做。*
