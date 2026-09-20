"""product_rbac_metadata

Revision ID: a03c3843be4c
Revises: 174fa67b1d42
Create Date: 2026-07-24 08:47:09.786895

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a03c3843be4c'
down_revision: Union[str, Sequence[str], None] = '174fa67b1d42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("roles", sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("roles", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("roles", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_roles_is_deleted", "roles", ["is_deleted"])
    op.add_column("permissions", sa.Column("module", sa.String(length=64), nullable=False, server_default="system"))
    op.add_column("permissions", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("permissions", sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("true")))

    op.execute("UPDATE roles SET is_system = true, is_deleted = false WHERE code = 'super_admin'")
    op.execute("UPDATE roles SET is_deleted = false WHERE is_deleted IS NULL")
    op.execute(
        "UPDATE permissions SET module = "
        "CASE "
        "WHEN code LIKE 'user:%' THEN 'user' "
        "WHEN code LIKE 'role:%' THEN 'role' "
        "ELSE 'system' "
        "END"
    )


def downgrade() -> None:
    op.drop_index("ix_roles_is_deleted", table_name="roles")
    op.drop_column("roles", "sort_order")
    op.drop_column("roles", "is_deleted")
    op.drop_column("roles", "is_system")
    op.drop_column("permissions", "is_system")
    op.drop_column("permissions", "sort_order")
    op.drop_column("permissions", "module")
