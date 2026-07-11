// WES/WGS 变异注释流程 — VEP / SnpEff
// nextflow run variant_annotation.nf --vcf input.vcf --reference GRCh38 --output ./results

params.vcf       = null
params.reference = "GRCh38"
params.output    = "./results"
params.annotation_tool = "snpeff"
params.filter_clinvar = true

log.info """
=========================================
Variant Annotation Pipeline
=========================================
VCF          : ${params.vcf}
Reference    : ${params.reference}
Output       : ${params.output}
Tool         : ${params.annotation_tool}
Filter ClinVar : ${params.filter_clinvar}
=========================================
"""

if (!params.vcf) {
    error "Missing --vcf parameter"
}

input_vcf = file(params.vcf)
if (!input_vcf.exists()) {
    error "VCF file not found: ${params.vcf}"
}

output_dir = file(params.output)
output_dir.mkdirs()

workflow {
    annotated = ANNOTATE(input_vcf)
    FILTER_CLINVAR(annotated)
    SUMMARY(annotated)
}

process ANNOTATE {
    container 'ensembl/vep:release111.0'
    publishDir "${params.output}", mode: 'copy'

    input:
    path input_vcf

    output:
    path "annotated.vcf"

    script:
    if (params.annotation_tool == "vep")
        """
        vep -i ${input_vcf} -o annotated.vcf \
            --cache --offline --assembly ${params.reference} \
            --symbol --protein --hgvs --vcf --force_overwrite \
            --database
        """
    else
        """
        snpEff ${params.reference} ${input_vcf} > annotated.vcf
        """
}

process FILTER_CLINVAR {
    container 'python:3.11-slim'
    publishDir "${params.output}", mode: 'copy'
    when { params.filter_clinvar }

    input:
    path annotated_vcf

    output:
    path "clinvar_pathogenic.vcf"

    script:
    """
    pip install --quiet cyvcf2
    python3 << 'EOF'
from cyvcf2 import VCF, Writer
reader = VCF("${annotated_vcf}")
writer = Writer("clinvar_pathogenic.vcf", reader)
for v in reader:
    clnsig = (v.INFO.get('CLNSIG') or '').lower()
    if any(t in clnsig for t in ['pathogenic', 'likely_pathogenic']):
        writer.write_record(v)
writer.close()
EOF
    """
}

process SUMMARY {
    container 'python:3.11-slim'
    publishDir "${params.output}", mode: 'copy'

    input:
    path annotated_vcf

    output:
    path "summary.json"

    script:
    """
    pip install --quiet cyvcf2
    python3 << 'EOF'
import json
from cyvcf2 import VCF
from collections import Counter

vcf = VCF("${annotated_vcf}")
total = 0
per_chrom = Counter()
clinsig_counter = Counter()
consequence_counter = Counter()

for v in vcf:
    total += 1
    per_chrom[v.CHROM] += 1
    clnsig = (v.INFO.get('CLNSIG') or 'unknown')
    clinsig_counter[clnsig] += 1
    consq = (v.INFO.get('Consequence') or 'unknown')
    consequence_counter[consq] += 1

summary = {
    "total_variants": total,
    "per_chrom": dict(per_chrom.most_common(25)),
    "clinsig_distribution": dict(clinsig_counter.most_common(10)),
    "top_consequences": dict(consequence_counter.most_common(10)),
}
with open("summary.json", "w") as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)
EOF
    """
}
