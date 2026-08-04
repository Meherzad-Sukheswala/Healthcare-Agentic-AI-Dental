"""
src/core/pipeline/master_orchestrator.py

MasterOrchestrator — the conductor. Runs the domain orchestrators in the order a real
US dental practice actually works, hands each domain's output to the next, halts the
whole encounter at any human gate (resume by re-calling with the decision), enforces
abort-vs-partial policy, and runs Fraud as a non-blocking observer at the end.

PIPELINE ORDER, BY REAL-WORLD PHASE
-----------------------------------
  PRE-VISIT   1. Scheduling      book the appointment + verify eligibility (270/271)
  VISIT DAY   2. Patient         check-in, identity, consent, history
              3. Clinical        diagnose -> plan -> consent -> treat -> transmit Rx
              4. Checkout        ESTIMATE the patient's share and COLLECT it
  POST-VISIT  5. Insurance       file the claim (837D), receive the payer's ERA (835)
              6. Reconciliation  settle estimate vs actual -> balance bill or refund
              7. Pharmacy        the pharmacy's own async workflow
              8. Fraud           parallel observer, never blocks
                 Recall          post-visit recare recommendation

WHY CHECKOUT PRECEDES INSURANCE
-------------------------------
This is the correction that matters most. A dental practice bills the patient BEFORE
the payer has adjudicated anything: the patient pays an estimate at the front desk on
the day of service, the claim goes out that evening, and the payer's real numbers
arrive 1–2 weeks later. There is no approval gate between treatment and collecting
money. Running Insurance before Billing — as this pipeline previously did — implies
the office knows the payer's answer when it bills the patient, which inverts the
single most consequential sequence in dental revenue cycle.

The consequence is that billing is two domains, not one: Checkout collects an
estimate, Reconciliation settles it once the ERA lands. See
docs/us-dental-clinic-real-world-workflow.md §0.1, §6 and §8.

Abort policy:
  Scheduling / Patient / Clinical failure   -> abort the encounter
  Checkout / Insurance / Reconciliation /
  Pharmacy failure                          -> continue with partial results
  Fraud                                     -> observer only, never halts/blocks
"""
from __future__ import annotations

import uuid

from src.agents.billing import CheckoutOrchestrator, ReconciliationOrchestrator
from src.agents.clinical import ClinicalOrchestrator
from src.agents.fraud import FraudDetectionOrchestrator
from src.agents.insurance import InsuranceOrchestrator
from src.agents.patient import PatientOrchestrator
from src.agents.pharmacy import PharmacyOrchestrator
from src.agents.scheduling import SchedulerOrchestrator
from src.agents.scheduling.recall_scheduler import RecallScheduler
from src.core.orchestrator import GateDecision, PipelineContext
from src.integrations.idempotency import bind_encounter
from src.logging_setup import get_logger
from src.shared.document_registry import build_registry
from src.shared.enums import PipelineStatus

from .encounter import EncounterResult

log = get_logger(__name__)

# domains whose failure aborts the whole encounter
_ABORT_DOMAINS = {"scheduling", "patient", "clinical"}


class MasterOrchestrator:
    def __init__(self, registry, llm_client):
        self.registry = registry
        self.llm = llm_client
        self.scheduling = SchedulerOrchestrator(registry=registry, llm_client=llm_client)
        self.patient = PatientOrchestrator(registry=registry, llm_client=llm_client)
        self.clinical = ClinicalOrchestrator(registry=registry, llm_client=llm_client)
        self.checkout = CheckoutOrchestrator(registry=registry, llm_client=llm_client)
        self.insurance = InsuranceOrchestrator(registry=registry, llm_client=llm_client)
        self.reconciliation = ReconciliationOrchestrator(registry=registry, llm_client=llm_client)
        self.pharmacy = PharmacyOrchestrator(registry=registry, llm_client=llm_client)
        self.fraud = FraudDetectionOrchestrator(registry=registry, llm_client=llm_client)
        # not a domain step: real recall systems are a background process that only
        # makes sense once the visit's actual procedures are known — see
        # recall_scheduler.py's docstring for why this isn't inside SchedulerOrchestrator
        self.recall_scheduler = RecallScheduler()

    # --------------------------------------------------------------- entrypoint
    async def execute_encounter(self, request: dict) -> EncounterResult:
        enc_id = request.get("encounter_id") or str(uuid.uuid4())
        # Bind this encounter so the service adapters can suppress side effects they
        # already performed on an earlier pass. Every resume replays the pipeline from
        # the start; without this, each replay re-books the slot, re-charges the card
        # and re-submits the claim. See integrations/idempotency.py.
        bind_encounter(enc_id)
        decisions = self._decisions(request)
        result = EncounterResult(encounter_id=enc_id, patient_id=request.get("patient_id", ""))
        log.info("encounter_started", encounter_id=enc_id, patient=result.patient_id)

        # ---------------- PRE-VISIT ----------------
        # 1. Scheduling — book, then verify insurance days before the visit
        sched = await self._run("scheduling", self.scheduling, self._sched_input(request), enc_id, decisions, result)
        if self._halt(result, "scheduling", sched):
            return self._finish(result)

        # ---------------- VISIT DAY ----------------
        # 2. Patient check-in
        pat = await self._run("patient", self.patient, self._patient_input(request), enc_id, decisions, result)
        if self._halt(result, "patient", pat):
            return self._finish(result)

        # 3. Clinical
        clin = await self._run("clinical", self.clinical,
                               self._clinical_input(request, sched, pat), enc_id, decisions, result)
        if self._halt(result, "clinical", clin):
            return self._finish(result)

        # 4. Checkout — estimate the patient's share and collect it, before any claim
        checkout = await self._run("checkout", self.checkout,
                                   self._checkout_input(request, sched, clin), enc_id, decisions, result)
        if self._halt(result, "checkout", checkout):
            return self._finish(result)

        # ---------------- POST-VISIT ----------------
        # 5. Insurance — file the claim; it is either rejected by front-end edits
        #    (no adjudication, no ERA) or accepted and adjudicated into a remittance
        ins = await self._run("insurance", self.insurance,
                              self._insurance_input(request, sched, pat, clin, checkout),
                              enc_id, decisions, result)
        if self._halt(result, "insurance", ins):
            return self._finish(result)

        # 6. Reconciliation — the estimate meets reality; balance bill or refund
        recon = await self._run("reconciliation", self.reconciliation,
                                self._reconciliation_input(request, checkout, ins), enc_id, decisions, result)
        if self._halt(result, "reconciliation", recon):
            return self._finish(result)

        # 7. Pharmacy — the pharmacy's own asynchronous workflow
        pharm = await self._run("pharmacy", self.pharmacy,
                                self._pharmacy_input(request, pat, clin), enc_id, decisions, result)
        if self._halt(result, "pharmacy", pharm):
            return self._finish(result)

        # 8. Fraud (parallel observer — never halts)
        await self._run("fraud", self.fraud,
                        self._fraud_input(clin, ins, pharm), enc_id, decisions, result)

        # Post-visit recall recommendation — not a domain, just a deterministic
        # lookup, so it's called directly rather than through a DomainOrchestrator.
        recall_ctx = PipelineContext(encounter_id=enc_id,
                                     input_data={"cdt_codes": clin.output.get("cdt_codes", [])})
        recall_res = await self.recall_scheduler.execute(recall_ctx)
        result.recall = recall_res.output

        return self._finish(result)

    # --------------------------------------------------------------- helpers
    def _decisions(self, request: dict) -> dict[str, GateDecision]:
        out: dict[str, GateDecision] = {}
        for gate_id, d in (request.get("decisions") or {}).items():
            out[gate_id] = GateDecision(gate_id=gate_id, approved=bool(d.get("approved", True)),
                                        actor=d.get("actor", "unknown"), note=d.get("note", ""))
        return out

    async def _run(self, name, orch, input_data, enc_id, decisions, result):
        ctx = PipelineContext(encounter_id=enc_id, input_data=input_data, decisions=dict(decisions))
        dr = await orch.run(ctx)
        result.record(name, dr)
        if dr.status == PipelineStatus.PARTIAL:
            result.partial = True
        return dr

    def _halt(self, result, name, dr) -> bool:
        """Return True if the encounter must stop after this domain."""
        if dr.status == PipelineStatus.AWAITING_HUMAN:
            result.status = "awaiting_human"
            result.awaiting_domain = name
            result.awaiting_gate = dr.gate
            log.info("encounter_paused", domain=name, gate=dr.gate.gate_id)
            return True
        if dr.status == PipelineStatus.FAILED and name in _ABORT_DOMAINS:
            result.status = "failed"
            log.error("encounter_aborted", domain=name)
            return True
        return False

    def _finish(self, result) -> EncounterResult:
        if result.status not in ("awaiting_human", "failed"):
            result.status = "partial" if result.partial else "completed"
        return result

    # --------------------------------------------------------------- transformers
    def _sched_input(self, request):
        # payer/member arrive with the booking request because the front desk captures
        # insurance at booking time — which is what makes pre-visit verification
        # possible. Passed through un-defaulted: absent means "use what's on file for
        # this patient", whereas an explicit "" means uninsured/self-pay.
        return {"patient_id": request.get("patient_id", ""),
                "request_text": request.get("request_text") or request.get("chief_complaint", ""),
                "requires_referral": request.get("requires_referral", False),
                "preferred_provider_npi": request.get("preferred_provider_npi", ""),
                "payer_id": request.get("payer_id"),
                "member_id": request.get("member_id")}

    def _patient_input(self, request):
        return {"patient_id": request.get("patient_id", ""),
                "identity_ambiguous": request.get("identity_ambiguous", False),
                "override_payer_id": request.get("payer_id"),
                "override_member_id": request.get("member_id")}

    def _clinical_input(self, request, sched, pat):
        meds = [m.get("code", "") for m in pat.output.get("medications", [])]
        return {"imaging_omitted": request.get("imaging_omitted", []),
                "patient_id": request.get("patient_id", ""),
                "selected_npi": sched.output.get("selected_npi", ""),
                "chief_complaint": request.get("chief_complaint", ""),
                "current_medications": [m for m in meds if m],
                "allergies": pat.output.get("allergies", []),
                "labs": request.get("labs", {}),
                "prescribe": request.get("prescribe", []),
                # coverage comes from the PRE-VISIT verification, not from check-in
                "coverage": sched.output.get("coverage", {})}

    def _checkout_input(self, request, sched, clin):
        """Checkout prices the visit from the pre-visit benefit check — no remittance
        exists yet, so BillSplitter runs in estimate mode."""
        coverage = sched.output.get("coverage", {})
        payers = [coverage] if coverage.get("active") else []
        payers += request.get("secondary_payers", [])
        return {"patient_id": request.get("patient_id", ""),
                # charge comes from what was actually performed, not from a claim that
                # hasn't been built yet
                "charge_cents": clin.output.get("procedure_total_cents", 0),
                "payers": payers,
                "payment_token": request.get("payment_token", "tok_demo"),
                "cdt": clin.output.get("cdt", ""), "icd10": clin.output.get("icd10", ""),
                "self_pay_discount_pct": request.get("self_pay_discount_pct"),
                "self_pay": request.get("self_pay", False),
                "retail_items": request.get("retail_items", [])}

    def _insurance_input(self, request, sched, pat, clin, checkout):
        return {"member_id": pat.output.get("member_id", ""),
                "payer_id": pat.output.get("payer_id", ""),
                "cdt": clin.output.get("cdt", "D0140"),
                "performed_items": clin.output.get("performed_items", []),
                "provider_npi": sched.output.get("selected_npi", ""),
                "ndcs": [p.get("ndc", "") for p in clin.output.get("prescriptions", [])],
                # ---- facts the payer knows that the claim doesn't state ----
                # These drive which denial (or downgrade) comes back — see
                # shared/payer_outcomes.py. Defaults are the clean-claim case.
                "days_since_service": request.get("days_since_service", 0),
                "attachments_ride_along": request.get("attachments_ride_along", False),
                "prior_procedures": request.get("prior_procedures", []),
                "duplicate_claim": request.get("duplicate_claim", False),
                "other_coverage_primary": request.get("other_coverage_primary", False),
                # injects one realistic data-entry / field-mapping fault so the 277CA
                # rejection path can be demonstrated — see claim_builder
                "claim_defect": request.get("claim_defect", ""),
                # What documentation this encounter genuinely holds. Built from what the
                # visit actually produced, so the router's "already on file" answer is
                # true rather than assumed — see shared/document_registry.py.
                "document_registry": build_registry(
                    imaging=clin.output.get("imaging", {}),
                    clinical_note=clin.output.get("clinical_note", ""),
                    narratives=clin.output.get("narratives", []),
                    treatment_plan_items=clin.output.get("treatment_plan", {}).get("items", []),
                    perio_charted=clin.output.get("imaging", {}).get("perio_charted", False),
                ),
                # ---- the documentation the claim is built from ----
                "icd10": clin.output.get("icd10", ""),                  # principal diagnosis
                "diagnosis_codes": clin.output.get("diagnosis_codes", []),        # ADA 34a
                "line_diagnoses": clin.output.get("line_diagnoses", []),          # ADA 29a
                "diagnosis_submission_required": clin.output.get("diagnosis_submission_required", False),
                "narratives": clin.output.get("narratives", []),
                "attachments_recommended": clin.output.get("attachments_recommended", []),
                # what the patient was already charged, for coder context
                "checkout_total_cents": checkout.output.get("total_cents", 0)}

    def _reconciliation_input(self, request, checkout, ins):
        """The settle-up: the payer's actual response vs. what was collected at checkout."""
        remittance = ins.output.get("remittance", {})
        return {"patient_id": request.get("patient_id", ""),
                "remittance": remittance,
                "collected_cents": checkout.output.get("collected_cents", 0),
                "estimated_patient_cents": checkout.output.get("estimated_patient_cents", 0),
                "addons_cents": checkout.output.get("addons_cents", 0),
                # A rejected claim never reached adjudication, so there is no remittance
                # to settle against and the balance stays UNRESOLVED in AR — distinct
                # from a self-pay encounter, which has no remittance because it never
                # had a payer. Without this flag the two look identical here.
                "claim_rejected": ins.output.get("claim_rejected", False),
                # the payer's actual ERA status drives denial detection, not a
                # synchronous claim-submission ack (which never carries a real
                # adjudication outcome — that comes back separately, later)
                "claim_status": remittance.get("status", "received"),
                # documentation already generated, so a "needs attachment" denial can be
                # answered by resubmitting rather than by an appeal
                "attachments_recommended": ins.output.get("claim", {}).get("attachments_recommended", [])}

    def _pharmacy_input(self, request, pat, clin):
        meds = [m.get("code", "") for m in pat.output.get("medications", [])]
        return {"patient_id": request.get("patient_id", ""),
                "state": request.get("state", "CA"),
                "pharmacy_id": request.get("pharmacy_id", "PHARM-001"),
                "allergies": pat.output.get("allergies", []),
                "current_medications": [m for m in meds if m],
                "prescriptions": clin.output.get("prescriptions", [])}

    def _fraud_input(self, clin, ins, pharm):
        pdmp_flags = pharm.output.get("pdmp", {}).get("risk_flags", [])
        return {"cdt": clin.output.get("cdt", ""),
                "cdt_codes": clin.output.get("cdt_codes", []),
                "charge_cents": ins.output.get("charge_cents", 0),
                "diagnosis_icd10": clin.output.get("icd10", ""),
                "prescriptions": clin.output.get("prescriptions", []),
                "pdmp_risk_flags": pdmp_flags}
