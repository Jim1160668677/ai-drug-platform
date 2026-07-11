// RNA-seq 差异表达流程 — DESeq2
// nextflow run rna_seq_pipeline.nf --input counts.csv --samples samples.csv --output ./results

params.input   = null
params.samples = null
params.output  = "./results"
params.control = "control"
params.case    = "case"
params.fc_threshold = 1.5
params.pvalue_threshold = 0.05

log.info """
=========================================
RNA-seq Differential Expression Pipeline
=========================================
Counts    : ${params.input}
Samples   : ${params.samples}
Output    : ${params.output}
Control   : ${params.control}
Case      : ${params.case}
FC threshold  : ${params.fc_threshold}
P threshold   : ${params.pvalue_threshold}
=========================================
"""

if (!params.input || !params.samples) {
    error "Missing --input (counts matrix) or --samples (sample metadata)"
}

input_file   = file(params.input)
samples_file = file(params.samples)
output_dir   = file(params.output)
output_dir.mkdirs()

workflow {
    quantified = QUANTIFY(input_file, samples_file)
    DIFF_EXPRESSION(quantified)
}

process QUANTIFY {
    container 'python:3.11-slim'
    publishDir "${params.output}", mode: 'copy'

    input:
    path counts_file
    path samples_file

    output:
    path "filtered_counts.csv"

    script:
    """
    pip install --quiet pandas
    python3 << 'EOF'
import pandas as pd
counts = pd.read_csv("${counts_file}", index_col=0)
samples = pd.read_csv("${samples_file}")
valid_samples = samples['sample_id'].tolist()
keep = [c for c in counts.columns if c in valid_samples]
filtered = counts[keep]
filtered.to_csv("filtered_counts.csv")
EOF
    """
}

process DIFF_EXPRESSION {
    container 'bioconductor/deseq2:latest'
    publishDir "${params.output}", mode: 'copy'

    input:
    path filtered_counts

    output:
    path "deseq2_results.csv"
    path "volcano_plot.png"
    path "ma_plot.png"

    script:
    """
    Rscript - << 'EOF'
library(DESeq2)
library(ggplot2)

counts <- read.csv("${filtered_counts}", row.names=1)
counts <- as.matrix(round(counts))
mode(counts) <- "integer"

samples <- read.csv("${params.samples}")
samples <- samples[match(colnames(counts), samples\$sample_id),]
dds <- DESeqDataSetFromMatrix(counts, samples, design=~condition)
dds <- DESeq(dds)
res <- results(dds, contrast=c("condition", "${params.case}", "${params.control}"))
res_df <- as.data.frame(res)
res_df\$gene <- rownames(res_df)
write.csv(res_df, "deseq2_results.csv", row.names=FALSE)

# Volcano plot
res_df\$sig <- ifelse(res_df\$padj < ${params.pvalue_threshold} & abs(res_df\$log2FoldChange) > log2(${params.fc_threshold}), "Significant", "Not sig")
ggplot(res_df, aes(x=log2FoldChange, y=-log10(padj), color=sig)) +
  geom_point() + scale_color_manual(values=c("grey","red")) + theme_minimal()
ggsave("volcano_plot.png")

# MA plot
ggplot(res_df, aes(x=log10(baseMean), y=log2FoldChange, color=sig)) +
  geom_point() + scale_color_manual(values=c("grey","red")) + theme_minimal()
ggsave("ma_plot.png")
EOF
    """
}
