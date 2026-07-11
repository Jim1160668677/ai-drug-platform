"""将 scRNA-seq TSV 转为系统可用的 CSV 格式（简化版）"""
import csv
import gzip
import os

BASE = os.path.dirname(os.path.abspath(__file__))


def convert_scrna():
    """将第一个人类肿瘤样本的 scRNA-seq 转为 CSV（取前 200 个基因）"""
    src_gz = os.path.join(BASE, "scrna_seq", "extracted", "GSM3635278_human_p1t1_raw_counts.tsv.gz")
    out = os.path.join(BASE, "scrna_seq", "human_p1t1_scrna_counts.csv")

    with gzip.open(src_gz, "rt", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader)  # 细胞 ID 行
        rows = []
        for i, row in enumerate(reader):
            if i >= 200:  # 取前 200 个基因
                break
            rows.append(row)

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["gene_symbol"] + header)
        for row in rows:
            w.writerow(row)

    print(f"scRNA-seq CSV: {len(rows)} genes x {len(header)-1} cells -> {out}")
    return len(rows), len(header) - 1


if __name__ == "__main__":
    g, c = convert_scrna()
    print(f"单细胞数据简化完成: {g} 基因 x {c} 细胞")
