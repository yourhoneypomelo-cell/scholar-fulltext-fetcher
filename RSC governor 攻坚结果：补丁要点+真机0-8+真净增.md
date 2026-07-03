# RSC governor 攻坚结果（-160）

**会话**：谷歌学术人机认证-160  
**任务**：task-fddc6f8f — 落地 -165 governor 补丁 + 8 条 RSC 金 OA 真机复跑  
**日期**：2026-07-02

---

## 1. 补丁要点（`fulltext_fetcher/render_fetch.py`）

| 优先级 | 内容 | 状态 |
|--------|------|------|
| P1 | `_GOVERNOR_SIGNALS` + `_looks_governor()` → 返回 `blocked:rsc-governor` / `blocked:rsc-governor-softblock` | ✅ |
| P2 | articlepdf 直链前先 `articlelanding` 预热（`_rsc_articlepdf_to_landing`） | ✅ |
| P3 | 同 host 30–90s 随机间隔 + governor 命中后 300s 冷却（`_host_capture_gate` / `_host_register_governor`） | ✅ |
| P4 | 移除 nodriver `--disable-blink-features=AutomationControlled` | ✅ |
| P5 | governor 页尝试点击 “Take me to my Content” 再续跑 | ✅ |

**发射脚本**：`_routeb_rsc_launch_156.py` 的 `min_interval` 从 `0.0` 改为 `45.0`。

**自检**：`python run_all.py --selftest` → `RUN_ALL_OK`（含 governor 信号与 landing 转换断言）。

---

## 2. 真机 8/8 结果

**输入**：`routeB_rsc_goldoa.txt`（8 DOI）  
**输出**：`out/routeB_rsc_launch/` + 日志 `out/routeB_rsc_launch_160.log`  
**模式**：有头 nodriver、单头串行（`out/.route_b.lock`）、timeout=120s

| DOI | 耗时 | 结果 | 真净增 |
|-----|------|------|--------|
| 10.1039/c4ra00825a | 4.1s | `blocked:rsc-governor` | ✗ |
| 10.1039/c4ra02037e | 56.9s | `blocked:rsc-governor` | ✗ |
| 10.1039/c4ra14572k | 154.7s | `no-pdf-captured` | ✗ |
| 10.1039/c5ra04969e | 16.7s | `blocked:rsc-governor` | ✗ |
| 10.1039/d0gc02302g | 30.2s | `blocked:rsc-governor` | ✗ |
| 10.1039/d2gc02623f | 56.8s | `blocked:rsc-governor` | ✗ |
| 10.1039/d3ee02589f | 44.0s | `blocked:rsc-governor` | ✗ |
| 10.1039/d5fd00172b | 43.9s | `blocked:rsc-governor` | ✗ |

**汇总**：pdf_ok=**0/8**，真净增（%PDF + QC=match）=**0/8**。

---

## 3. 结论

1. **补丁已落地且可观测**：7/8 明确命中 `blocked:rsc-governor`（较 -156 的 `no-pdf-captured` / `blocked:challenge-page` 混桶，归因更清晰）；1 条跑满 timeout 仍为 `no-pdf-captured`（可能已过 CF 但未抓到 PDF，或 governor 信号未全覆盖）。
2. **本机当前会话/IP 仍被 RSC governor 压制**：即使 landing 预热 + 45s 间隔 + 去掉 AutomationControlled，仍无法在 8 条金 OA 上突破第二道门。
3. **与 -160 诊断一致**：RSC route-B 金 OA 天花板 ~8 条，但依赖 **未 burned 的 IP/会话 + 更保守节流**；本波 honest 净增 **0**，不宜写 coverage。
4. **下一跳（若继续攻坚）**：
   - 换干净 IP / 隔 ≥24h 再单条探针（非 8 条连打）；
   - 首条用 `articlelanding` 作 `article_url`（不经 doi.org 跳转链）试跑；
   - RSC subscription ~59 条仍唯 A5，不指望 route-B 免费线。

---

## 4. 关联交付（本会话已完成）

| 任务 | 交付物 |
|------|--------|
| P3 长尾 OA | SciOpen +1（`out/p3_longtail_160/`），handoff `-155` allow_override |
| 经验记录审计 | `经验记录完整性审计-141波.md` |
| RSC 0/8 诊断 | `route-B RSC 0-8 归零因与收口结论-160.md` |
| 依赖环境核对 | `依赖环境就绪核对-141.md` |
