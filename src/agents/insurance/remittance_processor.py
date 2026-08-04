"""
Remittance Processor (single task: receive the payer's ERA/EOB response). FULL.

This is the other half of "the clinic requests payment from insurance": claim
submission is the request, this is the response. A real payer sends an X12 835
electronic remittance advice some days after the claim is processed — the sandbox
simulates that response synchronously so the demo stays deterministic, but the
agent itself only reads the port's response, exactly as a real ERA-ingestion
integration would.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class RemittanceProcessor(Agent):
    name = "remittance_processor"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        claim = dict(ctx.get_result("claim_builder").get("claim", {}))
        ack = ctx.get_result("claim_submitter").get("claim_ack", {})

        # If the claim was pended for documentation, the payer adjudicates against what it
        # actually RECEIVED — so the attachment's state has to travel with the claim. A
        # request that went unanswered is what turns a pend into a missing-information
        # denial; a request that was answered lets adjudication finish normally.
        attachment = ctx.get_result("attachment_assembler")
        if attachment:
            claim["attachments_sent_keys"] = [d.get("doc_key", "") for d in
                                              attachment.get("documents", [])]
            claim["adjudication_context"] = {
                **(claim.get("adjudication_context") or {}),
                "documentation_complete": bool(attachment.get("complete", False)),
            }

        remittance = await self.reg.claims.get_remittance(claim, ack.get("control_number", ""))
        return AgentResult.completed({"remittance": remittance.model_dump()})
