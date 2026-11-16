---
name: fullstack-sandbox
description: Working on sandbox packs (rails, next-nest), the live preview proxy, the sandbox runner service, or generated full-stack practice rounds - sandbox/, deploy/sandbox-vm/, api/services/mock_preview.py, mock/project_gen.py.
user-invocable: false
metadata:
  internal: true
---

## Full-stack packs and the live preview (Mock tab)

`sandbox/packs/{rails,next-nest}` declare dev servers (`[[servers]]`; the `pack.toml` format is at the top of `dayline_runner/packs.py`). The runner supervises them (`servers.py`) and serves them through its preview proxy (`preview.py`); the Workspace's Preview pane (`web/app/components/mock/PreviewPane.tsx`) shows them.

- Sandboxes keep `network_mode: none`: each preview connection is a `docker exec` of `socat` inside the sandbox (`tunnel.py`), so a pack with servers needs `socat` in its image.
- `/api/preview/<session>/<token>/<port>/...` is a capability URL. The app is served with a CSP `sandbox` (opaque origin) so it can never act on Dayline's origin, which also means it sends no cookies: that path skips the auth gate and Dayline's CORS middleware on purpose, Dayline answers the app's CORS preflights, and the runner keeps the app's cookies in a per-sandbox jar (`cookies.py`). Previewed apps cannot use `localStorage` or `document.cookie`. See `api/services/mock_preview.py`.
- Apps serve under `$BASE_PATH` (Next `basePath`, Rails `config.ru` `map`); a server with `base_path = false` (the Nest API) is served from `/` and the proxy strips the prefix.
- `[dependencies]` is the allowed list, checked both ways against the pack's lockfile at load. Generated projects must pass `deps.project_problems` (runner `POST /packs/{name}/check`, adapter `check_dependencies`); `create` refuses projects that do not.
- Editor saves are copied into place by a process inside the sandbox (`manager.write_file`), so dev-server file watchers fire under gVisor as well as runc.
- Pins with reasons: `@swc/core` 1.16.2 (later releases unpack a native addon into a writable, executable folder), TypeScript 6 (swc-node cannot load TS 7), Next needs `turbopack: { root: '/' }` (dependencies live in the image), and Minitest 6 no longer autoloads plugins, so the Rails test commands preload `lib/dayline_junit.rb`.
- The in-session assistant reads the dev servers' logs (`get_server_logs`) through `mock_preview.server_logs_reader`; it is offered only when the pack runs servers. In the Workspace the assistant and the preview share the right side: both open on 2xl screens, otherwise the one opened last.
- Per-pack `ignore` keeps build output and databases (`.next`, Rails `tmp`/`log`/`storage`) out of the file tree and snapshots; per-pack `memory` raises the sandbox limit (next-nest: 1.5 GiB). VM sizing for these packs is in `deploy/sandbox-vm/README.md`.

## Generated full-stack rounds (Mock tab)

The candidate describes a round (plus optional text context files) and Dayline generates a Rails or Next.js + NestJS project, validates it in a real sandbox, and lets them preview it before starting an AI-assisted staged round in it (stage 1 = the task, stage 2 = the change request).

- `mock/project_spec.py` (inputs, the `Artifact`, the rules code enforces), `mock/project_gen.py` (the model writes on top of the `notes-board-*` template scaffold via `submit_project`, then fixes via `revise_project`; at most `MAX_REPAIRS` repairs), `mock/project_check.py` (deps, boot + preview, visible tests, each stage's hidden tests fail before and pass after its reference). Nothing unvalidated is ever handed over. Model: `MOCK_GENERATOR_MODEL` (default `claude-sonnet-5-5`).
- Projects live in `mock_generated_projects` (migration 015), per owner (the signed-in email). A round started from one is an ordinary staged session whose `staged_problem_id` is the project id, so always resolve problems through `api/services/staged_problems.find_problem`, never `builtin_staged_problems()` directly.
- Generated stages match JUnit cases by the `(classname, name)` pairs validation recorded (`Stage.cases`): Vitest and Minitest classnames are not pytest module names.
- Generation runs in a worker thread (`api/services/mock_generate.py`) and keeps its state on the row (progress, attempt log, token usage). The client follows it with a long poll, which also keeps a scale-to-zero host's CPU allocated; a row untouched for `STALE_AFTER` reads as failed. One generation per user at a time.
- Validation and preview sandboxes count against the runner's `SANDBOX_MAX_RUNNING`; starting a round destroys the project's preview sandbox (`gen-<id>`) first.
- Docker tests: `RUN_DOCKER_TESTS=1 uv run pytest tests/test_project_gen_docker.py` (fixture projects in `tests/generated_projects/`); add `RUN_MODEL_TESTS=1` for the real-model `tests/test_project_gen_model.py`.
