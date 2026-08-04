"""
src/shared/enums.py

Enumerations shared across domains. Kept small and explicit for the demo;
each value maps to a real-world concept a clinician/biller would recognize.
"""
from __future__ import annotations

from enum import Enum


class TriageLevel(str, Enum):
    ROUTINE = "routine"
    URGENT = "urgent"
    EMERGENT = "emergent"          # red-flag -> immediate human


class ConsentStatus(str, Enum):
    NOT_STARTED = "not_started"
    PRESENTED = "presented"
    SIGNED = "signed"
    DECLINED = "declined"


class Automation(str, Enum):
    FULL = "full"                 # green
    PARTIAL = "partial"           # amber
    MANUAL = "manual"             # red (human gate)


class GateStatus(str, Enum):
    AWAITING = "awaiting"         # paused, needs a human decision
    APPROVED = "approved"
    REJECTED = "rejected"


class PipelineStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    AWAITING_HUMAN = "awaiting_human"
    FAILED = "failed"


class Severity(str, Enum):
    NONE = "none"
    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"
    CONTRAINDICATED = "contraindicated"


class DrugSchedule(str, Enum):
    NON_CONTROLLED = "non_controlled"
    CII = "CII"
    CIII = "CIII"
    CIV = "CIV"
    CV = "CV"
