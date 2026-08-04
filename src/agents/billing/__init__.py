"""
Billing / RCM domain — 12 single-task agents across TWO phases, because a US dental
practice bills the patient twice: once from an estimate at checkout, and again from
the payer's actual response weeks later.

PHASE 1 — CheckoutOrchestrator (same day, before the claim goes out)
  fee_calculator                (det.)        total charges
  tax_engine                    (det.)        apply tax (services exempt)
  coverage_coordinator          (det.)        coordination of benefits / payer order
  bill_splitter                 (det.)        payer vs patient split — ESTIMATE mode
                                               here (no remittance exists yet)
  charge_coding_qa              (HUMAN GATE)  CDI/coder review (conditional, high cost)
  invoice_generator             (det.)        walkout statement / estimate
  patient_payment_authorization (HUMAN GATE)  patient authorizes payment (always)
  payment_processor             (det.)        charge via payment port
  audit_logger                  (det.)        HIPAA audit trail

PHASE 2 — ReconciliationOrchestrator (1–2 weeks later, after the 835 ERA)
  reconciliation_statement      (det.)        estimate vs actual -> balance or refund
  denial_detector               (det.)        reads the real remittance status (835 ERA)
  denial_appeal_handler         (HUMAN GATE)  biller appeals, sees the CARC codes (conditional)
  audit_logger                  (det.)        HIPAA audit trail

See docs/us-dental-clinic-real-world-workflow.md §0.1 and §8 for why the split exists.
"""
from .orchestrator import CheckoutOrchestrator
from .reconciliation_orchestrator import ReconciliationOrchestrator

__all__ = ["CheckoutOrchestrator", "ReconciliationOrchestrator"]
