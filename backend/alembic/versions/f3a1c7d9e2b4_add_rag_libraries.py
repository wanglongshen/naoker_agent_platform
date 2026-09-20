"""add rag libraries and jobs

Revision ID: f3a1c7d9e2b4
Revises: 80488b353bdd
Create Date: 2026-09-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f3a1c7d9e2b4'
down_revision: Union[str, Sequence[str], None] = '80488b353bdd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_LIBRARY_ID = '6f1d2c3a-1111-4a2b-9c3d-000000000001'


def upgrade() -> None:
    op.create_table('rag_libraries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('visibility', sa.String(length=16), nullable=False),
        sa.Column('retrieval_enabled', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.add_column('rag_documents', sa.Column('library_id', sa.Uuid(), nullable=True))
    op.add_column('rag_documents', sa.Column('error_message', sa.Text(), nullable=True))

    op.execute(
        sa.text(
            "INSERT INTO rag_libraries (id, name, description, kind, visibility, retrieval_enabled) "
            "VALUES (CAST(:id AS uuid), :name, :description, 'industry', 'admins_only', true)"
        ).bindparams(
            id=DEFAULT_LIBRARY_ID,
            name='行业知识库',
            description='抖音电商官方方法论、投放手册与运营白皮书',
        )
    )
    op.execute(
        sa.text("UPDATE rag_documents SET library_id = CAST(:id AS uuid) WHERE library_id IS NULL").bindparams(
            id=DEFAULT_LIBRARY_ID
        )
    )

    op.alter_column('rag_documents', 'library_id', nullable=False)
    op.create_index('ix_rag_documents_library_id', 'rag_documents', ['library_id'])
    op.create_foreign_key(
        'fk_rag_documents_library_id', 'rag_documents', 'rag_libraries',
        ['library_id'], ['id'], ondelete='CASCADE',
    )

    op.create_table('rag_jobs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('library_id', sa.Uuid(), nullable=False),
        sa.Column('doc_id', sa.Uuid(), nullable=True),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('total', sa.Integer(), nullable=False),
        sa.Column('processed', sa.Integer(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['library_id'], ['rag_libraries.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['doc_id'], ['rag_documents.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_rag_jobs_status', 'rag_jobs', ['status'])


def downgrade() -> None:
    op.drop_index('ix_rag_jobs_status', table_name='rag_jobs')
    op.drop_table('rag_jobs')
    op.drop_constraint('fk_rag_documents_library_id', 'rag_documents', type_='foreignkey')
    op.drop_index('ix_rag_documents_library_id', table_name='rag_documents')
    op.drop_column('rag_documents', 'error_message')
    op.drop_column('rag_documents', 'library_id')
    op.drop_table('rag_libraries')
