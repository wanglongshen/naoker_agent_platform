"""add platform_notes table

Revision ID: a1b2c3d4e5f6
Revises: 42063a8344b0
Create Date: 2026-08-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "42063a8344b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("keyword", sa.String(200), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("image_urls", postgresql.JSONB(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=True),
        sa.Column("collect_count", sa.Integer(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("author", sa.String(200), nullable=True),
        sa.Column("published_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("topic_tags", postgresql.JSONB(), nullable=True),
        sa.Column("collected_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_user_id", "url", name="uq_platform_notes_owner_url"),
    )
    op.create_index("ix_platform_notes_owner_platform", "platform_notes", ["owner_user_id", "platform"])
    op.create_index("ix_platform_notes_owner_keyword", "platform_notes", ["owner_user_id", "keyword"])


def downgrade() -> None:
    op.drop_index("ix_platform_notes_owner_keyword", table_name="platform_notes")
    op.drop_index("ix_platform_notes_owner_platform", table_name="platform_notes")
    op.drop_table("platform_notes")
