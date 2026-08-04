"""
Coverage Coordinator (single task: coordination of benefits / payer ordering). FULL.

Determines which payers apply and in what order before the bill is split:
  * accepts a payer stack (list) or a single legacy 'coverage' dict
  * orders payers: commercial -> Medicare -> Medicaid (Medicaid is always payer of
    last resort)
  * flags dual-eligible (Medicare + Medicaid) and self-pay (no active coverage)

This is a distinct responsibility from splitting the bill, so it is its own agent.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

# lower rank = adjudicates earlier (primary). Medicaid is last resort.
_RANK = {"commercial": 1, "medicare": 2, "medicaid": 3, "self_pay": 9}


class CoverageCoordinator(Agent):
    name = "coverage_coordinator"
    automation = Automation.FULL

    def _collect(self, ctx) -> list[dict]:
        payers = list(ctx.input_data.get("payers", []) or [])
        if not payers and ctx.input_data.get("coverage"):
            cov = dict(ctx.input_data["coverage"])
            cov.setdefault("payer_type", "commercial")
            payers = [cov]
        return [p for p in payers if p.get("active", True) and p.get("payer_type") != "self_pay"]

    async def execute(self, ctx) -> AgentResult:
        active = self._collect(ctx)
        if not active:
            return AgentResult.completed({
                "payer_stack": [], "is_self_pay": True,
                "is_dual_eligible": False, "primary_type": "self_pay",
            })
        stack = sorted(active, key=lambda p: _RANK.get(p.get("payer_type", "commercial"), 5))
        types = {p.get("payer_type") for p in stack}
        return AgentResult.completed({
            "payer_stack": stack,
            "is_self_pay": False,
            "is_dual_eligible": "medicare" in types and "medicaid" in types,
            "primary_type": stack[0].get("payer_type", "commercial"),
        })
