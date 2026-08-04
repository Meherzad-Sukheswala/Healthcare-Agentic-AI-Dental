"""
Predetermination Review (single task: payer clinician reviews the estimate). MANUAL.

Runs only when the 278 response pended for review (high-cost/surgical procedures —
implants, bone grafts, comprehensive ortho). Unlike medical prior-auth, a pended or
denied predetermination does NOT abort or reverse anything here: the treatment
already happened earlier in the pipeline. This gate represents the payer's clinical
reviewer deciding whether they'll honor the estimate — it informs the claim, it
doesn't gate the encounter. A denial is a non-completing outcome, matching real
revenue-cycle behavior (denials get appealed downstream in Billing).
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent


class PredeterminationReview(HumanGateAgent):
    name = "predetermination_review"
    gate_id = "insurance.predetermination"

    def build_request(self, ctx) -> GateRequest:
        pa = ctx.get_result("predetermination_submitter").get("predetermination", {})
        return GateRequest(
            gate_id=self.gate_id,
            title="Predetermination review",
            prompt="Payer clinical reviewer: will this estimate be honored? "
                   "(Advisory only — the procedure has already been performed.)",
            domain="insurance",
            data={"cdt": ctx.input_data.get("cdt", ""), "icd10": ctx.input_data.get("icd10", ""),
                  "reason": pa.get("reason", "")},
        )

    def on_approved(self, ctx, decision) -> dict:
        return {"predetermination_honored": True, "auth_number": f"PD-{decision.actor[:3].upper()}",
                "reviewer": decision.actor}
