"""
Availability Finder (single task: gather open slots across matched doctors). FULL.

Queries each candidate doctor's calendar and builds a combined, numbered list of
open appointment options for the patient to choose from.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class AvailabilityFinder(Agent):
    name = "availability_finder"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        candidates = ctx.get_result("provider_matcher").get("candidates", [])[:3]
        options, i = [], 0
        for c in candidates:
            name = f"{c.get('first_name','')} {c.get('last_name','')}".strip() or c.get("provider_name", "")
            for slot in await self.reg.schedule.availability(c.get("npi", ""), limit=3):
                options.append({
                    "id": str(i), "npi": c.get("npi", ""), "provider_name": name,
                    "facility": c.get("facility", ""),
                    "start": slot["start"], "duration_min": slot["duration_min"],
                })
                i += 1
        if not options:
            return AgentResult.failed("no appointment availability for matched providers")
        return AgentResult.completed({"slot_options": options})
