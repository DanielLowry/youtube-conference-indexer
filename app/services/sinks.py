"""Output sinks for stateless extraction records.

What is a "sink"?
- A sink is a write target for extracted records.
- The extractor produces normalized `VideoRecord` objects; sinks decide where
  and how those records are persisted (JSONL, CSV, etc.).

Why this pattern is used:
- Separation of concerns:
  - Extractors focus on fetching/normalizing YouTube data.
  - Sinks focus on persistence format and file I/O details.
- Extensibility:
  - New output formats can be added by implementing the `Sink` interface.
  - Existing extractor logic does not need to change for new formats.
- Stateless runtime:
  - This replaces database writes with append-only file outputs.
  - Resume/checkpoint behavior works because sinks can append to existing files.
- Memory safety:
  - Records are streamed one-by-one to disk; no need to hold whole result sets.

Implementation details:
- `JsonlSink` writes one JSON object per line for streaming compatibility.
- `CsvSink` writes a stable column set with a header row and appends rows.
- `MultiSink` fans out each record to multiple concrete sinks in one call.
"""

import csv
import datetime
from pathlib import Path

from .contracts import OutputFormat, VideoRecord


CSV_FIELDNAMES = [
    "external_id",
    "title",
    "description",
    "published_at",
    "duration_seconds",
    "channel_id",
    "channel_title",
    "source_playlist_id",
    "source_channel_id",
    "source_query",
    "rank_in_run",
    "page_number",
    "fetched_at",
]


class Sink:
    """Minimal sink contract used by extractor services.

    Any sink implementation must support:
    - `write_record(record)`: append one normalized record.
    - `close()`: release underlying resources (file handles, buffers, etc.).
    """

    def write_record(self, record: VideoRecord) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class JsonlSink(Sink):
    """Append-only JSON Lines sink for `VideoRecord` payloads.

    JSONL is useful for large runs because each line is independent and can be
    consumed incrementally by downstream tools.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")

    def write_record(self, record: VideoRecord) -> None:
        self._fh.write(record.model_dump_json() + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


class CsvSink(Sink):
    """Append-capable CSV sink with stable headers.

    CSV is convenient for spreadsheets and lightweight analysis workflows.
    This implementation writes headers once and appends new rows on resume.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = self.path.exists() and self.path.stat().st_size > 0
        self._fh = self.path.open("a", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(self._fh, fieldnames=CSV_FIELDNAMES)
        if not file_exists:
            self._writer.writeheader()
            self._fh.flush()

    def write_record(self, record: VideoRecord) -> None:
        self._writer.writerow(_to_csv_row(record))
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


class MultiSink(Sink):
    """Fan-out sink that writes each record to multiple sinks.

    This allows a single extraction pass to produce multiple outputs (for
    example both JSONL and CSV) without duplicating extractor work.
    """

    def __init__(self, sinks: list[Sink]):
        self.sinks = sinks

    def write_record(self, record: VideoRecord) -> None:
        for sink in self.sinks:
            sink.write_record(record)

    def close(self) -> None:
        for sink in self.sinks:
            sink.close()


def create_sinks(output_dir: str, output_formats: list[OutputFormat]) -> MultiSink:
    """Build concrete sinks based on requested formats for a run.

    The returned `MultiSink` is the single object used by the extractor loop.
    Format requests are deduplicated so duplicate format inputs do not create
    duplicate file writers.
    """
    output_path = Path(output_dir)
    sinks: list[Sink] = []
    dedup_formats = list(dict.fromkeys(output_formats))
    for output_format in dedup_formats:
        if output_format == OutputFormat.JSONL:
            sinks.append(JsonlSink(output_path / "videos.jsonl"))
        elif output_format == OutputFormat.CSV:
            sinks.append(CsvSink(output_path / "videos.csv"))
        elif output_format == OutputFormat.MARKDOWN:
            # Markdown sink is deferred to later phase; keep explicit failure.
            raise NotImplementedError("Markdown sink is not implemented yet")
    return MultiSink(sinks)


def _to_csv_row(record: VideoRecord) -> dict:
    """Normalize a `VideoRecord` into a CSV-serializable row payload."""
    payload = record.model_dump(mode="python")
    payload["published_at"] = _to_iso(payload.get("published_at"))
    payload["fetched_at"] = _to_iso(payload.get("fetched_at"))
    return payload


def _to_iso(value):
    """Convert datetime values to ISO strings for CSV output stability."""
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    return value
