"""Invoice Generator (single task: produce the patient statement). FULL."""
from __future__ import annotations

import hashlib

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class InvoiceGenerator(Agent):
    name = "invoice_generator"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        split = ctx.get_result("bill_splitter")
        tax = ctx.get_result("tax_engine")
        amount = split.get("patient_responsibility_cents", 0)
        invoice_id = "INV-" + hashlib.sha256(
            f"{ctx.input_data.get('patient_id','')}{ctx.encounter_id}{amount}".encode()).hexdigest()[:10].upper()
        return AgentResult.completed({
            "invoice_id": invoice_id,
            "amount_due_cents": amount,
            "payer_cents": split.get("payer_cents", 0),
            "total_cents": split.get("total_cents", 0),
            "dual_bill": split.get("dual_bill", False),
            "bill_options": split.get("bill_options", []),
            "line_items": tax.get("line_items", []),
            "tax_cents": tax.get("tax_cents", 0),
        })
