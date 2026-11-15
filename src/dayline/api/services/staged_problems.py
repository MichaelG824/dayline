"""Where a staged round's problem comes from: a built-in problem folder
(``mock/staged_problems/<id>``) or a generated project stored per user
(``mock/project_spec.py``). Both load as the same
:class:`~dayline.mock.staged.StagedProblem`, so the round, the interviewer,
ending, and grading never need to know which.

A generated project is immutable once ready (deleting one a session uses is
refused), so loaded problems are cached by id.
"""

from __future__ import annotations

import threading

from dayline.api.context import AppContext
from dayline.mock import staged
from dayline.mock.project_spec import Artifact, staged_problem
from dayline.mock.staged import StagedProblem
from dayline.models import GenerationStatus, MockSession

_MAX_CACHED = 32
_cache: dict[str, StagedProblem] = {}
_lock = threading.Lock()


def find_problem(ctx: AppContext, problem_id: str | None) -> StagedProblem | None:
    """The staged problem with this id, built-in or generated and ready."""
    if not problem_id:
        return None
    builtin = staged.builtin_staged_problems().get(problem_id)
    if builtin is not None:
        return builtin
    with _lock:
        cached = _cache.get(problem_id)
    if cached is not None:
        return cached
    try:
        project = ctx.generated_source.get_any(problem_id)
    except KeyError:
        return None
    if project.status is not GenerationStatus.READY or project.artifact is None:
        return None
    problem = staged_problem(project.id, Artifact.from_json(project.artifact))
    with _lock:
        if len(_cache) >= _MAX_CACHED:
            _cache.pop(next(iter(_cache)))
        _cache[problem_id] = problem
    return problem


def session_problem(ctx: AppContext, session: MockSession) -> StagedProblem | None:
    return find_problem(ctx, session.staged_problem_id)


def forget(problem_id: str) -> None:
    """Drop a deleted project from the cache."""
    with _lock:
        _cache.pop(problem_id, None)
