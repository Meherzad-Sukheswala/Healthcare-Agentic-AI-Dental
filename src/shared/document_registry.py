"""
src/shared/document_registry.py

What documentation this encounter ACTUALLY produced, and for anything it didn't, who
would have to produce it.

WHY THIS EXISTS
---------------
When a payer pends a claim and asks for documentation, the only question that matters is
whether the practice already holds what's being asked for. Most of the time it does — the
radiograph was taken, it just never got attached — and that case is fully automatable.
The expensive case is the artifact that does not exist yet, because producing it can mean
the patient has to come back in, or another office has to be chased.

So the split that decides whether a human gets involved is NOT "is it a document or a
code" — it is:

    does this artifact already exist?   -> the AI attaches it
    does it not exist?                  -> a named human must produce it, and we say
                                           whether the patient must return

This registry is built from what the pipeline genuinely produced (the signed note, the
generated narratives, the radiographs the imaging recorder logged), not from a hardcoded
list of things we assume are lying around. If it says a film exists, a film exists.

PWK01 REPORT TYPE CODES
-----------------------
`pwk` below is the X12 element 755 Report Type Code that goes in PWK01 of the 837 to
declare what an attachment contains. RB (Radiology Films), DA (Dental Models) and OZ
(Support Data for Claim) are verified against the X12 755 list. B4 (Referral Form) is
used for the referral case and should be confirmed against the individual payer's
companion guide before any live submission — payers vary in which subset they accept.
"""
from __future__ import annotations

# Who has to produce a document that doesn't exist yet.
BY_AI = "ai"                    # already in the record — assemble and attach
BY_DENTIST = "dentist"          # requires the dentist (imaging, a signature, a decision)
BY_HYGIENIST = "hygienist"      # requires a hygienist (periodontal charting)
BY_ADMIN = "admin"              # requires an admin to obtain it from OUTSIDE the practice

# doc key -> metadata
DOCUMENT_TYPES: dict[str, dict] = {
    "preop_radiograph": {
        "pwk": "RB", "label": "Preoperative periapical radiograph",
        "produced_by": BY_DENTIST, "needs_patient_visit": True,
        "source": "imaging system"},
    "postop_radiograph": {
        "pwk": "RB", "label": "Postoperative periapical radiograph",
        "produced_by": BY_DENTIST, "needs_patient_visit": True,
        "source": "imaging system"},
    "bitewings": {
        "pwk": "RB", "label": "Bitewing radiographs",
        "produced_by": BY_DENTIST, "needs_patient_visit": True,
        "source": "imaging system"},
    "full_mouth_series": {
        "pwk": "RB", "label": "Full-mouth radiographic series",
        "produced_by": BY_DENTIST, "needs_patient_visit": True,
        "source": "imaging system"},
    "cbct": {
        "pwk": "RB", "label": "CBCT volume",
        "produced_by": BY_DENTIST, "needs_patient_visit": True,
        "source": "imaging system"},
    "intraoral_photos": {
        "pwk": "RB", "label": "Intraoral photographs",
        "produced_by": BY_DENTIST, "needs_patient_visit": True,
        "source": "imaging system"},
    "perio_charting": {
        "pwk": "OZ", "label": "Full-mouth periodontal charting (6 sites per tooth)",
        "produced_by": BY_HYGIENIST, "needs_patient_visit": True,
        "source": "periodontal chart"},
    "chart_note": {
        "pwk": "OZ", "label": "Signed clinical note for the date of service",
        "produced_by": BY_DENTIST, "needs_patient_visit": False,
        "source": "EHR"},
    "narrative": {
        "pwk": "OZ", "label": "Procedure narrative",
        "produced_by": BY_AI, "needs_patient_visit": False,
        "source": "generated from the signed note"},
    "treatment_plan": {
        "pwk": "OZ", "label": "Itemized treatment plan",
        "produced_by": BY_AI, "needs_patient_visit": False,
        "source": "treatment plan"},
    # The two genuinely external ones. Neither needs the patient back in the chair, but
    # both mean waiting on somebody else's office, which is the slowest path there is.
    "specialist_referral": {
        "pwk": "B4", "label": "Referral form from the treating general dentist",
        "produced_by": BY_ADMIN, "needs_patient_visit": False,
        "source": "DHMO referral — external"},
    "medical_necessity_letter": {
        "pwk": "OZ", "label": "Physician letter of medical necessity",
        "produced_by": BY_ADMIN, "needs_patient_visit": False,
        "source": "referring physician — external"},
}


def describe(doc_key: str) -> dict:
    """Metadata for a document type, with a safe default for unknown keys."""
    return DOCUMENT_TYPES.get(doc_key, {
        "pwk": "OZ", "label": doc_key.replace("_", " ").capitalize(),
        "produced_by": BY_ADMIN, "needs_patient_visit": False, "source": "unknown"})


def build_registry(*, imaging: dict | None = None, clinical_note: str = "",
                   narratives: list[dict] | None = None,
                   treatment_plan_items: list[dict] | None = None,
                   perio_charted: bool = False) -> dict:
    """What this encounter holds, keyed by document type.

    Every entry records whether the artifact exists AND what it is, so an attachment
    carries a real reference rather than a promise. `detail` is what a biller would see
    in the attachment list.
    """
    imaging = imaging or {}
    narratives = narratives or []
    items = treatment_plan_items or []
    held: dict[str, dict] = {}

    # Radiographs and photographs — whatever the imaging recorder actually logged.
    for key, images in (imaging.get("images") or {}).items():
        if images:
            held[key] = {"available": True, "count": len(images),
                         "detail": ", ".join(str(i) for i in images)}

    if clinical_note.strip():
        held["chart_note"] = {"available": True, "count": 1,
                              "detail": f"signed note, {len(clinical_note.split())} words"}
    if narratives:
        held["narrative"] = {"available": True, "count": len(narratives),
                             "detail": f"{len(narratives)} procedure narrative(s)"}
    if items:
        held["treatment_plan"] = {"available": True, "count": len(items),
                                  "detail": f"{len(items)} planned line item(s)"}
    if perio_charted:
        held["perio_charting"] = {"available": True, "count": 1,
                                  "detail": "probing depths recorded this visit"}
    return held


def resolve(doc_key: str, registry: dict) -> dict:
    """Can this request be satisfied from the record, and if not, who must act?

    This is the routing decision, in one place, so the router agent and the gate can't
    disagree about it.
    """
    meta = describe(doc_key)
    entry = (registry or {}).get(doc_key) or {}
    if entry.get("available"):
        return {
            "doc_key": doc_key, "label": meta["label"], "pwk": meta["pwk"],
            "available": True, "resolved_by": BY_AI,
            "needs_patient_visit": False,
            "detail": entry.get("detail", ""), "source": meta["source"],
            "why": "Already in the record — the AI attaches it without anyone being asked.",
        }
    return {
        "doc_key": doc_key, "label": meta["label"], "pwk": meta["pwk"],
        "available": False, "resolved_by": meta["produced_by"],
        "needs_patient_visit": meta["needs_patient_visit"],
        "detail": "", "source": meta["source"],
        "why": ("Does not exist yet — the patient has to come back in for it."
                if meta["needs_patient_visit"] else
                "Does not exist yet and has to be obtained from outside the practice."),
    }
