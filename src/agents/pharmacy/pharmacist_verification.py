"""
Pharmacist Verification (single task: OBRA-90 mandated pharmacist review). MANUAL.

A licensed pharmacist reviews the DUR findings, PDMP report and allergy screen and
verifies the fill. Legally required before dispensing — always pauses the pipeline.
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent


class PharmacistVerification(HumanGateAgent):
    name = "pharmacist_verification"
    gate_id = "pharmacy.verification"

    def build_request(self, ctx) -> GateRequest:
        return GateRequest(
            gate_id=self.gate_id,
            title="Pharmacist verification required",
            prompt="Pharmacist: review DUR/PDMP/allergy findings and verify the fill.",
            domain="pharmacy",
            data={
                "dur_findings": ctx.get_result("dur_screener").get("dur_findings", []),
                "pdmp_risk_flags": ctx.get_result("pdmp_query").get("risk_flags", []),
                "allergy_conflicts": ctx.get_result("allergy_gate").get("conflicts", []),
            },
        )

    def on_approved(self, ctx, decision) -> dict:
        return {"verified": True, "pharmacist": decision.actor, "note": decision.note}
