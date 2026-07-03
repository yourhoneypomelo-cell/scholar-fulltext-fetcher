# 数据卫生核对 · route-B 发射前 A集/B集 ready-to-fire 输入分片健康性复检（-142）

> 交付：**谷歌学术人机认证-142（worker）** → 总指挥 **144**｜2026-07-02｜工单 **task-17dfafb9**（[P2·只读] 发射前 ready-to-fire 输入分片健康性复检）。
> 边界：**纯只读**核对 + **仅新建**本 1 份 md + 1 个可复跑核验脚本 `_routeb_shard_healthcheck_142.py`；**未改任何库 `.py`/产物/coverage/分片**，**未联网**。
> 真值源：`out/coverage.json`（`generated_ts` **2026-07-02 18:25:56**，success 379 / miss 620 / total 999）+ `out/still_missing.txt`（620）。
>
> ⚠️ **净覆盖率口径统一（173 冻结）**：本文核对基于 **success 379 / miss 620**（@18:25:56 快照），现为**【历史口径】**——分片健康性核对方法与结论仍有效，仅数字已推进。**【历史快照】当前权威见 `out/coverage.json`：326 success / 673 miss / 999 = 32.63%**（generated_ts 2026-07-03 12:50:24, allow_override=10）。唯一权威见 **《基线口径冻结说明-388-173.md》**。
> 口径对齐：读取口径 = `fulltext_fetcher/cli.py::_read_text_lines`（逐行 strip、跳空行与**整行** `#` 注释）——与真实 `-f` 发射逐字一致；DOI 规范化 = `tools/build_coverage.py::norm_doi`（小写、剥 `doi.org/`·`doi:` 前缀）；裸 DOI 形态 = `^10\.\d{4,9}/\S+$`。

---

## 〇、TL;DR（一句话结论）

**当前 route-B 实际发射波 15 条（`routeB_mdpi.txt` 7 + `routeB_rsc_goldoa.txt` 8）100% 干净、可直接 `-f` 发射**：全去重、全裸 DOI、全在 still_missing、**0 已covered混入、0 语料外、0 脏行**。「不发」的 `routeB_rsc_subscription.txt`（59）与 A 集全集 `out/routeB_A_ready.txt`（74）同样零脏数据。

**仅两处需知会（均非当前发射波的阻断项）**：
1. **`out/routeB_B_ready.txt`（B 集 124）含 4 条已 covered 混入**——正是 -151 回写从 still_missing 剔除的 4 篇 ACS 真正文（现已 success）。B 集 -144 已定论走 **FS-shim 非 route-B**，仅作参考；**若日后发 B 段，须先剔这 4 条**（否则重复下载已成功项，batch7 式浪费）。
2. **`out/routeB_candidates.txt`（198）是候选池/中间产物，含 198 行【行内 `#` 注释】，不可直接 `-f`**（fetcher 只跳整行注释、不剥行内注释 → 会把 `10.1039/…  # rsc | …` 整串当输入 → 非裸 DOI → 落 websearch 假阳）。A_ready/B_ready 已是其**剥离注释后**的纯 DOI 拆分产物，发射用它们即可。此为设计如此、非缺陷（文件自身第 7 行已警告）。

---

## 一、真值源自洽（PASS）

| 校验项 | 值 | 结论 |
|---|---:|:--:|
| coverage.json success + miss = total | 379 + 620 = 999 | ✅ |
| still_missing.txt 唯一 DOI | 620 | ✅ |
| still_missing.txt == coverage.miss（集合相等） | 620 = 620 | ✅ |

> 与 `数据卫生核对-still_missing620与coverage三方一致性核验-148.md` 完全一致，复检以此为基准。

## 二、逐分片健康性复检（机器口径实测）

| 分片 | 角色 | 数据行 | 去重唯一 | 片内重复 | 在 still_missing | **已covered混入** | 语料外 | 行内注释 | 非裸DOI | 健康 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|
| `routeB_mdpi.txt` | 仓根·**发**·MDPI真OA | 7 | 7 | 0 | 7 | **0** | 0 | 0 | 0 | ✅ |
| `routeB_rsc_goldoa.txt` | 仓根·**发**·RSC真OA | 8 | 8 | 0 | 8 | **0** | 0 | 0 | 0 | ✅ |
| `routeB_rsc_subscription.txt` | 仓根·不发·RSC订阅(留A5) | 59 | 59 | 0 | 59 | **0** | 0 | 0 | 0 | ✅ |
| `out/routeB_A_ready.txt` | A集全集 rsc67+mdpi7 | 74 | 74 | 0 | 74 | **0** | 0 | 0 | 0 | ✅ |
| `out/routeB_B_ready.txt` | B集 acs95+wiley22+aip3+T&F3+OUP1 | 124 | 124 | 0 | 120 | **4** ⚠ | 0 | 0 | 0 | ⚠ |
| `out/routeB_candidates.txt` | 候选池/中间产物 | 198 | 198 | 0 | 194 | **4** ⚠ | 0 | 198 ⚠ | 0 | ⚠ |

**读法**：`数据行` = fetcher `-f` 实际会读入的条数（已跳注释/空行）；`去重唯一` = 规范化 DOI 去重后数；`在 still_missing` = 仍属缺集、值得抓的条数；`已covered混入` = 已是 success 却仍在清单里的过期项（发射会重复劳动）；`语料外` = 不在 999 权威语料内的野 DOI。

## 三、关键发现明细

### 3.1 `routeB_B_ready.txt` 的 4 条已 covered（过期项）

| DOI | 社别 | 现状 | 归因 |
|---|---|---|---|
| `10.1021/acs.energyfuels.5c06101` | ACS | success（已covered） | -151 增量回写A：内容 QC 纠黑名单误杀的 4 篇 ACS 真正文之一 |
| `10.1021/acs.langmuir.7b03998` | ACS | success（已covered） | 同上 |
| `10.1021/acscatal.0c04429` | ACS | success（已covered） | 同上 |
| `10.1021/ja509214d` | ACS | success（已covered） | 同上 |

> 这 4 条与 `数据卫生核对-…-148.md §四` 中「分片 628→当前 620 剔除的 8 条」里的 **4 条 ACS** 逐条吻合。根因：`routeB_B_ready.txt` 由 -150 拆自 **628 旧快照** candidates，未随 -151 回写后的 620 刷新。**B 集当前不走 route-B（-144 定论走 FS-shim），故非阻断**；但发前应清洗。

### 3.2 `routeB_candidates.txt` 行内注释（设计如此，勿直接 -f）

样本：`10.1039/a905548g  # rsc | JA3-bound-CF | route-B`。全部 198 行首 token 均为合法裸 DOI，但行尾带 `#` 标注。`_read_text_lines` 仅跳**整行** `#`，不剥行内注释 → 直接 `-f` 会把整行（含空格）当一条输入 → 不匹配裸 DOI → 走标题 websearch（68.5% 假阳源）。**候选池只作分桶来源**；发射一律用 `routeB_A_ready.txt`/`routeB_B_ready.txt` 或仓根三片（均为纯 DOI 行）。

### 3.3 格式细节（全通过）

- 所有分片首 token 均为裸 DOI，含老式 Wiley DOI `10.1002/1099-0739(200012)14:12`、`10.1002/1521-4095(200110)13:20`（含括号/冒号但合法，正则通过、与 still_missing 逐字对齐）。
- 无 BOM 污染、无空行残留、无多 token 非注释脏行（除 candidates 的行内注释）。

## 四、跨分片关系核对（全部自洽 PASS）

| 关系 | 结果 | 结论 |
|---|---|:--:|
| 仓根三片两两交集（mdpi∩gold / mdpi∩subs / gold∩subs） | 0 / 0 / 0 | ✅ 无跨片重复 |
| `routeB_A_ready.txt`(74) == 仓根三片并集(74) | 相等 | ✅ A 集 = 发7+发8+不发59 的三分 |
| A_ready ∩ B_ready | 0 | ✅ A/B 集不相交 |
| candidates(198) ⊇ A_ready ∪ B_ready(198) | 成立 | ✅ A/B 是候选池的纯DOI拆分 |
| **实际发射波 = mdpi ∪ goldoa = 15**（期望 15） | 15，全在 still_missing，0 covered，0 语料外 | ✅ **可直接发射** |

## 五、一键重跑命令

```powershell
# ① 复跑本复检（只读，产 stdout；加 --json 出机器可读）
python _routeb_shard_healthcheck_142.py
python _routeb_shard_healthcheck_142.py --json

# ② route-B 发射波（15 条，cf-only + 单头串行，承 -150 §三；发射前须装 pypdf、开内容QC硬拒）
python -m fulltext_fetcher -f routeB_mdpi.txt        -o out\routeB_A_mdpi --email you@org.edu --route-b cf-only -c 1
python -m fulltext_fetcher -f routeB_rsc_goldoa.txt  -o out\routeB_A_rsc  --email you@org.edu --route-b cf-only -c 1
#   routeB_rsc_subscription.txt(59) 不发：route-B 对订阅墙返 no-pdf 是正确行为，留 route-A(A5)。

# ③ 若日后要发 B 段：先按最新成功集剔除已 covered(含上文 4 条 ACS)，再发清洗后清单
python tools/dedup_recover_input.py out\routeB_B_ready.txt --scan out -o out\routeB_B_ready_clean.txt
#   (dedup 口径=metadata.success；权威口径以 coverage.json success 为准，本复检已核出应剔 4 条)
```

## 六、验收结论

**验收标准「分片可直接作发射输入、无脏数据」——当前 route-B 发射波达标 ✅。**

- **可直接 `-f` 发射（零脏数据）**：`routeB_mdpi.txt`(7)、`routeB_rsc_goldoa.txt`(8)、`routeB_rsc_subscription.txt`(59，语义为「不发」)、`out/routeB_A_ready.txt`(74)。
- **发前需清洗 ⚠**：`out/routeB_B_ready.txt`(124) 有 4 条已 covered（非当前发射波；给出 ③ 清洗命令）。
- **勿直接 `-f` ⚠**：`out/routeB_candidates.txt`(198) 为中间产物、含行内注释（设计如此，用 A_ready/B_ready 代替）。

---
*核验 2026-07-02｜-142 worker｜工单 task-17dfafb9（总指挥144 派工）｜权威源 `out/coverage.json` 18:25:56 + `out/still_missing.txt` 620｜方法：`_routeb_shard_healthcheck_142.py` 只读机器核对（读取口径对齐 cli._read_text_lines、规范化对齐 build_coverage.norm_doi，可复跑）｜结论：发射波 15 条零脏数据可直发；B_ready 4 条已covered待清洗、candidates 行内注释勿直发｜仅新建本 md + 1 核验脚本，未改任何 .py/产物/联网。*
