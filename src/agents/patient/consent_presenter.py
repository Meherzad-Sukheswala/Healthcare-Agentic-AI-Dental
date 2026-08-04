"""Consent Presenter (single task: present consent forms to the patient). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation, ConsentStatus


class ConsentPresenter(Agent):
    name = "consent_presenter"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        return AgentResult.completed({
            "forms": ["treatment_consent", "hipaa_authorization", "financial_policy_agreement"],
            "consent_status": ConsentStatus.PRESENTED.value,
        })
