"""
Pharmacy domain — 9 single-task agents.

  order_receiver          (Surescripts)  receive e-prescription at chosen pharmacy
  stock_checker           (det.)         confirm stock (single pharmacy)
  allergy_gate            (det.)         HARD STOP on drug-allergy conflict
  pdmp_query              (PDMP)         controlled-substance history
  dur_screener            (det.)         OBRA-90 prospective DUR
  pharmacist_verification (HUMAN GATE)   pharmacist verifies the fill (always)
  dispenser               (det.)         dispense (if gate passed + verified)
  dispatch_tracker        (det.)         track dispatch
  audit_logger            (det.)         HIPAA audit trail
"""
from .orchestrator import PharmacyOrchestrator

__all__ = ["PharmacyOrchestrator"]
