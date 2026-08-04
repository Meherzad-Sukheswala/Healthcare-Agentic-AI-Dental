"""
Critical-Value Notifier (single task: human must acknowledge a panic value). MANUAL.

Runs only when the detector found a critical value. A clinician must acknowledge it
before the encounter continues (regulatory critical-value notification).
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent


class CriticalValueNotifier(HumanGateAgent):
    name = "critical_value_notifier"
    gate_id = "clinical.critical_value"

    def build_request(self, ctx) -> GateRequest:
        return GateRequest(
            gate_id=self.gate_id,
            title="Critical lab value — notify clinician",
            prompt="Acknowledge critical value(s) and confirm the patient has been contacted.",
            domain="clinical",
            data={"critical_values": ctx.get_result("critical_value_detector").get("critical_values", [])},
        )

    def on_approved(self, ctx, decision) -> dict:
        return {"critical_acknowledged": True, "acknowledged_by": decision.actor}
