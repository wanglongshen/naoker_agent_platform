from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task_chain import TaskChain, TaskChainStage


@dataclass
class Page:
    items: list[TaskChain]
    page: int
    page_size: int
    total: int


class TaskChainRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_chain(
        self,
        user_id: uuid.UUID,
        goal: str,
        input_payload: dict[str, Any] | None = None,
    ) -> TaskChain:
        chain = TaskChain(
            user_id=user_id,
            goal=goal,
            input_payload=input_payload or {},
            status="queued",
        )
        self.db.add(chain)
        await self.db.commit()
        return chain

    async def get_chain(
        self, chain_id: uuid.UUID, user_id: uuid.UUID | None = None
    ) -> TaskChain | None:
        stmt = select(TaskChain).where(TaskChain.id == chain_id)
        if user_id is not None:
            stmt = stmt.where(TaskChain.user_id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_chains(
        self, user_id: uuid.UUID, page: int = 1, page_size: int = 20
    ) -> Page:
        base = select(TaskChain).where(TaskChain.user_id == user_id)
        count_q = select(func.count()).select_from(base.subquery())
        total = (await self.db.execute(count_q)).scalar_one()
        result = await self.db.execute(
            base.order_by(TaskChain.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return Page(
            items=list(result.scalars().all()),
            page=page,
            page_size=page_size,
            total=total,
        )

    async def list_stages(self, chain_id: uuid.UUID) -> list[TaskChainStage]:
        result = await self.db.execute(
            select(TaskChainStage)
            .where(TaskChainStage.chain_id == chain_id)
            .order_by(TaskChainStage.seq)
        )
        return list(result.scalars().all())

    async def add_stage(
        self, chain_id: uuid.UUID, stage: str, seq: int
    ) -> TaskChainStage:
        item = TaskChainStage(chain_id=chain_id, stage=stage, seq=seq)
        self.db.add(item)
        await self.db.commit()
        return item

    async def update_stage(
        self, stage_id: uuid.UUID, **fields: Any
    ) -> TaskChainStage | None:
        stage = await self.db.get(TaskChainStage, stage_id)
        if stage is None:
            return None
        for key, value in fields.items():
            setattr(stage, key, value)
        await self.db.commit()
        return stage

    async def claim_next_chain(self) -> TaskChain | None:
        result = await self.db.execute(
            text(
                """
                UPDATE task_chains
                SET status = 'running', started_at = now(), updated_at = now()
                WHERE id = (
                    SELECT id FROM task_chains
                    WHERE status = 'queued'
                    ORDER BY created_at
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id
                """
            )
        )
        row = result.first()
        await self.db.commit()
        if row is None:
            return None
        refreshed = await self.db.execute(
            select(TaskChain)
            .where(TaskChain.id == row[0])
            .execution_options(populate_existing=True)
        )
        return refreshed.scalar_one_or_none()

    async def set_chain_status(
        self, chain_id: uuid.UUID, status: str, **fields: Any
    ) -> TaskChain | None:
        chain = await self.db.get(TaskChain, chain_id)
        if chain is None:
            return None
        chain.status = status
        for key, value in fields.items():
            setattr(chain, key, value)
        await self.db.commit()
        return chain
