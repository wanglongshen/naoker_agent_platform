# 平台笔记采集入库设计（小红书/抖音 9 字段符合）

- 日期：2026-08-06
- 范围：采集侧符合（3.4 小红书数据收集）——不含项目隔离（3.5，独立 P0 另立任务）
- 前置：`fetch_platform_search` 工具、`/search` 端点、150 条闸门已上线（2026-08-06 platform-search 计划）

## 1. 背景与目标

需求文档《会议记录功能补充·需求说明 v1》3.4「小红书数据收集」要求：数量至少 40 条（保底）期望 150 条；字段含标题、正文、图片、点赞/收藏/评论数、作者、发布时间、话题标签、笔记链接；链接作为去重键；按清洗后有效数据计保底；每条记录来源（关键词、采集时间）可审计。

当前实现（platform-search 计划）差距：样本只流经观察/闸门计数不落库、字段仅 title/author/url/likes 四项、150 条硬闸门、无清洗、无溯源。本设计将这些差距全部补齐。

## 2. 数据流

```
模型调用 fetch_platform_search(platform, keyword, max_results)
  → POST /search（web_renderer 渲染搜索页，滚动加载取卡片）
  → 卡片样本（title/author/url/likes/collect/comment/cover/topic_tags）
  → 清洗（丢弃空标题/无链接）
  → 受限并发抓取详情页（POST /detail，每条 8s 超时，补 content/published_at/完整互动数）
  → upsert 入库 platform_notes（(owner_user_id, url) 唯一键）
  → 有效计数 = 入库成功数
  → 观察返回：{samples(≤20 条), sample_count, stored_count, detail_failed, login_required, note("累计 X/40(保底)/150(期望)")}
  → _accumulate_platform_samples 按 URL 去重累计 → _check_platform_sample_gate（<40 挂起）
```

## 3. 数据模型：platform_notes 表

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid PK | |
| owner_user_id | uuid FK users | 归属用户（隔离维度） |
| project_id | uuid nullable | **预留**，本轮恒 NULL（项目隔离另立任务） |
| platform | varchar(32) | xiaohongshu / douyin |
| keyword | varchar(200) | 采集关键词（溯源） |
| url | text | 笔记链接（去重键） |
| title | varchar(500) | 标题（清洗要求非空） |
| content | text | 正文全文（详情页，缺失为 NULL） |
| image_urls | JSON | 图片 URL 数组（可为 []） |
| like_count | int | 点赞数 |
| collect_count | int | 收藏数 |
| comment_count | int | 评论数 |
| author | varchar(200) | 作者昵称 |
| published_at | timestamptz nullable | 发布时间（详情页，缺失为 NULL） |
| topic_tags | JSON | 话题标签数组（可为 []） |
| collected_at | timestamptz | 采集时间（默认 now） |
| updated_at | timestamptz | 更新时间 |

约束：
- 唯一约束 `uq_platform_notes_owner_url (owner_user_id, url)`——同用户同链接唯一，upsert 用
- 索引：`(owner_user_id, platform)`、`(owner_user_id, keyword)`（查询接口与隔离用）

## 4. 解析器扩展（web_renderer.py）

### 4.1 卡片字段扩展

`_extract_samples_from_json` 现有输出 title/author/url/likes，扩展为：`{title, author, url, likes, collect_count, comment_count, cover_image, topic_tags}`。

- 小红书 noteList JSON：`title`、`user.nickname`、`url`（noteId 拼）、`interactInfo.likedCount/collectedCount/commentCount`、`imageList[].urlDefault`、`tagList[].name`
- 抖音 aweme_list JSON：`desc`、`author.nickname`、`share_url`、`statistics.digg_count/collect_count/comment_count`、`video.cover.url_list[0]`、`text_extra[].hashtag_name`
- 解析失败字段缺省为 None/空数组，不影响样本有效性（有效性只看 title+url）

### 4.2 详情页抓取

新增 `fetch_note_detail(url: str, platform: str, cookies, timeout_seconds) -> dict`：
- 渲染笔记详情页（复用 render_page：stealth JS、UA/视口随机、cookie 注入、网络空闲回退）
- 提取：`{content, published_at, like_count, collect_count, comment_count, topic_tags, title, author}`（以详情页为准覆盖卡片值）
- 抖音详情：复用 `_extract_douyin_json` 从 RENDER_DATA 提取 desc/statistics/create_time/视频信息
- 小红书详情：优先页内 JSON（`window.__INITIAL_STATE__` 或 note 接口数据），兜底 `_WebContentParser` 文本+链接
- 登录墙检测（同 /search）：`login_required: True` 时返回标记，不视为错误
- 超时/解析失败：返回 `{"error": ...}` 字段（与 /render//search 风格一致），不抛异常

## 5. /detail 端点（workers/web_renderer.py）

```
POST /detail
Request:  {platform: "xiaohongshu"|"douyin", url: str(≤2000), cookies?: [...]}
Response: {platform, url, title, content, published_at, like_count, collect_count,
           comment_count, topic_tags, author, image_urls, login_required, error}
```

- 独立超时：`web_renderer_search_timeout_seconds`（复用 60s 配置）
- 错误语义与 /search 一致（error 字段而非异常）
- url 校验：仅允许 http(s) 且 host 匹配平台域名（www.xiaohongshu.com / www.douyin.com），防 SSRF

## 6. 工具层：抓取策略与入库（tool_executor.py）

`_fetch_platform_search` 流程扩展（在现有卡片返回后）：
1. 卡片样本清洗：丢弃 title 为空或 url 为空的项
2. **受限并发抓详情**：`asyncio.gather` + `asyncio.Semaphore(3)`，每条 `httpx` 调 `POST /detail`，`timeout=8s`（单条详情超时独立于 /search 总超时）——同平台详情请求间隔 ≥1s（复用 `_last_platform_search_at` 节流逻辑，按 url 哈希分桶或直接串行化详情调用到同平台间隔）
   - 实现要点：详情抓取失败（网络/超时/解析）→ 该条字段留空，计入 `detail_failed`
   - `login_required` 详情 → 该条留空，计数并入 `detail_failed`，且 `login_required: True` 上报（观察提示用户登录）
3. **入库**：`platform_note_repository.upsert(owner_user_id, sample, platform, keyword)`——INSERT ... ON CONFLICT (owner_user_id, url) DO UPDATE 更新全部可更新字段
   - 入库异常 try/except：记 `logger.warning("platform_note_persist_failed")`，**不阻塞采集返回**
   - 入库成功数 = `stored_count`
4. 返回扩展：`{samples(≤20), sample_count(清洗后卡片数), stored_count(入库数), detail_failed, login_required, note}`

### 6.1 仓库层

新增 `backend/app/repositories/platform_note_repository.py`：
- `async def upsert(session, owner_user_id, platform, keyword, sample: dict) -> bool`（成功 True）
- `async def list_notes(session, owner_user_id, keyword=None, platform=None, limit=50, offset=0) -> (rows, total)`

## 7. 闸门改造（loop.py）

1. `_check_platform_sample_gate`：阈值常量 `PLATFORM_SAMPLE_MIN = 40`——清洗后有效样本（`platform_samples[platform]`，即累计 stored_count 或 sample_count 中较高的口径，按 URL 去重后的入库数）**<40 → 挂起**；**≥40 → 放行**（不再 150 硬挂起）
   - 挂起文案更新：「平台样本不足：{label} 平台累计 {count} 条，未达到保底 40 条目标…」（保留"换关键词继续搜索"与"确认接受当前样本数"两个出口）
2. `_accumulate_platform_samples`：累计口径改用 `stored_count`（入库有效数）；观察 note 格式：「该平台累计 X/40（保底）/150（期望）」；40-149 时附加提示「已达标 40，距 150 期望还差 Y 条，继续搜索可补充」
3. 豁免逻辑不变（未调用平台搜索的平台不检查）

## 8. 查询接口

```
GET /api/agent/platform-notes?keyword=&platform=&limit=50&offset=0
Response: {items: [{id, platform, keyword, url, title, content(≤500 字截断), image_urls,
                     like_count, collect_count, comment_count, author, published_at,
                     topic_tags, collected_at}], total}
```

- 鉴权：`get_current_user`（登录即可）；**服务端强制 owner 隔离**（WHERE owner_user_id = 当前用户）
- 无 CSRF（GET）；挂在 agent router（backend/app/api/agent.py）
- content 截断 500 字（返回体控制，不落库截断）

## 9. 测试

1. **解析器单测**（test_web_renderer.py）：详情页提取（mock 小红书 note 页 JSON、抖音详情 JSON、文本兜底）；卡片字段扩展（collect/comment/cover/topic_tags 从 mock JSON 提取）
2. **/detail 端点**（test_web_renderer.py）：成功返回、登录墙标记、错误字段、url 域名校验（非平台域名拒绝）
3. **入库**（test_platform_note_repository.py 或并入 test_agent_tool_files.py）：upsert 同链接更新不重复（两次调用一条记录）、字段刷新（详情补齐后覆盖）、清洗（空标题/无链接不入库）、入库异常不阻塞（mock 仓库抛错 → 采集仍返回）
4. **闸门**（test_agent_loop.py TestPlatformSampleGate）：<40 挂起、40+ 放行、40-149 提示文案含"150"、豁免不触发、挂起 questions dict 契约保持
5. **查询接口**（test_agent_api.py）：owner 隔离（A 用户查不到 B 用户笔记）、keyword/platform 筛选、content 截断、未登录 401

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| 详情页风控（验证码/限流） | 并发 3 + 同平台 ≥1s 间隔 + 单条 8s 超时；失败留空不阻塞；login_required 上报观察 |
| 150 条详情耗时 1-2 分钟 | 受限并发可接受（真实任务 5-10 分钟量级） |
| 抖音/小红书详情页结构差异 | 抖音复用 `_extract_douyin_json`（RENDER_DATA）；小红书 JSON 优先 + 文本兜底 |
| upsert 并发写（多 run 同用户同链接） | ON CONFLICT 原子语义保证不重复不报错 |
| 入库失败影响采集 | try/except + 日志，采集结果照常返回 |

## 11. 明确不做（本轮）

- 项目隔离（3.5）：`project_id` 字段预留恒 NULL；成员鉴权/项目表另立任务
- 前端页面（采集数据页/审计页）：只提供查询接口
- 详情页深度链路之外的扩展（评论抓取、搜索→详情→评论全链）：后续阶段
- 抖音侧需求未明确（需求文档只提小红书）：实现对称覆盖抖音（平台搜索本就双平台），字段口径一致
