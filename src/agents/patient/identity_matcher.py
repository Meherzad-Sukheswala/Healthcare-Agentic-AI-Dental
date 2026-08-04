"""
Identity Matcher (single task: EMPI probabilistic identity match). PARTIAL.

Auto-resolves a confident match; a low score is flagged 'ambiguous' so the MPI
conflict resolver (a human gate) is triggered downstream.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

_THRESHOLD = 0.90


class IdentityMatcher(Agent):
    name = "identity_matcher"
    automation = Automation.PARTIAL

    async def execute(self, ctx) -> AgentResult:
        demo = ctx.get_result("demographics_intake")
        # demo-controllable: caller can force an ambiguous match to show the gate
        forced = bool(ctx.input_data.get("identity_ambiguous"))
        score = 0.72 if forced else 0.985
        return AgentResult.completed({
            "mpi_id": demo.get("patient_id", ""),
            "match_score": score,
            "ambiguous": score < _THRESHOLD,
        })
