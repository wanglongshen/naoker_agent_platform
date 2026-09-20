"""add feishu_configs

Revision ID: c9d4e5f6a7b8
Revises: b2372b1b6d98
Create Date: 2026-08-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c9d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2372b1b6d98'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('feishu_configs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('app_id', sa.String(length=128), nullable=False),
    sa.Column('app_secret_encrypted', sa.Text(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feishu_configs_is_default'), 'feishu_configs', ['is_default'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_feishu_configs_is_default'), table_name='feishu_configs')
    op.drop_table('feishu_configs')
