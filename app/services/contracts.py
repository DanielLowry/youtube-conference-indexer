"""Shared extraction service contracts.

Purpose:
- Define the canonical data contracts used by the stateless extraction system.
- Provide one source of truth for inputs (`RunConfig`), outputs (`RunResult`),
  and normalized record payloads (`VideoRecord`).
- Ensure both adapters (CLI and FastAPI UI) call the same service interface,
  avoiding duplicated validation logic or UI-specific behavior in the core.

Implementation details:
- Uses Pydantic models to enforce schema validation at construction time.
- Uses strict `extra="forbid"` on all models so unknown fields fail fast.
- Encodes business limits directly in types/validators:
  - hard page cap (`MAX_PAGES_HARD_CAP`)
  - mode-specific required fields
  - date window validity checks
- Keeps defaults aligned with the stateless migration plan:
  - output root under `./runs`
  - required output formats: JSONL + CSV
  - per-run dedupe enabled by default
"""

import datetime
import enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Global hard limit to prevent unbounded search pagination and quota usage.
MAX_PAGES_HARD_CAP = 50


class ExtractionMode(str, enum.Enum):
    """Supported extraction entry points."""

    PLAYLIST = "playlist"
    CHANNEL = "channel"
    SEARCH = "search"


class OutputFormat(str, enum.Enum):
    """Supported persisted output artifacts for each run."""

    JSONL = "jsonl"
    CSV = "csv"
    MARKDOWN = "md"


class RunStatus(str, enum.Enum):
    """Lifecycle states for a run as seen by CLI/UI adapters."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


VideoDuration = Literal["any", "short", "medium", "long"]
OrderBy = Literal["relevance", "date", "viewCount", "rating"]
SafeSearch = Literal["none", "moderate", "strict"]


class RunConfig(BaseModel):
    """Validated run configuration used by both CLI and FastAPI adapters.

    The service layer accepts this model as its canonical input so that
    all invocations (web or CLI) follow identical validation and defaults.
    """

    mode: ExtractionMode
    run_id: str | None = None
    output_root: str = "./runs"
    output_formats: list[OutputFormat] = Field(default_factory=lambda: [OutputFormat.JSONL, OutputFormat.CSV])

    # source selectors
    playlist_id: str | None = None
    channel_id: str | None = None
    query: str | None = None

    # common controls
    dedupe_within_run: bool = True
    max_pages: int = Field(default=10, ge=1, le=MAX_PAGES_HARD_CAP)
    stop_after_empty_pages: int = Field(default=2, ge=1)

    # optional search filters
    published_after: datetime.datetime | None = None
    published_before: datetime.datetime | None = None
    video_duration: VideoDuration = "any"
    order_by: OrderBy = "relevance"
    region_code: str | None = None
    relevance_language: str | None = None
    safe_search: SafeSearch | None = None

    model_config = ConfigDict(extra="forbid")

    @property
    def max_results(self) -> int:
        """Derived result budget based on capped page count.

        Each page can return up to 50 search results. This property provides
        an explicit upper bound that downstream logic can log or enforce.
        """
        return self.max_pages * 50

    @model_validator(mode="after")
    def validate_mode_requirements(self):
        """Enforce mode-specific required fields and filter consistency.

        Rules implemented:
        - `search` mode requires `query`
        - `playlist` mode requires `playlist_id`
        - `channel` mode requires `channel_id`
        - `published_after` must not be later than `published_before`
        """
        if self.mode == ExtractionMode.SEARCH and not self.query:
            raise ValueError("query is required for search mode")
        if self.mode == ExtractionMode.PLAYLIST and not self.playlist_id:
            raise ValueError("playlist_id is required for playlist mode")
        if self.mode == ExtractionMode.CHANNEL and not self.channel_id:
            raise ValueError("channel_id is required for channel mode")
        if self.published_after and self.published_before and self.published_after > self.published_before:
            raise ValueError("published_after must be earlier than published_before")
        return self


class VideoRecord(BaseModel):
    """Normalized metadata payload emitted by extraction services.

    This model is intentionally source-agnostic: the same shape is produced
    for playlist/channel/search extraction so sinks can be shared across modes.
    Source-specific provenance is captured in optional `source_*` fields.
    """

    external_id: str
    title: str | None = None
    description: str | None = None
    published_at: datetime.datetime | None = None
    duration_seconds: int = 0
    channel_id: str | None = None
    channel_title: str | None = None
    source_playlist_id: str | None = None
    source_channel_id: str | None = None
    source_query: str | None = None
    rank_in_run: int | None = None
    page_number: int | None = None
    fetched_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))

    model_config = ConfigDict(extra="forbid")


class RunProgress(BaseModel):
    """Mutable counters and checkpoint values collected during extraction.

    Notes:
    - `next_page_token` tracks the pagination checkpoint for the *current*
      source scan (search page or playlistItems page).
    - Channel mode adds playlist-level checkpoint fields so resume can continue
      from the correct playlist and page token.
    """

    pages_processed: int = 0
    results_seen: int = 0
    new_video_ids: int = 0
    existing_video_ids: int = 0
    videos_fetched: int = 0
    quota_estimate: int = 0
    next_page_token: str | None = None
    total_playlists: int = 0
    processed_playlists: int = 0
    current_playlist_index: int = 0
    current_playlist_id: str | None = None

    model_config = ConfigDict(extra="forbid")


class RunResult(BaseModel):
    """Final or in-progress run state returned by service entry points.

    This model is designed to be serializable for UI polling, CLI output,
    and persisted run-state summaries without relying on a database.
    """

    run_id: str
    mode: ExtractionMode
    status: RunStatus
    output_dir: str
    output_files: list[str] = Field(default_factory=list)
    progress: RunProgress = Field(default_factory=RunProgress)
    started_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    finished_at: datetime.datetime | None = None
    error_message: str | None = None

    model_config = ConfigDict(extra="forbid")
