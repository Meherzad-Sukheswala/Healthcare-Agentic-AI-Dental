"""
Patient Payment Authorization (single task: patient authorizes the charge). MANUAL.

Always required before any money moves. This fires at CHECKOUT, on the day of
service, against an ESTIMATE — the payer has not adjudicated anything yet and will
not for another 1–2 weeks. Whatever the patient authorizes here is settled later by
billing/reconciliation_statement.py, which may produce a balance statement or a
refund once the 835 ERA lands.

A self-pay patient who also has active coverage is shown TWO options (cash vs.
insured); the choice is carried in the decision note and selects which amount is
charged. Everyone else sees a single bill.
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent


class PatientPaymentAuthorization(HumanGateAgent):
    name = "patient_payment_authorization"
    gate_id = "billing.payment_auth"

    def build_request(self, ctx) -> GateRequest:
        inv = ctx.get_result("invoice_generator")
        return GateRequest(
            gate_id=self.gate_id,
            title="Patient payment authorization (estimate)",
            prompt=("Patient authorizes the ESTIMATED amount due at checkout. "
                    "Insurance has not adjudicated yet — the final balance is settled "
                    "when the payer's remittance arrives."),
            domain="checkout",
            data={
                "invoice_id": inv.get("invoice_id", ""),
                "dual_bill": inv.get("dual_bill", False),
                "bills": inv.get("bill_options", []),
                "line_items": inv.get("line_items", []),
                "tax_cents": inv.get("tax_cents", 0),
            },
        )

    def on_approved(self, ctx, decision) -> dict:
        inv = ctx.get_result("invoice_generator")
        bills = inv.get("bill_options", [])
        choice = (decision.note or "").strip().lower()
        chosen = next((b for b in bills if b.get("label") == choice), None)
        if chosen is None:  # single-bill gate, or no explicit choice — take the default
            chosen = bills[0] if bills else {"label": "single", "amount_cents": inv.get("amount_due_cents", 0)}
        return {
            "payment_authorized": True,
            "authorized_by": decision.actor,
            "chosen_bill": chosen.get("label", "single"),
            "amount_due_cents": chosen.get("amount_cents", 0),
        }
