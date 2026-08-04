"""
Diagnosis Coder (single task: attach diagnosis codes to each procedure line). PARTIAL.

Replaces the old `icd10_coder`, which produced ONE encounter-level ICD-10. That shape
cannot be put on a real dental claim.

HOW A DENTAL CLAIM CARRIES DIAGNOSES
------------------------------------
On the 2024 ADA claim form / 837D:
  item 34   Diagnosis Code List Qualifier — "AB" for ICD-10-CM
  item 34a  up to FOUR diagnosis codes, A through D, primary adjacent to "A"
  item 29a  Diagnosis Code Pointer — per PROCEDURE LINE, which of A-D justify it

So the output here is a code list plus a pointer per line, not a single code. Each
performed procedure points at the diagnosis for its own tooth, falling back to the
principal diagnosis for procedures that aren't tooth-specific (periodontal quadrants,
occlusal guards).

WHETHER THEY GET SUBMITTED IS PAYER-DEPENDENT
---------------------------------------------
Dental claims are adjudicated on CDT procedure codes; the diagnosis is supplementary.
But it is no longer optional everywhere:
  * Medicare — claims received on/after 2025-07-01 REJECT without a valid ICD-10
    (plus a KX modifier for dental services inextricably linked to covered medical care)
  * Medicaid dental in several states, BCBS Federal, Horizon Blue — required
  * medical cross-coding (CBCT, sleep appliances, medically necessary oral surgery)
    — mandatory, and that path also carries real prior authorization
  * most commercial dental plans — accepted but not required

So this agent always computes the codes and reports whether the payer requires them,
rather than skipping and leaving the claim silently short. See
docs/us-dental-clinic-real-world-workflow.md §5.3 and §7.7.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation
from src.shared.medical_codes import is_valid_icd10

# Payer types that reject or require a diagnosis code on the dental claim.
_REQUIRES_DX = {
    "medicare": "Medicare rejects dental claims without a valid ICD-10 (eff. 2025-07-01)",
    "medicaid": "Medicaid dental programs in several states mandate a diagnosis code",
}
_POINTER_LETTERS = "ABCD"


class DiagnosisCoder(Agent):
    name = "diagnosis_coder"
    automation = Automation.PARTIAL

    async def execute(self, ctx) -> AgentResult:
        transcript = ctx.get_result("clinical_note_transcriber")
        performed = ctx.get_result("procedure_documentor").get("performed_items", [])

        codes = [c for c in transcript.get("claim_diagnosis_codes", []) if is_valid_icd10(c)]
        principal = transcript.get("principal_icd10", "")
        if not codes:
            fallback = principal or ctx.get_result("diagnosis_signoff").get("confirmed_icd10", "")
            codes = [fallback] if is_valid_icd10(fallback) else []
        if not principal and codes:
            principal = codes[0]

        # tooth -> its own diagnosis, so each line points at the right code
        by_tooth = {d["tooth"]: d["icd10"] for d in transcript.get("diagnoses", []) if d.get("tooth")}
        letter_for = {code: _POINTER_LETTERS[i] for i, code in enumerate(codes[:4])}

        lines = []
        for item in performed:
            tooth = item.get("tooth", "")
            code = by_tooth.get(tooth, principal)
            if code not in letter_for:          # a tooth-specific code that didn't make the top 4
                code = principal
            pointer = letter_for.get(code, "")
            lines.append({
                "item_id": item.get("item_id", ""),
                "cdt": item.get("cdt", ""),
                "tooth": tooth,
                "icd10": code,
                "diagnosis_pointer": pointer,   # item 29a
            })

        coverage = ctx.input_data.get("coverage", {}) or {}
        payer_type = coverage.get("payer_type", "commercial")
        required = payer_type in _REQUIRES_DX or bool(coverage.get("requires_diagnosis_codes"))
        reason = _REQUIRES_DX.get(
            payer_type,
            "Required by this payer" if coverage.get("requires_diagnosis_codes")
            else "Accepted but not required by this payer — claim adjudicates on CDT")

        return AgentResult.completed({
            # item 34 / 34a
            "code_list_qualifier": "AB",        # ICD-10-CM
            "diagnosis_codes": codes[:4],
            "principal_icd10": principal,
            # item 29a, one entry per service line
            "line_diagnoses": lines,
            # submission policy
            "submission_required": required,
            "submission_reason": reason,
            # backward-compatible single-value key used across the pipeline
            "icd10": principal,
            "valid": bool(codes) and all(is_valid_icd10(c) for c in codes),
        })
