"""修复 reasoning_trace.run_id 外键约束

Revision ID: 0008_fix_reasoning_trace_run_id
Revises: 0007_intelligence_module
Create Date: 2026-08-02

问题：
- reasoning_trace.run_id 原本是 FK → coscientist_runs.id
- 但推理渠道生成的 run_id 可能不存在于 coscientist_runs 表中
- 导致 trace 写入时因外键约束失败，推理轨迹查询返回空

修复：
- 将 run_id 列改为 VARCHAR(36)，取消外键约束
- run_id 现在作为普通标识符存储，允许任意 UUID 值
"""
from alembic import op
import sqlalchemy as sa

revision = '0008_fix_reasoning_trace_run_id'
down_revision = '0007_intelligence_module'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # 检查 reasoning_trace 表是否存在
    tables = inspector.get_table_names()
    if 'reasoning_trace' not in tables:
        print("[0008] reasoning_trace 表不存在，跳过迁移")
        return

    # 检查 run_id 列当前类型
    columns = {c['name']: c for c in inspector.get_columns('reasoning_trace')}
    run_id_col = columns.get('run_id')
    if run_id_col is None:
        print("[0008] run_id 列不存在，跳过迁移")
        return

    # 如果已经是 String 类型，说明迁移已完成
    col_type = str(run_id_col['type'])
    if 'VARCHAR' in col_type.upper() or 'STRING' in col_type.upper():
        print(f"[0008] run_id 已是字符串类型 ({col_type})，跳过列类型修改")
    else:
        # 删除外键约束（PostgreSQL 中存在，SQLite 中通常不存在）
        fk_constraints = inspector.get_foreign_keys('reasoning_trace')
        if fk_constraints:
            print(f"[0008] 发现 {len(fk_constraints)} 个外键约束，尝试删除")
            for fk in fk_constraints:
                try:
                    op.drop_constraint(
                        fk['name'],
                        'reasoning_trace',
                        type_='foreignkey',
                    )
                except Exception as e:
                    print(f"[0008] 删除外键约束失败（可忽略）: {e}")

        # 修改列类型为 VARCHAR(36)
        with op.batch_alter_table('reasoning_trace', schema=None) as batch_op:
            batch_op.alter_column(
                'run_id',
                existing_type=sa.UUID(),
                type_=sa.String(length=36),
                existing_nullable=True,
            )
        print("[0008] run_id 列类型已修改为 VARCHAR(36)")

    # 添加索引（如果不存在）
    existing_indexes = inspector.get_indexes('reasoning_trace')
    index_names = [idx['name'] for idx in existing_indexes]
    if 'ix_reasoning_trace_run_id_varchar' not in index_names:
        try:
            with op.batch_alter_table('reasoning_trace', schema=None) as batch_op:
                batch_op.create_index(
                    'ix_reasoning_trace_run_id_varchar',
                    ['run_id'],
                    unique=False,
                )
            print("[0008] 索引 ix_reasoning_trace_run_id_varchar 已创建")
        except Exception as e:
            print(f"[0008] 创建索引失败: {e}")
    else:
        print("[0008] 索引已存在，跳过")


def downgrade():
    pass