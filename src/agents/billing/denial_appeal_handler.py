"""
Denial / Appeal Handler (single task: a biller works an adjudicated denial). MANUAL.

Runs only when the payer ADJUDICATED the claim and the correct next move is an appeal or
a resubmission with documentation — not for every denial. A frequency limitation or an
exhausted annual maximum is a correct adjudication that a biller bills the patient for;
opening an appeal gate on those would be teaching the wrong reflex.

Rejections (bounced before adjudication) never reach here — they go to
`insurance.claim_rejection`, because there is no payer decision to appeal.

The gate presents the payer's actual reason, the CARC/RARC codes, the recommended
action, and the appeal deadline, because those four together are what a biller needs to
decide between appealing, resubmitting and writing off.
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent
from src.shared.payer_outcomes import ACTION_RESUBMIT_ATTACHMENT

# ERISA-covered group health plans must allow at least 180 days to file an internal
# appeal after an adverse benefit determination (29 CFR 2560.503-1). Plans vary from
# 90 days to 12 months, and the real deadline is printed on the EOB.
_APPEAL_WINDOW_DAYS = 180


class DenialAppealHandler(HumanGateAgent):
    name = "denial_appeal_handler"
    gate_id = "billing.denial"

    def build_request(self, ctx) -> GateRequest:
        remittance = ctx.input_data.get("remittance", {}) or {}
        detected = ctx.get_result("denial_detector")
        action = detected.get("action", "appeal")
        resubmitting = action == ACTION_RESUBMIT_ATTACHMENT

        title = ("Claim needs documentation — resubmit, do not appeal" if resubmitting
                 else "Claim denied — Billing Specialist appeal review")
        prompt = ("Payer wants documentation it never received. Attach it and resubmit as a "
                  "replacement claim (frequency code 7) — an appeal here just burns the "
                  "30-90 day cycle on something fixable today."
                  if resubmitting else
                  "Biller: file an appeal with supporting documentation, or write off the claim.")

        return GateRequest(
            gate_id=self.gate_id,
            title=title,
            prompt=prompt,
            domain="billing",
            data={
                "claim_status": detected.get("claim_status", ""),
                "denial_reason": detected.get("reason", ""),
                "recommended_action": action,
                "appealable": detected.get("appealable", False),
                "why": detected.get("explanation", ""),
                "carc_codes": detected.get("carcs", []),
                "adjustments": remittance.get("adjustments", []),
                "billed_cents": remittance.get("billed_cents", 0),
                "appeal_deadline_days": _APPEAL_WINDOW_DAYS,
                "attachments_available": ctx.input_data.get("attachments_recommended", []),
            },
        )

    def on_approved(self, ctx, decision) -> dict:
        detected = ctx.get_result("denial_detector")
        action = detected.get("action", "appeal")
        resubmitting = action == ACTION_RESUBMIT_ATTACHMENT
        return {
            "appeal_filed": not resubmitting,
            "resubmitted_with_attachment": resubmitting,
            "handled_by": decision.actor,
            # what the biller actually did, defaulting to the payer-indicated action
            "action": decision.note or action,
            "denial_reason": detected.get("reason", ""),
            "appeal_deadline_days": _APPEAL_WINDOW_DAYS,
            "frequency_code": "7" if resubmitting else "",
        }
