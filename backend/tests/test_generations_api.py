import uuid

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.main import app
from app.models.agent import AgentRun, AgentSession
from app.models.rbac import User

settings = get_settings()
TEST_ORIGIN = "http://localhost:3000"


@pytest.fixture
async def ordinary_user(test_db):
    async with test_db() as s:
        ph = PasswordHasher()
        user = User(
            username=f"ordinary_{uuid.uuid4().hex[:8]}",
            display_name="Ordinary User",
            password_hash=ph.hash("Password123"),
            status="active",
        )
        s.add(user)
        await s.commit()
        return user


@pytest.fixture
async def ordinary_client(test_db, ordinary_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Origin": TEST_ORIGIN},
    ) as ac:
        response = await ac.post(
            "/api/auth/login",
            json={"username": ordinary_user.username, "password": "Password123"},
        )
        assert response.status_code == 200
        yield ac


@pytest.fixture
async def admin_user(test_db):
    async with test_db() as db:
        user = await db.scalar(
            select(User).where(User.username == settings.initial_admin_username)
        )
        assert user is not None
        return user


@pytest.fixture
async def admin_client(test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Origin": TEST_ORIGIN},
    ) as ac:
        response = await ac.post(
            "/api/auth/login",
            json={
                "username": settings.initial_admin_username,
                "password": settings.initial_admin_password,
            },
        )
        assert response.status_code == 200
        yield ac


@pytest.fixture
async def csrf_headers(ordinary_client):
    resp = await ordinary_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    token = resp.json()["data"]["token"]
    return {"X-CSRF-Token": token}


async def _make_session(db, user_id, title="测试会话") -> AgentSession:
    session = AgentSession(owner_user_id=user_id, title=title)
    db.add(session)
    await db.flush()
    return session


async def _make_run(
    db,
    user_id,
    session: AgentSession,
    status="succeeded",
    goal="写一个杭州3日游方案",
) -> AgentRun:
    run = AgentRun(
        session_id=session.id,
        owner_user_id=user_id,
        goal=goal,
        status=status,
        max_steps=5,
        result={"final_answer": "这是最终方案", "answer_format": "markdown"},
    )
    db.add(run)
    await db.flush()
    return run


class TestGenerationsApi:
    @pytest.mark.anyio
    async def test_create_records_with_input_and_final_answer(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        assert resp.status_code == 200, resp.text
        log = resp.json()["data"]["log"]
        assert log["input_text"] == "写一个杭州3日游方案"
        assert log["final_answer"] == "这是最终方案"
        assert log["final_md_file_id"] is None
        assert log["folder_id"] is None
        assert log["status"] == "succeeded"
        assert log["feishu_doc_url"] == ""

    @pytest.mark.anyio
    async def test_create_rejects_incomplete_run(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session, status="running")
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "RUN_NOT_COMPLETED"

    @pytest.mark.anyio
    async def test_create_rejects_other_users_run(
        self, test_db, ordinary_client, ordinary_user, admin_client, admin_user, csrf_headers
    ):
        async with test_db() as db:
            session = await _make_session(db, admin_user.id)
            run = await _make_run(db, admin_user.id, session)
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_create_duplicate_rejected(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            await db.commit()
        body = {"session_id": str(session.id), "run_id": str(run.id)}
        assert (await ordinary_client.post("/api/generations", json=body, headers=csrf_headers)).status_code == 200
        resp2 = await ordinary_client.post("/api/generations", json=body, headers=csrf_headers)
        assert resp2.status_code == 409

    @pytest.mark.anyio
    async def test_list_by_folder(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.file import FileFolder

        async with test_db() as db:
            folder = FileFolder(owner_user_id=ordinary_user.id, name="项目A")
            db.add(folder)
            await db.flush()
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            from app.models.generation_log import GenerationLog

            log = GenerationLog(
                folder_id=folder.id,
                user_id=ordinary_user.id,
                session_id=session.id,
                run_id=run.id,
                input_text=run.goal,
                status="succeeded",
            )
            db.add(log)
            await db.commit()
        resp = await ordinary_client.get(
            f"/api/generations?folder_id={folder.id}"
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["logs"][0]["folder_name"] == "项目A"

    @pytest.mark.anyio
    async def test_list_requires_owner_folder(
        self, test_db, ordinary_client, ordinary_user, admin_client, admin_user
    ):
        from app.models.file import FileFolder

        async with test_db() as db:
            folder = FileFolder(owner_user_id=admin_user.id, name="别人项目")
            db.add(folder)
            await db.commit()
        resp = await ordinary_client.get(f"/api/generations?folder_id={folder.id}")
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_sync_feishu_on_enabled(
        self, test_db, ordinary_client, ordinary_user, csrf_headers, monkeypatch
    ):
        from unittest.mock import AsyncMock

        from app.services.feishu.service import FeishuService

        fake_create = AsyncMock(return_value={"url": "https://feishu.cn/docx/fakedoc"})
        monkeypatch.setattr(FeishuService, "create_document", fake_create)
        async with test_db() as db:
            user = await db.get(User, ordinary_user.id)
            user.sync_feishu_enabled = True
            await db.commit()
        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        assert resp.status_code == 200, resp.text
        log = resp.json()["data"]["log"]
        assert log["feishu_doc_url"] == "https://feishu.cn/docx/fakedoc"
        assert log["status"] == "succeeded"
        fake_create.assert_awaited_once()

    @pytest.mark.anyio
    async def test_sync_skipped_when_disabled(
        self, test_db, ordinary_client, ordinary_user, csrf_headers, monkeypatch
    ):
        from unittest.mock import AsyncMock

        from app.services.feishu.service import FeishuService

        fake_create = AsyncMock()
        monkeypatch.setattr(FeishuService, "create_document", fake_create)
        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        log = resp.json()["data"]["log"]
        assert log["feishu_doc_url"] == ""
        fake_create.assert_not_awaited()

    @pytest.mark.anyio
    async def test_sync_failure_keeps_succeeded(
        self, test_db, ordinary_client, ordinary_user, csrf_headers, monkeypatch
    ):
        from app.services.feishu.service import FeishuService

        async def boom(*args, **kwargs):
            raise RuntimeError("feishu api down")

        monkeypatch.setattr(FeishuService, "create_document", boom)
        async with test_db() as db:
            user = await db.get(User, ordinary_user.id)
            user.sync_feishu_enabled = True
            await db.commit()
        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        log = resp.json()["data"]["log"]
        assert log["status"] == "succeeded"
        assert "feishu api down" in log["error"]

    @pytest.mark.anyio
    async def test_plan_file_identified_from_events(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.agent import AgentRunEvent
        from app.models.file import FileFolder, FileObject

        async with test_db() as db:
            folder = FileFolder(owner_user_id=ordinary_user.id, name="项目A")
            db.add(folder)
            await db.flush()
            obj = FileObject(
                owner_user_id=ordinary_user.id,
                folder_id=folder.id,
                storage_key="var/files/placeholder",
                filename="方案.md",
                original_filename="方案.md",
                media_type="text/markdown",
                size_bytes=1024,
                sha256="0" * 64,
            )
            db.add(obj)
            await db.flush()
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            ev = AgentRunEvent(
                run_id=run.id,
                event_type="step_completed",
                payload={
                    "action_type": "write_file",
                    "observation": {"file_id": str(obj.id), "filename": "方案.md"},
                },
            )
            db.add(ev)
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        log = resp.json()["data"]["log"]
        assert log["final_md_file_id"] == str(obj.id)
        assert log["folder_id"] == str(folder.id)
        assert log["folder_name"] == "项目A"

    @pytest.mark.anyio
    async def test_quality_score_filled_from_review_event(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.agent import AgentRunEvent

        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            db.add(
                AgentRunEvent(
                    run_id=run.id,
                    seq=1,
                    event_type="quality_review_completed",
                    payload={
                        "file_id": "f1",
                        "rounds": 2,
                        "score": 86,
                        "pass": True,
                        "dims": [
                            {"name": "准确性", "pass": True, "reason": "数据核对无误"},
                            {"name": "完整性", "pass": True, "reason": "覆盖全部要点"},
                        ],
                    },
                )
            )
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        assert resp.status_code == 200, resp.text
        log = resp.json()["data"]["log"]
        assert log["quality_score"] == 86
        assert log["quality_review_rounds"] == 2

    @pytest.mark.anyio
    async def test_quality_score_uses_latest_review_event(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.agent import AgentRunEvent

        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            db.add(
                AgentRunEvent(
                    run_id=run.id,
                    seq=1,
                    event_type="quality_review_completed",
                    payload={"rounds": 1, "score": 55, "pass": False},
                )
            )
            db.add(
                AgentRunEvent(
                    run_id=run.id,
                    seq=2,
                    event_type="quality_review_completed",
                    payload={"rounds": 2, "score": 92, "pass": True},
                )
            )
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        log = resp.json()["data"]["log"]
        assert log["quality_score"] == 92
        assert log["quality_review_rounds"] == 2

    @pytest.mark.anyio
    async def test_quality_score_none_without_review_event(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        assert resp.status_code == 200, resp.text
        log = resp.json()["data"]["log"]
        assert log["quality_score"] is None
        assert log["quality_review_rounds"] == 0

    @pytest.mark.anyio
    async def test_me_sync_toggle(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        resp = await ordinary_client.put(
            "/api/me/sync-feishu", json={"enabled": True}, headers=csrf_headers
        )
        assert resp.status_code == 200, resp.text
        me = await ordinary_client.get("/api/auth/me")
        assert me.json()["data"]["sync_feishu_enabled"] is True


class TestGenerationTimeline:
    @pytest.mark.anyio
    async def test_timeline_assembles_events_in_order(
        self, test_db, ordinary_client, ordinary_user
    ):
        from app.models.agent import AgentRunEvent
        from app.models.generation_log import GenerationLog

        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            log = GenerationLog(
                folder_id=None,
                user_id=ordinary_user.id,
                session_id=session.id,
                run_id=run.id,
                input_text=run.goal,
                status="succeeded",
            )
            db.add(log)
            await db.flush()
            evs = [
                AgentRunEvent(run_id=run.id, event_type="visible_thought_completed",
                              payload={"step_index": 0, "text": "先查资料", "length": 4}),
                AgentRunEvent(run_id=run.id, event_type="step_completed",
                              payload={"step_index": 0, "action_type": "read_file",
                                       "tool_call": {"path": "docs/a.md"},
                                       "observation": {"file_id": "x", "filename": "a.md"},
                                       "step_duration_seconds": 1.5}),
                AgentRunEvent(run_id=run.id, event_type="answer_completed",
                              payload={"text": "最终方案", "length": 4}),
                AgentRunEvent(run_id=run.id, event_type="run_succeeded",
                              payload={"final_answer": "最终方案"}),
            ]
            db.add_all(evs)
            await db.commit()

        resp = await ordinary_client.get(f"/api/generations/{log.id}/timeline")
        assert resp.status_code == 200, resp.text
        steps = resp.json()["data"]["steps"]
        assert [s["type"] for s in steps] == ["thought", "tool", "answer", "terminal"]
        assert steps[0]["content"] == "先查资料"
        assert steps[1]["action_type"] == "read_file"
        assert steps[1]["input"]["path"] == "docs/a.md"
        assert "a.md" in steps[1]["observation"]
        assert steps[1]["duration_seconds"] == 1.5
        assert steps[2]["content"] == "最终方案"
        assert steps[3]["status"] == "succeeded"

    @pytest.mark.anyio
    async def test_timeline_failed_run_has_error(
        self, test_db, ordinary_client, ordinary_user
    ):
        from app.models.agent import AgentRunEvent
        from app.models.generation_log import GenerationLog

        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            log = GenerationLog(
                folder_id=None, user_id=ordinary_user.id, session_id=session.id,
                run_id=run.id, input_text=run.goal, status="succeeded",
            )
            db.add(log)
            await db.flush()
            db.add(AgentRunEvent(run_id=run.id, event_type="run_failed",
                                 payload={"error": "max_steps_exceeded"}))
            await db.commit()
        resp = await ordinary_client.get(f"/api/generations/{log.id}/timeline")
        steps = resp.json()["data"]["steps"]
        assert steps[0]["type"] == "terminal"
        assert steps[0]["status"] == "failed"
        assert steps[0]["error"] == "max_steps_exceeded"

    @pytest.mark.anyio
    async def test_timeline_other_users_log_forbidden(
        self, test_db, ordinary_client, ordinary_user, admin_client, admin_user
    ):
        from app.models.generation_log import GenerationLog

        async with test_db() as db:
            session = await _make_session(db, admin_user.id)
            run = await _make_run(db, admin_user.id, session)
            log = GenerationLog(
                folder_id=None, user_id=admin_user.id, session_id=session.id,
                run_id=run.id, input_text=run.goal, status="succeeded",
            )
            db.add(log)
            await db.commit()
        resp = await ordinary_client.get(f"/api/generations/{log.id}/timeline")
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_timeline_no_events_empty(self, test_db, ordinary_client, ordinary_user):
        from app.models.generation_log import GenerationLog

        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            log = GenerationLog(
                folder_id=None, user_id=ordinary_user.id, session_id=session.id,
                run_id=run.id, input_text=run.goal, status="succeeded",
            )
            db.add(log)
            await db.commit()
        resp = await ordinary_client.get(f"/api/generations/{log.id}/timeline")
        assert resp.json()["data"]["steps"] == []

    @pytest.mark.anyio
    async def test_timeline_observation_truncated(
        self, test_db, ordinary_client, ordinary_user
    ):
        from app.models.agent import AgentRunEvent
        from app.models.generation_log import GenerationLog

        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            log = GenerationLog(
                folder_id=None, user_id=ordinary_user.id, session_id=session.id,
                run_id=run.id, input_text=run.goal, status="succeeded",
            )
            db.add(log)
            await db.flush()
            db.add(AgentRunEvent(run_id=run.id, event_type="step_completed",
                                 payload={"step_index": 0, "action_type": "web_search",
                                          "tool_call": {"query": "测试"},
                                          "observation": "x" * 2000,
                                          "step_duration_seconds": 0.1}))
            await db.commit()
        resp = await ordinary_client.get(f"/api/generations/{log.id}/timeline")
        obs = resp.json()["data"]["steps"][0]["observation"]
        assert len(obs) <= 500

    @pytest.mark.anyio
    async def test_timeline_dict_observation_without_whitelist_keys_hidden(
        self, test_db, ordinary_client, ordinary_user
    ):
        from app.models.agent import AgentRunEvent
        from app.models.generation_log import GenerationLog

        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            log = GenerationLog(
                folder_id=None, user_id=ordinary_user.id, session_id=session.id,
                run_id=run.id, input_text=run.goal, status="succeeded",
            )
            db.add(log)
            await db.flush()
            db.add(AgentRunEvent(run_id=run.id, event_type="step_completed",
                                 payload={"step_index": 0, "action_type": "fetch_platform_search",
                                          "tool_call": {"query": "测试"},
                                          "observation": {"samples": [{"title": "秘密内容"}]},
                                          "step_duration_seconds": 0.1}))
            await db.commit()
        resp = await ordinary_client.get(f"/api/generations/{log.id}/timeline")
        obs = resp.json()["data"]["steps"][0]["observation"]
        assert obs == ""
