# 飞书文档集成 — 企业级方案

## Goal

Agent 通过飞书开放平台 API 读取、创建、编辑、评论、共享用户 OAuth 授权范围内的飞书文档。生成的飞书文档同步一份 Markdown 副本到「我的文件」。

## Architecture

```
┌──────────────────────────────────────────────────┐
│  Agent ToolExecutor                               │
│  ├─ feishu_read_doc    (读文档)                   │
│  ├─ feishu_create_doc  (新建文档)                 │
│  ├─ feishu_edit_doc    (编辑章节)                 │
│  └─ feishu_share_doc   (设置共享权限)             │
├──────────────────────────────────────────────────┤
│  FeishuService (服务层)                           │
│  ├─ Token 管理: user_access_token 缓存+刷新       │
│  ├─ 文档 API 调用 (open.feishu.cn/docx)           │
│  └─ 错误映射: 飞书错误码 → RetryableToolError     │
├──────────────────────────────────────────────────┤
│  飞书 OAuth 集成                                  │
│  ├─ 用户授权入口 (前端按钮 → 跳转飞书授权页)      │
│  ├─ 回调端点 (GET /api/feishu/oauth/callback)     │
│  └─ Token 加密存储 (DB user_feishu_tokens)        │
└──────────────────────────────────────────────────┘
```

## Components

### 1. OAuth 授权流程

| 端点 | 说明 |
|------|------|
| `GET /api/feishu/oauth/start` | 生成飞书授权 URL，重定向用户到飞书授权页 |
| `GET /api/feishu/oauth/callback` | 飞书回调，code → user_access_token，加密存 DB |
| `GET /api/feishu/status` | 返回当前用户飞书连接状态 |

授权 URL：
```
https://open.feishu.cn/open-apis/authen/v1/authorize
  ?app_id={app_id}
  &redirect_uri={callback_url}
  &scope=docx:document:readonly,docx:document
  &state={random_state}
```

### 2. Token 存储

新表 `user_feishu_tokens`：
- `owner_user_id` (PK/FK)
- `access_token` (AES 加密)
- `refresh_token` (AES 加密)
- `expires_at`
- `open_id`
- `created_at`, `updated_at`

加密：AES-GCM，密钥从 `JWT_SECRET` 派生（HKDF）。

### 3. FeishuService 核心方法

```python
class FeishuService:
    async def get_access_token(self, owner_user_id) -> str  # 自动刷新
    async def read_document(self, owner_user_id, doc_token) -> dict
    async def create_document(self, owner_user_id, title, markdown) -> dict
    async def edit_document(self, owner_user_id, doc_token, block_id, new_content) -> dict
    async def set_permission(self, owner_user_id, doc_token, permission) -> dict
```

### 4. 文档 API 端点

| 操作 | 飞书 API |
|------|---------|
| 读正文 | `GET /open-apis/docx/v1/documents/{id}/raw_content` |
| 新建文档 | `POST /open-apis/docx/v1/documents` |
| 写内容 | `POST /open-apis/docx/v1/documents/{id}/blocks` |
| 编辑段落 | `PATCH /open-apis/docx/v1/documents/{id}/blocks/{block_id}` |
| 共享权限 | `PATCH /open-apis/drive/v1/permissions/{token}/public` |

### 5. Agent 工具（4 个 action）

| action | input |
|--------|-------|
| `feishu_read_doc` | `doc_token: str` |
| `feishu_create_doc` | `title: str, content: str, folder_token?: str` |
| `feishu_edit_doc` | `doc_token: str, block_id: str, new_content: str` |
| `feishu_share_doc` | `doc_token: str, permission: str` |

### 6. 本地同步

`feishu_create_doc` 成功后：
1. 飞书返回 `document_id` + 链接
2. 用现有 `FileService` 把 Markdown 内容写入 `var/files/{user_id}/{uuid}.md`
3. 返回给 LLM：飞书链接 + 本地文件路径

### 7. 配置

```python
feishu_app_id: str = ""
feishu_app_secret: str = ""
feishu_redirect_uri: str = "http://localhost:3000/api/feishu/oauth/callback"
feishu_token_encryption_key: str = ""  # 留空则从 JWT_SECRET 派生
```

## Error Mapping

| 飞书错误码 | 处理 |
|-----------|------|
| 99991663 (token 过期) | 尝试 refresh；失败 → 提示重新授权 |
| 99991668 (无权限) | `ValueError("feishu_permission_denied")` |
| 99991672 (限流) | `RetryableToolError` |
| 网络错误 | `RetryableToolError` |

## Security

- Token AES-GCM 加密存储
- 每用户 token 隔离（owner_user_id）
- LLM 永不看到 token 明文
- OAuth state 参数防 CSRF

## Files

| File | Change |
|------|--------|
| `backend/app/models/feishu_token.py` | **New.** Token 模型 |
| `backend/app/services/feishu/oauth.py` | **New.** OAuth 授权 |
| `backend/app/services/feishu/client.py` | **New.** 飞书 API 客户端 |
| `backend/app/api/feishu.py` | **New.** OAuth 端点 |
| `backend/app/services/agent/tool_executor.py` | 4 个 feishu action |
| `backend/app/services/agent/planner.py` | 4 个 schema + prompt |
| `backend/app/core/config.py` | 飞书配置 |
| `backend/tests/test_feishu.py` | 单元测试 |
| `frontend/src/components/...` | 连接飞书按钮 |

## Non-Goals

- 飞书表格/多维表格
- 实时同步（文档变更监听）
- 多租户飞书应用
