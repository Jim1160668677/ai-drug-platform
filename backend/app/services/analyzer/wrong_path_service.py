"""此路不通规避服务 — 基于失败知识库给出规避建议"""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID as UUIDType

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class WrongPathAvoider:
    """失败路径规避器

    基于 FailureKnowledge 表中沉淀的负结果，在设计新实验/假设时
    查询历史失败记录，给出规避建议，避免重蹈覆辙。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def query_failures(
        self,
        project_id: UUIDType,
        target_id: Optional[UUIDType] = None,
        molecule_id: Optional[UUIDType] = None,
    ) -> List[Dict[str, Any]]:
        """查询项目下的失败记录，返回规避建议列表

        Args:
            project_id: 项目 ID
            target_id: 可选，靶点 ID 过滤
            molecule_id: 可选，分子 ID 过滤

        Returns:
            [
                {
                    "failure_id": str,
                    "failure_reason": str,
                    "wrong_path_proof": str,
                    "is_high_confidence": bool,
                    "failure_count": int,
                    "target_id": str | None,
                    "molecule_id": str | None,
                    "suggestion": str,
                },
                ...
            ]
        """
        from app.models.failure_knowledge import FailureKnowledge

        stmt = select(FailureKnowledge).where(
            FailureKnowledge.project_id == project_id
        )

        if target_id is not None:
            stmt = stmt.where(FailureKnowledge.target_id == target_id)
        if molecule_id is not None:
            stmt = stmt.where(FailureKnowledge.molecule_id == molecule_id)

        stmt = stmt.order_by(FailureKnowledge.failure_count.desc())

        result = await self.db.execute(stmt)
        records = result.scalars().all()

        suggestions: List[Dict[str, Any]] = []
        for record in records:
            suggestion = self._build_suggestion(record)
            suggestions.append({
                "failure_id": str(record.id),
                "failure_reason": record.failure_reason,
                "wrong_path_proof": record.wrong_path_proof,
                "is_high_confidence": record.is_high_confidence or False,
                "failure_count": record.failure_count or 1,
                "target_id": str(record.target_id) if record.target_id else None,
                "molecule_id": str(record.molecule_id) if record.molecule_id else None,
                "suggestion": suggestion,
            })

        return suggestions

    def should_avoid(self, similarity_score: float, high_confidence_threshold: float = 0.7) -> bool:
        """根据相似度和置信度阈值判定是否应规避某条路径

        Args:
            similarity_score: 0-1 相似度（与历史失败的参数/结构相似程度）
            high_confidence_threshold: 高置信度阈值，默认 0.7

        Returns:
            True 表示应规避，False 表示可尝试
        """
        if similarity_score >= high_confidence_threshold:
            return True
        return False

    def _build_suggestion(self, record) -> str:
        """根据失败记录构建人类可读的规避建议"""
        reason_map = {
            "contamination": "样本污染",
            "concentration": "浓度不合适",
            "protocol_degradation": "方案降解/过期",
            "equipment_malfunction": "设备故障",
            "human_error": "人为操作失误",
            "biological_variability": "生物学变异",
            "unknown": "未知原因",
        }
        reason_label = reason_map.get(record.failure_reason, record.failure_reason)
        count = record.failure_count or 1
        proof = record.wrong_path_proof or "无详细证明"

        base = f"⚠ 此路径曾因「{reason_label}」失败 {count} 次"
        if record.is_high_confidence:
            base += "（高置信度）"
        base += f"。证明：{proof[:200]}"

        return base