"""
Symptom Recorder (single task: structure the chief complaint into symptoms). PARTIAL.

LLM-backed with a deterministic sandbox fallback, so it demonstrates the AI path
while staying reproducible offline.
"""
from __future__ import annotations

import json

from src.core.llm import LLMMessage, LLMRequest
from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

_SYSTEM = (
    "You are a clinical intake assistant. Convert the patient's chief complaint into "
    'STRICT JSON: {"symptoms": [str, ...]}. Keep each symptom short.'
)


class SymptomRecorder(Agent):
    name = "symptom_recorder"
    automation = Automation.PARTIAL

    def __init__(self, llm):
        self.llm = llm

    def _heuristic(self, text: str) -> dict:
        parts = [p.strip() for chunk in text.split(",") for p in chunk.split(" and ")]
        return {"symptoms": [p for p in parts if p]}

    async def execute(self, ctx) -> AgentResult:
        text = ctx.input_data.get("chief_complaint", "")
        heuristic = self._heuristic(text)
        resp = await self.llm.complete(LLMRequest(
            system_prompt=_SYSTEM, messages=[LLMMessage.user(text)],
            agent_name=self.name, sandbox_response=json.dumps(heuristic),
        ))
        try:
            parsed = json.loads(resp.content)
        except (json.JSONDecodeError, TypeError):
            parsed = heuristic
        return AgentResult.completed({"symptoms": parsed.get("symptoms", []), "chief_complaint": text})
