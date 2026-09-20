# 真实积点计费系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 真实积点计费：DeepSeek 流式 usage 采集 → run 累计 → run 终态实时扣费；余额不足拦截 run 创建；内部充值（管理员充值 + 兑换码）；账户页重构为真实仪表盘。

**Architecture:** `llm.stream_text(..., usage_sink)` 解析流式末尾 usage 帧 → `_AttemptContext.llm_tokens` 累计（loop 直接调用 + planner 方法透传）→ `_do_process_attempt` 终态处调 `services/points.py:deduct_for_run`（原子 UPDATE 防负余额，失败只记日志）。3 新表（user_points/point_transactions/redeem_codes）。`create_run`/`retry` 余额检查（≤0 → 400 INSUFFICIENT_POINTS）。前端账户页仪表盘 + 用户管理页充值/兑换码。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, React + AntD

**Spec:** `docs/superpowers/specs/2026-08-06-points-billing-design.md` (c0cf498)

## Global Constraints

- 换算：`points_tokens_per_point=10000`（1 积点=10000 token，向上取整至少 1 积点）；`points_initial_grant=1000`（lazy 创建，老用户兼容）——config.py Settings 加两项
- 扣费点：`_do_process_attempt` 终态（run_succeeded/run_failed 的 `_persist_terminal_and_notify` 调用之后）——失败不阻塞（try/except 记日志）
- 扣费原子性：`UPDATE user_points SET balance=balance-:p, total_consumed=total_consumed+:p WHERE user_id=:id AND balance>=:p RETURNING`——行数 0 → InsufficientPointsError
- 流水 append-only；不存敏感信息；usage 帧缺失 → tokens=0 不扣
- 事件结构（已核实）：stream_text 在 loop.py:338/1099 直接调用；planner 内部 stream 在 planner.py:144（planner 方法被 loop 调用——loop.py:348/1553/1997 等，需给 planner 的流式方法加 `usage_sink` 透传）；`_AttemptContext`（loop.py:87）是 dataclass（run+attempt）——加 `llm_tokens: int = 0` 字段
- Python 执行器：`X:\python\anaconda\envs\01-rbac\python.exe`；后端测试 workdir `C:\01_agent_loop_pro\backend`
- **git 纪律**：只 `git add` 本任务精确路径，禁 `git add -A`；提交前 `git status --short`；仓库有并行会话改动
- 迁移：手写（续当前 head——写前 `alembic heads` 核实），含 point_transactions.tokens 可空列（usage 聚合用）
- 前端测试约定：禁页面级 byRole（jsdom 病理），用 querySelectorAll + textContent

---

### Task 1: 模型 + 迁移 + settings

**Files:**
- Create: `backend/app/models/points.py`（UserPoints/PointTransaction/RedeemCode 三个 ORM）
- Create: `backend/alembic/versions/<hex>_add_points_tables.py`（手写迁移）
- Modify: `backend/app/config.py`（Settings 加 `points_tokens_per_point: int = 10000`、`points_initial_grant: int = 1000`）

**Interfaces:**
- Produces: `UserPoints`（user_id PK/FK users.id, balance/total_granted/total_consumed int default 0, updated_at）、`PointTransaction`（id PK, user_id FK index, amount int, type varchar(20), ref text default "", tokens int NULL, created_at）、`RedeemCode`（code varchar(32) PK, points int, created_by FK, created_at, used_by FK NULL, used_at NULL）

- [ ] **Step 1: 核实 alembic head 与模型风格**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m alembic heads`（workdir `C:\01_agent_loop_pro\backend`）
Expected: 单行 head——作为迁移 down_revision。模型风格参照 `app/models/feishu_token.py`（Base/Mapped 模式）。

- [ ] **Step 2: 写模型**

`backend/app/models/points.py`：

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserPoints(Base):
    __tablename__ = "user_points"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    total_granted: Mapped[int] = mapped_column(Integer, default=0)
    total_consumed: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class PointTransaction(Base):
    __tablename__ = "point_transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    ref: Mapped[str] = mapped_column(Text, default="")
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class RedeemCode(Base):
    __tablename__ = "redeem_codes"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    used_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 3: config 加两项**

`backend/app/config.py` Settings 加：

```python
points_tokens_per_point: int = 10000
points_initial_grant: int = 1000
```

- [ ] **Step 4: 写迁移**

`backend/alembic/versions/<hex>_add_points_tables.py`（revision=<hex>，down_revision=Step 1 head）：

```python
"""add points billing tables

Revision ID: <hex>
Revises: <STEP1_HEAD>
Create Date: 2026-08-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '<hex>'
down_revision: Union[str, Sequence[str], None] = '<STEP1_HEAD>'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('user_points',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('balance', sa.Integer(), nullable=False),
    sa.Column('total_granted', sa.Integer(), nullable=False),
    sa.Column('total_consumed', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('point_transactions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('ref', sa.Text(), nullable=False),
    sa.Column('tokens', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_point_transactions_user_id'), 'point_transactions', ['user_id'], unique=False)
    op.create_table('redeem_codes',
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('points', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_by', sa.Uuid(), nullable=True),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['used_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('code')
    )


def downgrade() -> None:
    op.drop_table('redeem_codes')
    op.drop_index(op.f('ix_point_transactions_user_id'), table_name='point_transactions')
    op.drop_table('point_transactions')
    op.drop_table('user_points')
```

- [ ] **Step 5: 应用迁移 + 验证导入**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m alembic upgrade head`（workdir backend；表已存在 → `alembic stamp <hex>` 并注明）
Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -c "import sys; sys.path.insert(0, r'C:\01_agent_loop_pro\backend'); from app.models.points import UserPoints, PointTransaction, RedeemCode; from app.config import get_settings; print(get_settings().points_tokens_per_point); print('OK')"`
Expected: `10000` 与 `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/points.py backend/app/config.py backend/alembic/versions/<hex>_add_points_tables.py
git commit -m "feat: points billing tables (user_points/transactions/redeem_codes) and settings"
```

---

### Task 2: token 用量采集（llm.py + loop/planner 累计）

**Files:**
- Modify: `backend/app/services/agent/llm.py`
- Modify: `backend/app/services/agent/loop.py`
- Modify: `backend/app/services/agent/planner.py`
- Test: `backend/tests/test_llm_usage.py`（新建）+ `backend/tests/test_planner.py`（若存在——核实）扩展

**Interfaces:**
- Consumes: 无（独立于 T1）
- Produces:
  - `llm.stream_text(messages, usage_sink: Callable[[dict], None] | None = None)`
  - `_iter_sse_content(frames, usage_sink=None)`：`data.get("usage")` 非空 → `usage_sink(data["usage"])`
  - `_AttemptContext.llm_tokens: int = 0`（loop.py:87 dataclass 加字段，带默认值）
  - loop 两处 stream_text（:338、:1099）与 planner 所有流式方法透传 usage_sink

- [ ] **Step 1: 写失败测试**

`backend/tests/test_llm_usage.py`：

```python
import pytest

from app.services.agent.llm import DeepSeekClient


class TestUsageSink:
    @pytest.mark.anyio
    async def test_usage_frame_delivered_to_sink(self):
        frames = [
            'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":12,"completion_tokens":8,"total_tokens":20}}\n\n',
            "data: [DONE]\n\n",
        ]
        client = DeepSeekClient()
        seen = []
        collected = ""
        async for chunk in client._iter_sse_content(frames, usage_sink=seen.append):
            collected += chunk
        assert collected == "你好"
        assert seen == [{"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}]

    @pytest.mark.anyio
    async def test_no_usage_frame_no_callback(self):
        frames = ['data: {"choices":[{"delta":{"content":"x"}}]}\n\n', "data: [DONE]\n\n"]
        client = DeepSeekClient()
        seen = []
        async for _ in client._iter_sse_content(frames, usage_sink=seen.append):
            pass
        assert seen == []

    @pytest.mark.anyio
    async def test_usage_in_same_frame_as_content(self):
        frames = [
            'data: {"choices":[{"delta":{"content":"ok"}}],"usage":{"total_tokens":5}}\n\n',
        ]
        client = DeepSeekClient()
        seen = []
        collected = ""
        async for chunk in client._iter_sse_content(frames, usage_sink=seen.append):
            collected += chunk
        assert collected == "ok"
        assert seen == [{"total_tokens": 5}]
```

（`DeepSeekClient` 类名核实——llm.py 里类名；`_iter_sse_content` 是实例方法——需构造实例，若构造需要 settings 则 monkeypatch 或用类方法——**按实际实现调整**：若 `_iter_sse_content` 是 static/classmethod 则相应改调用；DeepSeekClient 构造若需要 httpx client 参数则传 `DeepSeekClient()` 默认构造。）

- [ ] **Step 2: 运行确认失败**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_llm_usage.py -q --no-header`
Expected: FAIL（TypeError：usage_sink 参数不存在）

- [ ] **Step 3: 实现 llm.py 采集**

`backend/app/services/agent/llm.py`：
1. `_iter_sse_content(self, frames, usage_sink: Callable[[dict], None] | None = None)`：解析帧时（`data = json.loads(payload)` 之后）：

```python
                if usage_sink is not None and data.get("usage"):
                    usage_sink(data["usage"])
```

2. `stream_text(self, messages, usage_sink: Callable[[dict], None] | None = None)`：
   - payload 加 `"stream_options": {"include_usage": True}`
   - 迭代处 `self._iter_sse_content([line], usage_sink=usage_sink)`

- [ ] **Step 4: 实现累计（loop.py + planner.py）**

loop.py:
1. `_AttemptContext`（:87）加字段：`llm_tokens: int = 0`
2. :338 处：

```python
        async for chunk in self.llm_client.stream_text(
            messages, usage_sink=_usage_accumulate
        ):
```

其中 `_usage_accumulate` 闭包/内联：

```python
        usage_holder: dict = {}

        def _usage_accumulate(usage: dict) -> None:
            usage_holder.update(usage)

        async for chunk in self.llm_client.stream_text(messages, usage_sink=_usage_accumulate):
            ...
        # 流结束后：
        ctx.llm_tokens += int(usage_holder.get("total_tokens", 0) or 0)
```

（:1099 同样处理。两处上下文不同（是否已有 usage_holder 变量名冲突）——按实际代码调整变量名。）

3. planner 调用：核实 loop.py 中所有 `self.planner.<method>` 调用点（:348/1553/1997 等），planner 流式方法加 `usage_sink` 透传：

planner.py——所有含 `async for chunk in self.client.stream_text(messages)` 的方法（核实：:144 及其他，如 create_plan/plan_next/…）签名加 `usage_sink: Callable[[dict], None] | None = None`，内部调用透传 `stream_text(messages, usage_sink=usage_sink)`。

loop.py 调 planner 处传 `usage_sink=_usage_accumulate`（同一 usage_holder/ctx 累加）——**在 `_do_process_attempt` 的作用域内构造 usage_holder 并传给 planner 调用与直接 stream_text**（若 planner 调用与直接 stream_text 在不同作用域，则各自构造 holder 并都累加到 ctx）。

- [ ] **Step 5: 运行确认通过**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_llm_usage.py -q --no-header`
Expected: 3 通过
Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_planner.py -q --no-header 2>&1`（若存在——核实文件名 glob `tests/test_planner*`；planner 签名改动回归）

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/llm.py backend/app/services/agent/loop.py backend/app/services/agent/planner.py backend/tests/test_llm_usage.py
git commit -m "feat: capture deepseek streaming usage and accumulate per run"
```

---

### Task 3: points 服务 + API + 拦截 + 扣费接入

**Files:**
- Create: `backend/app/services/points.py`
- Create: `backend/app/api/points.py`（/api/points/me、/usage、/redeem）
- Create: `backend/app/api/admin_points.py`（/api/admin/points/grant、/api/admin/points/all、/api/admin/redeem-codes GET/POST）
- Modify: `backend/app/api/agent.py`（create_run + retry 余额检查）
- Modify: `backend/app/services/agent/loop.py`（终态扣费接入）
- Modify: `backend/app/main.py`（注册 2 个 router）
- Test: `backend/tests/test_points_api.py`

**Interfaces:**
- Consumes: T1 模型、T2 的 `ctx.llm_tokens`
- Produces:
  - `services/points.py`：`tokens_to_points(tokens) -> int`、`get_or_create_points(db, user_id)`、`deduct_for_run(db, user_id, run_id, tokens) -> int`、`grant_points(db, user_id, points, type_, ref, description="")`、`redeem_code(db, user_id, code) -> dict`
  - `GET /api/points/me` → `{balance, total_granted, total_consumed, recent: [...]}`（recent 20 条含 id/amount/type/ref/tokens/created_at）
  - `GET /api/points/usage` → `{days: [{date, tokens, points}]}`（近 30 天按 point_transactions.tokens 聚合）
  - `POST /api/points/redeem` {code}（csrf）→ `{points}`；400 INVALID_CODE / CODE_REUSED
  - `POST /api/admin/points/grant` {user_id, points, description}（超管+csrf）→ `{balance}`
  - `GET /api/admin/points/all`（超管）→ `{users: [{user_id, username, balance}]}`
  - `POST /api/admin/redeem-codes` {points, count}（超管+csrf）→ `{codes: [...]}`（count 1-50，码格式 `XXXX-XXXX-XXXX` 大写字母数字，随机生成）
  - `GET /api/admin/redeem-codes`（超管）→ `{codes: [{code, points, used_by, used_at, created_at}]}`（倒序，分页 page/page_size 默认 20 le 100）
  - create_run（agent.py:228）与 retry（agent.py:475）在创建 run 前：
    ```python
    points = await get_or_create_points(db, current_user.id)
    if points.balance <= 0:
        raise ApiError(status_code=400, code="INSUFFICIENT_POINTS", message="积点余额不足，请先充值")
    ```
  - loop.py `_do_process_attempt` 终态（run_succeeded/run_failed 分支 `_persist_terminal_and_notify` 之后）：
    ```python
    try:
        from app.services.points import deduct_for_run
        from app.db.session import async_session_factory
        async with async_session_factory() as _db:
            await deduct_for_run(_db, owner_user_id, ctx.run.id, ctx.llm_tokens)
    except Exception:
        logger.exception("points deduction failed for run %s", ctx.run.id)
    ```
    （owner_user_id 从 run.owner_user_id 取；_do_process_attempt 内终态分支只跑一次——放成功与失败终态共有的收尾点，若没有共同点则在两分支各放一次且保证只执行一次——**实现者按实际控制流选择**，用 try/except 包住。）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_points_api.py`（fixtures 照 test_generations_api.py 模式；admin_client 有 csrf_headers）：

```python
import uuid

import pytest

from app.models.points import RedeemCode, UserPoints


class TestPointsService:
    @pytest.mark.anyio
    async def test_tokens_to_points_rounds_up(self, monkeypatch):
        from app.services.points import tokens_to_points
        monkeypatch.setattr("app.services.points.settings.points_tokens_per_point", 10000)
        assert tokens_to_points(0) == 0
        assert tokens_to_points(1) == 1
        assert tokens_to_points(9999) == 1
        assert tokens_to_points(10000) == 1
        assert tokens_to_points(10001) == 2

    @pytest.mark.anyio
    async def test_get_or_create_grants_initial(self, test_db, ordinary_user):
        from app.services.points import get_or_create_points
        async with test_db() as db:
            points = await get_or_create_points(db, ordinary_user.id)
            assert points.balance == 1000
            # 再次调用不重复送
            points2 = await get_or_create_points(db, ordinary_user.id)
            assert points2.balance == 1000

    @pytest.mark.anyio
    async def test_deduct_atomic_and_records_transaction(
        self, test_db, ordinary_user, monkeypatch
    ):
        from app.models.points import PointTransaction
        from app.services.points import deduct_for_run, get_or_create_points
        monkeypatch.setattr("app.services.points.settings.points_tokens_per_point", 10000)
        async with test_db() as db:
            await get_or_create_points(db, ordinary_user.id)  # balance 1000
            pts = await deduct_for_run(db, ordinary_user.id, uuid.uuid4(), 25000)  # 3 积点
            assert pts == 3
            row = await db.get(UserPoints, ordinary_user.id)
            assert row.balance == 997
            assert row.total_consumed == 3
            tx = (await db.execute(
                select(PointTransaction).where(PointTransaction.type == "consume")
            )).scalar_one()
            assert tx.amount == -3
            assert tx.tokens == 25000

    @pytest.mark.anyio
    async def test_deduct_insufficient_raises(self, test_db, ordinary_user, monkeypatch):
        from app.services.points import InsufficientPointsError, deduct_for_run, get_or_create_points
        monkeypatch.setattr("app.services.points.settings.points_tokens_per_point", 10000)
        async with test_db() as db:
            await get_or_create_points(db, ordinary_user.id)  # balance 1000
            await deduct_for_run(db, ordinary_user.id, uuid.uuid4(), 999 * 10000)  # 扣 999 → 余 1
            with pytest.raises(InsufficientPointsError):
                await deduct_for_run(db, ordinary_user.id, uuid.uuid4(), 2 * 10000)  # 需 2 > 余 1

    @pytest.mark.anyio
    async def test_redeem_code_flow(self, test_db, ordinary_user, admin_user):
        from app.services.points import redeem_code
        async with test_db() as db:
            db.add(RedeemCode(code="ABCD-EFGH-IJKL", points=500, created_by=admin_user.id))
            await db.commit()
        async with test_db() as db:
            result = await redeem_code(db, ordinary_user.id, "ABCD-EFGH-IJKL")
            assert result["points"] == 500
            row = await db.get(UserPoints, ordinary_user.id)
            assert row.balance == 1500  # 1000 初始 + 500
        async with test_db() as db:
            from app.services.points import RedeemCodeError
            with pytest.raises(RedeemCodeError):
                await redeem_code(db, ordinary_user.id, "ABCD-EFGH-IJKL")  # 重复
            with pytest.raises(RedeemCodeError):
                await redeem_code(db, ordinary_user.id, "NOPE-NOPE-NOPE")  # 无效


class TestPointsApi:
    @pytest.mark.anyio
    async def test_me_returns_balance_and_recent(
        self, test_db, ordinary_client, ordinary_user
    ):
        resp = await ordinary_client.get("/api/points/me")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["balance"] == 1000
        assert isinstance(data["recent"], list)

    @pytest.mark.anyio
    async def test_redeem_api(self, test_db, ordinary_client, ordinary_user, admin_user, csrf_headers):
        async with test_db() as db:
            db.add(RedeemCode(code="WXYZ-1234-5678", points=300, created_by=admin_user.id))
            await db.commit()
        resp = await ordinary_client.post(
            "/api/points/redeem", json={"code": "WXYZ-1234-5678"}, headers=csrf_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["points"] == 300
        bad = await ordinary_client.post(
            "/api/points/redeem", json={"code": "BAD-BAD-BAD"}, headers=csrf_headers
        )
        assert bad.status_code == 400

    @pytest.mark.anyio
    async def test_admin_grant_and_codes(
        self, test_db, admin_client, ordinary_user, csrf_headers
    ):
        resp = await admin_client.post(
            "/api/admin/points/grant",
            json={"user_id": str(ordinary_user.id), "points": 200, "description": "补偿"},
            headers=csrf_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["balance"] == 1200
        codes = await admin_client.post(
            "/api/admin/redeem-codes", json={"points": 100, "count": 2}, headers=csrf_headers
        )
        assert codes.status_code == 200
        assert len(codes.json()["data"]["codes"]) == 2
        lst = await admin_client.get("/api/admin/redeem-codes")
        assert lst.status_code == 200
        assert lst.json()["data"]["total"] == 2

    @pytest.mark.anyio
    async def test_admin_endpoints_forbidden_for_employee(
        self, test_db, ordinary_client, csrf_headers
    ):
        resp = await ordinary_client.post(
            "/api/admin/points/grant",
            json={"user_id": str(uuid.uuid4()), "points": 1, "description": ""},
            headers=csrf_headers,
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.anyio
    async def test_run_create_blocked_when_insufficient(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.points import UserPoints
        async with test_db() as db:
            row = await db.get(UserPoints, ordinary_user.id)
            if row is None:
                row = UserPoints(user_id=ordinary_user.id, balance=0)
                db.add(row)
            else:
                row.balance = 0
            await db.commit()
        # 创建 session + run（复用 test_generations_api 的 _make_session 模式或调 API）
        resp = await ordinary_client.post(
            "/api/agent/sessions", json={"title": "测试"}, headers=csrf_headers
        )
        session_id = resp.json()["data"]["id"] if resp.status_code == 201 else None
        if session_id:
            run_resp = await ordinary_client.post(
                f"/api/agent/sessions/{session_id}/runs",
                json={"goal": "写方案", "network_enabled": True},
                headers=csrf_headers,
            )
            assert run_resp.status_code == 400
            assert run_resp.json()["code"] == "INSUFFICIENT_POINTS"
```

（session/run 创建 API 请求体以实际为准——读 agent.py create_session/create_run 的 schema；`select` import 补全；`InsufficientPointsError`/`RedeemCodeError` 在 services/points.py 定义。）

- [ ] **Step 2: 运行确认失败**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_points_api.py -q --no-header`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 services/points.py**

```python
from __future__ import annotations

import math
import secrets
import string
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.points import PointTransaction, RedeemCode, UserPoints

settings = get_settings()

CODE_ALPHABET = string.ascii_uppercase + string.digits


class InsufficientPointsError(Exception):
    pass


class RedeemCodeError(Exception):
    pass


def tokens_to_points(tokens: int) -> int:
    if tokens <= 0:
        return 0
    return max(1, math.ceil(tokens / settings.points_tokens_per_point))


def _new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"


async def get_or_create_points(db: AsyncSession, user_id: uuid.UUID) -> UserPoints:
    row = await db.get(UserPoints, user_id)
    if row is not None:
        return row
    row = UserPoints(user_id=user_id, balance=settings.points_initial_grant,
                     total_granted=settings.points_initial_grant)
    db.add(row)
    db.add(PointTransaction(
        user_id=user_id, amount=settings.points_initial_grant,
        type="grant", ref="welcome", tokens=None,
    ))
    await db.flush()
    return row


async def deduct_for_run(db: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID, tokens: int) -> int:
    points = tokens_to_points(tokens)
    if points <= 0:
        return 0
    result = await db.execute(
        update(UserPoints)
        .where(UserPoints.user_id == user_id, UserPoints.balance >= points)
        .values(balance=UserPoints.balance - points, total_consumed=UserPoints.total_consumed + points)
        .returning(UserPoints.balance)
    )
    if result.scalar_one_or_none() is None:
        raise InsufficientPointsError(f"balance below {points}")
    db.add(PointTransaction(
        user_id=user_id, amount=-points, type="consume",
        ref=str(run_id), tokens=tokens,
    ))
    await db.commit()
    return points


async def grant_points(db: AsyncSession, user_id: uuid.UUID, points: int, type_: str,
                       ref: str = "", description: str = "") -> int:
    row = await get_or_create_points(db, user_id)
    row.balance += points
    row.total_granted += points
    db.add(PointTransaction(
        user_id=user_id, amount=points, type=type_,
        ref=ref or description,
    ))
    await db.commit()
    return row.balance


async def redeem_code(db: AsyncSession, user_id: uuid.UUID, code: str) -> dict:
    normalized = code.strip().upper()
    row = await db.get(RedeemCode, normalized)
    if row is None:
        raise RedeemCodeError("invalid_code")
    if row.used_by is not None:
        raise RedeemCodeError("code_reused")
    result = await db.execute(
        update(RedeemCode)
        .where(RedeemCode.code == normalized, RedeemCode.used_by.is_(None))
        .values(used_by=user_id)
    )
    if result.rowcount != 1:
        raise RedeemCodeError("code_reused")
    balance = await grant_points(db, user_id, row.points, "redeem", ref=normalized)
    return {"points": row.points, "balance": balance}
```

（注意：`get_or_create_points` 里 `await db.flush()` 在 grant_points 的 `await db.commit()` 前——事务内一致。`redeem_code` 的 grant_points 内部 commit——领取标记与加积点在同一事务（grant_points 的 commit 提交两者）✓。）

- [ ] **Step 4: 实现 API（points.py + admin_points.py）**

`backend/app/api/points.py`：

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.points import PointTransaction, UserPoints
from app.models.rbac import User
from app.schemas.common import success
from app.services.points import RedeemCodeError, get_or_create_points, redeem_code

router = APIRouter(tags=["Points"])


class RedeemRequest(BaseModel):
    code: str


@router.get("/points/me")
async def my_points(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_or_create_points(db, current_user.id)
    recent_result = await db.execute(
        select(PointTransaction)
        .where(PointTransaction.user_id == current_user.id)
        .order_by(PointTransaction.created_at.desc())
        .limit(20)
    )
    recent = [
        {
            "id": str(t.id),
            "amount": t.amount,
            "type": t.type,
            "ref": t.ref,
            "tokens": t.tokens,
            "created_at": t.created_at.isoformat() if t.created_at else "",
        }
        for t in recent_result.scalars().all()
    ]
    await db.commit()
    return success(request, {
        "balance": row.balance,
        "total_granted": row.total_granted,
        "total_consumed": row.total_consumed,
        "recent": recent,
    })


@router.get("/points/usage")
async def points_usage(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    start = datetime.now(UTC) - timedelta(days=29)
    result = await db.execute(
        select(
            func.date(PointTransaction.created_at).label("day"),
            func.coalesce(func.sum(PointTransaction.tokens), 0).label("tokens"),
            func.coalesce(func.sum(PointTransaction.amount), 0).label("points"),
        )
        .where(
            PointTransaction.user_id == current_user.id,
            PointTransaction.type == "consume",
            PointTransaction.created_at >= start,
        )
        .group_by(func.date(PointTransaction.created_at))
        .order_by(func.date(PointTransaction.created_at))
    )
    days = [
        {"date": str(day), "tokens": tokens, "points": points}
        for day, tokens, points in result.all()
    ]
    return success(request, {"days": days})


@router.post("/points/redeem")
async def redeem(
    request: Request,
    data: RedeemRequest,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await redeem_code(db, current_user.id, data.code)
    except RedeemCodeError as exc:
        code = str(exc)
        raise ApiError(status_code=400, code=code.upper(), message="兑换码无效或已被使用")
    return success(request, result)
```

`backend/app/api/admin_points.py`（超管：`require_super_admin` 依赖——核实现有 admin 端点权限写法，agent_audit.py 或 users.py 的 require_super_admin 用法）：

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user, require_super_admin
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.points import RedeemCode, UserPoints
from app.models.rbac import User
from app.schemas.common import success
from app.services.points import _new_code, grant_points

router = APIRouter(tags=["AdminPoints"])


class GrantRequest(BaseModel):
    user_id: uuid.UUID
    points: int
    description: str = ""


class CreateCodesRequest(BaseModel):
    points: int
    count: int = 1


@router.get("/admin/points/all")
async def admin_points_all(
    request: Request,
    _admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(UserPoints))
    users = [
        {"user_id": str(p.user_id), "balance": p.balance}
        for p in result.scalars().all()
    ]
    return success(request, {"users": users})


@router.post("/admin/points/grant")
async def admin_grant(
    request: Request,
    data: GrantRequest,
    _admin: User = Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    if data.points <= 0 or data.points > 1_000_000:
        raise ApiError(status_code=400, code="INVALID_POINTS", message="积点数量无效")
    balance = await grant_points(db, data.user_id, data.points, "grant", ref="admin", description=data.description)
    return success(request, {"balance": balance})


@router.post("/admin/redeem-codes")
async def admin_create_codes(
    request: Request,
    data: CreateCodesRequest,
    _admin: User = Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    if data.points <= 0 or data.points > 1_000_000 or data.count < 1 or data.count > 50:
        raise ApiError(status_code=400, code="INVALID_INPUT", message="参数无效")
    codes = []
    for _ in range(data.count):
        code = _new_code()
        db.add(RedeemCode(code=code, points=data.points, created_by=_admin.id))
        codes.append(code)
    await db.commit()
    return success(request, {"codes": codes})


@router.get("/admin/redeem-codes")
async def admin_list_codes(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    total = len((await db.execute(select(RedeemCode.code))).all())
    result = await db.execute(
        select(RedeemCode).order_by(RedeemCode.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    codes = [
        {
            "code": c.code,
            "points": c.points,
            "used_by": str(c.used_by) if c.used_by else None,
            "used_at": c.used_at.isoformat() if c.used_at else None,
            "created_at": c.created_at.isoformat() if c.created_at else "",
        }
        for c in result.scalars().all()
    ]
    return success(request, {"codes": codes, "total": total})
```

（`_new_code` 为私有——admin_points 引用（同包内）可接受，或导出；`require_super_admin` 签名核实——若返回 User 则 `_admin: User = Depends(require_super_admin)`。）

- [ ] **Step 5: agent.py 拦截 + main.py 注册 + loop.py 扣费**

agent.py `create_run`（:228）与 `retry`（:475）：在 run INSERT 前加：

```python
from app.services.points import get_or_create_points
...
points = await get_or_create_points(db, current_user.id)
if points.balance <= 0:
    raise ApiError(status_code=400, code="INSUFFICIENT_POINTS", message="积点余额不足，请先充值")
```

（`ApiError`/`get_db` 已在 agent.py import 则复用。）

main.py 注册：

```python
from app.api.points import router as points_router
from app.api.admin_points import router as admin_points_router
app.include_router(points_router, prefix="/api")
app.include_router(admin_points_router, prefix="/api")
```

loop.py `_do_process_attempt` 终态扣费（run_succeeded/run_failed 分支 `_persist_terminal_and_notify` 之后——实现者按实际控制流放一次且仅一次；建议放在 `_do_process_attempt` 的 try 主体末尾统一处或两终态分支的公共收尾）：

```python
            try:
                from app.db.session import async_session_factory
                from app.services.points import deduct_for_run

                async with async_session_factory() as _db:
                    await deduct_for_run(_db, ctx.run.owner_user_id, ctx.run.id, ctx.llm_tokens)
            except Exception:
                logger.exception("points deduction failed for run %s", ctx.run.id)
```

（`logger` 在 loop.py 已有则复用。）

- [ ] **Step 6: 运行确认通过**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_points_api.py -q --no-header`
Expected: 全过（~11 个）
回归：`& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_agent_api.py tests/test_generations_api.py -q --no-header`（agent.py 拦截不破坏既有测试——若既有测试建 run 且用户无 points 行 → lazy 创建送 1000 不受影响）

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/points.py backend/app/api/points.py backend/app/api/admin_points.py backend/app/api/agent.py backend/app/services/agent/loop.py backend/app/main.py backend/tests/test_points_api.py
git commit -m "feat: points billing service, APIs, run gate and live deduction"
```

---

### Task 4: 前端（账户页重构 + 管理端充值/兑换码）

**Files:**
- Modify: `frontend/src/lib/api.ts`（7 个 API 函数 + 类型）
- Modify: `frontend/src/lib/points-config.ts`（换算展示值对齐后端）
- Modify: `frontend/src/app/(agent)/account/points/page.tsx`（重构仪表盘）
- Modify: `frontend/src/components/users/user-table.tsx` 或用户管理页（充值按钮 + 余额列 + 兑换码管理 Modal）
- Modify: 会话页（createRun 失败 INSUFFICIENT_POINTS 提示——找 createRun 调用处 message.error 逻辑）
- Test: 账户页测试更新 + 用户管理测试扩展（照现有约定）

**Interfaces:**
- Consumes: T3 契约（7 端点）
- Produces: 无

- [ ] **Step 1: api.ts + types**

```ts
export interface PointTxn {
  id: string;
  amount: number;
  type: string;
  ref: string;
  tokens: number | null;
  created_at: string;
}

export interface MyPoints {
  balance: number;
  total_granted: number;
  total_consumed: number;
  recent: PointTxn[];
}

export function getMyPoints() {
  return api<MyPoints>("/api/points/me");
}

export function getPointsUsage() {
  return api<{ days: { date: string; tokens: number; points: number }[] }>("/api/points/usage");
}

export function redeemPoints(code: string) {
  return api<{ points: number }>("/api/points/redeem", {
    method: "POST",
    body: JSON.stringify({ code }),
    csrf: true,
  });
}

export function adminGrantPoints(userId: string, points: number, description: string) {
  return api<{ balance: number }>("/api/admin/points/grant", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, points, description }),
    csrf: true,
  });
}

export function adminPointsAll() {
  return api<{ users: { user_id: string; balance: number }[] }>("/api/admin/points/all");
}

export function adminCreateRedeemCodes(points: number, count: number) {
  return api<{ codes: string[] }>("/api/admin/redeem-codes", {
    method: "POST",
    body: JSON.stringify({ points, count }),
    csrf: true,
  });
}

export function adminListRedeemCodes(page = 1, pageSize = 20) {
  return api<{ codes: { code: string; points: number; used_by: string | null; used_at: string | null; created_at: string }[]; total: number }>(
    `/api/admin/redeem-codes?page=${page}&page_size=${pageSize}`
  );
}
```

- [ ] **Step 2: points-config.ts 更新**

换算展示值对齐后端：`POINTS_PER_TOKEN` 语义改为 `TOKENS_PER_POINT = 10000`、`INITIAL_GRANT_POINTS = 1000`；删除 MOCK_*（或保留作占位但页面不再用）。

- [ ] **Step 3: 账户页重构（浅色仪表盘）**

`frontend/src/app/(agent)/account/points/page.tsx` 重构：
1. 数据：`useEffect` 加载 `getMyPoints()` + `getPointsUsage()`（loading/error 态）
2. **余额大卡**：渐变背景（linear-gradient(135deg,#3370ff,#2f54eb)）、白字大数字（`balance.toLocaleString()` + "积点"）、下方两行小字（累计获得 X · 累计消耗 Y）
3. **兑换码**：余额卡下方内联：Input（placeholder 兑换码）+ [兑换] 按钮（loading + message 反馈成功/失败）
4. **用量趋势**：CSS 柱状图（近 30 天）：flex 行容器，每柱 `height = tokens/max * 100%`（min 4%），title 属性显示日期+token；下方图例（最近 30 天每日 token 消耗）
5. **计费规则卡**：1 积点 = 10000 token、新用户赠送 1000 积点、充值方式（管理员充值/兑换码）
6. **套餐区**：三档卡保留，按钮改"联系管理员充值"→ message.info
7. **流水表**：antd Table（列：时间 formatTime、类型 Tag（grant/充值绿、redeem/兑换蓝、consume/消耗红）、说明（ref）、数量（+/-着色）），数据 recent，无分页（20 条内）
8. 空数据态（balance 显示 0、流水 Empty）

- [ ] **Step 4: 用户管理页（超管）**

读 `frontend/src/components/users/user-table.tsx`（或实际用户管理组件）：
1. 用户列表加"余额"列（adminPointsAll 返回 map user_id→balance，加载后合并显示；无数据 "—"）
2. 行操作加"充值积点"按钮 → Modal（InputNumber 积点 + Input 说明 + 确认）→ adminGrantPoints → 刷新余额
3. 顶部/工具栏加"兑换码管理"按钮 → Modal 两个区：
   - 生成区：InputNumber 积点 + InputNumber 数量 + [生成] → adminCreateRedeemCodes → 显示码列表（每行 code + 复制按钮）
   - 码列表：adminListRedeemCodes 表格（码/积点/状态 Tag（未使用/已使用）/创建时间，分页 20）

- [ ] **Step 5: 余额不足提示**

会话页 createRun 调用处（找 `createRun` 或发消息函数）：catch 时若错误含 INSUFFICIENT_POINTS → `message.error("积点余额不足，请前往「账户」充值或输入兑换码")`——读现有错误处理逻辑按模式加。

- [ ] **Step 6: 前端验证**

Run: `npx tsc --noEmit`（workdir `C:\01_agent_loop_pro\frontend`）——本任务文件零新增错误
Run: `npx vitest run src/app/(agent)/account/points/ src/components/users/`——通过（现有测试按新 UI 更新断言；照仓库约定）

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/points-config.ts "frontend/src/app/(agent)/account/points/page.tsx" frontend/src/components/users/<实际文件> <会话页文件> <测试文件>
git commit -m "feat: real points dashboard, admin recharge and redeem codes UI"
```

---

### Task 5: E2E 验证与收尾

- [ ] **Step 1: 后端回归（隔离 DB）**

```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_points"
& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/ -q --no-header
```
Expected: 全过或仅已知失败（pypdf 4 + 并行会话既有）；points 相关全绿。

- [ ] **Step 2: 用户实测**

1. 账户页：余额 1000（新用户）→ 真实数据
2. 让 AI 生成一个方案 → 完成后账户页余额减少（约 1-5 积点）、流水出现"消耗"记录（ref=run id）、用量趋势有柱子
3. 超管用户管理页：看到用户余额列 → 给某用户充值 → 该用户余额增加
4. 超管生成兑换码 → 员工账户页输入兑换 → 余额增加 + 流水"兑换"
5. 把某用户余额扣到 0（管理员不充值）→ 该用户发消息 → 提示"积点余额不足"
6. 换算出账准确（DeepSeek usage vs 扣的积点）

- [ ] **Step 3: 提交校准修复（如有）**

```bash
git add <精确路径>
git commit -m "fix: points billing E2E calibration"
```
（仅当有修复。）
