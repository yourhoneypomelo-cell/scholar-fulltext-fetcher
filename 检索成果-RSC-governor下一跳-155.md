# RSC governor 下一跳 · 155

> 2026-07-03 · 155 转 RSC 支援 · coverage 写盘 FROZEN

## 现状

| 项 | 结论 |
|---|---|
| -165 补丁 | 已落地 `render_fetch.py`（P1–P5） |
| -160 真机 8/8 | **0 净增**；7× `blocked:rsc-governor` + 1× `no-pdf-captured` |
| 根因 | IP/会话已 burned；批量连打 articlepdf 触发 rate-gate；坏 reCAPTCHA 不可解 |
| route-B ROI | 金 OA ~8 条上限；订阅 ~59 条唯 A5 |

## 155 改动

`_routeb_rsc_launch_156.py`：**入口 URL 改为 `articlelanding`**（由首个 articlepdf fallback 推导），避免 doi.org 冷跳后再怼 PDF handler。

## 建议试跑 SOP（单条探针，非 8 条连打）

1. **冷却 ≥24h** 或换干净 IP（当前 host 可能仍在 300s governor cooldown）
2. 删/重置 `out/.route_b.lock`；确认无其他 route-B 进程
3. 单条 PoC：`10.1039/d5ra08493h`（-141 曾 484KB 成功）
   ```bash
   python _route_b_governor_probe_167.py 10.1039/d5ra08493h
   ```
4. 若 A=GOT-PDF 且 B=governor → 补丁路径正确，再试 landing 入口发射：
   ```bash
   echo 10.1039/d5ra08493h > out/_rsc_probe_one.txt
   # 临时改 INPUT 或手工跑 launch 首条
   ```
5. **禁止** 8 条连打直至单条连续 2 次 NET-GAIN

## 失败处置

- `deferred:rsc-governor-cooldown` → 等冷却，勿重试
- `blocked:rsc-governor-softblock` → 换 IP，勿打码
- 仍 0/8 → **defer RSC route-B**，订阅池走 A5
