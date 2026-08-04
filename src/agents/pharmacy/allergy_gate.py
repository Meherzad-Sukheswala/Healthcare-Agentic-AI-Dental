"""
Allergy Gate (single task: deterministic HARD STOP on drug-allergy conflict). FULL.

Not a human gate — a deterministic safety block. If a conflict is found, gate_passed
is False and downstream dispensing is skipped entirely.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class AllergyGate(Agent):
    name = "allergy_gate"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        allergies = list(ctx.input_data.get("allergies", []) or [])
        conflicts = []
        for it in ctx.get_result("order_receiver").get("items", []):
            hits = await self.reg.drug_info.cross_allergies(it.get("rxcui", ""), allergies)
            if hits:
                conflicts.append({"ndc": it.get("ndc"), "rxcui": it.get("rxcui"), "allergens": hits})
        return AgentResult.completed({"gate_passed": not conflicts, "conflicts": conflicts})
