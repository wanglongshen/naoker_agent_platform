# 过程稿时间线（详细版）+ 商业化界面 Design Spec

**Status:** Draft
**Date:** 2026-08-06

## 1. 范围（用户确认）

| 功能 | 方案 |
|---|---|
| 过程稿（3.6 补充） | ✅ 生成记录详情新增**时间线过程稿**：从 run 事件流组装（零新表） |
| 商业化界面（3.7） | ✅ 侧边栏"账户"新页面：余额/用量/规则/套餐，mock 数据标注"示例" |
| 用户级 AK/SK（3.2） | ❌ 维持现状（系统级多份配置 + 用户 OAuth——企业级标准，已向用户解释确认） |
| 分享占位/成员权限/小红书 | ❌ 不做 |

## 2. 过程稿时间线

### 2.1 数据源（已核实）

`agent_run_events` 表已含全链路事件（每事件：event_type/payload/seq/created_at），payload 结构：

| 事件 | payload 关键字段 |
|---|---|
| `visible_thought_completed` | step_index, text（**完整思考文本**）, length, fallback |
| `step_completed` | step_index, action_type, tool_call（输入参数，safe_fields 已过滤）, observation（工具输出）, step_duration_seconds |
| `answer_completed` | text（最终稿全文） |
| `run_succeeded` | final_answer |
| `run_failed` | error（失败原因） |

### 2.2 后端接口

`GET /api/generations/{log_id}/timeline`（generations.py 扩展）：

- 权限：log 归属校验（log.user_id == current_user.id 或超管）→ 403
- 取 log.run_id → 查该 run 的 AgentRunEvent（按 seq 升序）
- 组装时间线（服务端提取，不暴露原始 payload 无关字段）：

```python
def _timeline_entry(ev) -> dict:
    p = ev.payload or {}
    if ev.event_type == "visible_thought_completed":
        return {"type": "thought", "step_index": p.get("step_index"), "content": p.get("text", ""), "created_at": ...}
    if ev.event_type == "step_completed":
        return {
            "type": "tool",
            "step_index": p.get("step_index"),
            "action_type": p.get("action_type", ""),
            "input": p.get("tool_call") or {},
            "observation": _sanitize_observation(p.get("observation")),   # 截断 500 字 + 状态标记
            "duration_seconds": p.get("step_duration_seconds"),
            "created_at": ...,
        }
    if ev.event_type == "answer_completed":
        return {"type": "answer", "content": p.get("text", ""), "created_at": ...}
    if ev.event_type == "run_failed":
        return {"type": "terminal", "status": "failed", "error": p.get("error", ""), "created_at": ...}
    if ev.event_type == "run_succeeded":
        return {"type": "terminal", "status": "succeeded", "created_at": ...}
    return None  # 其他事件（delta 流/started 等）不进时间线
```

- `_sanitize_observation`：observation 为 dict/str 时提取可读文本（dict → 取 error/file_id/filename/path/summary 等白名单字段或 str 截断；str → 原样截断 500 字）；**不输出二进制内容/凭据**（observation 已有纪律）
- 响应：`{steps: [...]}`，按 seq 升序
- 思考/答案内容**不截断**（全文）

### 2.3 前端（generation-records-modal.tsx 扩展）

生成记录详情弹窗新增"**过程稿**"区块（时间线）：

- 时间线组件（纯 CSS/antd，无第三方）：步骤节点列表（序号 + 类型图标：思考💭/工具🔧/答案📄/终态✅❌）
- 每个节点可折叠（antd Collapse 或自定义）：
  - **思考**：全文展示（不截断）
  - **工具**：`工具名` + 输入参数（JSON 紧凑展示，file 路径高亮）+ 输出摘要（截断 500，成功绿/失败红）+ 耗时（`耗时 3.2s`）
  - **答案**：全文（简单文本/Markdown 已有 ReactMarkdown 可复用——**用纯文本 pre-wrap 即可**，避免引入依赖）
  - **终态**：成功绿标/失败红标 + error 全文
- 失败高亮：terminal=failed 时该节点红色边框 + 其前 2 步自动展开
- 工具输入展示：`input` dict → `JSON.stringify(input, null, 2)` 放 `<pre>`（小字号）

### 2.4 测试

- 后端：timeline 组装（mock 事件：thought/tool/answer/succeeded → 正确顺序与字段；run_failed → terminal failed + error；无事件 → steps 空；他人 log → 403）；_sanitize_observation 截断与白名单
- 前端：时间线渲染（步骤数、类型图标、失败高亮）——querySelectorAll 模式

## 3. 商业化界面

### 3.1 页面与导航

- 侧边栏新增"账户"入口（app-sidebar.tsx，放用户区）：→ `/account/points`
- 页面 `(agent)/account/points/page.tsx`（或对应目录——沿用现有页面结构）

### 3.2 内容（纯前端 mock，标注"示例 / 未开放"）

- **余额卡片**：`12345` 积点 + 说明"示例数据 · 未开放"
- **用量统计**：本周/本月 token 消耗 + 换算积点（两个统计卡 + antd Progress 条；无图表库，不引入）
- **积分规则**：说明卡片——"积点为系统虚拟计费单位，后台按 token 消耗换算扣减；当前比例待定（1 积点 ≈ 1000 token，示例值）"
- **套餐/充值**：3 个套餐卡片（体验版/标准版/专业版，积点量 + 价格占位"即将上线"），点击提示"即将上线"
- **换算比例**：独立常量文件（`frontend/src/lib/points-config.ts`：`POINTS_PER_TOKEN`、`MOCK_BALANCE` 等）——"留成配置不写死"（前端常量，后续接后端时替换为 API）
- 页面所有 mock 数据来源该常量文件

### 3.3 测试

- 前端：页面渲染（余额/规则/套餐占位文案）+ tsc

## 4. 明确不做

- 真实计费/扣费/支付、token 用量真实记录、余额流水表
- 用户级 AK/SK、分享、成员权限、小红书
- 图表库引入（YAGNI，统计条够用）
