"""
src/shared/claim_scrubber.py

Front-end claim edits — the checks that REJECT a claim before any payer adjudicates it.

REJECTION IS NOT DENIAL
-----------------------
These two get conflated constantly, and they need opposite handling:

  REJECTION  the clearinghouse or the payer's front-end edits bounce the claim before
             adjudication. Reported on a 277CA with a Claim Status Category Code, a
             Claim Status Code and the offending data element. NO CARC codes, because
             nothing was adjudicated. NOT appealable — there is no decision to appeal.
             The biller fixes the field and resubmits, often within a day.

  DENIAL     the payer adjudicated the claim and decided not to pay. Arrives on an 835
             ERA with CARC/RARC codes. Appealable, on a 30-90 day cycle.
             See src/shared/payer_outcomes.py for that half.

Two acknowledgement layers exist and only the second one matters here:

  999     X12 syntax / TR3 conformance only. Per X12 RFI #2099 a 999 acceptance does
          NOT confirm the payer received the claim — only that the envelope parsed.
  277CA   claim-level acceptance into adjudication. Carries the official payer receipt
          date, which is what the timely-filing clock runs from.

Claim Status Category Codes used below:
  A2  accepted into adjudication
  A6  rejected — missing information
  A7  rejected — invalid information
  A8  rejected — relational field in error (one field is wrong *given* another)

Claim Status Codes are from the X12 507 code list. Real clearinghouses run two edit
passes — generic front-end edits, then payer-specific ones from each carrier's
companion guide — which is why `requires_diagnosis_codes` is consulted per payer here.
"""
from __future__ import annotations

from .medical_codes import is_valid_icd10, is_valid_npi

# CDT code ranges where a tooth number is required for the line to be adjudicable.
# Restorative, endodontic, crown and extraction codes are tooth-specific; diagnostic,
# preventive and quadrant-level periodontal codes are not.
_TOOTH_REQUIRED_PREFIXES = ("D2", "D3", "D6", "D7")
_TOOTH_EXEMPT = {"D7953"}          # site-level graft; site is carried, tooth optional


def _item(category: str, code: str, description: str, element: str, fix: str) -> dict:
    return {"category_code": category, "status_code": code, "description": description,
            "element": element, "fix_hint": fix}


def scrub_claim(claim: dict, coverage: dict | None = None) -> list[dict]:
    """Front-end edits on an 837D. Returns one entry per problem; empty means clean.

    Each entry is shaped like a 277CA status line: the category, the status code, the
    data element at fault, and what a biller does about it. The `element` field is the
    whole point — a rejection a biller can't locate is a rejection they can't fix.
    """
    problems: list[dict] = []
    coverage = coverage or {}
    lines = claim.get("service_lines") or []

    # --- subscriber / payer identity -------------------------------------------------
    if not str(claim.get("member_id", "")).strip():
        problems.append(_item(
            "A6", "164", "Entity's contract/member number is missing",
            "SBR / member_id", "Re-verify the subscriber ID from the patient's card and resubmit."))

    if not str(claim.get("payer_id", "")).strip():
        problems.append(_item(
            "A7", "116", "Claim submitted to incorrect payer",
            "NM1*PR / payer_id", "Confirm the correct payer and destination, then resubmit."))

    # --- billing provider -------------------------------------------------------------
    npi = str(claim.get("billing_npi", "")).strip()
    if not npi:
        problems.append(_item(
            "A6", "562", "Entity's National Provider Identifier (NPI) is missing",
            "NM1*85 / billing_npi", "Add the billing provider's NPI and resubmit."))
    elif not is_valid_npi(npi):
        problems.append(_item(
            "A7", "562", "Entity's National Provider Identifier (NPI) is invalid",
            "NM1*85 / billing_npi", "Correct the NPI (10 digits, valid check digit) and resubmit."))

    # --- service lines ----------------------------------------------------------------
    if not lines:
        problems.append(_item(
            "A6", "453", "Procedure code for services rendered is missing",
            "SV3 / service_lines", "Add at least one procedure line and resubmit."))

    for i, ln in enumerate(lines, start=1):
        ref = f"line {i} ({ln.get('cdt', '?')})"
        cdt = str(ln.get("cdt", "")).upper()
        if int(ln.get("charge_cents", 0)) <= 0:
            problems.append(_item(
                "A7", "400", "Claim is out of balance — line charge must be greater than zero",
                f"SV3-02 / {ref}", "Correct the line fee and resubmit."))
        # Relational edit: this code REQUIRES a tooth number, and none was sent.
        if (cdt.startswith(_TOOTH_REQUIRED_PREFIXES) and cdt not in _TOOTH_EXEMPT
                and not str(ln.get("tooth", "")).strip()):
            problems.append(_item(
                "A8", "453", f"Tooth number is required for procedure {cdt}",
                f"TOO-02 / {ref}", "Add the tooth number in universal notation and resubmit."))

    # --- payer-specific edits (the companion-guide pass) -------------------------------
    # Medicare rejects dental claims with no valid ICD-10 (eff. 2025-07-01); several
    # state Medicaid dental programs do the same.
    if coverage.get("requires_diagnosis_codes") or claim.get("diagnosis_required_by_payer"):
        codes = [c for c in (claim.get("diagnosis_codes") or []) if is_valid_icd10(c)]
        if not codes:
            problems.append(_item(
                "A6", "255", "Diagnosis code is required by this payer and is missing or invalid",
                "HI / diagnosis_codes", "Add a valid ICD-10-CM diagnosis code and resubmit."))
        elif not any(str(ln.get("diagnosis_pointer", "")).strip() for ln in lines):
            problems.append(_item(
                "A8", "255", "Diagnosis code pointer is required on each service line",
                "SV3 / diagnosis_pointer", "Point each procedure line at a diagnosis code (A-D) and resubmit."))

    return problems
