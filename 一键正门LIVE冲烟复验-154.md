# 一键正门 LIVE 冲烟复验-154

> **4/5 成功**｜`run_all.py` 默认正门（`--route-b off`，无浏览器）｜RUNROOT=`out/_smoke154_live`（隔离，未碰主 `out/coverage.json`）｜2026-07-03 00:21:50

## 结论

| 项 | 结果 |
|---|---|
| 成功 | **4/5（80%）** |
| 失败 | `10.7554/eLife.08496` → `download-failed:http-404`（publisher_oa 直链 404，非流程断点） |
| 程序化 | 全程 CLI 一键，无人工断点 ✓ |
| 文件名 | DOI → 下划线标准化 ✓ |
| 日志 | `run.log` + 一页式 `run_all` 总结可读 ✓ |

## 输入（5 条 OA）

```
10.1371/journal.pone.0000217
10.7554/eLife.08496
1706.03762
10.3389/fpsyg.2015.01931
10.1038/s41598-017-17382-2
```

命令：

```bash
python run_all.py -f smoke154_live_input.txt --email research.probe@example.org \
  -o out/_smoke154_live --coverage-root out/_smoke154_live --no-resume -c 1 --route-b off
```

## 文件名样例（`fetch/pdfs/`）

| DOI | 标准文件名 | bytes | 源 |
|---|---|---:|---|
| 10.1371/journal.pone.0000217 | `10.1371_journal.pone.0000217.pdf` | 185,118 | unpaywall |
| 10.48550/arxiv.1706.03762 | `10.48550_arxiv.1706.03762.pdf` | 2,215,244 | arxiv |
| 10.3389/fpsyg.2015.01931 | `10.3389_fpsyg.2015.01931.pdf` | 1,967,871 | unpaywall |
| 10.1038/s41598-017-17382-2 | `10.1038_s41598-017-17382-2.pdf` | 2,750,151 | unpaywall |

## 日志片段

```
[INFO] 开始处理 5 条输入,并发=1,源=snapshot,unpaywall,openalex,publisher_oa,...
[INFO] [OK] 10.1371/journal.pone.0000217 -> unpaywall (doi, 4996ms)
[INFO] [MISS] 10.7554/elife.08496 -> download-failed:http-404 (doi, 37559ms)
[INFO] [OK] 10.48550/arxiv.1706.03762 -> arxiv (arxiv, 7867ms)
[INFO] [OK] 10.3389/fpsyg.2015.01931 -> unpaywall (doi, 5615ms)
[INFO] [OK] 10.1038/s41598-017-17382-2 -> unpaywall (doi, 8273ms)
[INFO] 完成。成功 4/5 (80%),用时 64.3s

run_all 一页式总结: 成功 4 / 处理 5(miss 1),用时 64.3s
本次命中源: unpaywall=3, arxiv=1
```

## 备注

- 本机 shell **未设 `OPENALEX_KEY`**（openalex 仍走 mailto 礼貌池）；`run_all` openalex_key 接线已在 `--selftest` 验证。
- eLife 404 属单条候选失效，换 DOI 或开 route-B/landing 可另测；**不否定一键正门 GOAL**。
