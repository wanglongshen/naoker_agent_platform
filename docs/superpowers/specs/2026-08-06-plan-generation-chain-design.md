# 方案生成链路（文件夹即项目 + 飞书同步 + 生成记录） Design Spec v2

**Status:** Draft
**Date:** 2026-08-06

## 1. 范围（v2 修订，用户确认）

| 功能 | 方案 |
|---|---|
| 项目隔离 | ✅ **项目 = 用户文件库中的一个顶层文件夹**（文件库 owner_user_id 隔离 + 文件夹树导航隔离即项目隔离）；不建项目表/页面 |
| 飞书同步开关 | ✅ **用户级**：连接飞书区域加"方案同步到飞书"开关（`users.sync_feishu_enabled`） |
| 生成记录（审计） | ✅ `generation_logs` 挂 **folder_id**；文件页内查看 |
| 飞书 AK/SK 用户级 | ❌ 暂缓（沿用系统级配置 + 用户 OAuth token） |
| 小红书/文件共享/商业化/项目权限 | ❌ 暂缓/另一进程 |

**核心复用**：飞书同步用**用户 OAuth token**（`FeishuService.get_access_token` + `markdown_to_blocks` + `create_document` 全部已实现）；方案文件 = Agent `write_file` 写入文件库的 FileObject。

## 2. 数据模型（迁移）

### 2.1 users 加列

```
sync_feishu_enabled boolean NOT NULL DEFAULT false   -- 用户级飞书同步开关
```

### 2.2 generation_logs（append-only）

```
id             uuid PK
folder_id      uuid FK file_folders.id NOT NULL      -- 方案所在文件夹（项目）
user_id        uuid FK users.id NOT NULL
session_id     uuid FK agent_sessions.id NOT NULL    -- 生成该方案的会话
run_id         uuid FK agent_runs.id NOT NULL
input_text     text NOT NULL                         -- 用户需求原文（后端从 run 事件提取）
final_md_file_id uuid FK file_objects.id NULL        -- write_file 成功产物；无则 NULL（final_answer 兜底）
final_answer   text NOT NULL DEFAULT ''              -- run 最终回答（无文件时的 md 内容来源）
feishu_doc_url text NOT NULL DEFAULT ''              -- 同步成功后的文档链接
status         varchar(20) NOT NULL DEFAULT 'pending'  -- pending/succeeded/failed
error          text NOT NULL DEFAULT ''
created_at     timestamptz NOT NULL
updated_at     timestamptz NOT NULL
```

append-only：仅 INSERT + 一次 status 更新（pending→succeeded/failed）；无删除/更新 API。

### 2.3 迁移

手写两个迁移（写前 `alembic heads` 核实）：`add_users_sync_feishu_enabled`（ALTER users 加列）、`add_generation_logs`（建表）。

## 3. 后端 API（新 `app/api/generations.py`，挂 /api/generations）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/generations?folder_id=&page=&page_size=` | 当前用户某文件夹的生成记录（倒序分页；folder_id 必填） |
| POST | `/api/generations` | body {session_id, run_id} → 校验 run 归属与完成 → 提取 input_text（run 事件首条 user 消息）→ 找 write_file 成功产物 FileObject（folder_id 取其父文件夹）→ INSERT 记录 → 若用户 sync_feishu_enabled → 飞书同步 → 返回记录 |

**权限**：GET 校验 folder_id 文件夹归属（owner 或超管，复用 `_check_file_access` 同款校验）；POST 校验 run 归属（`get_owned_agent_run` 同款）+ 产物文件归属一致。

**飞书同步流程**（POST 内同步执行、失败不阻塞）：

```
1. sync 开关关 / 用户未连接飞书 → 跳过（error="" / error="未连接飞书"）
2. 内容源：final_md_file_id 的 FileObject（storage_key 读磁盘，编码回退，>200KB 截断）→ 无文件用 final_answer
3. title = f"{文件夹名} - 方案 - {YYYY-MM-DD HH:mm}"
4. FeishuService.create_document(user_id, title) → add_blocks(markdown_to_blocks(content))
5. feishu_doc_url = https://feishu.cn/docx/{doc_token}
6. 异常 → error=异常消息（不存凭据），status 仍 succeeded（md 已成功）
```

## 4. 前端

### 4.1 飞书同步开关（feishu-connect.tsx）

连接飞书区域（超管配置区下方/连接按钮旁）加一行：`方案同步到飞书` Switch（用户级，读 users.sync_feishu_enabled，切换调 `PUT /api/me/sync-feishu`——新端点或并入现有 /api/auth/me 相关；简单加 `PUT /api/me/sync-feishu {enabled}`）。所有用户可见（员工也可开关自己的）。

### 4.2 文件页生成记录

- **我的文件页**（file-manager.tsx）：工具栏加"生成记录"按钮（当前选中文件夹的）→ 打开列表（抽屉/Modal）：时间、状态徽标、输入摘要、[详情]
- **记录详情**：输入原文、方案文件（点击跳文件预览）、飞书文档链接（新窗口）、错误信息、时间
- 页面归属：`(agent)/files` 内实现（复用现有文件页组件模式）

### 4.3 触发（run 完成自动记）

现有 Agent 会话页 run 完成后（SSE `run_succeeded`/`answer_completed` 回调处，use-run-event-stream 或会话页组件）调用 `POST /api/generations {session_id, run_id}`（**所有 run 都调**——后端无 write_file 产物时记录 final_answer 兜底，folder_id 从产物取；**产物 folder 为 null（根目录）时 folder_id 置空？**——generation_logs.folder_id NOT NULL 约束与根目录方案冲突——**folder_id 可空**（根目录产物 → NULL folder，前端"我的文件-全部"视图可查）。修订：folder_id 可空 FK。

## 5. 失败处理与审计要求

- 飞书同步失败：status=succeeded + error 记录原因（审计可见）
- 未连飞书：error="未连接飞书"
- 不存敏感信息；日志不输出 token
- append-only：无删除/修改端点

## 6. 测试策略

- 迁移：users 列 + generation_logs 建表
- POST /generations：run 归属 403；input_text 从事件提取；write_file 产物识别（FileObject + folder_id）；无产物 final_answer 兜底 + folder_id NULL；飞书同步（mock create_document）成功写 url；开关关/未连接 → 不调/error 记录；异常 → succeeded + error
- GET /generations：文件夹归属 403；分页
- PUT /api/me/sync-feishu：更新 users 列
- 前端：tsc + vitest（开关切换、生成记录列表/详情渲染）

## 7. 明确不做

- 项目表/页面/成员权限
- 用户级 AK/SK
- 图片上传飞书、双向同步
- 记录修改/删除/从中间稿重跑
- 商业化
