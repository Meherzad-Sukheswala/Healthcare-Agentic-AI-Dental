"""
src/core/orchestrator/context.py

The shared state passed through a domain pipeline. Holds inputs, per-agent
outputs, human decisions collected so far, an event log and any errors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import PipelineStepError
from .gate import GateDecision


@dataclass
class PipelineContext:
    encounter_id: str
    input_data: dict = field(default_factory=dict)
    results: dict[str, dict] = field(default_factory=dict)
    decisions: dict[str, GateDecision] = field(default_factory=dict)
    events: list = field(default_factory=list)
    errors: list[PipelineStepError] = field(default_factory=list)

    # --- results ---
    def add_result(self, key: str, output: dict) -> None:
        self.results[key] = output

    def get_result(self, key: str) -> dict:
        return self.results.get(key, {})

    # --- human decisions ---
    def decision_for(self, gate_id: str) -> GateDecision | None:
        return self.decisions.get(gate_id)

    def add_decision(self, decision: GateDecision) -> None:
        self.decisions[decision.gate_id] = decision

    # --- errors / events ---
    def add_error(self, error: PipelineStepError) -> None:
        self.errors.append(error)

    def add_event(self, event: Any) -> None:
        self.events.append(event)
