"""add users is_builtin

Revision ID: d5baf31d85c3
Revises: 80072d92fd829bb0dd55c22575f94730
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa

revision = "d5baf31d85c3"
down_revision = "80072d92fd829bb0dd55c22575f94730"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_builtin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_builtin")
