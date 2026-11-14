"""Runner settings, read once from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# sandbox/runner/src/dayline_runner/config.py -> sandbox/packs
_DEFAULT_PACKS_DIR = Path(__file__).resolve().parents[3] / "packs"


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


# Not slots: from_env reads the field defaults off the class.
@dataclass(frozen=True)
class Settings:
    # Shared with the Dayline API; every request must carry it.
    secret: str
    packs_dir: Path = _DEFAULT_PACKS_DIR
    # A sandbox nobody has touched for this long is stopped (not deleted).
    idle_timeout_s: int = 15 * 60
    # No sandbox runs longer than this, active or not.
    hard_cap_s: int = 90 * 60
    # Stopped sandboxes (and their files) are deleted after this long.
    retain_s: int = 24 * 60 * 60
    max_running: int = 2
    cpus: float = 1.0
    memory: str = "1g"
    pids_limit: int = 256
    # An alternative OCI runtime such as "runsc" (gVisor) for stronger isolation.
    runtime: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        secret = os.environ.get("SANDBOX_RUNNER_SECRET", "").strip()
        if len(secret) < 32:
            raise RuntimeError(
                "SANDBOX_RUNNER_SECRET must be set to a random string of at least 32 "
                "characters (the same value the Dayline API uses)."
            )
        packs_dir = os.environ.get("SANDBOX_PACKS_DIR", "").strip()
        return cls(
            secret=secret,
            packs_dir=Path(packs_dir) if packs_dir else _DEFAULT_PACKS_DIR,
            idle_timeout_s=_int("SANDBOX_IDLE_TIMEOUT_S", cls.idle_timeout_s),
            hard_cap_s=_int("SANDBOX_HARD_CAP_S", cls.hard_cap_s),
            retain_s=_int("SANDBOX_RETAIN_S", cls.retain_s),
            max_running=_int("SANDBOX_MAX_RUNNING", cls.max_running),
            runtime=os.environ.get("SANDBOX_RUNTIME", "").strip() or None,
        )
