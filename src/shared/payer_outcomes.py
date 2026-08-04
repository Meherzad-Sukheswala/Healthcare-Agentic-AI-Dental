"""
src/shared/payer_outcomes.py

What the payer DECIDES once a claim reaches adjudication — and, crucially, what the
practice should do about each decision.

WHY "DENIED" IS NOT ONE THING
-----------------------------
Roughly 15% of dental claims come back not-paid-as-billed, and the reasons route to
completely different work. Treating them as one bucket ("denied -> appeal") teaches a
biller the wrong move most of the time:

  reason                    what it means                          correct action
  ------------------------- -------------------------------------- ----------------------
  not covered               plan excludes the service              appeal w/ narrative
  missing attachment        payer wants the radiograph/perio chart RESUBMIT w/ attachment
  frequency limitation      2 cleanings/yr already used            bill the patient
  annual maximum reached    benefit cap exhausted for the year     bill the patient
  alternate benefit (LEAT)  paid at a cheaper procedure's rate     bill difference / appeal
  timely filing expired     claim filed too late                   write off
  duplicate                 already adjudicated                    no action
  other coverage primary    wrong payer billed first               rebill correct payer

Only two of those eight are appeals. "Missing attachment" is a resubmission, not an
appeal, and getting that wrong costs a practice the 30-90 day appeal cycle for something
fixable in a day.

THE ALTERNATE BENEFIT (LEAT) CASE IS NOT A DENIAL AT ALL
--------------------------------------------------------
Least Expensive Alternative Treatment: the plan pays for the cheapest clinically
acceptable option, not the one performed. A porcelain crown gets paid at the full-cast-
metal rate; a posterior composite gets paid at the amalgam rate. The claim is PAID — the
differential just becomes patient responsibility rather than a contractual write-off,
which is the distinction that matters, because the practice may legitimately bill the
patient for it. Modeling this as a denial would be wrong twice over: wrong status, and
wrong party owing the money.

CARC codes below are the standard X12 list. Real payers vary in which CARC they pair
with a LEAT downgrade (some use 59, some a proprietary remark plus RARC); 59 is used
here and the description states the provision explicitly so the intent is unambiguous.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------- actions
ACTION_APPEAL = "appeal"
ACTION_RESUBMIT_ATTACHMENT = "resubmit_with_attachment"
ACTION_BILL_PATIENT = "bill_patient"
ACTION_WRITE_OFF = "write_off"
ACTION_REBILL_OTHER_PAYER = "rebill_other_payer"
ACTION_NONE = "none"

# --------------------------------------------------------------- LEAT downgrade pairs
# performed CDT -> (alternate CDT the plan will pay for, its typical allowed fee)
ALTERNATE_BENEFIT: dict[str, tuple[str, int, str]] = {
    "D2740": ("D2790", 105000, "Crown — full cast high noble metal"),
    "D2750": ("D2790", 105000, "Crown — full cast high noble metal"),
    "D6058": ("D6059", 130000, "Abutment supported metal crown"),
    "D2392": ("D2150", 16000, "Amalgam — two surfaces, posterior"),
    "D2391": ("D2140", 13000, "Amalgam — one surface, posterior"),
}

# Procedures whose claims a payer will not adjudicate without documentation.
ATTACHMENT_REQUIRED = {"D2740", "D2750", "D2950", "D3310", "D3320", "D3330",
                       "D4341", "D4342", "D6010", "D6058", "D7953"}

# What a payer asks for, per procedure, when it pends a claim for documentation.
# doc_key -> see src/shared/document_registry.DOCUMENT_TYPES
DOCUMENTATION_EXPECTED: dict[str, list[tuple[str, str]]] = {
    "D3310": [("preop_radiograph", "Confirm pulpal/periapical pathology before treatment"),
              ("postop_radiograph", "Confirm the canal was obturated to length")],
    "D3320": [("preop_radiograph", "Confirm pulpal/periapical pathology before treatment"),
              ("postop_radiograph", "Confirm the canal was obturated to length")],
    "D3330": [("preop_radiograph", "Confirm pulpal/periapical pathology before treatment"),
              ("postop_radiograph", "Confirm the canals were obturated to length")],
    "D2740": [("preop_radiograph", "Show remaining tooth structure justifying full coverage")],
    "D2750": [("preop_radiograph", "Show remaining tooth structure justifying full coverage")],
    "D2950": [("preop_radiograph", "Show the extent of coronal destruction")],
    "D4341": [("perio_charting", "Probing depths at 6 sites per tooth for the quadrant"),
              ("full_mouth_series", "Demonstrate bone loss supporting definitive therapy")],
    "D4342": [("perio_charting", "Probing depths at 6 sites per tooth for the treated teeth")],
    "D6010": [("cbct", "Confirm ridge dimensions and proximity to vital structures")],
    "D7953": [("cbct", "Demonstrate the osseous defect being grafted")],
    "D6058": [("preop_radiograph", "Confirm implant osseointegration before restoring")],
}


def documentation_expected_for(codes: list[str]) -> list[dict]:
    """The documents a payer would ask for, given the procedures billed.

    De-duplicated across lines — a payer asks for one full-mouth series, not one per
    quadrant — while remembering which procedure drove the request.
    """
    out: dict[str, dict] = {}
    for code in codes:
        code = str(code).upper()
        for doc_key, reason in DOCUMENTATION_EXPECTED.get(code, []):
            if doc_key not in out:
                out[doc_key] = {"doc_key": doc_key, "reason": reason, "service_line_cdt": code}
    return list(out.values())

# Frequency-limited preventive/diagnostic codes: allowed occurrences per benefit year.
FREQUENCY_LIMITS = {"D1110": 2, "D1120": 2, "D0120": 2, "D0150": 1,
                    "D0274": 1, "D0210": 1, "D1206": 1, "D1208": 1}


class Outcome:
    """One adjudication outcome: the status, why, and what to do next."""

    def __init__(self, status: str, reason: str, carc: str, carc_description: str,
                 action: str, appealable: bool, explanation: str, rarc: str = ""):
        self.status = status
        self.reason = reason
        self.carc = carc
        self.carc_description = carc_description
        self.rarc = rarc
        self.action = action
        self.appealable = appealable
        self.explanation = explanation

    def as_dict(self) -> dict:
        return {"status": self.status, "reason": self.reason, "carc": self.carc,
                "carc_description": self.carc_description, "rarc": self.rarc,
                "action": self.action, "appealable": self.appealable,
                "explanation": self.explanation}


def _o(**kw) -> Outcome:
    return Outcome(**kw)


PAID = _o(status="paid", reason="adjudicated", carc="", carc_description="",
          action=ACTION_NONE, appealable=False,
          explanation="Claim adjudicated per plan terms.")


def classify(claim: dict, coverage: dict, context: dict | None = None) -> Outcome:
    """The payer's decision on an accepted claim.

    `context` carries the facts a payer knows but a claim doesn't state:
      days_since_service     int   for the timely-filing test
      documentation_complete bool  did the practice supply everything the payer asked for?
                                   Only False once a 277RFAI has gone unanswered.
      prior_procedures       list  CDT codes already paid this benefit year
      duplicate            bool  this control number was already adjudicated
      other_coverage_primary bool another plan should have been billed first
    Checks run in the order a payer applies them: administrative gates first, then
    coverage, then benefit limits, then the alternate-benefit determination.
    """
    ctx = context or {}
    lines = claim.get("service_lines") or []
    codes = [str(ln.get("cdt", "")).upper() for ln in lines if ln]

    # 1. administrative gates — checked before any benefit logic
    if ctx.get("duplicate"):
        return _o(status="denied", reason="duplicate", carc="18",
                  carc_description="Exact duplicate claim/service",
                  action=ACTION_NONE, appealable=False,
                  explanation="This claim was already adjudicated. No action — check the original payment.")

    if ctx.get("other_coverage_primary"):
        return _o(status="denied", reason="other_coverage_primary", carc="22",
                  carc_description="This care may be covered by another payer per coordination of benefits",
                  action=ACTION_REBILL_OTHER_PAYER, appealable=False,
                  explanation="Bill the primary plan first, then resubmit here with its EOB attached.")

    filing_limit = int(coverage.get("timely_filing_days", 365))
    days = int(ctx.get("days_since_service", 0))
    if days > filing_limit:
        return _o(status="denied", reason="timely_filing", carc="29",
                  carc_description="The time limit for filing has expired",
                  action=ACTION_WRITE_OFF, appealable=False,
                  explanation=(f"Filed {days} days after service; this plan's limit is {filing_limit}. "
                               "Not appealable — write off and fix the submission lag."))

    # 2. documentation. Note the ORDER OF EVENTS this represents: a payer's first move on
    # a claim it can't judge is to PEND and issue a 277RFAI (see
    # SandboxClaims.get_information_request), not to deny. This denial is what happens
    # when that request goes unanswered — the practice couldn't produce the document, or
    # nobody worked the request before the clock ran out.
    needs_attachment = [c for c in codes if c in ATTACHMENT_REQUIRED]
    if needs_attachment and ctx.get("documentation_complete") is False:
        return _o(status="denied", reason="missing_attachment", carc="16",
                  carc_description="Claim/service lacks information or has submission/billing error(s)",
                  rarc="N706", action=ACTION_RESUBMIT_ATTACHMENT, appealable=False,
                  explanation=("Documentation requested for "
                               f"{', '.join(sorted(set(needs_attachment)))} was not supplied. "
                               "Resubmit WITH the attachment — this is not an appeal, and "
                               "appealing it wastes the cycle."))

    # 3. coverage
    if not coverage.get("service_covered", True):
        return _o(status="denied", reason="not_covered", carc="96",
                  carc_description="Non-covered charge(s)",
                  action=ACTION_APPEAL, appealable=True,
                  explanation="Plan excludes this service. Appeal with a medical-necessity narrative if warranted.")

    # 4. benefit limits
    prior = [str(c).upper() for c in (ctx.get("prior_procedures") or [])]
    for code in codes:
        limit = FREQUENCY_LIMITS.get(code)
        if limit is not None and prior.count(code) >= limit:
            return _o(status="denied", reason="frequency_limitation", carc="119",
                      carc_description="Benefit maximum for this time period or occurrence has been reached",
                      action=ACTION_BILL_PATIENT, appealable=False,
                      explanation=(f"{code} is limited to {limit} per benefit year and the patient has "
                                   f"already used {prior.count(code)}. Patient responsibility — "
                                   "not a payer error, so an appeal will not succeed."))

    remaining = int(coverage.get("annual_max_cents", 0)) - int(coverage.get("annual_max_used_cents", 0))
    if int(coverage.get("annual_max_cents", 0)) > 0 and remaining <= 0:
        return _o(status="denied", reason="annual_maximum", carc="119",
                  carc_description="Benefit maximum for this time period or occurrence has been reached",
                  action=ACTION_BILL_PATIENT, appealable=False,
                  explanation=("Annual maximum exhausted for this benefit year. Patient responsibility; "
                               "offer to defer elective phases into the next plan year."))

    # 5. alternate benefit — a PAID outcome, with the differential owed by the patient
    if coverage.get("alternate_benefit_provision"):
        for code in codes:
            if code in ALTERNATE_BENEFIT:
                alt, _fee, alt_name = ALTERNATE_BENEFIT[code]
                return _o(status="paid_alternate_benefit", reason="alternate_benefit", carc="59",
                          carc_description=("Processed under the plan's alternate benefit provision — "
                                            f"allowed at the {alt} rate"),
                          action=ACTION_BILL_PATIENT, appealable=True,
                          explanation=(f"Plan pays {code} at the {alt} ({alt_name}) benefit level. The "
                                       "difference is patient responsibility, NOT a contractual "
                                       "write-off. Appealable with a narrative if the downgrade is "
                                       "clinically inappropriate."))

    return PAID


def alternate_allowed_cents(lines: list[dict]) -> int:
    """Allowed total under the alternate benefit provision.

    A line with a cheaper clinically acceptable alternative is allowed at the
    ALTERNATIVE's fee (capped at what was billed, since a plan never allows more than
    the charge); every other line is allowed at its billed charge. The shortfall this
    creates is patient responsibility, not a contractual write-off.
    """
    total = 0
    for ln in lines:
        code = str(ln.get("cdt", "")).upper()
        billed = int(ln.get("charge_cents", 0))
        alt = ALTERNATE_BENEFIT.get(code)
        total += min(billed, alt[1]) if alt else billed
    return total
