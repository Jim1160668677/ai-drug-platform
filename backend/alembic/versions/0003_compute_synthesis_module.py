"""新增计算引擎与合成模块 — 数据库迁移

Revision ID: 0003_compute_synthesis
Revises: 0002_genome_module
Create Date: 2026-07-22

新增表：
- protein_structures    蛋白结构预测记录（ESMFold/AlphaFold）
- compute_jobs          计算任务记录（对接/单细胞/新抗原/筛选统一追踪）
- benchmark_reports     基准评测报告（hybrid vs supercompute vs llm_only）
- neoantigens           新抗原与 mRNA 疫苗记录
- synthesis_plans       合成规划记录（路线+SA+SC+成本）

设计说明：本迁移沿用 0002 的模式，依赖 Base.metadata.create_all 幂等创建。
新增模型已在 app/models/__init__.py 中注册，import 后即挂载到 Base.metadata。
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_compute_synthesis"
down_revision: Union[str, None] = "0002_genome_module"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建计算引擎与合成模块的表

    依赖 Base.metadata.create_all 幂等机制。
    """
    from app.models.base import Base
    import app.models  # noqa: F401 — 触发所有模型注册到 Base.metadata

    bind = op.get_bind()
    # create_all 是幂等的 — 已存在的表不会重建
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """删除计算引擎与合成模块的表（按依赖逆序）"""
    from sqlalchemy import text

    bind = op.get_bind()
    tables = [
        "synthesis_plans",
        "neoantigens",
        "benchmark_reports",
        "compute_jobs",
        "protein_structures",
    ]
    for table in tables:
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
