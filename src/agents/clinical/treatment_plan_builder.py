"""
Treatment Plan Builder (single task: draft procedures for the confirmed diagnosis). PARTIAL.

This is the piece a real dental encounter cannot skip: the dentist doesn't just name
a diagnosis, they write up what they're going to DO about it — specific CDT
procedures, which tooth, and which phase of care. Real treatment plans are commonly
phased (Emergency -> Phase I non-surgical -> Phase II surgical -> Phase III
restorative -> Maintenance) because a single problem often takes more than one
procedure to fully resolve (e.g. root canal now, crown once it's healed).

Deterministic map keyed by the confirmed ICD-10 (same "one small map, obvious
mismatches only" philosophy as fraud/consistency_checker.py). AI drafts; the dentist
reviews and can override at the next (treatment_plan_review) gate — hence PARTIAL,
not FULL.
"""
from __future__ import annotations

import hashlib

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

# confirmed ICD-10 -> ordered list of recommended procedures (phased treatment)
_TREATMENT_MAP: dict[str, list[dict]] = {
    "Z01.20": [  # hygiene / recall visit — whole-mouth codes, never tooth-specific
        {"cdt": "D0120", "description": "Periodic oral evaluation — established patient",
         "phase": "diagnostic", "fee_cents": 6500, "assign_tooth": False},
        {"cdt": "D1110", "description": "Prophylaxis — adult",
         "phase": "preventive", "fee_cents": 11000, "assign_tooth": False},
    ],
    "K04.7": [  # periapical abscess: save the tooth now, protect it once it's healed
        {"cdt": "D3330", "description": "Root canal therapy, molar",
         "phase": "phase1_nonsurgical", "fee_cents": 110000, "assign_tooth": True},
        {"cdt": "D2740", "description": "Crown — porcelain/ceramic",
         "phase": "phase3_restorative", "fee_cents": 120000, "assign_tooth": True},
    ],
    "K05.10": [  # chronic gingivitis / early periodontitis: quadrant-level, not one tooth
        {"cdt": "D4341", "description": "Periodontal scaling & root planing, per quadrant",
         "phase": "phase1_nonsurgical", "fee_cents": 27500, "assign_tooth": False},
    ],
    "K02.9": [  # dental caries: a filling on the affected tooth
        {"cdt": "D2391", "description": "Resin composite filling, one surface, posterior",
         "phase": "phase1_nonsurgical", "fee_cents": 22000, "assign_tooth": True},
    ],
    "M26.60": [  # TMJ disorder: an orthotic, not a tooth-specific procedure
        {"cdt": "D7880", "description": "Occlusal orthotic device (night guard)",
         "phase": "phase1_nonsurgical", "fee_cents": 65000, "assign_tooth": False},
    ],
    "K08.409": [  # partial edentulism: graft the site, then implant, then restore it
        {"cdt": "D7953", "description": "Bone replacement graft for ridge preservation",
         "phase": "phase2_surgical", "fee_cents": 65000, "assign_tooth": True},
        {"cdt": "D6010", "description": "Surgical placement of implant body — endosteal",
         "phase": "phase2_surgical", "fee_cents": 240000, "assign_tooth": True},
        {"cdt": "D6058", "description": "Abutment-supported porcelain/ceramic crown",
         "phase": "phase3_restorative", "fee_cents": 175000, "assign_tooth": True},
    ],
    # K08.9 (unspecified) and any other diagnosis intentionally has no entry: the
    # exam alone is billed (see procedure_documentor's fallback) rather than
    # inventing a procedure with no clinical basis.
}

# ICD-10 families, for a diagnosis the exact map doesn't carry. ICD-10 genuinely
# clusters by clinical indication here, so this is more than string convenience:
# every K04.x is a disease of pulp or periapical tissue and implies endodontic
# treatment, every K05.x is periodontal, every M26.x is a dentofacial/TMJ disorder.
# Without this, a dentist amending K04.7 to K04.1 (necrosis of pulp — which still
# needs a root canal) would watch the whole treatment plan disappear.
#
# Longest prefix wins, which is what keeps K08.4xx (partial loss of teeth -> implant)
# separate from bare K08.9 (unspecified -> deliberately no plan).
_FAMILY_FALLBACK: dict[str, str] = {
    "Z01.2": "Z01.20",    # dental examination, with or without findings -> recall visit
    "K08.4": "K08.409",   # partial loss of teeth -> graft + implant + crown
    "K04": "K04.7",       # diseases of pulp / periapical tissues -> endodontic
    "K02": "K02.9",       # dental caries -> restorative
    "K05": "K05.10",      # gingival / periodontal disease -> SRP
    "M26": "M26.60",      # dentofacial anomalies incl. TMJ -> orthotic
}


def _template_for(icd10: str) -> tuple[list[dict], str]:
    """Procedures for a diagnosis, plus the code the template was matched on."""
    if icd10 in _TREATMENT_MAP:
        return _TREATMENT_MAP[icd10], icd10
    for prefix in sorted(_FAMILY_FALLBACK, key=len, reverse=True):
        if icd10.startswith(prefix):
            mapped = _FAMILY_FALLBACK[prefix]
            return _TREATMENT_MAP.get(mapped, []), mapped
    return [], ""


def _tooth_for(patient_id: str, cdt: str) -> str:
    """Deterministic, demo-plausible universal tooth number (1-32).

    Fallback only. When the dentist's signed note named a tooth, that tooth is used
    instead — a plan that treats a different tooth from the one in the chart note is
    the first thing a dentist reading a demo will catch.
    """
    h = int(hashlib.sha256(f"{patient_id}{cdt}".encode()).hexdigest(), 16)
    return str((h % 32) + 1)


class TreatmentPlanBuilder(Agent):
    name = "treatment_plan_builder"
    automation = Automation.PARTIAL

    async def execute(self, ctx) -> AgentResult:
        transcript = ctx.get_result("clinical_note_transcriber")
        confirmed = (transcript.get("principal_icd10")
                     or ctx.get_result("diagnosis_signoff").get("confirmed_icd10", ""))
        patient_id = ctx.input_data.get("patient_id", "")
        # the tooth the dentist actually named in the signed note, when there was one
        charted_tooth = transcript.get("primary_tooth", "")
        template, matched_on = _template_for(confirmed)

        items = []
        for i, proc in enumerate(template):
            tooth = ""
            if proc["assign_tooth"]:
                tooth = charted_tooth or _tooth_for(patient_id, proc["cdt"])
            items.append({
                "item_id": f"TX{i + 1}",
                "tooth": tooth,
                "cdt": proc["cdt"],
                "description": proc["description"],
                "phase": proc["phase"],
                "fee_cents": proc["fee_cents"],
                "status": "proposed",
            })

        return AgentResult.completed({
            "diagnosis_icd10": confirmed,
            "items": items,
            "total_cents": sum(i["fee_cents"] for i in items),
            "has_recommended_treatment": bool(items),
            "tooth_from_chart_note": bool(charted_tooth),
            # surfaced so a reviewing dentist can see the plan came from an adjacent
            # code in the same ICD-10 family rather than an exact protocol match
            "matched_on_icd10": matched_on,
            "exact_protocol_match": matched_on == confirmed,
        })
