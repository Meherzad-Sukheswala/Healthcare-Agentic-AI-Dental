"""
Referral Approval (single task: the scheduling human gate).

When a specialist visit requires a referral, a PCP / clinical staffer must approve.
Runs only when the request is flagged requires_referral. MANUAL — pauses the
pipeline via the HumanGateAgent pause/resume primitive.
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent
from src.shared.enums import GateStatus


class ReferralApproval(HumanGateAgent):
    name = "referral_approval"
    gate_id = "scheduling.referral"

    def build_request(self, ctx) -> GateRequest:
        parsed = ctx.get_result("request_parser")
        return GateRequest(
            gate_id=self.gate_id,
            title="Referral approval required",
            prompt="Approve specialist referral for this patient?",
            domain="scheduling",
            data={
                "patient_id": ctx.input_data.get("patient_id", ""),
                "specialty": parsed.get("specialty", ""),
                "reason": parsed.get("reason", ""),
            },
        )

    def on_approved(self, ctx, decision) -> dict:
        return {
            "referral_approved": True,
            "approved_by": decision.actor,
            "status": GateStatus.APPROVED.value,
        }
