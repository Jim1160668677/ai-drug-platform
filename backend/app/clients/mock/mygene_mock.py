"""Mock MyGene 客户端 — 预置 EGFR/B7H3/FAP/TP53/KRAS 基因信息"""
import asyncio
from typing import Any, Dict

from app.clients.base import GeneClient


GENE_DATABASE: Dict[str, Dict[str, Any]] = {
    "EGFR": {
        "symbol": "EGFR",
        "name": "Epidermal Growth Factor Receptor",
        "entrez_id": 1956,
        "ensembl_id": "ENSG00000146648",
        "uniprot_id": "P00533",
        "hgnc_id": "HGNC:3236",
        "gene_type": "protein_coding",
        "location": "7p11.2",
        "summary": (
            "EGFR 编码表皮生长因子受体（ERBB1/HER1），是跨膜酪氨酸激酶受体 ERBB 家族成员。"
            "与配体结合后同源/异源二聚化，激活 PI3K-AKT、RAS-RAF-MEK-ERK、JAK-STAT 等下游通路，"
            "调节细胞增殖、分化、存活和迁移。EGFR 在 NSCLC、胶质瘤、结直肠癌中常发生激活突变或扩增，"
            "是精准医学中最成熟的可靶向癌基因之一。"
        ),
        "pathways": [
            {"id": "hsa04010", "name": "MAPK signaling pathway", "source": "KEGG"},
            {"id": "hsa04012", "name": "ErbB signaling pathway", "source": "KEGG"},
            {"id": "hsa04151", "name": "PI3K-Akt signaling pathway", "source": "KEGG"},
            {"id": "R-HSA-1227986", "name": "Signaling by ERBB2", "source": "Reactome"},
        ],
        "synonyms": ["ERBB1", "HER1", "ERRP"],
        "drugbank_count": 12,
    },
    "B7H3": {
        "symbol": "CD276",
        "name": "CD276 Molecule",
        "entrez_id": 80381,
        "ensembl_id": "ENSG00000103882",
        "uniprot_id": "Q5ZPR3",
        "hgnc_id": "HGNC:16427",
        "gene_type": "protein_coding",
        "location": "9p13.3",
        "summary": (
            "CD276（即 B7-H3）是 B7 家族免疫检查点分子，在多种实体瘤（NSCLC、前列腺癌、胰腺癌、"
            "儿童神经母细胞瘤）中过表达，与免疫抑制、血管生成和不良预后相关。当前无获批靶向药，"
            "在研疗法包括抗体药物偶联物（ADC）、CAR-T、双特异性抗体。是 AI 模式发现新靶点的典型案例。"
        ),
        "pathways": [
            {"id": "R-HSA-389958", "name": "Co-stimulation by the CD28 family", "source": "Reactome"},
        ],
        "synonyms": ["B7-H3", "B7H3", "CD276"],
        "drugbank_count": 0,
    },
    "FAP": {
        "symbol": "FAP",
        "name": "Fibroblast Activation Protein Alpha",
        "entrez_id": 2191,
        "ensembl_id": "ENSG00000171243",
        "uniprot_id": "Q12884",
        "hgnc_id": "HGNC:3586",
        "gene_type": "protein_coding",
        "location": "2q24.2",
        "summary": (
            "FAP 编码成纤维激活蛋白 α，是一种 II 型跨膜丝氨酸蛋白酶，在肿瘤基质中的癌症相关成纤维细胞"
            "（CAF）高表达，促进肿瘤生长、侵袭和免疫逃逸。FAP 靶向 CAR-T、放射性核素疗法（如 68Ga-FAPI "
            "PET 显像）在研，是个性化基质治疗的关键候选。"
        ),
        "pathways": [
            {"id": "hsa04512", "name": "ECM-receptor interaction", "source": "KEGG"},
        ],
        "synonyms": ["FAPA", "DPPIV", "SEPR"],
        "drugbank_count": 2,
    },
    "TP53": {
        "symbol": "TP53",
        "name": "Tumor Protein P53",
        "entrez_id": 7157,
        "ensembl_id": "ENSG00000141510",
        "uniprot_id": "P04637",
        "hgnc_id": "HGNC:11998",
        "gene_type": "tumor_suppressor",
        "location": "17p13.1",
        "summary": (
            "TP53 编码 p53 肿瘤抑制蛋白，被称为'基因组卫士'。在 DNA 损伤、致癌基因激活、缺氧等应激下被激活，"
            "通过转录调控介导细胞周期阻滞、DNA 修复、凋亡和衰老。TP53 是人类肿瘤中最常突变的基因（>50%），"
            "突变类型多为错义突变（hotspot：R175H、R248Q、R273H），导致功能丧失并获得促癌功能。"
        ),
        "pathways": [
            {"id": "hsa04115", "name": "p53 signaling pathway", "source": "KEGG"},
            {"id": "hsa04110", "name": "Cell cycle", "source": "KEGG"},
        ],
        "synonyms": ["p53", "LFS1", "BCC7"],
        "drugbank_count": 0,
    },
    "KRAS": {
        "symbol": "KRAS",
        "name": "KRAS Proto-Oncogene, GTPase",
        "entrez_id": 3845,
        "ensembl_id": "ENSG00000133703",
        "uniprot_id": "P01116",
        "hgnc_id": "HGNC:6407",
        "gene_type": "protein_coding",
        "location": "12p12.1",
        "summary": (
            "KRAS 编码小 GTP 酶，是 RAS-MAPK 信号通路的关键开关。结合 GTP 时激活，水解为 GDP 时失活。"
            "KRAS 突变（G12C/G12D/G12V 等热点）使其锁定在激活状态，持续驱动下游增殖信号。"
            "在胰腺癌（>90%）、结直肠癌（~40%）、NSCLC（~25%）中高频突变。"
            "Sotorasib（AMG 510）和 Adagrasib（MRTX849）是首个获批的 KRAS G12C 抑制剂。"
        ),
        "pathways": [
            {"id": "hsa04010", "name": "MAPK signaling pathway", "source": "KEGG"},
            {"id": "hsa05223", "name": "Non-small cell lung cancer", "source": "KEGG"},
        ],
        "synonyms": ["KRAS2", "RASK2", "c-K-bas"],
        "drugbank_count": 4,
    },
}


class MockGeneClient(GeneClient):
    """Mock MyGene 客户端 — 返回预置基因信息"""

    async def query(self, gene_symbol: str) -> dict:
        await asyncio.sleep(0.15)

        symbol_upper = gene_symbol.strip().upper()
        if symbol_upper in GENE_DATABASE:
            return dict(GENE_DATABASE[symbol_upper])

        # 兼容别名查找
        for sym, data in GENE_DATABASE.items():
            if symbol_upper in [s.upper() for s in data.get("synonyms", [])]:
                return dict(data)

        # 未知基因 — 返回通用占位结构（保持 schema 一致）
        return {
            "symbol": gene_symbol,
            "name": f"{gene_symbol} (未在 Mock 数据库中)",
            "entrez_id": None,
            "ensembl_id": None,
            "uniprot_id": None,
            "hgnc_id": None,
            "gene_type": "unknown",
            "location": None,
            "summary": (
                f"基因 {gene_symbol} 在 Mock 数据库中无详细注释。"
                "配置 USE_MOCK=false 并接入 MyGene.info 真实 API 后将获得完整信息。"
            ),
            "pathways": [],
            "synonyms": [],
            "drugbank_count": 0,
            "note": "mock_placeholder",
        }
