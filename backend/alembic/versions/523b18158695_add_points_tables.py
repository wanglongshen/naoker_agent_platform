"""add points billing tables

Revision ID: 523b18158695
Revises: d1e2f3a4b5c6
Create Date: 2026-08-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '523b18158695'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('user_points',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('balance', sa.Integer(), nullable=False),
    sa.Column('total_granted', sa.Integer(), nullable=False),
    sa.Column('total_consumed', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('point_transactions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('ref', sa.Text(), nullable=False),
    sa.Column('tokens', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_point_transactions_user_id'), 'point_transactions', ['user_id'], unique=False)
    op.create_table('redeem_codes',
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('points', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_by', sa.Uuid(), nullable=True),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['used_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('code')
    )


def downgrade() -> None:
    op.drop_table('redeem_codes')
    op.drop_index(op.f('ix_point_transactions_user_id'), table_name='point_transactions')
    op.drop_table('point_transactions')
    op.drop_table('user_points')
