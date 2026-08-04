"""
Stock Checker (single task: confirm stock at the chosen pharmacy). FULL.

Checks the one pharmacy's inventory. Out-of-stock items are flagged for
transfer/backorder rather than silently rerouted.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class StockChecker(Agent):
    name = "stock_checker"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        items = ctx.get_result("order_receiver").get("items", [])
        out_of_stock = []
        for it in items:
            if not await self.reg.pharmacy.check_stock(it.get("ndc", "")):
                out_of_stock.append(it.get("ndc"))
        return AgentResult.completed({
            "in_stock": not out_of_stock,
            "out_of_stock_ndcs": out_of_stock,
            "action": "transfer_or_backorder" if out_of_stock else "fill_here",
        })
