"""
Critical-Value Detector (single task: flag panic lab values). FULL.

Deterministic thresholds. If a panic value is present the downstream notifier gate
forces a human acknowledgement before the encounter proceeds.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

# (lab, low_panic, high_panic) — standard adult critical thresholds
_PANIC = {
    "potassium": (2.5, 6.0),
    "sodium": (120, 160),
    "glucose": (40, 500),
    "calcium": (6.0, 13.0),
    "troponin": (None, 0.04),
    "hemoglobin": (7.0, None),
}


class CriticalValueDetector(Agent):
    name = "critical_value_detector"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        labs = ctx.input_data.get("labs", {}) or {}
        critical = []
        for lab, value in labs.items():
            lo, hi = _PANIC.get(lab, (None, None))
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            if (lo is not None and v < lo) or (hi is not None and v > hi):
                critical.append({"lab": lab, "value": v, "low": lo, "high": hi})
        return AgentResult.completed({"critical_values": critical, "has_critical": bool(critical)})
