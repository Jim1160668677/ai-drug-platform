"""将 cBioPortal 下载的 JSON 数据转换为系统可用的 CSV/VCF 格式"""
import json
import csv
import os
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))


def convert_mrna():
    """转换 mRNA 表达数据为 CSV 矩阵（基因 × 样本）"""
    # entrez ID → HUGO 基因符号映射
    ENTREZ_TO_HUGO = {
        1956: "EGFR", 3845: "KRAS", 7157: "TP53", 80381: "CD276",
        673: "BRAF", 5290: "PIK3CA", 207: "AKT1", 2475: "MTOR",
        4233: "MET", 2064: "ERBB2", 6098: "ROS1", 238: "ALK",
        5979: "RET", 6794: "STK11", 9817: "KEAP1", 4763: "NF1",
        5925: "RB1", 595: "CCND1", 1019: "CDK4", 1029: "CDKN2A",
        5291: "PIK3CB", 5293: "PIK3CD", 5294: "PIK3CG",
        5295: "PIK3R1", 5296: "PIK3R2", 672: "BRCA1",
        5728: "PTEN", 57698: "AKT2",
    }

    with open(os.path.join(BASE, "rna_seq", "mRNA_expression_raw.json"), encoding="utf-8-sig") as f:
        data = json.load(f)

    # 聚合：gene -> {sample: value}
    gene_sample = defaultdict(dict)
    gene_info = {}
    for rec in data:
        entrez = rec.get("entrezGeneId", 0)
        gene = ENTREZ_TO_HUGO.get(entrez, f"ENTREZ_{entrez}")
        sample = rec.get("sampleId", "?")
        value = rec.get("value", "")
        gene_sample[gene][sample] = value
        if gene not in gene_info:
            gene_info[gene] = {
                "entrez": entrez,
                "type": rec.get("type", "RNA-SEQ"),
            }

    samples = sorted({s for g in gene_sample for s in gene_sample[g]})
    genes = sorted(gene_sample.keys())

    out = os.path.join(BASE, "rna_seq", "luad_tcga_mrna_expression.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["gene_symbol", "entrez_id"] + samples)
        for g in genes:
            row = [g, gene_info[g]["entrez"]]
            for s in samples:
                row.append(gene_sample[g].get(s, ""))
            w.writerow(row)

    print(f"mRNA CSV: {len(genes)} genes x {len(samples)} samples -> {out}")
    return len(genes), len(samples)


def convert_mutations():
    """转换突变数据为 VCF 格式（提取前 50 个样本，控制文件大小）"""
    with open(os.path.join(BASE, "wes_vcf", "mutations_raw.json"), encoding="utf-8-sig") as f:
        data = json.load(f)

    # 提取前 50 个样本的突变
    sample_set = set()
    for rec in data:
        sample_set.add(rec.get("sampleId", "?"))
        if len(sample_set) >= 50:
            break
    target_samples = sorted(sample_set)

    # 过滤目标样本的突变
    filtered = [r for r in data if r.get("sampleId") in target_samples]

    out_vcf = os.path.join(BASE, "wes_vcf", "luad_tcga_mutations.vcf")
    with open(out_vcf, "w", newline="", encoding="utf-8") as f:
        # VCF 头部
        f.write("##fileformat=VCFv4.2\n")
        f.write('##INFO=<ID=GENE,Number=1,Type=String,Description="Gene symbol">\n')
        f.write('##INFO=<ID=AA,Number=1,Type=String,Description="Amino acid change">\n')
        f.write('##INFO=<ID=VT,Number=1,Type=String,Description="Variant type">\n')
        f.write('##INFO=<ID=IMPACT,Number=1,Type=String,Description="Mutation impact">\n')
        f.write('##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n')
        cols = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT"] + target_samples
        f.write("\t".join(cols) + "\n")

        written = 0
        for rec in filtered:
            chrom = rec.get("chr", ".")
            pos = rec.get("startPosition", ".")
            ref = rec.get("referenceAllele", ".")
            alt = rec.get("variantAllele", ".")
            gene = rec.get("gene", rec.get("hugoGeneSymbol", "."))
            aa = rec.get("proteinChange", rec.get("aminoAcidChange", "."))
            vt = rec.get("variantType", ".")
            impact = rec.get("mutationStatus", rec.get("impact", "."))
            sample = rec.get("sampleId", "?")

            if chrom == "." or pos == ".":
                continue

            info = f"GENE={gene};AA={aa};VT={vt};IMPACT={impact}"
            # 简化：每个突变只在一个样本中
            gts = []
            for s in target_samples:
                gts.append("0/1" if s == sample else "0/0")

            f.write("\t".join([
                str(chrom), str(pos), ".", str(ref), str(alt),
                ".", ".", info, "GT"
            ]) + "\t" + "\t".join(gts) + "\n")
            written += 1

    print(f"VCF: {written} mutations from {len(target_samples)} samples -> {out_vcf}")

    # 同时输出简化的 MAF 风格 CSV
    out_maf = os.path.join(BASE, "wes_vcf", "luad_tcga_mutations.csv")
    with open(out_maf, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sample_id", "chrom", "pos", "ref", "alt", "gene", "aa_change",
                     "variant_type", "mutation_status", "validation_status"])
        for rec in filtered:
            w.writerow([
                rec.get("sampleId", ""),
                rec.get("chr", ""),
                rec.get("startPosition", ""),
                rec.get("referenceAllele", ""),
                rec.get("variantAllele", ""),
                rec.get("gene", rec.get("hugoGeneSymbol", "")),
                rec.get("proteinChange", ""),
                rec.get("variantType", ""),
                rec.get("mutationStatus", ""),
                rec.get("validationStatus", ""),
            ])
    print(f"MAF CSV: {len(filtered)} mutations -> {out_maf}")
    return written, len(target_samples)


def convert_clinical():
    """转换临床数据为 CSV"""
    with open(os.path.join(BASE, "clinical_pathway", "clinical_data.json"), encoding="utf-8-sig") as f:
        data = json.load(f)

    # 聚合：sample -> {attr: value}
    sample_attrs = defaultdict(dict)
    for rec in data:
        sid = rec.get("sampleId", "")
        attr = rec.get("clinicalAttributeId", "")
        val = rec.get("value", "")
        if sid:
            sample_attrs[sid][attr] = val

    # 收集所有属性
    all_attrs = set()
    for attrs in sample_attrs.values():
        all_attrs.update(attrs.keys())
    all_attrs = sorted(all_attrs)

    out = os.path.join(BASE, "clinical_pathway", "luad_tcga_clinical.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sample_id"] + all_attrs)
        for sid in sorted(sample_attrs.keys()):
            row = [sid] + [sample_attrs[sid].get(a, "") for a in all_attrs]
            w.writerow(row)

    print(f"Clinical CSV: {len(sample_attrs)} samples, {len(all_attrs)} attributes -> {out}")
    return len(sample_attrs), len(all_attrs)


def create_pathway_data():
    """创建肺癌相关通路基因集"""
    pathways = {
        "EGFR_signaling": ["EGFR", "KRAS", "BRAF", "MAP2K1", "MAPK1", "PIK3CA", "AKT1", "MTOR"],
        "TP53_pathway": ["TP53", "MDM2", "CDKN1A", "BAX", "BCL2", "CCND1", "CDK4", "CDK6"],
        "immune_checkpoint": ["CD274", "PDCD1", "CTLA4", "CD80", "CD86", "B7H3", "LAG3", "TIGIT"],
        "apoptosis": ["BAX", "BAK1", "BCL2", "BCL2L1", "CASP3", "CASP8", "CASP9", "FAS", "FASL"],
        "cell_cycle": ["CCND1", "CCNE1", "CDK4", "CDK6", "CDKN2A", "RB1", "E2F1", "TP53"],
        "DNA_repair": ["BRCA1", "BRCA2", "ATM", "ATR", "CHEK1", "CHEK2", "RAD51", "XRCC1"],
        "PI3K_Akt_mTOR": ["PIK3CA", "PIK3R1", "AKT1", "AKT2", "MTOR", "TSC1", "TSC2", "PTEN"],
        "Wnt_signaling": ["CTNNB1", "APC", "AXIN1", "GSK3B", "WNT1", "FZD1", "LRP5", "LRP6"],
        "MAPK_signaling": ["KRAS", "NRAS", "BRAF", "MAP2K1", "MAP2K2", "MAPK1", "MAPK3", "RAF1"],
        "NSCLC_driver_genes": ["EGFR", "KRAS", "BRAF", "MET", "ERBB2", "ROS1", "ALK", "RET", "NTRK1", "TP53", "STK11", "KEAP1"],
    }

    out = os.path.join(BASE, "clinical_pathway", "lung_cancer_pathways.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pathway_name", "gene_symbol", "role"])
        for pathway, genes in pathways.items():
            for gene in genes:
                w.writerow([pathway, gene, "member"])

    print(f"Pathway CSV: {len(pathways)} pathways, {sum(len(g) for g in pathways.values())} gene entries -> {out}")
    return len(pathways)


if __name__ == "__main__":
    print("=" * 60)
    print("数据格式转换 — cBioPortal JSON -> CSV/VCF")
    print("=" * 60)

    g, s = convert_mrna()
    m, ms = convert_mutations()
    cs, ca = convert_clinical()
    pw = create_pathway_data()

    print("\n" + "=" * 60)
    print("转换完成：")
    print(f"  mRNA 表达矩阵: {g} 基因 x {s} 样本")
    print(f"  突变数据 VCF: {m} 突变 x {ms} 样本")
    print(f"  临床数据: {cs} 样本 x {ca} 属性")
    print(f"  通路基因集: {pw} 通路")
    print("=" * 60)
