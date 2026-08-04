"""
SchedulerOrchestrator — the PRE-VISIT domain: wires the 10 single-task agents that run
before the patient ever walks in.

Order: Request Parser -> Triage Classifier -> [Referral Approval gate, if required]
       -> Provider Matcher -> Availability Finder -> Slot Selection (patient gate)
       -> Appointment Creator -> Eligibility Verifier -> Reminder Dispatcher -> Audit Logger

The patient describes a problem, is matched to providers by specialty, sees each
provider's open slots, and PICKS the time that works (Slot Selection human gate).

Eligibility verification lives HERE, after the appointment is booked and before the
reminder goes out — i.e. days before the visit. That is the real pre-visit insurance
runway: the office verifies coverage against the upcoming appointment so the
treatment-plan estimate and the checkout collection can be priced correctly. Running
it on the day of service (as this repo previously did, inside patient intake) means
the estimate is built from coverage nobody confirmed in time to act on.
See docs/us-dental-clinic-real-world-workflow.md §3.5.

Scheduling is the encounter entry point, so failures abort.
"""
from __future__ import annotations

from src.agents.common import AuditLogger
from src.agents.patient.eligibility_verifier import EligibilityVerifier
from src.core.orchestrator import DomainOrchestrator, PipelineStep

from .appointment_creator import AppointmentCreator
from .availability_finder import AvailabilityFinder
from .provider_matcher import ProviderMatcher
from .reminder_dispatcher import ReminderDispatcher
from .request_parser import RequestParser
from .referral_approval import ReferralApproval
from .slot_selection import SlotSelection
from .triage_classifier import TriageClassifier


class SchedulerOrchestrator(DomainOrchestrator):
    name = "scheduling"
    abort_on_fail = True

    def build_steps(self):
        return [
            PipelineStep(RequestParser(self.llm, self.registry)),
            PipelineStep(TriageClassifier()),
            PipelineStep(
                ReferralApproval(),
                condition=lambda ctx: bool(ctx.input_data.get("requires_referral")),
            ),
            PipelineStep(ProviderMatcher(self.registry)),
            PipelineStep(AvailabilityFinder(self.registry)),
            PipelineStep(SlotSelection()),
            PipelineStep(AppointmentCreator(self.registry)),
            PipelineStep(EligibilityVerifier(self.registry)),
            PipelineStep(ReminderDispatcher()),
            PipelineStep(AuditLogger(domain="scheduling")),
        ]

    def build_output(self, ctx) -> dict:
        matcher = ctx.get_result("provider_matcher")
        sel = ctx.get_result("slot_selection")
        appt = ctx.get_result("appointment_creator")
        elig = ctx.get_result("eligibility_verifier")
        return {
            "appointment": appt,
            "selected_npi": sel.get("selected_npi", "") or appt.get("provider_npi", ""),
            "provider_name": sel.get("selected_provider", "") or appt.get("provider_name", ""),
            "candidates": matcher.get("candidates", []),
            "slot_options": ctx.get_result("availability_finder").get("slot_options", []),
            "triage": ctx.get_result("triage_classifier"),
            # pre-visit verified benefits — the basis for every downstream estimate
            "coverage": elig.get("coverage", {}),
            "eligibility_verified": elig.get("verified_pre_visit", False),
            "audit": ctx.get_result("audit_logger").get("audit", {}),
        }
