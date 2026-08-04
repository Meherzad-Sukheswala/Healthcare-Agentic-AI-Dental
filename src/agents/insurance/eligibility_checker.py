"""Eligibility Checker (single task: X12 270/271 at claim time). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class EligibilityChecker(Agent):
    name = "eligibility_checker"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        cov = await self.reg.eligibility.check(
            ctx.input_data.get("member_id", ""),
            ctx.input_data.get("payer_id", ""),
            ctx.input_data.get("cdt", "D0140"),
        )
        return AgentResult.completed({"coverage": cov.model_dump()})
