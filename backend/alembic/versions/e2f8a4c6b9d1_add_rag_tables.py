"""add rag tables

Revision ID: e2f8a4c6b9d1
Revises: 12f86502a966
Create Date: 2026-09-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e2f8a4c6b9d1'
down_revision: Union[str, Sequence[str], None] = '12f86502a966'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('rag_documents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('doc_type', sa.String(length=64), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=True),
    sa.Column('publisher', sa.String(length=200), nullable=True),
    sa.Column('license_note', sa.Text(), nullable=True),
    sa.Column('file_key', sa.String(length=512), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('chunk_count', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sha256')
    )
    op.create_index('ix_rag_documents_status', 'rag_documents', ['status'])

    op.create_table('rag_chunks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('doc_id', sa.Uuid(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('section_path', sa.String(length=500), nullable=True),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', sa.LargeBinary(), nullable=False),
    sa.Column('embedding_dim', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['doc_id'], ['rag_documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('doc_id', 'chunk_index', name='ix_rag_chunks_doc_chunk')
    )

    op.create_table('rag_eval_set',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('query', sa.Text(), nullable=False),
    sa.Column('expected_doc_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('rag_eval_set')
    op.drop_table('rag_chunks')
    op.drop_index('ix_rag_documents_status', table_name='rag_documents')
    op.drop_table('rag_documents')
