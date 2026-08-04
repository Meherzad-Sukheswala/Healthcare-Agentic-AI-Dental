"""Reminder Dispatcher (single task: schedule appointment reminders). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class ReminderDispatcher(Agent):
    name = "reminder_dispatcher"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        appt = ctx.get_result("appointment_creator")
        if appt.get("status") != "booked":
            return AgentResult.completed({"dispatched": False, "reminders": []})
        return AgentResult.completed({
            "dispatched": True,
            "reminders": [
                {"channel": "sms", "offset_hours": 24},
                {"channel": "email", "offset_hours": 2},
            ],
        })
