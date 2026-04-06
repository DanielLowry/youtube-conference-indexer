"""Filesystem-backed YouTube API key registry and quota estimates.

Purpose:
- Persist multiple YouTube API keys outside process memory.
- Track app-estimated quota usage per key and per YouTube quota day.
- Keep lightweight metadata needed by the API-keys dashboard.

Implementation details:
- Registry data is stored as JSON under `data/` by default.
- Usage buckets are keyed by the YouTube daily quota reset timezone
  (`America/Los_Angeles`) so "today" matches the upstream quota window.
- The store is intentionally small and lock-based; it is sufficient for the
  in-process FastAPI/background-thread model used by this app.
"""

from __future__ import annotations

import datetime
import json
import secrets
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field


YOUTUBE_QUOTA_TIMEZONE = ZoneInfo("America/Los_Angeles")


class DailyQuotaUsage(BaseModel):
    """Estimated successful API usage for one YouTube quota day."""

    quota_units: int = 0
    request_count: int = 0
    operations: dict[str, int] = Field(default_factory=dict)
    last_used_at: datetime.datetime | None = None

    model_config = ConfigDict(extra="forbid")


class ApiKeyRecord(BaseModel):
    """One persisted YouTube API key and its lightweight operational metadata."""

    id: str
    label: str
    api_key: str
    is_primary: bool = False
    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    updated_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    last_validated_at: datetime.datetime | None = None
    validation_ok: bool | None = None
    validation_message: str | None = None
    last_used_at: datetime.datetime | None = None
    last_quota_error_at: datetime.datetime | None = None
    quota_error_message: str | None = None
    quota_exhausted_on: str | None = None
    usage_by_day: dict[str, DailyQuotaUsage] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class ApiKeyRegistry(BaseModel):
    """Serialized registry payload written to disk."""

    version: int = 1
    keys: list[ApiKeyRecord] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


def quota_day_token(at: datetime.datetime | None = None) -> str:
    """Return the YouTube quota-day token in `YYYY-MM-DD` form."""
    value = at or datetime.datetime.now(datetime.UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.UTC)
    return value.astimezone(YOUTUBE_QUOTA_TIMEZONE).strftime("%Y-%m-%d")


def mask_api_key(value: str) -> str:
    """Return a short masked representation safe for UI display."""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


class ApiKeyStore:
    """Small JSON-backed store for API key metadata and quota estimates."""

    def __init__(self, path: str = "data/api_keys.json"):
        self.path = Path(path)
        self._lock = threading.Lock()

    def ensure_seed_key(self, api_key: str, label: str = "Imported from .env") -> ApiKeyRecord | None:
        """Seed the registry from the legacy env var only when empty."""
        normalized_key = api_key.strip()
        if not normalized_key or "your_api_key_here" in normalized_key:
            return None
        with self._lock:
            registry = self._load_unlocked()
            if registry.keys:
                return None
            record = self._build_record(
                api_key=normalized_key,
                label=label,
                is_primary=True,
            )
            registry.keys.append(record)
            self._save_unlocked(_normalize_registry(registry))
            return record.model_copy(deep=True)

    def list_keys(self) -> list[ApiKeyRecord]:
        """Return all keys ordered with the primary key first."""
        with self._lock:
            registry = _normalize_registry(self._load_unlocked())
            return [item.model_copy(deep=True) for item in _ordered_keys(registry.keys)]

    def get_key(self, key_id: str) -> ApiKeyRecord | None:
        """Return one key by id if present."""
        with self._lock:
            registry = self._load_unlocked()
            record = _find_key(registry, key_id=key_id)
            return record.model_copy(deep=True) if record else None

    def get_primary_key(self) -> ApiKeyRecord | None:
        """Return the persisted primary key, if any."""
        with self._lock:
            registry = _normalize_registry(self._load_unlocked())
            for item in registry.keys:
                if item.is_primary:
                    return item.model_copy(deep=True)
            return None

    def upsert_key(self, api_key: str, label: str | None = None, make_primary: bool = False) -> ApiKeyRecord:
        """Insert a new key or update label/primary flag for an existing one."""
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("API key is required")
        with self._lock:
            registry = self._load_unlocked()
            existing = _find_key(registry, api_key=normalized_key)
            now = datetime.datetime.now(datetime.UTC)
            if existing:
                if label and label.strip():
                    existing.label = label.strip()
                existing.updated_at = now
                if make_primary:
                    _set_primary_in_registry(registry, existing.id)
                registry = _normalize_registry(registry)
                self._save_unlocked(registry)
                refreshed = _find_key(registry, key_id=existing.id)
                assert refreshed is not None  # pragma: no cover - normalized invariant
                return refreshed.model_copy(deep=True)

            record = self._build_record(
                api_key=normalized_key,
                label=(label or "").strip() or f"API key {len(registry.keys) + 1}",
                is_primary=make_primary or not registry.keys,
            )
            registry.keys.append(record)
            registry = _normalize_registry(registry)
            self._save_unlocked(registry)
            stored = _find_key(registry, key_id=record.id)
            assert stored is not None  # pragma: no cover - normalized invariant
            return stored.model_copy(deep=True)

    def set_primary(self, key_id: str) -> ApiKeyRecord:
        """Promote one key to be the configured primary key."""
        with self._lock:
            registry = self._load_unlocked()
            record = _find_key(registry, key_id=key_id)
            if not record:
                raise KeyError(key_id)
            _set_primary_in_registry(registry, key_id)
            registry = _normalize_registry(registry)
            self._save_unlocked(registry)
            stored = _find_key(registry, key_id=key_id)
            assert stored is not None  # pragma: no cover - normalized invariant
            return stored.model_copy(deep=True)

    def delete_key(self, key_id: str) -> bool:
        """Delete one key and normalize the remaining primary flag if needed."""
        with self._lock:
            registry = self._load_unlocked()
            original_count = len(registry.keys)
            registry.keys = [item for item in registry.keys if item.id != key_id]
            if len(registry.keys) == original_count:
                return False
            registry = _normalize_registry(registry)
            self._save_unlocked(registry)
            return True

    def record_validation(self, key_id: str, ok: bool, message: str) -> None:
        """Persist the latest validation result for one key."""
        with self._lock:
            registry = self._load_unlocked()
            record = _find_key(registry, key_id=key_id)
            if not record:
                return
            now = datetime.datetime.now(datetime.UTC)
            record.last_validated_at = now
            record.validation_ok = ok
            record.validation_message = message
            record.updated_at = now
            self._save_unlocked(registry)

    def record_usage(self, key_id: str, quota_units: int, operation_name: str) -> None:
        """Add estimated successful usage for the active YouTube quota day."""
        with self._lock:
            registry = self._load_unlocked()
            record = _find_key(registry, key_id=key_id)
            if not record:
                return
            now = datetime.datetime.now(datetime.UTC)
            day = quota_day_token(now)
            usage = record.usage_by_day.get(day, DailyQuotaUsage())
            usage.quota_units += quota_units
            usage.request_count += 1
            usage.operations[operation_name] = usage.operations.get(operation_name, 0) + 1
            usage.last_used_at = now
            record.usage_by_day[day] = usage
            record.last_used_at = now
            if record.quota_exhausted_on == day:
                record.quota_exhausted_on = None
                record.quota_error_message = None
            record.updated_at = now
            self._save_unlocked(registry)

    def mark_quota_exhausted(self, key_id: str, message: str) -> None:
        """Mark a key exhausted for the current YouTube quota day."""
        with self._lock:
            registry = self._load_unlocked()
            record = _find_key(registry, key_id=key_id)
            if not record:
                return
            now = datetime.datetime.now(datetime.UTC)
            record.last_quota_error_at = now
            record.quota_error_message = message
            record.quota_exhausted_on = quota_day_token(now)
            record.updated_at = now
            self._save_unlocked(registry)

    def has_any_key(self) -> bool:
        """Return whether the registry contains at least one key."""
        return bool(self.list_keys())

    def has_usable_key(self) -> bool:
        """Return whether at least one key is currently usable."""
        return bool(self.get_candidate_keys())

    def get_candidate_keys(self) -> list[ApiKeyRecord]:
        """Return runtime candidates ordered for request execution.

        Ordering rules:
        - primary first
        - skip keys already marked quota-exhausted for the current quota day
        - skip keys with a known failed validation result
        """
        today = quota_day_token()
        with self._lock:
            registry = _normalize_registry(self._load_unlocked())
            ordered = _ordered_keys(registry.keys)
            usable = [
                item for item in ordered
                if item.quota_exhausted_on != today and item.validation_ok is not False
            ]
            return [item.model_copy(deep=True) for item in usable]

    def dashboard(self, history_days: int = 7) -> dict:
        """Build a UI-friendly dashboard payload without exposing raw secrets."""
        today = quota_day_token()
        records = self.list_keys()
        payload = []
        for record in records:
            today_usage = record.usage_by_day.get(today, DailyQuotaUsage())
            total_quota_units = sum(day.quota_units for day in record.usage_by_day.values())
            total_request_count = sum(day.request_count for day in record.usage_by_day.values())
            recent_days = []
            for day_token in sorted(record.usage_by_day.keys(), reverse=True)[:history_days]:
                usage = record.usage_by_day[day_token]
                recent_days.append(
                    {
                        "day": day_token,
                        "quota_units": usage.quota_units,
                        "request_count": usage.request_count,
                        "operations": dict(sorted(usage.operations.items())),
                    }
                )
            payload.append(
                {
                    "id": record.id,
                    "label": record.label,
                    "masked_key": mask_api_key(record.api_key),
                    "is_primary": record.is_primary,
                    "validation_ok": record.validation_ok,
                    "validation_message": record.validation_message,
                    "last_validated_at": record.last_validated_at,
                    "last_used_at": record.last_used_at,
                    "today_quota_units": today_usage.quota_units,
                    "today_request_count": today_usage.request_count,
                    "total_quota_units": total_quota_units,
                    "total_request_count": total_request_count,
                    "quota_exhausted_today": record.quota_exhausted_on == today,
                    "quota_error_message": record.quota_error_message if record.quota_exhausted_on == today else None,
                    "last_quota_error_at": record.last_quota_error_at if record.quota_exhausted_on == today else None,
                    "recent_days": recent_days,
                }
            )
        return {
            "quota_day": today,
            "quota_timezone_label": "America/Los_Angeles",
            "keys": payload,
            "has_any_key": bool(records),
            "has_usable_key": self.has_usable_key(),
        }

    def _build_record(self, api_key: str, label: str, is_primary: bool) -> ApiKeyRecord:
        now = datetime.datetime.now(datetime.UTC)
        return ApiKeyRecord(
            id=secrets.token_hex(8),
            label=label,
            api_key=api_key,
            is_primary=is_primary,
            created_at=now,
            updated_at=now,
        )

    def _load_unlocked(self) -> ApiKeyRegistry:
        if not self.path.exists():
            return ApiKeyRegistry()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return _normalize_registry(ApiKeyRegistry.model_validate(payload))

    def _save_unlocked(self, registry: ApiKeyRegistry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(registry.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _find_key(
    registry: ApiKeyRegistry,
    key_id: str | None = None,
    api_key: str | None = None,
) -> ApiKeyRecord | None:
    for item in registry.keys:
        if key_id is not None and item.id == key_id:
            return item
        if api_key is not None and item.api_key == api_key:
            return item
    return None


def _ordered_keys(keys: list[ApiKeyRecord]) -> list[ApiKeyRecord]:
    return sorted(
        keys,
        key=lambda item: (
            0 if item.is_primary else 1,
            item.created_at,
            item.id,
        ),
    )


def _set_primary_in_registry(registry: ApiKeyRegistry, key_id: str) -> None:
    for item in registry.keys:
        item.is_primary = item.id == key_id
        item.updated_at = datetime.datetime.now(datetime.UTC)


def _normalize_registry(registry: ApiKeyRegistry) -> ApiKeyRegistry:
    if not registry.keys:
        return registry
    ordered = _ordered_keys(registry.keys)
    primary_seen = False
    for item in ordered:
        if item.is_primary and not primary_seen:
            primary_seen = True
            continue
        item.is_primary = False
    if not primary_seen:
        ordered[0].is_primary = True
    registry.keys = ordered
    return registry
