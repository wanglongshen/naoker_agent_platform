"""add user_web_cookies

Revision ID: 8274d2ce84b8
Revises: a6f8c3b21d4e4f0a9b2c7d8e9f0a1b2c
Create Date: 2026-08-03 16:07:46.036213

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8274d2ce84b8'
down_revision: Union[str, Sequence[str], None] = 'a6f8c3b21d4e4f0a9b2c7d8e9f0a1b2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('user_web_cookies',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=False),
    sa.Column('domain', sa.String(length=256), nullable=False),
    sa.Column('cookie_string', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_web_cookies_owner_user_id'), 'user_web_cookies', ['owner_user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_user_web_cookies_owner_user_id'), table_name='user_web_cookies')
    op.drop_table('user_web_cookies')
