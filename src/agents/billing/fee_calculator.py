"""Fee Calculator (single task: total the charges). FULL.

Separates the professional service charge (adjudicated by insurance) from any
ancillary/retail line items the patient buys out of pocket, so the bill splitter
can run insurance only against the service and add items + tax on top.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class FeeCalculator(Agent):
    name = "fee_calculator"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        service = int(ctx.input_data.get("charge_cents", 0))
        items = ctx.input_data.get("retail_items", []) or []
        items_total = sum(int(i.get("amount_cents", 0)) for i in items)
        return AgentResult.completed({
            "service_cents": service,
            "items_cents": items_total,
            "total_cents": service + items_total,
        })
