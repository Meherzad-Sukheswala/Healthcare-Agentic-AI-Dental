"""
Clinical domain — 19 single-task agents (5 LLM, 5 human gates).

  symptom_recorder          (LLM)         structure the chief complaint
  critical_value_detector   (det.)        flag panic labs
  critical_value_notifier   (HUMAN GATE)  clinician acknowledges (conditional)
  diagnosis_suggester       (LLM)         AI differential + draft chart note
  diagnosis_signoff         (HUMAN GATE)  dentist edits and SIGNS the chart note (always)
  clinical_note_transcriber (LLM)         signed prose -> per-tooth diagnoses + findings
  treatment_plan_builder    (partial)     draft procedures for the diagnosis
  treatment_plan_review     (HUMAN GATE)  dentist confirms the plan (conditional)
  treatment_cost_estimator  (det.)        chairside patient-vs-insurer estimate
  treatment_plan_consent    (HUMAN GATE)  patient accepts/declines items (conditional)
  prescription_drafter      (partial)     draft prescriptions
  drug_interaction_checker  (det.)        DDI screen
  allergy_checker           (det.)        drug-allergy screen
  procedure_documentor      (det.)        record what was actually billable today
  diagnosis_coder           (partial)     ICD-10 per procedure line + ADA 29a pointers
  claim_narrative_writer    (LLM)         per-tooth narrative for the payer's consultant
  controlled_rx_epcs_signer (HUMAN GATE)  DEA EPCS 2-factor sign (conditional)
  ehr_writer                (det.)        persist the dentist's signed note
  audit_logger              (det.)        HIPAA audit trail

The documentation -> claim chain is diagnosis_signoff -> clinical_note_transcriber ->
(treatment plan) -> procedure_documentor -> diagnosis_coder + claim_narrative_writer.
See orchestrator.py for why that ordering is what it is.
"""
from .orchestrator import ClinicalOrchestrator

__all__ = ["ClinicalOrchestrator"]
