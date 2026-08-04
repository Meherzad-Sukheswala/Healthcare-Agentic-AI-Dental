"""
Attachment Assembler (single task: build and transmit the X12 275). FULL.

Sends the documentation back to the payer so adjudication can resume. Two real mechanics
this models, both of which practices get wrong:

PWK WITHOUT A PAYLOAD IS WORSE THAN NOTHING
-------------------------------------------
The PWK segment on the 837 declares "an attachment is coming". Some payers will stall a
claim INDEFINITELY waiting for a promised attachment that never arrives — a state that is
strictly worse than never having claimed one, because the claim neither pays nor denies
and nothing prompts anyone to look at it. So this agent emits a PWK segment only for a
document it is actually transmitting, and reports anything it could not send as
`outstanding` rather than quietly promising it.

THE ATTACHMENT CONTROL NUMBER IS THE JOIN KEY
--------------------------------------------
`attachment_control_number` (NEA FastAttach and comparable services issue one) is what
ties the 275 to the claim. It goes in PWK06 on the claim side and identifies the payload
on the attachment side. Without it the payer holds a document it cannot match to a claim.

Documents supplied by a human at the `insurance.document_request` gate are merged in here,
so the 275 carries both halves — what the AI found and what a person produced — as one
transmission rather than two.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class AttachmentAssembler(Agent):
    name = "attachment_assembler"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        routed = ctx.get_result("information_request_router")
        ack = ctx.get_result("claim_submitter").get("claim_ack", {})
        supplied = ctx.get_result("document_request")          # None unless the gate ran
        registry = ctx.input_data.get("document_registry", {}) or {}

        # 1. everything already in the record
        documents = [
            {"doc_key": a["doc_key"], "label": a["label"], "pwk": a["pwk"],
             "detail": a.get("detail", ""), "obtained_by": "ai"}
            for a in routed.get("auto_satisfiable", [])
        ]

        # 2. anything a human just produced at the gate
        human_keys = set((supplied or {}).get("doc_keys", []) or [])
        for item in routed.get("escalated", []):
            if item["doc_key"] in human_keys:
                documents.append({
                    "doc_key": item["doc_key"], "label": item["label"], "pwk": item["pwk"],
                    "detail": (registry.get(item["doc_key"], {}) or {}).get(
                        "detail", "supplied by practice staff"),
                    "obtained_by": item["resolved_by"],
                })

        # 3. anything still missing — declared honestly, never PWK'd
        outstanding = [item["label"] for item in routed.get("escalated", [])
                       if item["doc_key"] not in human_keys]

        attachment = await self.reg.claims.send_attachment(
            claim_control_number=ack.get("control_number", ""),
            documents=documents,
            outstanding=outstanding,
        )
        data = attachment.model_dump()
        return AgentResult.completed({
            "attachment": data,
            "attachment_control_number": data.get("attachment_control_number", ""),
            "transmitted": len(documents),
            "documents": documents,
            "pwk_segments": data.get("pwk_segments", []),
            # complete == the payer got everything it asked for, so adjudication can finish
            "complete": data.get("complete", False),
            "outstanding": outstanding,
            "ai_supplied": sum(1 for d in documents if d["obtained_by"] == "ai"),
            "human_supplied": sum(1 for d in documents if d["obtained_by"] != "ai"),
        })
