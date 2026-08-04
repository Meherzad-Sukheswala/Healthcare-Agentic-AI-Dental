"""
Patient domain (registration & intake) — 9 single-task agents.

  demographics_intake    (EHR)         fetch patient record
  identity_matcher       (EMPI)        probabilistic identity match
  mpi_conflict_resolver  (HUMAN GATE)  MPI steward resolves ambiguity (conditional)
  eligibility_verifier   (270/271)     coverage check
  consent_presenter      (det.)        present consent forms
  consent_signature      (HUMAN GATE)  patient signs consent (always)
  history_fetcher        (EHR)         pull allergies/meds/conditions
  history_reconciliation (partial)     de-dupe + flag for clinician confirm
  audit_logger           (det.)        HIPAA audit trail
"""
from .orchestrator import PatientOrchestrator

__all__ = ["PatientOrchestrator"]
