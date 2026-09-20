# Two-Phase Planner: Streaming + JSON-Mode Fallback

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate "DeepSeek returned non-JSON content" errors by falling back to JSON-mode `create_plan` when streaming output can't be parsed.

**Architecture:** `_stream_planning` tries streaming first (fast, 95% success). If `_parse_json_content` fails, falls back to `create_plan` with `response_format: json_object` (reliable, 100% JSON). The `create_plan` method (previously deleted) is restored with its original implementation.

**Tech Stack:** Python, httpx, DeepSeek API

## Global Constraints

- `create_plan` must remain non-streaming (DeepSeek doesn't support `stream=true` with `response_format: json_object`)
- The fallback adds 2-5s latency only when streaming fails (~5% of cases)
- Existing tests must pass
- `_stream_planning` interface unchanged

---

### Task 1: Restore `create_plan` with JSON mode

**Files:**
- Modify: `backend/app/services/agent/llm.py`

- [ ] **Step 1: Add `create_plan` back to `DeepSeekClient`**

Insert before the `_parse_json_content` method in `backend/app/services/agent/llm.py`:

```python
    async def create_plan(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")

        url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.deepseek_model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._client.post(url, headers=headers, json=payload, timeout=settings.http_timeout_seconds)
        except httpx.TimeoutException as exc:
            raise RetryablePlannerError("deepseek_timeout") from exc
        except httpx.RequestError as exc:
            raise RetryablePlannerError("deepseek_request_error") from exc

        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError("deepseek_auth_error")
        if response.status_code in {400, 404, 422}:
            raise ProviderResponseError("deepseek_request_rejected")
        if response.status_code in {408, 425, 429, 500, 502, 503, 504}:
            raise RetryablePlannerError(f"deepseek_retryable_status: {response.status_code}")

        response.raise_for_status()
        data = response.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Invalid DeepSeek response structure") from exc

        if not isinstance(content, str):
            raise ValueError("DeepSeek content must be a string")

        return self._parse_json_content(content)
```

- [ ] **Step 2: Run existing tests**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestLoopHelpers -v
```

---

### Task 2: Retry with `create_plan` on streaming parse failure

**Files:**
- Modify: `backend/app/services/agent/loop.py`

- [ ] **Step 1: Modify `_stream_planning` to fall back**

Replace lines 77-84 of `backend/app/services/agent/loop.py`:

```python
        parsed = None
        try:
            parsed = self.planner.client._parse_json_content(full_text)
        except ValueError:
            pass

        if parsed is None:
            parsed = await self.planner.client.create_plan(messages)

        display_text = parsed.get("thought_summary", full_text)
        await self._persist_and_notify(
            repo, ctx, "plan_completed",
            {"step_index": step_index, "stream_id": stream_id, "text": display_text, "length": len(display_text)},
        )

        return parsed
```

- [ ] **Step 2: Remove the `except ValueError` fallback at call site**

At lines 1037-1039, remove the `except ValueError` handler we previously added (it's now superseded by `_stream_planning`'s internal retry):

Delete this block:
```python
            except ValueError:
                raw_plan = {"thought_summary": "fallback", "action": {"type": "finish", "input": {}}}
                normalized_plan = self.planner._normalize_plan(raw_plan)
                plan = self.planner._validate_plan(normalized_plan).model_dump(mode="json")
```

- [ ] **Step 3: Run full tests**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py -v
```

Expected: 31/31 pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/agent/llm.py backend/app/services/agent/loop.py
git commit -m "feat: two-phase planner — stream first, JSON-mode retry on parse failure"
```
