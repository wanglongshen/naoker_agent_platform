"""add is_pinned to agent_sessions

Revision ID: 1bdd4c6d33d0
Revises: 7d5ba2fa56a0
Create Date: 2026-07-31 16:40:08.294439

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '1bdd4c6d33d0'
down_revision: Union[str, Sequence[str], None] = '7d5ba2fa56a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agent_sessions', sa.Column('is_pinned', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agent_sessions', 'is_pinned')
