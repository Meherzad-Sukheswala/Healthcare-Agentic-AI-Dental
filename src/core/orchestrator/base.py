"""
src/core/orchestrator/base.py

DomainOrchestrator — runs a domain's single-task agents in order, honoring:
  * conditional steps (skip when a guard is false)
  * human gates (pause the whole domain and bubble a GateRequest up)
  * abort vs. partial policy on failure (safety-critical domains abort)

Resume semantics: the master re-runs the domain with decisions now present;
agents are deterministic/idempotent, so re-execution is safe.

Dependencies (the ServiceRegistry and the LLM client) are injected at construction
and exposed as self.registry / self.llm so build_steps() can wire them into agents.
"""
from __future__ import annotations

from typing import Any

from src.logging_setup import get_logger
from src.shared.enums import PipelineStatus

from .context import PipelineContext
from .pipeline import DomainResult, PipelineStep

log = get_logger(__name__)


class DomainOrchestrator:
    name: str = "domain"
    # Safety-critical domains abort the encounter on failure; others return partial.
    abort_on_fail: bool = False

    def __init__(self, registry: Any = None, llm_client: Any = None, event_bus: Any = None) -> None:
        self.registry = registry
        self.llm = llm_client
        self.event_bus = event_bus
        self.steps: list[PipelineStep] = self.build_steps()

    # ---- to be provided by each domain ----
    def build_steps(self) -> list[PipelineStep]:
        raise NotImplementedError

    def build_output(self, ctx: PipelineContext) -> dict:
        """Aggregate the domain's output from ctx.results. Override per domain."""
        return dict(ctx.results)

    # ---- engine ----
    async def run(self, ctx: PipelineContext) -> DomainResult:
        result = DomainResult(domain=self.name, status=PipelineStatus.COMPLETED)
        for step in self.steps:
            if step.condition is not None and not step.condition(ctx):
                result.skipped.append(step.name)
                continue

            res = await step.agent.execute(ctx)

            if res.status == "awaiting_human":
                log.info("human_gate_opened", domain=self.name, gate=res.gate.gate_id)
                result.status = PipelineStatus.AWAITING_HUMAN
                result.gate = res.gate
                result.output = self.build_output(ctx)
                return result

            if res.status in ("failed", "rejected"):
                msg = res.error or f"{step.name} {res.status}"
                result.errors.append(msg)
                log.warning("step_failed", domain=self.name, step=step.name, reason=msg)
                if self.abort_on_fail:
                    result.status = PipelineStatus.FAILED
                    result.output = self.build_output(ctx)
                    return result
                result.status = PipelineStatus.PARTIAL
                continue

            if res.status == "skipped":
                result.skipped.append(step.name)
                continue

            ctx.add_result(step.output_key or step.agent.name, res.output)
            result.executed.append(step.name)

        result.output = self.build_output(ctx)
        return result
