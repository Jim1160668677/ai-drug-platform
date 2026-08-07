"""新增个人基因组解读模块 — 数据库迁移

Revision ID: 0002_genome_module
Revises: 0001_initial
Create Date: 2026-07-21

新增表：
- traits                性状
- snp_loci              SNP 位点知识库
- personal_genomes      个人基因文件
- genotype_matches      基因型匹配记录
- risk_assessments      风险评估
- lifestyle_recommendations  生活建议
- user_llm_configs      用户级 LLM 配置（BYO Key）
- prompt_templates      Prompt 模板

设计说明：本迁移不显式创建表，依赖 Base.metadata.create_all 在
0001_initial 的 upgrade() 中已包含新模型（因为 0001_initial 会重新执行
create_all）。本迁移仅作为版本标记，便于未来增量字段变更使用 alembic
autogenerate。

由于 init_db() 已使用 `Base.metadata.create_all(bind=bind)` 一次性创建所有表，
新增模型在表已存在时会被跳过、不存在时会被创建。开发环境重启服务即生效。
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_genome_module"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建个人基因组解读模块的表

    依赖 0001_initial 的 create_all 机制。此处显式调用 create_all
    以确保旧数据库升级时也能创建新表（幂等）。
    """
    from app.models.base import Base
    import app.models  # noqa: F401 — 触发所有模型注册到 Base.metadata

    bind = op.get_bind()
    # create_all 是幂等的 — 已存在的表不会重建
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """删除个人基因组解读模块的表（按依赖逆序）"""
    from sqlalchemy import text

    bind = op.get_bind()
    tables = [
        "lifestyle_recommendations",
        "risk_assessments",
        "genotype_matches",
        "personal_genomes",
        "snp_loci",
        "traits",
        "user_llm_configs",
        "prompt_templates",
    ]
    for table in tables:
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
