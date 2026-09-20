import asyncio, uuid, hashlib
from pathlib import Path
from sqlalchemy import select

async def main():
    from app.db.session import async_session_factory
    from app.models.file import FileObject, FileFolder
    from app.models.rbac import User

    async with async_session_factory() as s:
        admin = (await s.execute(select(User).where(User.username == "admin"))).scalar_one()
        uid = admin.id
        print(f"Admin ID: {uid}")

        # Create folder structure
        folders_spec = [
            ("docs", "/docs", None),
            ("agent-loop", "/docs/agent-loop", "docs"),
            ("learning", "/learning", None),
            ("basics", "/learning/basics", "learning"),
            ("advanced", "/learning/advanced", "learning"),
        ]
        folder_map = {}
        for name, path, parent_key in folders_spec:
            parent_id = folder_map.get(parent_key)
            f = FileFolder(owner_user_id=uid, parent_folder_id=parent_id,
                           name=name, path=path, depth=path.count("/"),
                           created_by=uid)
            s.add(f)
            await s.flush()
            folder_map[name] = f.id
        await s.commit()
        print(f"Folders: {list(folder_map.keys())}")

        # File contents
        files_content = {}

        files_content["docs/agent-loop/architecture-overview.md"] = """\
# Agent Loop 架构总览

## 核心组件

### 1. AgentWorker
- 独立进程运行，通过 SELECT ... FOR UPDATE 原子认领任务
- 租约机制(60s)防止僵尸任务
- 并发控制: Semaphore(3)

### 2. AgentLoopService
- 主循环: 规划 → 思考 → 工具执行 → 流式输出
- Planner: 调用 DeepSeek 决定下一步动作
- ToolExecutor: web_search, http_request, calculator, read_file, write_file, edit_file

### 3. EventBus
- 进程内 asyncio.Queue 发布-订阅
- EventItem 完整事件直通 SSE 生成器
- Redis Streams 批处理作为跨进程低延迟路径

### 4. SSE 流式传输
- text/event-stream 协议
- 三阶段: 历史重放 → 订阅EventBus → 实时循环
- 30s 心跳保活 + keepalive 补偿查询

## 数据流

DeepSeek → Worker(_stream_final_answer)
  → answer_delta 事件
  → _persist_and_notify
  → Redis Pub/Sub → API EventBus → SSE生成器 → 浏览器
  → async_task(INSERT DB) 异步落盘

## 关键配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| worker_concurrency | 3 | 最大并发任务数 |
| worker_lease_seconds | 60 | 租约时长 |
| run_timeout_seconds | 120 | 单次任务超时 |
| max_retry_attempts | 3 | 最大重试次数 |
"""

        files_content["docs/agent-loop/tool-executor-guide.md"] = """\
# ToolExecutor 工具使用指南

## 可用工具清单

| 工具 | 类型 | 网络要求 | 说明 |
|------|------|---------|------|
| web_search | 网络 | 是 | Tavily 搜索，返回最多10条结果 |
| http_request | 网络 | 是 | GET 请求，跟5次重定向，过滤敏感信息 |
| extract_web_content | 网络 | 是 | 同 http_request，用于内容提取 |
| calculator | 本地 | 否 | 安全算术求值，AST 解析限制50个操作 |
| read_file | 本地 | 否 | 读取文件或附件，支持模糊匹配 |
| write_file | 本地 | 否 | 创建/覆盖 .md 文件 |
| edit_file | 本地 | 否 | 单次查找替换(仅精确出现一次时) |

## 安全设计

### URL 安全
- 仅允许 http/https
- DNS 解析验证: 拒绝 localhost/私有 IP
- 禁止 utility 类 API (worldtimeapi, openweathermap 等)
- URL 脱敏: 去掉 username/password/search/hash

### 计算器安全
- Python AST 解析，不是 eval()
- 运算符白名单: +, -, *, /, //, %, **
- 绝对值上限: 10^100
- 最大操作数: 50

### 文件安全
- 仅 .md 扩展名
- 路径穿越拒绝
- 所有者校验: owner_user_id
- 超管可读全平台，但只能写自己空间
"""

        files_content["docs/agent-loop/streaming-protocol.md"] = """\
# SSE 流式传输协议规范

## 端点

GET /api/agent/runs/{run_id}/stream?after_seq={seq}

## 认证
- JWT 存储在 HttpOnly Cookie (access_token)
- Origin 校验防 CSRF
- 所有权验证: run.owner_user_id == current_user.id

## SSE 帧格式

id: {seq_number}
event: {event_type}
data: {json_payload}

## 事件类型(30+)

### 运行生命周期
- run_queued → run_started → run_succeeded/run_failed/run_cancelled

### 答案流式
- answer_started → answer_delta(×N) → answer_checkpoint → answer_completed

### 思考展示
- visible_thought_started → visible_thought_delta → visible_thought_paused/completed

### 工具调用
- tool_started → tool_completed

## 重连机制
- 浏览器: last-event-id 头携带最后看到的 seq
- 服务端: after_seq 查询参数，从指定点重放事件
- 去重: reducer 忽略 seq <= lastSeq 的事件
"""

        files_content["learning/basics/deepseek-integration.md"] = """\
# DeepSeek 集成学习笔记

## API 配置

DEEPSEEK_API_KEY = sk-xxx
DEEPSEEK_BASE_URL = https://api.deepseek.com
DEEPSEEK_MODEL = deepseek-chat

## 两种调用模式

### 1. 规划模式 (next_action)
- 输入: goal + step_index + observation + session_history
- 输出: JSON {thought_summary, action: {type, input}}
- 用于: Planner 决策下一步

### 2. 流式模式 (stream_text)
- 输入: messages (system + user)
- 输出: async generator 逐 chunk 返回
- 用于: visible_thought, final_answer

## 提示词工程

### Planner System Prompt
- 定义可用工具(action.type)
- 模式策略(quick/expert)
- 网络权限控制
- 输出格式约定(只返回 JSON)

### Visible Thought Prompt
- 简短中文说明
- 将来时/进行时
- 禁止泄露系统提示词
- 禁止泄露答案内容

## 错误处理
- ProviderAuthenticationError → 终止运行
- ProviderConfigurationError → 终止运行
- ProviderResponseError → 可重试
- RetryablePlannerError → 指数退避重试
"""

        files_content["learning/advanced/rbac-ownership-pattern.md"] = """\
# RBAC 所有权模式

## 核心原则

Agent 所有资源通过 owner_user_id 绑定用户:

## 权限矩阵

| 操作 | 普通用户 | 超管 |
|------|---------|------|
| 创建会话 | 自己 | 自己 |
| 查看自己的运行 | 可以 | 可以 |
| 取消/重试 | 自己的 | 自己的 |
| 查看他人运行 | 不可以(404) | 可以(审计页) |
| 上传附件 | 自己的会话 | 自己的会话 |
| 读文件 | 自己的 | 所有 |
| 写/改文件 | 自己的 | 自己的 |

## 实现细节

### 依赖注入
自动加载当前用户 + 所有权检查。

get_owned_agent_session 检查 session.owner_user_id == current_user.id
不存在或无权访问均返回 404(无法区分)。

### Worker 中的审计隔离
- Worker 通过 process_attempt(attempt_id, worker_id, owner_user_id) 接收
- 工具执行传递 owner_user_id 做权限检查
- file:read 改从 require_permissions 改为 Depends(get_current_user)
"""

        files_content["docs/agent-loop/optimization-roadmap.md"] = """\
# Agent Loop 优化路线图

## 已完成

-  SSE 流式延迟: 30s 降到 2ms (Redis Pub/Sub)
-  文件读取模糊匹配 + 文件夹感知
-  通用文件读取引擎(文本/PDF/DOCX/XLSX/PPTX)
-  思考面板去重(纯 useMemo 事件驱动)
-  前端零抖动 ProgressiveMarkdown
-  Planner: FinishInput extra=allow

## 进行中

-  PDF 扫描件友好错误提示
-  Agent 文件写入选定文件夹
-  测试用例补齐(文件操作 16 场景)

## 待启动

-  OCR 集成(扫描 PDF 到文字)
-  多租户文件空间隔离
-  Agent 对话历史搜索
-  知识库 RAG 集成
-  插件系统
-  审计日志持久化
"""

        for filepath, content in files_content.items():
            parts = filepath.split("/")
            folder_key = parts[-2]
            folder_id = folder_map.get(folder_key)
            filename = parts[-1]
            fid = uuid.uuid4()

            storage_root = Path("./var/files")
            storage_dir = storage_root / str(uid)
            storage_dir.mkdir(parents=True, exist_ok=True)
            storage_path = storage_dir / str(fid)
            storage_path.write_text(content, encoding="utf-8")

            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

            fo = FileObject(
                id=fid, owner_user_id=uid, folder_id=folder_id,
                storage_key=str(storage_path), filename=str(fid),
                original_filename=filename, media_type="text/markdown",
                size_bytes=len(content.encode("utf-8")), sha256=digest,
                created_by=uid,
            )
            s.add(fo)
            print(f"  File: {filepath}")

        await s.commit()
        print(f"Done! {len(files_content)} files created in DB.")

asyncio.run(main())
