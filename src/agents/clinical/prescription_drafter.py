"""
Prescription Drafter (single task: draft the prescriptions). PARTIAL.

Drafts from the requested medications and flags controlled substances, which must
be signed at the EPCS gate before they can be transmitted.
"""
from __future__ import annotations

import hashlib

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

_CONTROLLED = {"CII", "CIII", "CIV", "CV"}


class PrescriptionDrafter(Agent):
    name = "prescription_drafter"
    automation = Automation.PARTIAL

    async def execute(self, ctx) -> AgentResult:
        requested = ctx.input_data.get("prescribe", []) or []
        prescriptions, has_controlled = [], False
        for item in requested:
            schedule = item.get("schedule", "non_controlled")
            controlled = schedule in _CONTROLLED
            has_controlled = has_controlled or controlled
            rx_id = "RX-" + hashlib.sha256(
                f"{item.get('rxcui')}{ctx.encounter_id}".encode()).hexdigest()[:10].upper()
            prescriptions.append({
                "rx_id": rx_id,
                "rxcui": item.get("rxcui", ""),
                "display": item.get("display", ""),
                "ndc": item.get("ndc", ""),
                "schedule": schedule,
                "controlled": controlled,
                "transmit_status": "pending_sign" if controlled else "ready",
            })
        return AgentResult.completed({"prescriptions": prescriptions, "has_controlled": has_controlled})
