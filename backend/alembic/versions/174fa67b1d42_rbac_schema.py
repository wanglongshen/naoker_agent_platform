"""rbac schema

Revision ID: 174fa67b1d42
Revises:
Create Date: 2026-07-21 17:19:45.645582

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "174fa67b1d42"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("phone"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_table(
        "role_permissions",
        sa.Column("role_id", postgresql.UUID(), nullable=False),
        sa.Column("permission_id", postgresql.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_id"], ["permissions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"],
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
        sa.UniqueConstraint("role_id", "permission_id"),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("role_id", postgresql.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
        sa.UniqueConstraint("user_id", "role_id"),
    )


def downgrade() -> None:
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("permissions")
