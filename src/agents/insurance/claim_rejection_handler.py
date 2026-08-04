"""
Claim Rejection Handler (single task: a biller fixes a rejected claim). MANUAL.

Runs only when the 277CA came back REJECTED — the claim never reached adjudication.

WHY THIS IS A SEPARATE GATE FROM billing.denial
-----------------------------------------------
A rejection and a denial look similar on a worklist and need opposite work:

  rejected  the clearinghouse or payer front-end edits bounced it on a data problem.
            No CARC codes exist, because nothing was adjudicated. There is NOTHING TO
            APPEAL. The biller corrects the offending element and resubmits — often
            same-day.
  denied    the payer adjudicated and refused. CARC/RARC codes explain why, and an
            appeal is a real option on a 30-90 day cycle.

Routing a rejection to an appeal gate is the specific mistake this gate exists to
prevent: it burns the appeal cycle on something fixable in an afternoon, and the claim
sits unpaid while the timely-filing clock keeps running.

Resubmission mechanics this gate records: a corrected claim goes back out with
frequency code 7 (replacement) carrying the ORIGINAL claim control number, so the payer
replaces rather than duplicates — a fresh submission would come back as CARC 18,
duplicate. The timely-filing clock runs from the date of service, and the 277CA's payer
receipt date is what proves when the original attempt landed.
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent


class ClaimRejectionHandler(HumanGateAgent):
    name = "claim_rejection_handler"
    gate_id = "insurance.claim_rejection"

    def build_request(self, ctx) -> GateRequest:
        ack = ctx.get_result("claim_submitter").get("claim_ack", {})
        rejections = ack.get("rejections", [])
        return GateRequest(
            gate_id=self.gate_id,
            title="Claim rejected before adjudication — correct and resubmit",
            prompt=("The payer never adjudicated this claim, so there is nothing to appeal. "
                    "Fix the flagged data element(s) and resubmit as a replacement claim."),
            domain="insurance",
            data={
                "transaction": ack.get("transaction", "277CA"),
                "control_number": ack.get("control_number", ""),
                "payer_receipt_date": ack.get("payer_receipt_date", ""),
                "rejection_count": len(rejections),
                "rejections": rejections,
                # spelled out because it is the whole point of this gate
                "appealable": False,
                "resubmission_frequency_code": "7",
            },
        )

    def on_approved(self, ctx, decision) -> dict:
        ack = ctx.get_result("claim_submitter").get("claim_ack", {})
        rejections = ack.get("rejections", [])
        return {
            "rejection_worked": True,
            "handled_by": decision.actor,
            "action": "correct_and_resubmit",
            "correction_note": decision.note or "",
            "elements_to_fix": [r.get("element", "") for r in rejections],
            "status_codes": [r.get("status_code", "") for r in rejections],
            # a replacement claim, not a new one — a fresh submission would come back
            # as CARC 18 (exact duplicate)
            "resubmitted_as": "replacement",
            "frequency_code": "7",
            "original_control_number": ack.get("control_number", ""),
        }

    # Declining this gate is a real option — some rejections need the office to
    # re-verify insurance with the patient before the claim can go back out at all.
    # HumanGateAgent turns a declined decision into AgentResult.rejected, which marks
    # the insurance domain PARTIAL (abort_on_fail=False) and leaves the claim unpaid in
    # AR, which is exactly the right outcome for a held claim.
