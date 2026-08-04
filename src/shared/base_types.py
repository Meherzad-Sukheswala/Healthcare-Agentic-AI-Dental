"""
src/shared/base_types.py

Foundational Pydantic types reused by the domain contracts.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    """Timezone-aware UTC now (never naive datetimes)."""
    return datetime.now(timezone.utc)


class HealthcareModel(BaseModel):
    """Base for all domain contracts: strict, immutable-ish, explicit."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Money(HealthcareModel):
    """Currency amount in minor units to avoid float rounding (cents)."""

    cents: int = 0
    currency: str = "USD"

    @property
    def dollars(self) -> float:
        return round(self.cents / 100, 2)

    def __add__(self, other: "Money") -> "Money":
        assert self.currency == other.currency
        return Money(cents=self.cents + other.cents, currency=self.currency)


class CodedConcept(HealthcareModel):
    """A code from a named system (mirrors FHIR Coding)."""

    system: str            # e.g. "ICD-10-CM", "CPT", "RxNorm", "LOINC"
    code: str
    display: str = ""


class PersonName(HealthcareModel):
    first: str
    last: str

    @property
    def full(self) -> str:
        return f"{self.first} {self.last}".strip()
