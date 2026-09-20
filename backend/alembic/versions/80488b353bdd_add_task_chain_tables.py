"""add task chain tables

Revision ID: 80488b353bdd
Revises: e2f8a4c6b9d1
Create Date: 2026-09-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '80488b353bdd'
down_revision: Union[str, Sequence[str], None] = 'e2f8a4c6b9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('task_chains',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('goal', sa.Text(), nullable=False),
    sa.Column('input_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('current_stage', sa.String(length=50), nullable=False),
    sa.Column('result_file_id', sa.Uuid(), nullable=True),
    sa.Column('feishu_doc_url', sa.Text(), nullable=False),
    sa.Column('final_answer', sa.Text(), nullable=False),
    sa.Column('error', sa.Text(), nullable=False),
    sa.Column('total_tokens', sa.Integer(), nullable=False),
    sa.Column('points_cost', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    sa.ForeignKeyConstraint(['result_file_id'], ['file_objects.id']),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_task_chains_status_created', 'task_chains', ['status', 'created_at'])

    op.create_table('task_chain_stages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('chain_id', sa.Uuid(), nullable=False),
    sa.Column('stage', sa.String(length=50), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('input_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('output_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=False),
    sa.Column('tokens', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chain_id'], ['task_chains.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('chain_id', 'seq', name='ix_task_chain_stages_chain_seq')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('task_chain_stages')
    op.drop_index('ix_task_chains_status_created', table_name='task_chains')
    op.drop_table('task_chains')
