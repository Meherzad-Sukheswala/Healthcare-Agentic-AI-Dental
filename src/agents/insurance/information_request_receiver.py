"""
Information Request Receiver (single task: read the payer's 277RFAI). FULL.

The payer's THIRD possible answer to a claim, and the one this pipeline was missing.
A submitted claim can come back:

  rejected   277CA — bounced on a data fault, never adjudicated       (claim_submitter)
  PENDED     277RFAI — accepted, adjudication STARTED AND STOPPED     (this agent)
  adjudicated 835 ERA — paid or denied                                (remittance_processor)

Pending is not denial. The payer has not refused anything; it is asking for documents and
running a clock. Treating it as a denial sends a biller to file an appeal against a
decision that does not exist yet.

Like `remittance_processor`, this agent only reads what the port returns — a real
integration would poll for or receive the 277RFAI the same way.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class InformationRequestReceiver(Agent):
    name = "information_request_receiver"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        claim = ctx.get_result("claim_builder").get("claim", {})
        ack = ctx.get_result("claim_submitter").get("claim_ack", {})
        request = await self.reg.claims.get_information_request(
            claim, ack.get("control_number", ""))
        if request is None:
            return AgentResult.completed({
                "pended": False,
                "requested": [],
                "payer_trace": [],
            })
        data = request.model_dump()
        return AgentResult.completed({
            "pended": True,
            "information_request": data,
            "requested": data.get("requested", []),
            "reason_summary": data.get("reason_summary", ""),
            "due_date": data.get("due_date", ""),
            "respond_within_days": data.get("respond_within_days", 30),
            "payer_trace": data.get("payer_trace", []),
        })
