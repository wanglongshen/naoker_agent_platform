import pytest


class TestPlanSummary:
    @pytest.mark.anyio
    async def test_build_plan_summary_extracts_modules_and_sections(self):
        from app.services.agent.plan_structure import build_plan_summary

        blueprint = (
            "# 矩阵号规范\n"
            "## 3. 正式方案默认结构\n"
            "方案必须包含以下模块：\n"
            "- 项目背景与目标\n"
            "- 竞品与市场分析\n"
            "- 预算与排期\n"
        )
        summary = build_plan_summary(blueprint)
        assert "矩阵号规范" in summary
        assert "项目背景与目标" in summary
        assert "预算与排期" in summary
        assert len(summary) < 600

    @pytest.mark.anyio
    async def test_build_plan_summary_empty_returns_empty(self):
        from app.services.agent.plan_structure import build_plan_summary
        assert build_plan_summary("") == ""
        assert build_plan_summary("   \n  ") == ""


class TestQualityInjectionHints:
    def test_hints_cover_project_skeleton_and_research(self):
        from app.services.agent.loop import _quality_injection_hints

        hints = _quality_injection_hints(
            goal="写方案",
            project_name="项目A",
            skeleton="## 一、前策调研",
            researched=False,
        )
        assert "项目A" in hints
        assert "骨架" in hints
        assert "先调研" in hints

    def test_research_hint_only_for_plan_goals(self):
        from app.services.agent.loop import _quality_injection_hints

        plan_hints = _quality_injection_hints(
            goal="写方案", project_name="", skeleton="", researched=False, plan_goal=True
        )
        assert "先调研" in plan_hints

        non_plan_hints = _quality_injection_hints(
            goal="翻译这段英文", project_name="", skeleton="", researched=False, plan_goal=False
        )
        assert "先调研" not in non_plan_hints


class TestQualityCheck:
    @pytest.mark.anyio
    async def test_quality_check_flags_short_module_and_missing_budget(self):
        from app.services.agent.plan_structure import quality_check

        content = (
            "# 方案\n"
            "## 项目背景\n太短了。\n"
            "## 预算与排期\n"  # 标题含预算但无数值
            "根据实际情况调整。\n"
        )
        fails = quality_check(content, ["项目背景", "预算与排期"], min_chars=20)
        joined = "\n".join(fails)
        assert any("字数" in f or "太短" in f or "项目背景" in f for f in fails), joined
        assert any("预算" in f and ("数字" in f or "数据" in f) for f in fails), joined

    @pytest.mark.anyio
    async def test_quality_check_passes_good_content(self):
        from app.services.agent.plan_structure import quality_check

        content = (
            "# 方案\n"
            "## 项目背景\n" + "这是一段足够长的背景描述。" * 20 + "\n"
            "## 预算与排期\n首月预算 50000 元，排期 3 周。\n"
            "预算明细：投流 20000 元，达人 15000 元，物料 10000 元，机动 5000 元。\n"
        )
        fails = quality_check(content, ["项目背景", "预算与排期"], min_chars=50)
        assert fails == []

    @pytest.mark.anyio
    async def test_quality_check_detects_hollow_phrases(self):
        from app.services.agent.plan_structure import quality_check

        content = "## 执行策略\n本方案将全面赋能业务增长，实现跨越式发展。\n"
        fails = quality_check(content, ["执行策略"], min_chars=10)
        assert any("空洞" in f or "套话" in f or "赋能" in f for f in fails)


class TestResearchGate:
    def _run_and_attempt(self, goal):
        import uuid
        from types import SimpleNamespace

        run = SimpleNamespace(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            goal=goal,
            max_steps=4,
            web_enabled=True,
            attachments=[],
        )
        attempt = SimpleNamespace(id=uuid.uuid4(), attempt_number=1, status="running")
        return run, attempt

    async def _exercise(self, monkeypatch, *, goal, plans, execute):
        import uuid
        from unittest.mock import AsyncMock

        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()
        run, attempt = self._run_and_attempt(goal)
        ctx = _AttemptContext(run=run, attempt=attempt)

        class FakeStream:
            async def stream_text(self, messages, **kwargs):
                yield "我会先查看相关公开资料"

        monkeypatch.setattr(service, "llm_client", FakeStream())

        # 必须 patch loop 模块级 settings（loop.py 绑定 import 时的单例实例），
        # 而非执行时 get_settings()——test_alembic_config 的 cache_clear 会换新实例，
        # 全量顺序下两者不一致导致 monkeypatch 失效（workflow_docs_enabled 走 .env 真值）
        import app.services.agent.loop as _loop_module

        settings = _loop_module.settings
        monkeypatch.setattr(settings, "workflow_docs_enabled", False)
        monkeypatch.setattr(settings, "fast_path_enabled", False)
        monkeypatch.setattr(settings, "merged_plan_thought_enabled", False)

        class FakeRepo:
            session = AsyncMock()

            async def is_cancel_requested(self, run_id):
                return False

            async def transition_attempt_status(self, *args, **kwargs):
                return True

            async def add_step(self, **kwargs):
                return None

        repo = FakeRepo()

        executed: list[str] = []

        async def execute_wrapper(action, **kwargs):
            executed.append(action.get("type"))
            return execute(action, **kwargs)

        monkeypatch.setattr(service.tool_executor, "execute", execute_wrapper)
        monkeypatch.setattr(
            service.tool_executor,
            "_read_file",
            AsyncMock(
                return_value={
                    "bytes": 321,
                    "sha256": "b" * 64,
                    "content": "完整方案正文",
                }
            ),
        )

        events = []

        async def capture(repo_, ctx_, event_type, payload):
            events.append((event_type, dict(payload)))

        monkeypatch.setattr(service, "_persist_and_notify", capture)
        monkeypatch.setattr(service, "_commit_repo", AsyncMock())
        monkeypatch.setattr(service, "_build_session_history", AsyncMock(return_value=None))
        monkeypatch.setattr(service, "_read_attachment_context", AsyncMock(return_value=[]))
        monkeypatch.setattr(service, "_advance_workflow_stage", AsyncMock())
        monkeypatch.setattr(service, "_run_policy", lambda run, max_steps: (True, 4))
        plan_iter = iter(plans)
        monkeypatch.setattr(
            service, "_stream_planning", AsyncMock(side_effect=lambda *a: next(plan_iter))
        )

        completed = AsyncMock()
        monkeypatch.setattr(service, "_persist_successful_completion", completed)

        await service._do_process_attempt(repo, ctx, owner_user_id=uuid.uuid4())
        return service, ctx, completed, executed, events

    def _write_receipt(self):
        import uuid

        return {
            "file_id": str(uuid.uuid4()),
            "filename": "品牌年度方案.md",
            "path": "/方案/品牌年度方案.md",
            "folder_path": "/方案",
            "bytes": 321,
            "sha256": "b" * 64,
            "source": "my_files",
            "action": "created",
        }

    def _write_plan(self):
        return {
            "thought_summary": "保存方案",
            "action": {
                "type": "write_file",
                "input": {
                    "path": "方案/品牌年度方案.md",
                    "content": "完整方案正文",
                },
            },
        }

    def _finish_plan(self):
        return {
            "thought_summary": "完成",
            "action": {"type": "finish", "input": {"answer": "方案已生成"}},
        }

    async def test_plan_goal_write_file_without_research_is_blocked(self, monkeypatch):
        service, ctx, completed, executed, events = await self._exercise(
            monkeypatch,
            goal="为品牌撰写一份年度传播方案",
            plans=[self._write_plan(), self._finish_plan()],
            execute=lambda action, **kw: {"error": "should_not_run"},
        )

        assert executed == []
        completed.assert_awaited_once()
        gate_events = [
            p
            for (t, p) in events
            if t == "tool_completed"
            and (p.get("observation") or {}).get("error") == "research_required"
        ]
        assert gate_events, "research_required 观察未通过 tool_completed 事件下发"
        state = service._wf(ctx.run.id)
        assert any("research_required" in obs for obs in state.observation_history)

    async def test_web_search_unlocks_write_file(self, monkeypatch):
        service, ctx, completed, executed, events = await self._exercise(
            monkeypatch,
            goal="为品牌撰写一份年度传播方案并保存",
            plans=[
                {
                    "thought_summary": "先搜索案例",
                    "action": {"type": "web_search", "input": {"query": "品牌案例"}},
                },
                self._write_plan(),
                self._finish_plan(),
            ],
            execute=lambda action, **kw: (
                {"query": "品牌案例", "results": [{"title": "案例A"}], "total": 1}
                if action["type"] == "web_search"
                else self._write_receipt()
            ),
        )

        assert executed == ["web_search", "write_file"]
        assert ctx.researched is True
        completed.assert_awaited_once()
        assert not any(
            (p.get("observation") or {}).get("error") == "research_required"
            for (_t, p) in events
        )

    async def test_exempt_goal_with_existing_materials_is_allowed(self, monkeypatch):
        service, ctx, completed, executed, events = await self._exercise(
            monkeypatch,
            goal="基于已有资料整理一份投放方案",
            plans=[self._write_plan(), self._finish_plan()],
            execute=lambda action, **kw: self._write_receipt(),
        )

        assert executed == ["write_file"]
        completed.assert_awaited_once()

    async def test_non_plan_goal_write_file_is_allowed(self, monkeypatch):
        service, ctx, completed, executed, events = await self._exercise(
            monkeypatch,
            goal="整理会议纪要",
            plans=[self._write_plan(), self._finish_plan()],
            execute=lambda action, **kw: self._write_receipt(),
        )

        assert executed == ["write_file"]
        completed.assert_awaited_once()
