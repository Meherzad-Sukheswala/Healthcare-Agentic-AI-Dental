"""
src/integrations/seed_data.py

High-fidelity demo data for a general + specialty dental practice. Identifiers are
manufactured with correct checksums, codes are real (ICD-10-CM, RxNorm, CDT), and the
drug-interaction pairs are genuine clinically-significant interactions relevant to
dental prescribing. This is what makes the sandbox "look real" to a healthcare audience.
"""
from __future__ import annotations

from src.shared.base_types import CodedConcept
from src.shared.codegen import make_dea, make_npi
from src.shared.enums import Severity

from .models import Interaction, PatientRecord, Provider

# ---------------------------------------------------------------- providers
PROVIDERS: list[Provider] = [
    Provider(npi=make_npi("193456781"), first_name="Aisha", last_name="Rao",
             specialty="General Dentistry", facility="Meridian Dental Group", accepting_new_patients=True),
    Provider(npi=make_npi("142398760"), first_name="Daniel", last_name="Ortiz",
             specialty="General Dentistry", facility="Bay Family Dental", accepting_new_patients=True),
    Provider(npi=make_npi("155501234"), first_name="Priya", last_name="Nair",
             specialty="Orthodontics", facility="Downtown Orthodontics & Braces", accepting_new_patients=True),
    Provider(npi=make_npi("178812349"), first_name="Marcus", last_name="Bell",
             specialty="Oral & Maxillofacial Surgery", facility="Downtown Oral Surgery Associates",
             accepting_new_patients=False),
]

# A prescriber DEA number (valid checksum) for controlled-substance flows
PRESCRIBER_DEA = make_dea("AR", "918273")

# ---------------------------------------------------------------- drug interactions
# (drug_a rxcui, drug_b rxcui, severity, note) — real, well-known interactions relevant
# to dental prescribing (post-extraction analgesics, endodontic/periodontal antibiotics,
# epinephrine-containing local anesthetic, and procedural sedation).
INTERACTIONS: list[Interaction] = [
    Interaction(drug_a="11289", drug_b="5640", severity=Severity.SEVERE,
                description="Warfarin + Ibuprofen: increased post-extraction bleeding risk; "
                            "prefer acetaminophen for an anticoagulated patient"),
    Interaction(drug_a="11289", drug_b="6922", severity=Severity.SEVERE,
                description="Warfarin + Metronidazole: metronidazole inhibits warfarin metabolism, "
                            "raising INR / bleeding risk — common when treating an endodontic/"
                            "periodontal infection"),
    Interaction(drug_a="36567", drug_b="21212", severity=Severity.CONTRAINDICATED,
                description="Simvastatin + Clarithromycin: rhabdomyolysis risk (clarithromycin is a "
                            "common penicillin-allergy alternative for dental infections)"),
    Interaction(drug_a="3992", drug_b="8787", severity=Severity.MODERATE,
                description="Epinephrine (in local anesthetic) + Propranolol: unopposed alpha-adrenergic "
                            "effect in a non-selective-beta-blocked patient risks a hypertensive episode"),
    Interaction(drug_a="7804", drug_b="10689", severity=Severity.SEVERE,
                description="Oxycodone + Triazolam: combined CNS/respiratory depression risk "
                            "(post-op analgesic + oral sedation)"),
]

# ---------------------------------------------------------------- patients
PATIENTS: dict[str, PatientRecord] = {
    "PAT-001": PatientRecord(
        patient_id="PAT-001", first_name="Maria", last_name="Garcia", birth_date="1968-04-12",
        sex="female", member_id="BCB-90001", payer_id="PAYER-001", allergies=["penicillin"],
        medications=[CodedConcept(system="RxNorm", code="11289", display="warfarin")],
        conditions=[
            CodedConcept(system="ICD-10-CM", code="I48.91", display="Atrial fibrillation"),
            CodedConcept(system="ICD-10-CM", code="K02.9", display="Dental caries, unspecified"),
        ],
    ),
    "PAT-002": PatientRecord(
        patient_id="PAT-002", first_name="James", last_name="Wilson", birth_date="1955-09-30",
        sex="male", member_id="DD-70002", payer_id="PAYER-002", allergies=["latex"],
        medications=[CodedConcept(system="RxNorm", code="36567", display="simvastatin")],
        conditions=[
            CodedConcept(system="ICD-10-CM", code="E78.5", display="Hyperlipidemia"),
            CodedConcept(system="ICD-10-CM", code="K05.10", display="Chronic gingivitis, plaque induced"),
        ],
    ),
    "PAT-003": PatientRecord(
        patient_id="PAT-003", first_name="Sarah", last_name="Chen", birth_date="1982-01-22",
        sex="female", member_id="CIG-50003", payer_id="PAYER-003", allergies=[],
        medications=[CodedConcept(system="RxNorm", code="8787", display="propranolol")],
        conditions=[
            CodedConcept(system="ICD-10-CM", code="I10", display="Essential hypertension"),
            CodedConcept(system="ICD-10-CM", code="M26.60", display="Temporomandibular joint disorder, unspecified"),
        ],
    ),
}

# Traditional Medicare (Part A/B) excludes routine dental care; PAYER-MCR here models
# the medically-necessary path (e.g. oral-surgery claims tied to trauma/pathology, or a
# Medicare Advantage dental rider) rather than a routine cleaning being Medicare-billable.
PAYERS = {
    "PAYER-001": "BlueCross BlueShield Dental",
    "PAYER-002": "Delta Dental",
    "PAYER-003": "Cigna Dental",
    "PAYER-MCR": "Medicare",
    "PAYER-MCD": "Medicaid",
}

# payer_id -> payer_type used for coordination-of-benefits adjudication
PAYER_TYPE = {
    "PAYER-MCR": "medicare",
    "PAYER-MCD": "medicaid",
}


def payer_type_for(payer_id: str) -> str:
    return PAYER_TYPE.get(payer_id, "commercial")
