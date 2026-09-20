"""add workflow_doc_summaries

Revision ID: a6f8c3b21d4e4f0a9b2c7d8e9f0a1b2c
Revises: 79ec88b72f36
Create Date: 2026-08-03
"""
import sqlalchemy as sa
from alembic import op

revision = "a6f8c3b21d4e4f0a9b2c7d8e9f0a1b2c"
down_revision = "79ec88b72f36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_doc_summaries",
        sa.Column("doc_path", sa.String(length=500), primary_key=True),
        sa.Column("file_updated_at", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("file_sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ready"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distilled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("workflow_doc_summaries")
