"""add dsh tables

Revision ID: 12f86502a966
Revises: c7e8f9a0b1d2
Create Date: 2026-09-07 15:37:49.170362

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '12f86502a966'
down_revision: Union[str, Sequence[str], None] = 'c7e8f9a0b1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('dsh_instances',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('port', sa.Integer(), nullable=False),
    sa.Column('state', sa.String(length=32), nullable=False),
    sa.Column('pid', sa.Integer(), nullable=True),
    sa.Column('last_active_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_hint', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_table('dsh_sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('dsh_session_id', sa.String(length=120), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=True),
    sa.Column('turn_count', sa.Integer(), nullable=False),
    sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'dsh_session_id', name='uq_dsh_sessions_user_session')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('dsh_sessions')
    op.drop_table('dsh_instances')
