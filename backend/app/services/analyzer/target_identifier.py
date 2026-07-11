"""靶点发现引擎 — 子系统B 核心

流程：数据集 → 提取变异/差异基因 → 变异注释 → 基因查询 → PPI 扩展 → 评分分级 → 写库
"""
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    get_gene_client,
    get_variant_client,
    get_chembl_client,
    get_llm_client,
)
from app.models.dataset import Dataset
from app.models.target import Target, EvidenceGrade

logger = logging.getLogger(__name__)


# 已知的关键癌基因/抑癌基因映射（用于从 parsed_summary 中识别变异/差异基因）
KNOWN_TARGET_GENES = {
    "EGFR", "KRAS", "BRAF", "PIK3CA", "TP53", "PTEN", "ALK", "ROS1", "MET",
    "ERBB2", "ERBB3", "BRAF", "NRAS", "MAP2K1", "B7H3", "CD276", "FAP",
    "PD-L1", "CD274", "CTLA4", "VEGFA", "FGFR1", "FGFR2", "FGFR3", "RET",
}


class TargetIdentifier:
    """靶点发现引擎 — 从数据集中识别候选靶点并分级"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def discover(
        self,
        project_id: UUID,
        dataset_id: Optional[UUID] = None,
        tier: str = "fast_screen",
        hypothesis_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """靶点发现主流程

        Args:
            project_id: 项目 ID
            dataset_id: 可选，指定数据集；不指定则分析项目所有数据集
            tier: fast_screen / deep_insight
            hypothesis_id: 关联假设 ID（多假设并行场景）
        Returns:
            {targets: [...], count, tier, duration_sec}
        """
        start = time.time()

        # 1. 查询项目的数据集
        stmt = select(Dataset).where(Dataset.project_id == project_id)
        if dataset_id:
            stmt = stmt.where(Dataset.id == dataset_id)
        result = await self.db.execute(stmt)
        datasets = result.scalars().all()

        if not datasets:
            return {
                "targets": [],
                "count": 0,
                "tier": tier,
                "duration_sec": round(time.time() - start, 3),
                "message": "项目无可用数据集",
            }

        # 2. 从 parsed_summary 提取变异 / 差异基因
        variants: List[str] = []  # 形如 "chr7:55259515:T>A"
        diff_genes: List[str] = []  # 形如 "EGFR"

        for ds in datasets:
            summary = ds.parsed_summary or {}
            # VCF 数据 — 直接含 variant 列表
            for v in summary.get("variants", []) or []:
                if isinstance(v, str):
                    variants.append(v)
                elif isinstance(v, dict) and v.get("query"):
                    variants.append(v["query"])
            # scRNA-seq / RNA-seq — 含 top_markers / top_genes
            for marker_cluster in (summary.get("top_markers_per_cluster") or {}).values():
                if not isinstance(marker_cluster, list):
                    continue
                for m in marker_cluster:
                    if isinstance(m, dict) and m.get("gene"):
                        diff_genes.append(m["gene"])
            for g in summary.get("top_genes", []) or []:
                if isinstance(g, dict) and g.get("symbol"):
                    diff_genes.append(g["symbol"])
                elif isinstance(g, str):
                    diff_genes.append(g)

        # 3. 变异注释（如果存在变异）
        variant_annotations: List[Dict[str, Any]] = []
        if variants:
            try:
                vc = get_variant_client()
                variant_annotations = await vc.query_batch(variants[:50])  # 限制 50 条
            except Exception as e:
                logger.warning(f"变异注释失败: {e}")

        # 从变异注释中提取基因
        for va in variant_annotations:
            if va.get("gene"):
                diff_genes.append(va["gene"])

        # 4. 去重 + 过滤已知癌基因
        unique_genes = list({g.upper() for g in diff_genes if g})
        target_candidates = [g for g in unique_genes if g in KNOWN_TARGET_GENES]
        # 加上变异注释中的基因（即使不在已知列表，作为新候选）
        for g in unique_genes:
            if g not in target_candidates:
                target_candidates.append(g)
        target_candidates = target_candidates[:30]  # 限制候选数

        if not target_candidates:
            # 无候选基因时，使用项目癌种的默认基因
            target_candidates = ["EGFR", "TP53", "KRAS"]

        # 5. 并发查询基因信息 + PPI 扩展
        gene_infos: Dict[str, Dict] = {}
        gc = get_gene_client()
        for gene in target_candidates:
            try:
                info = await gc.query(gene)
                gene_infos[gene] = info
            except Exception as e:
                logger.warning(f"基因 {gene} 查询失败: {e}")
                gene_infos[gene] = {"symbol": gene, "name": gene}

        # PPI 扩展（使用 KnowledgeGraph）
        ppi_neighbors: Dict[str, List] = {}
        try:
            from app.services.knowledge.graph import get_knowledge_graph
            kg = get_knowledge_graph()
            for gene in target_candidates[:10]:  # 限制查询数
                neighbors = await kg.get_neighbors(gene, depth=1)
                ppi_neighbors[gene] = neighbors.get("neighbors", [])
        except Exception as e:
            logger.warning(f"PPI 扩展失败: {e}")

        # 6. 已获批药物查询（决定 evidence_grade）
        approved_drugs_map: Dict[str, List] = {}
        try:
            cc = get_chembl_client()
            for gene in target_candidates[:10]:
                drugs = await cc.find_approved_drugs(gene)
                approved_drugs_map[gene] = drugs
        except Exception as e:
            logger.warning(f"药物查询失败: {e}")

        # 6.5 PubMed 文献检索（spec 要求 4 个客户端：MyGene/ChEMBL/PubMed/MyVariant）
        pubmed_counts: Dict[str, int] = {}
        try:
            for gene in target_candidates[:10]:
                count = await self._query_pubmed(gene)
                pubmed_counts[gene] = count
        except Exception as e:
            logger.warning(f"PubMed 检索失败: {e}")

        # 7. 计算每个靶点的 confidence_score + evidence_grade
        targets_data: List[Dict[str, Any]] = []
        for gene in target_candidates:
            info = gene_infos.get(gene, {})
            variants_for_gene = [v for v in variant_annotations if v.get("gene", "").upper() == gene]
            neighbors = ppi_neighbors.get(gene, [])
            approved = approved_drugs_map.get(gene, [])
            pubmed_count = pubmed_counts.get(gene, 0)

            confidence = self._compute_confidence(
                gene=gene,
                variants=variants_for_gene,
                neighbors=neighbors,
                approved_drugs=approved,
                diff_genes_set=set(unique_genes),
            )
            # PubMed 文献数加权到置信度（文献越多，证据越充分）
            if pubmed_count > 0:
                confidence = min(1.0, confidence + min(0.1, pubmed_count / 1000))
            grade = self._assign_grade(approved, info, neighbors)

            target_data = {
                "gene_symbol": gene,
                "gene_name": info.get("name"),
                "evidence_grade": grade,
                "confidence_score": round(confidence, 3),
                "source": "multi_omics_integration",
                "variant_info": variants_for_gene[:3] if variants_for_gene else None,
                "annotation": {
                    "entrez_id": info.get("entrez_id"),
                    "uniprot_id": info.get("uniprot_id"),
                    "location": info.get("location"),
                    "summary": info.get("summary"),
                    "gene_type": info.get("gene_type"),
                },
                "pathway": {
                    "pathways": info.get("pathways", []),
                    "ppi_neighbors": neighbors[:10],
                    "ppi_count": len(neighbors),
                },
                "approved_drugs": approved[:5],
                "analysis_tier": tier,
            }
            targets_data.append(target_data)

        # 按置信度排序
        targets_data.sort(key=lambda x: x["confidence_score"], reverse=True)

        # 8. 写入 Target 表
        for td in targets_data[:20]:  # 最多写 20 个
            existing = await self.db.execute(
                select(Target).where(Target.project_id == project_id)
                .where(Target.gene_symbol == td["gene_symbol"])
            )
            if existing.scalar_one_or_none():
                continue

            target = Target(
                project_id=project_id,
                gene_symbol=td["gene_symbol"],
                gene_name=td.get("gene_name"),
                evidence_grade=td["evidence_grade"],
                confidence_score=td["confidence_score"],
                source=td["source"],
                variant_info=td.get("variant_info"),
                annotation=td.get("annotation"),
                pathway=td.get("pathway"),
                approved_drugs=td.get("approved_drugs"),
                analysis_tier=tier,
            )
            self.db.add(target)

        await self.db.flush()

        # 9. deep_insight 模式 — 调 LLM 生成深度分析
        if tier == "deep_insight":
            try:
                llm = get_llm_client()
                for td in targets_data[:5]:  # 前 5 个靶点深度分析
                    prompt = self._build_deep_analysis_prompt(td)
                    response = await llm.chat([
                        {"role": "system", "content": "你是精准医学专家，请基于变异注释、PPI 网络、已知药物信息进行深度靶点分析。"},
                        {"role": "user", "content": prompt},
                    ])
                    td["deep_analysis"] = response.get("content")
                    td["references"] = response.get("references", [])
            except Exception as e:
                logger.warning(f"深度分析失败: {e}")

        duration = round(time.time() - start, 3)
        return {
            "targets": targets_data,
            "count": len(targets_data),
            "tier": tier,
            "duration_sec": duration,
            "datasets_analyzed": len(datasets),
            "variants_annotated": len(variant_annotations),
        }

    def _compute_confidence(
        self,
        gene: str,
        variants: List[Dict],
        neighbors: List[Dict],
        approved_drugs: List[Dict],
        diff_genes_set: set,
    ) -> float:
        """计算靶点置信度（0-1）

        维度：
        - 变异致病性（30%）：含 Pathogenic 变异加分
        - 差异表达（20%）：在差异基因集合中加分
        - PPI 中心性（25%）：邻居数越多分越高
        - 已知药物（25%）：有获批药物加分
        """
        score = 0.0

        # 变异致病性
        if variants:
            pathogenic_count = sum(
                1 for v in variants
                if "pathogenic" in ((v.get("clinvar") or {}).get("clnsig") or "").lower()
            )
            score += min(0.30, 0.10 + 0.10 * pathogenic_count)
        else:
            score += 0.05

        # 差异表达
        if gene in diff_genes_set:
            score += 0.20
        else:
            score += 0.05

        # PPI 中心性
        ppi_count = len(neighbors)
        score += min(0.25, 0.05 + 0.02 * ppi_count)

        # 已知药物
        if approved_drugs:
            score += min(0.25, 0.10 + 0.05 * len(approved_drugs))
        else:
            score += 0.03

        return min(score, 1.0)

    def _assign_grade(
        self,
        approved_drugs: List[Dict],
        gene_info: Dict,
        neighbors: List[Dict],
    ) -> str:
        """分配证据等级 I-IV"""
        if approved_drugs:
            return EvidenceGrade.LEVEL_I
        if gene_info.get("pathways") or len(neighbors) >= 5:
            return EvidenceGrade.LEVEL_II
        if gene_info.get("summary") and gene_info.get("summary") != "":
            return EvidenceGrade.LEVEL_III
        return EvidenceGrade.LEVEL_IV

    def _build_deep_analysis_prompt(self, target_data: Dict) -> str:
        """构建深度分析 prompt"""
        gene = target_data["gene_symbol"]
        variants = target_data.get("variant_info") or []
        neighbors = (target_data.get("pathway") or {}).get("ppi_neighbors", [])
        approved = target_data.get("approved_drugs") or []

        variant_str = "\n".join(
            f"- {v.get('query', 'unknown')}: {v.get('hgvs_p', 'unknown')} "
            f"({(v.get('clinvar') or {}).get('clnsig', 'unknown')})"
            for v in variants[:5]
        ) or "无已知变异"

        neighbor_str = ", ".join(n.get("gene", "?") for n in neighbors[:10]) or "无"

        drug_str = ", ".join(d.get("name", "?") for d in approved[:5]) or "无获批药物"

        return (
            f"请深度分析靶点 {gene}：\n\n"
            f"## 已知变异\n{variant_str}\n\n"
            f"## PPI 邻居\n{neighbor_str}\n\n"
            f"## 已获批药物\n{drug_str}\n\n"
            f"## 证据等级\n{target_data.get('evidence_grade')}\n\n"
            "请从以下角度分析：\n"
            "1. 致病机制（变异如何影响蛋白功能）\n"
            "2. 通路角色（在信号通路中的位置）\n"
            "3. 治疗策略（已有/在研/潜在疗法）\n"
            "4. 耐药风险\n"
            "5. 推荐方案（含剂量与证据来源）"
        )

    async def _query_pubmed(self, gene: str, max_results: int = 100) -> int:
        """PubMed E-utilities 文献检索

        通过 NCBI ESearch API 查询基因相关文献数量。
        使用 httpx.AsyncClient 异步请求，避免阻塞事件循环。

        Args:
            gene: 基因符号（如 EGFR）
            max_results: 最大返回数（用于计数）
        Returns:
            文献数量（0 表示查询失败或无结果）
        """
        try:
            import httpx

            # ESearch API
            base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            query = f"{gene}[Gene] AND (cancer[Title/Abstract] OR tumor[Title/Abstract] OR oncolog*[Title/Abstract])"
            params = {
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
            }

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    base_url, params=params,
                    headers={"User-Agent": "PrecisionDrug/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()

            count = int(data.get("esearchresult", {}).get("count", 0))
            logger.debug(f"PubMed {gene}: {count} 篇文献")
            return count
        except Exception as e:
            logger.debug(f"PubMed 查询失败（降级为 0）: {e}")
            return 0
