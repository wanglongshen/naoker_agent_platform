"""add roles parent_role_id

Revision ID: 79ec88b72f36
Revises: 4bcb30b8d85a
Create Date: 2026-08-03 14:36:10.396229

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '79ec88b72f36'
down_revision: Union[str, Sequence[str], None] = '4bcb30b8d85a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "roles",
        sa.Column("parent_role_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_roles_parent_role_id_roles",
        "roles",
        "roles",
        ["parent_role_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_roles_parent_role_id", "roles", ["parent_role_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_roles_parent_role_id", table_name="roles")
    op.drop_constraint(
        "fk_roles_parent_role_id_roles", "roles", type_="foreignkey"
    )
    op.drop_column("roles", "parent_role_id")
