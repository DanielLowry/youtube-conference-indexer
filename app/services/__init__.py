"""Service layer package exports.

Purpose:
- Provide stable import points for shared service contracts.
- Keep adapter code (routes/CLI) decoupled from internal file layout by
  re-exporting core types from a single module namespace.

Implementation details:
- Re-exports are intentionally explicit so static analysis and IDE tooling
can discover available contract types without scanning submodules.
"""

from .contracts import (  # noqa: F401
    ExtractionMode,
    OutputFormat,
    RunConfig,
    RunProgress,
    RunResult,
    RunStatus,
    VideoRecord,
)
from .extractors import resume_extraction, run_extraction  # noqa: F401
from .run_state import RunStateStore  # noqa: F401
