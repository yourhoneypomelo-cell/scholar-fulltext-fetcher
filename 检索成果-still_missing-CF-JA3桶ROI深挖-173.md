# 检索成果 · still_missing CF/JA3 桶 ROI 深挖

> 交付：**信息检索-专家智库 · 谷歌学术人机认证-173**｜2026-07-02  
> 触发：用户直派「不等回复，先深挖 still_missing CF/JA3 桶 ROI」→ 产出完成后向总指挥 144 同步。  
> 边界：**只新建本 1 份 md，不改任何 `.py`/他人文档**。数据取自仓内已提交 ROI/回收/分桶文档（-144/-149/-176/-179 等）与 `经验记录` H/J/K/M 节。  
> 说明：本机 `out/coverage.json` 未在仓内检出（可能未提交或需重跑 `tools/build_coverage.py`）；**分母与桶规模沿用黑名单感知权威口径 448/999 → still_missing ≈ 551~553**（-150/-149）。
>
> ⚠️ **净覆盖率口径统一（173 冻结）**：本文成文时 coverage 不在仓内、沿用**假设值 448/999、still_missing≈551~553**，均为**【历史口径·推算】**。现权威已落盘：**【历史快照】当前权威见 `out/coverage.json`：326 success / 673 miss / 999 = 32.63%**（generated_ts 2026-07-03 12:50:24, allow_override=10）。CF/JA3 桶的 ROI 相对排序仍有效，唯分母/桶规模以 611 为准。唯一权威 + 历史对照表见 **《基线口径冻结说明-388-173.md》**。

---

## 〇、TL;DR（给 144 的一页决策卡）

| 优先级 | 行动 | 预期净增 | 工作量 | 归属 | 结论 |
|:--:|---|:---:|:---:|---|---|
| **P0·质** | **内容 QC 闸门增强**（SI/poster/exaly/文内 DOI≠期望） | 防假阳、净覆盖口径更诚实 | 1~2d | 140/147 | 与 CF 回收并行，**必须先做**（FS/路线B 会忠实地下载错候选） |
| **P1·能力** | **路线B：浏览器内页内直下 PDF**（nodriver `fetch().arrayBuffer()`） | **+15~35 篇（+1.5~3.5pp）**，点估 +20 | 1~2 人日 | download/render_fetch 实现者 | **JA3 绑定型 CF（RSC/ScienceDirect OA）唯一免费正解**；走量有限 |
| **P1·走量** | **FlareSolverr nodriver-shim**（已就绪，`FLARESOLVERR_URL`） | ACS-authorchoice + AIP/Wiley/OUP/T&F 长尾 | 运维 ~30min 启服务 | 运维/145 | **可回放型 CF**（不绑 JA3）；ACS 已实测 4.41MB PDF |
| **P2·根本** | **机构订阅 A5**（SciTeX SSO / Cookie 持久化 C→141） | **~300+ 真订阅墙** | 3~5h+ 凭据 | 141/用户 | still_missing **主体**；免费路线物理到顶 |
| **❌ 不做** | browser_search / wayback 扩量 Elsevier | 0/10、0/12 已实锤 | — | — | Elsevier = IP/登录墙，非 CF |

**一句话**：still_missing ≈553 里 **~55% 是真订阅付费墙（~300）**，免费 CF 破盾只能吃 **~25~50 篇边际**；**路线B 的价值在「JA3 从 0 到 1 + 提质」，不在清空 still_missing**。

---

## 一、分母与 still_missing 桶拆解

**权威净覆盖**：448/999 ≈ **44.8%**（QC 后，`build_coverage` 黑名单感知口径）→ **still_missing ≈ 551~553**。

综合 val500 / batch4 / batch6 失败分桶（-144 ROI §4.1、-149 §五、batch4 分桶文档）：

| 子桶 | 规模（估计） | 墙类型 | 主导出版商/域 |
|---|---:|---|---|
| **真订阅付费墙 403** | **~300** | 付费墙（非 CF） | ACS 订阅、RSC 订阅、Elsevier 订阅；val500 仅 http-403 就 ACS80+RSC41=121 | 
| **Elsevier/ScienceDirect IP/登录墙** | **~40~80** | 数据中心 IP/登录（**非 CF**） | `10.1016`；RG 落地页 403、SD AM 403 |
| **JA3 绑定型 CF 后的 OA/免费正文** | **~5~15** | CF + cf_clearance 绑 JA3 | RSC `pubs.rsc.org`、ScienceDirect OA |
| **可回放型 CF 后的 OA** | **~10~25** | CF（cookie 不绑 JA3） | ACS-authorchoice、AIP、Wiley、OUP、T&F、RG、ChemRxiv |
| **viewer-only OA** | **~5~10** | 无直链，PDF.js/Atypon epdf | Atypon 系 epdf 壳 |

**batch4 量级参考**：`cloudflare-challenge(http-403)` 事件 **519 次**（RSC/ACS/Elsevier/Wiley 均高发）；与 still_missing 有重叠（同一 DOI 多源多次失败）。

---

## 二、失败原因 × 出版商交叉（实跑证据）

| 出版商/桶 | 失败模式 | 免费可救？ | 最佳杠杆 | 实测证据 |
|---|---|---|---|---|
| **ACS-authorchoice** | CF403，不绑 JA3 | ✅ | FS shim → curl_cffi 回放 | `10.1021/acscatal.0c01253` 4.41MB（-145 `out/recover_b4_cf/`） |
| **AIP/Wiley/OUP/T&F 长尾** | CF403 | ✅ | FS shim | batch6 长尾 9 条 = CF 桶（-143 K 节） |
| **RG / ChemRxiv** | CF403（逃生口亦封） | ⚠️ 需 FS | FS shim | K 节：免费兜底口也进 CF |
| **RSC** | CF + **JA3 绑定** | ❌ 回放链无效 | **路线B 页内直下** | FS 已拿 cf_clearance，curl_cffi 仍 403（-179/-145）；batch6 净 MISS≈0 |
| **Elsevier 10.1016** | IP/登录 403 | ❌ | 机构订阅 | browser_search 0/10、wayback 0/12（-143/-149） |
| **ACS/RSC 纯订阅** | http-403 真墙 | ❌ | 机构订阅 | 121/149 条 http-403 为真付费墙（81%） |

---

## 三、回收路线 ROI 排序（诚实标注重叠）

### 1. 路线B · 浏览器内页内直下 PDF（**P1·能力型**）

- **机理**：同一 nodriver 真 Chrome 会话内 `fetch(pdfUrl).arrayBuffer()`，**不回放 cookie 到 curl_cffi** → 破 JA3 死结。
- **预期**：高置信 **~15 篇**；含可回放型 CF-OA 扣重叠后点估 **+20 篇（+2pp）**；区间 +10~+35。
- **成本**：~1~2 人日（`_nodriver_fetch_pdf_bytes` 加方法 B 支路）；依赖已装 nodriver 0.50.3。
- **质红利**：从权威 DOI 落地页直下 → **绕开 websearch 68.5% 错论文假阳**（-150 L 节）。
- **依据**：`ROI-路线B-render_fetch.md`（-144 全量定量）；`选型2026-强CF浏览器内直下PDF实现者骨架-renderfetch-CDP.md`（-177 骨架）。

### 2. FlareSolverr nodriver-shim（**P1·走量型·ACS/长尾**）

- **机理**：解 CF JS 质询 → `cf_clearance` + UA → **curl_cffi 同栈回放**（仅对不绑 JA3 的站有效）。
- **预期**：ACS-authorchoice 桶 + AIP/Wiley/OUP/T&F 长尾；batch4 CF 桶主体中**可回放部分**。
- **成本**：`python tools/flaresolverr_nodriver.py --port 8191` + `FLARESOLVERR_URL`；零 Docker。
- **⚠️ 必须与内容 QC 联用**：FS 会忠实地下载 websearch 错候选（如 `cssc.201601217` → jaad.org 皮肤病学 PDF，-149 §一）。
- **依据**：`回收实测结论-CF与免费路线到顶.md`（-149）；`选型2026-FlareSolverr免Docker-仓内nodriver-shim实测与落地-179.md`。

### 3. 机构订阅 A5（**P2·根本型·~300 篇**）

- **覆盖**：真订阅 403、Elsevier IP/登录墙——**still_missing 主体**。
- **仓内准备**：142→141 Cookie 持久化骨架（C 文档）；SciTeX SSO 参考（智库 -177 登记）。
- **依据**：`ROI-路线A-机构订阅代理.md`；`选型2026-A5机构订阅SSO浏览器接入实现者骨架-SciTeX参考.md`。

### 4. 明确不值得投（**❌**）

| 路线 | 实测 | 原因 |
|---|---|---|
| **browser_search** | Elsevier 0/10 | 只搜结果页、不渲染落地页；Bing DOI 召回低 |
| **wayback** | Elsevier 0/12 | 纯 DOI→doi.org 无 PDF 快照 |
| **byparr / 经典 FlareSolverr 扩到 RSC** | RSC 回放仍 403 | 回放范式，救不了 JA3 |
| **Scrapling** | — | 同 Camoufox 内核，不解 JA3-PDF（-177 一页摘要 B 节） |
| **为 RSC 单独上 CF 破盾走量** | batch6 净 MISS≈0 | websearch 已从别处兜底，边际≈0 |

---

## 四、CF 回收实测净收益校准（防乐观）

`out/recover_b4_cf/` full-80 回收（-142 M 节复核）：

- summary 报 success 27（37%）；**内容 QC 三层甄别后真全文仅 3+2=5 条** → **真净增益 ≈ 4%**。
- **flaresolverr_recovered 真救回 = 0**（27 条 success 无一来自 FS 直破 CF；多为绿 OA + websearch 碰运气）。
- **启示**：CF 桶「跑批 success 率」≠「真全文净增」；回收管线必须叠加 **SI/poster/citation-report/文内 DOI** 判识（M 节四类假阳）。

---

## 五、给总指挥 144 的排期建议

1. **并行不冲突**：QC 闸门增强（140）与 路线B 点亮（download 组）可并行；FS 启服务（运维）随时可开。
2. **推荐顺序**：
   - ① 确认 `OPENALEX_KEY` 已配（P0 止损，5 分钟，与 CF 桶无关但全局收益）
   - ② 路线B 页内 fetch 支路 + RSC/SD/viewer 抽样实测（1~2 人日）
   - ③ 启 FS shim 回收 ACS-authorchoice + 长尾 CF 桶（需 `--use-flaresolverr` 或 env）
   - ④ 141 Cookie 层 + 用户机构凭据 → 破 ~300 订阅墙
3. **不要期望**：路线B + FS 合计清空 still_missing；**诚实天花板 ≈ 46~48% 净覆盖**（+2~3pp），余下靠 A5。

---

## 六、证据索引

| 文档 | 贡献 |
|---|---|
| `ROI-路线B-render_fetch.md`（-144） | 桶拆解、+15~35 增量、JA3 三法、引擎表 |
| `回收实测结论-CF与免费路线到顶.md`（-149） | ACS 可救/RSC 难越/Elsevier 到顶/FS runbook |
| `选型2026-强CF浏览器内直下PDF实现者骨架-renderfetch-CDP.md`（-177） | 实现骨架 |
| `选型2026-RSC-Cloudflare挑战绕行方案.md`（-176） | RSC JA3 死结 |
| `经验记录-踩坑与发现.md` H.3/J/K/L/M | CF 主矛盾、探针 0/10、长尾 CF 桶、假阳、recover_b4_cf 净增益 |
| `检索成果-batch4-失败分桶与可回收分析.md` | CF 519 次、A 类桶 |
| `给总指挥-智库本轮成果一页决策摘要-2026-07-02.md`（-177） | P0 OpenAlex / P1 路线B / Scrapling 淘汰 |

---

*核验 2026-07-02｜信息检索-专家智库 · -173｜已同步总指挥 144*
