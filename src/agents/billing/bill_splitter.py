"""
Bill Splitter (single task: adjudicate patient vs payer responsibility with COB). FULL.

Insurance adjudicates ONLY the professional service charge:
  commercial / medicare : copay -> remaining deductible -> coinsurance % on the rest
  medicaid              : payer of last resort — nominal copay, patient owes ~$0

When a real remittance is available (single-payer, non-COB path — see
insurance/remittance_processor.py), adjudication runs against the payer's actual
ALLOWED amount, not the raw billed charge — the contractual write-off a negotiated
rate produces (see docs/deductible-system-american-healthcare.md) is now modeled,
not ignored. Without a remittance (e.g. self-pay, or a COB stack this simulation
doesn't model payer responses for), the raw billed charge is used as before.

Ancillary/retail line items and their tax are patient out-of-pocket and are added
on top of whatever the service adjudication leaves (insurance does not pay for a
patient's retail purchase).

Self-pay handling:
  * self-pay WITH active coverage  -> TWO bill options (cash vs insured); the patient
                                      chooses one at the payment-authorization gate.
  * self-pay WITHOUT coverage / uninsured -> a single cash bill.
  * using insurance                -> a single insured bill.
"""
from __future__ import annotations

from src.config import get_settings
from src.core.orchestrator import Agent, AgentResult
from src.shared.adjudication import adjudicate
from src.shared.enums import Automation


def _adjudicate_detail(billed: int, payer: dict) -> dict:
    """Itemized cost-share breakdown for the primary payer (for UI transparency)."""
    copay = min(int(payer.get("copay_cents", 0)), billed)
    rem = billed - copay
    ded_before = int(payer.get("deductible_remaining_cents", 0))
    ded = min(ded_before, rem)
    rem -= ded
    coins_pct = float(payer.get("coinsurance_pct", 0.0))
    coins = int(rem * coins_pct)
    return {
        "copay_cents": copay,
        "deductible_applied_cents": ded,
        "deductible_remaining_before_cents": ded_before,
        "deductible_remaining_after_cents": ded_before - ded,
        "coinsurance_pct": coins_pct,
        "coinsurance_cents": coins,
        "patient_owed_cents": copay + ded + coins,
    }


def _adjudicate_stack(service: int, stack: list[dict]) -> tuple[int, list[dict]]:
    owed = service
    breakdown = []
    for payer in stack:
        ptype = payer.get("payer_type", "commercial")
        before = owed
        if ptype == "medicaid":
            owed = min(int(payer.get("copay_cents", 0)), owed)
        else:  # commercial / medicare
            owed = adjudicate(owed, payer)
        breakdown.append({"payer": ptype, "paid_cents": before - owed})
    return owed, breakdown


class BillSplitter(Agent):
    name = "bill_splitter"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        fee = ctx.get_result("fee_calculator")
        service = int(fee.get("service_cents", fee.get("total_cents", 0)))
        items_cents = int(fee.get("items_cents", 0))
        tax_cents = int(ctx.get_result("tax_engine").get("tax_cents", 0))
        addons = items_cents + tax_cents           # patient out-of-pocket, never insured
        total_gross = service + addons

        coord = ctx.get_result("coverage_coordinator")
        stack = coord.get("payer_stack", [])
        has_coverage = not coord.get("is_self_pay", not stack)
        self_pay_intent = bool(ctx.input_data.get("self_pay", False))

        # a real remittance (single-payer only — this simulation doesn't produce
        # payer responses for a secondary/tertiary COB stack) supplies the actual
        # contracted allowed amount in place of the raw billed charge
        remittance = ctx.input_data.get("remittance", {}) or {}
        write_off_cents = 0
        insured_service = service
        if remittance and len(stack) == 1 and stack[0].get("payer_type") in ("commercial", "medicare"):
            insured_service = int(remittance.get("allowed_cents", service))
            write_off_cents = max(0, service - insured_service)

        discount = ctx.input_data.get("self_pay_discount_pct")
        if discount is None:
            discount = get_settings().self_pay_discount_pct
        discount = float(discount)

        # cash / self-pay bill (full service minus prompt-pay discount, plus addons)
        cash_service = int(service * (1 - discount))
        cash_bill = {
            "label": "self_pay", "name": "Self-pay (cash)",
            "amount_cents": cash_service + addons, "service_share_cents": cash_service,
            "items_cents": items_cents, "tax_cents": tax_cents,
            "self_pay_discount_cents": (service - cash_service) if discount else 0,
            "payer_cents": 0,
            "detail": {
                "service_cents": service,
                "self_pay_discount_cents": service - cash_service,
                "items_cents": items_cents, "tax_cents": tax_cents,
            },
        }

        # insured bill (only meaningful with active coverage)
        insured_bill = None
        if has_coverage:
            owed, breakdown = _adjudicate_stack(insured_service, stack)
            detail = _adjudicate_detail(insured_service, stack[0]) if stack else {}
            detail.update({
                "service_cents": service, "allowed_cents": insured_service,
                "contractual_write_off_cents": write_off_cents,
                "items_cents": items_cents, "tax_cents": tax_cents,
                "insurer_pays_cents": insured_service - owed,
                "plan": stack[0].get("plan", "") if stack else "",
            })
            insured_bill = {
                "label": "insured", "name": "With insurance",
                "amount_cents": owed + addons, "service_share_cents": owed,
                "items_cents": items_cents, "tax_cents": tax_cents,
                "payer_cents": insured_service - owed, "breakdown": breakdown, "detail": detail,
            }

        if self_pay_intent and has_coverage:
            options, chosen, dual, is_self_pay = [cash_bill, insured_bill], cash_bill, True, True
        elif self_pay_intent or not has_coverage:
            options, chosen, dual, is_self_pay = [cash_bill], cash_bill, False, True
        else:
            options, chosen, dual, is_self_pay = [insured_bill], insured_bill, False, False

        return AgentResult.completed({
            "total_cents": total_gross,
            "patient_responsibility_cents": chosen["amount_cents"],
            "payer_cents": chosen.get("payer_cents", 0),
            "is_self_pay": is_self_pay,
            "is_dual_eligible": coord.get("is_dual_eligible", False),
            "dual_bill": dual,
            "bill_options": options,
            "breakdown": chosen.get("breakdown", []),
        })
