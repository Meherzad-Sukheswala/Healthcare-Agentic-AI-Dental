"""
Slot Selection (single task: the patient picks a doctor + time). MANUAL.

Presents the open slots across the matched doctors and pauses for the patient to
choose. The chosen option id is supplied in the decision note; defaults to the
first option if none is given.
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent


class SlotSelection(HumanGateAgent):
    name = "slot_selection"
    gate_id = "scheduling.slot_selection"

    def build_request(self, ctx) -> GateRequest:
        return GateRequest(
            gate_id=self.gate_id,
            title="Choose an appointment",
            prompt="Select the doctor and time that works for you.",
            domain="scheduling",
            data={"options": ctx.get_result("availability_finder").get("slot_options", [])},
        )

    def on_approved(self, ctx, decision) -> dict:
        options = ctx.get_result("availability_finder").get("slot_options", [])
        idx = 0
        try:
            idx = int(decision.note)
        except (TypeError, ValueError):
            idx = 0
        if idx < 0 or idx >= len(options):
            idx = 0
        sel = options[idx] if options else {}
        return {
            "patient_selected": True,
            "selected_npi": sel.get("npi", ""),
            "selected_provider": sel.get("provider_name", ""),
            "selected_slot": {"start": sel.get("start", ""), "duration_min": sel.get("duration_min", 30)},
        }
