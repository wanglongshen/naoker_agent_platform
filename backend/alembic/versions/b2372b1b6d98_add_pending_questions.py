"""add pending questions

Revision ID: b2372b1b6d98
Revises: 29daf312d82f
Create Date: 2026-08-05 11:21:13.058142

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2372b1b6d98'
down_revision: Union[str, Sequence[str], None] = '29daf312d82f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add pending_questions column and awaiting_question run status."""
    op.add_column(
        "agent_runs",
        sa.Column("pending_questions", sa.JSON(), nullable=True),
    )
    op.drop_constraint("ck_agent_runs_status", "agent_runs", type_="check")
    op.create_check_constraint(
        "ck_agent_runs_status",
        "agent_runs",
        "status IN ('queued','running','retry_wait','awaiting_question','succeeded','failed','cancel_requested','cancelled')",
    )


def downgrade() -> None:
    """Drop pending_questions column and revert run status constraint."""
    op.drop_constraint("ck_agent_runs_status", "agent_runs", type_="check")
    op.create_check_constraint(
        "ck_agent_runs_status",
        "agent_runs",
        "status IN ('queued','running','retry_wait','succeeded','failed','cancel_requested','cancelled')",
    )
    op.drop_column("agent_runs", "pending_questions")
