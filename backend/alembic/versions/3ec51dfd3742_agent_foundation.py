"""agent foundation

Revision ID: 3ec51dfd3742
Revises: a03c3843be4c
Create Date: 2026-07-24 18:33:41.051651

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3ec51dfd3742'
down_revision: Union[str, Sequence[str], None] = 'a03c3843be4c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('agent_retention_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('job_type', sa.String(length=64), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('stats', postgresql.JSON(astext_type=sa.Text()), nullable=False),
    sa.Column('error_summary', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('agent_sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('last_run_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'owner_user_id', name='uq_agent_sessions_id_owner')
    )
    op.create_index(op.f('ix_agent_sessions_owner_user_id'), 'agent_sessions', ['owner_user_id'], unique=False)
    op.create_table('agent_attachments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('storage_key', sa.String(length=512), nullable=False),
    sa.Column('filename', sa.String(length=512), nullable=False),
    sa.Column('original_filename', sa.String(length=512), nullable=False),
    sa.Column('media_type', sa.String(length=128), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('extraction_status', sa.String(length=32), nullable=False),
    sa.Column('extracted_text', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id'], ['agent_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_attachments_owner_user_id'), 'agent_attachments', ['owner_user_id'], unique=False)
    op.create_index(op.f('ix_agent_attachments_session_id'), 'agent_attachments', ['session_id'], unique=False)
    op.create_table('agent_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=False),
    sa.Column('goal', sa.Text(), nullable=False),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('network_enabled', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('max_steps', sa.Integer(), nullable=False),
    sa.Column('current_attempt_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('queued','running','retry_wait','succeeded','failed','cancel_requested','cancelled')", name='ck_agent_runs_status'),
    sa.CheckConstraint('max_steps > 0 AND max_steps <= 200', name='ck_agent_runs_max_steps'),
    sa.ForeignKeyConstraint(['session_id', 'owner_user_id'], ['agent_sessions.id', 'agent_sessions.owner_user_id'], name='fk_agent_runs_session_owner'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_runs_owner_user_id'), 'agent_runs', ['owner_user_id'], unique=False)
    op.create_index(op.f('ix_agent_runs_session_id'), 'agent_runs', ['session_id'], unique=False)
    op.create_index(op.f('ix_agent_runs_status'), 'agent_runs', ['status'], unique=False)
    op.create_table('agent_run_attachments',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('attachment_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['attachment_id'], ['agent_attachments.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('run_id', 'attachment_id')
    )
    op.create_table('agent_run_attempts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('attempt_number', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('worker_id', sa.String(length=128), nullable=True),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_code', sa.String(length=64), nullable=True),
    sa.Column('retry_of_attempt_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'attempt_number', name='uq_agent_run_attempts_run_number')
    )
    op.create_index(op.f('ix_agent_run_attempts_run_id'), 'agent_run_attempts', ['run_id'], unique=False)
    op.execute(sa.text("CREATE SEQUENCE IF NOT EXISTS agent_run_events_seq_seq"))
    op.create_table('agent_run_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('attempt_id', sa.Uuid(), nullable=True),
    sa.Column('seq', sa.BigInteger(), nullable=False, server_default=sa.text("nextval('agent_run_events_seq_seq')")),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('payload', postgresql.JSON(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['attempt_id'], ['agent_run_attempts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_run_events_run_id'), 'agent_run_events', ['run_id'], unique=False)
    op.create_index('ix_agent_run_events_run_seq', 'agent_run_events', ['run_id', 'seq'], unique=False)
    op.create_table('agent_steps',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('attempt_id', sa.Uuid(), nullable=False),
    sa.Column('step_number', sa.Integer(), nullable=False),
    sa.Column('thought_summary', sa.Text(), nullable=True),
    sa.Column('action_type', sa.String(length=64), nullable=True),
    sa.Column('action_payload', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('observation', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['attempt_id'], ['agent_run_attempts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('attempt_id', 'step_number', name='uq_agent_steps_attempt_number')
    )
    op.create_index(op.f('ix_agent_steps_attempt_id'), 'agent_steps', ['attempt_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_agent_steps_attempt_id'), table_name='agent_steps')
    op.drop_table('agent_steps')
    op.drop_index('ix_agent_run_events_run_seq', table_name='agent_run_events')
    op.drop_index(op.f('ix_agent_run_events_run_id'), table_name='agent_run_events')
    op.drop_table('agent_run_events')
    op.execute(sa.text("DROP SEQUENCE IF EXISTS agent_run_events_seq_seq"))
    op.drop_index(op.f('ix_agent_run_attempts_run_id'), table_name='agent_run_attempts')
    op.drop_table('agent_run_attempts')
    op.drop_table('agent_run_attachments')
    op.drop_index(op.f('ix_agent_runs_status'), table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_session_id'), table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_owner_user_id'), table_name='agent_runs')
    op.drop_table('agent_runs')
    op.drop_index(op.f('ix_agent_attachments_session_id'), table_name='agent_attachments')
    op.drop_index(op.f('ix_agent_attachments_owner_user_id'), table_name='agent_attachments')
    op.drop_table('agent_attachments')
    op.drop_index(op.f('ix_agent_sessions_owner_user_id'), table_name='agent_sessions')
    op.drop_table('agent_sessions')
    op.drop_table('agent_retention_jobs')
