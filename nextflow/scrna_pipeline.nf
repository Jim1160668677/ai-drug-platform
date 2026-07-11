// scRNA-seq 处理流程 — Scanpy 完整预处理
// nextflow run scrna_pipeline.nf --input sample.h5 --output ./results

params.input    = null
params.output   = "./results"
params.min_genes = 200
params.min_cells = 3
params.n_top_genes = 2000
params.resolution = 0.8

log.info """
=========================================
scRNA-seq Pipeline (Scanpy)
=========================================
Input  : ${params.input}
Output : ${params.output}
Min genes/cell : ${params.min_genes}
Min cells/gene : ${params.min_cells}
Resolution     : ${params.resolution}
=========================================
"""

if (!params.input) {
    error "Missing required parameter: --input (10x h5 / mtx / csv file path)"
}

// 输入文件检查
input_file = file(params.input)
if (!input_file.exists()) {
    error "Input file does not exist: ${params.input}"
}

// 输出目录
output_dir = file(params.output)
output_dir.mkdirs()

workflow {
    qc_filtered = QC_FILTER(input_file)
    normalized  = NORMALIZE_PCA(qc_filtered)
    clustered   = CLUSTER_UMAP(normalized)
    DIFF_EXP(clustered)
}

process QC_FILTER {
    container 'python:3.11-slim'
    publishDir "${params.output}", mode: 'copy'

    input:
    path input_file

    output:
    path "filtered.h5ad"

    script:
    """
    pip install --quiet scanpy anndata
    python3 << 'EOF'
import scanpy as sc
import sys
adata = sc.read_10x_h5("${input_file}") if str("${input_file}").endswith('.h5') else sc.read("${input_file}")
adata.var['mt'] = adata.var_names.str.startswith('MT-')
sc.pp.calculate_qc_metrics(adata, qc_vars=['mt'], inplace=True)
sc.pp.filter_cells(adata, min_genes=${params.min_genes})
sc.pp.filter_genes(adata, min_cells=${params.min_cells})
adata.write("filtered.h5ad")
EOF
    """
}

process NORMALIZE_PCA {
    container 'python:3.11-slim'
    publishDir "${params.output}", mode: 'copy'

    input:
    path filtered

    output:
    path "normalized.h5ad"

    script:
    """
    pip install --quiet scanpy
    python3 << 'EOF'
import scanpy as sc
adata = sc.read_h5ad("${filtered}")
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=${params.n_top_genes}, flavor='seurat')
sc.pp.pca(adata, n_comps=min(50, adata.n_obs-1, adata.n_vars-1))
adata.write("normalized.h5ad")
EOF
    """
}

process CLUSTER_UMAP {
    container 'python:3.11-slim'
    publishDir "${params.output}", mode: 'copy'

    input:
    path normalized

    output:
    path "annotated.h5ad"

    script:
    """
    pip install --quiet scanpy leidenalg
    python3 << 'EOF'
import scanpy as sc
adata = sc.read_h5ad("${normalized}")
sc.pp.neighbors(adata, n_neighbors=10)
sc.tl.umap(adata)
sc.tl.leiden(adata, resolution=${params.resolution}, key_added='leiden')
adata.write("annotated.h5ad")
EOF
    """
}

process DIFF_EXP {
    container 'python:3.11-slim'
    publishDir "${params.output}", mode: 'copy'

    input:
    path annotated

    output:
    path "markers.csv", emit: markers
    path "qc_report.html", emit: report

    script:
    """
    pip install --quiet scanpy pandas
    python3 << 'EOF'
import scanpy as sc
import pandas as pd
adata = sc.read_h5ad("${annotated}")
sc.tl.rank_genes_groups(adata, 'leiden', method='wilcoxon', n_genes=20)
result = adata.uns['rank_genes_groups']
df = pd.DataFrame({
    cluster: result['names'][cluster]
    for cluster in adata.obs['leiden'].cat.categories
})
df.to_csv("markers.csv", index=False)
with open("qc_report.html", "w") as f:
    f.write(f"<h1>scRNA-seq QC Report</h1>")
    f.write(f"<p>Cells: {adata.n_obs}, Genes: {adata.n_vars}</p>")
    f.write(f"<p>Clusters: {adata.obs['leiden'].nunique()}</p>")
EOF
    """
}
