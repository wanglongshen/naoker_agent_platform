# LangChain 并行实验模块设计（2026-08-10）

## 1. 背景与动机

- 团队要求引入 LangChain（学习价值/团队标准化动机，非技术需求）。
- 现状：`backend/app/services/agent/llm.py` 是自研 httpx 直调 DeepSeek 的 `DeepSeekClient`（`create_plan` / `stream_text` / `complete` 三个方法），编排层（loop/planner/tool_executor）全自研，价值层（SSE 流式、事件审计、双通道推送、计费 usage 采集、调研门、骨架预填、自审门）全部框架无关。
- 结论（经利弊分析）：生产热路径不宜直接换 LangChain——计费 usage 透传、JSON 结构化、SSE 流式三条关键路径存在重适配风险。选定 **C 方案：并行双实现**——生产保持 httpx，实验模块用 LangChain 实现等价接口，用对比测试数据说话，由团队据报告决策是否渐进替换。

## 2. 范围

### 做
- 实验模块 `backend/app/services/langchain_demo/`：`LangChainClient`，与 `DeepSeekClient` 三个方法**签名完全一致**。
- 契约层测试（全 mock，CI 可跑）：签名/返回类型/异常映射/JSON 截断修复兼容性。
- 真实调用层测试（无 API key 自动 skip）：3 条固定输入 × 3 场景，双客户端各跑一遍，采集指标。
- 基准脚本 `backend/scripts/langchain_benchmark.py`：跑完真实对比生成 `docs/langchain-eval/report.md`。
- 依赖 `langchain-core` + `langchain-openai`（锁定 pydantic v2 兼容版本）装入 01-rbac conda 环境。

### 不做（YAGNI）
- 生产驱动切换开关（报告后由团队决策，再另走 spec/plan）。
- UI/API 端点；不注册路由、不挂 lifespan、不进 main.py。
- 多供应商抽象扩展（本次只对 DeepSeek）。
- 编排层任何改动。

## 3. 模块设计

```
backend/app/services/langchain_demo/
├── __init__.py
├── client.py      # LangChainClient
└── README.md      # 运行方式与报告阅读指引
```

### 3.1 LangChainClient 接口（与 DeepSeekClient 一致）

```python
class LangChainClient:
    def __init__(self) -> None: ...
    async def close(self) -> None: ...
    async def stream_text(
        self,
        messages: list[dict[str, str]],
        usage_sink: Callable[[dict], None] | None = None,
    ) -> AsyncIterator[str]: ...
    async def complete(self, messages: list[dict[str, str]]) -> str: ...
    async def create_plan(self, messages: list[dict[str, str]]) -> dict[str, Any]: ...
```

内部：`ChatOpenAI(base_url=settings.deepseek_base_url, api_key=settings.deepseek_api_key, model=settings.deepseek_model)`。

### 3.2 三方法对照实现

| 方法 | httpx 生产实现 | langchain 对照实现 | 对比关注点 |
|---|---|---|---|
| `stream_text` | 自解析 SSE + `stream_options: include_usage` 末尾 chunk 采 usage | `astream()` + `AIMessageChunk.usage_metadata` 提取（DeepSeek 非标准参数透传是最大不确定点，实测验证） | 首 token 延迟、总耗时、usage 是否拿得到且数值一致 |
| `create_plan` | `response_format: json_object` + 自研截断 JSON 自动补全（`_parse_json_content`） | `extra_body={"response_format": {"type": "json_object"}}` 直传，截断修复复用 `_parse_json_content` | JSON 可用率（含截断场景注入） |
| `complete` | 内部走流式收集 | `ainvoke()` | 返回一致性 |

### 3.3 异常映射

langchain 异常 → 生产一致异常语义：

| langchain 异常 | 映射 |
|---|---|
| `langchain_core.exceptions.AuthenticationError` | `ProviderAuthenticationError` |
| `langchain_core.exceptions.APIError` | `ProviderResponseError` |
| `langchain_core.exceptions.APITimeoutError` | `RetryableStreamingError` |
| 其余网络类异常 | `RetryableStreamingError` |

调用方（测试/脚本）无需感知客户端实现差异。

## 4. 数据流

```
真实调用测试 / benchmark 脚本
   ├── 输入样本（3 条固定输入 × 3 场景）
   ├── DeepSeekClient（生产） → 指标 A
   └── LangChainClient（实验） → 指标 B
        → 汇总（首 token 延迟 / 总耗时 / usage 数值 / JSON 可用率）
        → docs/langchain-eval/report.md（表格 + 结论 + 是否建议替换）
```

指标采集：`time.monotonic`（首 chunk 时刻、流结束时刻）；usage 以双方收集到的 `usage` 字典对比。

## 5. 测试策略

### 契约层（`backend/tests/test_langchain_demo.py`，全 mock）
- 三个方法签名/返回类型与 `DeepSeekClient` 一致（鸭子类型断言）。
- mock langchain 底层 transport：`stream_text` 产出 chunk 顺序一致、`usage_sink` 被调用且数值透传。
- 异常映射：模拟 401 → `ProviderAuthenticationError`，5xx → `RetryableStreamingError`。
- JSON 截断修复兼容：给 `create_plan` 注入截断原始文本，`_parse_json_content` 自动补全后可用。
- 无真实 API key 时整套契约层正常通过。

### 真实调用层（同文件，`@pytest.mark.skipif(not settings.deepseek_api_key, ...)`）
- 3 条固定输入 × 3 场景（普通问答 / JSON 规划 / 长文生成），双客户端各跑一遍。
- 断言：双方均成功、usage 数值一致（容差 ±5%）、JSON 场景双方均可解析。
- 注意：消耗真实 token（6 次调用/轮，成本约几毛钱），仅手动或显式触发，不随全量测试跑。

### 基准脚本（`backend/scripts/langchain_benchmark.py`）
- 与真实调用层同源复用输入样本与采集逻辑，输出 markdown 报告到 `docs/langchain-eval/report.md`。

## 6. 错误处理

- 实验模块任何失败不影响生产：不注册路由/lifespan，import 链隔离（仅测试与脚本 import）。
- langchain 依赖版本冲突风险：安装前核对 requirements 与 pydantic v2 兼容性；如冲突无法共存，报告问题并暂停实验（不强行升级生产依赖）。

## 7. 验证与交付

- 契约层测试并入全量回归（零回归）。
- `npx tsc` 无关（无前端改动）。
- 真实调用层 + benchmark 脚本手工触发，产出报告。
- 报告结论由团队决策（保持生产 / 渐进替换薄层），决策结果另走 spec/plan。

## 8. 风险

| 风险 | 缓解 |
|---|---|
| langchain-openai 不透传 DeepSeek 非标准参数（usage） | 契约层不覆盖此点，真实调用层实测；实测不通则报告记录该限制，不影响结论（数据即结论） |
| 依赖版本冲突 | 安装前核对；冲突则暂停并报告，不升级生产依赖 |
| 学习动机下"顺手替换生产"的蔓延 | 明确不做清单 + 报告作为唯一决策依据 |
