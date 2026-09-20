"""add distill_version to workflow_doc_summaries

Revision ID: b7e2f1a0c3d4
Revises: a6f8c3b21d4e
Create Date: 2026-08-04
"""
import sqlalchemy as sa
from alembic import op

revision = "b7e2f1a0c3d4"
down_revision = "a6f8c3b21d4e4f0a9b2c7d8e9f0a1b2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_doc_summaries",
        sa.Column("distill_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("workflow_doc_summaries", "distill_version")
