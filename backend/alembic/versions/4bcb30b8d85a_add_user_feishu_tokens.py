"""add user_feishu_tokens

Revision ID: 4bcb30b8d85a
Revises: 1bdd4c6d33d0
Create Date: 2026-08-03 12:09:49.744265

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4bcb30b8d85a'
down_revision: Union[str, Sequence[str], None] = '1bdd4c6d33d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_feishu_tokens',
        sa.Column('owner_user_id', sa.Uuid(), nullable=False),
        sa.Column('access_token', sa.Text(), nullable=False),
        sa.Column('refresh_token', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('open_id', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('owner_user_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('user_feishu_tokens')
