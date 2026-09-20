"""LangChain vs 生产 httpx 对比基准：产出 docs/langchain-eval/report.md。

用法（01-rbac 环境）：
    python scripts/langchain_benchmark.py
"""

import asyncio
import time
from pathlib import Path

from app.services.agent.llm import DeepSeekClient
from app.services.langchain_demo.client import LangChainClient
from app.services.langchain_demo.samples import SAMPLES

REPORT_PATH = Path(__file__).resolve().parents[2] / "docs" / "langchain-eval" / "report.md"


async def measure_stream(client, messages):
    first_latency = None
    total = ""
    usage: list[dict] = []
    started = time.monotonic()
    async for chunk in client.stream_text(messages, usage_sink=usage.append):
        if first_latency is None:
            first_latency = time.monotonic() - started
        total += chunk
    return {
        "first_token_s": round(first_latency or 0, 3),
        "total_s": round(time.monotonic() - started, 3),
        "chars": len(total),
        "usage": usage[-1] if usage else None,
    }


async def measure_plan(client, messages):
    started = time.monotonic()
    result = await client.create_plan(messages)
    return {"total_s": round(time.monotonic() - started, 3), "json_ok": isinstance(result, dict)}


def _err_label(exc: Exception) -> str:
    return f"错误: {type(exc).__name__}: {exc}"


def _fmt_side(value, exc: Exception | None, key: str) -> str:
    if exc is not None:
        return _err_label(exc)
    return f"{value[key]}s"


async def main() -> None:
    prod = DeepSeekClient()
    lc = LangChainClient()
    rows: list[str] = []
    errors: list[str] = []
    try:
        for name, sample in SAMPLES.items():
            pm = lm = None
            pm_exc = lm_exc = None
            try:
                pm = await measure_stream(prod, sample["messages"])
            except Exception as exc:
                pm_exc = exc
                errors.append(f"prod stream {name}: {exc}")
            try:
                lm = await measure_stream(lc, sample["messages"])
            except Exception as exc:
                lm_exc = exc
                errors.append(f"langchain stream {name}: {exc}")

            if pm is not None and lm is not None:
                usage_match = "一致" if pm["usage"] == lm["usage"] else "有差异"
            else:
                usage_match = "-"
            first_cell = f"{_fmt_side(pm, pm_exc, 'first_token_s')} / {_fmt_side(lm, lm_exc, 'first_token_s')}"
            total_cell = f"{_fmt_side(pm, pm_exc, 'total_s')} / {_fmt_side(lm, lm_exc, 'total_s')}"
            rows.append(f"| {name}（{sample['description']}） | {first_cell} | {total_cell} | {usage_match} |")

        plan_p = plan_l = None
        plan_p_exc = plan_l_exc = None
        try:
            plan_p = await measure_plan(prod, SAMPLES["plan"]["messages"])
        except Exception as exc:
            plan_p_exc = exc
            errors.append(f"prod plan: {exc}")
        try:
            plan_l = await measure_plan(lc, SAMPLES["plan"]["messages"])
        except Exception as exc:
            plan_l_exc = exc
            errors.append(f"langchain plan: {exc}")

        if plan_p is not None and plan_l is not None:
            rows.append(f"| plan JSON 规划 | {plan_p['json_ok']} / {plan_l['json_ok']} | 双方耗时 {plan_p['total_s']}s / {plan_l['total_s']}s |")
        else:
            plan_p_cell = _err_label(plan_p_exc) if plan_p_exc is not None else str(plan_p["json_ok"])
            plan_l_cell = _err_label(plan_l_exc) if plan_l_exc is not None else str(plan_l["json_ok"])
            rows.append(f"| plan JSON 规划 | {plan_p_cell} / {plan_l_cell} | 双方耗时 - |")
    finally:
        await prod.close()
        await lc.close()

    report = f"""# LangChain 实验对比报告

生成时间：{time.strftime("%Y-%m-%d %H:%M")}

对比对象：`DeepSeekClient`（生产 httpx 直连） vs `LangChainClient`（langchain-openai 0.3.35 + stream_usage）

## 指标

| 样本 | 首 token 延迟（prod/langchain） | 总耗时（prod/langchain） | usage 一致性 |
| --- | --- | --- | --- |
{chr(10).join(rows)}

> usage 一致性 = 同一输入同一模型下双方采集的 token 数是否一致；usage 差异说明 langchain 的 `stream_usage` 透传层与 DeepSeek 原生 `include_usage` 不完全等价。

## 运行异常记录

{chr(10).join(f"- {e}" for e in errors) if errors else "无。所有测量均成功。"}

## 结论（由数据驱动，团队决策依据）

- 若三行 usage 均为"一致"且延迟差距 <20%：薄层替换风险可控，可考虑渐进替换。
- 若 usage 有差异或 JSON 可用率低于生产：不建议替换，保持 httpx 生产实现。
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"report written: {REPORT_PATH}")
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
