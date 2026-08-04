"""
DUR Screener (single task: OBRA-90 prospective drug-utilization review). FULL.

Deterministic screen for interactions and duplicate therapy across the new order
and the patient's active medications. Findings are surfaced to the pharmacist.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation, Severity


class DURScreener(Agent):
    name = "dur_screener"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        current = list(ctx.input_data.get("current_medications", []) or [])
        ordered = [it.get("rxcui", "") for it in ctx.get_result("order_receiver").get("items", [])]
        findings = []

        interactions = await self.reg.drug_info.interactions([r for r in current + ordered if r])
        for i in interactions:
            findings.append({"type": "interaction", "severity": i.severity.value, "detail": i.description})

        duplicates = set(current) & set(ordered)
        for rx in duplicates:
            findings.append({"type": "duplicate_therapy", "rxcui": rx})

        flagged = any(f.get("severity") in (Severity.SEVERE.value, Severity.CONTRAINDICATED.value)
                      or f["type"] == "duplicate_therapy" for f in findings)
        return AgentResult.completed({"dur_findings": findings, "dur_flagged": flagged})
