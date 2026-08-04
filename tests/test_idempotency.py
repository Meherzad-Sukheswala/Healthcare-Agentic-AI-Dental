"""
Regression suite: replaying the pipeline must not repeat external side effects.

The encounter pipeline replays from the start on every human-gate resume. Before the
side-effect ledger, ONE 6-gate encounter produced 6 calendar bookings, 3 claim
submissions, 3 clinical-note writes, 2 card charges and 2 Rx transmissions — and the
patient's appointment silently drifted from the slot they picked, because each replay
re-booked and the previously booked slot dropped out of availability.
"""
from __future__ import annotations

import pytest

from src.api.store import EncounterStore
from src.config import Settings
from src.core.llm import LLMClient
from src.core.pipeline import MasterOrchestrator
from src.integrations import build_registry
from src.integrations.idempotency import (
    MUTATING_METHODS,
    IdempotentService,
    SideEffectLedger,
    bind_encounter,
)

# Mutating calls that a full encounter is expected to reach.
EXPECTED_ONCE = [
    ("schedule", "book"),
    ("payment", "charge"),
    ("claims", "submit_claim"),
    ("prior_auth", "submit"),
    ("pharmacy", "send_prescription"),
    ("pharmacy", "dispatch"),
    ("ehr", "write_clinical_note"),
]

REQUEST = {
    "patient_id": "PAT-001",
    "chief_complaint": "tooth pain, need a dentist",
    "request_text": "tooth pain, need a dentist",
    "prescribe": [{"rxcui": "161", "display": "acetaminophen", "controlled": False}],
    "labs": {"potassium": 6.5},  # pre-op labs before IV sedation — panic value on purpose
    "payment_token": "tok_demo",
    "state": "CA",
    "pharmacy_id": "PHARM-001",
}


def _counted_registry():
    """Registry whose guarded calls are counted at the REAL adapter boundary."""
    s = Settings(_env_file=None, llm_provider="sandbox")
    reg = build_registry(s)
    counts: dict[str, int] = {}

    for name, methods in MUTATING_METHODS.items():
        proxy = getattr(reg, name, None)
        if not getattr(proxy, "_is_idempotent_proxy", False):
            continue
        inner = proxy.unwrap()                      # count beneath the ledger
        for meth in methods:
            fn = getattr(inner, meth, None)
            if fn is None:
                continue
            key = f"{name}.{meth}"
            counts[key] = 0

            def make(fn=fn, key=key):
                async def wrapped(*a, **k):
                    counts[key] += 1
                    return await fn(*a, **k)
                return wrapped

            setattr(inner, meth, make())

    return reg, counts, s


async def _drive(reg, settings):
    master = MasterOrchestrator(reg, LLMClient(settings))
    store = EncounterStore()
    eid = store.create(dict(REQUEST))
    res = await master.execute_encounter(store.get(eid))
    passes, gates = 1, []
    while res.status == "awaiting_human":
        gid = res.awaiting_gate.gate_id
        gates.append(gid)
        store.add_decision(eid, gid, {"approved": True, "actor": "test", "note": "0"})
        res = await master.execute_encounter(store.get(eid))
        passes += 1
    return res, passes, gates


async def test_encounter_traverses_multiple_gates():
    """Guard the guard: if replay stopped happening these tests would be vacuous."""
    reg, _, s = _counted_registry()
    res, passes, gates = await _drive(reg, s)
    assert res.status == "completed", res.summary
    assert passes > 1, "expected at least one resume/replay pass"
    assert len(gates) >= 3, f"expected several gates, got {gates}"


@pytest.mark.parametrize("service,method", EXPECTED_ONCE)
async def test_mutating_call_fires_exactly_once_per_encounter(service, method):
    reg, counts, s = _counted_registry()
    res, passes, _ = await _drive(reg, s)
    assert res.status == "completed"
    key = f"{service}.{method}"
    n = counts.get(key)
    assert n is not None, f"{key} was never instrumented"
    assert n == 1, (
        f"{key} fired {n}x across {passes} pipeline passes; must be exactly 1. "
        f"Against a live vendor that is a duplicate booking/charge/claim.")


async def test_no_mutating_call_fires_more_than_once():
    """Blanket assertion, so a NEW side effect added later is caught too."""
    reg, counts, s = _counted_registry()
    await _drive(reg, s)
    repeated = {k: v for k, v in counts.items() if v > 1}
    assert not repeated, f"side effects re-executed on replay: {repeated}"


async def test_appointment_does_not_drift_across_replays():
    """The slot the patient chose must survive every subsequent resume."""
    s = Settings(_env_file=None, llm_provider="sandbox")
    reg = build_registry(s)
    master = MasterOrchestrator(reg, LLMClient(s))
    store = EncounterStore()
    eid = store.create(dict(REQUEST))

    res = await master.execute_encounter(store.get(eid))
    # first gate is the patient's slot pick — capture what they were offered
    assert res.awaiting_gate.gate_id == "scheduling.slot_selection"
    chosen = res.awaiting_gate.data["options"][0]

    while res.status == "awaiting_human":
        gid = res.awaiting_gate.gate_id
        store.add_decision(eid, gid, {"approved": True, "actor": "test", "note": "0"})
        res = await master.execute_encounter(store.get(eid))

    assert res.status == "completed"
    appt = res.domains["scheduling"]["output"]["appointment"]
    assert appt["slot"]["start"] == chosen["start"], (
        f"patient picked {chosen['start']} but was booked into {appt['slot']['start']}")
    assert appt["provider_npi"] == chosen["npi"]


async def test_slot_menu_is_stable_across_passes():
    """Availability is snapshotted, so the options don't shift under the patient."""
    s = Settings(_env_file=None, llm_provider="sandbox")
    reg = build_registry(s)
    master = MasterOrchestrator(reg, LLMClient(s))
    store = EncounterStore()
    eid = store.create(dict(REQUEST))

    first = await master.execute_encounter(store.get(eid))
    menu_1 = first.awaiting_gate.data["options"]
    # re-read without deciding anything — a GET replays the pipeline
    again = await master.execute_encounter(store.get(eid))
    menu_2 = again.awaiting_gate.data["options"]
    assert [o["start"] for o in menu_1] == [o["start"] for o in menu_2]


async def test_distinct_encounters_are_not_deduplicated_against_each_other():
    """The ledger is per-encounter: two patients must both get booked."""
    s = Settings(_env_file=None, llm_provider="sandbox")
    reg = build_registry(s)
    master = MasterOrchestrator(reg, LLMClient(s))
    store = EncounterStore()

    appts = []
    for pid in ("PAT-001", "PAT-003"):
        req = dict(REQUEST)
        req["patient_id"] = pid
        eid = store.create(req)
        res = await master.execute_encounter(store.get(eid))
        while res.status == "awaiting_human":
            gid = res.awaiting_gate.gate_id
            store.add_decision(eid, gid, {"approved": True, "actor": "t", "note": "0"})
            res = await master.execute_encounter(store.get(eid))
        assert res.status == "completed"
        appts.append(res.summary["appointment_id"])

    assert appts[0] and appts[1]
    assert appts[0] != appts[1], "two different encounters collapsed to one appointment"


# ------------------------------------------------------------------ unit-level
async def test_ledger_is_inert_when_no_encounter_is_bound():
    """Direct adapter use (unit tests, scripts) must not be silently memoised."""
    bind_encounter("")
    calls = []

    class Svc:
        async def book(self, npi, start):
            calls.append((npi, start))
            return True

    guarded = IdempotentService(Svc(), "schedule", SideEffectLedger())
    await guarded.book("123", "T1")
    await guarded.book("123", "T1")
    assert len(calls) == 2


async def test_ledger_replays_stored_receipt_for_same_payload():
    ledger = SideEffectLedger()
    calls = []

    class Svc:
        async def charge(self, token, cents):
            calls.append((token, cents))
            return {"status": "succeeded", "n": len(calls)}

    guarded = IdempotentService(Svc(), "payment", ledger)
    bind_encounter("ENC-1")
    try:
        first = await guarded.charge("tok", 500)
        second = await guarded.charge("tok", 500)
        assert len(calls) == 1
        assert first == second
        assert ledger.replay_suppressed == 1
        # a genuinely different payload is a different call
        await guarded.charge("tok", 900)
        assert len(calls) == 2
    finally:
        bind_encounter("")


async def test_unguarded_methods_pass_through_untouched():
    """Reference reads must NOT be memoised — only declared calls are guarded."""
    ledger = SideEffectLedger()
    calls = []

    class Svc:
        async def check_stock(self, ndc):
            calls.append(ndc)
            return True

        async def send_prescription(self, order):
            return "RX-1"

    guarded = IdempotentService(Svc(), "pharmacy", ledger)
    bind_encounter("ENC-2")
    try:
        await guarded.check_stock("ndc")
        await guarded.check_stock("ndc")
        assert len(calls) == 2
    finally:
        bind_encounter("")
