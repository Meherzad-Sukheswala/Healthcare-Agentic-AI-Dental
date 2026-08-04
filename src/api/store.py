"""
src/api/store.py

In-memory encounter store for the demo. Holds each encounter's request plus the
human decisions gathered so far. Because the pipeline is deterministic, replaying
the stored request (with accumulated decisions) reproduces the current state — so
resume is just "add a decision and re-run".

For production this would be Redis/Postgres-backed; the interface is the same.
"""
from __future__ import annotations

import uuid


class EncounterStore:
    def __init__(self) -> None:
        self._d: dict[str, dict] = {}

    def create(self, request: dict) -> str:
        eid = str(uuid.uuid4())
        request["encounter_id"] = eid
        request["decisions"] = {}
        self._d[eid] = request
        return eid

    def get(self, eid: str) -> dict | None:
        return self._d.get(eid)

    def add_decision(self, eid: str, gate_id: str, decision: dict) -> None:
        self._d[eid]["decisions"][gate_id] = decision
