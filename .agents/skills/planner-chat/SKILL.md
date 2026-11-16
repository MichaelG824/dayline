---
name: planner-chat
description: Working on the planner chat assistant - api/chat.py, its read/propose tools, POST /api/chat/confirm, the SSE stream, planner preferences, or logged outcomes.
user-invocable: false
metadata:
  internal: true
---

## LLM chat (analysis-first, propose/confirm)

`api/chat.py` uses the Anthropic Python SDK directly (no MCP). The assistant is **analysis-first**: situation → risks/gaps → recommendation. It may stop at advice; `propose_*` tools fire only when the user asks for changes or analysis clearly needs a concrete fix. Response shape stays `{ explanation, proposals, history }` - **proposals may be empty**.

**Read tools** (auto-executed each turn): `list_tasks`, `get_plan`, `list_interviews`, `get_category_ranks`, `get_preferences`, `get_recent_outcomes`. **Propose tools** (schema-only until confirm): `propose_duration_change`, `propose_new_task`, `propose_reprioritization`, `propose_preference_update`, `propose_category_rank_change`. `POST /api/chat/confirm` is the only mutation path (user multi-select); never auto-apply because Claude called a tool. LLM never enters `build_plan`.

**Streaming** (`POST /api/chat/stream`): an additive SSE twin of `/api/chat`, which stays as the non-streaming fallback. `chat.py`'s `stream_chat_turn` mirrors `run_chat_turn` round-for-round (both share `_handle_tool_uses`), yielding `("status"|"delta"|"result", ...)`; `services/chat.py` hand-formats those as `data: <json>` frames (no `sse-starlette`) and `_json_default` converts SDK content blocks in `history`, which FastAPI's encoder does for free on the blocking path. The `Cache-Control: no-transform` header on the endpoint is load-bearing, not boilerplate: without it the Next dev proxy gzips the response and buffers the whole turn into one chunk. The Starlette `BaseHTTPMiddleware` auth gate does *not* buffer it.

**Preferences** (`adapters/preferences.py`, table `planner_preferences` via `009_planner_preferences_outcomes.sql`): peak hours, category caps, standing rules, free text - injected into the system prompt every turn; also `GET/PUT /api/preferences`.

**Outcomes** (`adapters/outcomes.py`, table `planner_outcomes`): lightweight accept/reject/completion/duration-override events for retros via `get_recent_outcomes`. Confirm logs accepts + rejects (`offered` minus applied); task PATCH logs completion/duration overrides best-effort. Nudges still require propose → confirm.
