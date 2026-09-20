# 真实积点计费系统（内部充值 + 实时扣费） Design Spec

**Status:** Draft
**Date:** 2026-08-06

## 1. 范围（用户确认）

| 项 | 方案 |
|---|---|
| 付费通道 | **内部充值机制**：管理员充值 + 兑换码（无第三方支付资质） |
| 扣费时机 | **run 结束时按累计 token 实时扣**（流水 1 条/run，事务原子） |
| 余额不足 | **run 创建时拦截**（400 insufficient_points），生成暂停提示充值 |
| 换算（配置化） | `points_tokens_per_point=10000`（1 积点=10000 token） |
| 新手赠送（配置化） | `points_initial_grant=1000`（=1000 万 token，约 200 次方案生成）——**lazy 创建**（老用户首次查余额时补建） |
| 页面 | 浅色专业仪表盘（余额大卡/用量趋势/规则/流水表/兑换码/套餐） |

**关键前提**：DeepSeek 流式响应最后一个 SSE 数据帧带 `usage`（需 `stream_options: {include_usage: true}`）；当前 `_iter_sse_content` 未解析 usage——需采集。

## 2. 数据模型（3 新表，手写迁移，续当前 head）

### 2.1 user_points（余额）

```
user_id           uuid PK FK users.id
balance           integer NOT NULL DEFAULT 0      -- 当前余额（积点，正整数）
total_granted     integer NOT NULL DEFAULT 0
total_consumed    integer NOT NULL DEFAULT 0
updated_at        timestamptz NOT NULL
```

### 2.2 point_transactions（append-only 流水，只增不改）

```
id            uuid PK
user_id       uuid FK users.id NOT NULL index
amount        integer NOT NULL                    -- 正=入账，负=扣费
type          varchar(20) NOT NULL                -- grant / consume / redeem
ref           text NOT NULL DEFAULT ''            -- run_id（consume）/ code（redeem）/ description 补充
created_at    timestamptz NOT NULL
```

### 2.3 redeem_codes

```
code          varchar(32) PK                      -- 生成的兑换码（大写字母数字，如 XK9F-2MNP-QR7T）
points        integer NOT NULL
created_by    uuid FK users.id NOT NULL
created_at    timestamptz NOT NULL
used_by       uuid FK users.id NULL
used_at       timestamptz NULL
```

## 3. token 用量采集（llm.py）

`stream_text` 改造（所有 LLM 调用都走它——planner/thought/final answer 三处已核实）：

```python
async def stream_text(
    self, messages: list[dict[str, str]],
    usage_sink: Callable[[dict], None] | None = None,
) -> AsyncIterator[str]:
    payload = {
        ...,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    ...
    async for line in response.aiter_lines():
        async for chunk in self._iter_sse_content([line], usage_sink=usage_sink):
            yield chunk
```

`_iter_sse_content(frames, usage_sink=None)`：解析帧时若 `data.get("usage")` 非空 → `usage_sink(data["usage"])`（usage 帧与 content 帧可同帧——delta.content 为空时只是不 yield，不影响 usage 提取）。

**调用点接入**（loop.py 三处 stream_text 调用 + planner.py）：各调用处创建 `usage_holder = {}`，传 `usage_sink=lambda u: usage_holder.update(u)`，流结束后 `tokens = usage_holder.get("total_tokens", 0)` 累加到 run 级累计器。

**run 级累计**：`_AttemptContext` 加字段 `llm_tokens: int = 0`（核实 ctx 定义位置——loop.py 内 dataclass/class）；每段流结束后 `ctx.llm_tokens += tokens`。无 usage（兜底）时记 0 不扣。

## 4. 扣费（app/services/points.py 新建）

```python
POINTS = settings  # points_tokens_per_point / points_initial_grant

def tokens_to_points(tokens: int) -> int:
    return math.ceil(tokens / settings.points_tokens_per_point)  # 不足1积点按1积点扣（向上取整，最少扣1）

async def get_or_create_points(db, user_id) -> UserPoints:
    # 无行 → 建行 balance=points_initial_grant + grant 流水（type=grant, ref="welcome"）

async def deduct_for_run(db, user_id, run_id, tokens) -> int:
    # points = tokens_to_points(tokens); points==0 → 0 不扣
    # 原子：UPDATE user_points SET balance=balance-:p, total_consumed=total_consumed+:p
    #       WHERE user_id=:id AND balance>=:p  RETURNING balance
    # 行数 0 → raise InsufficientPointsError（防御；创建时已检查）
    # INSERT point_transactions(type=consume, ref=run_id, amount=-points)
    # 返回扣的积点数

async def grant_points(db, user_id, points, type_, ref, description="") -> None
    # UPDATE balance/total_granted + 流水

async def redeem_code(db, user_id, code) -> dict
    # 查码：不存在/已用 → ApiError 400 invalid/reused
    # 原子领取：UPDATE redeem_codes SET used_by=:uid, used_at=now WHERE code=:c AND used_by IS NULL
    #   行数 0 → ApiError 400 code_reused
    # grant_points(user_id, points, "redeem", ref=code) → 返回 {points}
```

**接入点（loop.py）**：run 终态（run_succeeded / run_failed 的 `_persist_terminal_and_notify` 之后、`_do_process_attempt` 收尾处）调 `deduct_for_run(db, owner_user_id, run_id, ctx.llm_tokens)`——**失败不阻塞**：扣费异常（DB 错误等）只记录日志，不影响 run 结果（账务后补）。run 失败也扣（已消耗的 token 真实发生）。

## 5. 余额不足拦截（agent.py create_run）

`POST /api/agent/sessions/{session_id}/runs` 创建时：

```python
points = await get_or_create_points(db, current_user.id)
if points.balance <= 0:
    raise ApiError(status_code=400, code="INSUFFICIENT_POINTS", message="积点余额不足，请先充值")
```

（`get_or_create_points` 在 create_run 事务内。）retry/answer 端点同样检查（`POST /runs/{run_id}/retry` 也是新生成）。

## 6. API

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/points/me` | 登录 | `{balance, total_granted, total_consumed, recent: [流水20条{id,amount,type,ref,created_at}]}` |
| GET | `/api/points/usage` | 登录 | 近 30 天每日 `[{date, tokens, points}]`（按 consume 流水 ref 关联 run？——**简化**：流水不含 token 数——需要 token 聚合 → point_transactions 加 `tokens` 列（可空，consume 时填）——**修订 2.2**：加 `tokens integer NULL` 列，usage 查询按日 sum(tokens) |
| POST | `/api/points/redeem` | 登录 + csrf | `{code}` → `{points}` |
| POST | `/api/admin/points/grant` | 超管 + csrf | `{user_id, points, description}` → `{balance}` |
| GET | `/api/admin/points/all` | 超管 | 用户余额列表（用户管理页显示）`[{user_id, username, balance}]` |
| POST | `/api/admin/redeem-codes` | 超管 + csrf | `{points, count}` → `{codes: [...]}`（生成 count 个） |
| GET | `/api/admin/redeem-codes` | 超管 | 全部码 + 使用状态（分页） |

**point_transactions 修订**：加 `tokens integer NULL`（consume 行填 token 数，usage 聚合用）。

## 7. 前端

### 7.1 账户页重构（浅色仪表盘）

- **余额大卡**：渐变蓝（#3370ff→#2f54eb）大数字 + "积点" + 总额/已消耗小字
- **兑换码**：输入框 + [兑换] 按钮（内联在余额卡下方）
- **用量趋势**：近 30 天每日 token CSS 柱状条（flex 容器，柱高按最大值归一化；tooltip=title 属性）——不引入图表库
- **计费规则卡**：换算比例、赠送说明、充值方式说明（"联系管理员充值或输入兑换码"）
- **套餐区**：三档卡（保留），按钮改"联系管理员充值"（提示 message）
- **流水表**：antd Table（时间/类型 Tag：充值绿/兑换蓝/消耗红/说明/数量），分页 10 条，数据来自 GET /api/points/me recent
- 空态/加载态处理

### 7.2 用户管理页（超管）

- 用户表格加"余额"列（GET /api/admin/points/all 合并显示，默认 "—"）
- 每行操作加"充值积点"按钮 → Modal（数量 + 说明）→ POST grant → 刷新
- 顶部工具栏加"兑换码管理"按钮 → Modal：生成区（积点 + 数量 → 生成 → 显示码列表可复制）+ 码列表表格（码/积点/状态/使用人/时间，分页）

### 7.3 余额不足提示

- 会话页发消息/重试时 createRun 失败 400 insufficient_points → message.error("积点余额不足，请前往「账户」充值")

### 7.4 数据接入

- `frontend/src/lib/api.ts`：`getMyPoints()`、`getPointsUsage()`、`redeemPoints(code)`、`adminGrantPoints()`、`adminPointsAll()`、`adminCreateRedeemCodes()`、`adminListRedeemCodes()`
- `points-config.ts` 常量更新为真实换算（展示用，后端为准）

## 8. settings 配置

```python
points_tokens_per_point: int = 10000
points_initial_grant: int = 1000
```

（config.py Settings 加两项，.env 可覆盖。）

## 9. 失败处理与安全

- 扣费失败（DB 异常）只记日志不阻塞 run（账务后补）；`balance >= points` 原子 UPDATE 防并发负余额
- 兑换码：原子领取（UPDATE ... WHERE used_by IS NULL）+ 无效/重复码 400；码为 12 位大写（4-4-4 分组）
- 流水 append-only；不存敏感信息
- 新用户注册（auth.py register）不建 points 行——首次查询 lazy 创建（老用户兼容）

## 10. 测试策略

- llm usage 采集：mock SSE 帧（content 帧 + usage 帧）→ usage_sink 收到正确 total_tokens；无 usage 帧 → 不回调
- points 服务：tokens_to_points（向上取整/0 值）；get_or_create（lazy 建行 + welcome 流水）；deduct（原子扣、流水、不足抛错）；grant；redeem（成功/无效码/重复领）
- 扣费接入：run 完成 → 扣费被调（mock points 服务）、ctx.llm_tokens 累计正确、失败不阻塞
- API：/points/me（余额+流水）、/points/usage（30 天聚合）、redeem（400 场景）、admin grant/codes（权限 403 非超管）
- create_run 余额拦截：balance=0 → 400 insufficient_points
- 前端：账户页渲染（余额/流水/兑换）、充值按钮流程、tsc

## 11. 明确不做

- 第三方支付（微信/支付宝）、配额限制/防刷、token 用量分模型统计（prompt/completion 分开）
- 负余额容忍、账单月结、积分过期
