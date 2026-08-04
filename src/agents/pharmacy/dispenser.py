"""
Dispenser (single task: dispense the verified medications). FULL.

Runs only if the allergy gate passed and the pharmacist verified. Otherwise skipped.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class Dispenser(Agent):
    name = "dispenser"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        verified = ctx.get_result("pharmacist_verification").get("verified", False)
        gate_ok = ctx.get_result("allergy_gate").get("gate_passed", False)
        if not (verified and gate_ok):
            return AgentResult.completed({"dispensed": False, "reason": "not verified or allergy hard stop"})
        items = ctx.get_result("order_receiver").get("items", [])
        return AgentResult.completed({"dispensed": True, "dispensed_items": items})
