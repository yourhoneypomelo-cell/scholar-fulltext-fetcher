# 选型2026 — scansci-pdf 竞速引擎源码架构拆解 与 fulltext_fetcher 并行化改造方案

> **定位**：项目智库（142）对 `scansci-pdf` 多源并行竞速引擎的**源码级**拆解，并据此给出把本项目 `fulltext_fetcher` 从「单条内顺序回退」升级到「单条内并行竞速」的落地改造方案。
> 整理人：谷歌学术人机认证-142（项目智库）｜2026-07-02
> **状态**：智库检索成果，待总指挥（147）判断采纳/排期。
> **源码基准**：`Rimagination/scansci-pdf`（master 分支，503★，Apache-2.0），核心文件 `src/scansci_pdf/sources/__init__.py`(47KB)、`sources/scoring.py`、`config.py`。

---

## 摘要（TL;DR）

- **最大差异**：`fulltext_fetcher` 的并行只在**输入之间**（一次跑多个 DOI，`ThreadPoolExecutor`）；**单个 DOI 内部是顺序回退**（逐源试、首个直链成功即短路）。scansci-pdf 在**单个 DOI 内部让所有源同时竞速**，最快成功者胜出并即时取消其余。
- **收益**：单条延迟从「Σ 各源延迟直到首中」降到「最快命中源的延迟」。对「靠后源才命中」的 DOI 提速最明显；对整批吞吐在慢源占比高时收益巨大。
- **代价**：单条请求量放大（N 源并发）。但因各源命中**不同主机**，与本项目现有 **per-host 礼貌限速**并不冲突，只需新增「单条内源并发上限」和「两级并发预算」防线程爆炸。
- **可直接借鉴的 4 个机制**：① Event 唤醒式竞速原语（非轮询）；② 自适应 EMA 源评分排序（自调优，替代静态优先级）；③ 可疑 PDF 检测（1 页/超小 → 判非全文）；④ 批量 Phase 2 按出版商分组「一次登录多篇」。
- **改造工作量**：核心竞速原语 P0 约 3–5h；EMA 排序 P1 约 1–2h；可疑 PDF P1 约 1h；分组机构 Phase2 P2 约 3–5h（依赖机构订阅落地）。

---

## 一、scansci-pdf 竞速引擎源码架构拆解

### 1.0 模块地图（与竞速相关）

| 文件 | 职责 |
|------|------|
| `sources/__init__.py` | 编排核心：`download()` 单条主流程、`_run_tiers_parallel()` 竞速原语、`_try_source()` 源包装、`batch_download()` 批量 + 分组机构 Phase2 |
| `sources/scoring.py` | 自适应 EMA 评分：`record_result()` 记账、`sort_sources()` 按分排序、`classify_error()` 错误归类、`get_user_advice()` 建议 |
| `sources/publishers.py` | `get_publisher_fast_sources(doi)`：按 DOI 前缀路由出版商快速直链源 |
| `config.py` | 超时/延迟/并发/开关等默认配置 |
| `_core/racing.*`（可选 Cython） | 编译版竞速引擎 `run_parallel_race`，import 失败自动回退纯 Python |

### 1.1 单条 DOI 主流程 `download()`

分层：本地缓存/去重 → arXiv 直取(L0) → **Phase 1 免费源竞速(15s)** → **Phase 2 机构源竞速(30s，仅当 Phase 1 失败)** → 失败兜底扫盘 + 生成可执行建议。

```python
# Phase 1: Free sources (OA + grey) — parallel race
free_sources = _build_free_sources(doi, config)          # 已按 EMA 分排序
if free_sources:
    result = _run_tiers_parallel([(free_sources, "Free", 15)],
                                 doi, target_dir, output_path, config, use_tor, 15)
    if result:
        return _finalize_result(...)                     # 更新索引/改名/缓存/bibtex

# Phase 2: Institutional access — only when Phase 1 failed
if _institutional:
    inst_sources = _build_institutional_sources(doi, config, use_instsci=use_instsci)
    if inst_sources:
        result = _run_tiers_parallel([(inst_sources, "Institutional", 30)],
                                     doi, target_dir, output_path, config, use_tor, 30)
```

要点：
- **命中前置缓存/去重**：`cache_get` + `.doi_index.json`（DOI→文件索引）+ 按重命名模板扫已存在文件（含 `_1.._9` 后缀），避免重复下载。
- **DOI 预校验** `validate_doi`：非法 DOI 直接返回，不浪费竞速。
- **Phase 1 免费、Phase 2 机构**分离：机构（浏览器/CARSI）成本高，只在免费全灭时才触发。

### 1.2 竞速原语 `_run_tiers_parallel()`（核心）

把所有 tier 的源拍平成一个池，一线程一源；**首个成功者用共享结果 + Event 即时唤醒主线程**，而非轮询。

```python
result_lock   = threading.Lock()
success_event = threading.Event()
cancel_event  = threading.Event()
shared_result = {"result": None}

def _try_and_publish(fn, label, src_output):
    if cancel_event.is_set():          # 已有胜者→跳过（协作式取消）
        return None
    result = _try_source(fn, doi, src_output, config, label, use_tor=use_tor)
    if result and result.get("success"):
        with result_lock:
            if shared_result["result"] is None:
                shared_result["result"] = (result, label, src_output)
                cancel_event.set()      # 通知其余源别再进
                success_event.set()     # 唤醒主线程
    return result

pool = ThreadPoolExecutor(max_workers=len(all_sources))   # 一源一线程
for fn, label, tier_label, tier_timeout in all_sources:
    futures[pool.submit(_try_and_publish, fn, label, src_output)] = (label, src_output)

success_event.wait(timeout=overall_timeout + 5)           # 命中即刻返回；否则等到超时
```

超时后的三级兜底（关键工程细节）：
1. **宽限期 grace**：`success_event.wait(grace)` 再等一会儿——`CARSI → 300s`、含 `Browser → 180s`、纯免费 → `15s`。因为可见浏览器 SSO 登录可能 60–300s，硬超时会误杀正在成功的登录。
2. **扫盘兜底**：即使超时，遍历各源临时文件 `{doi}_{label}.pdf`，若有合法 PDF（`is_pdf_file` 且非 `is_suspicious_pdf`）也算成功。
3. **清理**：`finally` 里 `pool.shutdown(wait=False)` + 删除所有非胜者临时文件。

胜者落地：临时文件 `rename` 到最终 `output_path`；其余源临时文件删除。

> **注意其取消是「协作式」**：`max_workers=len(all_sources)` 时所有源几乎同时启动，`cancel_event` 只能挡住尚未进入的极少数；已卡在阻塞 IO 的线程无法强杀（与本项目 straggler 看门狗遇到的约束一致）。真正的止损靠 `success_event` 让**主线程**不等它们即返回。

### 1.3 源包装 `_try_source()`

```python
is_browser = label in _BROWSER_SOURCE_LABELS
sem = _get_browser_semaphore(config) if is_browser else None   # 全局信号量
if sem: sem.acquire()
try:
    result = source_fn(doi, output_path, config[, use_tor])     # 按签名自适应传参
    latency_ms = (time.time() - t0) * 1000
    if result and result.get("success"):
        if is_suspicious_pdf(fp):                # 1 页/超小 → 判非全文
            record_result(label, False, latency_ms, "suspicious_pdf")
            return suspicious_pdf(doi, fp, label)
        record_result(label, True, latency_ms)   # EMA 记账（成功）
    else:
        record_result(label, False, latency_ms, classify_error(status_code))
finally:
    if sem: sem.release()
```

三个亮点：
- **浏览器源全局信号量**（`max_browser_workers` 默认 2）：跨所有 DOI 限制同时打开的 Chrome 窗口，避免 `batch_workers × 每DOI浏览器源` 爆炸。
- **可疑 PDF 检测**：出版商常返回「首页/封面单页 PDF」冒充全文，`is_suspicious_pdf`（按页数/字节）拦截，避免假成功。
- **EMA 记账**：每次尝试都写入成功率/延迟，供下一次排序。

### 1.4 自适应 EMA 源排序 `scoring.py`

指数滑动平均（α=0.1），成功率主排、延迟做二级排；持久化到 `~/.scansci-pdf/source_scores.json`。

```python
_ALPHA = 0.1
entry["success_ema"] = _ALPHA * (1.0 if success else 0.0) + (1-_ALPHA) * entry["success_ema"]
if success and latency_ms > 0:
    entry["latency_ema"] = _ALPHA * latency_ms + (1-_ALPHA) * entry["latency_ema"]

def sort_sources(sources):
    return sorted(sources, key=lambda it: (-get_score(it[1]), get_latency(it[1])))
```

好处：源时好时坏（限流/宕机/恢复）时排序自动跟随；比静态优先级更抗漂移。**注意**：在「全源竞速」语义下，排序主要影响资源占用与临时文件命名，命中仍取决于谁最快；但在「有并发预算需要挑子集竞速」时，排序就决定先派哪些源，价值凸显。

### 1.5 批量 `batch_download()` 与分组机构 Phase 2

- **去重**：按 `normalize_doi` 归一去重。
- **并发预校验**：`ThreadPoolExecutor(10)` 并发 `validate_doi`，非法早筛。
- **断点续跑**：进度写 `batch_progress/{batch_id}.jsonl`（`batch_id = md5(sorted(identifiers))`），重跑跳过已成功。
- **Phase 1 逐 DOI 并发**：`batch_workers`（默认 10）线程，每个 DOI 调 `download(..., _institutional=False)`（**批量下只做免费竞速**），错峰 `batch_stagger_seconds=0.3s` 防惊群。
- **Phase 2 批级分组**：把 Phase 1 失败的 DOI 按出版商 profile 分组，**每个出版商只登录一次浏览器**，用 `PublisherBatchDownloader` 批量取该组全部 DOI（`instsci` 桥）。这是机构订阅路线「一次登录多篇」的关键效率来源。

### 1.6 关键配置（`config.py`）

| 配置 | 默认 | 含义 |
|------|------|------|
| `connect_timeout` / `read_timeout` | 15 / 30 | 连接/读超时（秒）|
| `request_delay_min/max` | 2.0 / 5.0 | 请求间随机延迟 |
| `parallel_sources` / `parallel_probes` | True / True | 源竞速 / 探针并行总开关 |
| `batch_workers` | 10 | 批量跨 DOI 并发 |
| `batch_stagger_seconds` | 0.3 | 批量错峰起步 |
| `max_browser_workers` | 2 | 全局浏览器并发上限 |
| `min_pdf_size_bytes` | 10000 | 小于此判非有效 PDF |

### 1.7 可编译 Cython 核

`_run_tiers_parallel` 开头若 `from .._core.racing import run_parallel_race` 成功则委托编译版；失败回退纯 Python。语义等价，纯性能优化，对本项目**非必需**（本项目是 I/O 密集，GIL 影响小）。

---

## 二、fulltext_fetcher 现状对照

本项目 `pipeline.py` 的并发模型：

```
run(inputs)
 └─ ThreadPoolExecutor(concurrency)         # ← Level 1：输入之间并行（默认 4）
      └─ process_one(raw)
           └─ _gather_and_download(paper)   # ← Level 2：单条内【顺序】回退
                for src in self.sources:    #    逐源 find_candidates
                    for c in direct:        #    直链即时下载
                        if download_pdf(...) success: return   # 首中短路
                # 落地页候选累积到最后再兜底
```

| 维度 | fulltext_fetcher（现状） | scansci-pdf |
|------|--------------------------|-------------|
| 输入间并行（Level 1）| ✅ ThreadPool(concurrency=4) | ✅ batch_workers=10 |
| **单条内源并行（Level 2）** | ❌ **顺序回退 + 首中短路** | ✅ **全源竞速 + Event 唤醒** |
| 源排序 | 静态 `DEFAULT_SOURCE_ORDER`(22 源) | 自适应 EMA 动态排序 |
| 限速 | ✅ per-host 最小间隔（礼貌）| 请求间随机延迟 2–5s |
| 断点续跑 | ✅ metadata.jsonl + 临时/永久失败分类 | ✅ progress.jsonl |
| %PDF/体积校验 | ✅ download.py | ✅ min_pdf_size + 可疑 PDF 页数检测 |
| 尾部卡死处理 | ✅ straggler 看门狗 + 收尾必落盘 | tier grace + 扫盘兜底 |
| 机构订阅 | publisher_direct（`--institutional`，逐 DOI）| 批级按出版商分组一次登录 |
| 可疑单页 PDF 拦截 | ❌（仅体积下限）| ✅ 页数/预览页检测 |

**结论**：本项目在**工程健壮性**（续跑分类、straggler 看门狗、收尾必落盘、per-host 礼貌限速）上做得比 scansci 更细；**唯独缺「单条内源竞速」这一层**，这正是延迟/吞吐的主要短板与本次改造重点。

---

## 三、fulltext_fetcher 并行化改造方案

### 3.1 目标与约束

- **必须保留**：per-host 礼貌限速、断点续跑与失败分类、%PDF 校验、straggler 看门狗、收尾必落盘（P1 无人值守）。
- **新增**：单条内「源竞速」，最快命中即短路取消其余。
- **不破坏**：`no_download`（只定位）、`oa_only`、落地页兜底等既有语义。
- **默认安全**：racing 可用开关控制，默认可先灰度（如 `--race` 开启），保证与现网行为可回退。

### 3.2 方案 A：单条内源竞速（改 `_gather_and_download`）

把「逐源顺序」改为「分组竞速」。因本项目候选分「直链(direct)」与「落地页(landing)」两类且已有 per-host 限速，建议**分档竞速**而非全量裸并发：

```
档 1（快源竞速）：能给直链的 OA/聚合/仓储源（unpaywall/openalex/publisher_oa/arxiv/
                 europe_pmc/s2/pmc/core/base…）→ 并发调用 find_candidates，
                 谁先产出可下载直链并 download_pdf 成功 → 短路取消其余。
档 2（兜底竞速）：落地页候选 + websearch/wayback/scihub(可选) → 仅当档 1 全灭再竞速。
```

竞速原语可直接移植 scansci 的 Event 唤醒式（贴合本项目已有 `concurrent.futures`）：

```python
def _race_sources(self, srcs, paper, raw, idx, result, overall_timeout):
    success_event = threading.Event()
    cancel_event  = threading.Event()
    lock = threading.Lock()
    winner = {"path": None, "src": None, "url": None, "bytes": 0}

    def worker(src):
        if cancel_event.is_set() or not src.applicable(paper):
            return
        try:
            cands = src.find_candidates(paper, self.ctx) or []
        except Exception as e:
            self.events.emit("source", raw=raw, source=src.name, ok=False, error=str(e)); return
        for c in sorted([c for c in cands if c.is_direct()],
                        key=lambda c: c.confidence, reverse=True):
            if cancel_event.is_set():
                return
            path, nbytes, derr = download_pdf(c, paper, self.pdf_dir, self.client,
                                              self.cfg, self.log, fallback_name=str(idx),
                                              events=self.events)
            if path:
                with lock:
                    if winner["path"] is None:
                        winner.update(path=path, src=c.source, url=c.url, bytes=nbytes)
                        cancel_event.set(); success_event.set()
                return

    with ThreadPoolExecutor(max_workers=min(len(srcs), self.cfg.race_max)) as pool:
        for s in srcs:
            pool.submit(worker, s)
        success_event.wait(timeout=overall_timeout)

    if winner["path"]:
        result.success = True
        result.pdf_path, result.source_used = winner["path"], winner["src"]
        result.pdf_url,  result.pdf_bytes  = winner["url"], winner["bytes"]
        return True
    return False
```

- `no_download` 模式**不并发下载**，仍可并发 `find_candidates` 只收集候选并按 (direct, confidence) 排序取 top（保持只定位语义）。
- 落地页兜底：档 1 失败后，对累计的 landing 候选按 confidence 竞速 `download_pdf`（与现逻辑一致，只是并发化）。

### 3.3 两级并发预算（防线程爆炸）——**改造中最需要注意的点**

Level 1 × Level 2 = `concurrency 输入 × race_max 源`。默认 `concurrency=4 × race_max=6 = 24` 线程/下载连接，尚可控；但要显式设上限，且与 per-host 限速协同：

- 新增 `race_max`（单条内竞速源数上限，默认 6–8）。
- **全局下载信号量** `download_semaphore = Semaphore(global_max_inflight)`（默认如 16），所有 `download_pdf` 入口 acquire，封顶总在途连接。
- **per-host 限速天然兼容竞速**：竞速的各源命中不同主机（unpaywall/openalex/arxiv/europepmc…各自域），`HttpClient.set_host_interval` 仍按域串行；同域源（少见）自动被限速排队，不会突发。
- 重源（`browser_search`、`scihub`）沿用 scansci 思路加**专用低配额信号量**（如浏览器源全局 1–2）。

### 3.4 自适应 EMA 源排序（P1，可选增强）

移植 `scoring.py`：`out/source_scores.json` 记录每源 success_ema/latency_ema；`build_sources` 后用 `sort_sources` 动态排。竞速模式下它决定「档 1 先派哪 race_max 个源」，把历史高命中低延迟的源优先放进竞速档，进一步降延迟、省请求。可与静态 `DEFAULT_SOURCE_ORDER` 融合（冷启动用静态，热数据接管）。

### 3.5 借鉴：可疑 PDF 检测（P1）

本项目 `download.py` 现只有 `min_pdf_bytes` 下限。补一个「页数/预览页」检测（`pypdf` 读页数，1 页且非明确单页论文 → 标记 `suspicious`，降级不算成功或二次确认），拦截出版商「封面页冒充全文」的假成功。

### 3.6 借鉴：批量机构 Phase 2 按出版商分组（P2，依赖机构订阅落地）

与 141/144 正在做的 `publisher_direct` / 机构订阅协同：把批量里 Phase 1 失败的 DOI 按出版商前缀分组，同一出版商**一次登录**（可见浏览器/Cookie 持久化）后批量取该组全部 DOI，显著降低登录次数。此项建议在机构订阅 Cookie 持久化层落地后再排期。

### 3.7 建议新增配置项（`config.py`）

| 新配置 | 默认 | 含义 |
|--------|------|------|
| `race: bool` | False（灰度）→ 稳定后 True | 单条内源竞速总开关 |
| `race_max: int` | 6 | 单条内同时竞速的源数上限 |
| `global_max_inflight: int` | 16 | 全局在途下载连接上限（信号量）|
| `race_phase1_timeout: float` | 20 | 档 1 竞速整体超时 |
| `race_phase2_timeout: float` | 30 | 兜底档竞速整体超时 |
| `adaptive_order: bool` | False | 启用 EMA 动态源排序 |
| `suspicious_pdf_check: bool` | True | 单页/预览页可疑 PDF 拦截 |

---

## 四、风险与权衡

| 风险 | 说明 | 缓解 |
|------|------|------|
| **请求量放大** | 单条从「首中即停」变「多源齐发」，总请求上升 | `race_max` 限档宽；EMA 排序把高命中源前置减少无谓请求；命中即 `cancel_event` 止损 |
| **礼貌/被封** | 免费 API 大多宽松且分属不同域，风险低；但 arXiv(≥3s)、Scholar 类敏感 | 敏感/重源不进竞速档或给独立低配额信号量；保留 per-host interval |
| **线程/连接爆炸** | Level1×Level2 叠乘 | 全局 `download_semaphore` + `race_max` 双封顶 |
| **协作式取消不彻底** | 已阻塞 IO 的源线程杀不掉 | 与现 straggler 看门狗一致：主线程不等它们即返回；`shutdown(wait=False)` |
| **临时文件竞争** | 多源同写 | 沿用 scansci 的 `{doi}_{label}` 分文件命名 + 胜者 rename + 其余清理 |
| **行为回退性** | 新并发路径引入回归风险 | `race` 默认关灰度；两条路径并存，selftest 双跑对拍 |

---

## 五、落地优先级、工作量与 ROI

| 优先级 | 改造项 | 工作量 | 预期收益 | 依赖 |
|--------|--------|--------|----------|------|
| **P0** | 单条内源竞速原语 + 分档（3.2/3.3）| 3–5h | 单条延迟↓、慢源占比高时整批吞吐显著↑ | 无 |
| **P1** | 全局并发预算与信号量（3.3）| 1–2h | 防爆炸、稳定性 | 随 P0 |
| **P1** | 可疑 PDF 检测（3.5）| 1h | 减少假成功、提升真实成功率口径 | pypdf |
| **P1** | 自适应 EMA 源排序（3.4）| 1–2h | 进一步降延迟省请求 | 随 P0 |
| **P2** | 批量机构 Phase2 分组（3.6）| 3–5h | 机构订阅登录次数↓ | 机构订阅 Cookie 持久化层 |

**ROI 判断**：P0+P1 是「低风险、纯加速、可灰度回退」的一组，建议优先排期；对 500 DOI 实测里「命中源靠后 / 慢源拖尾」的那部分收益最直接。P2 与机构订阅路线绑定，随其排期。

---

## 六、给总指挥（147）的采纳建议

1. **建议直接采纳（P0/P1）**：单条内源竞速 + 全局并发预算 + 可疑 PDF 检测 + EMA 排序。四项互相独立、默认可灰度、与现有健壮性设施（续跑/看门狗/礼貌限速/收尾落盘）不冲突。
2. **建议登记待评估（P2）**：批量机构 Phase2 分组，待 141/144 的 `publisher_direct` 与机构订阅 Cookie 持久化层落地后合并排期。
3. **可派一名组员实施 P0**：改造点集中在 `pipeline.py::_gather_and_download`（新增 `_race_sources`）与 `config.py`（新增开关），面小可控；建议实施者与我（142）对齐竞速原语接口后再动手。
4. **不建议引入**：scansci 的 Cython `_core.racing` 编译核（本项目 I/O 密集，收益低、增加构建复杂度）。

---

## 七、参考（源码文件与校验）

| 文件（scansci-pdf @ master） | 作用 |
|------|------|
| `src/scansci_pdf/sources/__init__.py` | `download` / `_run_tiers_parallel` / `_try_source` / `batch_download` / `_batch_institutional_phase` |
| `src/scansci_pdf/sources/scoring.py` | EMA 评分 `record_result` / `sort_sources` / `classify_error` |
| `src/scansci_pdf/sources/publishers.py` | `get_publisher_fast_sources` 出版商前缀路由 |
| `src/scansci_pdf/config.py` | 超时/延迟/并发/`max_browser_workers` 等默认 |
| `src/scansci_pdf/_core/racing.*` | 可选 Cython 竞速核（本项目非必需）|

本项目对照文件：`fulltext_fetcher/pipeline.py`（`_gather_and_download` / `run`）、`sources/base.py`（`find_candidates` 接口）、`config.py`（`DEFAULT_SOURCE_ORDER` / `concurrency`）。

> 本文档为智库检索成果，判断基于 2026-07-02 的 `Rimagination/scansci-pdf` master 分支源码与本项目当时代码。改造需结合项目实际负载与合规要求，建议以 `race` 默认关的灰度方式落地并用 selftest 双路对拍。
