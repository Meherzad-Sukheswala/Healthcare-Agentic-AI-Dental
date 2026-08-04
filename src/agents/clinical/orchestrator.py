"""
ClinicalOrchestrator — wires the 19 single-task clinical agents.

Order: Symptom Recorder -> Critical-Value Detector -> [Critical-Value Notifier gate,
       if panic value] -> Diagnosis Suggester -> **Diagnosis Sign-off (gate)** ->
       **Clinical Note Transcriber** -> Treatment Plan Builder -> [Treatment Plan
       Review gate, if a procedure was recommended] -> Treatment Cost Estimator ->
       [Treatment Plan Consent gate, if a procedure was recommended] -> Prescription
       Drafter -> Drug Interaction Checker -> Allergy Checker -> Procedure Documentor
       -> **Diagnosis Coder** -> **Claim Narrative Writer** -> [Controlled-Rx EPCS
       Signer gate, if controlled] -> EHR Writer -> Audit Logger

THE DOCUMENTATION -> CLAIM CHAIN
--------------------------------
Three steps do the work the dentist is buying, and their order is deliberate:

  1. `diagnosis_signoff` — the dentist is handed a pre-filled chart note (dictation /
     ambient-scribe output), edits it, and signs. The signed prose is the artifact.
  2. `clinical_note_transcriber` — AI turns that prose into structured per-tooth
     diagnoses and measurable findings. It runs BEFORE the treatment plan because the
     plan keys off the confirmed diagnosis and uses the tooth the dentist named.
  3. `diagnosis_coder` + `claim_narrative_writer` — both run AFTER
     `procedure_documentor`, because they describe what was actually PERFORMED, not
     what was proposed. The coder emits per-line diagnosis pointers (ADA item 29a);
     the narrative writer emits the per-tooth justification a payer's consultant
     reads.

Diagnosing a problem and deciding how to treat it are different clinical decisions,
so they're different gates: a dentist can agree on the diagnosis but want to change
the plan, and a patient can accept part of a phased plan and defer the rest.

Safety-critical: failures abort. Up to five human gates may fire in one encounter.
"""
from __future__ import annotations

from src.agents.common import AuditLogger
from src.core.orchestrator import DomainOrchestrator, PipelineStep

from .allergy_checker import AllergyChecker
from .claim_narrative_writer import ClaimNarrativeWriter
from .clinical_note_transcriber import ClinicalNoteTranscriber
from .controlled_rx_epcs_signer import ControlledRxEPCSSigner
from .critical_value_detector import CriticalValueDetector
from .critical_value_notifier import CriticalValueNotifier
from .diagnosis_coder import DiagnosisCoder
from .diagnosis_signoff import DiagnosisSignoff
from .diagnosis_suggester import DiagnosisSuggester
from .drug_interaction_checker import DrugInteractionChecker
from .ehr_writer import EHRWriter
from .imaging_recorder import ImagingRecorder
from .prescription_drafter import PrescriptionDrafter
from .procedure_documentor import ProcedureDocumentor
from .symptom_recorder import SymptomRecorder
from .treatment_cost_estimator import TreatmentCostEstimator
from .treatment_plan_builder import TreatmentPlanBuilder
from .treatment_plan_consent import TreatmentPlanConsent
from .treatment_plan_review import TreatmentPlanReview


class ClinicalOrchestrator(DomainOrchestrator):
    name = "clinical"
    abort_on_fail = True

    def build_steps(self):
        return [
            PipelineStep(SymptomRecorder(self.llm)),
            PipelineStep(CriticalValueDetector()),
            PipelineStep(
                CriticalValueNotifier(),
                condition=lambda ctx: ctx.get_result("critical_value_detector").get("has_critical", False),
            ),
            PipelineStep(DiagnosisSuggester(self.llm)),
            PipelineStep(DiagnosisSignoff()),
            PipelineStep(ClinicalNoteTranscriber(self.llm)),
            PipelineStep(TreatmentPlanBuilder()),
            PipelineStep(
                TreatmentPlanReview(),
                condition=lambda ctx: ctx.get_result("treatment_plan_builder").get(
                    "has_recommended_treatment", False),
            ),
            PipelineStep(TreatmentCostEstimator()),
            PipelineStep(
                TreatmentPlanConsent(),
                condition=lambda ctx: ctx.get_result("treatment_plan_builder").get(
                    "has_recommended_treatment", False),
            ),
            PipelineStep(PrescriptionDrafter()),
            PipelineStep(DrugInteractionChecker(self.registry)),
            PipelineStep(AllergyChecker(self.registry)),
            PipelineStep(ProcedureDocumentor()),
            PipelineStep(ImagingRecorder()),
            PipelineStep(DiagnosisCoder()),
            PipelineStep(ClaimNarrativeWriter(self.llm)),
            PipelineStep(
                ControlledRxEPCSSigner(self.registry),
                condition=lambda ctx: ctx.get_result("prescription_drafter").get("has_controlled", False),
            ),
            PipelineStep(EHRWriter(self.registry)),
            PipelineStep(AuditLogger(domain="clinical")),
        ]

    def build_output(self, ctx) -> dict:
        proc = ctx.get_result("procedure_documentor")
        signoff = ctx.get_result("diagnosis_signoff")
        transcript = ctx.get_result("clinical_note_transcriber")
        coder = ctx.get_result("diagnosis_coder")
        narrative = ctx.get_result("claim_narrative_writer")
        return {
            "symptoms": ctx.get_result("symptom_recorder").get("symptoms", []),
            "diagnosis": signoff,
            # ---- the documentation -> claim chain ----
            "clinical_note": signoff.get("clinical_note", ""),
            "note_signed_by": signoff.get("dentist", ""),
            "transcription": transcript,
            "diagnoses": transcript.get("diagnoses", []),
            "findings": transcript.get("findings", {}),
            "icd10": coder.get("icd10", ""),                       # principal, backward-compat
            "diagnosis_codes": coder.get("diagnosis_codes", []),   # ADA item 34a
            "line_diagnoses": coder.get("line_diagnoses", []),     # ADA item 29a pointers
            "diagnosis_submission_required": coder.get("submission_required", False),
            "diagnosis_submission_reason": coder.get("submission_reason", ""),
            "narratives": narrative.get("narratives", []),
            "attachments_recommended": narrative.get("attachments_recommended", []),
            # ---- the documentation this visit actually captured ----
            # Feeds the document registry, so "the AI found the film and attached it" is a
            # statement about a real artifact rather than an assumption.
            "imaging": ctx.get_result("imaging_recorder"),
            # ---- plan, procedures, prescriptions ----
            "treatment_plan": ctx.get_result("treatment_plan_builder"),
            "treatment_plan_review": ctx.get_result("treatment_plan_review"),
            "cost_estimate": ctx.get_result("treatment_cost_estimator"),
            "treatment_consent": ctx.get_result("treatment_plan_consent"),
            "performed_items": proc.get("performed_items", []),
            "cdt": proc.get("cdt", ""),
            "cdt_codes": proc.get("cdt_codes", []),
            "procedure_total_cents": proc.get("total_cents", 0),
            "prescriptions": ctx.get_result("prescription_drafter").get("prescriptions", []),
            "interactions": ctx.get_result("drug_interaction_checker"),
            "allergy": ctx.get_result("allergy_checker"),
            "epcs": ctx.get_result("controlled_rx_epcs_signer"),
            "critical": ctx.get_result("critical_value_detector"),
            "document_ref": ctx.get_result("ehr_writer").get("document_ref", ""),
            "audit": ctx.get_result("audit_logger").get("audit", {}),
        }
