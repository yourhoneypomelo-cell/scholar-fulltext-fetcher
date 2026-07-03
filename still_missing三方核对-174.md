# still_missing 三方核对 · -174

**核对时间**：2026-07-03（定版 live 盘 `@12:50:24`，原 `@01:27:42` 已回填至 326 定版）

## 结论

| 核对项 | 结果 |
|--------|------|
| `still_missing.txt` 行数 | **673**（无重复 DOI） |
| `coverage.json` `summary.miss` | **673** |
| `coverage.json` records 非 success | **673** |
| **txt ↔ json 集合** | **完全一致** ✓ |
| `success + miss = total` | **326 + 673 = 999** ✓ |

→ **现盘三方一致**（326 定版 @12:50:24）；与 **656**（wave2）、**660**（v2 @01:27:42）等历史口径的差异来自换配方与重算，非 txt/json 不同步。

## 与 −155 口径对照

| 版本 | `generated_ts` | success | miss | allow_override | 说明 |
|------|----------------|---------|------|----------------|------|
| wave2 终稿（§6.6） | 01:03:41 | **343** | **656** | 14 | 长 extra-dirs + allow14 |
| v2（§6.8，已被 326 定版取代） | 01:27:42 | 339 | 660 | 10 | 缩短 extra-dirs + allow11 → 673 @12:50:24 |
| **326 定版（现 live）** | **12:50:24** | **326** | **673** | **10** | 重算/最终口径 |

**漂移**：wave2→v2 miss **+4**、success **−4**（343→339）；v2→定版 miss **+13**、success **−13**（339→326、660→673）。见 `纠偏重算配方-155.md` §6.8；backup `coverage.bak_pre_final_155_v2_allow11.json`。

## 默认 flat `--no-write` 对照（勿当权威）

`python tools/build_coverage.py --out-root out`（无 extra-dirs/allow）→ **325 / 674 / allow0** — 仅说明漏配方会偏，**非现盘口径**。

## 174 动作

- **未 `--write`**
- OpenAlex 探针输入曾读 **659** 行（scan 前）；现 txt **660**（v2 写盘后 +1 或计数差，以 header 为准）→ 定版 **673** @12:50:24
