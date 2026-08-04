"""
Treatment Plan Consent (single task: patient accepts/declines specific procedures). MANUAL.

Distinct from patient.consent (the general HIPAA/treatment-authorization signature
taken at check-in, before the dentist has even examined the patient). This is the
real financial/informed-consent decision that happens AFTER a cost estimate exists:
a patient can accept part of a phased plan and defer the rest (e.g. "do the root
canal now, I'll think about the crown"). Decline specific items by item_id, comma-
separated, in the decision note; an empty note accepts the whole plan.
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent


class TreatmentPlanConsent(HumanGateAgent):
    name = "treatment_plan_consent"
    gate_id = "clinical.treatment_consent"

    def build_request(self, ctx) -> GateRequest:
        est = ctx.get_result("treatment_cost_estimator")
        return GateRequest(
            gate_id=self.gate_id,
            title="Patient treatment consent",
            prompt="Which recommended procedures would you like to proceed with today? "
                   "(List item IDs to decline, if any; otherwise the full plan is accepted.)",
            domain="clinical",
            data={
                "estimates": est.get("estimates", []),
                "estimated_patient_cents": est.get("estimated_patient_cents", 0),
                "estimated_insurer_cents": est.get("estimated_insurer_cents", 0),
            },
        )

    def on_approved(self, ctx, decision) -> dict:
        declined = {s.strip() for s in decision.note.split(",") if s.strip()}
        plan_items = ctx.get_result("treatment_plan_builder").get("items", [])
        accepted_ids = [i["item_id"] for i in plan_items if i["item_id"] not in declined]
        return {
            "accepted_item_ids": accepted_ids,
            "declined_item_ids": sorted(declined),
            "consented_by": decision.actor,
        }
