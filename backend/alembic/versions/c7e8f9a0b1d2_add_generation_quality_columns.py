"""add quality columns to generation_logs

Revision ID: c7e8f9a0b1d2
Revises: a1b2c3d4e5f6
Create Date: 2026-08-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c7e8f9a0b1d2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generation_logs",
        sa.Column("quality_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "generation_logs",
        sa.Column(
            "quality_review_rounds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("generation_logs", "quality_review_rounds")
    op.drop_column("generation_logs", "quality_score")
