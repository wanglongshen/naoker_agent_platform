# Realtime SSE And Tavily Design

## Scope

Make active Agent runs visibly stream across the existing separate API and Worker processes, restore a fast frontend development command, and configure the existing Tavily-backed web search tool. Keep the current final-answer typing animation at 20 milliseconds per character.

## Architecture

The SSE endpoint remains the frontend transport. After replaying persisted events and subscribing to the in-process event bus, it will query persisted events every 250 milliseconds while the run is active. This database polling closes the notification gap between the separate Worker process, which persists events, and the API process, which owns SSE connections. The event bus remains an optimization for events published by the API process. A 15-second keepalive remains available only when no event is sent.

The frontend continues to use `EventSource`, `useRunEventStream`, and the existing reducer. Each persisted `answer_delta` is rendered as it arrives; `FinalAnswerPanel` continues to animate its supplied stream at 20 milliseconds per character. No fallback polling or protocol change is added to the browser.

## Frontend Startup

`npm run dev` runs the existing Next development server command directly. A separate `preview` script performs the production build and starts the production server. This prevents ordinary frontend development from waiting for a full build.

## Tavily Search

The supplied Tavily API key is stored only as `TAVILY_API_KEY` in the ignored `backend/.env` file. Existing `Settings`, `ToolExecutor._web_search`, input bounds, URL validation, and output sanitization remain the sole search implementation. The key is not added to source files, examples, tests, output, or git history.

## Error Handling

The SSE generator must continue to emit events in ascending sequence order, emit each sequence once, finish after terminal runs are fully caught up, and retain its origin and ownership validation. A database query failure must not silently fabricate an event; it should close the stream so the browser reconnect behavior can recover.

Tavily request failures continue to map to the existing safe retryable errors and must not expose the configured key.

## Testing

Backend tests cover a running SSE subscription receiving an event persisted without an in-process event-bus notification within the polling interval. Existing replay, ordering, terminal catch-up, and authorization tests remain green.

Frontend tests retain the 20ms typing behavior and verify the `dev`/`preview` package-script contract. Tool tests exercise a successful Tavily response with a mocked secret and continue to assert that missing-key errors do not disclose credentials.
