"""
Audit Logger (single task: write a domain's HIPAA audit trail).

One implementation, instantiated per domain with its name. Records which agents
ran for the encounter so the full pipeline is traceable end to end.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.base_types import utcnow
from src.shared.enums import Automation


class AuditLogger(Agent):
    name = "audit_logger"
    automation = Automation.FULL

    def __init__(self, domain: str):
        self.domain = domain

    async def execute(self, ctx) -> AgentResult:
        steps = [k for k in ctx.results.keys() if k != self.name]
        return AgentResult.completed({
            "audit": {
                "domain": self.domain,
                "encounter_id": ctx.encounter_id,
                "steps_recorded": steps,
                "at": utcnow().isoformat(),
            }
        })
