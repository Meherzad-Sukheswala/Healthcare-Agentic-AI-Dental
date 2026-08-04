"""
Insurance domain — 9 single-task agents.

  eligibility_checker         (270/271)     coverage at claim time
  formulary_checker           (det.)        drug coverage
  predetermination_submitter  (278)         submit predetermination (advisory, dental)
  predetermination_review     (HUMAN GATE)  payer clinical reviewer (conditional)
  claim_builder                (837D)       assemble multi-line claim
  claim_submitter              (det.)       transmit claim — the request for payment
  remittance_processor         (835)        the payer's ERA response — what they paid, and why
  payment_reconciler           (det.)       compare paid vs billed, flag follow-up
  audit_logger                 (det.)       HIPAA audit trail
"""
from .orchestrator import InsuranceOrchestrator

__all__ = ["InsuranceOrchestrator"]
