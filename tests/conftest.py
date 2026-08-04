"""Shared test fixtures / setup."""
import os

# Force the offline, deterministic LLM provider for all tests (no network in CI).
os.environ.setdefault("LLM_PROVIDER", "sandbox")

from src.logging_setup import configure_logging  # noqa: E402

configure_logging(level="WARNING", json_logs=False)
