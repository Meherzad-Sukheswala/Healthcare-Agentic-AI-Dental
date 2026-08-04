"""Orchestration error hierarchy."""
from __future__ import annotations


class PipelineStepError(Exception):
    """A single agent/step failed. Carries the step name and retry hint."""

    def __init__(self, step: str, message: str, retryable: bool = False):
        self.step = step
        self.message = message
        self.retryable = retryable
        super().__init__(f"[{step}] {message}")


class AbortPipeline(PipelineStepError):
    """Raised for failures that must stop the whole encounter (safety-critical)."""
