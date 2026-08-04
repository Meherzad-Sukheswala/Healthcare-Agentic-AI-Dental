"""
FraudDetectionOrchestrator — wires the 8 single-task fraud agents.

Parallel OBSERVER: it analyzes the encounter's claim/prescription/billing signals,
scores risk, raises an alert, and queues a human SIU review — but pipeline_blocked
is ALWAYS False and it never pauses. Alerts go to a review queue, out of band.
"""
from __future__ import annotations

from src.agents.common import AuditLogger
from src.core.orchestrator import DomainOrchestrator, PipelineStep

from .alert_generator import AlertGenerator
from .billing_anomaly_detector import BillingAnomalyDetector
from .claim_analyzer import ClaimAnalyzer
from .consistency_checker import ConsistencyChecker
from .prescription_analyzer import PrescriptionAnalyzer
from .risk_scorer import RiskScorer
from .siu_investigator_review import SIUInvestigatorReview


class FraudDetectionOrchestrator(DomainOrchestrator):
    name = "fraud"
    abort_on_fail = False

    def build_steps(self):
        return [
            PipelineStep(ClaimAnalyzer()),
            PipelineStep(PrescriptionAnalyzer()),
            PipelineStep(BillingAnomalyDetector()),
            PipelineStep(ConsistencyChecker(self.llm)),
            PipelineStep(RiskScorer()),
            PipelineStep(AlertGenerator()),
            PipelineStep(SIUInvestigatorReview()),
            PipelineStep(AuditLogger(domain="fraud")),
        ]

    def build_output(self, ctx) -> dict:
        alert = ctx.get_result("alert_generator")
        return {
            "pipeline_blocked": False,            # ABSOLUTE — fraud never blocks
            "risk_score": ctx.get_result("risk_scorer").get("risk_score", 0),
            "level": ctx.get_result("risk_scorer").get("level", "low"),
            "signals": ctx.get_result("risk_scorer").get("signals", []),
            "alert": alert.get("alert", False),
            "alert_id": alert.get("alert_id", ""),
            "siu": ctx.get_result("siu_investigator_review"),
            "consistency": ctx.get_result("consistency_checker"),
            "audit": ctx.get_result("audit_logger").get("audit", {}),
        }
