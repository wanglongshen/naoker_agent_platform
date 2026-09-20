# Agent 文件发现与读取工具设计（File Module）

**Date:** 2026-08-01
**Status:** approved

## 1. 背景与目标

AI 对话流中，AI 需要能**自主发现并读取"我的文件"页面（File 模块）中的 md 文件**。当前系统已有 `read_file` 工具（按文件名模糊搜索），但存在缺口：

| 缺口 | 现状 |
|------|------|
| 文件发现 | AI 不知道文件模块里有什么文件，只能靠用户把文件名写进问题 |
| 按 file_id 读取 | 无法用文件 ID 定位文件 |
| attachment_id 路径 | 运行时崩溃（`get_owned_attachment` 不存在） |
| prompt 感知 | 未告知 AI 模糊搜索/文件夹语法/歧义处理 |

**目标：** AI 可通过两个工具完成"发现 → 读取"闭环，读取"我的文件"中**属于当前用户**的文件（owner 隔离，超级管理员可读全部）。

## 2. 工具定义

### 2.1 新增 `list_files`（文件发现）

```
输入: { keyword?: string, folder?: string, limit?: int(默认10, ≤20) }
输出: {
  "files": [
    {"file_id": "uuid", "filename": "杨振东-全栈开发.md", "folder_path": "/简历", "size_bytes": 1024, "updated_at": "..."}
  ],
  "total": 3
}
```

**行为：**
- `keyword` 有值 → `FileRepository.list_files(keyword=...)`（文件名 ILIKE）
- `folder` 有值 → `find_folder_by_name`（模糊）→ `search_by_folder_and_filename`
- 无参数 → 列出最近文件（`list_files(owner_id=...)`）
- **不返回文件内容**，只返回元数据

### 2.2 增强 `read_file`

```
输入: { file_id?: string, path?: string, attachment_id?: string }
解析顺序: file_id → 精确文件名 → 文件夹/文件名 → 模糊搜索 → attachment_id
```

**修复：**
1. 新增 `file_id` 解析分支 → `FileRepository.get_file(file_id)`（校验 owner）
2. `attachment_id` 路径修复：改用 AgentRepository 实际存在的方法 + `storage_key` 落盘读取（删除对不存在属性 `attachment.content` 的依赖）

**输出（`_format_file_result` 复用）：**
```
{ "filename": "...", "media_type": "...", "content": "<提取文本>", "truncated": bool }
```

## 3. Planner prompt 更新

action_policy 追加：

```
list_files（列出或搜索"我的文件"中的文件，输入 keyword/folder/limit，返回文件元数据与 file_id）、
read_file（读取文件内容；推荐传入 file_id；path 可为文件名、文件夹/文件名；支持模糊匹配；
若返回多个候选请用 file_id 指定）
```

## 4. 数据流（不变）

```
AI 决策 action(type=list_files|read_file)
→ ToolExecutor.execute(action, owner_user_id, is_super_admin)
→ FileRepository（owner 隔离；super_admin 可跨用户）
→ 文本提取 extract_file_text（md 直接读取；PDF/DOCX/XLSX 走提取器）
→ {filename, content} 回填 observation → 继续循环
```

## 5. 权限

- 普通用户：仅读自己（owner_user_id 匹配）的文件
- 超级管理员：可读所有用户的文件（现有 is_super_admin 旁路保持）

## 6. 错误处理

| 场景 | 返回 |
|------|------|
| 未找到 | `file_not_found` 错误文本 |
| 多个模糊候选 | 列出最多 5 个（filename + file_id），提示用 file_id |
| 超大文件 | 50k 字符截断 + `truncated: true` |

## 7. 测试策略

| 层级 | 用例 |
|------|------|
| 单元 | `ListFilesInput` 校验（keyword/folder/limit 边界） |
| 单元 | `_list_files` 无参/关键词/文件夹三分支 |
| 单元 | `_read_file` 五级解析顺序、file_id 优先、attachment_id 不崩溃 |
| 集成 | 全链路：AI 决策 list_files → read_file → 内容回填 → 答案生成 |

## 8. 影响文件

| 文件 | 改动 |
|------|------|
| `backend/app/services/agent/planner.py` | `ListFilesInput`、`ReadFileInput` 加 file_id、action 类型、prompt |
| `backend/app/services/agent/tool_executor.py` | `_list_files`、`_read_file` 修复与 file_id 支持 |
| `backend/tests/test_agent_tool_files.py` | 新增测试 |
| 前端 | 无 |
