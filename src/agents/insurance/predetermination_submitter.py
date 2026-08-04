"""
Predetermination Submitter (single task: X12 278 predetermination request). FULL.

Dental terminology matters here: this is a "predetermination" (a voluntary written
estimate a payer returns for a proposed treatment, commonly requested for anything
over ~$500), not a medical-style mandatory "prior authorization." It is advisory —
it does not gate whether treatment happens (treatment already happened earlier in
this pipeline) and does not guarantee payment. See PriorAuthResult.is_advisory.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class PredeterminationSubmitter(Agent):
    name = "predetermination_submitter"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        res = await self.reg.prior_auth.submit(
            ctx.input_data.get("member_id", ""),
            ctx.input_data.get("payer_id", ""),
            ctx.input_data.get("cdt", "D0140"),
            ctx.input_data.get("icd10", ""),
        )
        return AgentResult.completed({
            "predetermination": res.model_dump(),
            "requires_review": res.requires_clinical_review,
            "status": res.status,
        })
