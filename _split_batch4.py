"""一次性工具:把 batch_4 的 500 条(优先 DOI、回退 title)切成 5 个 chunk txt,供多成员并行跑到各自输出目录。用完可删。"""
import math
import os

import openpyxl

SRC = r"E:\AI项目\一次性操作窗口\output\title_doi_batches_4_5_6_distinct_20260630\batch_04\title_doi_500_batch_4.xlsx"
OUTDIR = r"e:\AI项目\谷歌学术人机认证\batch4_chunks"
N = 5

wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
ws = wb.active
rows = [[("" if c.value is None else str(c.value)).strip() for c in row] for row in ws.iter_rows()]
wb.close()

header = [c.strip().lower() for c in rows[0]]
doi_i = header.index("doi") if "doi" in header else -1
title_i = header.index("title") if "title" in header else -1

entries = []
for r in rows[1:]:
    val = ""
    if 0 <= doi_i < len(r) and r[doi_i].strip():
        val = r[doi_i].strip()
    elif 0 <= title_i < len(r) and r[title_i].strip():
        val = r[title_i].strip()
    if val:
        entries.append(val)

seen, uniq = set(), []
for e in entries:
    if e not in seen:
        seen.add(e)
        uniq.append(e)

os.makedirs(OUTDIR, exist_ok=True)
per = math.ceil(len(uniq) / N)
for k in range(N):
    chunk = uniq[k * per:(k + 1) * per]
    fp = os.path.join(OUTDIR, f"chunk_{k + 1}.txt")
    with open(fp, "w", encoding="utf-8") as f:
        f.write("\n".join(chunk) + "\n")
    print(f"chunk_{k + 1}.txt: {len(chunk)} entries -> {fp}")

print("total unique entries:", len(uniq))
