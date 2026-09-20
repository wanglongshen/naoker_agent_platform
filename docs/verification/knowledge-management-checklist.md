# 知识库管理（库 → 文件 两级）人工验收清单

- 范围：知识库两级改造（`rag_libraries` / `rag_documents.library_id` / `rag_jobs`、上传入库、素材导入、检索过滤、`/knowledge` 两级页面）
- 环境：本机 Windows；后端 `http://127.0.0.1:8010`、前端 `http://localhost:3001`；已用 `scripts\run-all.ps1` 启动（含 `rag-ingest-worker`）
- 账号：管理操作 `admin / ChangeMe-Strong1`（super_admin）；权限项用普通用户 `bai.ling / ChangeMe-Demo1`（demo 种子数据）
- 填法：「实测」由验收人现场填写（通过 / 失败 + 实际数值或截图链接）
- 自动化回归基线（2026-09-17 实测）：RAG 评测 recall@5 = 0.9091、P95 = 24.02ms（`docs/rag-eval/report.md`）；后端全量 `pytest -q` = 1243 passed / 5 failed（5 个均为已知非本轮失败：4 个缺可选依赖的 `test_file_reader` + 1 个他人未跟踪用例 `test_agent_blueprint_closure.py`）

## 1. 新建库 → 上传 PDF → 进度到 ready → 块数正确 → 搜索测试命中 → Agent 引用新库

| # | 操作 | 预期 | 实测 |
| --- | --- | --- | --- |
| 1.1 | admin 打开 `/knowledge` → 「新建知识库」→ 名称 `验收库-<日期>`、类型自定义 → 创建 | 创建成功；卡片出现，文档数 / 切块数均为 0 | |
| 1.2 | 进入该库 → 「数据集」→ 「新建 / 导入」→ 上传一份含文字层的 PDF（≤20MB）→ 「开始上传」 | 上传成功，弹窗出现处理进度并每 3s 轮询 | |
| 1.3 | 等待进度完成（`rag-ingest-worker` 运行中） | 数据集状态变为「已就绪」；切块数 > 0；「预览切块」可看到 PDF 正文 | |
| 1.4 | 打开 `GET /api/rag/documents/{doc_id}/chunks`（或对照切块预览抽屉） | 接口 `total` 与列表显示的块数一致，且等于实际切块数 | |
| 1.5 | 「搜索测试」→ 输入 PDF 原文中的一句话（Top-K 5） | 命中来自本库的片段，显示相似度 / 章节路径 / 来源，`library_name` = `验收库-<日期>` | |
| 1.6 | 打开 `/agent` 新建对话 → 提问一个只在该 PDF 中有的信息 | Agent 调用 `knowledge_search`，回答引用该文档（标题 / 内容片段），不编造 | |

## 2. 平台规则库：从已采集素材导入（254 篇规则类，scope=all&category=rules）

> 当前无前端入口，用接口调用：`POST /api/rag/libraries/{library_id}/import`，body `{"scope":"all","category":"rules"}`（超管 + CSRF；可参考 `backend/tests/test_rag_import_api.py` 的调用方式）。

| # | 操作 | 预期 | 实测 |
| --- | --- | --- | --- |
| 2.1 | 新建库「平台规则库」（kind 可自定义）→ 调用导入接口 | 200，返回 `queued = 254` | |
| 2.2 | `GET /api/rag/jobs/{job_id}`（或前端轮询） | `kind=import`、`total=254`；worker 运行中 `processed` 递增到 254 | |
| 2.3 | 等待任务 `succeeded` → 查看库统计与数据集 | `doc_count = 254`（sha256 去重后 ≤254）、`failed_count = 0`；抽样文档状态「已就绪」、块数 > 0 | |

## 3. 现有 192 篇仍在「行业知识库」下

| # | 操作 | 预期 | 实测 |
| --- | --- | --- | --- |
| 3.1 | `/knowledge` 查看「行业知识库」卡片 | `doc_count = 192`、`chunk_count = 1501`、类型 industry、检索已启用 | |
| 3.2 | 进入「数据集」翻页 / 按状态「已就绪」筛选 | 共 192 篇，均为已就绪，无丢失 / 重复 | |
| 3.3 | 「搜索测试」输入评测集问题（如「直播复盘里的直播成交金额公式是怎么算的？」） | 命中既有文档片段，来源链接可跳转 | |
| 3.4 | 回归评测：`cd backend; $env:WEB_TOOL_ALLOW_NON_GLOBAL_TARGETS="true"; python -m scripts.rag_eval` | `recall@5 = 0.9091 ≥ 0.90`、P95 ≤ 500ms（本次基线 24.02ms），报告写入 `docs/rag-eval/report.md` | |

## 4. 权限：普通用户访问 `/knowledge` 被拒，但 Agent 检索可用

| # | 操作 | 预期 | 实测 |
| --- | --- | --- | --- |
| 4.1 | 以 `bai.ling / ChangeMe-Demo1` 登录 → 直接访问 `/knowledge` | 页面显示「无权限：仅超级管理员可访问知识库管理。」 | |
| 4.2 | 同账号直接请求 `GET /api/rag/libraries`（带其 token） | 403（`require_super_admin`） | |
| 4.3 | 同账号打开 `/agent`，提问行业知识问题（如「抖音电商罗盘的入口在哪？」） | 正常回答并引用知识库内容（检索对全部登录用户开放） | |

## 5. 删除非空库提示

| # | 操作 | 预期 | 实测 |
| --- | --- | --- | --- |
| 5.1 | 对第 1 项建的有文档的库执行删除（卡片「···」→ 删除，或配置页「删除本库」） | 弹窗提示「该知识库仍有 N 篇文档。请先清空文档，或选择『强制删除』…」；直接确认「删除」→ 409 `LIBRARY_NOT_EMPTY` | |
| 5.2 | 选择「强制删除」 | 库及其文档 / 切块 / 上传文件级联删除，卡片消失；`/knowledge` 列表不再出现 | |

## 6. 停用库不参与检索

| # | 操作 | 预期 | 实测 |
| --- | --- | --- | --- |
| 6.1 | 对某库卡片「···」→「停用检索」（或配置页关闭「参与检索」） | 提示「已停用检索」，卡片标签变「检索已停用」 | |
| 6.2 | 该库「搜索测试」输入此前能命中的问题 | 无命中（停用库被跳过） | |
| 6.3 | `/agent` 提问只在该库的内容 | 回答不再引用该库（可引用其他启用库或说明知识库无匹配） | |
| 6.4 | 重新「启用检索」后再搜 | 恢复命中 | |

## 7. `rag_ingest_worker` 未启动时任务显示排队中

| # | 操作 | 预期 | 实测 |
| --- | --- | --- | --- |
| 7.1 | 停止该 worker（`scripts\stop-all.ps1` 后仅启动 backend / frontend；或单独结束其进程） | `scripts\status-all.ps1` 中 `rag-ingest-worker` 显示 stopped | |
| 7.2 | 在任一库上传一份文档 | 上传成功；数据集状态「排队中」；`GET /api/rag/jobs/{job_id}` `status=queued`、`processed=0` | |
| 7.3 | 启动 worker（`python -m app.workers.rag_ingest_worker` 或 `run-all.ps1`） | 3s 内任务变 `running` → `succeeded`，文档状态「已就绪」 | |

## 验收前必须处理的前置问题（2026-09-17 回归发现；同日修复后状态如下）

1. **运行环境缺解析依赖 — 部分修复**：已安装 `pypdf 6.19.0`，第 1 项 PDF 上传链路可跑通（`tests/test_file_reader.py` 的 PDF 用例已由失败转通过）。`python-docx / openpyxl / python-pptx` 仍未安装：上传 `.docx/.xlsx/.pptx` 现在会 fail-fast 返回 400 `PARSER_UNAVAILABLE`（提示「该格式需要安装解析依赖：<module>」），不会再把二进制当文本入库。若验收需覆盖这三种格式，仍须 `pip install -r backend/requirements.txt`。
2. **上传解析未支持二进制格式 — 已修复**：`app/services/rag/ingest.py::ingest_one` 对 `.pdf/.docx/.xlsx/.pptx` 改走既有 `app/services/agent/file_reader.py::extract_file_text`；提取不到正文时抛 `EmptyDocumentError`，任务转 `failed` 并记录原因。`.md/.html` 等仍走 `parse_source_file`。
3. **素材导入路径不一致 — 已修复**：`app/api/rag.py::kb_industry_root()` 改为仓库根 `var/kb_industry`（`Path(__file__).resolve().parents[3]`），`kb_manifest_path(scope)` 与 job payload 的 `markdown_root` 随之指向仓库根 `var/kb_industry/{manifest,markdown}`，不再返回 400 `MANIFEST_NOT_FOUND`。
4. **素材清单缺 `category` 字段 — 已修复**：按 `var/kb_industry/_scripts/make_core.py` 的 `RULE_KW / METHOD_KW` 口径（title + tags）在 `app/services/rag/ingest.py` 实现 `classify_manifest_item`，导入接口按此过滤，无需回填清单。实测 601 篇分布：methodology 226 / rules 254 / other 121，其中 methodology 与 `manifest-core.json` 的 226 篇完全一致。

## 验收结论

| 项 | 结论（通过 / 不通过 / 阻塞） | 验收人 | 日期 |
| --- | --- | --- | --- |
| 1 新建库 → 上传 → 检索 → Agent | | | |
| 2 规则库导入 254 篇 | | | |
| 3 现有 192 篇与评测回归 | | | |
| 4 权限（/knowledge 拒绝 + Agent 可用） | | | |
| 5 删除非空库提示 | | | |
| 6 停用库不参与检索 | | | |
| 7 worker 未启动时排队中 | | | |


## 自动化端到端结果（2026-09-17，控制器实跑）

> 环境说明：本机 8000 端口（RuoYi 风格）与 3000 端口（HC_Gao-next-admin）当时被另一个非本项目的进程占用（/openapi.json 为 RuoYi 风格路由），
> 本项目后端/前端此前已停止；端到端验收在 **8010** 上跑（同一份代码 + 同一数据库），不影响结论。

| 项 | 结果 |
| --- | --- |
| 新建库 → 上传 .md → worker 入库 | ✅ 文档 
eady、2 块；任务 succeeded、processed 1/1、inished_at 已写 |
| 从已采集素材导入（scope=core, limit=2） | ✅ 200 queued=2；任务 succeeded、processed 2/2（两条 sha256 已存在 → 正确跳过） |
| 库内检索 POST /api/rag/search + library_id | ✅ hits=2、library_name 与章节路径正确（修复前为 0 命中，见下） |
| 默认库回归 | ✅「行业知识库」仍 192 篇；评测 
ecall@5 = 0.9091、P95 = 24.02ms 不变 |
| 删除文档 / 强制删除库 | ✅ 200；库从列表消失，默认库不受影响 |
| PDF 上传（1.2/1.3 的 PDF 部分） | ⏳ 未自动验证（环境里没有带文字层的样例 PDF）；解析分支已由单测覆盖、pypdf 6.19.0 已安装，待人工用真实 PDF 验证 |
| 前端浏览器验收（1.1、1.5 UI、1.6、4.x、5.1、6.x） | ⏳ 待人工 |

### 端到端验收中发现并已修复的两个真缺陷

1. **入库后检索看不到新文档**：NumpyVectorStore 进程内永久缓存向量，worker 在另一个进程写入的切块对 API 不可见（修复：加版本探针 count(*), max(created_at)，变化才重载；commit 2db8bb17）。
2. **按库检索命中 0 条**：检索先在**全库**取 top-etch_k 再按库过滤，小库的块几乎不可能进入全局 top-15（修复：指定 library_id 时先取该库切块 id 集合，在向量打分时按集合过滤；commit 5eceb0a7）。

> 另注：API 进程首次检索会加载本地 embedding 模型（约 20-24 秒），之后 P95 ≈ 24ms（评测口径）；这是冷启动成本，不是回归。
