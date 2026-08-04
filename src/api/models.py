"""
src/api/models.py

Request/response models for the encounter API.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class StartEncounterRequest(BaseModel):
    patient_id: str
    chief_complaint: str = ""
    request_text: str | None = None
    prescribe: list[dict] = Field(default_factory=list)
    labs: dict = Field(default_factory=dict)
    payment_token: str = "tok_demo"
    state: str = "CA"
    pharmacy_id: str = "PHARM-001"
    requires_referral: bool = False
    preferred_provider_npi: str = ""
    identity_ambiguous: bool = False
    self_pay_discount_pct: float | None = None
    secondary_payers: list[dict] = Field(default_factory=list)
    # Insurance override (drives eligibility). payer_id/member_id empty => uninsured.
    payer_id: str | None = None
    member_id: str | None = None
    # self_pay = patient elects to pay cash (may or may not have coverage on file).
    self_pay: bool = False
    # Ancillary/retail line items the patient buys (supplies, DME, OTC). Each:
    # {"description": str, "amount_cents": int, "taxable": bool}. Only taxable ones taxed.
    retail_items: list[dict] = Field(default_factory=list)

    # ---- claim-cycle controls: how the payer responds ----
    # A rejection (277CA, pre-adjudication) and a denial (835 ERA, post-adjudication)
    # are different things needing different work — see src/shared/claim_scrubber.py
    # and src/shared/payer_outcomes.py. Defaults produce a clean, accepted, paid claim.
    #
    # Injects one realistic data-entry / field-mapping fault so the claim is REJECTED by
    # front-end edits: "member_id" | "npi" | "tooth" | "diagnosis".
    claim_defect: str = ""
    # Did the practice proactively attach documentation WITH the claim (unsolicited 275)?
    # True skips the pend entirely — best practice, and what a well-run attachment
    # workflow does. Left False the claim goes out bare and the payer PENDS with a
    # 277RFAI for what it needs, which is the round trip this pipeline answers.
    attachments_ride_along: bool = False
    # Documentation the visit did NOT capture, by document_registry key (e.g.
    # ["preop_radiograph"]). When the payer later asks for one of these the AI cannot
    # answer from the record, so a named human is asked — and for imaging that usually
    # means recalling the patient. Empty = the visit captured its normal imaging.
    imaging_omitted: list[str] = Field(default_factory=list)
    # CDT codes already paid this benefit year — drives frequency-limitation denials
    # (e.g. ["D1110", "D1110"] exhausts the two-cleanings-per-year benefit).
    prior_procedures: list[str] = Field(default_factory=list)
    # Days between date of service and claim submission; past the payer's limit this
    # produces a timely-filing denial, which is a write-off rather than an appeal.
    days_since_service: int = 0
    duplicate_claim: bool = False
    other_coverage_primary: bool = False


class ResumeRequest(BaseModel):
    """A human decision for one gate."""

    gate_id: str
    approved: bool = True
    actor: str = "unknown"
    note: str = ""


class EncounterStateResponse(BaseModel):
    encounter_id: str
    status: str                       # completed | awaiting_human | partial | failed
    awaiting_domain: str = ""
    awaiting_gate: dict | None = None
    summary: dict = Field(default_factory=dict)
    domains: dict = Field(default_factory=dict)
    # LLM activity during THIS pass (live calls + cache reuse), for observability.
    llm_calls: list[dict] = Field(default_factory=list)
