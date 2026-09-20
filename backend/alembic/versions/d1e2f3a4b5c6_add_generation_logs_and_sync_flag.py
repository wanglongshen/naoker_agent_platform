"""add generation_logs and users.sync_feishu_enabled

Revision ID: d1e2f3a4b5c6
Revises: c9d4e5f6a7b8
Create Date: 2026-08-06 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c9d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('sync_feishu_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.create_table('generation_logs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('folder_id', sa.Uuid(), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('input_text', sa.Text(), nullable=False),
    sa.Column('final_md_file_id', sa.Uuid(), nullable=True),
    sa.Column('final_answer', sa.Text(), nullable=False),
    sa.Column('feishu_doc_url', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['folder_id'], ['file_folders.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['agent_sessions.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ),
    sa.ForeignKeyConstraint(['final_md_file_id'], ['file_objects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_generation_logs_folder_id'), 'generation_logs', ['folder_id'], unique=False)
    op.create_index(op.f('ix_generation_logs_user_id'), 'generation_logs', ['user_id'], unique=False)
    op.create_index(op.f('ix_generation_logs_run_id'), 'generation_logs', ['run_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_generation_logs_run_id'), table_name='generation_logs')
    op.drop_index(op.f('ix_generation_logs_user_id'), table_name='generation_logs')
    op.drop_index(op.f('ix_generation_logs_folder_id'), table_name='generation_logs')
    op.drop_table('generation_logs')
    op.drop_column('users', 'sync_feishu_enabled')
