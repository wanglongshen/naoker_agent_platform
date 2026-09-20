"""add project_folder_id to sessions and runs

Revision ID: 42063a8344b0
Revises: 523b18158695
Create Date: 2026-08-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '42063a8344b0'
down_revision: Union[str, Sequence[str], None] = '523b18158695'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agent_sessions', sa.Column('project_folder_id', sa.Uuid(), nullable=True))
    op.add_column('agent_runs', sa.Column('project_folder_id', sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column('agent_runs', 'project_folder_id')
    op.drop_column('agent_sessions', 'project_folder_id')
