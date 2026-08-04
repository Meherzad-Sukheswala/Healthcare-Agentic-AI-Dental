"""
src/integrations/models.py

DTOs exchanged with external services. Field shapes mirror the real standards
(FHIR resources, X12 270/271/278/837, NCPDP) so the sandbox data is authentic.
"""
from __future__ import annotations

from pydantic import Field

from src.shared.base_types import CodedConcept, HealthcareModel
from src.shared.enums import Severity


class PatientRecord(HealthcareModel):
    """FHIR Patient + a summarized clinical snapshot."""

    patient_id: str
    first_name: str
    last_name: str
    birth_date: str                       # ISO date
    sex: str = "unknown"
    member_id: str = ""
    payer_id: str = ""
    allergies: list[str] = Field(default_factory=list)          # substances
    medications: list[CodedConcept] = Field(default_factory=list)  # RxNorm
    conditions: list[CodedConcept] = Field(default_factory=list)   # ICD-10
    source: str = "sandbox"               # "sandbox" | "fhir_public"


class Coverage(HealthcareModel):
    """X12 271 eligibility response.

    `category_coverage_pct` mirrors how dental plans actually structure benefits:
    preventive (cleanings/exams) at 100%, basic (fillings/extractions) around 80%,
    major (crowns/implants/dentures) around 50% — coinsurance_pct is the commercial
    default fallback for categories not listed. `annual_max_*` models the yearly
    benefit cap dental plans use in place of medical's out-of-pocket maximum.
    """

    active: bool
    payer_id: str
    plan: str = ""
    payer_type: str = "commercial"        # commercial | medicare | medicaid | self_pay
    service_covered: bool = True
    copay_cents: int = 0
    coinsurance_pct: float = 0.0
    deductible_remaining_cents: int = 0
    annual_max_cents: int = 150000
    annual_max_used_cents: int = 0
    # Whether this payer requires an ICD-10 diagnosis code on the dental claim.
    # Dental claims adjudicate on CDT, so most commercial plans accept a diagnosis
    # without requiring one — but Medicare REJECTS dental claims without a valid
    # ICD-10 (eff. 2025-07-01), and Medicaid dental in several states mandates it.
    requires_diagnosis_codes: bool = False
    # Least Expensive Alternative Treatment: the plan pays for the cheapest clinically
    # acceptable option rather than the one performed (porcelain crown paid at the
    # cast-metal rate, posterior composite at the amalgam rate). Common in commercial
    # dental plans; the differential falls to the patient.
    alternate_benefit_provision: bool = False
    # Days from date of service in which a claim must be filed. Varies widely by payer
    # (90 days to 12 months); the deadline is printed on the EOB and provider manual.
    timely_filing_days: int = 365
    category_coverage_pct: dict[str, float] = Field(
        default_factory=lambda: {"preventive": 1.0, "basic": 0.8, "major": 0.5})

    @property
    def annual_max_remaining_cents(self) -> int:
        return max(0, self.annual_max_cents - self.annual_max_used_cents)


class PriorAuthResult(HealthcareModel):
    """X12 278 response.

    Dental predetermination (the common case here) is advisory — an estimate the
    payer will honor if nothing changes before treatment, not a gate the practice
    must wait on before treating. Medical prior-auth is typically a hard requirement.
    `is_advisory=True` marks the dental predetermination case.
    """

    status: str                           # approved | pended | denied
    auth_number: str = ""
    requires_clinical_review: bool = False
    reason: str = ""
    is_advisory: bool = True
    estimated_payer_cents: int = 0
    estimated_patient_cents: int = 0


class ClaimStatusItem(HealthcareModel):
    """One 277CA claim-status line: why a claim was rejected, and where.

    `element` is the load-bearing field — a rejection whose offending data element a
    biller cannot locate is a rejection they cannot fix.
    """

    category_code: str          # A2 accepted · A6 missing info · A7 invalid info · A8 relational
    status_code: str            # X12 507 Claim Status Code
    description: str
    element: str = ""           # e.g. "NM1*85 / billing_npi"
    fix_hint: str = ""


class ClaimAck(HealthcareModel):
    """Acknowledgement for a submitted 837 claim — the REJECTION half of the cycle.

    Models the two real acknowledgement layers, because only the second decides whether
    a claim was accepted into adjudication:

      `syntax_ok`  the 999 layer: X12 / TR3 conformance. Per X12 RFI #2099 a 999
                   acceptance does NOT mean the payer received the claim.
      `accepted`   the 277CA layer: acceptance into adjudication. This is the one that
                   matters, and `payer_receipt_date` is the timely-filing anchor.

    A rejected claim never reaches adjudication, so it has NO CARC codes and is NOT
    appealable — see src/shared/claim_scrubber.py. Denials are the other half and live
    on RemittanceAdvice.
    """

    control_number: str
    accepted: bool
    status: str = "received"    # received | accepted | rejected
    transaction: str = "277CA"
    syntax_ok: bool = True
    payer_receipt_date: str = ""
    rejections: list["ClaimStatusItem"] = Field(default_factory=list)
    # the front-end edit passes, for the claim-exchange view
    payer_trace: list[dict] = Field(default_factory=list)

    @property
    def is_rejected(self) -> bool:
        return not self.accepted


class RequestedDocument(HealthcareModel):
    """One document a payer is asking for, on a 277RFAI."""

    doc_key: str                    # maps to src/shared/document_registry.DOCUMENT_TYPES
    label: str
    reason: str = ""                # why the payer wants it
    pwk_code: str = ""              # X12 755 report type it will come back under
    service_line_cdt: str = ""      # which procedure it supports, when line-specific


class InformationRequest(HealthcareModel):
    """X12 277RFAI — the payer ASKING for documentation, not refusing to pay.

    This is the state most "we need more evidence" situations actually arrive in. The
    claim was accepted, adjudication started and then STOPPED pending documents, and a
    clock is running. A denial for missing information is what happens when this goes
    unanswered — not the payer's opening move.

    Solicited requests name the wanted document types with LOINC codes in the STC
    segment. `pwk_code` on each item is the X12 755 report type the practice will send
    them back under in the 275/PWK.
    """

    claim_control_number: str
    requested: list["RequestedDocument"] = Field(default_factory=list)
    reason_summary: str = ""
    due_date: str = ""              # ISO date the payer wants it by
    respond_within_days: int = 30
    # Reconstruction of the payer-side steps that led here. Labelled explicitly because
    # a practice cannot see inside adjudication — this is inferred from the transactions
    # the payer sends plus published plan rules, not data the payer discloses.
    payer_trace: list[dict] = Field(default_factory=list)


class ClaimAttachment(HealthcareModel):
    """X12 275 — the documentation going back, with its PWK linkage.

    `attachment_control_number` is what ties the 275 to the claim (NEA FastAttach and
    similar services issue one). A PWK segment declared on the 837 without a matching
    payload here is the failure mode this model exists to make impossible: some payers
    stall such a claim indefinitely, which is worse than sending nothing at all.
    """

    attachment_control_number: str
    claim_control_number: str
    transaction: str = "275"
    documents: list[dict] = Field(default_factory=list)   # {doc_key,label,pwk,detail}
    pwk_segments: list[dict] = Field(default_factory=list)  # {PWK01,PWK02,PWK06}
    accepted: bool = True
    complete: bool = False          # did it satisfy everything the payer asked for?
    outstanding: list[str] = Field(default_factory=list)


class CARCAdjustment(HealthcareModel):
    """A single Claim Adjustment Reason Code line on a remittance."""

    code: str              # e.g. "1", "2", "3", "45", "96", "119"
    description: str
    amount_cents: int


class RemittanceAdvice(HealthcareModel):
    """X12 835 electronic remittance advice (ERA) — the payer's response to a
    submitted claim: what they paid, what they adjusted, and why (CARC codes)."""

    claim_control_number: str
    billed_cents: int
    allowed_cents: int                    # post-contractual-adjustment amount
    paid_cents: int
    patient_responsibility_cents: int
    adjustments: list["CARCAdjustment"] = Field(default_factory=list)
    # paid                    correctly adjudicated per plan terms (any payer/patient split)
    # paid_alternate_benefit  paid at a cheaper procedure's rate (LEAT) — differential is
    #                         PATIENT responsibility, not a contractual write-off
    # denied                  adjudicated and refused; see `reason` for which kind
    status: str = "paid"
    # Reconstruction of the payer's adjudication steps. See InformationRequest.payer_trace
    # — this is inferred from what the payer sends back plus published plan rules, never
    # something the payer actually discloses.
    payer_trace: list[dict] = Field(default_factory=list)
    # Which denial this is, and what to do about it. Eight reasons route to five
    # different actions and only two are appeals — see src/shared/payer_outcomes.py.
    reason: str = "adjudicated"
    action: str = "none"                  # appeal | resubmit_with_attachment | bill_patient | write_off | rebill_other_payer | none
    appealable: bool = False
    explanation: str = ""


class Provider(HealthcareModel):
    """NPPES provider record."""

    npi: str
    first_name: str
    last_name: str
    specialty: str
    facility: str = ""
    accepting_new_patients: bool = True


class Interaction(HealthcareModel):
    drug_a: str
    drug_b: str
    severity: Severity
    description: str = ""


class FormularyStatus(HealthcareModel):
    covered: bool
    tier: int = 0
    prior_auth_required: bool = False


class Dispatch(HealthcareModel):
    order_id: str
    carrier: str = "sandbox-courier"
    tracking: str = ""
    status: str = "in_transit"


class EPCSSignature(HealthcareModel):
    """Simulated DEA EPCS 2-factor signing event."""

    signature_id: str
    signed: bool
    prescriber_npi: str
    two_factor_used: bool = True
    at: str = ""


class PDMPReport(HealthcareModel):
    patient_id: str
    state: str
    controlled_fills_last_90d: int = 0
    multiple_prescribers: bool = False
    risk_flags: list[str] = Field(default_factory=list)


class PaymentResult(HealthcareModel):
    transaction_id: str
    status: str                           # succeeded | declined
    amount_cents: int = 0
