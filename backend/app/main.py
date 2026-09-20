import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.api.agent import router as agent_router
from app.api.agent_attachments import router as agent_attachments_router
from app.api.agent_cookies import router as agent_cookies_router
from app.api.agent_login_sessions import router as agent_login_sessions_router
from app.api.agent_audit import router as agent_audit_router
from app.api.agent_stream import router as agent_stream_router
from app.api.dsh import router as dsh_router
from app.api.dsh_proxy import router as dsh_proxy_router
from app.api.admin_points import router as admin_points_router
from app.api.auth import me_router, router as auth_router
from app.api.avatars import router as avatars_router
from app.api.feishu import router as feishu_router
from app.api.files import router as files_router
from app.api.generations import router as generations_router
from app.api.metrics import router as metrics_router
from app.api.points import router as points_router
from app.api.rag import router as rag_router
from app.api.roles import permissions_router, router as roles_router
from app.api.task_chains import router as task_chains_router
from app.api.users import router as users_router
from app.core.config import get_settings
from app.core.errors import ApiError, api_error_handler
from app.core.middleware import RequestIdMiddleware
from app.db.seed import seed_rbac
from app.db.session import async_session_factory
from app.schemas.common import success
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

settings = get_settings()


async def _warmup_rag() -> None:
    """后台预热 RAG（D4）：不阻塞启动，失败只告警。"""
    from app.api.rag import get_search_service

    started = time.monotonic()
    try:
        service = get_search_service()
        await service.warmup()
        chunks = len(getattr(service.store, "_ids", []) or [])
        logger.info(
            "rag_warmup_done elapsed_ms=%s chunks=%s",
            int((time.monotonic() - started) * 1000),
            chunks,
        )
    except Exception as exc:  # noqa: BLE001 - 预热失败不影响服务可用性
        logger.warning("rag_warmup_failed error=%s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with async_session_factory() as session:
        await seed_rbac(session)
        await session.commit()
    from app.services.agent.loop import init_redis_bridge, shutdown_redis_bridge
    await init_redis_bridge()

    warmup_task: asyncio.Task[None] | None = None
    if settings.rag_warmup_on_startup:
        warmup_task = asyncio.create_task(_warmup_rag())

    try:
        yield
    finally:
        if warmup_task is not None and not warmup_task.done():
            warmup_task.cancel()
        await shutdown_redis_bridge()


app = FastAPI(
    title="权限管理系统 API",
    summary="用户、角色与权限统一管理服务",
    description="提供基于角色的访问控制、用户管理和角色权限管理接口。",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "认证管理", "description": "用户登录、登出与个人信息查询"},
        {"name": "用户管理", "description": "用户增删改查与状态管理"},
        {"name": "角色管理", "description": "角色增删改查与权限分配"},
        {"name": "权限管理", "description": "权限字典查询"},
        {"name": "系统监控", "description": "服务健康检查"},
    ],
)

app.add_middleware(RequestIdMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)

app.add_exception_handler(ApiError, api_error_handler)


@app.get("/api/stream-debug")
async def stream_debug():
    import datetime
    import time as _time

    async def test_generator():
        yield ":connected\n\n"
        for i in range(1, 6):
            ts = _time.time()
            data = f'{{"seq": {i}, "event_type": "test_event", "payload": {{"index": {i}, "server_ts": {ts}, "message": "事件{i} @ {ts:.3f}"}}, "created_at": "{datetime.datetime.now().isoformat()}", "run_id": "00000000-0000-0000-0000-000000000000"}}'
            yield f"id: {i}\ndata: {data}\n\n"
            await asyncio.sleep(0.5)
        yield "event: done\ndata: done\n\n"

    return StreamingResponse(
        test_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.include_router(auth_router, prefix="/api/auth")
app.include_router(me_router, prefix="/api")
app.include_router(roles_router, prefix="/api/roles")
app.include_router(permissions_router, prefix="/api/permissions")
app.include_router(users_router, prefix="/api/users")
app.include_router(agent_router, prefix="/api/agent")
app.include_router(agent_attachments_router, prefix="/api/agent")
app.include_router(agent_stream_router, prefix="/api/agent")
app.include_router(agent_audit_router, prefix="/api/agent/audit")
app.include_router(agent_cookies_router, prefix="/api/agent")
app.include_router(agent_login_sessions_router, prefix="/api/agent")
app.include_router(files_router, prefix="/api/files")
app.include_router(feishu_router, prefix="/api/feishu")
app.include_router(generations_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(avatars_router, prefix="/api/avatars")
app.include_router(points_router, prefix="/api")
app.include_router(admin_points_router, prefix="/api")
app.include_router(dsh_router, prefix="/api/dsh")
app.include_router(dsh_proxy_router, prefix="/api")
app.include_router(rag_router, prefix="/api/rag")
app.include_router(task_chains_router, prefix="/api/task-chains")


@app.get("/health", tags=["系统监控"])
async def health(request: Request) -> dict:
    return success(request, {"status": "ok"})
