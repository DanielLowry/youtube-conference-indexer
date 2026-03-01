"""CLI adapter for stateless extraction services.

Purpose:
- Provide a direct command-line entry point for extraction runs and resumes.
- Reuse the same service contracts and business logic as the FastAPI UI.
- Keep operator workflows script-friendly without introducing a database layer.

Implementation details:
- This module is an adapter only; extraction logic remains in
  `app.services.extractors`.
- `run` builds a validated `RunConfig` and calls `run_extraction(...)`.
- `resume` calls `resume_extraction(...)` from persisted run-state files.
- Results are printed as formatted JSON for shell automation and inspection.
"""

import argparse
import datetime
import json
import sys

from .services.contracts import ExtractionMode, OutputFormat, RunConfig
from .services.extractors import resume_extraction, run_extraction


def _parse_optional_datetime(value: str | None) -> datetime.datetime | None:
    """Parse an optional ISO timestamp into a UTC-aware datetime.

    The CLI accepts either timezone-aware values or naive values. Naive inputs
    are interpreted as UTC for consistency with UI behavior.
    """
    if not value:
        return None
    parsed = datetime.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def _build_run_parser(subparsers) -> None:
    """Define CLI arguments for the `run` command."""
    run_parser = subparsers.add_parser("run", help="Start a new extraction run")
    run_parser.add_argument("--mode", required=True, choices=[mode.value for mode in ExtractionMode])
    run_parser.add_argument("--run-id")
    run_parser.add_argument("--output-root", default="./runs")
    run_parser.add_argument(
        "--output-format",
        action="append",
        choices=[fmt.value for fmt in OutputFormat],
        help="Repeat for multiple outputs, e.g. --output-format jsonl --output-format csv",
    )

    # Source selectors
    run_parser.add_argument(
        "--playlist-id",
        action="append",
        help="Repeat for multiple playlists, e.g. --playlist-id PL1 --playlist-id PL2",
    )
    run_parser.add_argument("--channel-id")
    run_parser.add_argument(
        "--query",
        action="append",
        help="Repeat for multiple search inputs, e.g. --query 'cppcon allocator' --query 'cppnow pmr'",
    )

    # Common controls
    run_parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Maximum pages per query (search) or per playlist (playlist/channel)",
    )
    run_parser.add_argument("--stop-after-empty-pages", type=int, default=2)
    run_parser.add_argument("--no-dedupe-within-run", action="store_true")

    # Optional search filters
    run_parser.add_argument("--published-after")
    run_parser.add_argument("--published-before")
    run_parser.add_argument("--video-duration", choices=["any", "short", "medium", "long"], default="any")
    run_parser.add_argument(
        "--order-by",
        choices=["relevance", "date", "viewCount", "rating"],
        default="relevance",
    )
    run_parser.add_argument("--region-code")
    run_parser.add_argument("--relevance-language")
    run_parser.add_argument("--safe-search", choices=["none", "moderate", "strict"])


def _build_resume_parser(subparsers) -> None:
    """Define CLI arguments for the `resume` command."""
    resume_parser = subparsers.add_parser("resume", help="Resume a run from run_state.json")
    resume_parser.add_argument("run_id")
    resume_parser.add_argument("--output-root", default="./runs")


def _config_from_args(args) -> RunConfig:
    """Convert parsed CLI args into a validated run configuration.

    Validation and mode-specific requirements are enforced by `RunConfig`.
    """
    output_formats = args.output_format or [OutputFormat.JSONL.value, OutputFormat.CSV.value]
    playlist_ids = args.playlist_id or []
    queries = args.query or []
    return RunConfig(
        mode=ExtractionMode(args.mode),
        run_id=args.run_id,
        output_root=args.output_root,
        output_formats=[OutputFormat(fmt) for fmt in output_formats],
        playlist_id=playlist_ids[0] if playlist_ids else None,
        playlist_ids=playlist_ids,
        channel_id=args.channel_id,
        query=queries[0] if queries else None,
        queries=queries,
        dedupe_within_run=not args.no_dedupe_within_run,
        max_pages=args.max_pages,
        stop_after_empty_pages=args.stop_after_empty_pages,
        published_after=_parse_optional_datetime(args.published_after),
        published_before=_parse_optional_datetime(args.published_before),
        video_duration=args.video_duration,
        order_by=args.order_by,
        region_code=args.region_code,
        relevance_language=args.relevance_language,
        safe_search=args.safe_search,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint returning process exit code."""
    parser = argparse.ArgumentParser(description="YouTube stateless metadata extractor")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _build_run_parser(subparsers)
    _build_resume_parser(subparsers)

    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            config = _config_from_args(args)
            result = run_extraction(config)
        else:
            result = resume_extraction(run_id=args.run_id, output_root=args.output_root)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
