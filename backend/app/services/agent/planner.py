from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

from app.services.agent.llm import DeepSeekClient, RetryablePlannerError


class HttpRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["GET"] = "GET"
    url: HttpUrl


class ExtractWebContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl


class WebSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=5, ge=1, le=10)


class CalculatorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str = Field(min_length=1, max_length=200)


class FinishInput(BaseModel):
    model_config = ConfigDict(extra="allow")


class ReadFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str | None = Field(default=None, min_length=36, max_length=36)
    path: str | None = Field(default=None, min_length=1, max_length=500)
    attachment_id: str | None = Field(default=None, min_length=1, max_length=64)


class ListFilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str | None = Field(default=None, max_length=200)
    folder: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=10, ge=1, le=1000)


class WriteFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=50000)
    overwrite: bool = False


class EditFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str | None = Field(default=None, min_length=1, max_length=500)
    file_id: str | None = Field(default=None, min_length=36, max_length=36)
    old_str: str = Field(min_length=1, max_length=10000)
    new_str: str = Field(min_length=0, max_length=10000)


class FeishuReadDocInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_token: str = Field(min_length=1, max_length=200)


class FeishuCreateDocInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=50000)


class FeishuEditDocInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_token: str = Field(min_length=1, max_length=200)
    block_id: str = Field(min_length=1, max_length=200)
    new_content: str = Field(min_length=1, max_length=10000)


class FeishuShareDocInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_token: str = Field(min_length=1, max_length=200)
    permission: str = Field(min_length=1, max_length=50)


class FetchWebContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    requires_login: bool = False


class FetchPlatformSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["xiaohongshu", "douyin"]
    keyword: str = Field(min_length=1, max_length=50)
    max_results: int = Field(default=30, ge=1, le=50)


class PlanAction(BaseModel):
    type: Literal["web_search", "http_request", "extract_web_content", "calculator", "read_file", "write_file", "edit_file", "list_files", "fetch_web_content", "fetch_platform_search", "feishu_read_doc", "feishu_create_doc", "feishu_edit_doc", "feishu_share_doc", "finish"]
    input: dict[str, Any]


class PlannerResponse(BaseModel):
    thought_summary: str = Field(min_length=1, max_length=2000)
    action: PlanAction


class ResearchPlanner:
    def __init__(self) -> None:
        self.client = DeepSeekClient()

    async def next_action(
        self,
        goal: str,
        step_index: int,
        previous_observation: dict[str, Any] | None,
        session_history: list[dict[str, str]] | None = None,
        web_enabled: bool = True,
        final_step: bool = False,
        usage_sink: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        messages = self._build_messages(
            goal=goal,
            step_index=step_index,
            previous_observation=previous_observation,
            session_history=session_history,
            web_enabled=web_enabled,
            final_step=final_step,
        )
        full_text = ""
        async for chunk in self.client.stream_text(messages, usage_sink=usage_sink):
            full_text += chunk
        try:
            parsed = self.client._parse_json_content(full_text)
            normalized_plan = self._normalize_plan(parsed)
            validated = self._validate_plan(normalized_plan)
            return validated.model_dump(mode="json")
        except (ValueError, KeyError) as exc:
            raise RetryablePlannerError(f"invalid_planner_output: {exc}") from exc

    def _build_messages(
        self,
        goal: str,
        step_index: int,
        previous_observation: dict[str, Any] | None,
        session_history: list[dict[str, str]] | None = None,
        web_enabled: bool = True,
        final_step: bool = False,
        step_journal: list[str] | None = None,
    ) -> list[dict[str, str]]:
        if web_enabled:
            action_policy = (
                "允许的 action.type 有 web_search、http_request、extract_web_content、"
                "fetch_web_content（用浏览器渲染 JS 页面，适合抖音/小红书等动态网页，需 url；"
                "如需登录数据可设置 requires_login=true。若返回 login_expired=true，说明平台登录态已过期，"
                "告知用户\"登录态已过期，请打开平台登录中心重新扫码\"，不要反复重试）、"
                "fetch_platform_search（平台站内搜索：小红书或抖音，输入 platform/keyword/max_results，"
                "返回笔记/视频样本列表（标题/账号/链接/互动数）；涉及小红书或抖音平台研究时必须优先使用本工具，"
                "不能只用普通网页搜索替代（蓝图硬规则）；可多次搜索不同关键词累积样本）、"
                "calculator、"
                "list_files（列出或搜索\"我的文件\"中的文件，输入 keyword/folder/limit，返回文件元数据与 file_id）、"
                "read_file（读取文件内容；推荐传入 file_id；path 可为文件名或\"文件夹/文件名\"；支持模糊匹配；"
                "若返回多个候选请用 file_id 指定）、"
                "write_file（创建或覆盖 .md 文件并保存到\"我的文件\"，"
                "path 为\"文件夹/文件名.md\"或\"文件名.md\"，文件夹不存在会自动创建，已存在默认覆盖）、"
                "edit_file（修改文件，可用 file_id 或 path 定位，需 old_str、new_str，old_str 必须唯一）、"
                "feishu_read_doc（读取飞书文档，需 doc_token）、"
                "feishu_create_doc（创建飞书文档，需 title 和 content）、"
                "feishu_edit_doc（编辑飞书文档段落，需 doc_token、block_id、new_content）、"
                "feishu_share_doc（设置飞书文档共享权限，需 doc_token 和 permission）、"
                "以及 finish。"
                "当用户要求保存/写入/生成文件（如\"保存到\"、\"写到\"、\"存为\"、\"生成…文件\"）时，"
                "必须先调用 write_file 或 edit_file 把内容实际保存到\"我的文件\"，不得只输出内容；"
                "仅当文件确实已保存（或用户明确不需要保存）时才可选择 finish。"
            )
        else:
            action_policy = (
                "网络已禁用，禁止 web_search、http_request 和 extract_web_content；"
                "允许的 action.type 只有本地 calculator 和 finish。"
            )
        final_step_policy = (
            "这是最后一个允许步骤，必须选择 finish，禁止选择任何工具动作。"
            if final_step
            else ""
        )
        system_prompt = (
            "你是一个研究型 Agent 规划器。你必须只返回合法 JSON，且顶层只能包含 thought_summary 和 action 两个字段。\n"
            f"{action_policy}"
            f"{final_step_policy}"
            "所有 thought_summary 使用简体中文。不要输出 markdown 代码块或额外说明。"
            "已读取过的文件不要重复读取，直接基于已获得的内容继续；如需复核某段内容可用 edit_file 目标定位，不要整体重读。"
            "若目标文件已在近期工具结果中读取过，不要再声明\"我将先读取…\"，直接说明下一步调研或撰写动作。"
            "联网搜索不要重复：若近期工具结果已包含相同主题的搜索结果（如同一人物/事件/趋势的补充检索），"
            "直接基于已有结果继续，不要反复搜索同一主题；每个主题最多搜索 2 次，整个任务搜索合计不宜超过 6 次。"
        )

        observation_text = "None"
        if previous_observation is not None:
            observation_text = str(previous_observation)[:3000]

        history_block = self._format_session_history(session_history)

        journal_block = "无"
        if step_journal:
            journal_block = "\n".join(f"- {entry[:200]}" for entry in step_journal[-10:])

        user_prompt = (
            f"当前目标：{goal}\n"
            f"网络权限：{'开启' if web_enabled else '关闭'}\n"
            f"当前步数：{step_index}\n"
            f"是否最后一步：{'是，必须选择 finish' if final_step else '否'}\n"
            f"上一轮观察结果：{observation_text}\n"
            f"本任务已执行步骤：\n{journal_block}\n"
            f"会话历史：\n{history_block}\n"
            "你现在必须决定下一步唯一动作。"
            "若可直接回答，立即选择 finish。"
            "需要访问页面时，选择官方文档/网站/仓库，不选搜索页或工具类 API。"
            "示例：\n"
            '{"thought_summary":"分析需求后可直接回答","action":{"type":"finish","input":{}}}\n'
            '{"thought_summary":"需要搜索相关资料","action":{"type":"web_search","input":{"query":"关键词","max_results":5}}}\n'
            '{"thought_summary":"需读取文件内容","action":{"type":"read_file","input":{"path":"文档路径"}}}\n'
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _format_session_history(self, session_history: list[dict[str, str]] | None) -> str:
        if not session_history:
            return "无"

        lines: list[str] = []
        for index, item in enumerate(session_history, start=1):
            user_text = item.get("user", "")
            assistant_text = item.get("assistant", "")
            lines.append(f"{index}. 用户：{user_text}")
            lines.append(f"   助手：{assistant_text}")
        return "\n".join(lines)

    def _normalize_plan(self, raw_plan: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(raw_plan)
        action = normalized.get("action")
        if not isinstance(action, dict):
            return normalized

        action_type = action.get("type")
        action_input = action.get("input")

        if not isinstance(action_input, dict):
            action_input = {}

        if action_type == "finish":
            if "answer" not in action_input and isinstance(action.get("answer"), str):
                action_input["answer"] = action["answer"]
            if "answer" not in action_input and isinstance(normalized.get("answer"), str):
                action_input["answer"] = normalized["answer"]

        if action_type == "http_request":
            if "method" not in action_input and isinstance(action.get("method"), str):
                action_input["method"] = action["method"]
            if "url" not in action_input and isinstance(action.get("url"), str):
                action_input["url"] = action["url"]
            if "method" not in action_input and isinstance(normalized.get("method"), str):
                action_input["method"] = normalized["method"]
            if "url" not in action_input and isinstance(normalized.get("url"), str):
                action_input["url"] = normalized["url"]

        action["input"] = action_input
        normalized["action"] = action
        return normalized

    def _validate_plan(self, raw_plan: dict[str, Any]) -> PlannerResponse:
        try:
            parsed = PlannerResponse.model_validate(raw_plan)
        except ValidationError as exc:
            raise ValueError(f"Invalid planner output: {exc}") from exc

        input_models = {
            "web_search": WebSearchInput,
            "http_request": HttpRequestInput,
            "extract_web_content": ExtractWebContentInput,
            "calculator": CalculatorInput,
            "finish": FinishInput,
            "read_file": ReadFileInput,
            "write_file": WriteFileInput,
            "edit_file": EditFileInput,
            "list_files": ListFilesInput,
            "fetch_web_content": FetchWebContentInput,
            "fetch_platform_search": FetchPlatformSearchInput,
            "feishu_read_doc": FeishuReadDocInput,
            "feishu_create_doc": FeishuCreateDocInput,
            "feishu_edit_doc": FeishuEditDocInput,
            "feishu_share_doc": FeishuShareDocInput,
        }
        try:
            input_models[parsed.action.type].model_validate(parsed.action.input)
        except ValidationError as exc:
            raise RetryablePlannerError(f"invalid_tool_input: {exc}") from exc

        return parsed
