"""Run state persistence for stateless extraction.

Purpose:
- Persist extraction progress and metadata to local files instead of a database.
- Provide deterministic, resumable run folders under `./runs/<run_id>/`.
- Keep state format adapter-agnostic so both CLI and FastAPI can read/write it.

Implementation details:
- Each run directory stores:
  - `run_state.json`: full serialized `RunConfig` + `RunResult` + dedupe IDs.
  - `summary.json`: compact summary for quick inspection/UI display.
- `RunStateStore` owns all filesystem interactions and serialization concerns.
- State serialization uses Pydantic `model_dump(mode="json")` to keep datetime
  values JSON-safe and reversible via `model_validate`.
"""

import datetime
import hashlib
import json
from pathlib import Path

from .contracts import RunConfig, RunResult, RunStatus


STATE_FILENAME = "run_state.json"
SUMMARY_FILENAME = "summary.json"


def build_run_id(config: RunConfig) -> str:
    """Build a deterministic-ish run identifier with timestamp + source hash.

    The ID format balances readability and collision resistance:
    - timestamp: helps sort runs chronologically
    - mode token: helps humans inspect run type quickly
    - short hash: avoids path collisions for repeated similar runs
    """
    now_token = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d-%H%M%S")
    if config.mode.value == "search":
        source_token = "|".join(config.resolved_queries)
    elif config.mode.value == "playlist":
        source_token = "|".join(config.resolved_playlist_ids)
    else:
        source_token = config.channel_id or "run"
    source_token = source_token or "run"
    digest = hashlib.sha1(source_token.encode("utf-8")).hexdigest()[:8]
    return f"{now_token}-{config.mode.value}-{digest}"


class RunStateStore:
    """Filesystem-backed run state manager for stateless extraction."""

    def __init__(self, output_root: str = "./runs"):
        self.output_root = Path(output_root)

    def run_dir(self, run_id: str) -> Path:
        """Return the directory path for a run."""
        return self.output_root / run_id

    def state_path(self, run_id: str) -> Path:
        """Return the checkpoint file path for a run."""
        return self.run_dir(run_id) / STATE_FILENAME

    def summary_path(self, run_id: str) -> Path:
        """Return the compact summary file path for a run."""
        return self.run_dir(run_id) / SUMMARY_FILENAME

    def initialize_run(self, config: RunConfig) -> RunResult:
        """Create run directory/files and return a queued run result.

        This method is the canonical run bootstrap point. It creates the output
        directory, computes output file paths from requested formats, writes the
        initial `run_state.json`, and returns a `RunResult`.
        """
        run_id = config.run_id or build_run_id(config)
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        output_files = _output_files_for_formats(run_dir, config.output_formats)
        result = RunResult(
            run_id=run_id,
            mode=config.mode,
            status=RunStatus.QUEUED,
            output_dir=str(run_dir.resolve()),
            output_files=output_files,
        )
        self.write_state(config=config, result=result, seen_ids=set())
        self.write_summary(result=result)
        return result

    def load_state(self, run_id: str) -> tuple[RunConfig, RunResult, set[str]]:
        """Load persisted run state and return config/result/dedupe IDs."""
        state_file = self.state_path(run_id)
        payload = json.loads(state_file.read_text(encoding="utf-8"))
        config = RunConfig.model_validate(payload["config"])
        result = RunResult.model_validate(payload["result"])
        seen_ids = set(payload.get("seen_ids", []))
        return config, result, seen_ids

    def write_state(self, config: RunConfig, result: RunResult, seen_ids: set[str]) -> None:
        """Persist full run checkpoint data to `run_state.json`."""
        run_dir = self.run_dir(result.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "config": config.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "seen_ids": sorted(seen_ids),
        }
        self.state_path(result.run_id).write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def write_summary(self, result: RunResult) -> None:
        """Persist a compact summary snapshot for quick inspection."""
        summary = {
            "run_id": result.run_id,
            "mode": result.mode.value,
            "status": result.status.value,
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat() if result.finished_at else None,
            "output_dir": result.output_dir,
            "output_files": result.output_files,
            "progress": result.progress.model_dump(mode="json"),
            "error_message": result.error_message,
        }
        self.summary_path(result.run_id).write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _output_files_for_formats(run_dir: Path, output_formats) -> list[str]:
    """Convert requested output formats into concrete run file paths."""
    paths = []
    seen_formats = set()
    for output_format in output_formats:
        if output_format.value in seen_formats:
            continue
        seen_formats.add(output_format.value)
        paths.append(str((run_dir / f"videos.{output_format.value}").resolve()))
    return paths
