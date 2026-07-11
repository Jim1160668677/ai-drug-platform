"""网络建模器 — PPI 网络分析（P2: PyG GraphSAGE）"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class NetworkModeler:
    """PPI 网络建模器 — 识别关键 hub 节点"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def analyze_ppi(
        self,
        gene_list: List[str],
        max_depth: int = 1,
    ) -> Dict[str, Any]:
        """分析 PPI 网络

        Args:
            gene_list: 种子基因列表
            max_depth: 扩展深度
        Returns:
            {nodes, edges, hub_genes, embedding_dim}
        """
        # 1. 构建网络（使用 KnowledgeGraph）
        from app.services.knowledge.graph import get_knowledge_graph
        kg = get_knowledge_graph()

        nodes_set = set(gene_list)
        edges: List[Dict] = []
        all_neighbors: Dict[str, List] = {}

        for gene in gene_list:
            neighbors_data = await kg.get_neighbors(gene, depth=max_depth)
            neighbors = neighbors_data.get("neighbors", [])
            all_neighbors[gene] = neighbors
            for n in neighbors:
                neighbor_gene = n.get("gene")
                if neighbor_gene:
                    nodes_set.add(neighbor_gene)
                    edges.append({
                        "source": gene,
                        "target": neighbor_gene,
                        "interaction": n.get("interaction"),
                        "score": n.get("score"),
                        "evidence": n.get("evidence"),
                    })

        nodes = [{"id": g, "label": g} for g in sorted(nodes_set)]

        # 2. 计算 hub 基因（按 degree 排序）
        degree_map: Dict[str, int] = {g: 0 for g in nodes_set}
        for e in edges:
            degree_map[e["source"]] = degree_map.get(e["source"], 0) + 1
            degree_map[e["target"]] = degree_map.get(e["target"], 0) + 1

        hub_genes = sorted(degree_map.items(), key=lambda x: x[1], reverse=True)[:10]
        hub_genes_list = [{"gene": g, "degree": d} for g, d in hub_genes]

        # 3. 尝试 PyG GraphSAGE 嵌入（P2）
        embedding_dim = 0
        try:
            import torch
            from torch_geometric.nn import SAGEConv
            embedding_dim = await self._compute_sage_embeddings(nodes, edges)
        except ImportError:
            logger.info("PyG 未安装，跳过 GraphSAGE 嵌入（P2 功能）")
        except Exception as e:
            logger.warning(f"GraphSAGE 嵌入失败: {e}")

        return {
            "nodes": nodes,
            "edges": edges,
            "hub_genes": hub_genes_list,
            "embedding_dim": embedding_dim,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "model": "graph_sage" if embedding_dim > 0 else "degree_based",
            "phase": "P2" if embedding_dim > 0 else "P0",
        }

    async def predict_synergy(
        self,
        target_pairs: List[tuple],
        network: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """预测靶点协同效应

        基于网络路径距离和共同邻居数量评估靶点对的协同潜力。

        Args:
            target_pairs: [("gene_a", "gene_b"), ...] 靶点对列表
            network: 预构建的网络（来自 analyze_ppi）；若为 None 则现场构建
        Returns:
            {"predictions": [{"pair", "synergy_score", "shared_neighbors", "path_distance"}],
             "model": "path_based"}
        """
        # 1. 准备网络
        if network is None:
            all_genes = list({g for pair in target_pairs for g in pair})
            network = await self.analyze_ppi(all_genes, max_depth=1)

        # 构建邻接表
        adj: Dict[str, set] = {}
        for edge in network.get("edges", []):
            src, dst = edge.get("source"), edge.get("target")
            if src and dst:
                adj.setdefault(src, set()).add(dst)
                adj.setdefault(dst, set()).add(src)

        predictions = []
        for gene_a, gene_b in target_pairs:
            neighbors_a = adj.get(gene_a, set())
            neighbors_b = adj.get(gene_b, set())
            shared = neighbors_a & neighbors_b
            # 协同评分：共同邻居越多 + 路径越短 → 协同潜力越高
            shared_score = len(shared) / max(1, len(neighbors_a | neighbors_b))
            # 路径距离（BFS，最多 4 跳）
            distance = self._bfs_distance(adj, gene_a, gene_b, max_depth=4)
            distance_score = 1.0 / max(1, distance) if distance > 0 else 0.0
            synergy = round(0.6 * shared_score + 0.4 * distance_score, 4)
            predictions.append({
                "pair": [gene_a, gene_b],
                "synergy_score": synergy,
                "shared_neighbors": sorted(list(shared))[:10],
                "shared_count": len(shared),
                "path_distance": distance,
            })

        predictions.sort(key=lambda x: x["synergy_score"], reverse=True)
        return {
            "predictions": predictions,
            "model": "path_based",
            "total_pairs": len(predictions),
            "high_synergy": sum(1 for p in predictions if p["synergy_score"] > 0.3),
        }

    @staticmethod
    def _bfs_distance(
        adj: Dict[str, set],
        start: str,
        target: str,
        max_depth: int = 4,
    ) -> int:
        """BFS 计算两节点间最短路径距离"""
        if start == target:
            return 0
        if start not in adj or target not in adj:
            return -1
        visited = {start}
        queue = [(start, 0)]
        while queue:
            node, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for neighbor in adj.get(node, set()):
                if neighbor == target:
                    return depth + 1
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
        return -1

    async def _compute_sage_embeddings(
        self,
        nodes: List[Dict],
        edges: List[Dict],
    ) -> int:
        """使用 GraphSAGE 计算节点嵌入（P2）

        Returns:
            embedding_dim（0 表示未计算）
        """
        try:
            import torch
            from torch_geometric.data import Data
            from torch_geometric.nn import SAGEConv

            if not edges or len(nodes) < 5:
                return 0

            # 构建节点索引
            node_idx = {n["id"]: i for i, n in enumerate(nodes)}

            # 构建边索引
            src = [node_idx[e["source"]] for e in edges if e["source"] in node_idx and e["target"] in node_idx]
            dst = [node_idx[e["target"]] for e in edges if e["source"] in node_idx and e["target"] in node_idx]
            if not src:
                return 0

            edge_index = torch.tensor([src + dst, dst + src], dtype=torch.long)
            x = torch.eye(len(nodes), dtype=torch.float)  # one-hot 特征

            data = Data(x=x, edge_index=edge_index)

            # 2 层 GraphSAGE
            conv1 = SAGEConv(len(nodes), 64)
            conv2 = SAGEConv(64, 32)
            with torch.no_grad():
                h = conv1(data.x, data.edge_index).relu()
                h = conv2(h, data.edge_index)

            return h.size(1)  # 32
        except Exception as e:
            logger.warning(f"SAGE 嵌入计算失败: {e}")
            return 0
