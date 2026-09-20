"""file_management

Revision ID: 7d5ba2fa56a0
Revises: 5cf62b7d4822
Create Date: 2026-07-30 06:55:04.666650

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d5ba2fa56a0'
down_revision: Union[str, Sequence[str], None] = '5cf62b7d4822'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "file_folders",
        sa.Column("id", sa.dialects.postgresql.UUID, primary_key=True),
        sa.Column("owner_user_id", sa.dialects.postgresql.UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("parent_folder_id", sa.dialects.postgresql.UUID, sa.ForeignKey("file_folders.id")),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("path", sa.Text, nullable=False, server_default=""),
        sa.Column("depth", sa.Integer, nullable=False, server_default="0"),
        sa.Column("child_file_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("total_size_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_by", sa.dialects.postgresql.UUID),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_file_folders_owner", "file_folders", ["owner_user_id"])
    op.create_index("ix_file_folders_parent", "file_folders", ["parent_folder_id"])
    op.create_index("ix_file_folders_path", "file_folders", ["path"])

    op.create_table(
        "file_objects",
        sa.Column("id", sa.dialects.postgresql.UUID, primary_key=True),
        sa.Column("owner_user_id", sa.dialects.postgresql.UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("folder_id", sa.dialects.postgresql.UUID, sa.ForeignKey("file_folders.id")),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("extracted_text", sa.Text),
        sa.Column("preview_status", sa.String(32), nullable=False, server_default="none"),
        sa.Column("preview_path", sa.String(512)),
        sa.Column("source_attachment_id", sa.dialects.postgresql.UUID, sa.ForeignKey("agent_attachments.id")),
        sa.Column("created_by", sa.dialects.postgresql.UUID),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_file_objects_owner", "file_objects", ["owner_user_id"])
    op.create_index("ix_file_objects_folder", "file_objects", ["folder_id"])
    op.create_index("ix_file_objects_media_type", "file_objects", ["media_type"])
    op.create_index("ix_file_objects_sha256", "file_objects", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_file_objects_sha256")
    op.drop_index("ix_file_objects_media_type")
    op.drop_index("ix_file_objects_folder")
    op.drop_index("ix_file_objects_owner")
    op.drop_table("file_objects")
    op.drop_index("ix_file_folders_path")
    op.drop_index("ix_file_folders_parent")
    op.drop_index("ix_file_folders_owner")
    op.drop_table("file_folders")
