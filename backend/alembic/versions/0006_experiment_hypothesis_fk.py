"""新增 experiments.hypothesis_id 外键 — Phase B4 反馈闭环

Revision ID: 0006_experiment_hypothesis_fk
Revises: 0005_coscientist_module
Create Date: 2026-07-31

修改表：
- experiments    新增 hypothesis_id 外键列（nullable, indexed），关联 hypotheses 表

设计说明：
- Phase B4 反馈闭环：将湿实验结果反馈到 Co-Scientist 假设评估。
- hypothesis_id 为 nullable，向后兼容已有实验记录。
- 添加索引 ix_experiments_hypothesis_id 加速按假设查询实验。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0006_experiment_hypothesis_fk"
down_revision: Union[str, None] = "0005_coscientist_module"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加 experiments.hypothesis_id 列 + 索引"""
    # 幂等：先检查列是否存在
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("experiments")]

    if "hypothesis_id" not in columns:
        op.add_column(
            "experiments",
            sa.Column(
                "hypothesis_id",
                sa.String(36),
                nullable=True,
            ),
        )
        op.create_index(
            "ix_experiments_hypothesis_id",
            "experiments",
            ["hypothesis_id"],
        )
        # 外键约束（SQLite ALTER TABLE 有限制，使用 batch_alter_table 兼容）
        with op.batch_alter_table("experiments") as batch_op:
            batch_op.create_foreign_key(
                "fk_experiments_hypothesis_id",
                "hypotheses",
                ["hypothesis_id"],
                ["id"],
            )


def downgrade() -> None:
    """回滚：移除 experiments.hypothesis_id 列"""
    with op.batch_alter_table("experiments") as batch_op:
        batch_op.drop_constraint("fk_experiments_hypothesis_id", type_="foreignkey")
    op.drop_index("ix_experiments_hypothesis_id", table_name="experiments")
    op.drop_column("experiments", "hypothesis_id")