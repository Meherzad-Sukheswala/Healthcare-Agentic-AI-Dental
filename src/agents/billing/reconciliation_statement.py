"""
Reconciliation Statement (single task: settle the estimate against the payer's actual
response). FULL.

WHY THIS EXISTS
---------------
A US dental practice bills the patient BEFORE the payer has adjudicated anything. At
checkout the patient pays an ESTIMATE computed from a pre-visit eligibility check
(see docs/us-dental-clinic-real-world-workflow.md §0.1). Days later the 835 ERA
arrives with the payer's real numbers, and the two rarely match exactly — a
deductible applied elsewhere, an annual maximum that ran out, a downgraded code.

This agent is that settle-up. It compares what the patient actually owes (from the
remittance) against what was already collected, and produces exactly one of three
real-world outcomes:

  balance_due  -> the estimate was low; send a balance statement
  refund_due   -> the estimate was high; refund or credit the account
  balanced     -> the estimate was right; nothing to send

Retail/ancillary items and their tax are patient out-of-pocket, never insured, so
they were fully collected at checkout and are added to the payer-determined service
responsibility to get the patient's true total.
"""
from __future__ import annotations

import hashlib

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


# Denial actions that mean the payer has not finally answered yet, so the account
# cannot be settled in either direction.
_PENDING_ACTIONS = {"appeal", "resubmit_with_attachment", "rebill_other_payer"}


class ReconciliationStatement(Agent):
    name = "reconciliation_statement"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        remit = ctx.input_data.get("remittance") or {}
        collected = int(ctx.input_data.get("collected_cents", 0))
        estimated = int(ctx.input_data.get("estimated_patient_cents", collected))
        addons = int(ctx.input_data.get("addons_cents", 0))

        # No payer response to settle against. Two very different situations produce
        # this, and conflating them would misreport the account:
        #   self-pay / uninsured  -> what was collected at checkout WAS the final bill
        #   claim rejected        -> the claim never reached adjudication, so the balance
        #                            is UNRESOLVED and stays in AR until a corrected
        #                            claim goes back out. Nothing is settled here.
        if not remit:
            rejected = bool(ctx.input_data.get("claim_rejected"))
            return AgentResult.completed({
                "outcome": "unresolved" if rejected else "not_applicable",
                "reason": "claim_rejected_not_adjudicated" if rejected else "self_pay_no_remittance",
                "awaiting_corrected_claim": rejected,
                "collected_cents": collected,
                "actual_patient_cents": collected,
                "delta_cents": 0,
                "estimate_variance_cents": 0,
            })

        # A denial that is being appealed, resubmitted or rebilled is NOT a final answer.
        # The payer has not said what it will ultimately pay, so there is nothing to
        # settle: the patient's estimate stands and the balance sits in AR. Refunding
        # them now — which is what a naive "payer said $0, so refund everything" reading
        # produces — would hand back money the claim may well still collect.
        if str(remit.get("action", "none")) in _PENDING_ACTIONS:
            return AgentResult.completed({
                "outcome": "unresolved",
                "reason": remit.get("reason", "pending_payer_response"),
                "pending_action": remit.get("action", ""),
                "awaiting_corrected_claim": True,
                "collected_cents": collected,
                "estimated_patient_cents": estimated,
                # what the patient owes is still the estimate until the payer answers
                "actual_patient_cents": collected,
                "delta_cents": 0,
                "balance_due_cents": 0,
                "refund_due_cents": 0,
                "estimate_variance_cents": 0,
                "explanation": remit.get("explanation", ""),
            })

        service_patient = int(remit.get("patient_responsibility_cents", 0))
        actual_total = service_patient + addons
        delta = actual_total - collected

        outcome = "balanced"
        if delta > 0:
            outcome = "balance_due"
        elif delta < 0:
            outcome = "refund_due"

        statement_id = "STM-" + hashlib.sha256(
            f"{ctx.input_data.get('patient_id','')}{ctx.encounter_id}{actual_total}".encode()
        ).hexdigest()[:10].upper()

        return AgentResult.completed({
            "statement_id": statement_id,
            "outcome": outcome,
            # the three numbers the patient and the office argue about
            "estimated_patient_cents": estimated,
            "collected_cents": collected,
            "actual_patient_cents": actual_total,
            # what to do about the gap
            "delta_cents": delta,
            "balance_due_cents": max(0, delta),
            "refund_due_cents": max(0, -delta),
            # how far off the pre-visit estimate turned out to be
            "estimate_variance_cents": actual_total - estimated,
            # payer-side detail, for the statement's explanation of benefits section
            "service_patient_cents": service_patient,
            "addons_cents": addons,
            "billed_cents": int(remit.get("billed_cents", 0)),
            "allowed_cents": int(remit.get("allowed_cents", 0)),
            "insurer_paid_cents": int(remit.get("paid_cents", 0)),
            "write_off_cents": max(0, int(remit.get("billed_cents", 0)) - int(remit.get("allowed_cents", 0))),
            "adjustments": remit.get("adjustments", []),
        })
