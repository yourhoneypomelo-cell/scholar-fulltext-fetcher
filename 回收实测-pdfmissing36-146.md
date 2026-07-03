# 回收实测 · 36 条 metadata-success-but-pdf-missing(隔离真跑,免费路线)

> 交付:**谷歌学术人机认证-145**(持续巡检 AI · 收口冲刺)｜2026-07-04 00:20｜承用户 GO(隔离真跑、不回写)
> 边界:隔离 `RUNROOT=out/pdfmissing36_recover_145`,**未碰权威 `out/coverage.json`(368/631/36.84% @22:07:22 逐字未变)**、未改黑白名单/生产码、无 route-B/机构凭据。

---

## 〇、结论(一句话)

**免费路线对这 36 条「曾声称成功但盘上无 PDF」的桶净增 = 0/36。** 主因不是「漏抓的低垂果实」,而是 **83% 是 RSC(10.1039)CF/JA3 绑定站的 cloudflare-challenge(http-403)** —— 与全局结论一致:**这批只能靠 route-B 授权会话或 A5 机构订阅救,免费公开边界已到顶。** 我此前预估的「+1~3pp」过于乐观,已按实测修正为 **0pp(免费路线)**。

---

## 一、真跑结果(可复现)

| 项 | 值 |
|---|---|
| 命令 | `python run_all.py -f out/_pdfmissing36_recover_145.txt -o out/pdfmissing36_recover_145 --no-resume --email … -c 3` |
| 输入 / 去重 / 待跑 | 36 / 36 / 36 |
| **净成功 / miss** | **0 / 36**(0.0%) |
| 用时 | 1871.1s(~31 min;RSC CF 挑战每条 90–285s 退避) |
| `--verify` | **REPRODUCIBLE**(原报 0/36 == 复算 0/36,QC 快照完整) |
| 权威 coverage | **未变**(368/631 @22:07:22);git 工作树干净 |

## 二、失败分桶(全枚举)

| reason 桶 | 条数 | 含义 / 处置 |
|---|---:|---|
| **cf-403**(cloudflare-challenge) | **30** | RSC(10.1039)为主 + 1×10.1595;JA3 绑定 CF,免费回放到顶 → **route-B 同会话直下 或 A5** |
| download-fail | 4 | `d2cp01971j` landing-no-pdf、`d6cy00444j` http-202、`10.1109/lpt…` + `10.1146/annurev…` landing-no-embedded-pdf |
| no-source | 2 | `10.1166/jnn.2011.4752`、`10.2138/am.2011.3775`(无 OA 候选) |

## 三、根因与去向

- **这 36 条并非「免费能救但之前漏了」**:它们在历史批里 metadata 声称成功、但 PDF 未落盘,重跑后暴露真实终态 = **绝大多数是订阅墙内 CF 站**(RSC catalysis/dalton/GC/nanoscale 系列)。
- **正解**:整体并入 **A5 机构订阅通道**(`a5_smoke_input.txt` 同源口径)或 **route-B 授权会话页内直下**;免费路线不应再对该桶投工程(与《回收实测结论-CF与免费路线到顶.md》§三/§五、经验记录 M/N 一致)。
- **对 KPI 的意义**:36.84% 与免费天花板 40–42% 的差额,**不含这 36 条可被免费回收的成分**;该桶已确证归 A5/route-B。

## 四、产物留存(隔离,不入库)

`out/pdfmissing36_recover_145/`:`coverage.json`(36/0/36)、`still_missing.txt`(36)、`run_all_detail.tsv`、`run_all_summary.json`、`run_all.log`、`fetch/`(逐条 run.log + results.csv + attempts.jsonl)。清单 `out/_pdfmissing36_recover_145.txt`(-145 生成)。

---

*145｜隔离真跑复核:36 条 pdf-missing 免费路线净增 0/36(30 cf-403+4 dl-fail+2 no-src),`--verify` REPRODUCIBLE;权威 coverage 未动、无回写、无凭据。结论:该桶归 A5/route-B,免费路线到顶。*
