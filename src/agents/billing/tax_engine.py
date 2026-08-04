"""
Tax Engine (single task: apply tax to NON-EXEMPT line items only). FULL.

Professional medical services and exempt items (e.g. prescriptions) are never
taxed. Tax is applied ONLY to ancillary/retail line items explicitly flagged
`taxable` (e.g. retail supplies, OTC products, taxable DME), at the configured
sales-tax rate. Each item is taxed individually, so exempt and taxable items can
sit side by side on the same bill.
"""
from __future__ import annotations

from src.config import get_settings
from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class TaxEngine(Agent):
    name = "tax_engine"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        rate = float(get_settings().sales_tax_pct)
        items = ctx.input_data.get("retail_items", []) or []
        lines, tax_total = [], 0
        for it in items:
            amount = int(it.get("amount_cents", 0))
            taxable = bool(it.get("taxable", False))
            tax = int(round(amount * rate)) if taxable else 0
            tax_total += tax
            lines.append({
                "description": it.get("description", "item"),
                "amount_cents": amount,
                "taxable": taxable,
                "tax_cents": tax,
            })
        return AgentResult.completed({
            "tax_cents": tax_total,
            "rate": rate,
            "line_items": lines,
            "taxable": tax_total > 0,
        })
