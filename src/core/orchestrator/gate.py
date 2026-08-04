"""
src/core/orchestrator/gate.py

The human-gate pause/resume primitive — the core of the production design.

Every one of the 12 mandated human touchpoints is its own agent that subclasses
HumanGateAgent. On first run it emits a GateRequest and returns status
"awaiting_human", which pauses the pipeline. When the encounter is resumed with a
GateDecision for that gate_id, the same agent sees the decision and proceeds.

Because every agent is single-task, deterministic and idempotent, "resume" is just
re-running the pipeline with the decision now present — no fragile mid-run state.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import Field

from src.shared.base_types import HealthcareModel, utcnow
from src.shared.enums import Automation, GateStatus

if TYPE_CHECKING:
    from .context import PipelineContext


class GateRequest(HealthcareModel):
    """What a human is being asked to decide."""

    gate_id: str
    title: str
    prompt: str
    domain: str = ""
    data: dict = Field(default_factory=dict)


class GateDecision(HealthcareModel):
    """A human's answer to a gate."""

    gate_id: str
    approved: bool
    actor: str = "unknown"          # who acted (e.g. "Dr. Rao, MD")
    note: str = ""
    at: str = Field(default_factory=lambda: utcnow().isoformat())


@dataclass
class AgentResult:
    status: str                     # completed | awaiting_human | rejected | failed | skipped
    output: dict = field(default_factory=dict)
    gate: GateRequest | None = None
    error: str | None = None

    @staticmethod
    def completed(output: dict | None = None) -> "AgentResult":
        return AgentResult("completed", output or {})

    @staticmethod
    def awaiting(gate: GateRequest) -> "AgentResult":
        return AgentResult("awaiting_human", {}, gate=gate)

    @staticmethod
    def rejected(gate_id: str, note: str = "") -> "AgentResult":
        return AgentResult("rejected", {"gate_id": gate_id, "note": note})

    @staticmethod
    def failed(error: str) -> "AgentResult":
        return AgentResult("failed", {}, error=error)

    @staticmethod
    def skipped() -> "AgentResult":
        return AgentResult("skipped", {})


class Agent(ABC):
    """Single-responsibility unit of work."""

    name: str = "agent"
    automation: Automation = Automation.FULL

    @abstractmethod
    async def execute(self, ctx: "PipelineContext") -> AgentResult:
        ...


class HumanGateAgent(Agent):
    """Base for the 12 mandated human touchpoints."""

    automation: Automation = Automation.MANUAL
    gate_id: str = "gate"

    @abstractmethod
    def build_request(self, ctx: "PipelineContext") -> GateRequest:
        """Describe the decision the human must make."""

    def on_approved(self, ctx: "PipelineContext", decision: GateDecision) -> dict:
        """Output produced once a human approves. Override as needed."""
        return {"gate_id": self.gate_id, "approved_by": decision.actor, "status": GateStatus.APPROVED}

    async def execute(self, ctx: "PipelineContext") -> AgentResult:
        decision = ctx.decision_for(self.gate_id)
        if decision is None:
            return AgentResult.awaiting(self.build_request(ctx))
        if not decision.approved:
            return AgentResult.rejected(self.gate_id, decision.note)
        return AgentResult.completed(self.on_approved(ctx, decision))
