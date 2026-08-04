"""Allergy Checker (single task: deterministic drug-allergy screen). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class AllergyChecker(Agent):
    name = "allergy_checker"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        allergies = list(ctx.input_data.get("allergies", []) or [])
        conflicts = []
        for p in ctx.get_result("prescription_drafter").get("prescriptions", []):
            hits = await self.reg.drug_info.cross_allergies(p.get("rxcui", ""), allergies)
            if hits:
                conflicts.append({"rx_id": p.get("rx_id"), "rxcui": p.get("rxcui"), "allergens": hits})
        return AgentResult.completed({"allergy_conflicts": conflicts, "has_conflict": bool(conflicts)})
