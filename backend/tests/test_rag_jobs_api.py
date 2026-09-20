from __future__ import annotations

import uuid

import pytest

JOB_FIELDS = {
    "id",
    "library_id",
    "doc_id",
    "kind",
    "status",
    "total",
    "processed",
    "error_message",
    "created_at",
    "started_at",
    "finished_at",
}


@pytest.mark.anyio
async def test_jobs_list_and_detail(admin_client, admin_csrf, test_db):
    from app.repositories.rag_repository import RagRepository

    lib = (
        await admin_client.post(
            "/api/rag/libraries", json={"name": "任务查询库"}, headers=admin_csrf
        )
    ).json()["data"]
    async with test_db() as session:
        repo = RagRepository(session)
        job = await repo.create_job(
            library_id=uuid.UUID(lib["id"]),
            kind="upload",
            status="running",
            total=3,
            processed=1,
        )
        job_id = str(job.id)

    detail = (await admin_client.get(f"/api/rag/jobs/{job_id}")).json()["data"]
    assert set(detail) == JOB_FIELDS
    assert detail["status"] == "running" and detail["processed"] == 1
    assert detail["library_id"] == lib["id"] and detail["kind"] == "upload"
    assert detail["total"] == 3 and detail["error_message"] is None

    active = (
        await admin_client.get(f"/api/rag/jobs?library_id={lib['id']}&active=true")
    ).json()["data"]["items"]
    assert [item["id"] for item in active] == [job_id]

    all_jobs = (
        await admin_client.get(f"/api/rag/jobs?library_id={lib['id']}")
    ).json()["data"]["items"]
    assert [item["id"] for item in all_jobs] == [job_id]


@pytest.mark.anyio
async def test_jobs_active_filter_excludes_terminal(admin_client, admin_csrf, test_db):
    from app.repositories.rag_repository import RagRepository

    lib = (
        await admin_client.post(
            "/api/rag/libraries", json={"name": "终态任务库"}, headers=admin_csrf
        )
    ).json()["data"]
    async with test_db() as session:
        repo = RagRepository(session)
        running = await repo.create_job(
            library_id=uuid.UUID(lib["id"]),
            kind="upload",
            status="running",
            total=2,
            processed=1,
        )
        finished = await repo.create_job(
            library_id=uuid.UUID(lib["id"]),
            kind="upload",
            status="succeeded",
            total=1,
            processed=1,
        )
        running_id, finished_id = str(running.id), str(finished.id)

    active = (
        await admin_client.get(f"/api/rag/jobs?library_id={lib['id']}&active=true")
    ).json()["data"]["items"]
    assert [item["id"] for item in active] == [running_id]

    all_jobs = (
        await admin_client.get(f"/api/rag/jobs?library_id={lib['id']}")
    ).json()["data"]["items"]
    assert {item["id"] for item in all_jobs} == {running_id, finished_id}


@pytest.mark.anyio
async def test_jobs_detail_missing_returns_404(admin_client):
    resp = await admin_client.get(f"/api/rag/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404
