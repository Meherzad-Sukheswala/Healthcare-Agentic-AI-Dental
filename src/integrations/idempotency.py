"""
src/integrations/idempotency.py

Encounter-scoped idempotency for the service adapters.

WHY THIS EXISTS
---------------
The encounter pipeline replays from the start on every human-gate resume. The LLM
client already caches responses so replays don't re-call the model — but nothing
protected the EXTERNAL adapters. Measured on a single 6-gate encounter, one run
produced 6 calendar bookings, 3 claim submissions, 3 clinical-note writes, 2 card
charges and 2 prescription transmissions. Against live vendors that is a
double-charged patient, duplicate claims (a compliance problem, not just noise),
and duplicate Rx transmission.

HOW IT WORKS
------------
Two mechanisms, both keyed by encounter id:

1. MUTATING calls (`book`, `charge`, `submit_claim`, `sign`, ...) are recorded in a
   ledger the first time they run. A replay with the same arguments returns the
   STORED RECEIPT instead of calling the vendor again. This is precisely the
   idempotency-key pattern Stripe and Surescripts expose, applied at the port
   boundary so no agent code changes.

2. VOLATILE READS whose result is changed by our own writes (`schedule.availability`)
   are snapshotted per encounter. Without this, availability shifts between passes:
   the slot the patient chose from position 0 is booked, so on replay position 0 is
   a DIFFERENT slot. That silently moved a real booking from Thu 09:00 to Fri 17:00
   across five replays. Freezing the read means the menu the patient chose from is
   the menu they get.

The encounter id travels via a ContextVar so adapter signatures stay untouched. If
no encounter is bound (direct unit-test use of an adapter), both mechanisms are
inert and calls pass straight through.
"""
from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar
from typing import Any

from src.logging_setup import get_logger

log = get_logger(__name__)

_current_encounter: ContextVar[str] = ContextVar("current_encounter", default="")

# Calls that change state, cost money, or consume inventory. Replaying any of these
# against a live vendor is a real-world incident, so each runs at most once per
# encounter per distinct payload.
MUTATING_METHODS: dict[str, frozenset[str]] = {
    "schedule": frozenset({"book"}),
    "payment": frozenset({"charge", "refund"}),
    "claims": frozenset({"submit_claim"}),
    "prior_auth": frozenset({"submit"}),
    "pharmacy": frozenset({"send_prescription", "dispatch"}),
    "epcs": frozenset({"sign"}),
    "ehr": frozenset({"write_clinical_note"}),
}

# Reads whose answer our own writes perturb, so they must be stable within an
# encounter. Pure reference lookups (directory, eligibility, drug interactions)
# are NOT listed: they're already stable, and freezing them would mask real changes.
STABLE_READS: dict[str, frozenset[str]] = {
    "schedule": frozenset({"availability"}),
}


def bind_encounter(encounter_id: str) -> Any:
    """Bind the encounter whose side effects should be deduplicated.

    Returns the ContextVar token so the caller can reset it if desired.
    """
    return _current_encounter.set(encounter_id or "")


def current_encounter() -> str:
    return _current_encounter.get()


def _fingerprint(service: str, method: str, args: tuple, kwargs: dict) -> str:
    try:
        payload = json.dumps([args, sorted(kwargs.items())], sort_keys=True, default=repr)
    except (TypeError, ValueError):
        payload = repr((args, sorted(kwargs.items())))
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"{service}.{method}|{digest}"


class SideEffectLedger:
    """Per-encounter record of external calls already made, and their results."""

    # Bound so a long-lived process can't grow without limit.
    _MAX_ENCOUNTERS = 512

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}
        self.replay_suppressed = 0        # observability: side effects prevented

    def _bucket(self, encounter_id: str) -> dict[str, Any]:
        if encounter_id not in self._entries and len(self._entries) >= self._MAX_ENCOUNTERS:
            self._entries.clear()
        return self._entries.setdefault(encounter_id, {})

    def has(self, encounter_id: str, key: str) -> bool:
        return key in self._entries.get(encounter_id, {})

    def get(self, encounter_id: str, key: str) -> Any:
        return self._entries.get(encounter_id, {})[key]

    def put(self, encounter_id: str, key: str, value: Any) -> None:
        self._bucket(encounter_id)[key] = value

    def receipts(self, encounter_id: str) -> dict[str, Any]:
        """The external calls actually made for this encounter — an audit trail."""
        return dict(self._entries.get(encounter_id, {}))

    def forget(self, encounter_id: str) -> None:
        self._entries.pop(encounter_id, None)


class IdempotentService:
    """Transparent proxy that routes designated methods through the ledger."""

    # Marker used instead of isinstance(), because __class__ is forwarded below.
    _is_idempotent_proxy = True

    def __init__(self, service: Any, name: str, ledger: SideEffectLedger):
        self._service = service
        self._name = name
        self._ledger = ledger
        self._mutating = MUTATING_METHODS.get(name, frozenset())
        self._stable = STABLE_READS.get(name, frozenset())

    @property
    def __class__(self):
        """Masquerade as the wrapped adapter.

        Keeps the proxy invisible to `isinstance()` and `type(x).__name__` checks, so
        wrapping does not change how callers introspect the registry.
        """
        return self._service.__class__

    def __repr__(self) -> str:
        return f"<IdempotentService {self._name} wrapping {self._service!r}>"

    def unwrap(self) -> Any:
        """The underlying adapter, bypassing the ledger."""
        return self._service

    def __getattr__(self, item: str) -> Any:
        target = getattr(self._service, item)
        if item not in self._mutating and item not in self._stable:
            return target

        kind = "mutating" if item in self._mutating else "stable_read"

        async def guarded(*args, **kwargs):
            enc = current_encounter()
            if not enc:                       # unbound (direct adapter use) — passthrough
                return await target(*args, **kwargs)
            key = _fingerprint(self._name, item, args, kwargs)
            if self._ledger.has(enc, key):
                self._ledger.replay_suppressed += 1
                log.debug("side_effect_replay_suppressed", encounter_id=enc,
                          call=f"{self._name}.{item}", kind=kind)
                return self._ledger.get(enc, key)
            result = await target(*args, **kwargs)
            self._ledger.put(enc, key, result)
            return result

        return guarded


def wrap_registry(registry: Any, ledger: SideEffectLedger | None = None) -> Any:
    """Wrap every guarded service on a ServiceRegistry in place."""
    ledger = ledger or SideEffectLedger()
    for name in set(MUTATING_METHODS) | set(STABLE_READS):
        svc = getattr(registry, name, None)
        if svc is None or getattr(svc, "_is_idempotent_proxy", False):
            continue
        setattr(registry, name, IdempotentService(svc, name, ledger))
    registry.ledger = ledger
    return registry
