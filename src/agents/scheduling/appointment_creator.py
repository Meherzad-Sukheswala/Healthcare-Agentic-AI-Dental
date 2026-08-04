"""Appointment Creator (single task: book the patient-selected slot). FULL."""
from __future__ import annotations

import hashlib

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class AppointmentCreator(Agent):
    name = "appointment_creator"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        sel = ctx.get_result("slot_selection")
        npi = sel.get("selected_npi", "")
        slot = sel.get("selected_slot", {})
        patient_id = ctx.input_data.get("patient_id", "")
        booked = await self.reg.schedule.book(npi, slot.get("start", ""))
        if not booked:
            return AgentResult.failed("selected slot no longer available")
        appt_id = "APPT-" + hashlib.sha256(
            f"{patient_id}{npi}{slot.get('start')}".encode()).hexdigest()[:10].upper()
        return AgentResult.completed({
            "appointment_id": appt_id,
            "status": "booked",
            "patient_id": patient_id,
            "provider_npi": npi,
            "provider_name": sel.get("selected_provider", ""),
            "slot": slot,
        })
