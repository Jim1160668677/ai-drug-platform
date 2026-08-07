"""新增统一智能系统模块 — 数据库迁移

Revision ID: 0007_intelligence_module
Revises: 0006_experiment_hypothesis_fk
Create Date: 2026-08-01

新增表（6 张）：
- unified_sessions      统一智能会话（融合 AI 问答 / 科学推理 / Agent 工作台）
- context_memory        持久化上下文记忆（论文 Context Memory 组件，支持故障重启）
- reasoning_trace       推理过程追溯（每个 agent/LLM 调用/决策点持久化）
- reasoning_rules       推理规则（YAML 预置 + 用户自定义，开放规则引擎）
- analysis_templates    分析报告模板（CDISC SDTM / FHIR / 自定义）
- multimodal_assets     多模态资产（DICOM/PDF/OCR/病理图像统一文本化）

修改表（2 张）：
- datasets              新增 analysis_results（JSON, nullable）— 修复数据契约缺口 #2
- agent_sessions        新增 unified_session_id（FK → unified_sessions.id, nullable）

设计说明：
- 新表沿用 0005 模式，依赖 Base.metadata.create_all 幂等创建。
- 表创建顺序按外键依赖排列：unified_sessions 先于依赖它的表。
- 修改现有表使用 op.add_column + 幂等检查（同 0005/0006）。
- agent_sessions.unified_session_id 外键使用 batch_alter_table 兼容 SQLite（同 0006）。
- 所有新字段 nullable，新表外键 ondelete=SET NULL/CASCADE，向后兼容。
- downgrade 完整回滚：先删列，再按依赖逆序删表。

前置依赖：本迁移是所有数据持久化的前置依赖，必须最先完成。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0007_intelligence_module"
down_revision: Union[str, None] = "0006_experiment_hypothesis_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建统一智能系统模块的 6 张新表 + 扩展 2 张现有表

    步骤：
    1. create_all 幂等创建 6 张新表（按外键依赖顺序）
    2. op.add_column 给 datasets 表添加 analysis_results 字段
    3. op.add_column + batch_alter_table 给 agent_sessions 表添加 unified_session_id 外键字段
    """
    from app.models.base import Base
    import app.models  # noqa: F401 — 触发所有模型注册到 Base.metadata

    bind = op.get_bind()

    # 1. 创建 6 张新表（幂等 — 已存在的表不会重建）
    # 按外键依赖顺序排列：unified_sessions 先于 context_memory / reasoning_trace / multimodal_assets
    Base.metadata.create_all(bind=bind, tables=[
        Base.metadata.tables.get("unified_sessions"),
        Base.metadata.tables.get("context_memory"),
        Base.metadata.tables.get("reasoning_trace"),
        Base.metadata.tables.get("reasoning_rules"),
        Base.metadata.tables.get("analysis_templates"),
        Base.metadata.tables.get("multimodal_assets"),
    ])

    # 2. 给 datasets 表添加 analysis_results 字段（幂等检查）
    inspector = sa.inspect(bind)
    dataset_columns = {c["name"] for c in inspector.get_columns("datasets")}
    if "analysis_results" not in dataset_columns:
        op.add_column(
            "datasets",
            sa.Column("analysis_results", sa.JSON, nullable=True),
        )

    # 3. 给 agent_sessions 表添加 unified_session_id 外键字段（幂等检查）
    # 使用 batch_alter_table 兼容 SQLite（同 0006 模式）
    agent_session_columns = {c["name"] for c in inspector.get_columns("agent_sessions")}
    if "unified_session_id" not in agent_session_columns:
        op.add_column(
            "agent_sessions",
            sa.Column("unified_session_id", sa.String(36), nullable=True),
        )
        op.create_index(
            "ix_agent_sessions_unified_session_id",
            "agent_sessions",
            ["unified_session_id"],
        )
        with op.batch_alter_table("agent_sessions") as batch_op:
            batch_op.create_foreign_key(
                "fk_agent_sessions_unified_session_id",
                "unified_sessions",
                ["unified_session_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    """回滚统一智能系统模块

    步骤：
    1. 删除 agent_sessions 表的 unified_session_id 字段（含外键约束 + 索引）
    2. 删除 datasets 表的 analysis_results 字段
    3. 按依赖逆序删除 6 张新表
    """
    from sqlalchemy import text

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. 删除 agent_sessions 表的 unified_session_id 字段
    agent_session_columns = {c["name"] for c in inspector.get_columns("agent_sessions")}
    if "unified_session_id" in agent_session_columns:
        try:
            with op.batch_alter_table("agent_sessions") as batch_op:
                batch_op.drop_constraint(
                    "fk_agent_sessions_unified_session_id", type_="foreignkey"
                )
        except Exception:
            pass  # 外键约束可能不存在（SQLite）
        try:
            op.drop_index(
                "ix_agent_sessions_unified_session_id", table_name="agent_sessions"
            )
        except Exception:
            pass
        op.drop_column("agent_sessions", "unified_session_id")

    # 2. 删除 datasets 表的 analysis_results 字段
    dataset_columns = {c["name"] for c in inspector.get_columns("datasets")}
    if "analysis_results" in dataset_columns:
        op.drop_column("datasets", "analysis_results")

    # 3. 删除 6 张新表（按依赖逆序：先删依赖 unified_sessions 的表）
    # multimodal_assets → analysis_templates → reasoning_rules → reasoning_trace → context_memory → unified_sessions
    bind.execute(text("DROP TABLE IF EXISTS multimodal_assets"))
    bind.execute(text("DROP TABLE IF EXISTS analysis_templates"))
    bind.execute(text("DROP TABLE IF EXISTS reasoning_rules"))
    bind.execute(text("DROP TABLE IF EXISTS reasoning_trace"))
    bind.execute(text("DROP TABLE IF EXISTS context_memory"))
    bind.execute(text("DROP TABLE IF EXISTS unified_sessions"))
