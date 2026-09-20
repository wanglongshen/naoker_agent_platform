"""方案质量自审门：写入后由 LLM 对照质量评分卡评审，结果驱动修订。"""
from __future__ import annotations

import json
import re
from typing import Any

DEFAULT_CRITERIA = (
    "完整性：全部模块有实质内容（非一句话带过），每模块不少于 200 字。\n"
    "可落地性：有具体预算数字表；有排期执行节奏；步骤可操作（谁、何时、做什么）。\n"
    "数据支撑：关键结论有数据或来源；引用调研结果；无凭空编造的数字。\n"
    "专业度：术语与规范一致；格式统一；无空洞套话。"
)

_SCORECARD_RE = re.compile(r"^#{1,3}\s*质量评分卡\s*$", re.MULTILINE)


def extract_criteria(blueprint: str) -> str:
    """从蓝图「质量评分卡」章节提取评审标准；无该章节返回内置默认。"""
    if not blueprint:
        return DEFAULT_CRITERIA
    m = _SCORECARD_RE.search(blueprint)
    if m is None:
        return DEFAULT_CRITERIA
    return blueprint[m.end():].strip()[:2000] or DEFAULT_CRITERIA


def build_review_messages(
    goal: str, file_content: str, criteria: str, round_no: int
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是严苛的方案质量评审官。你的职责是找出所有问题，绝不放过任何不合格项。\n"
                "评审标准（质量评分卡）：\n" + criteria + "\n\n"
                "输出格式：只输出 JSON，结构："
                '{"score": 0-100, "pass": true/false, "dims": [{"name": "完整性", "pass": true/false, "reason": "依据（引用原文片段）"}, ...]}\n'
                "规则：score < 60 或任一维度未通过 则 pass 为 false。\n"
                "禁止使用『基本合格』『大体符合』等模糊判定；每项必须给出依据。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"任务目标：{goal}\n"
                f"待评审方案全文（第 {round_no} 轮评审）：\n\n{file_content}"
            ),
        },
    ]


def parse_review_result(text: str) -> dict[str, Any]:
    """解析评审 JSON；失败返回 score=0/pass=False 的兜底结构。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {"score": 0, "pass": False, "dims": []}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"score": 0, "pass": False, "dims": []}
    score = int(data.get("score", 0))
    dims = data.get("dims", [])
    passed = bool(data.get("pass", False))
    if score < 60 or any(not d.get("pass", False) for d in dims):
        passed = False
    return {"score": score, "pass": passed, "dims": dims}
