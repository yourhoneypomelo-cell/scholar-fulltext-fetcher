# OpenAlex-key 净增探针 · still_missing 全量扫描

> 交付：监管者 -176｜工单 task-6bcfc22c（原指派 -155）｜2026-07-03  
> 边界：**只读探针，未改 `coverage.json` / 未跑批量回收**

---

## 〇、TL;DR

| 指标 | 值 | 说明 |
|---|---:|---|
| **OPENALEX_KEY** | ✅ 已设（User env，len=22） | 当前 shell 需 `GetEnvironmentVariable` 或 `setx` 后新开终端 |
| **still_missing 基数** | **660** | `out/still_missing.txt` @ 探针前 |
| **coverage 既有 openalex success** | **31** | 全库并集，非 miss 子集 |
| **X — API 返回 pdf_url** | **26 / 660 (3.9%)** | 带 key 全量单条查，0 API 错误 |
| **Y — 直 HTTP 下载 PDF 成功** | **1 / 26** | 未开 route-B / 浏览器兜底 |
| **Z — 内容 QC 通过（可计净增候选）** | **1 / 660 (0.15%)** | `10.35848/1347-4065/ad280f`（IOP） |

**结论**：OpenAlex key **主要价值是解除 $0.10/天 限速**（660 条一次扫完）；对 still_missing 的 **直链净增极低（≈1 条）**。26 条命中里多数为 Elsevier 缩略图 JPG、ScienceDirect/Wiley/RSC 403、或 landing 非 PDF——需 **route-B / 机构订阅** 才有二次转化空间，不属于 OpenAlex key 本身能解决的。

---

## 一、探针方法

- 脚本：`_openalex_key_probe_176.py`
- 输出：`out/_openalex_key_probe_176.json`（`generated_ts` 2026-07-03 01:44:59）
- API：`OpenAlex.find_candidates` + `api_key` 查询参（与 CLI 路径一致，见 runbook-148）
- 下载：轻量 HTTP GET（timeout 20s，无 retry），PDF 魔数校验 + `_content_qc_gate`
- **刻意未开** `route_b` / `download_pdf` 全链路——测的是「OpenAlex 直链 + key 解锁 API」上限，非 route-B 组合 ROI

---

## 二、26 条 API 命中分桶（下载层）

| 失败模式 | 条数 | 典型 |
|---|---:|---|
| http-403（CF/付费墙） | 14 | RSC `pubs.rsc.org`、Wiley、ScienceDirect、Hindawi |
| not-pdf（JPG/landing/HTML） | 9 | Elsevier `ars.els-cdn.com/...jpg`、repository landing |
| http-none / 熔断 | 2 | RSC 单条熔断、sciopen 无响应 |
| **QC 通过** | **1** | `10.35848/1347-4065/ad280f` IOP 2.4MB PDF |

---

## 三、与 run_all 缺口的关系（-148 已文档化）

- `python -m fulltext_fetcher -f still_missing.txt`：**env→Config 闭合，key 生效** ✅  
- `run_all.py` 批量：**仍不传 `openalex_key`** ❌ — 若要用 key 跑北极星一键，需在 `run_all.py` Config 构造处补 `openalex_key=os.environ.get("OPENALEX_KEY")`（**本波未改代码**）

---

## 四、建议（供 141 / 155 裁决）

1. **运营层**：保持 User 级 `OPENALEX_KEY`；批量 miss 扫描用 CLI `-f`，勿依赖 run_all 直到缺口修补。  
2. **ROI**：OpenAlex key 对 still_missing **不是净增主杠杆**（Z≈1）；RSC/Wiley/Elsevier 命中应走 **route-B 或 A5 机构** 二次下载，而非指望 OpenAlex 直链。  
3. **可选 follow-up**：对 26 条命中跑 `--route-b cf-only` 子集探针，估「key + route-B」组合 Y/Z（需另开工单，避免与本次「key 本身」混淆）。

---

## 五、附件

- 机器可读：`out/_openalex_key_probe_176.json`
- API 阶段快照：`out/_openalex_key_probe_176.json.partial`
