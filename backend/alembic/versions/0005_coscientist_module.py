"""新增 Co-Scientist 多智能体科学推理引擎模块 — 数据库迁移

Revision ID: 0005_coscientist_module
Revises: 0004_model_switch_log
Create Date: 2026-07-31

新增表：
- coscientist_runs          Co-Scientist 研究运行实例
- coscientist_debate_logs   科学辩论日志记录

修改表：
- hypotheses                新增 11 个 Co-Scientist 扩展字段（均 nullable 向后兼容）

设计说明：
- 新表沿用 0002/0003/0004 的模式，依赖 Base.metadata.create_all 幂等创建。
- hypotheses 表新字段使用 op.add_column() 显式添加（create_all 不会修改已存在的表）。
- 必须先创建 coscientist_runs 表，再添加 hypotheses.coscientist_run_id 外键字段。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0005_coscientist_module"
down_revision: Union[str, None] = "0004_model_switch_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 Co-Scientist 模块的表 + 扩展 hypotheses 表

    步骤：
    1. create_all 幂等创建 coscientist_runs + coscientist_debate_logs 新表
    2. op.add_column 给 hypotheses 表添加 11 个 Co-Scientist 扩展字段
    """
    from app.models.base import Base
    import app.models  # noqa: F401 — 触发所有模型注册到 Base.metadata

    bind = op.get_bind()

    # 1. 创建新表（幂等 — 已存在的表不会重建）
    Base.metadata.create_all(bind=bind, tables=[
        Base.metadata.tables.get("coscientist_runs"),
        Base.metadata.tables.get("coscientist_debate_logs"),
    ])

    # 2. 给 hypotheses 表添加 Co-Scientist 扩展字段（幂等检查）
    inspector = sa.inspect(bind)
    existing_columns = {c["name"] for c in inspector.get_columns("hypotheses")}

    new_columns = [
        ("elo_score", sa.Float, {"default": 1000.0, "nullable": True}),
        ("novelty_score", sa.Float, {"nullable": True}),
        ("plausibility_score", sa.Float, {"nullable": True}),
        ("testability_score", sa.Float, {"nullable": True}),
        ("safety_score", sa.Float, {"nullable": True}),
        ("parent_ids", sa.JSON, {"nullable": True}),
        ("evolution_strategy", sa.String(20), {"nullable": True}),
        ("evolution_history", sa.JSON, {"nullable": True}),
        ("debate_log", sa.JSON, {"nullable": True}),
        ("critique_summary", sa.Text, {"nullable": True}),
        ("rank", sa.Integer, {"nullable": True}),
        # coscientist_run_id 外键字段（引用 coscientist_runs.id）
        ("coscientist_run_id", sa.Uuid, {
            "nullable": True,
            "foreign_key": sa.ForeignKeyConstraint(
                ["coscientist_run_id"], ["coscientist_runs.id"],
                name="fk_hypotheses_coscientist_run_id"
            ),
        }),
    ]

    for col_name, col_type, col_kwargs in new_columns:
        if col_name not in existing_columns:
            fk = col_kwargs.pop("foreign_key", None)
            column = sa.Column(col_name, col_type, **col_kwargs)
            op.add_column("hypotheses", column)
            if fk is not None:
                # 外键约束已在 Column 定义中通过 ForeignKey 处理，此处无需额外操作
                pass

    # 创建索引（幂等）
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("hypotheses")}
    if "ix_hypotheses_coscientist_run_id" not in existing_indexes:
        op.create_index(
            "ix_hypotheses_coscientist_run_id",
            "hypotheses",
            ["coscientist_run_id"],
        )


def downgrade() -> None:
    """回滚 Co-Scientist 模块

    步骤：
    1. 删除 hypotheses 表的 Co-Scientist 扩展字段
    2. 删除 coscientist_debate_logs 表
    3. 删除 coscientist_runs 表
    """
    from sqlalchemy import text

    bind = op.get_bind()

    # 1. 删除 hypotheses 表的扩展字段
    drop_columns = [
        "coscientist_run_id",
        "rank",
        "critique_summary",
        "debate_log",
        "evolution_history",
        "evolution_strategy",
        "parent_ids",
        "safety_score",
        "testability_score",
        "plausibility_score",
        "novelty_score",
        "elo_score",
    ]

    inspector = sa.inspect(bind)
    existing_columns = {c["name"] for c in inspector.get_columns("hypotheses")}

    for col_name in drop_columns:
        if col_name in existing_columns:
            try:
                op.drop_column("hypotheses", col_name)
            except Exception:
                # 外键约束可能阻止删除，先尝试删约束
                pass

    # 2. 删除新表（按依赖逆序）
    bind.execute(text("DROP TABLE IF EXISTS coscientist_debate_logs"))
    bind.execute(text("DROP TABLE IF EXISTS coscientist_runs"))
