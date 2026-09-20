# 平台站内搜索设计（fetch_platform_search）

日期：2026-08-06
状态：已确认

## 背景

蓝图（`脑壳儿_Agent运行蓝图_v1.1.md`）对小红书/抖音平台研究有硬规则：

> 小红书/抖音硬规则：只要 brief、方案或需求涉及小红书或抖音平台研究，必须使用平台搜索入口；不能跳过平台内搜索，不能只用 Web 搜索或泛行业报告替代。每个涉及的平台单平台可用样本目标不少于 150 条（去重、与 brief 相关、至少提供标题/账号/链接/互动信息或正文线索）。若因登录态、验证码、平台风控、接口限制等导致可用样本少于 150 条，必须在对话框说明原因、已尝试的关键词/后端/重试路径、实际可用样本数和替代方案，并等待人工确认后再继续。

当前系统的差距：

1. `$agent-reach` 在 workflow_rules.py 被映射为 `web_search`（Tavily 通用搜索），不含小红书/抖音站内数据；
2. `fetch_web_content`（Playwright 单页渲染）只能抓已知 URL 的详情页，无法"搜索关键词 → 获得笔记/视频列表"；
3. 无样本批量采集、无 150 条口径计数、无"样本不足等待人工确认"流程。

已有基础设施（全部复用）：

- `web_renderer` 服务（独立 Playwright 进程，`POST /render` 端点）；
- `login_session` / `web_cookie_store`（douyin/xiaohongshu 登录 cookie 的存取与注入）；
- `assess_login_expired`（平台登录态过期检测）；
- `_extract_douyin_json`（抖音 RENDER_DATA / `__INITIAL_STATE__` JSON 提取）；
- awaiting_question 挂起机制（loop.py：`_QuestionHangSignal` → `mark_run_awaiting_question` → attempt paused → 用户回答后恢复）。

## 目标

- 提供平台站内搜索工具 `fetch_platform_search`（小红书/抖音），返回结构化样本列表（标题/账号/链接/互动数）；
- 在规划器提示与路由规则层面落实"平台研究优先平台内搜索"；
- 实现 150 条样本硬闸门：涉及平台研究的任务在样本不足时挂起等待人工确认（复用 awaiting_question）；
- 不引入第三方工具链（Agent-Reach/OpenCLI），以现有 Playwright 渲染能力自建站内搜索。

## 架构

```
模型(planner 选 fetch_platform_search)
  → tool_executor._fetch_platform_search(platform, keyword, max_results)
    → web_cookie_store 注入已存 cookie
    → httpx → web_renderer 服务 POST /search
      → Playwright 渲染搜索页 + 滚动加载至 max_results（上限 8 轮）
      → 平台解析器提取样本 [{title, author, url, likes}]
      → 登录墙/验证码检测 → login_required
    → 返回 {samples, sample_count, login_required}
  → 观察注入：紧凑样本列表 + "该平台累计 X/150 条"
  → 系统按平台累计（per-run 状态）→ research 结束时 <150 → 挂起等确认
```

## 组件设计

### 1. web_renderer `/search` 端点

- 请求：`{"platform": "xiaohongshu" | "douyin", "keyword": str, "max_results": int(1-50), "cookies": [...] | null}`
- 渲染流程：
  - 小红书：`https://www.xiaohongshu.com/search_result?keyword={keyword}`，默认综合 tab；
  - 抖音：`https://www.douyin.com/search/{keyword}`，默认综合 tab；
  - 复用现有反检测（UA 随机、stealth JS）与 cookie 注入；
  - 滚动加载：重复滚动直到收集条数 ≥ max_results 或连续 3 轮无新样本或达 8 轮上限；
- 平台解析：
  - 抖音：优先 `_extract_douyin_json`（RENDER_DATA / `__INITIAL_STATE__`）中的搜索列表节点（实现时实测节点路径），兜底 `_WebContentParser` 文本 + 链接提取；
  - 小红书：feed card 结构解析（实现时实测 DOM/JSON），兜底文本 + 链接提取；
  - 样本字段：`title`（标题/描述）、`author`（账号名，拿不到则空串）、`url`（详情链接，拿不到则空串）、`likes`（互动数，拿不到则 null）；
- 登录墙/验证码检测：`assess_login_expired` + 搜索页特征（小红书"登录后推荐更懂你的笔记"、抖音验证码表单）→ 返回 `login_required: true`（不视为错误）；
- 响应：`{"samples": [...], "sample_count": int, "login_required": bool, "platform": str}`；
- 超时：/search 独立超时 60s（滚动加载 8 轮需要，可配置 `web_renderer_search_timeout_seconds`），重试语义与 `/render` 一致；
- 节流：同一平台连续两次平台搜索之间至少间隔 3 秒（降低平台风控/验证码触发概率）。

### 2. planner `FetchPlatformSearchInput` 与工具

- `FetchPlatformSearchInput`：`platform: Literal["xiaohongshu", "douyin"]`、`keyword: str ≤ 50`、`max_results: int = Field(30, ge=1, le=50)`；
- action 类型 `"fetch_platform_search"` 加入允许列表（web_enabled 分支）；
- 工具描述（planner 提示词）："平台站内搜索（小红书/抖音），返回笔记/视频样本列表（标题/账号/链接/互动数）。涉及小红书/抖音平台研究时必须优先使用本工具，不能只用普通网页搜索替代（蓝图硬规则）。可多次搜索不同关键词累积样本。"
- `tool_executor._fetch_platform_search`：
  - cookie 注入：`web_cookie_store.get_user_cookie_string(owner_user_id, domain)`（与 `_fetch_web_content` 同模式）；
  - 调用 `POST {web_renderer_url}/search`；`web_renderer_unavailable` / `web_render_status` 可重试错误语义与 `_fetch_web_content` 一致；
  - 返回：`{"platform": ..., "keyword": ..., "sample_count": n, "samples": [最多 20 条紧凑列表：标题|账号|点赞|链接], "total_available": n, "login_required": bool, "note": "该平台累计 X/150 条"}`；
  - 样本数组在观察中截断（最多 20 条 + 计数），避免撑爆上下文；
- 路由规则：workflow_rules.py 中 `$agent-reach` / `agent-reach` 的映射从 `web_search` 改为 `fetch_platform_search`。

### 3. 150 条样本硬闸门

- per-run 工作流状态新增：
  - `platform_samples: dict[str, int]`（键：`xiaohongshu` / `douyin`，最终计数）；
  - `platform_sample_urls: dict[str, set[str]]`（按 URL 去重，去重后再计数——同关键词重复搜索不重复累计）；
- 累计时机：主循环工具执行成功后（与观察记录同处）按返回样本的 URL 去重累加；
- research 阶段推进检查（位置明确：`_advance_workflow_stage` 中 research → content 的转移处）：
  - 触发条件（唯一）：本 attempt 曾调用过 `fetch_platform_search` 的平台（无论成功与否）；goal 含平台关键词但未调用过平台搜索的任务**不触发**（"不能跳过平台内搜索"由 planner 提示词层约束，闸门只管"用了但不足"）；
  - 任一触发平台累计 < 150 → 抛 `_QuestionHangSignal`，问题文案：
    - 已使用关键词列表（本 run 内 fetch_platform_search 的 keyword 去重；未调用过则显示"尚未使用平台搜索"及原因，如 renderer 不可用/登录墙/无样本）；
    - 平台、实际累计样本数、目标 150；
    - 建议：换关键词继续搜索，或用户确认接受当前样本数继续；
  - 复用既有挂起链路（`mark_run_awaiting_question` + `run_awaiting_question` 事件 + attempt paused + 用户回答后恢复）；
- 用户确认继续后：将该平台标记"已确认豁免"（per-run 状态），不再触发挂起（避免恢复后再次挂起）；豁免后模型继续搜索产生的新样本仍正常累加。

### 4. 错误处理与降级

- web_renderer 服务不可用 → `RetryableToolError("web_renderer_unavailable")`（走既有重试）；
- 登录墙/验证码 → `login_required: true`（非错误观察）：模型按现有流程提示用户"请打开平台登录中心扫码/验证码登录"；
- 解析失败（平台改版）→ 文本兜底（title/部分链接）+ 结构化日志 `platform_search_parse_fallback`；
- 空结果（关键词无供给/风控）→ `sample_count: 0` + 观察注明原因；
- 平台禁用网络时（web_enabled=False）→ 与 web_search 一致不暴露该工具。

## 测试策略

1. web_renderer 解析器单测（mock HTML）：
   - 抖音 RENDER_DATA 搜索列表 → 样本提取；
   - 小红书 feed card → 样本提取；
   - 登录墙特征（小红书/抖音）→ `login_required: true`；
   - 解析失败 → 文本兜底；
2. 工具层测试（mock /search 服务）：样本返回、`login_required`、`web_renderer_unavailable` 可重试、cookie 注入参数、观察格式（20 条截断 + 累计计数）；
3. planner 测试：`FetchPlatformSearchInput` 校验（platform 枚举、keyword 长度、max_results 1-50）；
4. 闸门测试三态：
   - 平台研究任务 research 结束样本 <150 → 挂起等待确认（`run_awaiting_question` 事件 + attempt paused）；
   - 样本 ≥150 → 放行不挂起；
   - 未涉及平台研究 → 完全不触发；
   - 用户确认后不再重复挂起；
5. 端到端实测（实现后）：真实渲染小红书/抖音搜索页，验证样本可获取性；若平台改版/风控导致拿不到，记录实际情况并作为闸门"说明原因"路径的输入。

## 验收标准

- [ ] `fetch_platform_search` 工具可被模型调用，返回结构化样本（标题/账号/链接/互动数）；
- [ ] 小红书与抖音搜索页至少一种能拿到真实样本（端到端实测确认）；若均拿不到，闸门"说明原因"路径可用；
- [ ] 涉及平台研究的任务：样本 <150 时挂起等待人工确认，≥150 直接放行；
- [ ] `$agent-reach` 路由映射指向平台搜索；
- [ ] 全量回归通过，前端无改动。

## 明确不做（YAGNI）

- 不接入 Agent-Reach/OpenCLI 第三方工具链（当前环境无该工具，自建 Playwright 已覆盖）；
- 不做平台详情页批量抓取与评论抓取（样本口径=搜索列表项；详情是模型后续用 fetch_web_content 的补充动作）；
- 不做样本持久化/落库（观察上下文即足够，闸门计数在 per-run 状态）；
- 不做多 tab（综合/视频/用户）切换（默认综合 tab，后续按需扩展）。
