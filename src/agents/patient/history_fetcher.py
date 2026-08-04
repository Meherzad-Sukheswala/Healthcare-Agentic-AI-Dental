"""History Fetcher (single task: pull allergies/meds/conditions from the record). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class HistoryFetcher(Agent):
    name = "history_fetcher"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        demo = ctx.get_result("demographics_intake")
        return AgentResult.completed({
            "allergies": demo.get("allergies", []),
            "medications": demo.get("medications", []),
            "conditions": demo.get("conditions", []),
        })
