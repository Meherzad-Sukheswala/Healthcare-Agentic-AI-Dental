"""
src/shared/events.py

Domain events emitted through the pipeline. Human-gate events are first-class so
the UI and audit trail can show exactly where/why the pipeline paused for a person.
"""
from __future__ import annotations

from enum import Enum

from pydantic import Field

from .base_types import HealthcareModel, utcnow


class EventType(str, Enum):
    ENCOUNTER_STARTED = "encounter.started"
    DOMAIN_COMPLETED = "domain.completed"
    DOMAIN_FAILED = "domain.failed"
    AGENT_COMPLETED = "agent.completed"
    HUMAN_GATE_OPENED = "human_gate.opened"       # pipeline paused for a person
    HUMAN_GATE_RESOLVED = "human_gate.resolved"   # person approved/rejected
    FRAUD_ASSESSED = "fraud.assessed"
    CRITICAL_VALUE_FLAGGED = "clinical.critical_value"
    ENCOUNTER_COMPLETED = "encounter.completed"


class DomainEvent(HealthcareModel):
    type: EventType
    encounter_id: str = ""
    source: str = ""                       # agent or domain name
    payload: dict = Field(default_factory=dict)
    at: str = Field(default_factory=lambda: utcnow().isoformat())
