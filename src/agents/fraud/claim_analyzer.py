"""Claim Analyzer (single task: fraud signals in the claim). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

# high-reimbursement CDT codes disproportionately represented in payer SIU upcoding models
_HIGH_LEVEL_CDT = {"D0150", "D4260", "D6010", "D7953"}


class ClaimAnalyzer(Agent):
    name = "claim_analyzer"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        cdt = ctx.input_data.get("cdt", "")
        codes = ctx.input_data.get("cdt_codes", [cdt] if cdt else [])
        signals, points = [], 0
        if cdt in _HIGH_LEVEL_CDT:                       # potential upcoding
            signals.append("high_level_cdt_code")
            points += 15
        duplicates = {c for c in set(codes) if codes.count(c) > 1}
        if duplicates:                                    # same procedure billed twice on one claim
            signals.append("duplicate_procedure_billing")
            points += 20
        return AgentResult.completed({"signals": signals, "risk_points": points})
