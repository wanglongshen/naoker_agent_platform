"""split rag libraries into eight routed libraries

Revision ID: a4b8c2d6e9f1
Revises: f3a1c7d9e2b4
Create Date: 2026-09-17
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "a4b8c2d6e9f1"
down_revision = "f3a1c7d9e2b4"
branch_labels = None
depends_on = None

OLD_LIBRARY_ID = uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000001")
OLD_LIBRARY_NAME = "行业知识库"
OLD_LIBRARY_DESCRIPTION = "抖音电商官方方法论、投放手册与运营白皮书"
REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPO_ROOT / "var" / "kb_industry" / "manifest" / "manifest.json"

INSERT_LIBRARY = sa.text(
    "INSERT INTO rag_libraries (id, name, description, kind, visibility, retrieval_enabled)"
    " VALUES (:id, :name, :description, :kind, 'admins_only', true)"
    " ON CONFLICT (id) DO NOTHING"
)


def _manifest_index() -> dict[str, dict]:
    if not MANIFEST.exists():
        return {}
    payload = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    items = payload.get("items") if isinstance(payload, dict) else payload
    return {
        str(item.get("title") or ""): item
        for item in items or []
        if isinstance(item, dict)
    }


def upgrade() -> None:
    from app.services.rag.library_routing import LIBRARY_SEEDS, route_library

    bind = op.get_bind()
    for seed in LIBRARY_SEEDS:
        bind.execute(
            INSERT_LIBRARY,
            {
                "id": seed.id,
                "name": seed.name,
                "description": seed.description,
                "kind": seed.kind,
            },
        )

    manifest = _manifest_index()
    rows = bind.execute(sa.text("SELECT id, title, library_id FROM rag_documents")).all()
    for doc_id, title, library_id in rows:
        if library_id != OLD_LIBRARY_ID:
            continue
        item = manifest.get(str(title)) or {"title": title, "tags": []}
        route = route_library(item)
        bind.execute(
            sa.text("UPDATE rag_documents SET library_id = :library_id WHERE id = :doc_id"),
            {"library_id": route.library_id, "doc_id": doc_id},
        )

    remaining = bind.execute(
        sa.text("SELECT count(*) FROM rag_documents WHERE library_id = :library_id"),
        {"library_id": OLD_LIBRARY_ID},
    ).scalar_one()
    if remaining:
        raise RuntimeError(f"老库仍有 {remaining} 篇文档引用，中止删除")

    bind.execute(
        sa.text("DELETE FROM rag_libraries WHERE id = :library_id"),
        {"library_id": OLD_LIBRARY_ID},
    )


def downgrade() -> None:
    from app.services.rag.library_routing import LIBRARY_SEEDS

    bind = op.get_bind()
    bind.execute(
        INSERT_LIBRARY,
        {
            "id": OLD_LIBRARY_ID,
            "name": OLD_LIBRARY_NAME,
            "description": OLD_LIBRARY_DESCRIPTION,
            "kind": "industry",
        },
    )
    ids = [seed.id for seed in LIBRARY_SEEDS]
    bind.execute(
        sa.text(
            "UPDATE rag_documents SET library_id = :old_id"
            " WHERE library_id = ANY(:new_ids)"
        ),
        {"old_id": OLD_LIBRARY_ID, "new_ids": ids},
    )
