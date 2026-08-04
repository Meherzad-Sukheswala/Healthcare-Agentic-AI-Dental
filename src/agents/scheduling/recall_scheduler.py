"""
Recall Scheduler (single task: recommend the next recare interval). FULL.

Real dental recall systems are a background process, not part of the same visit
transaction: "patients leave every hygiene appointment with their next visit
already scheduled," and recall rules run continuously off procedure codes rather
than a fixed calendar rule. This agent produces that recommendation once the
visit's actual procedures are known — which is only true at the END of an
encounter, after Clinical has run, so the MasterOrchestrator invokes it once after
all domains complete rather than as a step inside SchedulerOrchestrator's own
pipeline (which runs first, before any procedure exists to react to).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

# CDT prefix -> recommended recall interval in months (procedure-driven, not a fixed rule)
_INTERVAL_MONTHS = {
    "D1": 6,     # preventive (cleanings) — standard recare
    "D4": 4,     # periodontal treatment — perio maintenance recalls more often
    "D3": 1,     # endodontic (root canal) — short follow-up to confirm healing
    "D2": 6,     # restorative (fillings, crowns) — standard recare
}
_DEFAULT_MONTHS = 6


class RecallScheduler(Agent):
    name = "recall_scheduler"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        codes = ctx.input_data.get("cdt_codes", []) or [ctx.input_data.get("cdt", "")]
        months = min((_INTERVAL_MONTHS.get(c[:2], _DEFAULT_MONTHS) for c in codes if c),
                     default=_DEFAULT_MONTHS)
        due = (datetime.now(timezone.utc) + timedelta(days=months * 30)).date().isoformat()
        return AgentResult.completed({
            "recall_interval_months": months,
            "recall_due_date": due,
            "reason": "periodontal maintenance" if months <= 4 and months > 1 else
                      ("post-endodontic follow-up" if months == 1 else "routine recare"),
        })
