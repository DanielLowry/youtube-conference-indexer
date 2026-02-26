"""Minimal in-memory application state for stateless routes."""

# API-key status is shared across requests for lightweight UI feedback.
api_key_status_message: str | None = None
api_key_validation_ok: bool | None = None
