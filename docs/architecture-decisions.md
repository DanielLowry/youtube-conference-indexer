# YouTube Extractor - Architecture Decisions

This document captures the key architecture decisions behind the current
stateless extraction direction. It is intended as a living reference for future
changes, not a one-time plan artifact.

## 1) Problem framing

The original app grew around a database-centric workflow (sync, search, curation,
export). The current target is different:
- extract metadata by playlist/channel/search
- keep UI continuity where useful
- avoid persistence complexity unless it is required
- keep logic easy to call from Python and easy to expose in UI later

That shift drives the decisions below.

## 2) Decision: keep the existing UI baseline

Decision:
- Keep the existing FastAPI + HTMX shell and user flow wherever possible.
- Remove DB-specific controls/features, but do not rewrite UI from scratch.

Why:
- Preserves user familiarity and avoids unnecessary frontend churn.
- Lets us migrate backend behavior incrementally while keeping the app usable.

Tradeoff:
- Some route/template structure reflects earlier DB assumptions and will need
  gradual cleanup rather than a clean-slate redesign.

## 3) Decision: service-first architecture with explicit contracts

Decision:
- New extraction behavior is implemented in Python services first.
- Adapters (CLI/UI) call the same service API:
  - `run_extraction(config: RunConfig) -> RunResult`
  - `resume_extraction(run_id: str) -> RunResult`

Why:
- Prevents logic drift between web and CLI paths.
- Makes feature development testable without HTTP.
- Keeps future UI integration low-friction.

Concrete implementation:
- `app/services/contracts.py` defines:
  - `RunConfig` (input contract)
  - `VideoRecord` (normalized record shape)
  - `RunResult` and `RunProgress` (output/progress contract)

## 4) Decision: no runtime database dependency

Decision:
- Replace DB writes with filesystem outputs and run-state files.
- Do not require SQLAlchemy/Alembic/SQLite at runtime for extraction.

Why:
- Matches the current requirement: extraction over curation/state management.
- Reduces operational complexity and avoids migration overhead.

Tradeoff:
- We lose DB features (FTS, relational joins, persistent curation tables) unless
  intentionally reintroduced later.

## 5) Decision: file outputs and sink abstraction

Decision:
- Required output formats are `jsonl` and `csv`.
- Use sink abstractions so extractors are format-agnostic.

Why:
- JSONL is streaming-friendly and robust for large runs.
- CSV is convenient for spreadsheets and quick analysis.
- Sink abstraction allows adding formats without changing extraction logic.

Concrete implementation:
- `app/services/sinks.py`:
  - `JsonlSink`
  - `CsvSink`
  - `MultiSink`
  - `create_sinks(...)`

## 6) Decision: run state in JSON files

Decision:
- Persist progress and checkpoints in run directories under `./runs/<run_id>/`.
- Each run stores:
  - `videos.jsonl`
  - `videos.csv`
  - `run_state.json`
  - `summary.json`

Why:
- Enables resume/recovery without a database.
- Keeps run artifacts inspectable with normal tooling.

Concrete implementation:
- `app/services/run_state.py` (`RunStateStore`) handles initialization,
  checkpoint writes, summary writes, and checkpoint loads.

## 7) Decision: dedupe scope is per run

Decision:
- Dedupe by `video_id` within a single run (not globally across runs).

Why:
- Matches extraction-first requirements.
- Avoids introducing global state or cross-run index structures.

Tradeoff:
- The same video can appear in separate runs by design.

## 8) Decision: bounded search and quota safety

Decision:
- Search is bounded by default and hard-capped:
  - `max_pages` default 10
  - hard cap 50
  - `stop_after_empty_pages` default 2

Why:
- `search.list` is quota-expensive; bounding prevents runaway usage.
- Keeps extraction predictable for users and tests.

Tradeoff:
- "Complete coverage" for broad queries is not guaranteed.

## 9) Decision: resume is best-effort

Decision:
- Resume uses persisted `next_page_token` and checkpoint counters.
- If token behavior changes upstream, run may need restart semantics.

Why:
- YouTube pagination tokens are not guaranteed to remain valid indefinitely.
- Best-effort resume is the practical middle ground without hidden state.

## 10) Decision: phased parity (search first, then playlist/channel)

Decision:
- Phase 2 implements the stateless core and search path first.
- Playlist/channel are completed in parity phase.

Why:
- Search path exercises the most critical mechanics (pagination, batching,
  dedupe, checkpoints, sinks), so it de-risks the architecture early.

## 11) Testing posture

Decision:
- Prioritize service-level tests with mocked YouTube calls and real filesystem IO
  in temporary directories.

Why:
- Validates core behavior without depending on network or full HTTP stacks.
- Keeps failures local to business logic and I/O concerns.

Current note:
- Stateless contract/core/routes/CLI tests are green.

## 12) Revisit triggers

Revisit these decisions if any of the following become true:
- Need persistent curation and cross-run querying again.
- Need global dedupe or historical indexing across runs.
- Need richer scheduling/queueing than in-process orchestration.
- Need stronger resume guarantees than token-based best effort.
