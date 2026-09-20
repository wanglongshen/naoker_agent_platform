# LangGraph 差分校准报告

## 归一化规则（event_normalize.NORMALIZATION_RULES）

- 事件主键 id → <id>
- 键名 in {created_at, updated_at, started_at, finished_at, completed_at} 的字符串值 → <ts>
- 任意字符串值中的 UUID 子串 → <uuid>（保留前后缀，如 error-<uuid>）
- 任意字符串值中的 ISO 时间戳子串 → <ts>

### 驱动层额外归一化（run_scenario 采集时应用）

- `seq` → 该 run 内的 1-based 序号（DB sequence 为全局序列，非 run 内序号）
- payload 中 `step_duration_seconds`（数值）→ `<duration>`（墙钟耗时，两次运行必不相同）

### 回放期确定性 web 工具桩（仅 --diff 生效）

真实网络/渲染器结果不可复现，回放时下列工具被替换为固定返回，避免与轨道无关的假差异：

- `web_search` → `{"results": [{"title": "差分回放固定搜索结果", "url": "https://example.com/langgraph-replay/web-search", "content": "回放模式固定返回：真实 web_search 结果依赖网络时序，不可复现。"}]}`
- `http_request` → `{"status_code": 200, "url": "https://example.com/langgraph-replay/http-request", "title": "差分回放固定页面", "text": "回放模式固定返回：真实 http_request 响应依赖网络时序，不可复现。", "links": []}`
- `fetch_web_content` → `{"status_code": 200, "url": "https://example.com/langgraph-replay/fetch-web-content", "title": "差分回放固定渲染页", "text": "回放模式固定返回：fetch_web_content 依赖本机 web_renderer，不可复现。", "platform": "generic", "source": "playwright", "login_expired": false}`
- `fetch_platform_search` → `{"platform": "<input.platform>", "keyword": "<input.keyword>", "sample_count": 1, "samples": [{"title": "差分回放固定平台样本", "url": "https://example.com/langgraph-replay/platform-sample"}], "total_available": 1, "stored_count": 0, "detail_failed": 0, "platform_total": 0, "login_required": false, "note": "回放模式固定返回：平台搜索依赖本机 web_renderer 与登录态，不可复现。"}`

DB/文件类工具（read_file/write_file/edit_file/list_files）保持真实执行；`--record` 不替换。

### 场景级确定性故障注入

- 场景配置 `fault: {"tool": ..., "mode": "retryable"}` 时，该工具每次执行都抛 `RetryableToolError`；录制与回放均生效（脚本层 monkeypatch，不改 app/**）。
## 场景 2: 方案类全流程

- goal: `基于已有资料写一份新品上市的广告营销方案`
- 旧轨事件数: 526
- 图轨事件数: 526
- 结果: FAIL（9 处差异）

```
[diff @2] old={'seq': 3, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_started', 'payload': {'step_index': 0, 'stream_id': 'plan-510a72d9999e'}, 'created_at': '<ts>'} new={'seq': 3, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_started', 'payload': {'step_index': 0, 'stream_id': 'plan-e67ab889fe1a'}, 'created_at': '<ts>'}
[diff @39] old={'seq': 40, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_completed', 'payload': {'step_index': 0, 'stream_id': 'plan-510a72d9999e', 'text': '用户要求基于已有资料写新品上市广告营销方案，但尚未明确是哪些资料；先列出我的文件确认可用的 brief 与附件，再进入复述与调研。', 'length': 65}, 'created_at': '<ts>'} new={'seq': 40, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_completed', 'payload': {'step_index': 0, 'stream_id': 'plan-e67ab889fe1a', 'text': '用户要求基于已有资料写新品上市广告营销方案，但尚未明确是哪些资料；先列出我的文件确认可用的 brief 与附件，再进入复述与调研。', 'length': 65}, 'created_at': '<ts>'}
[diff @75] old={'seq': 76, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_started', 'payload': {'step_index': 1, 'stream_id': 'plan-b226ae9b7520'}, 'created_at': '<ts>'} new={'seq': 76, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_started', 'payload': {'step_index': 1, 'stream_id': 'plan-7eabb392d56f'}, 'created_at': '<ts>'}
[diff @356] old={'seq': 357, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_completed', 'payload': {'step_index': 1, 'stream_id': 'plan-b226ae9b7520', 'text': '用户要求基于已有资料写新品上市广告营销方案，但工作区文件为空，且未提供品牌、品类、平台、预算与周期等关键信息，无法启动有效调研与撰写，需先向用户确认输入', 'length': 76}, 'created_at': '<ts>'} new={'seq': 357, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_completed', 'payload': {'step_index': 1, 'stream_id': 'plan-7eabb392d56f', 'text': '用户要求基于已有资料写新品上市广告营销方案，但工作区文件为空，且未提供品牌、品类、平台、预算与周期等关键信息，无法启动有效调研与撰写，需先向用户确认输入', 'length': 76}, 'created_at': '<ts>'}
[diff @358] old={'seq': 359, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_started', 'payload': {'step_index': 2, 'stream_id': 'plan-b983aa5d1966'}, 'created_at': '<ts>'} new={'seq': 359, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_started', 'payload': {'step_index': 2, 'stream_id': 'plan-7852f4581920'}, 'created_at': '<ts>'}
[diff @396] old={'seq': 397, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_completed', 'payload': {'step_index': 2, 'stream_id': 'plan-b983aa5d1966', 'text': '"我的文件"为空，无已有资料可读，需先做外部研究。首步先检索中国市场新品上市营销的最新趋势与打法，作为方案前策依据。', 'length': 58}, 'created_at': '<ts>'} new={'seq': 397, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_completed', 'payload': {'step_index': 2, 'stream_id': 'plan-7852f4581920', 'text': '"我的文件"为空，无已有资料可读，需先做外部研究。首步先检索中国市场新品上市营销的最新趋势与打法，作为方案前策依据。', 'length': 58}, 'created_at': '<ts>'}
[diff @519] old={'seq': 520, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_started', 'payload': {'step_index': 3, 'stream_id': 'plan-0437ceb2d6f4'}, 'created_at': '<ts>'} new={'seq': 520, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_started', 'payload': {'step_index': 3, 'stream_id': 'plan-bbe659363c71'}, 'created_at': '<ts>'}
[diff @520] old={'seq': 521, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_completed', 'payload': {'step_index': 3, 'stream_id': 'plan-0437ceb2d6f4', 'text': '{"thought_summary":"用户需要一份新品上市广告营销方案，但“我的文件”为空，无已有资料。当前处于 research 阶段，需先完成外部研究。先检索新品上市营销方案的方法论与框架，作为方案骨架依据。","action":{"type":"web_search","input":{"query":"新品上市 广告营销方案 框架 方法论 4P 整合营销","max_results":5', 'length': 200}, 'created_at': '<ts>'} new={'seq': 521, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_completed', 'payload': {'step_index': 3, 'stream_id': 'plan-bbe659363c71', 'text': '{"thought_summary":"用户需要一份新品上市广告营销方案，但“我的文件”为空，无已有资料。当前处于 research 阶段，需先完成外部研究。先检索新品上市营销方案的方法论与框架，作为方案骨架依据。","action":{"type":"web_search","input":{"query":"新品上市 广告营销方案 框架 方法论 4P 整合营销","max_results":5', 'length': 200}, 'created_at': '<ts>'}
[diff @521] old={'seq': 522, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_started', 'payload': {'step_index': 3, 'stream_id': 'plan-479782011f44'}, 'created_at': '<ts>'} new={'seq': 522, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_started', 'payload': {'step_index': 3, 'stream_id': 'plan-21053146d920'}, 'created_at': '<ts>'}
```
## 场景 2: 方案类全流程

- goal: `基于已有资料写一份新品上市的广告营销方案`
- 旧轨事件数: 846
- 图轨事件数: 7
- 结果: FAIL（842 处差异）

```
[diff @4] old={'seq': 5, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 0, 'delta': '\n'}, 'created_at': '<ts>'} new={'seq': 5, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 0, 'delta': 'no recorded call at cursor 17 for stream_text'}, 'created_at': '<ts>'}
[diff @5] old={'seq': 6, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 1, 'delta': '我先'}, 'created_at': '<ts>'} new={'seq': 6, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_completed', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'text': 'no recorded call at cursor 17 for stream_text', 'length': 45, 'fallback': True}, 'created_at': '<ts>'}
[diff @6] old={'seq': 7, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 3, 'delta': '查看'}, 'created_at': '<ts>'} new={'seq': 7, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'run_failed', 'payload': {'error': 'no recorded call at cursor 17 for stream_text'}, 'created_at': '<ts>'}
[-only-old @7] {'seq': 8, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 5, 'delta': '您'}, 'created_at': '<ts>'}
[-only-old @8] {'seq': 9, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 6, 'delta': '"'}, 'created_at': '<ts>'}
[-only-old @9] {'seq': 10, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 7, 'delta': '我的'}, 'created_at': '<ts>'}
[-only-old @10] {'seq': 11, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 9, 'delta': '文件'}, 'created_at': '<ts>'}
[-only-old @11] {'seq': 12, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 11, 'delta': '"'}, 'created_at': '<ts>'}
[-only-old @12] {'seq': 13, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 12, 'delta': '中'}, 'created_at': '<ts>'}
[-only-old @13] {'seq': 14, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 13, 'delta': '已有的'}, 'created_at': '<ts>'}
[-only-old @14] {'seq': 15, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 16, 'delta': '资料'}, 'created_at': '<ts>'}
[-only-old @15] {'seq': 16, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 18, 'delta': '（'}, 'created_at': '<ts>'}
[-only-old @16] {'seq': 17, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 19, 'delta': '如'}, 'created_at': '<ts>'}
[-only-old @17] {'seq': 18, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 20, 'delta': ' brief'}, 'created_at': '<ts>'}
[-only-old @18] {'seq': 19, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 26, 'delta': '、'}, 'created_at': '<ts>'}
[-only-old @19] {'seq': 20, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 27, 'delta': '产品'}, 'created_at': '<ts>'}
[-only-old @20] {'seq': 21, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 29, 'delta': '信息'}, 'created_at': '<ts>'}
[-only-old @21] {'seq': 22, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 31, 'delta': '、'}, 'created_at': '<ts>'}
[-only-old @22] {'seq': 23, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 32, 'delta': '案例'}, 'created_at': '<ts>'}
[-only-old @23] {'seq': 24, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 34, 'delta': '等'}, 'created_at': '<ts>'}
[-only-old @24] {'seq': 25, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 35, 'delta': '），'}, 'created_at': '<ts>'}
[-only-old @25] {'seq': 26, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 37, 'delta': '确认'}, 'created_at': '<ts>'}
[-only-old @26] {'seq': 27, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 39, 'delta': '这次'}, 'created_at': '<ts>'}
[-only-old @27] {'seq': 28, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 41, 'delta': '新品'}, 'created_at': '<ts>'}
[-only-old @28] {'seq': 29, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 43, 'delta': '上市的'}, 'created_at': '<ts>'}
[-only-old @29] {'seq': 30, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 46, 'delta': '推广'}, 'created_at': '<ts>'}
[-only-old @30] {'seq': 31, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 48, 'delta': '主体'}, 'created_at': '<ts>'}
[-only-old @31] {'seq': 32, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 50, 'delta': '与'}, 'created_at': '<ts>'}
[-only-old @32] {'seq': 33, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 51, 'delta': '已有'}, 'created_at': '<ts>'}
[-only-old @33] {'seq': 34, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 53, 'delta': '素材'}, 'created_at': '<ts>'}
[-only-old @34] {'seq': 35, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 55, 'delta': '，'}, 'created_at': '<ts>'}
[-only-old @35] {'seq': 36, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 56, 'delta': '再'}, 'created_at': '<ts>'}
[-only-old @36] {'seq': 37, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 57, 'delta': '据此'}, 'created_at': '<ts>'}
[-only-old @37] {'seq': 38, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 59, 'delta': '展开'}, 'created_at': '<ts>'}
[-only-old @38] {'seq': 39, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 61, 'delta': '调研'}, 'created_at': '<ts>'}
[-only-old @39] {'seq': 40, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 63, 'delta': '和'}, 'created_at': '<ts>'}
[-only-old @40] {'seq': 41, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 64, 'delta': '方案'}, 'created_at': '<ts>'}
[-only-old @41] {'seq': 42, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 66, 'delta': '撰写'}, 'created_at': '<ts>'}
[-only-old @42] {'seq': 43, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 68, 'delta': '。'}, 'created_at': '<ts>'}
[-only-old @43] {'seq': 44, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_completed', 'payload': {'step_index': 0, 'stream_id': 'stream-1', 'text': "任务要求'基于已有资料'写新品上市营销方案，但尚未确认'已有资料'具体是什么。先列出我的文件，定位可用的 brief、产品资料或案例，再决定后续调研与撰写。", 'length': 78}, 'created_at': '<ts>'}
[-only-old @44] {'seq': 45, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_completed', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'text': '我先查看您"我的文件"中已有的资料（如 brief、产品信息、案例等），确认这次新品上市的推广主体与已有素材，再据此展开调研和方案撰写。', 'length': 68}, 'created_at': '<ts>'}
[-only-old @45] {'seq': 46, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_created', 'payload': {'step_index': 0, 'thought_summary': "任务要求'基于已有资料'写新品上市营销方案，但尚未确认'已有资料'具体是什么。先列出我的文件，定位可用的 brief、产品资料或案例，再决定后续调研与撰写。", 'action': {'type': 'list_files', 'input': {}}}, 'created_at': '<ts>'}
[-only-old @46] {'seq': 47, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_paused', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'text': '我先查看您"我的文件"中已有的资料（如 brief、产品信息、案例等），确认这次新品上市的推广主体与已有素材，再据此展开调研和方案撰写。', 'length': 68, 'fallback': False}, 'created_at': '<ts>'}
[-only-old @47] {'seq': 48, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'tool_started', 'payload': {'step_index': 0, 'action_type': 'list_files', 'tool_call': {}}, 'created_at': '<ts>'}
[-only-old @48] {'seq': 49, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'tool_completed', 'payload': {'step_index': 0, 'action_type': 'list_files', 'tool_call': {}, 'observation': {'files': [], 'folders': [], 'total': 0}}, 'created_at': '<ts>'}
[-only-old @49] {'seq': 50, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_started', 'payload': {'step_index': 0, 'stream_id': 'stream-3'}, 'created_at': '<ts>'}
[-only-old @50] {'seq': 51, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-3', 'offset': 0, 'delta': '当前'}, 'created_at': '<ts>'}
[-only-old @51] {'seq': 52, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-3', 'offset': 2, 'delta': '工作'}, 'created_at': '<ts>'}
[-only-old @52] {'seq': 53, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-3', 'offset': 4, 'delta': '目录'}, 'created_at': '<ts>'}
[-only-old @53] {'seq': 54, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-3', 'offset': 6, 'delta': '中没有'}, 'created_at': '<ts>'}
... 其余 792 条差异已省略
```
## 场景 2: 方案类全流程

- goal: `基于已有资料写一份新品上市的广告营销方案`
- 旧轨事件数: 846
- 图轨事件数: 7
- 结果: FAIL（842 处差异）

```
[diff @4] old={'seq': 5, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 0, 'delta': '\n'}, 'created_at': '<ts>'} new={'seq': 5, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 0, 'delta': 'no recorded call at cursor 17 for stream_text'}, 'created_at': '<ts>'}
[diff @5] old={'seq': 6, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 1, 'delta': '我先'}, 'created_at': '<ts>'} new={'seq': 6, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_completed', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'text': 'no recorded call at cursor 17 for stream_text', 'length': 45, 'fallback': True}, 'created_at': '<ts>'}
[diff @6] old={'seq': 7, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 3, 'delta': '查看'}, 'created_at': '<ts>'} new={'seq': 7, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'run_failed', 'payload': {'error': 'no recorded call at cursor 17 for stream_text'}, 'created_at': '<ts>'}
[-only-old @7] {'seq': 8, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 5, 'delta': '您'}, 'created_at': '<ts>'}
[-only-old @8] {'seq': 9, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 6, 'delta': '"'}, 'created_at': '<ts>'}
[-only-old @9] {'seq': 10, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 7, 'delta': '我的'}, 'created_at': '<ts>'}
[-only-old @10] {'seq': 11, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 9, 'delta': '文件'}, 'created_at': '<ts>'}
[-only-old @11] {'seq': 12, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 11, 'delta': '"'}, 'created_at': '<ts>'}
[-only-old @12] {'seq': 13, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 12, 'delta': '中'}, 'created_at': '<ts>'}
[-only-old @13] {'seq': 14, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 13, 'delta': '已有的'}, 'created_at': '<ts>'}
[-only-old @14] {'seq': 15, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 16, 'delta': '资料'}, 'created_at': '<ts>'}
[-only-old @15] {'seq': 16, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 18, 'delta': '（'}, 'created_at': '<ts>'}
[-only-old @16] {'seq': 17, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 19, 'delta': '如'}, 'created_at': '<ts>'}
[-only-old @17] {'seq': 18, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 20, 'delta': ' brief'}, 'created_at': '<ts>'}
[-only-old @18] {'seq': 19, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 26, 'delta': '、'}, 'created_at': '<ts>'}
[-only-old @19] {'seq': 20, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 27, 'delta': '产品'}, 'created_at': '<ts>'}
[-only-old @20] {'seq': 21, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 29, 'delta': '信息'}, 'created_at': '<ts>'}
[-only-old @21] {'seq': 22, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 31, 'delta': '、'}, 'created_at': '<ts>'}
[-only-old @22] {'seq': 23, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 32, 'delta': '案例'}, 'created_at': '<ts>'}
[-only-old @23] {'seq': 24, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 34, 'delta': '等'}, 'created_at': '<ts>'}
[-only-old @24] {'seq': 25, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 35, 'delta': '），'}, 'created_at': '<ts>'}
[-only-old @25] {'seq': 26, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 37, 'delta': '确认'}, 'created_at': '<ts>'}
[-only-old @26] {'seq': 27, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 39, 'delta': '这次'}, 'created_at': '<ts>'}
[-only-old @27] {'seq': 28, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 41, 'delta': '新品'}, 'created_at': '<ts>'}
[-only-old @28] {'seq': 29, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 43, 'delta': '上市的'}, 'created_at': '<ts>'}
[-only-old @29] {'seq': 30, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 46, 'delta': '推广'}, 'created_at': '<ts>'}
[-only-old @30] {'seq': 31, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 48, 'delta': '主体'}, 'created_at': '<ts>'}
[-only-old @31] {'seq': 32, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 50, 'delta': '与'}, 'created_at': '<ts>'}
[-only-old @32] {'seq': 33, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 51, 'delta': '已有'}, 'created_at': '<ts>'}
[-only-old @33] {'seq': 34, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 53, 'delta': '素材'}, 'created_at': '<ts>'}
[-only-old @34] {'seq': 35, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 55, 'delta': '，'}, 'created_at': '<ts>'}
[-only-old @35] {'seq': 36, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 56, 'delta': '再'}, 'created_at': '<ts>'}
[-only-old @36] {'seq': 37, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 57, 'delta': '据此'}, 'created_at': '<ts>'}
[-only-old @37] {'seq': 38, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 59, 'delta': '展开'}, 'created_at': '<ts>'}
[-only-old @38] {'seq': 39, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 61, 'delta': '调研'}, 'created_at': '<ts>'}
[-only-old @39] {'seq': 40, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 63, 'delta': '和'}, 'created_at': '<ts>'}
[-only-old @40] {'seq': 41, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 64, 'delta': '方案'}, 'created_at': '<ts>'}
[-only-old @41] {'seq': 42, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 66, 'delta': '撰写'}, 'created_at': '<ts>'}
[-only-old @42] {'seq': 43, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 68, 'delta': '。'}, 'created_at': '<ts>'}
[-only-old @43] {'seq': 44, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_completed', 'payload': {'step_index': 0, 'stream_id': 'stream-1', 'text': "任务要求'基于已有资料'写新品上市营销方案，但尚未确认'已有资料'具体是什么。先列出我的文件，定位可用的 brief、产品资料或案例，再决定后续调研与撰写。", 'length': 78}, 'created_at': '<ts>'}
[-only-old @44] {'seq': 45, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_completed', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'text': '我先查看您"我的文件"中已有的资料（如 brief、产品信息、案例等），确认这次新品上市的推广主体与已有素材，再据此展开调研和方案撰写。', 'length': 68}, 'created_at': '<ts>'}
[-only-old @45] {'seq': 46, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_created', 'payload': {'step_index': 0, 'thought_summary': "任务要求'基于已有资料'写新品上市营销方案，但尚未确认'已有资料'具体是什么。先列出我的文件，定位可用的 brief、产品资料或案例，再决定后续调研与撰写。", 'action': {'type': 'list_files', 'input': {}}}, 'created_at': '<ts>'}
[-only-old @46] {'seq': 47, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_paused', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'text': '我先查看您"我的文件"中已有的资料（如 brief、产品信息、案例等），确认这次新品上市的推广主体与已有素材，再据此展开调研和方案撰写。', 'length': 68, 'fallback': False}, 'created_at': '<ts>'}
[-only-old @47] {'seq': 48, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'tool_started', 'payload': {'step_index': 0, 'action_type': 'list_files', 'tool_call': {}}, 'created_at': '<ts>'}
[-only-old @48] {'seq': 49, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'tool_completed', 'payload': {'step_index': 0, 'action_type': 'list_files', 'tool_call': {}, 'observation': {'files': [], 'folders': [], 'total': 0}}, 'created_at': '<ts>'}
[-only-old @49] {'seq': 50, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_started', 'payload': {'step_index': 0, 'stream_id': 'stream-3'}, 'created_at': '<ts>'}
[-only-old @50] {'seq': 51, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-3', 'offset': 0, 'delta': '当前'}, 'created_at': '<ts>'}
[-only-old @51] {'seq': 52, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-3', 'offset': 2, 'delta': '工作'}, 'created_at': '<ts>'}
[-only-old @52] {'seq': 53, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-3', 'offset': 4, 'delta': '目录'}, 'created_at': '<ts>'}
[-only-old @53] {'seq': 54, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-3', 'offset': 6, 'delta': '中没有'}, 'created_at': '<ts>'}
... 其余 792 条差异已省略
```
## 场景 2: 方案类全流程

- goal: `基于已有资料写一份新品上市的广告营销方案`
- 旧轨事件数: 846
- 图轨事件数: 846
- 结果: PASS（0 差异）
## 场景 1: 普通问答 fast path

- goal: `你好，介绍一下你自己`
- 旧轨事件数: 10
- 图轨事件数: 10
- 结果: PASS（0 差异）

## 场景 2: 方案类全流程

- goal: `基于已有资料写一份新品上市的广告营销方案`
- 旧轨事件数: 846
- 图轨事件数: 846
- 结果: PASS（0 差异）

## 场景 3: 必读文件未读→先追问

- goal: `基于已有资料写一份传播方案`
- 旧轨事件数: 839
- 图轨事件数: 839
- 结果: PASS（0 差异）

## 场景 4: 研究前置门禁

- goal: `写一份竞品分析方案`
- 旧轨事件数: 837
- 图轨事件数: 837
- 结果: PASS（0 差异）

## 场景 5: 版本规则

- goal: `把方案更新到 V2 版本`
- 旧轨事件数: 598
- 图轨事件数: 598
- 结果: PASS（0 差异）

## 场景 6: 结构校验拒稿→骨架补全

- goal: `写一份投放策略方案`
- 旧轨事件数: 1077
- 图轨事件数: 1077
- 结果: PASS（0 差异）

## 场景 7: 重试耗尽 run_failed

- goal: `写一份年度营销方案`
- 旧轨事件数: 269
- 图轨事件数: 269
- 结果: PASS（0 差异）

## 场景 8: 附件引用

- goal: `参考我上传的附件写一份推广方案`
- 旧轨事件数: 605
- 图轨事件数: 183
- 结果: FAIL（426 处差异）

```
[diff @179] old={'seq': 180, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'run_retry_scheduled', 'payload': {'error': "invalid_tool_input: 1 validation error for FetchPlatformSearchInput\nplatform\n  Input should be 'xiaohongshu' or 'douyin' [type=literal_error, input_value='小红书', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.13/v/literal_error", 'attempt_number': 2, 'retry_of_attempt_id': '<uuid>'}, 'created_at': '<ts>'} new={'seq': 180, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_started', 'payload': {'step_index': 0, 'stream_id': 'stream-7'}, 'created_at': '<ts>'}
[diff @180] old={'seq': 181, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'run_started', 'payload': {'run_id': '<uuid>', 'started_at': '<ts>'}, 'created_at': '<ts>'} new={'seq': 181, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-7', 'offset': 0, 'delta': "invalid_tool_input: 1 validation error for FetchPlatformSearchInput\nplatform\n  Input should be 'xiaohongshu' or 'douyin' [type=literal_error, input_value='小红书', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.13/v/literal_error"}, 'created_at': '<ts>'}
[diff @181] old={'seq': 182, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'plan_started', 'payload': {'step_index': 0, 'stream_id': 'stream-7'}, 'created_at': '<ts>'} new={'seq': 182, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_completed', 'payload': {'step_index': 0, 'stream_id': 'stream-7', 'text': "invalid_tool_input: 1 validation error for FetchPlatformSearchInput\nplatform\n  Input should be 'xiaohongshu' or 'douyin' [type=literal_error, input_value='小红书', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.13/v/literal_error", 'length': 259, 'fallback': True}, 'created_at': '<ts>'}
[diff @182] old={'seq': 183, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_started', 'payload': {'step_index': 0, 'stream_id': 'stream-2'}, 'created_at': '<ts>'} new={'seq': 183, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'run_failed', 'payload': {'error': "invalid_tool_input: 1 validation error for FetchPlatformSearchInput\nplatform\n  Input should be 'xiaohongshu' or 'douyin' [type=literal_error, input_value='小红书', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.13/v/literal_error"}, 'created_at': '<ts>'}
[-only-old @183] {'seq': 184, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 0, 'delta': '我先'}, 'created_at': '<ts>'}
[-only-old @184] {'seq': 185, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 2, 'delta': '从小'}, 'created_at': '<ts>'}
[-only-old @185] {'seq': 186, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 4, 'delta': '红'}, 'created_at': '<ts>'}
[-only-old @186] {'seq': 187, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 5, 'delta': '书'}, 'created_at': '<ts>'}
[-only-old @187] {'seq': 188, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 6, 'delta': '平台'}, 'created_at': '<ts>'}
[-only-old @188] {'seq': 189, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 8, 'delta': '内'}, 'created_at': '<ts>'}
[-only-old @189] {'seq': 190, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 9, 'delta': '搜索'}, 'created_at': '<ts>'}
[-only-old @190] {'seq': 191, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 11, 'delta': '"'}, 'created_at': '<ts>'}
[-only-old @191] {'seq': 192, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 12, 'delta': '无'}, 'created_at': '<ts>'}
[-only-old @192] {'seq': 193, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 13, 'delta': '糖'}, 'created_at': '<ts>'}
[-only-old @193] {'seq': 194, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 14, 'delta': '气泡'}, 'created_at': '<ts>'}
[-only-old @194] {'seq': 195, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 16, 'delta': '水'}, 'created_at': '<ts>'}
[-only-old @195] {'seq': 196, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 17, 'delta': ' '}, 'created_at': '<ts>'}
[-only-old @196] {'seq': 197, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 18, 'delta': '夏日'}, 'created_at': '<ts>'}
[-only-old @197] {'seq': 198, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 20, 'delta': '"'}, 'created_at': '<ts>'}
[-only-old @198] {'seq': 199, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 21, 'delta': '相关内容'}, 'created_at': '<ts>'}
[-only-old @199] {'seq': 200, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 25, 'delta': '，'}, 'created_at': '<ts>'}
[-only-old @200] {'seq': 201, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 26, 'delta': '收集'}, 'created_at': '<ts>'}
[-only-old @201] {'seq': 202, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 28, 'delta': '真实'}, 'created_at': '<ts>'}
[-only-old @202] {'seq': 203, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 30, 'delta': '笔记'}, 'created_at': '<ts>'}
[-only-old @203] {'seq': 204, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 32, 'delta': '样本'}, 'created_at': '<ts>'}
[-only-old @204] {'seq': 205, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 34, 'delta': '与'}, 'created_at': '<ts>'}
[-only-old @205] {'seq': 206, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 35, 'delta': '用户'}, 'created_at': '<ts>'}
[-only-old @206] {'seq': 207, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 37, 'delta': '表达'}, 'created_at': '<ts>'}
[-only-old @207] {'seq': 208, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 39, 'delta': '，'}, 'created_at': '<ts>'}
[-only-old @208] {'seq': 209, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 40, 'delta': '为'}, 'created_at': '<ts>'}
[-only-old @209] {'seq': 210, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 41, 'delta': '后续'}, 'created_at': '<ts>'}
[-only-old @210] {'seq': 211, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 43, 'delta': '竞'}, 'created_at': '<ts>'}
[-only-old @211] {'seq': 212, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 44, 'delta': '品'}, 'created_at': '<ts>'}
[-only-old @212] {'seq': 213, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 45, 'delta': '拆'}, 'created_at': '<ts>'}
[-only-old @213] {'seq': 214, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 46, 'delta': '解'}, 'created_at': '<ts>'}
[-only-old @214] {'seq': 215, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 47, 'delta': '、'}, 'created_at': '<ts>'}
[-only-old @215] {'seq': 216, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 48, 'delta': '卖'}, 'created_at': '<ts>'}
[-only-old @216] {'seq': 217, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 49, 'delta': '点'}, 'created_at': '<ts>'}
[-only-old @217] {'seq': 218, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 50, 'delta': '转'}, 'created_at': '<ts>'}
[-only-old @218] {'seq': 219, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 51, 'delta': '译'}, 'created_at': '<ts>'}
[-only-old @219] {'seq': 220, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 52, 'delta': '和'}, 'created_at': '<ts>'}
[-only-old @220] {'seq': 221, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 53, 'delta': '达人'}, 'created_at': '<ts>'}
[-only-old @221] {'seq': 222, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 55, 'delta': '内容'}, 'created_at': '<ts>'}
[-only-old @222] {'seq': 223, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 57, 'delta': '设计'}, 'created_at': '<ts>'}
[-only-old @223] {'seq': 224, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 59, 'delta': '打'}, 'created_at': '<ts>'}
[-only-old @224] {'seq': 225, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 60, 'delta': '底'}, 'created_at': '<ts>'}
[-only-old @225] {'seq': 226, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 61, 'delta': '；'}, 'created_at': '<ts>'}
[-only-old @226] {'seq': 227, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 62, 'delta': '同时'}, 'created_at': '<ts>'}
[-only-old @227] {'seq': 228, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 64, 'delta': '会在'}, 'created_at': '<ts>'}
[-only-old @228] {'seq': 229, 'id': '<id>', 'run_id': '<uuid>', 'attempt_id': '<uuid>', 'event_type': 'visible_thought_delta', 'payload': {'step_index': 0, 'stream_id': 'stream-2', 'offset': 66, 'delta': '后续'}, 'created_at': '<ts>'}
... 其余 376 条差异已省略
```

## 场景 9: 质检闭环

- goal: `写一份完整的品牌营销方案`
- 旧轨事件数: 974
- 图轨事件数: 974
- 结果: PASS（0 差异）

## 场景 10: 计费/usage

- goal: `写一份简短的营销方案`
- 旧轨事件数: 841
- 图轨事件数: 841
- 结果: PASS（0 差异）
## 场景 8: 附件引用

- goal: `参考我上传的附件写一份推广方案`
- 旧轨事件数: 605
- 图轨事件数: 605
- 结果: PASS（0 差异）
## 场景 1: 普通问答 fast path

- goal: `你好，介绍一下你自己`
- 旧轨事件数: 10
- 图轨事件数: 10
- 结果: PASS（0 差异）

## 场景 2: 方案类全流程

- goal: `基于已有资料写一份新品上市的广告营销方案`
- 旧轨事件数: 846
- 图轨事件数: 846
- 结果: PASS（0 差异）

## 场景 3: 必读文件未读→先追问

- goal: `基于已有资料写一份传播方案`
- 旧轨事件数: 839
- 图轨事件数: 839
- 结果: PASS（0 差异）

## 场景 4: 研究前置门禁

- goal: `写一份竞品分析方案`
- 旧轨事件数: 837
- 图轨事件数: 837
- 结果: PASS（0 差异）

## 场景 5: 版本规则

- goal: `把方案更新到 V2 版本`
- 旧轨事件数: 598
- 图轨事件数: 598
- 结果: PASS（0 差异）

## 场景 6: 结构校验拒稿→骨架补全

- goal: `写一份投放策略方案`
- 旧轨事件数: 1077
- 图轨事件数: 1077
- 结果: PASS（0 差异）

## 场景 7: 重试耗尽 run_failed

- goal: `写一份年度营销方案`
- 旧轨事件数: 269
- 图轨事件数: 269
- 结果: PASS（0 差异）

## 场景 8: 附件引用

- goal: `参考我上传的附件写一份推广方案`
- 旧轨事件数: 605
- 图轨事件数: 605
- 结果: PASS（0 差异）

## 场景 9: 质检闭环

- goal: `写一份完整的品牌营销方案`
- 旧轨事件数: 974
- 图轨事件数: 974
- 结果: PASS（0 差异）

## 场景 10: 计费/usage

- goal: `写一份简短的营销方案`
- 旧轨事件数: 841
- 图轨事件数: 841
- 结果: PASS（0 差异）
