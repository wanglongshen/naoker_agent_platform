# LangChain 实验模块

目的：并行验证 LangChain 是否值得替换生产 `DeepSeekClient`（httpx 直连）。**生产代码零依赖本模块**——只有测试与脚本 import 它。

## 运行

```bash
# 契约层测试（全 mock，CI 可跑）
python -m pytest tests/test_langchain_demo.py -q --no-header

# 真实调用对比（消耗真实 token，需 .env 有 DEEPSEEK_API_KEY）
python -m pytest tests/test_langchain_demo.py::TestRealCalls -q --no-header

# 基准报告
python scripts/langchain_benchmark.py
# → 生成 docs/langchain-eval/report.md
```

## 决策流程

1. 跑 benchmark 拿数据
2. 团队读 `docs/langchain-eval/report.md` 结论
3. 若决定替换：另开 spec/plan（薄层替换 llm.py），本模块不直接进生产

## 已知结论（2026-08-10 首轮实测）

- 契约层 21 测试全过；真实调用 3/3 通过（qa/plan/long 双客户端）。
- usage 透传：prompt_tokens 两侧**完全一致**（stream_usage 透传正确）；completion_tokens 同量级但不等（模型输出随机性 + 参数差异）。
- long 样本首 token 延迟：langchain 15.3s vs 生产 1.3s（12 倍差距）。
- 结论：暂不建议替换，保持 httpx 生产实现。后续如需多供应商支持可重新评估。
