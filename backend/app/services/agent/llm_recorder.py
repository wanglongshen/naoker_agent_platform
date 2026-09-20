"""LLM 录制/回放（LangGraph 差分校准用，env 门控，生产默认不生效）。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable


class ReplayExhaustedError(RuntimeError):
    pass


@dataclass
class LlmRecorder:
    mode: str  # "record" | "replay"
    path: Path
    scenario: str
    calls: list[dict[str, Any]] = field(default_factory=list)
    _cursor: int = 0
    _usage_sink: Callable[[dict], None] | None = None

    def __post_init__(self) -> None:
        if self.mode == "replay":
            self.calls = json.loads(Path(self.path).read_text(encoding="utf-8"))["calls"]

    # ---- record ----
    def record_plan(self, messages: list[dict], response: dict) -> None:
        self.calls.append({"method": "create_plan", "messages": messages,
                           "response": response, "chunks": None, "usages": []})

    def record_stream(self, messages: list[dict], chunks: list[str], usages: list[dict]) -> None:
        self.calls.append({"method": "stream_text", "messages": messages,
                           "response": None, "chunks": chunks, "usages": usages})

    def save(self) -> None:
        payload = {"scenario": self.scenario, "calls": self.calls}
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(self.path).with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # ---- replay ----
    def _next(self, method: str) -> dict[str, Any]:
        if self._cursor >= len(self.calls):
            raise ReplayExhaustedError(f"no recorded call at cursor {self._cursor} for {method}")
        call = self.calls[self._cursor]
        if call["method"] != method:
            raise ReplayExhaustedError(
                f"recorded method mismatch at {self._cursor}: expected {call['method']}, got {method}")
        self._cursor += 1
        return call

    def bind_usage_sink(self, sink: Callable[[dict], None] | None) -> None:
        self._usage_sink = sink

    def replay_plan(self, messages: list[dict]) -> dict:
        return self._next("create_plan")["response"]

    async def replay_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        call = self._next("stream_text")
        for chunk in call["chunks"] or []:
            yield chunk
        for usage in call["usages"] or []:
            if self._usage_sink is not None:
                self._usage_sink(usage)


_REGISTRY: dict[str, LlmRecorder] = {}


def recorder_from_env() -> LlmRecorder | None:
    """按 env 返回**进程内共享**的录制/回放器。

    进程里会构造多个 DeepSeekClient（service.llm_client、planner.client、质检等），
    它们必须共享同一个 recorder：录制时把全部调用按发生顺序写进同一份 fixture，
    回放时共享同一个游标。否则每个 client 各自从 0 开始消费 fixture（错位），
    录制时各自的 save() 互相覆盖（丢调用）。
    """
    record_path = os.environ.get("LANGGRAPH_DIFF_RECORD")
    replay_path = os.environ.get("LANGGRAPH_DIFF_REPLAY")
    if record_path:
        return _shared("record", Path(record_path))
    if replay_path:
        return _shared("replay", Path(replay_path))
    return None


def _shared(mode: str, path: Path) -> LlmRecorder:
    key = f"{mode}:{path}"
    existing = _REGISTRY.get(key)
    if existing is None:
        existing = LlmRecorder(mode=mode, path=path, scenario=path.stem)
        _REGISTRY[key] = existing
    return existing


def reset_shared_recorders() -> None:
    """清空共享登记表。

    差分脚本在同一个进程里先后跑旧轨与图轨两次 run：两次 run 必须各自从
    fixture 游标 0 开始（各自独立消费），因此每次 run 开始前重置。
    """
    _REGISTRY.clear()
