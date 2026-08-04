"""Formulary Checker (single task: plan drug-coverage lookup). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class FormularyChecker(Agent):
    name = "formulary_checker"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        payer = ctx.input_data.get("payer_id", "")
        ndcs = ctx.input_data.get("ndcs", []) or []
        results, any_pa = [], False
        for ndc in ndcs:
            fs = await self.reg.drug_info.formulary(payer, ndc)
            any_pa = any_pa or fs.prior_auth_required
            results.append({"ndc": ndc, **fs.model_dump()})
        return AgentResult.completed({"formulary": results, "any_pa_required": any_pa})
