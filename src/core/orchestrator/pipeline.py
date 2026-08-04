"""
src/core/orchestrator/pipeline.py

Declarative pipeline step + domain result types.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from src.shared.enums import PipelineStatus

from .context import PipelineContext
from .gate import Agent, GateRequest


@dataclass
class PipelineStep:
    """One agent in a domain pipeline.

    condition   : optional gate on whether the step runs (ctx -> bool)
    output_key  : where the agent's output is stored in ctx.results
                  (defaults to the agent's name)
    """

    agent: Agent
    condition: Callable[[PipelineContext], bool] | None = None
    output_key: str | None = None

    @property
    def name(self) -> str:
        return self.output_key or self.agent.name


@dataclass
class DomainResult:
    domain: str
    status: PipelineStatus
    output: dict = field(default_factory=dict)
    gate: GateRequest | None = None
    executed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def awaiting_human(self) -> bool:
        return self.status == PipelineStatus.AWAITING_HUMAN
