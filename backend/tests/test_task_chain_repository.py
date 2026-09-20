from __future__ import annotations

import uuid

import pytest


@pytest.mark.anyio
async def test_create_claim_and_stage_lifecycle(test_db):
    from app.models.rbac import User
    from app.repositories.task_chain_repository import TaskChainRepository

    async with test_db() as db:
        user = User(
            id=uuid.uuid4(),
            username=f"tc-{uuid.uuid4().hex[:8]}",
            display_name="Task Chain User",
            password_hash="x",
        )
        db.add(user)
        await db.commit()

        repo = TaskChainRepository(db)
        chain = await repo.create_chain(
            user_id=user.id, goal="写一份方案", input_payload={"brand": "X"}
        )
        assert chain.status == "queued"

        claimed = await repo.claim_next_chain()
        assert claimed is not None
        assert claimed.id == chain.id
        assert claimed.status == "running"
        assert await repo.claim_next_chain() is None

        stage = await repo.add_stage(chain_id=chain.id, stage="research_agenda", seq=1)
        await repo.update_stage(
            stage.id, status="succeeded", output_payload={"topics": ["a"]}
        )
        stages = await repo.list_stages(chain.id)
        assert stages[0].status == "succeeded"
        assert stages[0].output_payload == {"topics": ["a"]}


@pytest.mark.anyio
async def test_chain_status_list_and_owner_scoping(test_db):
    from app.models.rbac import User
    from app.repositories.task_chain_repository import TaskChainRepository

    async with test_db() as db:
        owner = User(
            id=uuid.uuid4(),
            username=f"tc-{uuid.uuid4().hex[:8]}",
            display_name="Owner",
            password_hash="x",
        )
        stranger = User(
            id=uuid.uuid4(),
            username=f"tc-{uuid.uuid4().hex[:8]}",
            display_name="Stranger",
            password_hash="x",
        )
        db.add_all([owner, stranger])
        await db.commit()

        repo = TaskChainRepository(db)
        chain = await repo.create_chain(
            user_id=owner.id, goal="写一份新品方案", input_payload={}
        )

        updated = await repo.set_chain_status(
            chain.id, "succeeded", final_answer="done", points_cost=3
        )
        assert updated is not None
        assert updated.status == "succeeded"
        assert updated.final_answer == "done"

        assert await repo.get_chain(chain.id) is not None
        assert await repo.get_chain(chain.id, user_id=owner.id) is not None
        assert await repo.get_chain(chain.id, user_id=stranger.id) is None

        page = await repo.list_chains(owner.id, page=1, page_size=10)
        assert page.total == 1
        assert page.items[0].id == chain.id
        assert (await repo.list_chains(stranger.id)).total == 0

        assert await repo.set_chain_status(uuid.uuid4(), "failed") is None
        assert await repo.update_stage(uuid.uuid4(), status="failed") is None
