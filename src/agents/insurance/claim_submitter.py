"""Claim Submitter (single task: transmit the 837 claim to the payer). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class ClaimSubmitter(Agent):
    name = "claim_submitter"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        claim = ctx.get_result("claim_builder").get("claim", {})
        ack = await self.reg.claims.submit_claim(claim)
        return AgentResult.completed({"claim_ack": ack.model_dump()})
