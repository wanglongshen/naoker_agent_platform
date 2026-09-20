"""agent attempt schedule and observation

Revision ID: 6d8024aea979
Revises: 3ec51dfd3742
Create Date: 2026-07-25 10:16:37.477372

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6d8024aea979'
down_revision: Union[str, Sequence[str], None] = '3ec51dfd3742'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agent_run_attempts', sa.Column('not_before', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('agent_steps', 'observation',
               existing_type=sa.TEXT(),
               type_=postgresql.JSON(astext_type=sa.Text()),
               existing_nullable=True,
               postgresql_using='observation::json')
    op.create_index(
        'ix_agent_run_attempts_queue',
        'agent_run_attempts',
        ['status', 'not_before', 'created_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_agent_run_attempts_queue', table_name='agent_run_attempts')
    op.alter_column('agent_steps', 'observation',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.drop_column('agent_run_attempts', 'not_before')
