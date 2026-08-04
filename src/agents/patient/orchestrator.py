"""
PatientOrchestrator — the VISIT-DAY check-in domain: wires the 8 single-task Patient
(registration & intake) agents that run once the patient is physically present.

Order: Demographics Intake -> Identity Matcher -> [MPI Conflict Resolver gate,
       if ambiguous] -> Consent Presenter -> Consent Signature (gate, always) ->
       History Fetcher -> History Reconciliation -> Audit Logger

Eligibility verification is deliberately NOT here — it moved to the scheduling
(pre-visit) domain, because a coverage check that happens after the patient is seated
is too late to price the visit. See scheduling/orchestrator.py and
docs/us-dental-clinic-real-world-workflow.md §3.5.

Safety-critical (identity/consent), so failures abort. This domain can pause at up
to two gates; the re-run-with-decisions model advances to the next unresolved gate
each time, so multiple human touchpoints compose cleanly.
"""
from __future__ import annotations

from src.agents.common import AuditLogger
from src.core.orchestrator import DomainOrchestrator, PipelineStep

from .consent_presenter import ConsentPresenter
from .consent_signature import ConsentSignature
from .demographics_intake import DemographicsIntake
from .history_fetcher import HistoryFetcher
from .history_reconciliation import HistoryReconciliation
from .identity_matcher import IdentityMatcher
from .mpi_conflict_resolver import MPIConflictResolver


class PatientOrchestrator(DomainOrchestrator):
    name = "patient"
    abort_on_fail = True

    def build_steps(self):
        return [
            PipelineStep(DemographicsIntake(self.registry)),
            PipelineStep(IdentityMatcher()),
            PipelineStep(
                MPIConflictResolver(),
                condition=lambda ctx: ctx.get_result("identity_matcher").get("ambiguous", False),
            ),
            PipelineStep(ConsentPresenter()),
            PipelineStep(ConsentSignature()),
            PipelineStep(HistoryFetcher()),
            PipelineStep(HistoryReconciliation()),
            PipelineStep(AuditLogger(domain="patient")),
        ]

    def build_output(self, ctx) -> dict:
        demo = ctx.get_result("demographics_intake")
        return {
            "patient_id": demo.get("patient_id", ""),
            "member_id": demo.get("member_id", ""),
            "payer_id": demo.get("payer_id", ""),
            "consent": ctx.get_result("consent_signature"),
            "identity": ctx.get_result("identity_matcher"),
            "history": ctx.get_result("history_reconciliation"),
            "allergies": ctx.get_result("history_fetcher").get("allergies", []),
            "medications": ctx.get_result("history_fetcher").get("medications", []),
            "conditions": ctx.get_result("history_fetcher").get("conditions", []),
            "audit": ctx.get_result("audit_logger").get("audit", {}),
        }
