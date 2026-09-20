import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.models.base import Base
from app.models.agent import (  # noqa: F401
    AgentAttachment,
    AgentRetentionJob,
    AgentRun,
    AgentRunAttachment,
    AgentRunAttempt,
    AgentRunEvent,
    AgentSession,
    AgentStep,
)
from app.models.rag import RagChunk, RagDocument, RagEvalSet  # noqa: F401
from app.models.rbac import Permission, Role, RolePermission, User, UserRole  # noqa: F401
from app.models.task_chain import TaskChain, TaskChainStage  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url = get_url()
    connectable = create_async_engine(
        url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
