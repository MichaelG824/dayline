---
name: mock-interviews
description: Working on the Mock tab - question bank and extraction, grading and scorecards, live coding sessions, staged practical rounds, or the in-session AI assistant (src/dayline/mock/, adapters/mock_source.py, api/services/mock*.py).
user-invocable: false
metadata:
  internal: true
---

## Mock interviews (the Mock tab)

`adapters/mock_source.py` (`MockSource`, migration `011_mock_interviews.sql`) stores the private question bank, rubrics, grading standards (`mock_guidelines`), sessions, and scorecards. The LLM work lives in `src/dayline/mock/` (no FastAPI/Supabase imports); `api/services/mock.py` wires it.

- **Tool calls are not forced.** The current models reject `tool_choice` of type `tool`/`any`, so `mock/llm.py` offers the tool with `auto`, says "call it" in the system prompt, and nudges once if the reply is prose. Never reintroduce a forced `tool_choice`.
- **Code decides what to trust in a scorecard** (`mock/grader.py`): every rubric key exactly once with an integer 1-4 (invalid cards go back to the model, up to `MAX_ATTEMPTS`), the overall score is a weighted mean computed in code, and each evidence quote is matched against the transcript (`verified`) so invented quotes are flagged, not trusted.
- **Duplicates are suggestions, never merges.** `mock/ingest.py` shortlists similar canonical questions (rapidfuzz on title + prompt); the user picks "same as" on save. Copies point at a root via `canonical_id`, one level deep (`services/mock.py` `_canonical_target`).
- **Weak areas become tasks only via `POST /api/chat/confirm`.** `weak_area_proposals` emits `propose_new_task` proposals carrying `mock_session_id`; `apply_proposal` copies it onto the task. The client offers only proposals not yet added, so already-added ones are never logged as rejected.
- **Live sessions never touch Docker from Dayline.** Code runs in the separate `sandbox/runner` service (its own `pyproject.toml`; the only process with Docker access), reached by `adapters/sandbox.py` over HTTP/WebSocket via `SANDBOX_RUNNER_URL` + `SANDBOX_RUNNER_SECRET`. Templates live in `mock/templates/` (migration `012_mock_live_sessions.sql`). Runner Docker tests are opt-in: `RUN_DOCKER_TESTS=1 uv run pytest sandbox/runner/tests/test_runner_docker.py`.
- Models: `MOCK_MODEL` (extraction and the staged-round interviewer; default `claude-sonnet-5-5`) and `MOCK_GRADER_MODEL` (default `claude-opus-5-5`), see `mock/__init__.py`.

## Staged practical rounds (Mock tab)

A staged round is a live session (`kind = live`) with `MockSession.staged_problem_id` + `stages` (migrations 013, then 014 in a separate run), so files, terminal, resume, and end reuse `services/mock_live.py`; the staged parts live in `services/mock_staged.py`.

- **Problems are content, not code**: one folder per problem under `src/dayline/mock/staged_problems/<id>/` (format documented at the top of `mock/staged.py`). Adding a problem means adding a folder; `tests/test_staged_lru.py` shows how to prove each reference passes its stage and one-bug variants fail the right tests.
- **Hidden tests never touch the workspace tree**: the runner's `POST /sandboxes/{id}/hidden-tests` copies them into the ignored `.dayline/hidden` folder for one run and runs the pack's `hidden_test_cmd` (python, rails and next-nest have one). A stage passes only when the whole cumulative run (active + passed stages, never skipped ones) passes and every one of its own tests ran.
- **Scores are computed in code** (`staged.score_round`): edge cases are "hit" only if they passed the stage's first run; design churn is the share of the previous stage's code lines kept (`REWRITE_THRESHOLD`). The interviewer (`mock/interviewer.py`, `MOCK_MODEL`) only talks; it never changes round state. Notes, hidden tests, and locked stages never reach the client (`serializers.staged_round_json`).
- Changing `sandbox/` (packs included) means re-running `deploy/sandbox-vm/setup.sh`; an older runner answers hidden-test runs with a 501 "redeploy" error.

## In-session AI assistant (AI-assisted live rounds)

Live sessions whose template or staged problem has `round_type = "AI-assisted project"` get a coding assistant (`mock/assistant.py`, wired in `api/services/mock_assistant.py`; `services/mock.assistant_enabled` decides).
Model: `MOCK_ASSISTANT_MODEL`, default `claude-sonnet-4-5` on purpose (the captain's choice, not a stale default).

- **No mode writes.** Ask and plan get read-only tools; edit adds `propose_edit`, which only drafts a full new file plus the version it was based on. The only write is `POST .../assistant/edits/{id}` with `accept`, through `mock_live.write_file`, and only if the file is still at that version (otherwise the edit is recorded as `conflict`).
- **The conversation lives in `mock_session_events`** (`assistant_prompt` / `assistant_response` / `assistant_edit_proposed` / `assistant_edit_decided`; shapes in the module docstring), so no migration and it survives restarts. The model gets earlier turns back as text only. `serializers.mock_event_json` strips the proposed file content; `worklog.ai_log` is the grader's compact view.
- A turn in flight is tracked in process memory (one per session) for cancelling; the client also drops the connection after a grace period, which the stream records as stopped.
- Opt-in real-model test: `RUN_MODEL_TESTS=1 uv run pytest tests/test_mock_assistant_model.py`.
