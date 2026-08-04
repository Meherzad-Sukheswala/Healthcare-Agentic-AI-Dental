"""Drug Interaction Checker (single task: deterministic DDI screen). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation, Severity


class DrugInteractionChecker(Agent):
    name = "drug_interaction_checker"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        current = list(ctx.input_data.get("current_medications", []) or [])
        prescribed = [p.get("rxcui", "") for p in ctx.get_result("prescription_drafter").get("prescriptions", [])]
        rxcuis = [r for r in current + prescribed if r]
        interactions = await self.reg.drug_info.interactions(rxcuis)
        unsafe = any(i.severity in (Severity.SEVERE, Severity.CONTRAINDICATED) for i in interactions)
        return AgentResult.completed({
            "interactions": [i.model_dump() for i in interactions],
            "unsafe": unsafe,
        })
