"""
Document Request (single task: a human supplies documentation the record doesn't hold). MANUAL.

Human gate #17, and deliberately the narrowest gate in the pipeline: it fires ONLY for the
documents `information_request_router` could not satisfy from the record. Everything the
AI could already answer has been attached and sent before anyone is interrupted.

That is the whole design intent. A payer asking for three documents where two are already
on file should cost the practice one small task, not three.

The gate says four things a real worklist item has to say:
  * exactly which documents are missing, and which procedure each supports
  * WHO has to produce each one — dentist, hygienist, or admin chasing another office
  * whether the PATIENT has to come back in, which is the expensive outcome
  * how many days are left on the payer's clock

Declining is a real option: some requests are not worth answering — a $95 exam claim is
not worth recalling a patient for a film — and the right move is to write it off. Declining
marks the insurance domain PARTIAL and the claim stays unresolved in AR.
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent


class DocumentRequest(HumanGateAgent):
    name = "document_request"
    gate_id = "insurance.document_request"

    def build_request(self, ctx) -> GateRequest:
        routed = ctx.get_result("information_request_router")
        received = ctx.get_result("information_request_receiver")
        escalated = routed.get("escalated", [])
        auto = routed.get("auto_satisfiable", [])

        return GateRequest(
            gate_id=self.gate_id,
            title="Payer wants documentation the record doesn't hold",
            prompt=("The AI has already attached everything on file. These items don't exist "
                    "yet and need a person. Confirm they've been produced, or decline and "
                    "write the claim off."),
            domain="insurance",
            data={
                "reason_summary": received.get("reason_summary", ""),
                "due_date": received.get("due_date", ""),
                "days_to_respond": received.get("respond_within_days", 30),
                # what the AI already handled, so the human sees what they were spared
                "already_attached": [
                    {"label": a["label"], "detail": a.get("detail", "")} for a in auto],
                "already_attached_count": len(auto),
                # what is actually being asked of a person
                "needed": [
                    {"label": e["label"], "produced_by": e["resolved_by"],
                     "needs_patient_visit": e["needs_patient_visit"],
                     "supports_cdt": e.get("service_line_cdt", ""),
                     "why_payer_wants_it": e.get("reason", ""),
                     "why_escalated": e.get("why", "")}
                    for e in escalated],
                "actors_required": routed.get("actors_required", []),
                "patient_must_return": routed.get("patient_must_return", False),
            },
        )

    def on_approved(self, ctx, decision) -> dict:
        routed = ctx.get_result("information_request_router")
        escalated = routed.get("escalated", [])
        return {
            "documents_supplied": True,
            "supplied_by": decision.actor,
            "note": decision.note or "",
            "doc_keys": [e["doc_key"] for e in escalated],
            "labels": [e["label"] for e in escalated],
            "patient_recalled": routed.get("patient_must_return", False),
        }
