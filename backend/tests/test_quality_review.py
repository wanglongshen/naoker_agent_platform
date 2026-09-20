import logging
import uuid

import pytest

from app.models.agent import AgentRun, AgentRunAttempt
from app.services.agent.loop import AgentLoopService, _AttemptContext, _RunWorkflowState


async def _nop(*_a, **_k):
    return None


def _make_ctx(goal: str = "写一份小红书种草方案") -> _AttemptContext:
    run = AgentRun(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        goal=goal,
        owner_user_id=uuid.uuid4(),
        status="running",
        max_steps=5,
    )
    attempt = AgentRunAttempt(
        id=uuid.uuid4(), run_id=run.id, worker_id="w", attempt_number=1, status="running"
    )
    return _AttemptContext(run=run, attempt=attempt)


REVIEW_TEXT = """```json
{"score": 62, "pass": false, "dims": [
  {"name": "完整性", "pass": true, "reason": "模块齐全"},
  {"name": "可落地性", "pass": false, "reason": "预算模块无具体金额"},
  {"name": "数据支撑", "pass": true, "reason": "引用调研数据"},
  {"name": "专业度", "pass": false, "reason": "存在空洞套话"}
]}
```"""


class TestReviewParse:
    def test_parse_review_result_extracts_score_and_dims(self):
        from app.services.agent.quality_review import parse_review_result
        result = parse_review_result(REVIEW_TEXT)
        assert result["score"] == 62
        assert result["pass"] is False
        assert len(result["dims"]) == 4
        assert result["dims"][1]["name"] == "可落地性"
        assert result["dims"][1]["pass"] is False

    def test_parse_review_result_fallback_on_garbage(self):
        from app.services.agent.quality_review import parse_review_result
        result = parse_review_result("完全不是 JSON 的输出")
        assert result["score"] == 0
        assert result["pass"] is False

    def test_extract_criteria_default_when_no_scorecard(self):
        from app.services.agent.quality_review import extract_criteria
        criteria = extract_criteria("# 普通文档\n无评分卡\n")
        assert "完整性" in criteria and "可落地性" in criteria
        assert "数据支撑" in criteria and "专业度" in criteria

    def test_extract_criteria_from_blueprint_scorecard(self):
        from app.services.agent.quality_review import extract_criteria
        blueprint = "# 规范\n## 质量评分卡\n完整性：全部模块有实质内容。\n可落地性：预算必须有数字。\n"
        criteria = extract_criteria(blueprint)
        assert "完整性" in criteria and "可落地性" in criteria

    def test_build_review_messages_contains_adversarial_role_and_content(self):
        from app.services.agent.quality_review import build_review_messages
        msgs = build_review_messages("写方案", "文件正文内容", "完整性：全部模块有实质内容。", 1)
        system = msgs[0]["content"]
        assert "评审" in system and "找出所有问题" in system
        assert "文件正文内容" in msgs[-1]["content"]


class TestQualityReviewFileIdResolution:
    """新建文件的 write_file input 里只有 path（非 UUID），质检必须改用
    成功 observation 里的真实 file_id，否则读回失败、质检静默不执行。"""

    @pytest.mark.anyio
    async def test_execute_node_starts_review_with_observation_file_id(self, monkeypatch):
        service = AgentLoopService()
        ctx = _make_ctx()
        file_id = str(uuid.uuid4())
        observation = {
            "file_id": file_id,
            "filename": "方案_V1.md",
            "path": "方案_V1.md",
            "sha256": "a" * 64,
            "bytes": 18,
            "source": "agent",
            "action": "write_file",
        }

        class FakeRepo:
            def __init__(self):
                self.steps = []

            async def add_step(self, **kwargs):
                self.steps.append(kwargs)

        repo = FakeRepo()
        runtime = {
            "repo": repo,
            "ctx": ctx,
            "owner_user_id": ctx.run.owner_user_id,
            "is_super_admin": False,
        }
        state = {
            "pending_action": {
                "action": {"type": "write_file", "input": {"path": "方案_V1.md"}},
                "thought_summary": "写入方案文件",
            },
            "step_index": 0,
            "workflow": {},
            "previous_observation": None,
            "web_enabled": False,
            "pre_generated_thought": None,
        }

        read_file_ids: list[str] = []

        async def fake_stream(*_a, **_k):
            return "即将写入方案文件", dict(observation)

        async def fake_read_file(payload, owner_user_id, is_super_admin):
            return {"sha256": observation["sha256"], "bytes": observation["bytes"]}

        async def fake_read_for_review(repo, fid, owner_user_id, is_super_admin, run_id=None):
            read_file_ids.append(str(fid))
            try:
                uuid.UUID(str(fid))
            except ValueError:
                return None
            return "方案正文内容"

        events: list[tuple[str, dict]] = []

        async def fake_persist(repo, ctx, event_type, payload):
            events.append((event_type, payload))

        async def fake_complete(messages):
            return REVIEW_TEXT

        async def fake_blueprint(repo, run_id):
            return ""

        monkeypatch.setattr(service, "_stream_visible_thought_with_tool_interleave", fake_stream)
        monkeypatch.setattr(service.tool_executor, "_read_file", fake_read_file)
        monkeypatch.setattr(service, "_read_file_content_for_review", fake_read_for_review)
        monkeypatch.setattr(service, "_load_blueprint_full", fake_blueprint)
        monkeypatch.setattr(service.llm_client, "complete", fake_complete)
        monkeypatch.setattr(service, "_persist_and_notify", fake_persist)
        monkeypatch.setattr(service, "_record_observation", lambda *_a, **_k: None)
        monkeypatch.setattr(service, "_commit_repo", _nop)

        await service._do_node_execute(state, runtime)

        assert read_file_ids == [file_id], (
            "write_file 成功后质检必须用 observation.file_id（UUID）读回文件，而不是 input.path"
        )
        started = [payload for name, payload in events if name == "quality_review_started"]
        assert started, "新建文件写入成功后必须产生 quality_review_started 事件"
        assert started[0]["file_id"] == file_id

    @pytest.mark.anyio
    async def test_path_fallback_without_uuid_warns_instead_of_silent_skip(
        self, monkeypatch, caplog
    ):
        service = AgentLoopService()
        ctx = _make_ctx()
        st = _RunWorkflowState()
        events: list[tuple[str, dict]] = []

        async def fake_persist(repo, ctx, event_type, payload):
            events.append((event_type, payload))

        monkeypatch.setattr(service, "_persist_and_notify", fake_persist)

        with caplog.at_level(logging.WARNING, logger="app.services.agent.loop"):
            review = await service._run_quality_review(
                None,
                ctx,
                {"type": "write_file", "input": {"path": "方案_V1.md"}},
                st,
            )

        assert review is None
        assert events == [], "无法解析 UUID 的路径不应产生质检事件"
        messages = [record.getMessage() for record in caplog.records]
        assert any("方案_V1.md" in message for message in messages), (
            "路径无法解析 UUID 时必须留下告警，让未评审可观测"
        )
        assert any(str(ctx.run.id) in message for message in messages), "告警必须带 run_id"

    @pytest.mark.anyio
    async def test_input_file_id_fallback_still_used_without_observation(self, monkeypatch):
        service = AgentLoopService()
        ctx = _make_ctx()
        st = _RunWorkflowState()
        file_id = str(uuid.uuid4())
        captured: list[str] = []

        async def fake_read_for_review(repo, fid, owner_user_id, is_super_admin, run_id=None):
            captured.append(str(fid))
            return "正文"

        async def fake_persist(repo, ctx, event_type, payload):
            return None

        async def fake_complete(messages):
            return REVIEW_TEXT

        async def fake_blueprint(repo, run_id):
            return ""

        monkeypatch.setattr(service, "_read_file_content_for_review", fake_read_for_review)
        monkeypatch.setattr(service, "_persist_and_notify", fake_persist)
        monkeypatch.setattr(service, "_load_blueprint_full", fake_blueprint)
        monkeypatch.setattr(service.llm_client, "complete", fake_complete)

        await service._run_quality_review(
            None,
            ctx,
            {"type": "edit_file", "input": {"file_id": file_id}},
            st,
            observation=None,
        )

        assert captured == [file_id], "没有 observation 时仍应回退到 action.input.file_id"
