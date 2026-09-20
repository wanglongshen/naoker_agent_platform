"""add users avatar_path

Revision ID: 29daf312d82f
Revises: d5baf31d85c3
Create Date: 2026-08-04 22:01:50.944478

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '29daf312d82f'
down_revision: Union[str, Sequence[str], None] = 'd5baf31d85c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("avatar_path", sa.String(length=512), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "avatar_path")
