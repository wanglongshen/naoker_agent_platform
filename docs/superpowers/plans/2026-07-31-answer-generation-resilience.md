# Agent Answer Generation Resilience — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent intermittent "未完成" failures when DeepSeek API returns transient errors during answer generation.

**Architecture:** Wrap `_stream_final_answer` call with retry logic (3 attempts × 2s delay). On final failure, generate a fallback answer via a condensed non-streaming call instead of marking the run as failed.

**Tech Stack:** Python, httpx, asyncio

## Global Constraints

- Must not break existing retry mechanism (`_schedule_retryable_failure`)
- Must preserve streaming for the answer (first attempt always streams)
- Fallback answer should be brief but informative
- Tests must pass (31/31 backend)

---

### Task 1: Add retry wrapper for `_stream_final_answer`

**Files:**
- Modify: `backend/app/services/agent/loop.py:563-568`

**Interfaces:**
- Consumes: `_stream_final_answer(self, repo, ctx, messages)`
- Produces: Same return value, but retried on transient errors

- [ ] **Step 1: Add retry logic in `_stream_visible_thought_with_tool_interleave`**

In `backend/app/services/agent/loop.py`, replace lines 563-568:

```python
        if validated_action_type == "finish":
            await self._persist_and_notify(repo, ctx, "visible_thought_completed",
                {"step_index": step_index, "stream_id": stream_id, "text": finalized_text, "length": len(finalized_text), "fallback": fallback})

            answer_messages = self._build_final_answer_messages(
                goal=self._extract_goal_from_messages(messages),
                session_history=None, previous_observation=previous_observation, attachments=None)

            answer = None
            last_error = None
            for attempt_num in range(1, 4):
                try:
                    answer = await self._stream_final_answer(repo, ctx, answer_messages)
                    break
                except (RetryableStreamingError, httpx.HTTPError, asyncio.TimeoutError) as exc:
                    last_error = exc
                    if attempt_num < 3:
                        await asyncio.sleep(2)

            if answer is None:
                fallback_answer = f"抱歉，回答生成服务暂时不可用（{str(last_error)[:100]}），请稍后重试。"
                answer = fallback_answer
                await self._persist_and_notify(repo, ctx, "answer_started",
                    {"stream_id": f"answer-{ctx.run.id}"})
                await self._persist_and_notify(repo, ctx, "answer_delta",
                    {"stream_id": f"answer-{ctx.run.id}", "offset": 0, "delta": fallback_answer})
                await self._persist_and_notify(repo, ctx, "answer_completed",
                    {"stream_id": f"answer-{ctx.run.id}", "text": fallback_answer, "length": len(fallback_answer)})

            observation = {"final_answer": answer}
            return finalized_text, observation
```

- [ ] **Step 2: Same fix for the exception handler path**

In the same file, replace lines 545-552 (the fallback handler for finish inside the except block):

```python
                if validated_action_type == "finish":
                    answer = None
                    for _ in range(3):
                        try:
                            answer = await self._stream_final_answer(repo, ctx, self._build_final_answer_messages(
                                goal=self._extract_goal_from_messages(messages),
                                session_history=None, previous_observation=previous_observation, attachments=None))
                            break
                        except (RetryableStreamingError, httpx.HTTPError, asyncio.TimeoutError):
                            await asyncio.sleep(2)
                    if answer is None:
                        answer = "抱歉，回答生成服务暂时不可用，请稍后重试。"
                    observation = {"final_answer": answer}
```

- [ ] **Step 3: Verify tests**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py -v
```

Expected: 31/31 pass

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/agent/loop.py
git commit -m "fix: retry answer generation 3x with 2s delay before fallback"
```
