"""day-planner: a personal planning agent that time-blocks a daily task list.

The package is layered so credentials are never required to build or test a plan:

- ``models``          - typed domain objects (dependency-free).
- ``planner.core``    - a pure, deterministic ``build_plan`` (dependency-free).
- ``adapters``        - ``TaskSource`` / ``CalendarClient`` interfaces plus
                        in-memory fakes; real Notion/Google impls drop in later.
- ``scheduler.run``   - wires source + calendar + core together with idempotent
                        write-back (stands in for the future morning cron).
- ``ui.streamlit_app``- a thin interactive surface over the same core/scheduler.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
