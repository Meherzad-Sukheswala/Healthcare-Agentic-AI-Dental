"""
PharmacyOrchestrator — a DIFFERENT ORGANIZATION's workflow, running asynchronously
after the clinic's encounter is otherwise finished.

Order: Order Receiver -> Stock Checker -> Allergy Gate (hard stop) -> PDMP Query
       -> DUR Screener -> Pharmacist Verification (gate) -> [Dispenser, if gate
       passed] -> [Dispatch Tracker, if dispensed] -> Audit Logger

WHY THIS RUNS LAST
------------------
The clinic's involvement with a prescription ends the moment the dentist transmits an
NCPDP SCRIPT `NewRx` over Surescripts to the pharmacy the PATIENT named. Everything
below happens inside the pharmacy's own dispensing system, on the pharmacy's clock —
possibly hours later, possibly days. The clinic has no visibility into any of it
unless the pharmacy volunteers an optional `RxFill` notification, which most retail
pharmacies do not send.

So `pharmacist_verification` is correctly identified as a legally mandated human gate
(OBRA-90), but it is the PHARMACIST's gate in the PHARMACY's system — not a step the
clinic waits on before closing out the visit. Running it last is closer to the truth
than running it mid-encounter; running it as a genuinely detached async process would
be closer still.

Known simplifications, documented rather than silently modeled wrong:
  * `dispatch_tracker` produces tracking numbers and an `in_transit` status, which is
    a MAIL-ORDER shape. Dental prescriptions are overwhelmingly retail pickup — the
    patient walks in and collects, or never does.
  * PBM adjudication is absent. The drug claim goes to a pharmacy benefit manager
    (CVS Caremark, Express Scripts, OptumRx) with its own formulary, tier, copay and
    prior-auth rules — an entirely separate payer from the dental plan modeled in the
    insurance domain.
  * Only `NewRx` is modeled. Real traffic includes RxChange, RxRenewal, RxTransfer
    and CancelRx.

See docs/us-dental-clinic-real-world-workflow.md §0.3 and §9.

Not safety-critical at the pipeline level (abort_on_fail=False), but the allergy
gate is a deterministic hard stop that blocks dispensing.
"""
from __future__ import annotations

from src.agents.common import AuditLogger
from src.core.orchestrator import DomainOrchestrator, PipelineStep

from .allergy_gate import AllergyGate
from .dispatch_tracker import DispatchTracker
from .dispenser import Dispenser
from .dur_screener import DURScreener
from .order_receiver import OrderReceiver
from .pdmp_query import PDMPQuery
from .pharmacist_verification import PharmacistVerification
from .stock_checker import StockChecker


class PharmacyOrchestrator(DomainOrchestrator):
    name = "pharmacy"
    abort_on_fail = False

    def build_steps(self):
        return [
            PipelineStep(OrderReceiver(self.registry)),
            PipelineStep(StockChecker(self.registry)),
            PipelineStep(AllergyGate(self.registry)),
            PipelineStep(PDMPQuery(self.registry)),
            PipelineStep(DURScreener(self.registry)),
            PipelineStep(PharmacistVerification()),
            PipelineStep(
                Dispenser(),
                condition=lambda ctx: ctx.get_result("allergy_gate").get("gate_passed", False),
            ),
            PipelineStep(
                DispatchTracker(self.registry),
                condition=lambda ctx: ctx.get_result("allergy_gate").get("gate_passed", False),
            ),
            PipelineStep(AuditLogger(domain="pharmacy")),
        ]

    def build_output(self, ctx) -> dict:
        return {
            "order_id": ctx.get_result("order_receiver").get("order_id", ""),
            "pharmacy_id": ctx.get_result("order_receiver").get("pharmacy_id", ""),
            "in_stock": ctx.get_result("stock_checker").get("in_stock", False),
            "allergy_gate_passed": ctx.get_result("allergy_gate").get("gate_passed", False),
            "pdmp": ctx.get_result("pdmp_query"),
            "dur": ctx.get_result("dur_screener"),
            "verification": ctx.get_result("pharmacist_verification"),
            "dispensed": ctx.get_result("dispenser").get("dispensed", False),
            "dispatch": ctx.get_result("dispatch_tracker"),
            "audit": ctx.get_result("audit_logger").get("audit", {}),
        }
