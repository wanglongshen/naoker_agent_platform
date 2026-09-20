from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest

from app.core.config import get_settings
from app.services.agent.llm import RetryablePlannerError
from app.services.agent.loop import AgentLoopService, _AttemptContext
from app.services.agent.planner import WriteFileInput
from app.services.agent.tool_executor import ToolExecutor
from app.services.agent.workflow_policy import WorkflowPolicy


def _ready_plan_service() -> tuple[AgentLoopService, object]:
    service = AgentLoopService()
    state = service._fallback_state
    state.rules = object()
    state.stage = "content"
    state.material_inventory_done = True
    state.research_ok = True
    state.version_number = "V2"
    return service, state


class TestRequiredSourceFiles:
    def test_extracts_explicit_sources_in_order_and_excludes_output(self):
        goal = (
            "先读取 brief/brief_test.md 和 QA.docx，再参考 brief/brief_test.md，"
            "最后保存到 brief/GAP_成毅传播方案_V2.md"
        )

        assert AgentLoopService._extract_required_source_files(goal) == [
            "brief/brief_test.md",
            "QA.docx",
        ]

    def test_read_receipt_must_match_required_source(self):
        service, state = _ready_plan_service()
        state.required_source_paths = ["brief/brief_test.md", "QA.docx"]
        state.read_receipts = [
            {
                "file_id": str(uuid.uuid4()),
                "path": "/brief/brief_test.md",
                "bytes": 2894,
                "sha256": "a" * 64,
                "source": "my_files",
            }
        ]

        assert service._missing_required_sources(state) == ["QA.docx"]


class TestBlueprintGates:
    @staticmethod
    def _write_plan(path: str = "brief/GAP_成毅传播方案_V2.md") -> dict:
        return {
            "thought_summary": "写入正式方案",
            "action": {"type": "write_file", "input": {"path": path, "content": "正文"}},
        }

    def test_inventory_gate_runs_before_other_write_gates(self):
        service, state = _ready_plan_service()
        state.material_inventory_done = False

        with pytest.raises(RetryablePlannerError, match="material_inventory_required"):
            service._enforce_stage_gate(self._write_plan())

    def test_required_read_gate_rejects_unread_named_file(self):
        service, state = _ready_plan_service()
        state.required_source_paths = ["brief/brief_test.md"]

        with pytest.raises(RetryablePlannerError, match="required_source_not_read"):
            service._enforce_stage_gate(self._write_plan())

    def test_research_gate_rejects_write_before_search(self):
        service, state = _ready_plan_service()
        state.research_ok = False

        with pytest.raises(RetryablePlannerError, match="research_required"):
            service._enforce_stage_gate(self._write_plan())

    def test_version_gate_requires_scanned_next_version(self):
        service, state = _ready_plan_service()

        with pytest.raises(RetryablePlannerError, match="version_mismatch"):
            service._enforce_stage_gate(self._write_plan("brief/GAP_成毅传播方案_V1.md"))

    def test_all_gates_pass_with_inventory_read_research_and_version(self):
        service, state = _ready_plan_service()
        state.required_source_paths = ["brief/brief_test.md"]
        state.read_receipts = [{"path": "/brief/brief_test.md"}]

        service._enforce_stage_gate(self._write_plan())

    def test_finish_rejects_unverified_save(self):
        service, state = _ready_plan_service()
        state.stage = "done"
        state.save_receipts = [{"path": "/brief/GAP_成毅传播方案_V2.md"}]

        with pytest.raises(RetryablePlannerError, match="save_not_verified"):
            service._enforce_stage_gate(
                {"thought_summary": "完成", "action": {"type": "finish", "input": {}}}
            )


class TestFileReceiptsAndOverwrite:
    async def test_read_file_returns_disk_bytes_sha_and_requested_path(self, monkeypatch, tmp_path):
        content = "# Brief\n真实正文"
        storage = tmp_path / "brief.md"
        storage.write_text(content, encoding="utf-8")
        file_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        file_obj = SimpleNamespace(
            id=file_id,
            owner_user_id=owner_id,
            original_filename="brief_test.md",
            media_type="text/markdown",
            storage_key=str(storage),
            size_bytes=1,
            sha256="stale-db-sha",
        )

        class FakeRepo:
            def __init__(self, session):
                pass

            async def get_by_owner_and_filename(self, owner, path):
                return file_obj

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory", lambda: FakeSession()
        )
        monkeypatch.setattr("app.services.agent.tool_executor.FileRepository", FakeRepo)

        receipt = await ToolExecutor()._read_file(
            {"path": "brief/brief_test.md"}, owner_id, False
        )
        raw = storage.read_bytes()
        assert receipt["file_id"] == str(file_id)
        assert receipt["path"] == "/brief/brief_test.md"
        assert receipt["bytes"] == len(raw)
        assert receipt["sha256"] == hashlib.sha256(raw).hexdigest()
        assert receipt["source"] == "my_files"
        assert receipt["content"] == raw.decode("utf-8")

    def test_write_file_model_defaults_to_no_overwrite(self):
        assert WriteFileInput(path="brief/a.md", content="x").overwrite is False

    async def test_existing_file_is_rejected_when_overwrite_omitted(self, monkeypatch):
        existing = SimpleNamespace(id=uuid.uuid4(), original_filename="existing.md")

        class Result:
            def scalar_one_or_none(self):
                return existing

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def execute(self, stmt):
                return Result()

        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory", lambda: FakeSession()
        )

        with pytest.raises(ValueError, match="file_already_exists"):
            await ToolExecutor()._write_file(
                {"path": "existing.md", "content": "new"}, uuid.uuid4()
            )


class TestWorkflowDiskShaCache:
    async def test_cache_refreshes_when_disk_changes_without_db_metadata_change(
        self, monkeypatch, tmp_path
    ):
        storage = tmp_path / "blueprint.md"
        storage.write_text("blueprint-v1", encoding="utf-8")
        file_obj = SimpleNamespace(storage_key=str(storage))
        policy = WorkflowPolicy()
        monkeypatch.setattr(policy, "_resolve_file", AsyncMock(return_value=file_obj))

        first = await policy._load_doc(AsyncMock(), uuid.uuid4(), "blueprint.md")
        first_sha = policy._cache["blueprint.md"]["sha256"]
        storage.write_text("blueprint-v2-with-new-content", encoding="utf-8")
        second = await policy._load_doc(AsyncMock(), uuid.uuid4(), "blueprint.md")

        assert first == "blueprint-v1"
        assert second == "blueprint-v2-with-new-content"
        assert policy._cache["blueprint.md"]["sha256"] != first_sha
        assert policy._cache["blueprint.md"]["sha256"] == hashlib.sha256(
            storage.read_bytes()
        ).hexdigest()

    async def test_doc_receipt_uses_disk_truth(self, monkeypatch, tmp_path):
        raw = "蓝图原文".encode("utf-8")
        storage = tmp_path / "blueprint.md"
        storage.write_bytes(raw)
        file_id = uuid.uuid4()
        file_obj = SimpleNamespace(id=file_id, storage_key=str(storage))
        policy = WorkflowPolicy()
        monkeypatch.setattr(policy, "_resolve_file", AsyncMock(return_value=file_obj))

        receipt = await policy.get_doc_receipt(
            AsyncMock(), uuid.uuid4(), "00_Agent规范与模板/脑壳儿_Agent运行蓝图_v1.1.md"
        )

        assert receipt == {
            "file_id": str(file_id),
            "path": "/00_Agent规范与模板/脑壳儿_Agent运行蓝图_v1.1.md",
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "source": "my_files",
        }


class TestSaveReadbackClosure:
    @staticmethod
    def _run_and_attempt():
        run_id = uuid.uuid4()
        attempt_id = uuid.uuid4()
        run = SimpleNamespace(
            id=run_id,
            session_id=uuid.uuid4(),
            goal="写方案保存到 brief/，最后告诉我保存结果",
            max_steps=3,
            web_enabled=True,
            attachments=[],
        )
        attempt = SimpleNamespace(id=attempt_id, attempt_number=1, status="running")
        return run, attempt

    async def _exercise(self, monkeypatch, *, readback_sha: str):
        service = AgentLoopService()
        run, attempt = self._run_and_attempt()
        ctx = _AttemptContext(run=run, attempt=attempt)
        digest = "b" * 64
        write_receipt = {
            "file_id": str(uuid.uuid4()),
            "filename": "GAP_成毅传播方案_V1.md",
            "path": "/brief/GAP_成毅传播方案_V1.md",
            "folder_path": "/brief",
            "bytes": 321,
            "sha256": digest,
            "source": "my_files",
            "action": "created",
        }
        plans = iter(
            [
                {
                    "thought_summary": "保存方案",
                    "action": {
                        "type": "write_file",
                        "input": {
                            "path": "brief/GAP_成毅传播方案_V1.md",
                            "content": "完整方案正文",
                        },
                    },
                },
                {
                    "thought_summary": "报告真实保存结果",
                    "action": {"type": "finish", "input": {"answer": "模型声称保存了别的.md"}},
                },
            ]
        )

        class FakeRepo:
            session = AsyncMock()

            async def is_cancel_requested(self, run_id):
                return False

            async def transition_attempt_status(self, *args, **kwargs):
                return True

            async def add_step(self, **kwargs):
                return None

        repo = FakeRepo()
        settings = get_settings()
        monkeypatch.setattr(settings, "workflow_docs_enabled", False)
        monkeypatch.setattr(settings, "fast_path_enabled", False)
        monkeypatch.setattr(settings, "merged_plan_thought_enabled", False)
        monkeypatch.setattr(service, "_commit_repo", AsyncMock())
        monkeypatch.setattr(service, "_persist_and_notify", AsyncMock())
        monkeypatch.setattr(service, "_build_session_history", AsyncMock(return_value=None))
        monkeypatch.setattr(service, "_read_attachment_context", AsyncMock(return_value=[]))
        monkeypatch.setattr(service, "_advance_workflow_stage", AsyncMock())
        monkeypatch.setattr(service, "_run_policy", lambda run, max_steps: (True, 3))
        monkeypatch.setattr(service, "_stream_planning", AsyncMock(side_effect=lambda *a: next(plans)))
        monkeypatch.setattr(
            service,
            "_stream_visible_thought_with_tool_interleave",
            AsyncMock(
                side_effect=[
                    ("正在保存", write_receipt),
                    ("正在核对", {"final_answer": "模型声称保存了别的.md"}),
                ]
            ),
        )
        monkeypatch.setattr(
            service.tool_executor,
            "_read_file",
            AsyncMock(
                return_value={
                    **write_receipt,
                    "bytes": 321,
                    "sha256": readback_sha,
                    "content": "完整方案正文",
                }
            ),
        )
        completed = AsyncMock()
        terminal = AsyncMock()
        monkeypatch.setattr(service, "_persist_successful_completion", completed)
        monkeypatch.setattr(service, "_persist_terminal_and_notify", terminal)

        await service._do_process_attempt(repo, ctx, owner_user_id=uuid.uuid4())
        return service, completed, terminal, write_receipt

    async def test_write_is_read_back_by_file_id_and_final_answer_is_deterministic(
        self, monkeypatch
    ):
        service, completed, terminal, receipt = await self._exercise(
            monkeypatch, readback_sha="b" * 64
        )

        service.tool_executor._read_file.assert_awaited_once_with(
            {"file_id": receipt["file_id"]}, ANY, False
        )
        terminal.assert_not_awaited()
        state = service._wf(completed.await_args.kwargs["ctx"].run.id)
        assert state.verified_save_receipts[0]["verification"] == (
            "readback_sha256_and_bytes_match"
        )
        answer = completed.await_args.kwargs["answer"]
        assert receipt["filename"] in answer
        assert receipt["path"] in answer
        assert "321 bytes" in answer
        assert receipt["sha256"] in answer
        assert "别的.md" not in answer

    async def test_sha_mismatch_never_marks_save_verified(self, monkeypatch):
        service, completed, terminal, _ = await self._exercise(
            monkeypatch, readback_sha="c" * 64
        )

        completed.assert_not_awaited()
        terminal.assert_awaited_once()
        assert terminal.await_args.args[2] == "run_failed"
        assert terminal.await_args.args[3]["error"] == "save_readback_mismatch"
        assert terminal.await_args.kwargs["failure_code"] == "save_readback_mismatch"
        state = service._wf(terminal.await_args.args[1].run.id)
        assert state.verified_save_receipts == []
        assert state.save_ok is False
