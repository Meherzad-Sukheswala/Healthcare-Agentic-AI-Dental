"""
src/core/pipeline/encounter.py

EncounterResult — the aggregate result of a full end-to-end encounter across all
seven domains, plus the encounter-wide status and the human gate it's waiting on
(if any).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EncounterResult:
    encounter_id: str
    patient_id: str = ""
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "completed"                 # completed | awaiting_human | partial | failed
    awaiting_domain: str = ""
    awaiting_gate: Any = None                  # GateRequest when paused
    partial: bool = False
    domains: dict[str, dict] = field(default_factory=dict)   # name -> {status, output}
    recall: dict = field(default_factory=dict)                # post-visit recare recommendation

    def record(self, name: str, dr) -> None:
        self.domains[name] = {"status": dr.status.value, "output": dr.output,
                              "gate": dr.gate.model_dump() if dr.gate else None,
                              "errors": dr.errors}

    def _out(self, domain: str) -> dict:
        return self.domains.get(domain, {}).get("output", {})

    @property
    def summary(self) -> dict:
        sched, clin, checkout, ins, recon, pharm, fraud = (
            self._out("scheduling"), self._out("clinical"), self._out("checkout"),
            self._out("insurance"), self._out("reconciliation"), self._out("pharmacy"),
            self._out("fraud"),
        )
        return {
            "encounter_id": self.encounter_id,
            "status": self.status,
            "awaiting": (self.awaiting_gate.model_dump() if self.awaiting_gate else None),
            "provider": sched.get("provider_name", ""),
            "appointment_id": sched.get("appointment", {}).get("appointment_id", ""),
            "eligibility_verified": sched.get("eligibility_verified", False),
            "diagnosis_icd10": clin.get("icd10", ""),
            "cdt": clin.get("cdt", ""),
            # ---- the signed note, and what the AI made of it ----
            "clinical_note": clin.get("clinical_note", ""),
            "note_signed_by": clin.get("note_signed_by", ""),
            "coding": {
                "diagnoses": clin.get("diagnoses", []),
                "diagnosis_codes": clin.get("diagnosis_codes", []),
                "line_diagnoses": clin.get("line_diagnoses", []),
                "submission_required": clin.get("diagnosis_submission_required", False),
                "submission_reason": clin.get("diagnosis_submission_reason", ""),
                "narratives": clin.get("narratives", []),
                "attachments_recommended": clin.get("attachments_recommended", []),
                "findings": clin.get("findings", {}),
            },
            # --- what happened at checkout (estimate) ---
            "amount_due_cents": checkout.get("amount_due_cents"),
            "collected_cents": checkout.get("collected_cents"),
            "payment_status": checkout.get("payment", {}).get("status"),
            # --- what the payer actually said (post-visit) ---
            # Two distinct failure modes, deliberately reported separately:
            #   claim_rejected  277CA bounced it on a data problem, never adjudicated,
            #                   NOT appealable — fix the element and resubmit
            #   denial_*        835 ERA adjudicated and refused, with a reason that
            #                   decides whether to appeal, resubmit, bill or write off
            "claim_accepted": ins.get("claim_accepted"),
            "claim_rejected": ins.get("claim_rejected", False),
            "rejections": ins.get("rejections", []),
            "rejection_handling": ins.get("rejection_handling", {}),
            "claim_status": ins.get("remittance", {}).get("status"),
            # where the claim actually got to, so the UI can show a stage rather than "done"
            "claim_stage": ins.get("claim_stage", ""),
            # the full clinic <-> payer conversation, including payer-side rows flagged
            # `simulated_internal` because a practice cannot see inside adjudication
            "exchange": ins.get("exchange", []),
            # --- the payer asked for documentation (277RFAI) ---
            "pended": ins.get("pended", False),
            "documents_requested": ins.get("documents_requested", []),
            "documents_auto_satisfied": ins.get("documents_auto_satisfied", []),
            "documents_escalated": ins.get("documents_escalated", []),
            "document_routing_summary": ins.get("document_routing", {}).get("summary", ""),
            "document_response_fully_automated": ins.get("document_response_fully_automated", False),
            "documents_supplied_by_staff": ins.get("documents_supplied_by_staff", {}),
            "attachment": ins.get("attachment", {}),
            "attachment_control_number": ins.get("attachment_control_number", ""),
            "denial_reason": recon.get("denial_reason", ""),
            "denial_action": recon.get("recommended_action", ""),
            "denial_explanation": recon.get("denial", {}).get("explanation", ""),
            "denied": recon.get("denied", False),
            "downgraded": recon.get("downgraded", False),
            "carc_codes": recon.get("denial", {}).get("carcs", []),
            "appeal": recon.get("appeal", {}),
            # --- the settle-up ---
            "reconciliation_outcome": recon.get("outcome"),
            "actual_patient_cents": recon.get("actual_patient_cents"),
            "balance_due_cents": recon.get("balance_due_cents"),
            "refund_due_cents": recon.get("refund_due_cents"),
            "estimate_variance_cents": recon.get("estimate_variance_cents"),
            "write_off_cents": recon.get("write_off_cents"),
            "dispensed": pharm.get("dispensed"),
            "dispatch_tracking": pharm.get("dispatch", {}).get("dispatch", {}).get("tracking", ""),
            "fraud_risk": fraud.get("risk_score"),
            "fraud_alert": fraud.get("alert"),
            "recall_due_date": self.recall.get("recall_due_date"),
            "recall_interval_months": self.recall.get("recall_interval_months"),
        }
