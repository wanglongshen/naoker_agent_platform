from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

METHOD_TITLE = "巨量千川投放宝典"
RULE_TITLE = "精选联盟变更公示"
OTHER_TITLE = "创作者服务中心功能介绍"


def _item(title: str, file_name: str, sha256: str, **extra) -> dict:
    item = {
        "id": f"kb-{sha256}",
        "title": title,
        "file": file_name,
        "char_count": 1200,
        "pages_estimate": 2,
        "tags": [],
        "view_count": 3,
        "update_timestamp": "2025-09-01 10:00:00",
        "source_url": "https://school.jinritemai.com/doudian/web/article/1",
        "source_site": "抖音电商官方学习中心",
        "source_type": "course",
        "sha256": sha256,
    }
    item.update(extra)
    return item


def _write_manifest(path: Path, items: list[dict], **summary) -> None:
    payload = {
        "summary": {"count": len(items), "chars": 3600, **summary},
        "items": items,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_material(tmp_path: Path) -> dict[str, Path]:
    manifest_dir = tmp_path / "manifest"
    manifest_dir.mkdir()
    source_dir = tmp_path / "markdown"
    source_dir.mkdir()
    for file_name in ("method.md", "rules.md", "other.md"):
        (source_dir / file_name).write_text("# 素材\n\n正文", encoding="utf-8")

    method = _item(METHOD_TITLE, "method.md", "sha-method", tags=["投放"])
    rules = _item(RULE_TITLE, "rules.md", "sha-rules")
    other = _item(OTHER_TITLE, "other.md", "sha-other")
    all_manifest = manifest_dir / "manifest.json"
    core_manifest = manifest_dir / "manifest-core.json"
    _write_manifest(all_manifest, [method, rules, other])
    _write_manifest(core_manifest, [method])
    return {"all": all_manifest, "core": core_manifest}


async def _create_library(admin_client, admin_csrf, name: str) -> str:
    resp = await admin_client.post(
        "/api/rag/libraries", json={"name": name}, headers=admin_csrf
    )
    assert resp.status_code == 200
    return resp.json()["data"]["id"]


def test_kb_industry_root_points_to_repo_root():
    from app.api import rag as rag_api

    expected = REPO_ROOT / "var" / "kb_industry"
    assert rag_api.kb_industry_root() == expected
    assert rag_api.kb_manifest_path("core") == expected / "manifest" / "manifest-core.json"
    assert rag_api.kb_manifest_path("all") == expected / "manifest" / "manifest.json"


@pytest.mark.anyio
async def test_import_scope_and_category_filters(
    admin_client, admin_csrf, test_db, tmp_path, monkeypatch
):
    from app.api import rag as rag_api
    from app.repositories.rag_repository import RagRepository

    manifests = _write_material(tmp_path)
    monkeypatch.setattr(
        rag_api, "kb_manifest_path", lambda scope: manifests.get(scope, manifests["all"])
    )

    lib_id = await _create_library(admin_client, admin_csrf, "导入筛选库")

    core = await admin_client.post(
        f"/api/rag/libraries/{lib_id}/import",
        json={"scope": "core"},
        headers=admin_csrf,
    )
    assert core.status_code == 200
    assert core.json()["data"]["queued"] == 1

    expected_root = str(REPO_ROOT / "var" / "kb_industry" / "markdown")
    async with test_db() as session:
        repo = RagRepository(session)
        job = await repo.get_job(uuid.UUID(core.json()["data"]["job_id"]))
        assert job.payload["scope"] == "core"
        assert job.payload["category"] is None
        assert job.payload["markdown_root"] == expected_root
        assert [item["sha256"] for item in job.payload["items"]] == ["sha-method"]

    cases = {
        "methodology": "sha-method",
        "rules": "sha-rules",
        "other": "sha-other",
    }
    for category, sha256 in cases.items():
        resp = await admin_client.post(
            f"/api/rag/libraries/{lib_id}/import",
            json={"scope": "all", "category": category},
            headers=admin_csrf,
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["queued"] == 1
        async with test_db() as session:
            repo = RagRepository(session)
            job = await repo.get_job(uuid.UUID(body["job_id"]))
            assert job.payload["category"] == category
            assert [item["sha256"] for item in job.payload["items"]] == [sha256]

    unfiltered = await admin_client.post(
        f"/api/rag/libraries/{lib_id}/import",
        json={"scope": "all"},
        headers=admin_csrf,
    )
    assert unfiltered.status_code == 200
    assert unfiltered.json()["data"]["queued"] == 3

    detail = (
        await admin_client.get(f"/api/rag/jobs/{unfiltered.json()['data']['job_id']}")
    ).json()["data"]
    assert detail["kind"] == "import"
    assert detail["total"] == 3
    assert detail["status"] == "queued"


@pytest.mark.anyio
async def test_import_missing_manifest_returns_400(
    admin_client, admin_csrf, tmp_path, monkeypatch
):
    from app.api import rag as rag_api

    monkeypatch.setattr(rag_api, "kb_manifest_path", lambda scope: tmp_path / "nope.json")

    lib_id = await _create_library(admin_client, admin_csrf, "缺清单库")
    resp = await admin_client.post(
        f"/api/rag/libraries/{lib_id}/import",
        json={"scope": "core"},
        headers=admin_csrf,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "MANIFEST_NOT_FOUND"


@pytest.mark.anyio
async def test_import_no_matching_material_returns_400(
    admin_client, admin_csrf, tmp_path, monkeypatch
):
    from app.api import rag as rag_api

    manifest_dir = tmp_path / "manifest"
    manifest_dir.mkdir()
    manifest = manifest_dir / "manifest-core.json"
    _write_manifest(manifest, [_item(METHOD_TITLE, "method.md", "only-method")])
    monkeypatch.setattr(rag_api, "kb_manifest_path", lambda scope: manifest)

    lib_id = await _create_library(admin_client, admin_csrf, "空素材库")
    resp = await admin_client.post(
        f"/api/rag/libraries/{lib_id}/import",
        json={"scope": "core", "category": "rules"},
        headers=admin_csrf,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "NO_MATERIAL"


@pytest.mark.anyio
async def test_import_missing_library_returns_404(admin_client, admin_csrf):
    resp = await admin_client.post(
        f"/api/rag/libraries/{uuid.uuid4()}/import",
        json={"scope": "core"},
        headers=admin_csrf,
    )
    assert resp.status_code == 404
