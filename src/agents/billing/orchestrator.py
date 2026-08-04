"""
CheckoutOrchestrator — phase 1 of billing: what happens at the front desk on the way
out, BEFORE the claim is ever submitted.

Order: Fee Calculator -> Tax Engine -> Coverage Coordinator -> Bill Splitter
       (ESTIMATE) -> [Coding QA gate, if high cost] -> Invoice Generator ->
       Patient Payment Authorization (gate, always) -> Payment Processor -> Audit Logger

WHY THIS RUNS BEFORE INSURANCE
------------------------------
In a US dental practice the patient pays at checkout, on the day of service, against
an ESTIMATE derived from the pre-visit eligibility check — not against the payer's
actual response, which does not exist yet and will not for another 1–2 weeks. There
is no approval gate between treatment and collecting money.

That is why `BillSplitter` runs here with no remittance in context: it computes the
estimate. The same agent's remittance-aware path is exercised later, in
ReconciliationOrchestrator, once the 835 ERA has arrived.

Coding QA sits here rather than in Insurance because checkout precedes claim
submission, so a coder review at this point is still pre-submission — which is where
a real CDI/coder review belongs.

Not safety-critical: abort_on_fail=False (partial results on failure).
"""
from __future__ import annotations

from src.agents.common import AuditLogger
from src.core.orchestrator import DomainOrchestrator, PipelineStep

from .bill_splitter import BillSplitter
from .charge_coding_qa import QA_THRESHOLD_CENTS, ChargeCodingQA
from .coverage_coordinator import CoverageCoordinator
from .fee_calculator import FeeCalculator
from .invoice_generator import InvoiceGenerator
from .patient_payment_authorization import PatientPaymentAuthorization
from .payment_processor import PaymentProcessor
from .tax_engine import TaxEngine


class CheckoutOrchestrator(DomainOrchestrator):
    name = "checkout"
    abort_on_fail = False

    def build_steps(self):
        return [
            PipelineStep(FeeCalculator()),
            PipelineStep(TaxEngine()),
            PipelineStep(CoverageCoordinator()),
            PipelineStep(BillSplitter()),
            PipelineStep(
                ChargeCodingQA(),
                condition=lambda ctx: ctx.get_result("bill_splitter").get("total_cents", 0) >= QA_THRESHOLD_CENTS,
            ),
            PipelineStep(InvoiceGenerator()),
            PipelineStep(PatientPaymentAuthorization()),
            PipelineStep(PaymentProcessor(self.registry)),
            PipelineStep(AuditLogger(domain="checkout")),
        ]

    def build_output(self, ctx) -> dict:
        inv = ctx.get_result("invoice_generator")
        auth = ctx.get_result("patient_payment_authorization")
        split = ctx.get_result("bill_splitter")
        tax = ctx.get_result("tax_engine")
        fee = ctx.get_result("fee_calculator")
        payment = ctx.get_result("payment_processor").get("payment", {})
        # Once authorized, reflect the bill the patient chose; otherwise the invoice default.
        amount_due = auth.get("amount_due_cents", inv.get("amount_due_cents", 0))
        # Only money that actually moved counts as collected — a declined card leaves
        # the full estimate outstanding for reconciliation to pick up.
        collected = amount_due if payment.get("status") == "succeeded" else 0
        return {
            "invoice": inv,
            "total_cents": inv.get("total_cents", 0),
            "amount_due_cents": amount_due,
            "estimated_patient_cents": amount_due,
            "collected_cents": collected,
            # patient out-of-pocket that insurance never touches, carried forward so
            # reconciliation can separate it from the payer-determined service share
            "addons_cents": int(fee.get("items_cents", 0)) + int(tax.get("tax_cents", 0)),
            "is_self_pay": split.get("is_self_pay", False),
            "chosen_bill": auth.get("chosen_bill", ""),
            "payment": payment,
            "coding_qa": ctx.get_result("charge_coding_qa"),
            "audit": ctx.get_result("audit_logger").get("audit", {}),
        }
