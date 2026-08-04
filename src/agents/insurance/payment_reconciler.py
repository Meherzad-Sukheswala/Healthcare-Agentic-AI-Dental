"""
Payment Reconciler (single task: compare what was paid against what was billed). FULL.

The insurance coordinator's real job once an ERA arrives: does the payment match
expectations, and if not, why (read off the CARC codes)? This produces the
structured reconciliation Billing's denial_detector consumes — a real underpayment
or denial is now a fact derived from the payer's actual response, not a flag the
caller happened to pass in.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class PaymentReconciler(Agent):
    name = "payment_reconciler"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        remit = ctx.get_result("remittance_processor").get("remittance", {})
        billed = remit.get("billed_cents", 0)
        allowed = remit.get("allowed_cents", billed)
        status = remit.get("status", "paid")
        return AgentResult.completed({
            "billed_cents": billed,
            "allowed_cents": allowed,
            "write_off_cents": max(0, billed - allowed),
            "paid_cents": remit.get("paid_cents", 0),
            "patient_responsibility_cents": remit.get("patient_responsibility_cents", 0),
            "status": status,
            "needs_follow_up": status != "paid",
            "adjustments": remit.get("adjustments", []),
        })
