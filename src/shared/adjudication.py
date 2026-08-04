"""
src/shared/adjudication.py

Shared patient/payer cost-share math (copay -> deductible -> coinsurance).
Used by BOTH the pre-treatment ESTIMATE (billing/bill_splitter.py and
clinical/treatment_cost_estimator.py) and the post-claim ACTUAL remittance
(integrations/sandbox.py SandboxClaims.get_remittance), so the estimate and
the real payer response are computed by the same formula and never drift.
"""
from __future__ import annotations


def adjudicate(billed_cents: int, payer: dict) -> int:
    """Patient cost-share for a commercial/Medicare payer on `billed_cents`.

    Medicaid (payer of last resort, nominal copay only) is handled by callers
    before reaching here — see billing/bill_splitter.py's `_adjudicate_stack`.
    """
    copay = min(int(payer.get("copay_cents", 0)), billed_cents)
    rem = billed_cents - copay
    ded = min(int(payer.get("deductible_remaining_cents", 0)), rem)
    rem -= ded
    coins = int(rem * float(payer.get("coinsurance_pct", 0.0)))
    return copay + ded + coins
