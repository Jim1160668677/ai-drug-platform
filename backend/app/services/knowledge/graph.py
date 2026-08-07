"""知识图谱服务 — Neo4j PPI/通路查询"""
import logging
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


# Mock 模式下的预置 PPI 网络
MOCK_PPI_NETWORK: Dict[str, List[Dict[str, Any]]] = {
    "EGFR": [
        {"gene": "KRAS", "interaction": "activation", "score": 0.95, "evidence": "KEGG hsa04010"},
        {"gene": "BRAF", "interaction": "activation", "score": 0.92, "evidence": "KEGG hsa04010"},
        {"gene": "PIK3CA", "interaction": "activation", "score": 0.90, "evidence": "KEGG hsa04151"},
        {"gene": "JAK2", "interaction": "activation", "score": 0.75, "evidence": "Reactome"},
        {"gene": "STAT3", "interaction": "activation", "score": 0.78, "evidence": "Reactome"},
        {"gene": "ERBB2", "interaction": "heterodimerization", "score": 0.93, "evidence": "Reactome"},
        {"gene": "ERBB3", "interaction": "heterodimerization", "score": 0.85, "evidence": "Reactome"},
        {"gene": "GRB2", "interaction": "binding", "score": 0.88, "evidence": "BioGRID"},
        {"gene": "SOS1", "interaction": "binding", "score": 0.82, "evidence": "BioGRID"},
    ],
    "KRAS": [
        {"gene": "BRAF", "interaction": "activation", "score": 0.96, "evidence": "KEGG"},
        {"gene": "RAF1", "interaction": "activation", "score": 0.94, "evidence": "KEGG"},
        {"gene": "MAP2K1", "interaction": "activation", "score": 0.90, "evidence": "KEGG"},
        {"gene": "PIK3CA", "interaction": "activation", "score": 0.80, "evidence": "KEGG"},
        {"gene": "EGFR", "interaction": "downstream_of", "score": 0.95, "evidence": "KEGG"},
    ],
    "TP53": [
        {"gene": "MDM2", "interaction": "regulation", "score": 0.97, "evidence": "KEGG hsa04115"},
        {"gene": "BAX", "interaction": "activation", "score": 0.92, "evidence": "KEGG"},
        {"gene": "CDKN1A", "interaction": "activation", "score": 0.90, "evidence": "KEGG"},
        {"gene": "BCL2", "interaction": "inhibition", "score": 0.85, "evidence": "KEGG"},
        {"gene": "ATM", "interaction": "phosphorylation", "score": 0.88, "evidence": "Reactome"},
    ],
    "B7H3": [
        {"gene": "CD28", "interaction": "family", "score": 0.65, "evidence": "Reactome"},
        {"gene": "PD-L1", "interaction": "co_expression", "score": 0.70, "evidence": "literature"},
    ],
    "FAP": [
        {"gene": "DPP4", "interaction": "family", "score": 0.78, "evidence": "UniProt"},
        {"gene": "COL1A1", "interaction": "substrate", "score": 0.85, "evidence": "literature"},
        {"gene": "ACTA2", "interaction": "co_expression", "score": 0.80, "evidence": "CAF marker"},
    ],
}


# Mock 模式下的用户基因型节点存储（不污染公共 PPI 图谱）
# Key 格式："{owner_id}:{rsid}" → 节点属性 dict
MOCK_USER_GENOTYPES: Dict[str, Dict[str, Any]] = {}


class KnowledgeGraph:
    """Neo4j 知识图谱封装 — Mock 模式下使用预置 PPI"""

    def __init__(self):
        self._driver = None

    def _get_driver(self):
        if self._driver is not None:
            return self._driver

        if settings.is_mock:
            return None

        try:
            from neo4j import AsyncGraphDatabase
            self._driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            )
            return self._driver
        except Exception as e:
            logger.warning(f"Neo4j 连接失败，降级为 Mock PPI: {e}")
            return None

    async def get_neighbors(
        self, gene_symbol: str, depth: int = 1
    ) -> Dict[str, Any]:
        """获取基因的 PPI 邻居"""
        symbol = gene_symbol.strip().upper()
        driver = self._get_driver()

        if driver is None:
            return self._mock_neighbors(symbol, depth)

        try:
            query = (
                "MATCH (g:Gene {symbol: $gene})-[:INTERACTS*1.." + str(depth) + "]-(neighbor) "
                "RETURN neighbor.symbol AS gene, neighbor.name AS name"
            )
            async with driver.session() as session:
                result = await session.run(query, gene=symbol)
                nodes = []
                async for record in result:
                    nodes.append({"gene": record["gene"], "name": record["name"]})
            return {"root": symbol, "neighbors": nodes, "depth": depth, "source": "neo4j"}
        except Exception as e:
            logger.warning(f"Neo4j 查询失败，降级: {e}")
            return self._mock_neighbors(symbol, depth)

    def _mock_neighbors(self, symbol: str, depth: int) -> Dict[str, Any]:
        neighbors = list(MOCK_PPI_NETWORK.get(symbol, []))
        # 深度 > 1 时简单扩展一层
        if depth > 1:
            extended = list(neighbors)
            seen = {symbol} | {n["gene"] for n in neighbors}
            for n in neighbors:
                for n2 in MOCK_PPI_NETWORK.get(n["gene"], []):
                    if n2["gene"] not in seen:
                        extended.append({**n2, "via": n["gene"]})
                        seen.add(n2["gene"])
            neighbors = extended
        return {
            "root": symbol,
            "neighbors": neighbors,
            "depth": depth,
            "source": "mock_ppi",
        }

    async def find_path(
        self, gene_a: str, gene_b: str, max_depth: int = 4
    ) -> Dict[str, Any]:
        """查找两基因间的通路路径"""
        # Mock 简化：直接看是否在同一网络
        a_neighbors = {n["gene"] for n in MOCK_PPI_NETWORK.get(gene_a.upper(), [])}
        if gene_b.upper() in a_neighbors:
            return {
                "from": gene_a.upper(),
                "to": gene_b.upper(),
                "paths": [[gene_a.upper(), gene_b.upper()]],
                "length": 1,
                "source": "mock_ppi",
            }
        # 二阶路径
        for mid in a_neighbors:
            mid_neighbors = {n["gene"] for n in MOCK_PPI_NETWORK.get(mid, [])}
            if gene_b.upper() in mid_neighbors:
                return {
                    "from": gene_a.upper(),
                    "to": gene_b.upper(),
                    "paths": [[gene_a.upper(), mid, gene_b.upper()]],
                    "length": 2,
                    "source": "mock_ppi",
                }
        return {
            "from": gene_a.upper(),
            "to": gene_b.upper(),
            "paths": [],
            "length": 0,
            "source": "mock_ppi",
            "note": f"在 Mock PPI 中未找到 {gene_a}-{gene_b} 路径（≤{max_depth}）",
        }

    async def get_pathway_genes(self, pathway_id: str) -> Dict[str, Any]:
        """获取指定通路的所有基因"""
        mock_pathways = {
            "hsa04010": {"name": "MAPK signaling pathway", "genes": ["EGFR", "KRAS", "BRAF", "RAF1", "MAP2K1", "MAPK1", "MAPK3"]},
            "hsa04012": {"name": "ErbB signaling pathway", "genes": ["EGFR", "ERBB2", "ERBB3", "ERBB4", "GRB2", "SOS1", "KRAS"]},
            "hsa04151": {"name": "PI3K-Akt signaling pathway", "genes": ["EGFR", "PIK3CA", "AKT1", "MTOR", "PTEN"]},
            "hsa04115": {"name": "p53 signaling pathway", "genes": ["TP53", "MDM2", "BAX", "CDKN1A", "BCL2"]},
        }
        if pathway_id in mock_pathways:
            return {**mock_pathways[pathway_id], "pathway_id": pathway_id, "source": "mock_kegg"}
        return {"pathway_id": pathway_id, "genes": [], "source": "mock_kegg", "note": "通路未在 Mock 数据库中"}

    async def add_genome_context(
        self, personal_genome_id: UUID, db: AsyncSession
    ) -> Dict[str, Any]:
        """将个人基因组变异加入知识图谱节点（标记 is_user_genotype=True）

        不污染公共图谱：用户级节点用前缀 `user:{owner_id}:{rsid}` 区分。
        Mock 模式下写入内存 MOCK_USER_GENOTYPES 字典；Neo4j 模式下写入 user_genotype 标签节点。
        """
        from app.models.personal_genome import PersonalGenome, GenotypeMatch
        from app.models.snp_locus import SnpLocus

        # 1. 加载基因组（校验存在）
        genome = await db.get(PersonalGenome, personal_genome_id)
        if not genome:
            return {
                "personal_genome_id": str(personal_genome_id),
                "user_nodes_added": 0,
                "error": "genome_not_found",
            }

        owner_id = str(genome.owner_id)

        # 2. 加载所有 GenotypeMatch + 关联 SnpLocus
        stmt = (
            select(GenotypeMatch, SnpLocus)
            .join(SnpLocus, GenotypeMatch.snp_locus_id == SnpLocus.id)
            .where(GenotypeMatch.personal_genome_id == personal_genome_id)
        )
        result = await db.execute(stmt)
        rows = result.all()

        # 3. 写入 MOCK_USER_GENOTYPES（仅风险位点）
        user_nodes_added = 0
        for match, locus in rows:
            if not match.is_risk:
                continue
            key = f"{owner_id}:{locus.rsid}"
            MOCK_USER_GENOTYPES[key] = {
                "rsid": locus.rsid,
                "gene_symbol": locus.gene_symbol,
                "user_genotype": match.user_genotype,
                "is_risk": True,
                "risk_score": match.risk_score,
                "effect_allele": locus.effect_allele,
                "risk_genotype": locus.risk_genotype,
                "effect_size": locus.effect_size,
                "owner_id": owner_id,
                "personal_genome_id": str(personal_genome_id),
                "source": "user_upload",
            }
            user_nodes_added += 1

        # 4. Neo4j 模式下也写入图数据库（best-effort，不阻塞主流程）
        driver = self._get_driver()
        if driver is not None:
            try:
                async with driver.session() as session:
                    for match, locus in rows:
                        if not match.is_risk:
                            continue
                        await session.run(
                            "MERGE (n:UserGenotype {rsid: $rsid, owner_id: $owner_id}) "
                            "SET n.gene = $gene, n.genotype = $genotype, n.is_risk = true",
                            rsid=locus.rsid,
                            owner_id=owner_id,
                            gene=locus.gene_symbol,
                            genotype=match.user_genotype,
                        )
            except Exception as e:
                logger.warning(f"Neo4j 写入 user_genotype 失败（不影响 Mock 缓存）: {e}")

        return {
            "personal_genome_id": str(personal_genome_id),
            "user_nodes_added": user_nodes_added,
            "total_matches": len(rows),
            "source": "mock" if driver is None else "neo4j",
        }

    def get_user_genotypes(self, owner_id: str) -> List[Dict[str, Any]]:
        """读取用户级基因型节点（Mock 模式从内存字典过滤）

        Args:
            owner_id: 用户 ID 字符串
        Returns:
            该用户的所有风险基因型节点列表
        """
        prefix = f"{owner_id}:"
        return [v for k, v in MOCK_USER_GENOTYPES.items() if k.startswith(prefix)]


_graph_singleton: KnowledgeGraph = None


def get_knowledge_graph() -> KnowledgeGraph:
    global _graph_singleton
    if _graph_singleton is None:
        _graph_singleton = KnowledgeGraph()
    return _graph_singleton
