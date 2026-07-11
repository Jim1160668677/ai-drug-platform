"""知识图谱服务 — Neo4j PPI/通路查询"""
import logging
from typing import Any, Dict, List

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


_graph_singleton: KnowledgeGraph = None


def get_knowledge_graph() -> KnowledgeGraph:
    global _graph_singleton
    if _graph_singleton is None:
        _graph_singleton = KnowledgeGraph()
    return _graph_singleton
