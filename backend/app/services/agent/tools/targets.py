"""靶点工具组 — 3 个工具

工具列表：
- discover_targets       靶点发现（委托 TargetIdentifier）
- build_evidence_chain   构建证据链（委托 EvidenceChainBuilder）
- predict_synergy        靶点协同预测（委托 NetworkModeler）
"""
import logging
from typing import Any, Dict
from uuid import UUID

from app.core.exceptions import ForbiddenError
from app.core.security import UserRole
from app.models.project import Project
from app.models.target import Target
from app.services.agent.tools.base import (
    AgentTool,
    ToolContext,
    ToolParameter,
    ToolResult,
)

logger = logging.getLogger(__name__)


async def _check_project_owner(ctx: ToolContext, project_id: str) -> bool:
    """校验项目归属：FOUNDER 全权，其余必须是 owner"""
    if ctx.user.role == UserRole.FOUNDER:
        return True
    project = await ctx.db.get(Project, UUID(project_id))
    return project is not None and project.owner_id == ctx.user.id


async def _check_target_access(ctx: ToolContext, target_id: str) -> bool:
    """校验靶点访问权：FOUNDER 全权，其余必须 owner"""
    if ctx.user.role == UserRole.FOUNDER:
        return True
    target = await ctx.db.get(Target, UUID(target_id))
    if target is None or not getattr(target, "project_id", None):
        return False
    project = await ctx.db.get(Project, target.project_id)
    return project is not None and project.owner_id == ctx.user.id


class DiscoverTargetsTool(AgentTool):
    """靶点发现 — 委托 TargetIdentifier.discover"""

    name = "discover_targets"
    description = (
        "从指定项目的数据集中发现候选药物靶点。"
        "执行流程：突变提取 → 变异注释 → 通路分析 → 证据分级。"
        "返回排好序的靶点列表（含置信度、证据等级）。"
    )
    parameters = [
        ToolParameter("project_id", "string", "项目 ID", required=True),
        ToolParameter("dataset_id", "string", "数据集 ID（可选，默认取项目首个）", required=False),
        ToolParameter(
            "tier",
            "string",
            "分析层级",
            required=False,
            default="fast_screen",
            enum=["fast_screen", "deep_insight"],
        ),
    ]
    side_effects = False  # 仅查询，但会写库（持久化靶点）；保守起见不需确认
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.services.analyzer.target_identifier import TargetIdentifier

        project_id = params["project_id"]
        dataset_id = params.get("dataset_id")
        tier = params.get("tier", "fast_screen")

        # 权限校验
        if not await _check_project_owner(ctx, project_id):
            return ToolResult.fail(error="无权操作此项目")

        try:
            identifier = TargetIdentifier(ctx.db)
            result = await identifier.discover(
                project_id=project_id,
                dataset_id=dataset_id,
                tier=tier,
            )
            targets = result.get("targets", [])
            return ToolResult.ok(
                data={
                    "targets": targets,
                    "total": len(targets),
                    "tier": tier,
                    "project_id": project_id,
                },
                display={
                    "type": "table",
                    "payload": {
                        "columns": ["gene", "confidence_score", "evidence_grade"],
                        "rows": targets[:50],
                    },
                },
            )
        except Exception as e:
            logger.error(f"discover_targets 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))


class BuildEvidenceChainTool(AgentTool):
    """构建证据链 — 委托 EvidenceChainBuilder.build"""

    name = "build_evidence_chain"
    description = (
        "为指定靶点构建完整证据链，整合 ClinVar/COSMIC/ChEMBL/ClinicalTrials 多源证据。"
        "返回结构化证据链报告。"
    )
    parameters = [
        ToolParameter("target_id", "string", "靶点 ID", required=True),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.services.analyzer.evidence_chain import EvidenceChainBuilder

        target_id = params["target_id"]
        if not await _check_target_access(ctx, target_id):
            return ToolResult.fail(error="无权操作此靶点")

        try:
            target = await ctx.db.get(Target, UUID(target_id))
            if target is None:
                return ToolResult.fail(error=f"靶点不存在: {target_id}")

            builder = EvidenceChainBuilder(ctx.db)
            result = await builder.build(target)
            return ToolResult.ok(
                data=result,
                display={"type": "evidence_chain", "payload": result},
            )
        except Exception as e:
            logger.error(f"build_evidence_chain 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))


class PredictSynergyTool(AgentTool):
    """靶点协同预测 — 委托 NetworkModeler.predict_synergy"""

    name = "predict_synergy"
    description = (
        "预测多个靶点对之间的协同效应。"
        "基于 PPI 网络距离和功能相似性计算协同评分。"
        "输入靶点对列表，返回每个靶点对的协同评分与解释。"
    )
    parameters = [
        ToolParameter(
            "target_pairs",
            "array",
            "靶点对列表，每项为 [gene_a, gene_b]",
            required=True,
        ),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.services.analyzer.network_modeler import NetworkModeler

        target_pairs = params["target_pairs"]
        if not target_pairs or not isinstance(target_pairs, list):
            return ToolResult.fail(error="target_pairs 必须是非空数组")

        try:
            modeler = NetworkModeler(ctx.db)
            result = await modeler.predict_synergy(target_pairs)
            return ToolResult.ok(
                data=result,
                display={"type": "table", "payload": result},
            )
        except Exception as e:
            logger.error(f"predict_synergy 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))
