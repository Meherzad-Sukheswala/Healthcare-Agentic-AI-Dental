"""Claim Builder (single task: assemble the ADA dental claim / X12 837D). FULL.

A real dental claim usually bills several procedures from the same visit on one
claim (multiple service lines), not just one. When Clinical accepted a treatment
plan, its line-item fees (already tooth-specific and real) are used directly —
`_FEE` is only a fallback fee schedule for the single-code path (e.g. an exam-only
visit, or a caller that hasn't gone through treatment planning at all).
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

# fallback demo fee schedule by CDT (cents) — used only when no treatment-plan
# line items are available
_FEE = {
    "D0140": 9500,      # limited oral evaluation, problem focused
    "D0150": 15000,     # comprehensive oral evaluation
    "D6010": 240000,    # surgical placement of implant body
    "D7953": 65000,     # bone replacement graft for ridge preservation
}


def _apply_defect(claim: dict, defect: str) -> dict:
    """Blank or corrupt one field, mimicking a real data-entry / mapping error.

    Each corresponds to a genuine front-end edit in shared/claim_scrubber.py, so the
    resulting 277CA rejection is produced by the scrubber finding a real problem rather
    than by a flag short-circuiting to a canned response.
    """
    out = dict(claim)
    if defect == "member_id":                       # transposed at the front desk
        out["member_id"] = ""
    elif defect == "npi":                           # NPI field never mapped from the PMS
        out["billing_npi"] = "1234567890"           # fails the CMS Luhn check digit
    elif defect == "tooth":                         # tooth number not carried through
        out["service_lines"] = [dict(ln, tooth="") for ln in out.get("service_lines", [])]
        if out.get("service_lines"):
            out["service_line"] = out["service_lines"][0]
    elif defect == "diagnosis":                     # payer requires a dx; none sent
        out["diagnosis_codes"] = []
        out["service_lines"] = [dict(ln, diagnosis_pointer="") for ln in out.get("service_lines", [])]
        if out.get("service_lines"):
            out["service_line"] = out["service_lines"][0]
    return out


class ClaimBuilder(Agent):
    name = "claim_builder"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        performed = ctx.input_data.get("performed_items", [])
        # Diagnosis pointers and narratives, keyed by line, from the clinical domain.
        line_dx = {d.get("item_id", ""): d for d in ctx.input_data.get("line_diagnoses", [])}
        narratives = ctx.input_data.get("narratives", [])
        narrative_for_cdt: dict[str, str] = {}
        for n in narratives:
            narrative_for_cdt.setdefault(f"{n.get('cdt','')}|{n.get('tooth','')}", n.get("text", ""))

        if performed:
            lines = []
            for i in performed:
                cdt, tooth = i["cdt"], i.get("tooth", "")
                dx = line_dx.get(i.get("item_id", ""), {})
                lines.append({
                    "cdt": cdt, "tooth": tooth,
                    "charge_cents": int(i["fee_cents"]), "units": 1,
                    # ADA item 29a — which of the claim's diagnosis codes justify this line
                    "diagnosis_pointer": dx.get("diagnosis_pointer", ""),
                    "icd10": dx.get("icd10", ""),
                    # the per-tooth justification the payer's consultant reads
                    "narrative": narrative_for_cdt.get(f"{cdt}|{tooth}", ""),
                })
        else:
            # Single-code fallback (exam-only visit, or a caller that skipped treatment
            # planning). A tooth is accepted here because tooth-specific CDT codes are
            # rejected without one by the payer's relational edits — see
            # shared/claim_scrubber.py.
            cdt = ctx.input_data.get("cdt", "D0140")
            lines = [{"cdt": cdt, "tooth": ctx.input_data.get("tooth", ""),
                      "charge_cents": _FEE.get(cdt, 9500), "units": 1,
                      "diagnosis_pointer": "", "icd10": ctx.input_data.get("icd10", ""),
                      "narrative": ""}]

        charge_cents = sum(ln["charge_cents"] for ln in lines)
        # snapshot the coverage terms in force at claim time, so the remittance
        # simulation adjudicates against the SAME numbers the chairside estimate used
        coverage = ctx.get_result("eligibility_checker").get("coverage", {})
        dx_codes = ctx.input_data.get("diagnosis_codes", []) or []
        claim = {
            "transaction": "837D",
            "member_id": ctx.input_data.get("member_id", ""),
            "payer_id": ctx.input_data.get("payer_id", ""),
            "billing_npi": ctx.input_data.get("provider_npi", ""),
            "diagnosis": ctx.input_data.get("icd10", ""),      # principal, backward-compat
            # ADA item 34 / 34a — up to four codes, principal at pointer "A"
            "diagnosis_code_list_qualifier": "AB" if dx_codes else "",
            "diagnosis_codes": dx_codes[:4],
            "diagnosis_required_by_payer": bool(ctx.input_data.get("diagnosis_submission_required")),
            "service_lines": lines,
            "service_line": lines[0],       # backward-compat single-line access
            # PWK / attachment envelope: what the payer needs alongside the claim
            "attachments_recommended": ctx.input_data.get("attachments_recommended", []),
            "copay_cents": coverage.get("copay_cents", 0),
            "deductible_remaining_cents": coverage.get("deductible_remaining_cents", 0),
            "coinsurance_pct": coverage.get("coinsurance_pct", 0.0),
            # Full coverage terms travel WITH the claim so the payer side (front-end
            # edits and adjudication alike) reads the same plan it was billed under —
            # e.g. whether this payer requires a diagnosis code, or applies a least-
            # expensive-alternative provision.
            "coverage_snapshot": coverage,
            # Facts a payer knows that a claim does not state: how late it was filed,
            # whether documentation rode along, what the patient has already used this
            # benefit year. Drives the denial reason — see shared/payer_outcomes.py.
            # Did the practice proactively attach documentation WITH the claim (an
            # unsolicited 275)? That is best practice and skips the pend entirely. Left
            # False, the claim goes out bare and the payer pends for what it needs — which
            # is what happens in a practice without an attachment workflow, and is the
            # case this pipeline exists to answer automatically.
            "attachments_ride_along": bool(ctx.input_data.get("attachments_ride_along", False)),
            "adjudication_context": {
                "days_since_service": ctx.input_data.get("days_since_service", 0),
                "prior_procedures": ctx.input_data.get("prior_procedures", []),
                "duplicate": ctx.input_data.get("duplicate_claim", False),
                "other_coverage_primary": ctx.input_data.get("other_coverage_primary", False),
            },
        }
        # Demo hook: inject ONE realistic data fault so the 277CA rejection path can be
        # shown. These are the actual top causes of dental claim rejection — a member ID
        # transposed at the front desk, an NPI field that never got mapped, a tooth
        # number the PMS didn't carry through. Off by default; a clean claim is the
        # normal case and should stay the normal case.
        defect = str(ctx.input_data.get("claim_defect", "") or "")
        if defect:
            claim = _apply_defect(claim, defect)

        return AgentResult.completed({
            "claim": claim,
            "charge_cents": charge_cents,
            "narrative_count": sum(1 for ln in lines if ln.get("narrative")),
            "injected_defect": defect,
        })
