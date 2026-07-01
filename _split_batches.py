"""一次性工具:把测试集 csv/xlsx(优先 DOI、回退 title、去重)切成 N 个 chunk txt,供多成员并行跑到各自输出目录。用完可删。"""
import csv
import math
import os


def read_entries(src):
    low = src.lower()
    if low.endswith(".csv"):
        with open(src, newline="", encoding="utf-8-sig") as f:
            rows = [[(c if c is not None else "") for c in row] for row in csv.reader(f)]
    else:
        import openpyxl
        wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
        ws = wb.active
        rows = [[("" if c.value is None else str(c.value)).strip() for c in row] for row in ws.iter_rows()]
        wb.close()
    header = [c.strip().lower() for c in rows[0]]
    doi_i = header.index("doi") if "doi" in header else -1
    title_i = header.index("title") if "title" in header else -1
    entries = []
    if doi_i >= 0 or title_i >= 0:
        for r in rows[1:]:
            val = ""
            if 0 <= doi_i < len(r) and r[doi_i].strip():
                val = r[doi_i].strip()
            elif 0 <= title_i < len(r) and r[title_i].strip():
                val = r[title_i].strip()
            if val:
                entries.append(val)
    else:
        for r in rows:
            for c in r:
                cell = c.strip()
                if cell and not cell.startswith("#"):
                    entries.append(cell)
                    break
    seen, uniq = set(), []
    for e in entries:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return uniq


def split(src, outdir, n=5):
    uniq = read_entries(src)
    os.makedirs(outdir, exist_ok=True)
    per = math.ceil(len(uniq) / n)
    for k in range(n):
        chunk = uniq[k * per:(k + 1) * per]
        fp = os.path.join(outdir, f"chunk_{k + 1}.txt")
        with open(fp, "w", encoding="utf-8") as f:
            f.write("\n".join(chunk) + "\n")
        print(f"{os.path.basename(outdir)}/chunk_{k + 1}.txt: {len(chunk)}")
    print(f"{os.path.basename(outdir)} total unique: {len(uniq)}")


if __name__ == "__main__":
    base = r"E:\AI项目\一次性操作窗口\output\title_doi_batches_4_5_6_distinct_20260630"
    split(base + r"\batch_05\title_doi_500_batch_5.csv", r"e:\AI项目\谷歌学术人机认证\batch5_chunks", 5)
    split(base + r"\batch_06\title_doi_500_batch_6.csv", r"e:\AI项目\谷歌学术人机认证\batch6_chunks", 5)
