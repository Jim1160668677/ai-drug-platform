"""数据血缘追踪服务 — 记录和查询数据流转关系

使用 BFS 迭代遍历（兼容 SQLite + PostgreSQL），支持上下游查询和完整 DAG 构建。
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_lineage import DataLineage

logger = logging.getLogger(__name__)

# 最大遍历深度（安全上限，防止无限循环）
_MAX_DEPTH = 10


class LineageTracker:
    """数据血缘追踪器"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(
        self,
        project_id: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        transformation: str,
        meta: Optional[dict] = None,
        created_by: Optional[str] = None,
    ) -> DataLineage:
        """记录一条血缘关系"""
        lineage = DataLineage(
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            transformation=transformation,
            transformation_meta=meta,
            created_by=created_by,
        )
        self.db.add(lineage)
        await self.db.flush()
        return lineage

    async def get_upstream(
        self,
        project_id: str,
        node_type: str,
        node_id: str,
        depth: int = 3,
    ) -> List[Dict[str, Any]]:
        """查询节点的上游链路（谁产生了这个节点）

        Returns: 上游节点列表，按距离排序（直接上游在前）
        """
        safe_depth = min(depth, _MAX_DEPTH)
        visited: set = set()
        results: List[Dict[str, Any]] = []
        queue = [(node_type, node_id, 0)]

        while queue:
            current_type, current_id, current_depth = queue.pop(0)
            if current_depth >= safe_depth:
                continue
            node_key = f"{current_type}:{current_id}"
            if node_key in visited:
                continue
            visited.add(node_key)

            # 查找指向当前节点的所有血缘记录
            stmt = select(DataLineage).where(
                DataLineage.project_id == project_id,
                DataLineage.target_type == current_type,
                DataLineage.target_id == current_id,
            )
            rows = (await self.db.execute(stmt)).scalars().all()
            for row in rows:
                results.append({
                    "node_type": row.source_type,
                    "node_id": row.source_id,
                    "transformation": row.transformation,
                    "depth": current_depth + 1,
                    "meta": row.transformation_meta,
                })
                queue.append((row.source_type, row.source_id, current_depth + 1))

        return results

    async def get_downstream(
        self,
        project_id: str,
        node_type: str,
        node_id: str,
        depth: int = 3,
    ) -> List[Dict[str, Any]]:
        """查询节点的下游链路（这个节点产生了什么）

        Returns: 下游节点列表，按距离排序
        """
        safe_depth = min(depth, _MAX_DEPTH)
        visited: set = set()
        results: List[Dict[str, Any]] = []
        queue = [(node_type, node_id, 0)]

        while queue:
            current_type, current_id, current_depth = queue.pop(0)
            if current_depth >= safe_depth:
                continue
            node_key = f"{current_type}:{current_id}"
            if node_key in visited:
                continue
            visited.add(node_key)

            # 查找当前节点指向的所有血缘记录
            stmt = select(DataLineage).where(
                DataLineage.project_id == project_id,
                DataLineage.source_type == current_type,
                DataLineage.source_id == current_id,
            )
            rows = (await self.db.execute(stmt)).scalars().all()
            for row in rows:
                results.append({
                    "node_type": row.target_type,
                    "node_id": row.target_id,
                    "transformation": row.transformation,
                    "depth": current_depth + 1,
                    "meta": row.transformation_meta,
                })
                queue.append((row.target_type, row.target_id, current_depth + 1))

        return results

    async def get_dag(
        self,
        project_id: str,
        node_type: str,
        node_id: str,
        depth: int = 3,
    ) -> Dict[str, Any]:
        """获取以指定节点为中心的完整 DAG（上游 + 下游）

        Returns: {nodes: [{type, id, depth, direction}], edges: [{source, target, transformation}]}
        """
        upstream = await self.get_upstream(project_id, node_type, node_id, depth)
        downstream = await self.get_downstream(project_id, node_type, node_id, depth)

        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []

        # 中心节点
        center_key = f"{node_type}:{node_id}"
        nodes[center_key] = {
            "type": node_type,
            "id": node_id,
            "depth": 0,
            "direction": "center",
        }

        # 上游节点和边
        for item in upstream:
            key = f"{item['node_type']}:{item['node_id']}"
            if key not in nodes:
                nodes[key] = {
                    "type": item["node_type"],
                    "id": item["node_id"],
                    "depth": item["depth"],
                    "direction": "upstream",
                }
            edges.append({
                "source": key,
                "target": "",  # 填充在下面
                "transformation": item["transformation"],
                "meta": item.get("meta"),
            })

        # 下游节点和边
        for item in downstream:
            key = f"{item['node_type']}:{item['node_id']}"
            if key not in nodes:
                nodes[key] = {
                    "type": item["node_type"],
                    "id": item["node_id"],
                    "depth": item["depth"],
                    "direction": "downstream",
                }
            edges.append({
                "source": "",
                "target": key,
                "transformation": item["transformation"],
                "meta": item.get("meta"),
            })

        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
