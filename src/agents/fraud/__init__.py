"""
Fraud Detection domain — 8 single-task agents (parallel observer, NEVER blocks).

  claim_analyzer           (det.)         upcoding / claim signals
  prescription_analyzer    (det.)         controlled / PDMP signals
  billing_anomaly_detector (det.)         charge outliers / duplicates
  consistency_checker      (LLM)          dx/med consistency (graceful fallback)
  risk_scorer              (det.)         aggregate 0-100 risk score
  alert_generator          (det.)         raise SIU alert above threshold
  siu_investigator_review  (HUMAN, non-blocking)  queues for out-of-band review
  audit_logger             (det.)         HIPAA audit trail

pipeline_blocked is ALWAYS False.
"""
from .orchestrator import FraudDetectionOrchestrator

__all__ = ["FraudDetectionOrchestrator"]
