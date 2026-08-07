"""新增模型切换日志表 — 智谱 GLM 降级链路

Revision ID: 0004_model_switch_log
Revises: 0003_compute_synthesis
Create Date: 2026-07-29

新增表：
- model_switch_logs    大模型自动切换/降级事件日志

设计说明：本迁移沿用 0002/0003 的模式，依赖 Base.metadata.create_all 幂等创建。
新增模型已在 app/models/__init__.py 中注册，import 后即挂载到 Base.metadata。
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_model_switch_log"
down_revision: Union[str, None] = "0003_compute_synthesis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建模型切换日志表

    依赖 Base.metadata.create_all 幂等机制。
    """
    from app.models.base import Base
    import app.models  # noqa: F401 — 触发所有模型注册到 Base.metadata

    bind = op.get_bind()
    # create_all 是幂等的 — 已存在的表不会重建
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """删除模型切换日志表"""
    from sqlalchemy import text

    bind = op.get_bind()
    # 先删 enum 类型（PostgreSQL），再删表
    bind.execute(text("DROP TABLE IF EXISTS model_switch_logs"))
    bind.execute(text("DROP TYPE IF EXISTS switch_trigger_type"))
