"""
Denial Detector (single task: classify the payer's ERA outcome and route it). FULL.

Not just "was it denied" — WHICH denial, and therefore what a biller should do. Eight
denial reasons route to five different actions and only two of them are appeals, so a
detector that returns a bare boolean sends most denials down the wrong path (see
src/shared/payer_outcomes.py for the full mapping).

Three distinctions this makes that a boolean cannot:

  * a REJECTED claim never reached adjudication, so it is not a denial at all and has no
    CARC codes — it is handled upstream by `insurance.claim_rejection`, and must not
    surface here as a denial.
  * `paid_alternate_benefit` (LEAT) is a PAID claim, not a denial. The plan paid at a
    cheaper procedure's rate and the differential is patient responsibility.
  * `needs_appeal` is narrower than `denied`. A frequency limitation or an exhausted
    annual maximum is a correct adjudication — appealing it cannot succeed, and the
    money is the patient's to pay.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation
from src.shared.payer_outcomes import ACTION_APPEAL, ACTION_RESUBMIT_ATTACHMENT


class DenialDetector(Agent):
    name = "denial_detector"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        remit = ctx.input_data.get("remittance") or {}
        # A claim rejected pre-adjudication has no ERA; don't invent a denial for it.
        if ctx.input_data.get("claim_rejected"):
            return AgentResult.completed({
                "denied": False, "claim_status": "rejected", "reason": "not_adjudicated",
                "action": "correct_and_resubmit", "appealable": False, "needs_appeal": False,
                "explanation": ("Claim was rejected by front-end edits and never adjudicated — "
                                "handled at the insurance.claim_rejection gate, not here."),
            })

        status = str(remit.get("status", ctx.input_data.get("claim_status", "received"))).lower()
        reason = remit.get("reason", "adjudicated")
        action = remit.get("action", "none")
        appealable = bool(remit.get("appealable", False))
        denied = status == "denied"

        # A denial that arrives without a stated reason still has to reach a human. Fail
        # toward the appeal gate rather than silently absorbing it — an unexplained
        # denial nobody looks at is worse than one wrongly routed to a biller.
        if denied and action == "none":
            action, appealable = ACTION_APPEAL, True
            if reason == "adjudicated":
                reason = "unspecified"

        return AgentResult.completed({
            "denied": denied,
            "claim_status": status,
            "reason": reason,
            "action": action,
            "appealable": appealable,
            # Only open the appeal gate when an appeal is the RIGHT move. A missing
            # attachment is a resubmission; a frequency cap is the patient's bill.
            "needs_appeal": action in (ACTION_APPEAL, ACTION_RESUBMIT_ATTACHMENT),
            "downgraded": status == "paid_alternate_benefit",
            "explanation": remit.get("explanation", ""),
            "carcs": [a.get("code", "") for a in remit.get("adjustments", [])],
        })
