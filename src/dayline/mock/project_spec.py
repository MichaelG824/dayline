"""What a generated practice project is, and the rules it must keep.

The project generator (``mock/project_gen.py``) turns a candidate's prompt
and imported context files into an :class:`Artifact`: a small full-stack app
(the baseline the round starts from), a task, and a change request the
interviewer brings in mid-round. Each of the two has a candidate-facing
prompt, hidden tests, and a reference solution (the files it changes), so
the artifact is a two-stage staged problem (``mock/staged.py``) once it has
been validated in a real sandbox (``mock/project_check.py``).

Everything here is pure: input limits, the artifact and its JSON form, the
constraints code enforces on whatever the model writes, and the conversion
to a :class:`~dayline.mock.staged.StagedProblem`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from dayline.mock.staged import OVERVIEW_FILE, EdgeCase, Stage, StagedProblem
from dayline.models import MockRoundType

# -- the candidate's inputs ------------------------------------------------------

DIFFICULTIES = ("easy", "medium", "hard")
MAX_PROMPT_CHARS = 4000
MAX_FEEDBACK_CHARS = 2000
MIN_DURATION_MIN, MAX_DURATION_MIN = 20, 120
# The change request needs some round left on either side of it.
MIN_CHANGE_GAP_MIN = 5

# Imported context: text only, and small enough to sit in the prompt.
MAX_CONTEXT_FILES = 10
MAX_CONTEXT_FILE_BYTES = 64 * 1024
MAX_CONTEXT_TOTAL_BYTES = 256 * 1024
CONTEXT_EXTENSIONS = frozenset(
    {
        "md", "markdown", "txt", "text", "rst", "adoc", "csv", "tsv", "log",
        "json", "yml", "yaml", "toml", "ini", "cfg", "env", "xml", "html", "htm", "css",
        "scss", "sql", "graphql", "gql", "proto",
        "py", "rb", "erb", "rake", "js", "jsx", "mjs", "cjs", "ts", "tsx", "go", "rs",
        "java", "kt", "kts", "scala", "swift", "c", "h", "cc", "cpp", "hpp", "cs", "php",
        "sh", "bash", "zsh", "lua", "ex", "exs", "dart", "vue", "svelte",
    }
)  # fmt: skip
# Extension-less files people commonly drop in.
CONTEXT_NAMES = frozenset({"readme", "dockerfile", "makefile", "gemfile", "procfile"})


@dataclass(frozen=True, slots=True)
class Stack:
    """A stack a project can be generated for: its sandbox pack and the
    built-in template whose files are the scaffold the model starts from."""

    name: str
    display_name: str
    pack: str
    template: str
    # A hidden test file's name must end with one of these.
    test_suffixes: tuple[str, ...]
    # Dependency lockfiles: never written by the model (the pack's are fixed).
    lockfiles: tuple[str, ...]
    # Where the candidate-facing app code lives (scanned for browser storage).
    source_roots: tuple[str, ...]


STACKS: dict[str, Stack] = {
    "next-nest": Stack(
        name="next-nest",
        display_name="Next.js + NestJS",
        pack="next-nest",
        template="notes-board-next-nest",
        test_suffixes=(".test.ts", ".test.tsx"),
        lockfiles=("package-lock.json",),
        source_roots=("web/", "api/"),
    ),
    "rails": Stack(
        name="rails",
        display_name="Rails",
        pack="rails",
        template="notes-board-rails",
        test_suffixes=("_test.rb",),
        lockfiles=("Gemfile.lock",),
        source_roots=("app/", "config/", "lib/", "public/"),
    ),
}


class RequestError(ValueError):
    """The candidate's input breaks a limit; the message says which."""


@dataclass(frozen=True, slots=True)
class ContextFile:
    name: str
    content: str


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    prompt: str
    stack: str
    difficulty: str
    duration_min: int
    change_request_min: int
    context_files: tuple[ContextFile, ...] = ()
    # Regenerating: what the candidate wants different, and the project being replaced.
    feedback: str = ""
    previous: Artifact | None = None

    def to_json(self) -> dict[str, Any]:
        """The inputs as stored on the project (context files are stored apart)."""
        return {
            "prompt": self.prompt,
            "stack": self.stack,
            "difficulty": self.difficulty,
            "durationMin": self.duration_min,
            "changeRequestMin": self.change_request_min,
            "feedback": self.feedback,
        }


def context_file_problem(name: str, content: str) -> str | None:
    """Why an imported file is refused (``None`` = fine)."""
    base = PurePosixPath(name.replace("\\", "/")).name
    if not base or len(base) > 120:
        return "Context files need a name of at most 120 characters"
    stem, dot, ext = base.rpartition(".")
    known = ext.lower() in CONTEXT_EXTENSIONS if dot and stem else base.lower() in CONTEXT_NAMES
    if not known:
        return f"{base}: only text and code files can be imported"
    if "\x00" in content:
        return f"{base}: this looks like a binary file, not text"
    if len(content.encode()) > MAX_CONTEXT_FILE_BYTES:
        return f"{base}: files must be under {MAX_CONTEXT_FILE_BYTES // 1024} KB"
    return None


def parse_request(
    *,
    prompt: str,
    stack: str,
    difficulty: str,
    duration_min: int,
    change_request_min: int,
    context_files: list[tuple[str, str]],
    feedback: str = "",
    previous: Artifact | None = None,
) -> GenerationRequest:
    """The candidate's input, checked. Raises :class:`RequestError`."""
    prompt = prompt.strip()
    if not prompt:
        raise RequestError("Describe the round first")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise RequestError(f"Keep the description under {MAX_PROMPT_CHARS} characters")
    if stack not in STACKS:
        raise RequestError(f"Pick a stack: {', '.join(STACKS)}")
    if difficulty not in DIFFICULTIES:
        raise RequestError(f"Pick a difficulty: {', '.join(DIFFICULTIES)}")
    if not MIN_DURATION_MIN <= duration_min <= MAX_DURATION_MIN:
        raise RequestError(f"The round must last {MIN_DURATION_MIN} to {MAX_DURATION_MIN} minutes")
    latest = duration_min - MIN_CHANGE_GAP_MIN
    if not MIN_CHANGE_GAP_MIN <= change_request_min <= latest:
        raise RequestError(
            f"The change request must come between minute {MIN_CHANGE_GAP_MIN} and "
            f"minute {latest} of a {duration_min}-minute round"
        )
    if len(context_files) > MAX_CONTEXT_FILES:
        raise RequestError(f"Import at most {MAX_CONTEXT_FILES} context files")
    files = []
    for name, content in context_files:
        if problem := context_file_problem(name, content):
            raise RequestError(problem)
        files.append(ContextFile(PurePosixPath(name.replace("\\", "/")).name, content))
    if sum(len(f.content.encode()) for f in files) > MAX_CONTEXT_TOTAL_BYTES:
        raise RequestError(f"Context files must total under {MAX_CONTEXT_TOTAL_BYTES // 1024} KB")
    feedback = feedback.strip()
    if len(feedback) > MAX_FEEDBACK_CHARS:
        raise RequestError(f"Keep the feedback under {MAX_FEEDBACK_CHARS} characters")
    return GenerationRequest(
        prompt=prompt,
        stack=stack,
        difficulty=difficulty,
        duration_min=duration_min,
        change_request_min=change_request_min,
        context_files=tuple(files),
        feedback=feedback,
        previous=previous,
    )


# -- the artifact ----------------------------------------------------------------------


@dataclass(slots=True)
class EdgeSpec:
    """An edge case a stage's hidden tests check; ``tests`` are test titles
    as the model wrote them until validation maps them to recorded names."""

    id: str
    title: str
    tests: list[str]


@dataclass(slots=True)
class StageSpec:
    """The task (stage 1) or the change request (stage 2)."""

    title: str
    prompt_md: str
    notes_md: str
    target_min: int
    # Hidden test files by their name in the hidden-tests folder.
    tests: dict[str, str]
    # The reference solution: full contents of every file the stage creates
    # or changes, applied on top of the project as it was before the stage.
    reference: dict[str, str]
    edge_cases: list[EdgeSpec] = field(default_factory=list)
    # Recorded by validation: every hidden test case as [classname, name].
    cases: list[list[str]] = field(default_factory=list)


@dataclass(slots=True)
class Artifact:
    stack: str
    title: str
    summary: str
    open_path: str
    # The baseline: every file the sandbox starts with.
    files: dict[str, str]
    task: StageSpec
    change: StageSpec
    analysis_hints: list[str]
    duration_min: int
    change_request_min: int

    @property
    def stages(self) -> tuple[StageSpec, StageSpec]:
        return (self.task, self.change)

    def after(self, stage: int) -> dict[str, str]:
        """The project's files with the references up to ``stage`` applied."""
        files = dict(self.files)
        for spec in self.stages[:stage]:
            files |= spec.reference
        return files

    def to_json(self) -> dict[str, Any]:
        return {
            "stack": self.stack,
            "title": self.title,
            "summary": self.summary,
            "openPath": self.open_path,
            "files": self.files,
            "task": _stage_json(self.task),
            "changeRequest": _stage_json(self.change),
            "analysisHints": self.analysis_hints,
            "durationMin": self.duration_min,
            "changeRequestMin": self.change_request_min,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Artifact:
        return cls(
            stack=str(data["stack"]),
            title=str(data["title"]),
            summary=str(data.get("summary", "")),
            open_path=str(data["openPath"]),
            files=dict(data["files"]),
            task=_stage_from_json(data["task"]),
            change=_stage_from_json(data["changeRequest"]),
            analysis_hints=[str(h) for h in data.get("analysisHints", [])],
            duration_min=int(data["durationMin"]),
            change_request_min=int(data["changeRequestMin"]),
        )


def _stage_json(stage: StageSpec) -> dict[str, Any]:
    return {
        "title": stage.title,
        "promptMd": stage.prompt_md,
        "notesMd": stage.notes_md,
        "targetMin": stage.target_min,
        "tests": stage.tests,
        "reference": stage.reference,
        "edgeCases": [{"id": e.id, "title": e.title, "tests": e.tests} for e in stage.edge_cases],
        "cases": stage.cases,
    }


def _stage_from_json(data: dict[str, Any]) -> StageSpec:
    return StageSpec(
        title=str(data["title"]),
        prompt_md=str(data["promptMd"]),
        notes_md=str(data.get("notesMd", "")),
        target_min=int(data["targetMin"]),
        tests=dict(data["tests"]),
        reference=dict(data["reference"]),
        edge_cases=[
            EdgeSpec(id=str(e["id"]), title=str(e["title"]), tests=[str(t) for t in e["tests"]])
            for e in data.get("edgeCases", [])
        ],
        cases=[[str(c), str(n)] for c, n in data.get("cases", [])],
    )


_SLUGS = ("task", "change-request")


def staged_problem(problem_id: str, artifact: Artifact) -> StagedProblem:
    """The validated artifact as the staged problem a round runs on. The
    reference solutions stay on the artifact: a round never needs them."""
    stages = []
    for number, (spec, slug) in enumerate(zip(artifact.stages, _SLUGS, strict=True), start=1):
        stages.append(
            Stage(
                number=number,
                slug=slug,
                title=spec.title,
                target_min=spec.target_min,
                prompt_md=spec.prompt_md,
                notes_md=spec.notes_md,
                tests=dict(spec.tests),
                edge_cases=tuple(
                    EdgeCase(id=e.id, title=e.title, tests=tuple(e.tests))
                    for e in spec.edge_cases
                    if e.tests
                ),
                cases=frozenset((c, n) for c, n in spec.cases),
                unlock_min=artifact.change_request_min if number == 2 else 0,
            )
        )
    # What the interviewer reads and the design score compares: the files
    # the references touch, as the candidate's work most likely lives there.
    touched = {p for spec in artifact.stages for p in spec.reference}
    return StagedProblem(
        id=problem_id,
        title=artifact.title,
        pack=STACKS[artifact.stack].pack,
        round_type=MockRoundType.AI_ASSISTED_PROJECT,
        duration_min=artifact.duration_min,
        summary=artifact.summary,
        open_path=artifact.open_path,
        solution=tuple(sorted(touched)),
        stages=tuple(stages),
        starter=dict(artifact.files),
        analysis_hints=tuple(artifact.analysis_hints),
    )


# -- the constraints code enforces -------------------------------------------------

MAX_FILES = 80
MAX_FILE_BYTES = 40_000
# "Small enough to read in a few minutes": lines across the baseline, lockfiles aside.
MAX_PROJECT_LINES = 1800
MAX_TEST_FILES = 4
MAX_PROMPT_MD_CHARS = 4000
MAX_HINTS = 8
# Browser storage cannot work in the preview (the app runs in an opaque origin).
_BROWSER_STATE = re.compile(r"\b(localStorage|sessionStorage|indexedDB)\b|document\.cookie")
_TEST_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")
# Folders that never reach the sandbox's file tree (the runner ignores them).
_RESERVED_DIRS = frozenset(
    {".dayline", ".git", "node_modules", ".next", "tmp", "log", "storage", "__pycache__"}
)


def path_problem(path: str) -> str | None:
    """Why ``path`` cannot be a project file (``None`` = fine)."""
    if not path or len(path) > 200 or "\\" in path or "\x00" in path:
        return f"{path!r} is not a valid file path"
    parts = path.split("/")
    if path.startswith("/") or any(p in ("", ".", "..") for p in parts):
        return f"{path!r} must be a relative path without '.' or '..' parts"
    if reserved := _RESERVED_DIRS.intersection(parts[:-1]):
        return f"{path} is inside {sorted(reserved)[0]}/, which the sandbox ignores"
    return None


def hidden_test_problem(stack: Stack, name: str) -> str | None:
    if not _TEST_NAME.match(name) or not name.endswith(stack.test_suffixes):
        return (
            f"Hidden test {name!r} must be a plain file name ending in "
            f"{' or '.join(stack.test_suffixes)}"
        )
    return None


def _lines(files: dict[str, str], stack: Stack) -> int:
    return sum(
        text.count("\n") + 1
        for path, text in files.items()
        if path.rpartition("/")[2] not in stack.lockfiles
    )


def _is_test_path(path: str) -> bool:
    name = path.rpartition("/")[2]
    return path.startswith(("test/", "spec/")) or "/test/" in path or ".test." in name


def static_problems(artifact: Artifact) -> list[str]:
    """Every rule the artifact breaks that code can check without running it."""
    stack = STACKS[artifact.stack]
    problems: list[str] = []
    if not artifact.title.strip():
        problems.append("The project needs a title")
    if OVERVIEW_FILE not in artifact.files:
        problems.append(f"The project needs a {OVERVIEW_FILE} that describes the app")
    if artifact.open_path not in artifact.files:
        problems.append(f"open_path {artifact.open_path!r} is not a project file")
    if len(artifact.files) > MAX_FILES:
        problems.append(f"The project has {len(artifact.files)} files; keep it to {MAX_FILES}")
    lines = _lines(artifact.files, stack)
    if lines > MAX_PROJECT_LINES:
        problems.append(
            f"The baseline is {lines} lines; keep it under {MAX_PROJECT_LINES} so it reads "
            "in a few minutes"
        )
    for number, spec in enumerate(artifact.stages, start=1):
        label = "task" if number == 1 else "change_request"
        if not spec.title.strip() or not spec.prompt_md.strip():
            problems.append(f"The {label} needs a title and a prompt")
        if len(spec.prompt_md) > MAX_PROMPT_MD_CHARS:
            problems.append(f"Keep the {label} prompt under {MAX_PROMPT_MD_CHARS} characters")
        if not spec.tests:
            problems.append(f"The {label} has no hidden tests")
        if len(spec.tests) > MAX_TEST_FILES:
            problems.append(f"The {label} has more than {MAX_TEST_FILES} hidden test files")
        problems += [p for name in spec.tests if (p := hidden_test_problem(stack, name))]
        if not spec.reference:
            problems.append(f"The {label} has no reference solution")
        before = artifact.after(number - 1)
        if spec.reference and all(before.get(p) == c for p, c in spec.reference.items()):
            problems.append(f"The {label} reference changes nothing")
        if spec.target_min <= 0:
            problems.append(f"The {label} needs a positive target_min")
    if overlap := set(artifact.task.tests) & set(artifact.change.tests):
        problems.append(f"Hidden test file names are reused across stages: {sorted(overlap)}")
    if len(artifact.analysis_hints) > MAX_HINTS:
        problems.append(f"Give at most {MAX_HINTS} analysis hints")

    every = {"baseline": artifact.files, **{
        ("task" if n == 1 else "change_request") + " reference": s.reference
        for n, s in enumerate(artifact.stages, start=1)
    }}  # fmt: skip
    for where, files in every.items():
        for path, content in files.items():
            if problem := path_problem(path):
                problems.append(f"{where}: {problem}")
                continue
            if len(content.encode()) > MAX_FILE_BYTES:
                problems.append(f"{where}: {path} is over {MAX_FILE_BYTES // 1000} KB")
            if where != "baseline" and path.rpartition("/")[2] in stack.lockfiles:
                problems.append(f"{where}: {path} is the pack's lockfile; do not write it")
            if (
                path.startswith(stack.source_roots)
                and not _is_test_path(path)
                and _BROWSER_STATE.search(content)
            ):
                problems.append(
                    f"{where}: {path} uses browser storage (localStorage, sessionStorage, "
                    "indexedDB or document.cookie), which the preview blocks; keep state on "
                    "the server"
                )
    return problems
