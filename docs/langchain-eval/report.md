# LangChain 实验对比报告

生成时间：2026-08-09 15:20

对比对象：`DeepSeekClient`（生产 httpx 直连） vs `LangChainClient`（langchain-openai 0.3.35 + stream_usage）

## 指标

| 样本 | 首 token 延迟（prod/langchain） | 总耗时（prod/langchain） | usage 一致性 |
| --- | --- | --- | --- |
| qa（普通问答） | 1.052s / 1.013s | 1.493s / 1.517s | 有差异 |
| plan（JSON 规划） | 1.095s / 1.462s | 1.746s / 2.252s | 有差异 |
| long（长文生成） | 1.328s / 15.336s | 5.516s / 17.456s | 有差异 |
| plan JSON 规划 | True / True | 双方耗时 1.456s / 2.071s |

> usage 一致性 = 同一输入同一模型下双方采集的 token 数是否一致。实测 prompt_tokens 两侧完全一致（透传正确）；completion_tokens 同量级但不等（模型输出随机性为主因）。

## 运行异常记录

无。所有测量均成功。

## 结论（由数据驱动，团队决策依据）

- json_object 修复已验证：qa/long 两个普通文本样本在 langchain 侧不再被 DeepSeek 400 拒绝（此前因 response_format 误用报 deepseek_request_rejected）。
- usage 透传正确（prompt_tokens 完全一致），但 long 样本首 token 延迟差距远超 20%（1.328s vs 15.336s）：薄层替换风险不可控，暂不建议替换，保持 httpx 生产实现。
