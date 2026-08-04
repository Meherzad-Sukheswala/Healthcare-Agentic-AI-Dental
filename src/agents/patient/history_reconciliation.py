"""
History Reconciliation (single task: de-duplicate & flag the med/allergy list). PARTIAL.

Auto de-dupes; flags needs_clinician_confirm so a clinician confirms the reconciled
list (the human oversight step) before it drives clinical decisions.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class HistoryReconciliation(Agent):
    name = "history_reconciliation"
    automation = Automation.PARTIAL

    async def execute(self, ctx) -> AgentResult:
        hf = ctx.get_result("history_fetcher")
        seen, reconciled = set(), []
        for med in hf.get("medications", []):
            code = med.get("code")
            if code and code not in seen:
                seen.add(code)
                reconciled.append(med)
        return AgentResult.completed({
            "reconciled_medications": reconciled,
            "allergy_count": len(hf.get("allergies", [])),
            "condition_count": len(hf.get("conditions", [])),
            "needs_clinician_confirm": len(reconciled) > 0,
        })
