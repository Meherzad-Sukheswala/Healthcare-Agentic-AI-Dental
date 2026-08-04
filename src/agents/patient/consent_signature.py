"""
Consent Signature (single task: the patient's informed-consent signature). MANUAL.

Always required — a person must authorize treatment and the HIPAA release. Pauses
the pipeline until a signed decision is provided.
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent
from src.shared.enums import ConsentStatus


class ConsentSignature(HumanGateAgent):
    name = "consent_signature"
    gate_id = "patient.consent"

    def build_request(self, ctx) -> GateRequest:
        return GateRequest(
            gate_id=self.gate_id,
            title="Patient consent signature required",
            prompt="Patient must sign treatment consent and HIPAA authorization.",
            domain="patient",
            data={
                "patient_id": ctx.input_data.get("patient_id", ""),
                "forms": ctx.get_result("consent_presenter").get("forms", []),
            },
        )

    def on_approved(self, ctx, decision) -> dict:
        return {"consent_status": ConsentStatus.SIGNED.value, "signed_by": decision.actor}
