# The Deductible System in American Healthcare

American health insurance splits the cost of care between the patient and the insurer using four moving parts that apply in a specific order: the **premium**, the **deductible**, **copays/coinsurance**, and the **out-of-pocket maximum**. The deductible is the hinge the whole system turns on.

## The core components

**Premium.** What the patient (or their employer) pays every month just to have the plan, regardless of whether any care is used. It is separate from everything below — paying premiums does *not* count toward the deductible.

**Deductible.** The amount the patient must pay out of pocket for covered care each year *before* the insurer starts paying its share. With a $2,000 deductible, the patient pays the first $2,000 of covered services themselves. Until that number is reached, the insurer mainly provides access to its negotiated prices rather than paying anything.

**Copay.** A flat fee for a specific service (e.g., $30 for a doctor visit), paid regardless of the total charge.

**Coinsurance.** A percentage split that applies *after* the deductible is met — e.g., the patient pays 20% and the insurer 80% of each covered charge.

**Out-of-pocket (OOP) maximum.** The annual safety cap — the most the patient will pay for covered, in-network care in a year. Once combined deductible + copays + coinsurance reach this ceiling, the insurer pays 100% for the rest of the year. Premiums do not count toward it.

**Allowed amount (negotiated / in-network rate).** Insurers contract with providers for discounted prices. The deductible and coinsurance are calculated against this negotiated rate, not the provider's sticker price. Even when the insurer pays $0 (deductible not met), the patient typically owes the *lower negotiated rate* — a key reason an insured bill and a cash bill usually differ. Going **out-of-network** removes this: no negotiated rate, often a separate higher deductible, and possible "balance billing" for the difference.

## How a single claim is adjudicated (order of operations)

```
Provider charge
   → Insurer reprices to the ALLOWED (negotiated) amount
   → Patient pays COPAY
   → Remainder applies to REMAINING DEDUCTIBLE
   → Once deductible is exhausted, COINSURANCE splits further charges (e.g., 20% / 80%)
   → All patient payments accumulate toward the OUT-OF-POCKET MAX
   → After OOP max is reached, insurer pays 100% for the rest of the plan year
```

All counters (deductible, OOP max) **reset at the start of each plan year**, which is why the same care can be nearly free in December but cost full price in January.

## Why "insured" and "cash" bills can be identical

When a patient has not met their deductible, a small charge falls entirely inside the deductible, so the insurer pays $0 and the patient owes the whole amount — the same as paying cash. This is realistic and is exactly why people with high-deductible plans sometimes just pay cash: the insurance "price" isn't lower until the deductible is met. If the charge exceeds copay + remaining deductible, coinsurance kicks in, the insurer pays a share, and the two bills diverge.

Two real-world nuances would normally still make them differ: the **negotiated allowed amount** (patient owes the lower contracted rate, not the sticker price) and a **prompt-pay/cash discount** (which can make cash cheaper).

## Plan types and government programs

**High-Deductible Health Plan (HDHP).** Low premiums but a large deductible (often several thousand dollars); the patient pays most routine costs until the deductible is met. Pairs with a **Health Savings Account (HSA)** — a tax-advantaged account funded with pre-tax dollars to pay those out-of-pocket costs. HDHPs are precisely where paying cash can match or beat using insurance for small charges.

**Medicare Part B.** Has its own annual deductible, then 20% coinsurance, with no out-of-pocket cap on its own (which is why many buy supplemental "Medigap" coverage).

**Medicaid.** Little or no deductible and only nominal copays; acts as the payer of last resort, so the patient typically owes almost nothing.

## How this maps to the demo

The billing pipeline's bill splitter follows the real adjudication order (**copay → remaining deductible → coinsurance**). The sandbox payer types reflect the above: commercial PPO ($30 copay, 20% coinsurance, remaining deductible), Medicare Part B (deductible then 20% coinsurance), Medicaid (nominal copay, patient owes ~$0), and self-pay/uninsured (full charge minus any prompt-pay discount).

The negotiated **allowed amount** is now modeled too: `insurance/remittance_processor.py` simulates the payer's X12 835 remittance applying a flat 20% in-network contractual write-off for commercial claims before the copay → deductible → coinsurance math runs, with the write-off itself reported as a CARC 45 adjustment ("charge exceeds fee schedule"). `billing/bill_splitter.py` adjudicates against that real allowed amount rather than the raw billed charge once a remittance exists — so a small-charge insured bill and cash bill no longer come out equal by construction; the still-open gap is a **prompt-pay/cash discount**, which is provider-configurable (`SELF_PAY_DISCOUNT_PCT`) but defaults to 0.
