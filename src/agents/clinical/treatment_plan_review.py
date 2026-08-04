"""
Treatment Plan Review (single task: the dentist signs off on the drafted plan). MANUAL.

Distinct from diagnosis sign-off: confirming a diagnosis and approving a treatment
plan are different clinical decisions in real practice (you can agree on what's
wrong and still disagree on how aggressively to treat it). Only runs when the
builder actually recommended something — an exam-only visit has nothing to review.
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent


class TreatmentPlanReview(HumanGateAgent):
    name = "treatment_plan_review"
    gate_id = "clinical.treatment_plan"

    def build_request(self, ctx) -> GateRequest:
        plan = ctx.get_result("treatment_plan_builder")
        return GateRequest(
            gate_id=self.gate_id,
            title="Dentist treatment plan review",
            prompt="Confirm the recommended procedures before presenting a cost estimate to the patient.",
            domain="clinical",
            data={
                "diagnosis_icd10": plan.get("diagnosis_icd10", ""),
                "items": plan.get("items", []),
                "total_cents": plan.get("total_cents", 0),
            },
        )

    def on_approved(self, ctx, decision) -> dict:
        return {"treatment_plan_approved": True, "reviewing_dentist": decision.actor}
