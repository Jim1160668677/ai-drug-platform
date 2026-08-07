"""Mock NCBI E-utilities 客户端 — 预置文献/变异/基因数据

用于测试环境（USE_MOCK=true）和开发环境，无需真实 NCBI API 调用。
数据集覆盖 EGFR/TP53/KRAS 等核心基因，与 MockGeneClient 的 GENE_DATABASE 风格一致。
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.clients.base import NcbiClient

logger = logging.getLogger(__name__)


# ========== 预置 PubMed 文献数据 ==========
# 覆盖 EGFR/TP53/KRAS 等核心基因的代表性文献摘要
PUBMED_DATABASE: Dict[str, List[Dict[str, Any]]] = {
    "EGFR": [
        {
            "uid": "36123456",
            "title": "EGFR mutations in non-small cell lung cancer: A comprehensive review of clinical implications",
            "authors": ["Lynch TJ", "Bell DW", "Sordella R"],
            "journal": "N Engl J Med",
            "pubdate": "2024 Jun 15",
            "abstract": (
                "EGFR mutations are found in 10-15% of non-small cell lung cancer (NSCLC) patients, "
                "with higher prevalence in never-smokers, women, and Asian populations. "
                "Exon 19 deletions and L858R point mutations account for 85% of activating mutations "
                "and confer sensitivity to EGFR tyrosine kinase inhibitors (TKIs) such as gefitinib and erlotinib. "
                "The T790M mutation is the most common resistance mechanism, occurring in 50-60% of resistant cases. "
                "Third-generation TKIs like osimertinib have shown superior efficacy in T790M-positive tumors."
            ),
            "doi": "10.1056/NEJMra2401234",
            "pubtype": ["Review", "Journal Article"],
            "source": "PubMed",
        },
        {
            "uid": "36123457",
            "title": "Osimertinib as first-line treatment for EGFR-mutated NSCLC: FLAURA trial 5-year update",
            "authors": ["Soria JC", "Ohe Y", "Vansteenkiste J"],
            "journal": "J Clin Oncol",
            "pubdate": "2024 Mar 20",
            "abstract": (
                "The FLAURA trial demonstrated superior progression-free survival (PFS) with osimertinib "
                "compared to first-generation EGFR TKIs (18.9 vs 10.2 months, HR 0.46). "
                "At 5-year follow-up, overall survival benefit was confirmed (38.6 vs 31.8 months). "
                "Central nervous system metastasis occurred in 28% of patients, with intracranial PFS of 22.1 months."
            ),
            "doi": "10.1200/JCO.24.00012",
            "pubtype": ["Clinical Trial", "Phase III"],
            "source": "PubMed",
        },
        {
            "uid": "36123458",
            "title": "Mechanisms of acquired resistance to EGFR TKIs in lung cancer",
            "authors": ["Wu SG", "Shih JY"],
            "journal": "Nat Rev Cancer",
            "pubdate": "2024 Jan 10",
            "abstract": (
                "Acquired resistance to EGFR TKIs involves multiple mechanisms: T790M mutation (50-60%), "
                "MET amplification (5-10%), HER2 amplification (8%), histologic transformation to SCLC (3-5%), "
                "and epithelial-mesenchymal transition. Liquid biopsy using circulating tumor DNA (ctDNA) "
                "enables non-invasive monitoring of resistance mechanisms and early detection of progression."
            ),
            "doi": "10.1038/s41568-024-00045-6",
            "pubtype": ["Review"],
            "source": "PubMed",
        },
    ],
    "TP53": [
        {
            "uid": "36234567",
            "title": "TP53 mutations in human cancer: Recent advances in therapy",
            "authors": ["Vogelstein B", "Lane D", "Levine AJ"],
            "journal": "Nature",
            "pubdate": "2024 May 5",
            "abstract": (
                "TP53 is the most frequently mutated gene in human cancer (>50% of all tumors). "
                "Most mutations are missense, clustered in the DNA-binding domain (R175, R248, R273 hotspots). "
                "Mutant p53 not only loses tumor suppressor function but also gains oncogenic properties, "
                "promoting invasion, metastasis, and chemoresistance. "
                "Targeted therapies include APR-246 (p53 reactivation), PC14504 (Y220C-specific), "
                "and KRT-232 (MDM2 inhibitor for wild-type p53)."
            ),
            "doi": "10.1038/s41586-024-12345-6",
            "pubtype": ["Review", "Journal Article"],
            "source": "PubMed",
        },
        {
            "uid": "36234568",
            "title": "Eprenetapopt (APR-246) in TP53-mutant myelodysplastic syndromes",
            "authors": ["Cluzeau T", "Sekeres MA", "List AF"],
            "journal": "J Clin Oncol",
            "pubdate": "2024 Feb 1",
            "abstract": (
                "Eprenetapopt combined with azacitidine showed promising response rates in TP53-mutant MDS "
                "(overall response rate 73%, complete remission 50%). "
                "The phase III trial is ongoing. Mechanism involves reactivation of mutant p53 conformation, "
                "restoration of pro-apoptotic function, and induction of ferroptosis."
            ),
            "doi": "10.1200/JCO.23.02234",
            "pubtype": ["Clinical Trial"],
            "source": "PubMed",
        },
    ],
    "KRAS": [
        {
            "uid": "36345678",
            "title": "KRAS G12C inhibitors in solid tumors: Beyond lung cancer",
            "authors": ["Skoulidis F", "Li BT", "Dy GK"],
            "journal": "N Engl J Med",
            "pubdate": "2024 Jul 1",
            "abstract": (
                "Sotorasib (AMG 510) and adagrasib (MRTX849) are FDA-approved KRAS G12C inhibitors for NSCLC. "
                "Response rates of 28-43% in pretreated patients, with median PFS of 6.8 months. "
                "Expansion to pancreatic, colorectal, and other solid tumors is under investigation. "
                "Resistance mechanisms include KRAS Y96D, Y96S, H95Q, and bypass activation of RTK/RAS/MAPK."
            ),
            "doi": "10.1056/NEJMoa2405678",
            "pubtype": ["Clinical Trial", "Phase I/II"],
            "source": "PubMed",
        },
    ],
    "default": [
        {
            "uid": "36000001",
            "title": "Advances in precision oncology: A systematic review",
            "authors": ["Smith A", "Johnson B"],
            "journal": "JAMA Oncol",
            "pubdate": "2024 Jun",
            "abstract": (
                "Precision oncology has transformed cancer treatment through biomarker-driven therapy selection. "
                "This review summarizes current genomic testing standards, targeted therapies, "
                "and emerging immunotherapy approaches."
            ),
            "doi": "10.1001/jamaoncol.2024.0001",
            "pubtype": ["Review"],
            "source": "PubMed",
        }
    ],
}


# ========== 预置 ClinVar 变异数据 ==========
CLINVAR_DATABASE: Dict[str, List[Dict[str, Any]]] = {
    "TP53": [
        {
            "uid": "VCV000011821",
            "title": "NM_000546.6(TP53):c.524G>A (p.Arg175His)",
            "clnsig": "Pathogenic",
            "gene": "TP53",
            "hgvs_p": "p.Arg175His",
            "hgvs_c": "c.524G>A",
            "variant_type": "single_nucleotide_variant",
            "review_status": "reviewed by expert panel",
            "source": "NCBI ClinVar (E-utilities)",
        },
        {
            "uid": "VCV000011820",
            "title": "NM_000546.6(TP53):c.743G>A (p.Arg248Gln)",
            "clnsig": "Pathogenic",
            "gene": "TP53",
            "hgvs_p": "p.Arg248Gln",
            "hgvs_c": "c.743G>A",
            "variant_type": "single_nucleotide_variant",
            "review_status": "reviewed by expert panel",
            "source": "NCBI ClinVar (E-utilities)",
        },
        {
            "uid": "VCV000011819",
            "title": "NM_000546.6(TP53):c.818G>A (p.Arg273His)",
            "clnsig": "Pathogenic",
            "gene": "TP53",
            "hgvs_p": "p.Arg273His",
            "hgvs_c": "c.818G>A",
            "variant_type": "single_nucleotide_variant",
            "review_status": "reviewed by expert panel",
            "source": "NCBI ClinVar (E-utilities)",
        },
        {
            "uid": "VCV000011818",
            "title": "NM_000546.6(TP53):c.841C>T (p.Pro281Leu)",
            "clnsig": "Likely pathogenic",
            "gene": "TP53",
            "hgvs_p": "p.Pro281Leu",
            "hgvs_c": "c.841C>T",
            "variant_type": "single_nucleotide_variant",
            "review_status": "criteria provided, multiple submitters",
            "source": "NCBI ClinVar (E-utilities)",
        },
        {
            "uid": "VCV000011817",
            "title": "NM_000546.6(TP53):c.215C>G (p.Pro72Arg)",
            "clnsig": "Pathogenic",
            "gene": "TP53",
            "hgvs_p": "p.Pro72Arg",
            "hgvs_c": "c.215C>G",
            "variant_type": "single_nucleotide_variant",
            "review_status": "criteria provided, single submitter",
            "source": "NCBI ClinVar (E-utilities)",
        },
    ],
    "EGFR": [
        {
            "uid": "VCV000035660",
            "title": "NM_005228.5(EGFR):c.2156G>C (p.Gly719Ala)",
            "clnsig": "Pathogenic",
            "gene": "EGFR",
            "hgvs_p": "p.Gly719Ala",
            "hgvs_c": "c.2156G>C",
            "variant_type": "single_nucleotide_variant",
            "review_status": "reviewed by expert panel",
            "source": "NCBI ClinVar (E-utilities)",
        },
        {
            "uid": "VCV000035659",
            "title": "NM_005228.5(EGFR):c.2369C>T (p.Thr790Met)",
            "clnsig": "Pathogenic",
            "gene": "EGFR",
            "hgvs_p": "p.Thr790Met",
            "hgvs_c": "c.2369C>T",
            "variant_type": "single_nucleotide_variant",
            "review_status": "reviewed by expert panel",
            "source": "NCBI ClinVar (E-utilities)",
        },
        {
            "uid": "VCV000035658",
            "title": "NM_005228.5(EGFR):c.2573T>G (p.Leu858Arg)",
            "clnsig": "Pathogenic",
            "gene": "EGFR",
            "hgvs_p": "p.Leu858Arg",
            "hgvs_c": "c.2573T>G",
            "variant_type": "single_nucleotide_variant",
            "review_status": "reviewed by expert panel",
            "source": "NCBI ClinVar (E-utilities)",
        },
    ],
    "KRAS": [
        {
            "uid": "VCV000037634",
            "title": "NM_004985.4(KRAS):c.34G>T (p.Gly12Cys)",
            "clnsig": "Pathogenic",
            "gene": "KRAS",
            "hgvs_p": "p.Gly12Cys",
            "hgvs_c": "c.34G>T",
            "variant_type": "single_nucleotide_variant",
            "review_status": "reviewed by expert panel",
            "source": "NCBI ClinVar (E-utilities)",
        },
        {
            "uid": "VCV000037633",
            "title": "NM_004985.4(KRAS):c.35G>A (p.Gly12Asp)",
            "clnsig": "Pathogenic",
            "gene": "KRAS",
            "hgvs_p": "p.Gly12Asp",
            "hgvs_c": "c.35G>A",
            "variant_type": "single_nucleotide_variant",
            "review_status": "reviewed by expert panel",
            "source": "NCBI ClinVar (E-utilities)",
        },
    ],
}


# ========== 预置基因信息 ==========
GENE_INFO_DATABASE: Dict[str, Dict[str, Any]] = {
    "EGFR": {
        "symbol": "EGFR",
        "entrez_id": "1956",
        "name": "epidermal growth factor receptor",
        "description": "Receptor tyrosine kinase, ERBB family member",
        "summary": (
            "The protein encoded by this gene is a transmembrane glycoprotein that is a receptor "
            "for members of the epidermal growth factor family. Mutations in this gene are associated "
            "with lung cancer, glioblastoma, and other cancers."
        ),
        "chromosome": "7",
        "map_location": "7p11.2",
        "aliases": ["ERBB1", "HER1", "ERRP"],
        "other_aliases": "ERBB1, HER1, ERRP",
        "source": "NCBI Gene",
    },
    "TP53": {
        "symbol": "TP53",
        "entrez_id": "7157",
        "name": "tumor protein p53",
        "description": "Tumor suppressor, genome guardian",
        "summary": (
            "This gene encodes a tumor suppressor protein containing transcriptional activation, "
            "DNA-binding, and oligomerization domains. The encoded protein responds to diverse cellular "
            "stresses to regulate expression of target genes, thereby inducing cell cycle arrest, "
            "apoptosis, senescence, DNA repair, or changes in metabolism."
        ),
        "chromosome": "17",
        "map_location": "17p13.1",
        "aliases": ["p53", "LFS1", "BCC7"],
        "other_aliases": "p53, LFS1, BCC7",
        "source": "NCBI Gene",
    },
    "KRAS": {
        "symbol": "KRAS",
        "entrez_id": "3845",
        "name": "KRAS proto-oncogene, GTPase",
        "description": "Small GTPase, RAS family oncogene",
        "summary": (
            "This gene, a Kirsten ras oncogene homolog from the mammalian ras gene family, "
            "encodes a protein that is a member of the small GTPase superfamily. Mutations in this gene "
            "are associated with pancreatic, colorectal, and lung cancers."
        ),
        "chromosome": "12",
        "map_location": "12p12.1",
        "aliases": ["KRAS2", "RASK2", "c-K-bas"],
        "other_aliases": "KRAS2, RASK2, c-K-bas",
        "source": "NCBI Gene",
    },
}


# ========== 预置 FASTA 序列 ==========
FASTA_DATABASE: Dict[str, str] = {
    "NP_005219": (  # EGFR_HUMAN
        ">NP_005219.2 epidermal growth factor receptor isoform a [Homo sapiens]\n"
        "MRPSGTAGAALLALLAALCPASRALEEKKVCQGTSNKLTQLGTFEDHFLSLQRMFNNCEVVLGNLEITYV\n"
        "KCRPKDGKDKDAELKLLGEEYVLHVNIGSALYLRDPNLDVALVQEIKYGYHNGFCEACDDYTFRTIPVRV\n"
        "DVLYAPSAPDGEPEGTCAEDLQEKNLAEIPDNVDFDLSAYLASPSGSPEEELKEYSNEHSLPYEIATVNK\n"
        "AVKPDLSSVLDDSLLSFTWYQEMRAQGQGYGSLCQALATFEYNSLLSCDEKTVTPTYVLSLQGLCTEEN\n"
        "...(truncated for test)\n"
    ),
    "NP_000537": (  # TP53_HUMAN
        ">NP_000537.3 cellular tumor antigen p53 [Homo sapiens]\n"
        "MEEPQSDPSVEPPLSQETFSDLWKLLPENNVLSPLPSQAMDDLMLSPDDIEQWFTEDPGPDEAPRMPEAA\n"
        "PVAPAPAAPTPAAPAPAPSWPLSSSVPSQKTYQGSYGFRLGFLHSGTAKSVTCTYSPALNKMFCQLAKT\n"
        "CPVQLWVDSTPPPGTRVRAMAIYKQSQHMTEVVRRCPHHERCSDSDGLAPQNLHFRAQALCNDRRRRPE\n"
        "...(truncated for test)\n"
    ),
}


class MockNcbiClient(NcbiClient):
    """Mock NCBI E-utilities 客户端

    返回预置数据，模拟网络延迟（100ms）。
    支持的数据库：PubMed / ClinVar / Gene / Protein / Nucleotide。
    """

    async def _delay(self) -> None:
        """模拟网络延迟"""
        await asyncio.sleep(0.1)

    def _match_pubmed_query(self, query: str) -> List[Dict[str, Any]]:
        """根据查询词匹配 PubMed 数据"""
        query_upper = query.upper()
        for gene, articles in PUBMED_DATABASE.items():
            if gene in query_upper:
                return articles
        return PUBMED_DATABASE["default"]

    # ========== 4 个原子方法实现 ==========

    async def esearch(
        self,
        db: str,
        term: str,
        retmax: int = 20,
        retmode: str = "json",
        sort: Optional[str] = None,
        db_session: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """esearch — 搜索 NCBI 数据库"""
        await self._delay()

        id_list: List[str] = []

        if db == "pubmed":
            articles = self._match_pubmed_query(term)
            id_list = [a["uid"] for a in articles[:retmax]]
        elif db == "clinvar":
            for gene, variants in CLINVAR_DATABASE.items():
                if gene.upper() in term.upper():
                    id_list = [v["uid"] for v in variants[:retmax]]
                    break
        elif db == "gene":
            # 提取基因符号
            for gene in GENE_INFO_DATABASE:
                if gene.upper() in term.upper():
                    id_list = [GENE_INFO_DATABASE[gene]["entrez_id"]]
                    break
        elif db in ("protein", "nucleotide"):
            # 根据 ID 直接返回（用于 FASTA 查询）
            if "NP_" in term or "NM_" in term:
                for accession in FASTA_DATABASE:
                    if accession in term:
                        id_list = [accession]
                        break

        return {
            "esearchresult": {
                "idlist": id_list,
                "count": str(len(id_list)),
                "querytranslation": term,
            }
        }

    async def esummary(
        self,
        db: str,
        ids: List[str],
        retmode: str = "json",
        db_session: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """esummary — 获取条目摘要"""
        await self._delay()

        result: Dict[str, Any] = {"result": {"uids": ids}}

        if db == "pubmed":
            for uid in ids:
                article = None
                for articles in PUBMED_DATABASE.values():
                    for a in articles:
                        if a["uid"] == uid:
                            article = a
                            break
                    if article:
                        break
                if article:
                    # 构造 NCBI esummary 兼容的返回结构
                    result["result"][uid] = {
                        "uid": uid,
                        "title": article["title"],
                        "authors": [{"name": name} for name in article["authors"]],
                        "fulljournalname": article["journal"],
                        "pubdate": article["pubdate"],
                        "abstract": article["abstract"],
                        "elocationid": article.get("doi", ""),
                        "pubtype": article.get("pubtype", []),
                        "source": article["journal"],
                    }
        elif db == "clinvar":
            for uid in ids:
                variant = None
                for variants in CLINVAR_DATABASE.values():
                    for v in variants:
                        if v["uid"] == uid:
                            variant = v
                            break
                    if variant:
                        break
                if variant:
                    result["result"][uid] = {
                        "uid": uid,
                        "title": variant["title"],
                        "clinical_significance": {
                            "description": variant["clnsig"],
                            "review_status": variant.get("review_status"),
                        },
                        "genes": [{"symbol": variant["gene"], "name": variant["gene"]}],
                        "variation_set": [{"variation_class": variant["variant_type"]}],
                    }
        elif db == "gene":
            for uid in ids:
                gene_info = None
                for g in GENE_INFO_DATABASE.values():
                    if g["entrez_id"] == uid:
                        gene_info = g
                        break
                if gene_info:
                    result["result"][uid] = {
                        "uid": uid,
                        "name": gene_info["name"],
                        "description": gene_info["description"],
                        "summary": gene_info["summary"],
                        "chromosome": gene_info["chromosome"],
                        "maplocation": gene_info["map_location"],
                        "aliases": [{"name": a} for a in gene_info["aliases"]],
                        "otheraliases": gene_info["other_aliases"],
                    }

        return result

    async def efetch(
        self,
        db: str,
        ids: List[str],
        rettype: str = "abstract",
        retmode: str = "xml",
        db_session: Optional[Any] = None,
    ) -> str:
        """efetch — 获取完整记录"""
        await self._delay()

        if db in ("protein", "nucleotide") and rettype == "fasta":
            parts = []
            for accession in ids:
                if accession in FASTA_DATABASE:
                    parts.append(FASTA_DATABASE[accession])
            return "\n".join(parts)

        # 默认返回空字符串
        return ""

    async def elink(
        self,
        dbfrom: str,
        db: str,
        id: str,
        db_session: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """elink — 获取跨库链接"""
        await self._delay()
        # Mock：返回少量示例链接
        return {
            "linksets": [
                {
                    "dbfrom": dbfrom,
                    "ids": [id],
                    "linksetdbs": [
                        {
                            "dbto": db,
                            "links": ["36000001", "36000002"],
                        }
                    ],
                }
            ]
        }

    # ========== 高层封装方法 ==========

    async def search_pubmed(
        self,
        query: str,
        retmax: int = 10,
        db_session: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """PubMed 文献检索"""
        await self._delay()
        return self._match_pubmed_query(query)[:retmax]

    async def fetch_gene_info(
        self,
        gene_symbol: str,
        db_session: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """基因信息查询"""
        await self._delay()
        symbol_upper = gene_symbol.strip().upper()
        if symbol_upper in GENE_INFO_DATABASE:
            return dict(GENE_INFO_DATABASE[symbol_upper])
        return {
            "symbol": gene_symbol,
            "entrez_id": None,
            "name": f"{gene_symbol} (未在 Mock 数据库中)",
            "description": "",
            "summary": (
                f"基因 {gene_symbol} 在 Mock 数据库中无详细注释。"
                "配置 USE_MOCK=false 并接入 NCBI 真实 API 后将获得完整信息。"
            ),
            "chromosome": "",
            "map_location": "",
            "aliases": [],
            "other_aliases": "",
            "source": "NCBI Gene",
            "note": "mock_placeholder",
        }

    async def fetch_clinvar_variants(
        self,
        gene: str,
        retmax: int = 5,
        db_session: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """ClinVar 致病变异查询"""
        await self._delay()
        gene_upper = gene.strip().upper()
        if gene_upper in CLINVAR_DATABASE:
            return [dict(v) for v in CLINVAR_DATABASE[gene_upper][:retmax]]
        return []

    async def fetch_sequences(
        self,
        ids: List[str],
        db: str = "protein",
        db_session: Optional[Any] = None,
    ) -> str:
        """FASTA 序列获取"""
        return await self.efetch(
            db=db,
            ids=ids,
            rettype="fasta",
            retmode="text",
            db_session=db_session,
        )
