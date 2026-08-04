"""
PDMP Query (single task: query the state prescription drug monitoring program). FULL.

Queried for controlled-substance orders; results feed the pharmacist's verification.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class PDMPQuery(Agent):
    name = "pdmp_query"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        items = ctx.get_result("order_receiver").get("items", [])
        has_controlled = any(it.get("controlled") for it in items)
        if not has_controlled:
            return AgentResult.completed({"queried": False, "risk_flags": []})
        report = await self.reg.pdmp.query(ctx.input_data.get("patient_id", ""),
                                           ctx.input_data.get("state", "CA"))
        return AgentResult.completed({"queried": True, "pdmp": report.model_dump(),
                                      "risk_flags": report.risk_flags})
