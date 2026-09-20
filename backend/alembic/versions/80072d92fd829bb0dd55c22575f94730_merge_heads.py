"""merge 8274d2ce84b8 and b7e2f1a0c3d4 heads

Revision ID: 80072d92fd829bb0dd55c22575f94730
Revises: 8274d2ce84b8, b7e2f1a0c3d4
Create Date: 2026-08-04
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '80072d92fd829bb0dd55c22575f94730'
down_revision: Union[str, Sequence[str], None] = ('8274d2ce84b8', 'b7e2f1a0c3d4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge two alembic heads; no schema changes."""
    pass


def downgrade() -> None:
    """Merge two alembic heads; no schema changes."""
    pass
