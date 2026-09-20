# 知识库管理（库 → 文件 两级）设计

- 日期：2026-09-17
- 状态：设计已确认（用户批准），待实施
- 设计稿（可视）：`.superpowers/brainstorm/kb-manage-01/design.html`（四个页签：库列表 / 数据集 / 搜索测试 / 配置）
- 关联：二期 RAG（`docs/superpowers/specs/2026-09-07-dsh-platform-rebase-design.md` 第 3 节）、实施计划 `docs/superpowers/plans/2026-09-15-rag-industry-kb.md`

## 1. 背景与目标

现状：二期 RAG 已交付「行业知识库」——192 篇文档 / 1,501 块切块、评测集 recall@5 = 90.9%、检索 P95 = 26ms。但管理界面 `/knowledge` 只有一个**扁平文档列表**，缺少「库」这一层，无法承载多库（行业库 / 规则库 / 自定义库），也不支持在界面里上传文件入库。

目标：把 `/knowledge` 升级为**知识库管理**，做成「库列表 → 库详情（数据集 / 搜索测试 / 配置）」两级结构：

1. 库层：新建 / 重命名 / 改介绍 / 改可见范围 / 停用检索 / 删除，卡片展示真实统计。
2. 文件层：分页表格（名称 / 训练模式 / 数据总量 / 创建更新时间 / 状态 / 启用开关 / 操作）、按名称与来源搜索、批量操作、切块预览。
3. 导入：支持**上传文件入库**（解析 → 切分 → 向量化，异步 + 进度）与**从已采集素材导入**。
4. 检索验证：库内搜索测试页，展示命中片段、相似度、章节路径与来源链接。

约束（已确认）：

- **平台级、仅超管管理**：不新增权限码，12 权限体系一字不动；检索对全部登录用户开放（沿用二期 spec）。
- 沿用现有设计语言与色板（`#e8751d` 侧栏 / `#D96313` 主色 / `#FAF7F3` 底 / `#2B2521` 文字），不照搬截图配色。
- 复用既有服务与模式：`parsing` / `chunking` / `embedding` / `store`、文件库的魔术字节嗅探、`task_chain_worker` 的 `FOR UPDATE SKIP LOCKED` 领取模式、`PageHeader`/`view-states`/AntD 组件。

## 2. 范围

**v1 做**

- 多库数据模型 + 迁移回填（现有 192 篇 → 默认库「行业知识库」）
- 库 CRUD、库统计、库维度文档列表与检索过滤
- 上传文件入库（异步任务 + 进度 + 失败原因 + 重试）
- 从已采集素材批量导入（消费 `var/kb_industry/` 与 `manifest-core.json` 白名单）
- 搜索测试页、配置页（展示 + 少量可改项）
- 文档启用/禁用（已有）、删除、重新切分、切块预览

**v1 不做（记录在案）**

- UI 触发网络采集爬虫（采集源白名单只做展示；导入走「已采集素材」）
- Embedding 模型与切分参数的库级可改（改动需重建索引，留 v2）
- 用户私有库与配额（归属已定：平台级）

## 3. 数据模型与迁移

### 3.1 新表 `rag_libraries`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | uuid PK | |
| `name` | String(120) unique | 库名，重复返回 409 |
| `description` | Text nullable | 介绍，空时前端显示「这个知识库还没有介绍~」 |
| `kind` | String(32) default `custom` | `industry` / `rules` / `custom`（仅影响标签展示） |
| `visibility` | String(16) default `admins_only` | `admins_only` / `all_members`（仅标签与文案，不新增权限码） |
| `retrieval_enabled` | Boolean default true | false 时该库**不参与 Agent 检索** |
| `created_by` | uuid nullable | 操作人 |
| `created_at` / `updated_at` | timestamptz | |

### 3.2 改 `rag_documents`

- 加 `library_id`：FK → `rag_libraries.id`（`ondelete=CASCADE`），建索引 `ix_rag_documents_library_id`
- 加 `error_message`：Text nullable（入库失败原因）
- `status` 取值扩展为 `pending` / `processing` / `ready` / `failed` / `disabled`

### 3.3 迁移与回填

一个 alembic 迁移完成：建表 → 加列（先 nullable）→ 插入默认库「行业知识库」（`kind=industry`、`visibility=admins_only`、`retrieval_enabled=true`）→ `UPDATE rag_documents SET library_id = <默认库>` → 置 `NOT NULL`。回填结果在迁移测试中断言（192 篇全部有库）。

### 3.4 新表 `rag_jobs`（入库任务）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | uuid PK | |
| `library_id` | uuid FK | |
| `doc_id` | uuid FK nullable | 单文档导入时有值 |
| `kind` | String(16) | `upload` / `import` |
| `status` | String(16) | `queued` / `running` / `succeeded` / `failed` / `superseded`（同一文档重复入队时旧任务标记为 `superseded`，worker 跳过） |
| `total` / `processed` | Integer | 进度（文件数） |
| `error_message` | Text nullable | |
| `payload` | JSONB nullable | 导入参数（源目录、白名单路径等） |
| `created_by` / `created_at` / `started_at` / `finished_at` | | |

## 4. 后端 API（全部 `require_super_admin`）

库：

- `GET /api/rag/libraries` → 列表 + 统计（`doc_count` / `chunk_count` / `ready_count` / `failed_count` / `last_updated_at`）
- `POST /api/rag/libraries` `{name, description?, kind?}` → 新建（重名 409）
- `GET /api/rag/libraries/{id}` → 详情
- `PATCH /api/rag/libraries/{id}` `{name?, description?, visibility?, retrieval_enabled?}`
- `DELETE /api/rag/libraries/{id}` → 非空库默认 409（提示先清空），`?force=true` 级联删除

文件：

- `GET /api/rag/libraries/{id}/documents?q=&status=&page=&page_size=` → 分页 + 名称/来源搜索
- `POST /api/rag/libraries/{id}/documents`（multipart）→ 落盘 + 建文档(`pending`) + 建任务 → 返回 `{doc_id, job_id}`
- `POST /api/rag/libraries/{id}/import` `{source: "collected", scope: "core"|"all", category?: "methodology"|"rules"|"other", limit?}` → 从已采集素材导入（`scope=core` 消费 `manifest-core.json` 226 篇方法论白名单；`scope=all` 消费全量 `manifest.json` 601 篇，可按 `category` 过滤；sha256 去重；进度按文件数）
- `POST /api/rag/documents/{id}/disable` / `enable`（已有）
- `DELETE /api/rag/documents/{id}` → 删文档 + 切块 + 上传文件
- `POST /api/rag/documents/{id}/reingest` → 重新解析切分入库（复用原文件或原始素材）
- `GET /api/rag/documents/{id}/chunks?page=&page_size=` → 切块预览

任务：

- `GET /api/rag/jobs/{id}` → 进度（前端轮询）
- `GET /api/rag/jobs?library_id=&active=true` → 活跃任务（页面初始化时恢复进度显示）

检索：

- `POST /api/rag/search` 改造：新增可选 `library_id` 过滤；返回结果附 `library_id` / `library_name`

## 5. 入库管线与异步任务

**公共函数**（CLI 与 API 共用一套，避免两份实现）：把现有 `ingest.py` 的入库逻辑抽为 `ingest_document(session, *, library_id, title, text|path, source_url, publisher, license_note, sha256, ...)`，返回 `(doc, chunk_count)`；CLI 改为调用它。

**上传流程**：`POST .../documents` → 校验（扩展名白名单 + 魔术字节嗅探 + ≤20MB + 同库 sha256 去重）→ 存 `var/rag/uploads/<uuid>.<ext>`（gitignored）→ 建 `rag_documents(pending)` + `rag_jobs(queued)` → 返回。

**执行**：新增 `backend/app/workers/rag_ingest_worker.py`（与 `task_chain_worker` 同款：轮询 + `FOR UPDATE SKIP LOCKED` + 优雅退出）。逐文件：`pending → processing` → 解析（`parsing`）→ 切分（`chunking`，标题感知 512/64）→ embedding（本地 `bge-small-zh-v1.5`，512 维）→ 写 `rag_chunks` → `ready`；异常 → `failed` + `error_message`，任务计数继续推进。

**进度**：`rag_jobs.processed/total`（导入任务按文件数）；单文档任务 processed 0→1。

**失败可见**：表格状态列显示「失败」+ tooltip 原因，「···」提供「重试」。

## 6. 前端设计

路由与页面：

- `/knowledge` → 库列表（卡片网格 + 顶部统计条 + 搜索 + 新建库）
- `/knowledge/[libraryId]?tab=datasets|search|config` → 库详情：左侧子导航（数据集 / 搜索测试 / 配置 / ← 全部知识库），右侧内容区

新增组件（`frontend/src/components/knowledge/`）：

- `library-grid.tsx` / `library-card.tsx`（统计、权限与类型标签、检索状态、`···` 菜单：重命名/介绍/可见范围/停用检索/删除）
- `new-library-modal.tsx`、`upload-modal.tsx`（拖拽 + 文件列表 + 进度轮询）
- `dataset-table.tsx`（分页、搜索、批量启用/禁用/删除、启用开关、行内 `···`：预览切块/查看来源/重新切分/删除）；「训练模式」列固定显示「直接分段」（v1 只有标题感知切分一种模式，列保留以便 v2 扩展）
- `search-test-panel.tsx`（Top-K、仅启用文档、命中卡片：相似度条 + 章节路径 + 来源链接）
- `config-panel.tsx`（基础信息可改；向量与切分只读；采集来源白名单展示；危险区）
- `chunk-preview-drawer.tsx`

改造：侧栏文案「知识库」→「知识库管理」（`copy.navigation.knowledge`）；`document-list.tsx` / `document-preview-drawer.tsx` 由新组件替代（旧文件删除，测试同步替换）。

轮询：页面可见且存在 `pending/processing` 文档或活跃任务时，每 3s 拉取一次（`document.visibilityState` 判断，离开页面停止）。

## 7. 边界与错误处理

- 库名重复 → 409，前端表单内联报错
- 删除非空库 → 409 + 提示（「先清空或强制删除」）；`force` 级联删除文档、切块、上传文件
- 上传：扩展名白名单（pdf/docx/xlsx/pptx/txt/md/csv/html）+ 魔术字节嗅探（沿用文件库 `_detect_mime_type`）+ ≤20MB + 同库 sha256 去重（重复 → 409 提示已存在）
- 解析为空（纯图片 PDF 等）→ `failed` + `error_message="未提取到正文"`，可重试
- `retrieval_enabled=false` 的库：`/api/rag/search` 与 DSH `knowledge_search` 均跳过；搜索测试页可显式指定该库（用于调试）
- 文档 `disabled`：不参与检索，但保留切块
- 并发：worker 领取用 `FOR UPDATE SKIP LOCKED`；同一文档重复入队时以最新任务为准（旧任务标记 superseded）

## 8. 测试与验收

**后端测试**（新增 `tests/test_rag_libraries_api.py`、`test_rag_documents_api.py`、`test_rag_jobs_api.py`、`test_rag_ingest_worker.py`、迁移回填测试）：

- 库 CRUD、重名 409、非空删除 409 / force 级联
- 文档分页、搜索、状态过滤、启用/禁用、删除、切块预览
- 上传：白名单拒绝、超限拒绝、sha256 去重、任务入队
- worker：成功入库（chunk_count > 0）、解析为空 → failed + 原因、重试成功
- 检索：`library_id` 过滤、停用库被跳过
- 迁移：回填后 192 篇全部有 `library_id`

**前端测试**：库列表渲染与空态、新建校验（重名/空名）、详情表格分页与开关、上传进度、搜索测试、权限门（非超管拒绝）。

**验收（人工）**：

1. 新建库 → 上传一份 PDF → 进度到 `ready` → 块数正确 → 搜索测试能命中 → Agent 工作台里 `knowledge_search` 能引用到新库
2. 「平台规则库」从已采集素材导入（254 篇规则类）→ 进度完成 → 状态就绪
3. 回归：现有 192 篇仍在「行业知识库」下，评测集 `scripts/rag_eval.py` recall@5 ≥ 90%（不因迁移与重构下降）
4. 权限：普通用户访问 `/knowledge` → 拒绝；Agent 检索仍对全部登录用户可用

## 9. 风险与后续

- **风险**：迁移回填后置 NOT NULL 需在开发库与测试库都验证（迁移测试覆盖）；上传大文件阻塞（已限制 20MB + 异步 worker）；worker 未启动时任务排队（状态页显示「排队中」，README 补充说明）
- **后续（v2）**：库级 embedding/切分参数与索引重建；UI 触发采集；用户私有库；检索重排（rerank）开关
