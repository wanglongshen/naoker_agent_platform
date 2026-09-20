"""add_agent_run_result

Revision ID: 5cf62b7d4822
Revises: 6d8024aea979
Create Date: 2026-07-27 16:44:36.016981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5cf62b7d4822'
down_revision: Union[str, Sequence[str], None] = '6d8024aea979'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'agent_runs',
        sa.Column('result', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('agent_runs', 'result')
