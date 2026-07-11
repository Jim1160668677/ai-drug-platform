"""initial schema — 基于 Base.metadata.create_all 生成全部表

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-06

设计决策 D13：手动创建初始迁移，upgrade 时调用 Base.metadata.create_all
        生成所有表（包含 P1.1 新增的 5 个模型）。
        后续模型变更应使用 `alembic revision --autogenerate` 生成增量迁移。
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建全部表（基于 Base.metadata）

    使用 Base.metadata.create_all 一次性生成所有表结构，包括：
    - projects, datasets, targets, molecules, hypotheses, experiments
    - users, audit_logs, llm_configs
    - P1.1 新增：federated_jobs, privacy_domains, efficacy_records, feedbacks, chat_sessions
    - 关联表：hypothesis_analyses, docking_results, target_reports 等
    """
    from app.models.base import Base
    import app.models  # noqa: F401 — 触发所有模型注册到 Base.metadata

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """删除全部表（按依赖逆序）"""
    from app.models.base import Base
    import app.models  # noqa: F401

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
