"""
src/logging_setup.py

Structured logging via structlog. Console renderer in dev, JSON in prod.
Every agent and orchestrator logs through this so the whole encounter is traceable.
"""
from __future__ import annotations

import logging

import structlog

_CONFIGURED = False


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    processors.append(
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str):
    return structlog.get_logger(name)
