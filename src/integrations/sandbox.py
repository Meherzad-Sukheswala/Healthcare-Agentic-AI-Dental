"""
src/integrations/sandbox.py

Offline, deterministic implementations of every port. High fidelity: real code
systems, standards-shaped payloads, and clinically-plausible logic — but no
network, so a live demo is fully reproducible. Swap any of these for a real
vendor implementation via the ServiceRegistry with zero agent changes.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from src.shared.enums import Severity

from src.shared.adjudication import adjudicate
from src.shared.claim_scrubber import scrub_claim
from src.shared.document_registry import describe
from src.shared.payer_outcomes import (
    ACTION_BILL_PATIENT,
    ACTION_WRITE_OFF,
    alternate_allowed_cents,
    classify,
    documentation_expected_for,
)

from .models import (
    CARCAdjustment,
    ClaimAck,
    ClaimAttachment,
    ClaimStatusItem,
    InformationRequest,
    RequestedDocument,
    Coverage,
    Dispatch,
    EPCSSignature,
    FormularyStatus,
    Interaction,
    PatientRecord,
    PaymentResult,
    PDMPReport,
    PriorAuthResult,
    Provider,
    RemittanceAdvice,
)
from .seed_data import INTERACTIONS, PATIENTS, PROVIDERS, payer_type_for

_now = lambda: datetime.now(timezone.utc).isoformat()
_hash = lambda s: hashlib.sha256(s.encode()).hexdigest()[:12].upper()

# CDT codes we treat as requiring payer clinical review (high-cost/surgical)
_PA_REQUIRED_CDT = {"D6010", "D7953", "D4260", "D8080"}

# crude allergen cross-reference for the demo (RxNorm -> substances)
_ALLERGEN = {
    "723": ["penicillin"],       # amoxicillin -> penicillin class
    "733": ["penicillin"],       # ampicillin
    "10180": ["sulfa"],          # sulfamethoxazole
}


class SandboxEHR:
    async def get_patient(self, patient_id: str) -> PatientRecord | None:
        return PATIENTS.get(patient_id)

    async def write_clinical_note(self, patient_id: str, note: str) -> str:
        return f"DocumentReference/{_hash(patient_id + note)}"


class SandboxEligibility:
    async def check(self, member_id: str, payer_id: str, service_code: str) -> Coverage:
        active = bool(member_id) and payer_id.startswith("PAYER-")
        if not active:
            return Coverage(active=False, payer_id=payer_id, payer_type="self_pay",
                            service_covered=False, annual_max_cents=0,
                            category_coverage_pct={})
        ptype = payer_type_for(payer_id)
        if ptype == "medicare":          # medically-necessary oral surgery under Part B
            # Claims received on/after 2025-07-01 reject without a valid ICD-10.
            return Coverage(active=True, payer_id=payer_id, plan="Medicare Part B",
                            payer_type="medicare", copay_cents=0, coinsurance_pct=0.2,
                            deductible_remaining_cents=24000, annual_max_cents=0,
                            requires_diagnosis_codes=True,
                            category_coverage_pct={"preventive": 0.0, "basic": 0.8, "major": 0.8})
        if ptype == "medicaid":          # payer of last resort; nominal copay
            # Several state Medicaid dental programs mandate a diagnosis code.
            return Coverage(active=True, payer_id=payer_id, plan="Medicaid",
                            payer_type="medicaid", copay_cents=400, coinsurance_pct=0.0,
                            deductible_remaining_cents=0, annual_max_cents=100000,
                            annual_max_used_cents=0, requires_diagnosis_codes=True,
                            timely_filing_days=180,
                            category_coverage_pct={"preventive": 1.0, "basic": 1.0, "major": 0.5})
        # commercial PPO — the textbook dental benefit structure: preventive 100%,
        # basic (fillings/extractions) 80%, major (crowns/implants/dentures) 50%,
        # subject to a $1,500 annual maximum.
        #
        # PAYER-002 carries a least-expensive-alternative provision and PAYER-001/003 do
        # not, because that is how the market actually looks — LEAT is common but far
        # from universal, and a demo where every plan downgrades would misrepresent it.
        return Coverage(active=True, payer_id=payer_id, plan="PPO", payer_type="commercial",
                        copay_cents=3000, coinsurance_pct=0.2, deductible_remaining_cents=25000,
                        annual_max_cents=150000, annual_max_used_cents=0,
                        alternate_benefit_provision=(payer_id == "PAYER-002"),
                        timely_filing_days=365,
                        category_coverage_pct={"preventive": 1.0, "basic": 0.8, "major": 0.5})


class SandboxPriorAuth:
    async def submit(self, member_id: str, payer_id: str, procedure_code: str, dx: str) -> PriorAuthResult:
        if procedure_code in _PA_REQUIRED_CDT:
            return PriorAuthResult(status="pended", requires_clinical_review=True,
                                   reason="Payer medical-necessity review required")
        return PriorAuthResult(status="approved", auth_number=_hash(member_id + procedure_code),
                               requires_clinical_review=False)


# Days a payer typically allows for a response to a 277RFAI before it converts the pend
# into a denial for missing information.
_RFAI_RESPOND_DAYS = 30


class SandboxClaims:
    async def submit_claim(self, claim: dict) -> ClaimAck:
        """Clearinghouse + payer front-end edits, answered as a 277CA.

        A real submission is acknowledged twice: a 999 for X12 syntax, then a 277CA that
        either accepts the claim into adjudication or REJECTS it with the offending data
        element. Rejections carry no CARC codes and are not appealable — the biller fixes
        the field and resubmits. See src/shared/claim_scrubber.py.

        The edits run against the claim actually built, so a rejection here is earned by
        real missing/invalid data rather than injected by a demo flag.
        """
        cn = _hash(str(sorted(claim.items())))
        coverage = claim.get("coverage_snapshot") or {}
        problems = scrub_claim(claim, coverage)
        receipt = datetime.now(timezone.utc).date().isoformat()
        # No "claim received" step — the clinic's own 837D row already says that, and
        # repeating it in the exchange view reads as two events instead of one.
        trace = [
            {"step": "syntax", "label": "X12 syntax / TR3 conformance (999)", "result": "ok",
             "detail": "envelope parsed"},
            {"step": "front_end_edits", "label": "Front-end edits — IDs, NPI, tooth numbers",
             "result": "stop" if problems else "ok",
             "detail": (f"{len(problems)} problem(s)" if problems else "clean")},
        ]
        if problems:
            return ClaimAck(
                control_number=cn, accepted=False, status="rejected",
                transaction="277CA", syntax_ok=True, payer_receipt_date=receipt,
                rejections=[ClaimStatusItem(**p) for p in problems], payer_trace=trace)
        return ClaimAck(control_number=cn, accepted=True, status="accepted",
                        transaction="277CA", syntax_ok=True, payer_receipt_date=receipt,
                        payer_trace=trace)

    async def get_information_request(self, claim: dict, control_number: str):
        """The payer's documentation check — a 277RFAI, or None if nothing is wanted.

        This is where a real claim most often stalls: the payer accepts it, starts
        adjudicating, finds it cannot judge medical necessity without a radiograph or a
        perio chart, and PENDS. It has refused nothing at this point.

        The check is honest rather than scripted: it asks what documentation the billed
        procedures warrant, then compares that against what the practice actually declared
        it was sending. A claim that already carried its attachments is never pended.
        """
        lines = [ln for ln in (claim.get("service_lines") or []) if ln]
        codes = [str(ln.get("cdt", "")).upper() for ln in lines]
        expected = documentation_expected_for(codes)
        already_sent = {str(k) for k in (claim.get("attachments_sent_keys") or [])}
        wanted = [e for e in expected if e["doc_key"] not in already_sent]

        if not wanted or claim.get("attachments_ride_along"):
            return None

        due = (datetime.now(timezone.utc) + timedelta(days=_RFAI_RESPOND_DAYS)).date().isoformat()
        return InformationRequest(
            claim_control_number=control_number,
            requested=[RequestedDocument(
                doc_key=w["doc_key"], label=describe(w["doc_key"])["label"],
                reason=w["reason"], pwk_code=describe(w["doc_key"])["pwk"],
                service_line_cdt=w["service_line_cdt"]) for w in wanted],
            reason_summary=("Unable to determine medical necessity without supporting "
                            "documentation for the procedures billed."),
            due_date=due, respond_within_days=_RFAI_RESPOND_DAYS,
            payer_trace=[
                {"step": "eligibility_dos", "label": "Eligibility on date of service",
                 "result": "ok", "detail": "active"},
                {"step": "benefit_lookup", "label": "Benefit category / frequency lookup",
                 "result": "ok", "detail": "within limits"},
                # The pend itself is the 277RFAI row in the exchange view, not a trace step.
                {"step": "documentation", "label": "Documentation sufficiency check",
                 "result": "stop",
                 "detail": f"{len(wanted)} document(s) required, none received"},
            ],
        )

    async def send_attachment(self, claim_control_number: str, documents: list[dict],
                              outstanding: list[str] | None = None) -> ClaimAttachment:
        """Receive the practice's X12 275 and decide whether adjudication can resume.

        A PWK segment is emitted ONLY for a document actually present in the payload. A
        declared-but-absent attachment is the state that strands a claim indefinitely at
        some payers, so it is made structurally impossible here rather than merely
        discouraged: `outstanding` items get reported, never PWK'd.
        """
        outstanding = outstanding or []
        acn = "NEA" + _hash(claim_control_number + str(len(documents)))[:9]
        pwk = [
            {"PWK01": d.get("pwk", "OZ"),          # report type — what the document is
             "PWK02": "EL",                        # transmission method: electronic
             "PWK06": acn,                         # attachment control number
             "document": d.get("label", "")}
            for d in documents
        ]
        return ClaimAttachment(
            attachment_control_number=acn, claim_control_number=claim_control_number,
            transaction="275", documents=documents, pwk_segments=pwk,
            accepted=bool(documents), complete=bool(documents) and not outstanding,
            outstanding=outstanding)

    async def get_remittance(self, claim: dict, control_number: str) -> RemittanceAdvice:
        """Simulate the payer's X12 835 ERA coming back some days after submission.

        Applies a flat in-network contractual write-off for commercial plans (the
        "allowed amount" a real negotiated rate would produce — see
        docs/deductible-system-american-healthcare.md), then the same copay ->
        deductible -> coinsurance math the pre-treatment estimate uses, so the two
        only diverge when the underlying facts (e.g. deductible already used
        elsewhere) actually diverge.
        """
        lines = [ln for ln in (claim.get("service_lines") or [claim.get("service_line", {})]) if ln]
        billed = sum(int(ln.get("charge_cents", 0)) for ln in lines)
        payer_id = claim.get("payer_id", "")
        ptype = payer_type_for(payer_id) if payer_id.startswith("PAYER-") else "self_pay"
        coverage = claim.get("coverage_snapshot") or {}
        adjustments: list[CARCAdjustment] = []

        payer = {
            "payer_type": ptype,
            "copay_cents": claim.get("copay_cents", 3000 if ptype == "commercial" else
                                     (400 if ptype == "medicaid" else 0)),
            "deductible_remaining_cents": claim.get("deductible_remaining_cents", 0),
            "coinsurance_pct": claim.get("coinsurance_pct", 0.2 if ptype != "medicaid" else 0.0),
        }

        # ---- what did the payer DECIDE? ------------------------------------------
        # Administrative gates, coverage, benefit limits and the alternate-benefit
        # determination, in the order a payer applies them.
        outcome = classify(claim, {**coverage, "payer_type": ptype},
                           claim.get("adjudication_context") or {})

        # A flat denial allows nothing and pays nothing. WHO ends up owing the money
        # depends on why it was denied, and the three cases are genuinely different:
        if outcome.status == "denied":
            if outcome.carc:
                adjustments.append(CARCAdjustment(
                    code=outcome.carc, amount_cents=billed, description=outcome.carc_description))
            if outcome.action == ACTION_BILL_PATIENT:
                # Benefit exhausted or frequency-limited: the service simply isn't covered
                # for this patient right now, so the whole charge is theirs.
                to_patient = billed
            elif outcome.action == ACTION_WRITE_OFF:
                # Untimely filing is the PRACTICE's administrative failure and generally
                # may not be balance-billed to the patient — so the practice absorbs what
                # the payer would have paid, while the patient's normal cost share stands.
                # Refunding them the whole estimate here would be wrong.
                to_patient = adjudicate(billed, payer)
            else:
                # Appeal, resubmission or rebill pending: nothing posts to the patient
                # yet. The balance sits in AR until the payer answers properly.
                to_patient = 0
            return RemittanceAdvice(
                claim_control_number=control_number, billed_cents=billed,
                allowed_cents=0, paid_cents=0, patient_responsibility_cents=to_patient,
                adjustments=adjustments, status="denied", reason=outcome.reason,
                action=outcome.action, appealable=outcome.appealable,
                explanation=outcome.explanation)

        # ---- allowed amount -------------------------------------------------------
        if outcome.status == "paid_alternate_benefit":
            # LEAT: the plan allows the CHEAPER procedure's fee. The shortfall is patient
            # responsibility, NOT a contractual write-off — that distinction decides who
            # owes the money, so it is tracked separately from the CARC-45 adjustment.
            allowed = alternate_allowed_cents(lines)
            downgrade = billed - allowed
            if downgrade > 0:
                adjustments.append(CARCAdjustment(
                    code=outcome.carc, amount_cents=downgrade,
                    description=outcome.carc_description))
        elif ptype == "commercial":
            allowed = round(billed * 0.80)
            write_off = billed - allowed
            if write_off:
                adjustments.append(CARCAdjustment(
                    code="45", amount_cents=write_off,
                    description="Charge exceeds fee schedule/maximum allowable — contractual write-off"))
        else:
            allowed = billed

        if ptype == "medicaid":
            patient_resp = min(payer["copay_cents"], allowed)
        else:
            patient_resp = adjudicate(allowed, payer)
            if payer["copay_cents"]:
                adjustments.append(CARCAdjustment(
                    code="3", amount_cents=min(payer["copay_cents"], allowed),
                    description="Co-payment amount"))
            if payer["deductible_remaining_cents"]:
                ded_applied = min(payer["deductible_remaining_cents"],
                                  max(0, allowed - payer["copay_cents"]))
                if ded_applied:
                    adjustments.append(CARCAdjustment(
                        code="1", amount_cents=ded_applied, description="Deductible amount"))
            coins_applied = patient_resp - min(payer["copay_cents"], allowed) - \
                min(payer["deductible_remaining_cents"], max(0, allowed - payer["copay_cents"]))
            if coins_applied > 0:
                adjustments.append(CARCAdjustment(
                    code="2", amount_cents=coins_applied, description="Coinsurance amount"))

        paid = max(0, allowed - patient_resp)
        # On a LEAT downgrade the patient also owes the differential between the
        # performed procedure and the alternate the plan paid for.
        if outcome.status == "paid_alternate_benefit":
            patient_resp += billed - allowed

        trace = [
            {"step": "resume", "label": "Adjudication resumed", "result": "ok",
             "detail": "documentation on file" if claim.get("attachments_sent_keys") else "no pend"},
            {"step": "consultant", "label": "Dental consultant reviews narrative + imaging",
             "result": "ok", "detail": "medical necessity accepted"},
            {"step": "fee_schedule", "label": "Contracted fee schedule applied",
             "result": "ok", "detail": f"allowed {allowed / 100:.2f} of {billed / 100:.2f}"},
            {"step": "leat", "label": "Alternate benefit (LEAT) determination",
             "result": "warn" if outcome.status == "paid_alternate_benefit" else "ok",
             "detail": ("downgraded to the alternate procedure's rate"
                        if outcome.status == "paid_alternate_benefit" else "no downgrade")},
            {"step": "cost_share", "label": "Copay / deductible / coinsurance applied",
             "result": "ok", "detail": f"patient share {patient_resp / 100:.2f}"},
            {"step": "era", "label": "835 ERA issued", "result": "ok",
             "detail": f"payer pays {paid / 100:.2f}"},
        ]
        # "paid" means the payer correctly adjudicated per plan terms — which can
        # legitimately mean $0 to the practice if the deductible absorbs it all. That is
        # normal, not a denial. A true denial was already returned above.
        status = "denied" if allowed == 0 else outcome.status
        return RemittanceAdvice(
            claim_control_number=control_number, billed_cents=billed, allowed_cents=allowed,
            paid_cents=paid, patient_responsibility_cents=patient_resp,
            adjustments=adjustments, status=status, reason=outcome.reason,
            action=outcome.action, appealable=outcome.appealable,
            explanation=outcome.explanation, payer_trace=trace)


class SandboxProviderDirectory:
    async def find(self, specialty: str, accepting_new: bool = True) -> list[Provider]:
        s = specialty.lower()
        return [p for p in PROVIDERS
                if s in p.specialty.lower() and (p.accepting_new_patients or not accepting_new)]

    async def get(self, npi: str) -> Provider | None:
        return next((p for p in PROVIDERS if p.npi == npi), None)

    async def specialties(self) -> list[str]:
        """The specialties this directory can actually staff.

        Exposed so the intake parser can be constrained to a vocabulary that
        the directory can satisfy, instead of emitting an open-ended specialty
        that would match no provider.
        """
        seen: list[str] = []
        for p in PROVIDERS:
            if p.specialty not in seen:
                seen.append(p.specialty)
        return seen


class SandboxDrugInfo:
    async def interactions(self, rxcuis: list[str]) -> list[Interaction]:
        found, s = [], set(rxcuis)
        for it in INTERACTIONS:
            if it.drug_a in s and it.drug_b in s:
                found.append(it)
        return found

    async def cross_allergies(self, rxcui: str, allergies: list[str]) -> list[str]:
        allergens = _ALLERGEN.get(rxcui, [])
        return [a for a in allergies if a.lower() in [x.lower() for x in allergens]]

    async def formulary(self, payer_id: str, ndc: str) -> FormularyStatus:
        pa = ndc.endswith("99")     # deterministic demo rule
        return FormularyStatus(covered=True, tier=2, prior_auth_required=pa)


class SandboxPharmacy:
    async def send_prescription(self, order: dict) -> str:
        return f"RX-{_hash(str(sorted(order.items())))}"

    async def check_stock(self, ndc: str) -> bool:
        return True

    async def dispatch(self, order_id: str) -> Dispatch:
        return Dispatch(order_id=order_id, tracking=_hash(order_id), status="in_transit")


class SandboxEPCS:
    async def sign(self, prescriber_npi: str, rx_id: str, otp: str) -> EPCSSignature:
        signed = bool(otp) and len(otp) >= 6         # 2nd factor present
        return EPCSSignature(signature_id=_hash(prescriber_npi + rx_id), signed=signed,
                             prescriber_npi=prescriber_npi, two_factor_used=signed, at=_now())


class SandboxPDMP:
    async def query(self, patient_id: str, state: str) -> PDMPReport:
        # deterministic pseudo-history from the patient id
        h = int(_hash(patient_id), 16)
        fills = h % 4
        multi = (h % 7) == 0
        flags = []
        if fills >= 3:
            flags.append("frequent_controlled_fills")
        if multi:
            flags.append("multiple_prescribers")
        return PDMPReport(patient_id=patient_id, state=state,
                          controlled_fills_last_90d=fills, multiple_prescribers=multi, risk_flags=flags)


class SandboxPayment:
    async def charge(self, amount_cents: int, token: str) -> PaymentResult:
        ok = amount_cents > 0 and bool(token)
        return PaymentResult(transaction_id=_hash(token + str(amount_cents)),
                             status="succeeded" if ok else "declined", amount_cents=amount_cents)


class SandboxSchedule:
    """Per-provider availability. Deterministic open slots minus in-session bookings."""

    _HOURS = (9, 11, 13, 15, 17)         # local business hours, 9 AM - 6 PM

    def __init__(self) -> None:
        self._booked: set[tuple[str, str]] = set()

    def _open_slots(self, npi: str) -> list[dict]:
        base = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        out = []
        for d in range(1, 9):
            day = base + timedelta(days=d)
            if day.weekday() >= 5:                       # skip weekends
                continue
            for h in self._HOURS:
                start = day.replace(hour=h).isoformat()
                seed = int(_hash(npi + start), 16)
                if seed % 3 == 0:                        # ~1/3 already booked by others
                    continue
                if (npi, start) in self._booked:
                    continue
                out.append({"start": start, "duration_min": 30})
        return out

    async def availability(self, npi: str, limit: int = 5) -> list[dict]:
        return self._open_slots(npi)[:limit]

    async def book(self, npi: str, start: str) -> bool:
        if (npi, start) in self._booked:
            return False
        self._booked.add((npi, start))
        return True
