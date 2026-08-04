"""
ReconciliationOrchestrator — phase 2 of billing: what happens 1–2 weeks after the
visit, once the payer's 835 ERA lands.

Order: Reconciliation Statement -> Denial Detector -> [Denial/Appeal Handler gate,
       if denied] -> Audit Logger

WHY THIS IS A SEPARATE DOMAIN FROM CHECKOUT
-------------------------------------------
Checkout collected an ESTIMATE. This phase is the only point at which the patient's
true out-of-pocket is known, because it is the first point at which the payer has
actually spoken. The office posts the ERA, applies the contractual write-off,
discovers the estimate was off, and then either sends a balance statement or issues a
refund.

Modeling these as one domain (as this repo previously did) implies the patient is
billed once, with the payer's answer already in hand. That is not how any US dental
practice works, and it hides the single largest source of real-world AR pain: the gap
between the estimate and the ERA.

Denial detection lives here rather than at checkout for the same reason — a denial is
a fact about the payer's response, so it cannot be known until the response exists.

Not safety-critical: abort_on_fail=False.
"""
from __future__ import annotations

from src.agents.common import AuditLogger
from src.core.orchestrator import DomainOrchestrator, PipelineStep

from .denial_appeal_handler import DenialAppealHandler
from .denial_detector import DenialDetector
from .reconciliation_statement import ReconciliationStatement


class ReconciliationOrchestrator(DomainOrchestrator):
    name = "reconciliation"
    abort_on_fail = False

    def build_steps(self):
        return [
            PipelineStep(ReconciliationStatement()),
            PipelineStep(DenialDetector()),
            PipelineStep(
                DenialAppealHandler(),
                # `needs_appeal`, not `denied`: a frequency cap or an exhausted annual
                # maximum is a correct adjudication the patient owes, not something a
                # biller can appeal. Only appeals and documentation-resubmissions gate.
                condition=lambda ctx: ctx.get_result("denial_detector").get("needs_appeal", False),
            ),
            PipelineStep(AuditLogger(domain="reconciliation")),
        ]

    def build_output(self, ctx) -> dict:
        stmt = ctx.get_result("reconciliation_statement")
        return {
            "statement": stmt,
            "outcome": stmt.get("outcome", ""),
            "actual_patient_cents": stmt.get("actual_patient_cents", 0),
            "balance_due_cents": stmt.get("balance_due_cents", 0),
            "refund_due_cents": stmt.get("refund_due_cents", 0),
            "estimate_variance_cents": stmt.get("estimate_variance_cents", 0),
            "write_off_cents": stmt.get("write_off_cents", 0),
            "denied": ctx.get_result("denial_detector").get("denied", False),
            # the classified outcome, so the UI and AR reporting can route it
            "denial": ctx.get_result("denial_detector"),
            "denial_reason": ctx.get_result("denial_detector").get("reason", ""),
            "recommended_action": ctx.get_result("denial_detector").get("action", ""),
            "downgraded": ctx.get_result("denial_detector").get("downgraded", False),
            "appeal": ctx.get_result("denial_appeal_handler"),
            "audit": ctx.get_result("audit_logger").get("audit", {}),
        }
