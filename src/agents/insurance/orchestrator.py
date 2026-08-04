"""
InsuranceOrchestrator — the POST-VISIT claim cycle: the 13 single-task insurance agents
that run after the patient has already left and already paid their estimate.

Order: Eligibility (date-of-service re-check) -> Formulary -> Predetermination Submitter
       -> [Predetermination Review gate, if pended] -> Claim Builder -> Claim Submitter
       -> [Claim Rejection Handler gate, if the 277CA rejected it]
       -> [Information Request Receiver, if accepted]
       -> [Information Request Router, if pended]
       -> [Document Request gate, if the record can't answer it]
       -> [Attachment Assembler, if pended]
       -> [Remittance Processor, if accepted] -> [Payment Reconciler, if accepted]
       -> Audit Logger

WHY THIS RUNS AFTER CHECKOUT
----------------------------
The claim is filed after the visit — same evening at the earliest, in an end-of-day
batch. By then the patient has been billed and has paid an estimate. Nothing in this
domain gates whether the patient is charged; it determines whether the ESTIMATE was
right, which ReconciliationOrchestrator then settles.

THREE THINGS A CLAIM CAN COME BACK AS
-------------------------------------
This is the part most models get wrong by having only two:

  REJECTED   277CA bounced it on a data fault. Never adjudicated, so no CARC codes and
             nothing to appeal. -> `claim_rejection_handler`, then the remittance is
             SKIPPED entirely: an 835 for a claim that never entered adjudication cannot
             happen, and reconciling against one would settle a patient's balance
             against a fiction.
  PENDED     277RFAI. Accepted, adjudication started and STOPPED for documentation, and a
             30-day clock is running. The payer has refused nothing. -> the receiver reads
             the request, the router decides who can answer each item, only the
             unanswerable remainder reaches a human, and the assembler sends the 275.
  ADJUDICATED 835 ERA, paid or denied. Denials are classified and routed by the
             reconciliation domain.

`eligibility_checker` here is not the primary verification (that ran pre-visit, in the
scheduling domain). It is the claim-time re-confirmation that coverage was active as of
the date of service, which is what the payer adjudicates against.

Note on predetermination: real dental predetermination is VOLUNTARY and advisory, not a
blocking prior authorization, and when a practice uses it the treatment is deferred 2-4
weeks rather than proceeding. Modeling it as an in-encounter gate is a simplification —
see docs/us-dental-clinic-real-world-workflow.md §0.2 and §6.4.

Insurance is NOT safety-critical: abort_on_fail=False, so a denial or a held claim yields
a partial result and the encounter continues.
"""
from __future__ import annotations

from src.agents.common import AuditLogger
from src.core.orchestrator import DomainOrchestrator, PipelineStep

from .attachment_assembler import AttachmentAssembler
from .claim_builder import ClaimBuilder
from .claim_rejection_handler import ClaimRejectionHandler
from .claim_submitter import ClaimSubmitter
from .document_request_gate import DocumentRequest
from .eligibility_checker import EligibilityChecker
from .formulary_checker import FormularyChecker
from .information_request_receiver import InformationRequestReceiver
from .information_request_router import InformationRequestRouter
from .payment_reconciler import PaymentReconciler
from .predetermination_review import PredeterminationReview
from .predetermination_submitter import PredeterminationSubmitter
from .remittance_processor import RemittanceProcessor


def _accepted(ctx) -> bool:
    """Did the 277CA accept this claim into adjudication?"""
    return bool(ctx.get_result("claim_submitter").get("claim_ack", {}).get("accepted", False))


def _pended(ctx) -> bool:
    """Did the payer stop and ask for documentation (277RFAI)?"""
    return bool(ctx.get_result("information_request_receiver").get("pended", False))


def _needs_human_docs(ctx) -> bool:
    """Is anything the payer asked for absent from the record?"""
    return bool(ctx.get_result("information_request_router").get("needs_human", False))


class InsuranceOrchestrator(DomainOrchestrator):
    name = "insurance"
    abort_on_fail = False

    def build_steps(self):
        return [
            PipelineStep(EligibilityChecker(self.registry)),
            PipelineStep(FormularyChecker(self.registry)),
            PipelineStep(PredeterminationSubmitter(self.registry)),
            PipelineStep(
                PredeterminationReview(),
                condition=lambda ctx: ctx.get_result("predetermination_submitter").get(
                    "requires_review", False),
            ),
            PipelineStep(ClaimBuilder()),
            PipelineStep(ClaimSubmitter(self.registry)),
            # --- rejected branch: data fault, no adjudication ---
            PipelineStep(ClaimRejectionHandler(), condition=lambda ctx: not _accepted(ctx)),
            # --- pended branch: payer wants documentation ---
            PipelineStep(InformationRequestReceiver(self.registry), condition=_accepted),
            PipelineStep(InformationRequestRouter(), condition=_pended),
            # only the items the record cannot answer ever reach a person
            PipelineStep(DocumentRequest(),
                         condition=lambda ctx: _pended(ctx) and _needs_human_docs(ctx)),
            PipelineStep(AttachmentAssembler(self.registry), condition=_pended),
            # --- adjudication ---
            PipelineStep(RemittanceProcessor(self.registry), condition=_accepted),
            PipelineStep(PaymentReconciler(), condition=_accepted),
            PipelineStep(AuditLogger(domain="insurance")),
        ]

    # ------------------------------------------------------------------ exchange view
    def _exchange(self, ctx) -> list[dict]:
        """The clinic <-> payer conversation, in order, for the UI.

        Every entry is either a real transaction the practice genuinely sends or receives,
        or a payer-side step flagged `simulated_internal`. A practice never sees inside
        adjudication — the payer-side rows are a reconstruction from the transactions the
        payer returns plus published plan rules, and are labelled as such so the
        distinction survives into the UI.
        """
        claim = ctx.get_result("claim_builder")
        ack = ctx.get_result("claim_submitter").get("claim_ack", {})
        received = ctx.get_result("information_request_receiver")
        routed = ctx.get_result("information_request_router")
        supplied = ctx.get_result("document_request")
        attachment = ctx.get_result("attachment_assembler")
        remit = ctx.get_result("remittance_processor").get("remittance", {})
        rows: list[dict] = []

        def add(actor, direction, transaction, label, detail="", status="ok", internal=False):
            rows.append({"seq": len(rows) + 1, "actor": actor, "direction": direction,
                         "transaction": transaction, "label": label, "detail": detail,
                         "status": status, "simulated_internal": internal})

        lines = claim.get("claim", {}).get("service_lines", [])
        add("clinic", "out", "837D", "Claim submitted",
            f"{len(lines)} service line(s) · ${claim.get('charge_cents', 0) / 100:,.2f}")
        for t in ack.get("payer_trace", []):
            add("payer", "internal", "", t["label"], t.get("detail", ""), t.get("result", "ok"), True)

        if not ack.get("accepted", False):
            add("payer", "in", "277CA", "Claim REJECTED — not adjudicated",
                f"{len(ack.get('rejections', []))} data problem(s) · no CARC codes, not appealable",
                "stop")
            handling = ctx.get_result("claim_rejection_handler")
            if handling:
                add("clinic", "out", "837D", "Corrected claim resubmitted",
                    f"replacement, frequency code {handling.get('frequency_code', '7')}", "ok")
            return rows

        add("payer", "in", "277CA", "Claim accepted into adjudication",
            f"payer receipt {ack.get('payer_receipt_date', '')}")

        if received.get("pended"):
            for t in received.get("payer_trace", []):
                add("payer", "internal", "", t["label"], t.get("detail", ""),
                    t.get("result", "ok"), True)
            add("payer", "in", "277RFAI", "Payer PENDED — documentation requested",
                f"{len(received.get('requested', []))} document(s) · respond by "
                f"{received.get('due_date', '')}", "warn")
            add("clinic", "internal", "", "AI checks the record for each requested document",
                routed.get("summary", ""), "ok")
            if supplied:
                add("clinic", "internal", "", "Practice staff supplied what was missing",
                    f"{supplied.get('supplied_by', '')} · {', '.join(supplied.get('labels', []))}",
                    "warn")
            add("clinic", "out", "275", "Documentation transmitted",
                f"{attachment.get('transmitted', 0)} document(s) · ACN "
                f"{attachment.get('attachment_control_number', '')} · "
                f"{attachment.get('ai_supplied', 0)} by AI, "
                f"{attachment.get('human_supplied', 0)} by staff",
                "ok" if attachment.get("complete") else "warn")

        for t in remit.get("payer_trace", []):
            add("payer", "internal", "", t["label"], t.get("detail", ""), t.get("result", "ok"), True)
        if remit:
            denied = remit.get("status") == "denied"
            add("payer", "in", "835", f"Remittance — {remit.get('status', '')}",
                f"payer pays ${remit.get('paid_cents', 0) / 100:,.2f} · patient "
                f"${remit.get('patient_responsibility_cents', 0) / 100:,.2f}",
                "stop" if denied else "ok")
        return rows

    def build_output(self, ctx) -> dict:
        ack = ctx.get_result("claim_submitter").get("claim_ack", {})
        received = ctx.get_result("information_request_receiver")
        routed = ctx.get_result("information_request_router")
        attachment = ctx.get_result("attachment_assembler")
        accepted = bool(ack.get("accepted", False))
        return {
            "coverage": ctx.get_result("eligibility_checker").get("coverage", {}),
            "formulary": ctx.get_result("formulary_checker").get("formulary", []),
            "predetermination": ctx.get_result("predetermination_submitter").get("predetermination", {}),
            "predetermination_review": ctx.get_result("predetermination_review"),
            "claim": ctx.get_result("claim_builder").get("claim", {}),
            "claim_ack": ack,
            # ---- the rejection branch (pre-adjudication) ----
            "claim_accepted": accepted,
            "claim_rejected": not accepted,
            "rejections": ack.get("rejections", []),
            "rejection_handling": ctx.get_result("claim_rejection_handler"),
            # ---- the pend branch (payer wants documentation) ----
            "pended": bool(received.get("pended", False)),
            "information_request": received.get("information_request", {}),
            "documents_requested": received.get("requested", []),
            "document_routing": routed,
            "documents_auto_satisfied": routed.get("auto_satisfiable", []),
            "documents_escalated": routed.get("escalated", []),
            "document_response_fully_automated": bool(routed.get("fully_automated", False)),
            "documents_supplied_by_staff": ctx.get_result("document_request"),
            "attachment": attachment.get("attachment", {}),
            "attachment_control_number": attachment.get("attachment_control_number", ""),
            # ---- adjudication ----
            "remittance": ctx.get_result("remittance_processor").get("remittance", {}),
            "reconciliation": ctx.get_result("payment_reconciler"),
            "charge_cents": ctx.get_result("claim_builder").get("charge_cents", 0),
            # ---- the whole conversation, for the UI ----
            "exchange": self._exchange(ctx),
            "claim_stage": _stage(accepted, received, attachment, ctx),
            "audit": ctx.get_result("audit_logger").get("audit", {}),
        }


def _stage(accepted: bool, received: dict, attachment: dict, ctx) -> str:
    """Where the claim actually got to — for the Insurance step chip, instead of 'done'.

    The payer's answer wins over our own state: an unanswered documentation request whose
    clock ran out is DENIED, not still awaiting documents.
    """
    if not accepted:
        return "rejected"
    remit = ctx.get_result("remittance_processor").get("remittance", {})
    if remit.get("status") == "denied":
        return "denied"
    if received.get("pended") and not attachment.get("complete", False):
        return "awaiting_documents"
    if not remit:
        return "submitted"
    if received.get("pended"):
        return "paid_after_documents"
    return "paid"
