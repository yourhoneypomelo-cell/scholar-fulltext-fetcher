# 选型2026 · N1 实现者可照抄骨架 — pipeline 单条内「源竞速」

> 智库交付（信息检索-智库专家 **-177**）｜2026-07-02｜配套《选型2026-scansci竞速引擎源码架构与并行化改造》(142)。
> **性质**：给实现者的**参考骨架/设计**，非生产改动——本文不改 `.py`；由 -156 排定的实现者据此整合进 `pipeline.py` 并跑 selftest。借鉴 scansci-pdf 的 Event 唤醒式竞速原语（Apache-2.0，仅借鉴手法、不引库）。
> **恪守既有不变量**：① per-host 礼貌限速（共享 `HttpClient`，竞速各源多命中不同域，天然兼容）；② `no_download`/`oa_only` 语义不变；③ `%PDF` 校验（`download_pdf` 不动）；④ straggler 看门狗/收尾必落盘（在 `run()` 层，不受影响）；⑤ 默认 `race=False` 灰度、与现顺序路径并存可回退。

---

## 0. 改动总览
| 项 | 改动点 | 新增 |
|---|---|---|
| 竞速原语 | 新增 `_race_tier()`（Event 唤醒、首中即 `cancel_event` 止损） | `import threading` 已在 |
| 编排 | 新增 `_race_and_download()`；`_gather_and_download()` 按 `cfg.race` 分派 | — |
| 并发预算 | 全局在途下载信号量，防 `concurrency × race_max` 线程/连接爆炸 | `self._dl_sem` |
| 配置 | `config.py` 新增 5 项 | 见 §1 |

## 1. 新增配置（`config.py`，默认与现网等价/安全）
```python
race: bool = False                 # 单条内源竞速总开关（默认关，灰度稳定后可 True）
race_max: int = 6                  # 单条内同时竞速的源数上限
global_max_inflight: int = 16      # 全局在途下载连接上限（信号量封顶）
race_phase1_timeout: float = 20.0  # 档1（直链源）竞速整体超时
race_phase2_timeout: float = 30.0  # 档2（落地页+重源）竞速整体超时
```

## 2. 竞速原语 `_race_tier()`（`pipeline.py`，Pipeline 方法）
```python
from concurrent.futures import ThreadPoolExecutor

# 档2「重/兜底」源（仅在档1全灭后竞速；也可用源自带属性判定）
_RACE_HEAVY = {"websearch", "wayback", "scihub", "browser_search"}

def _race_tier(self, srcs, paper, raw, idx, result, *, timeout, do_download, landing_sink):
    """并发跑 srcs 的 find_candidates；do_download=True 时对 direct 候选并发下载，
    首个成功即 cancel 其余并唤醒。landing 候选统一汇入 landing_sink（供档2）。
    返回 True=已下到 PDF（result 已填），False=本档未命中。线程安全。"""
    if not srcs:
        return False
    success_event = threading.Event()
    cancel_event = threading.Event()
    lock = threading.Lock()          # 保护 result 字段 / attempts / tried_urls / landing_sink
    tried: set = set()

    def worker(src):
        if cancel_event.is_set():
            return
        t = time.time()
        err = None
        try:
            cands = src.find_candidates(paper, self.ctx) or []
        except Exception as e:  # noqa: BLE001
            cands, err = [], str(e)
        dt = int((time.time() - t) * 1000)
        with lock:
            result.attempts.append(Attempt(src.name, bool(cands), len(cands), dt, err))
            result.candidates += len(cands)
        self.events.emit("source", raw=raw, doi=paper.doi, source=src.name,
                         ok=bool(cands), n=len(cands), ms=dt, error=err)
        direct = sorted([c for c in cands if c.is_direct()],
                        key=lambda c: c.confidence, reverse=True)
        with lock:
            landing_sink.extend([c for c in cands if not c.is_direct()])
        if not do_download:
            return
        for c in direct:
            if cancel_event.is_set():
                return
            with lock:
                if c.url in tried:
                    continue
                tried.add(c.url)
            with self._dl_sem:               # 全局在途下载封顶
                if cancel_event.is_set():
                    return
                path, nbytes, derr = download_pdf(c, paper, self.pdf_dir, self.client,
                                                  self.cfg, self.log, fallback_name=str(idx),
                                                  events=self.events)
            self.events.emit("download", raw=raw, doi=paper.doi, source=c.source,
                             url=c.url, kind=c.kind, ok=bool(path), bytes=nbytes, error=derr)
            if path:
                with lock:
                    if not result.success:   # 首个胜者落地
                        result.success = True
                        result.pdf_path, result.pdf_bytes = path, nbytes
                        result.source_used, result.pdf_url = c.source, c.url
                        cancel_event.set(); success_event.set()
                return

    with ThreadPoolExecutor(max_workers=min(len(srcs), int(self.cfg.race_max))) as pool:
        for s in srcs:
            pool.submit(worker, s)
        success_event.wait(timeout=timeout)   # 命中即返回；否则等到本档超时
    # 协作式取消：已阻塞 IO 的 worker 杀不掉，但主线程不等它们（与 straggler 看门狗同理）
    return result.success
```

## 3. 编排 `_race_and_download()`（替 `_gather_and_download` 的竞速路径）
```python
def _race_and_download(self, paper, raw, idx, result):
    applicable = [s for s in self.sources if s.applicable(paper)]
    fast = [s for s in applicable if s.name not in _RACE_HEAVY]
    heavy = [s for s in applicable if s.name in _RACE_HEAVY]
    landing: list = []

    # 档1：直链源竞速下载
    if self._race_tier(fast, paper, raw, idx, result, timeout=self.cfg.race_phase1_timeout,
                       do_download=not self.cfg.no_download, landing_sink=landing):
        return

    # no_download：只定位——并发收集完档1候选后取全局最佳（保持只定位语义）
    if self.cfg.no_download:
        # 档1 已 emit source / 收集 landing；再并发跑 heavy 的 find_candidates 收集候选
        self._race_tier(heavy, paper, raw, idx, result, timeout=self.cfg.race_phase2_timeout,
                        do_download=False, landing_sink=landing)
        ranked = sorted(landing + [], key=lambda c: (c.is_direct(), c.confidence), reverse=True)
        # 注：direct 候选在档1 do_download=False 时也应收集；实现时把 direct 也并入一个 all_cands sink
        result.success = bool(ranked)
        if ranked:
            result.pdf_url, result.source_used = ranked[0].url, ranked[0].source
        elif not result.error:
            result.error = "no-candidates-located"
        self.events.emit("located", raw=raw, doi=paper.doi, candidates=result.candidates,
                         top=(ranked[0].url if ranked else None))
        return

    # 档2：落地页候选 + 重源竞速兜底（oa_only 时跳过）
    if not self.cfg.oa_only:
        # 把已收集的 landing 候选包装成一个「伪源」与 heavy 源一起竞速下载
        if self._race_landing_and_heavy(heavy, landing, paper, raw, idx, result):
            return
    if not result.success and not result.error:
        result.error = "no-candidates" if result.candidates == 0 else "no-downloadable-pdf"
```
> `_race_landing_and_heavy` 可复用 `_race_tier` 思路：对 `sorted(landing, confidence desc)` 的候选并发 `download_pdf` + 同时跑 heavy 源；首中即止。为省篇幅此处略，接口同 §2。
> **只定位模式**建议在 `_race_tier` 里加一个 `all_sink` 收集 **全部** 候选（direct+landing），使 `no_download` 分支能取全局最佳，与现 `_gather_and_download` 的 `ranked` 语义一致。

## 4. 分派 + 全局信号量（`__init__` 与 `_gather_and_download`）
```python
# __init__ 内新增：
self._dl_sem = threading.Semaphore(int(getattr(self.cfg, "global_max_inflight", 16)))

# _gather_and_download 开头分派：
def _gather_and_download(self, paper, raw, idx, result):
    if getattr(self.cfg, "race", False):
        return self._race_and_download(paper, raw, idx, result)
    # …（原顺序回退实现保持不变，作为默认/可回退路径）…
```

## 5. selftest 草案（沿用 pipeline.py `__main__` 注入法，不联网）
```
RACE_WINNER_OK   : 注入 3 个 fake 源(慢直链/快直链/落地页)，断言胜者=快直链、
                   其余被 cancel（快直链 download 后 cancel_event 置位、慢源 worker 提前返回）
RACE_BUDGET_OK   : race_max=2 + global_max_inflight=1 → 断言同时在途下载 ≤1（信号量封顶）
RACE_NODL_OK     : no_download=True → 不发起下载、只 emit located、取全局最佳候选
RACE_FALLBACK_OK : 档1 全 miss → 档2 落地页候选竞速命中；oa_only=True 时跳过档2
RACE_EQUIV_OK    : 同一组 mock 源，race=False 与 race=True 最终 success/source_used 对拍一致
```
> 断言点：用 `threading.Event`/计数器验证「峰值并发下载 ≤ global_max_inflight」「命中即止其余源」；`RACE_EQUIV_OK` 双路对拍保证行为可回退。

## 6. 风险与缓解（承 scansci 文档 §四）
| 风险 | 缓解 |
|---|---|
| 请求量放大（多源齐发） | `race_max` 限档宽；命中即 `cancel_event` 止损；后续可接 EMA 排序把高命中源前置 |
| 线程/连接爆炸（concurrency×race_max） | `global_max_inflight` 全局信号量 + `race_max` 双封顶 |
| 礼貌/被封 | 竞速各源多命中不同域，per-host 限速仍逐域串行；arXiv(≥3s)/scihub 等敏感源归档2或独立低配额 |
| 协作式取消不彻底 | 已阻塞 IO 的 worker 杀不掉 → 主线程不等它们即返回（同 straggler 看门狗） |
| 行为回退性 | `race` 默认关；两路径并存；`RACE_EQUIV_OK` 双跑对拍 |

## 7. 落地检查清单（给实现者）
- [ ] `config.py` 加 5 项（§1）；`race` 默认 False 灰度。
- [ ] `__init__` 加 `self._dl_sem`。
- [ ] 加 `_race_tier` / `_race_and_download`（+ `_race_landing_and_heavy`）；`_race_tier` 里加 `all_sink` 支持 `no_download` 取全局最佳。
- [ ] `_gather_and_download` 开头按 `cfg.race` 分派，原实现保留为默认路径。
- [ ] 扩 selftest 5 断言（尤其 `RACE_EQUIV_OK` 对拍）；`python -m fulltext_fetcher.pipeline` 打印 `PIPELINE_OK`。
- [ ] 回收执行期**勿动**（-156 定：避免 mid-recovery 破稳定）；排回收后波次。
- [ ] （可选 P1）接 scansci 的 EMA 源排序 + 可疑单页 PDF 检测（见 142 文 §3.4/§3.5）。

---
*核验 2026-07-02｜信息检索-智库专家 -177｜实现者参考骨架，非生产改动。借鉴 scansci Event 唤醒竞速（仅手法不引库）；恪守 per-host 限速/`%PDF` 校验/straggler 看门狗/默认可回退。*
