"""Payment Processor (single task: charge the authorized amount). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class PaymentProcessor(Agent):
    name = "payment_processor"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        auth = ctx.get_result("patient_payment_authorization")
        if not auth.get("payment_authorized"):
            return AgentResult.completed({"payment": {"status": "not_authorized"}, "processed": False})
        # Charge the bill the patient actually chose (cash vs. insured); fall back to invoice.
        amount = auth.get("amount_due_cents")
        if amount is None:
            amount = ctx.get_result("invoice_generator").get("amount_due_cents", 0)
        if amount <= 0:
            return AgentResult.completed({"payment": {"status": "no_balance", "amount_cents": 0}, "processed": True})
        res = await self.reg.payment.charge(amount, ctx.input_data.get("payment_token", ""))
        return AgentResult.completed({"payment": res.model_dump(), "processed": res.status == "succeeded"})
