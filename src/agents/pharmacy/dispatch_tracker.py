"""Dispatch Tracker (single task: track the dispatched order). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class DispatchTracker(Agent):
    name = "dispatch_tracker"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        if not ctx.get_result("dispenser").get("dispensed", False):
            return AgentResult.completed({"dispatched": False})
        order_id = ctx.get_result("order_receiver").get("order_id", "")
        dispatch = await self.reg.pharmacy.dispatch(order_id)
        return AgentResult.completed({"dispatched": True, "dispatch": dispatch.model_dump()})
