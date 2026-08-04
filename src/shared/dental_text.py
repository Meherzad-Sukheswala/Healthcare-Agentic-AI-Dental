"""
src/shared/dental_text.py

Clinical text the pipeline reads and writes, plus the extractors that turn a
dentist's free-text note into structured data.

Three things live here:

1. DRAFT_NOTES — a realistic dentist's chart note per diagnosis, in the shorthand a
   practising dentist actually writes (universal tooth numbering, standard
   abbreviations, objective findings before diagnosis before plan). These are the
   demo's stand-in for ambient-scribe or dictation output: the dentist sees one
   pre-filled at the sign-off gate and edits it freely.

2. NARRATIVE_TEMPLATES — the claim narrative per CDT code. A dental payer's
   consultant cannot examine the patient, so the narrative is the only channel for
   what a radiograph can't show, and inadequate narratives are the leading cause of
   dental claim denials. Each template follows the structure payers actually want:
   tooth in universal notation -> objective measurable findings -> imaging reference
   -> prior treatment -> procedure tied to the findings -> why a cheaper alternative
   would not suffice (the LEAT argument).

3. Extractors — tooth numbers, ICD-10 codes, and objective findings out of prose.

Abbreviations used in the notes, for anyone reading this who isn't a dentist:
  MOD / DO / O   surfaces (mesial-occlusal-distal / distal-occlusal / occlusal)
  PA / BW        periapical radiograph / bitewing
  BOP            bleeding on probing
  WNL            within normal limits
  OHI            oral hygiene instruction
  FPD / RPD      fixed partial denture (bridge) / removable partial denture
  IAN            inferior alveolar nerve
  SRP            scaling and root planing
  2/2            secondary to
"""
from __future__ import annotations

import re

from .medical_codes import is_valid_cdt, is_valid_icd10

# --------------------------------------------------------------------------------
# 1. Draft chart notes — keyed by the diagnosis the AI suggested
# --------------------------------------------------------------------------------

DRAFT_NOTES: dict[str, str] = {
    # ---- the hygiene / recall visit: the most common appointment in the practice ----
    "Z01.20": """S: Pt presents for 6-month recall and prophylaxis. No pain, no complaints. Reports brushing 2x/day, flossing 2-3x/wk. Last visit 6 mo ago, no treatment since.

O: Extraoral - no swelling, no lymphadenopathy, TMJ WNL. Intraoral - soft tissues WNL, oral cancer screening negative. Generalized light supragingival calculus, heaviest mandibular anterior lingual. Localized marginal erythema interproximally. BOP 12% of sites. Probing depths 1-3mm generalized, no site greater than 3mm. No mobility, no recession.
BW x4: no interproximal caries. Existing restorations intact, margins sound. Bone levels WNL.

A: Sound dentition with localized plaque-induced gingival inflammation. Recall examination and prophylaxis, no abnormal findings. Z01.20

P: Adult prophylaxis today. Periodic oral evaluation documented. OHI - interproximal cleaning technique reinforced. Fluoride varnish declined by pt. Next recall 6 months.""",

    # ---- periapical abscess: the flagship case (RCT + crown) ----
    "K04.7": """S: Pt reports 6-day h/o spontaneous throbbing pain LR quadrant, worse at night. Woke her the last two nights; OTC ibuprofen no longer controlling it. Now with mild facial swelling.

O: Tooth #30 - large MOD amalgam, distal marginal breakdown w/ recurrent caries. NON-RESPONSIVE to cold. Exquisite tenderness to percussion. Palpation tender at buccal vestibule w/ localized fluctuant swelling ~4mm. No trismus, no lymphadenopathy, afebrile. Probing depths WNL 2-3mm, no mobility.
PA #30: 3mm periapical radiolucency at distal root apex. Caries extending into pulp chamber. Existing restoration >50% of clinical crown.

A: Necrotic pulp #30 with acute apical abscess, 2/2 recurrent caries under failing MOD amalgam. K04.7

P: RCT #30 today to relieve. Core buildup + full-coverage crown once symptoms resolve - remaining tooth structure insufficient for a direct restoration. Amoxicillin 500mg TID x7d. Ibuprofen 600mg q6h prn. Post-op instructions given.""",

    # ---- gingivitis / early periodontitis (SRP) ----
    "K05.10": """S: Pt reports gums bleeding on brushing x3 months. No pain. Last prophy >2 yrs ago per hx. Smoker, ~half pack/day.

O: Generalized marginal erythema and edema, heaviest posterior. BOP 34% of sites. Probing depths 4-5mm localized to UR and LR posterior sextants; remainder 2-3mm. No mobility, no furcation involvement. Moderate supragingival calculus w/ subgingival extension interproximally posterior.
Radiographs: early horizontal crestal bone loss posterior sextants, <15%. No periapical pathology.

A: Generalized plaque-induced gingivitis w/ localized early periodontitis, Stage I Grade B. K05.10

P: SRP UR and LR quadrants. Re-evaluate 4-6 wks. OHI reinforced, smoking cessation discussed. Perio maintenance interval to be set at re-eval.""",

    # ---- caries / reversible pulpitis (composite) ----
    "K02.9": """S: Pt c/o cold sensitivity UL x3 wks. Sharp, resolves on removal of stimulus. No spontaneous pain, no night pain.

O: Tooth #14 - occlusal caries into dentin. Responds BRISKLY to cold, resolves <5s. Non-tender to percussion and palpation. Probing depths WNL. Adjacent teeth asymptomatic.
BW #14: occlusal radiolucency extending approx 1/2 into dentin. No pulpal involvement. Lamina dura intact.

A: Reversible pulpitis 2/2 moderate occlusal caries #14. K02.9

P: Composite restoration #14 O. No endodontic therapy indicated - pulp vital, symptoms consistent w/ reversible pulpitis. Fluoride varnish. Caries risk counseling, dietary review.""",

    # ---- TMJ disorder (occlusal orthotic) ----
    "M26.60": """S: Pt reports 2 mo h/o L preauricular pain and clicking on opening, worse mornings. Reports clenching under work stress. No locking, no h/o trauma to the jaw.

O: Max opening 42mm without deviation. Reciprocal click L TMJ on opening ~28mm and on closing. Tenderness to palpation L masseter and L temporalis. L TMJ tender to lateral palpation. No crepitus. Wear facets on posterior occlusal surfaces bilaterally; attrition of mandibular anterior incisal edges. Dentition otherwise sound - no caries, no periapical pathology on radiographs.

A: L TMJ internal derangement with reduction. Myofascial pain of masticatory muscles. Parafunctional clenching/bruxism. M26.60

P: Maxillary occlusal orthotic device (night guard). Soft diet, moist heat, NSAID prn. Re-evaluate 4 wks. Refer to OMFS if no improvement or if locking develops.""",

    # ---- partial edentulism -> graft + implant (the high-cost / predetermination case) ----
    "K08.409": """S: Pt presents for implant consultation. Tooth #19 extracted approx 8 mo ago elsewhere. Reports difficulty chewing on L side. Declines removable partial.

O: Site #19 edentulous, ridge healed, adequate keratinized tissue, non-tender. Mesiodistal space 10.5mm. Adjacent teeth #18 and #20 sound and UNRESTORED - a conventional FPD would require preparation of two virgin abutments. Ridge narrow buccolingually on palpation.
CBCT: residual ridge height 13.2mm above IAN canal. Buccal plate deficiency, ridge width 4.8mm at crest - insufficient for a standard-diameter fixture without augmentation. No pathology at site.

A: Partial edentulism #19 with localized alveolar ridge deficiency. K08.409

P: Ridge augmentation / bone replacement graft #19, 4-6 mo healing, then endosseous implant placement #19, restore w/ abutment-supported ceramic crown. Predetermination to be submitted w/ CBCT prior to surgical phase given fee. Alternatives (FPD, RPD, no treatment) presented and discussed; pt elects implant.""",

    # ---- catch-all: nothing definitive found ----
    "K08.9": """S: Pt presents for evaluation. Complaint not localized to a specific tooth on exam today.

O: Extraoral - no swelling, no lymphadenopathy, TMJ WNL. Intraoral - soft tissues WNL, no lesions on oral cancer screening. Dentition - existing restorations intact, no gross caries detected. Probing depths 2-3mm generalized, minimal BOP.
Radiographs: no periapical pathology, no interproximal caries, bone levels WNL.

A: No definitive pathology identified this visit. Symptoms not reproducible on examination. K08.9

P: Comprehensive evaluation documented. Monitor. Pt to return if symptoms localize or worsen. Routine recall interval.""",
}

DEFAULT_DRAFT_NOTE = DRAFT_NOTES["K08.9"]


# --------------------------------------------------------------------------------
# 2. Claim narratives — keyed by CDT
# --------------------------------------------------------------------------------
# `{tooth}` is substituted with the universal tooth number. Each narrative names the
# objective findings, references the attached imaging, and closes the LEAT argument
# (why a cheaper alternative was not adequate) because that is the specific thing a
# payer's dental consultant is looking for.

NARRATIVE_TEMPLATES: dict[str, str] = {
    "D3330": ("Tooth {tooth}: patient presented with spontaneous throbbing pain of several days' "
              "duration and localized facial swelling. Tooth was non-responsive to cold testing "
              "with exquisite tenderness to percussion; buccal vestibule tender to palpation with "
              "localized fluctuant swelling. Preoperative periapical radiograph demonstrates a 3mm "
              "periapical radiolucency at the distal root apex with caries extending into the pulp "
              "chamber. Diagnosis: necrotic pulp with acute apical abscess. Endodontic therapy "
              "performed to resolve active infection and retain the tooth; extraction was the only "
              "alternative. Pre- and post-operative radiographs attached."),
    "D3310": ("Tooth {tooth}: non-responsive to cold with tenderness to percussion and periapical "
              "radiolucency on the preoperative radiograph, consistent with pulpal necrosis. "
              "Endodontic therapy performed to retain the tooth. Radiographs attached."),
    "D2950": ("Tooth {tooth}: following endodontic access and complete caries excavation, remaining "
              "coronal tooth structure is less than half the clinical crown with loss of both "
              "marginal ridges. A core buildup is required to establish adequate retention and "
              "resistance form for the definitive crown; without it the restoration would lack "
              "structural support. Radiograph attached."),
    "D2740": ("Tooth {tooth}: existing large MOD amalgam with distal marginal breakdown and "
              "recurrent caries. Remaining coronal tooth structure comprises less than half the "
              "clinical crown following endodontic access and caries excavation. A direct "
              "restoration would not provide adequate structural support or a predictable marginal "
              "seal on an endodontically treated molar and would place the tooth at risk of "
              "cuspal fracture. Full-coverage porcelain/ceramic crown indicated. Pre- and "
              "post-operative radiographs attached."),
    "D4341": ("Quadrant scaling and root planing. Probing depths of 4-5mm with bleeding on probing "
              "at 34% of sites and moderate supragingival calculus with subgingival extension "
              "interproximally. Radiographs demonstrate early horizontal crestal bone loss in the "
              "posterior sextants. Diagnosis: generalized plaque-induced gingivitis with localized "
              "early periodontitis, Stage I Grade B. Definitive periodontal therapy indicated; a "
              "prophylaxis would not address subgingival calculus or the active disease process. "
              "Full-mouth periodontal charting and radiographs attached."),
    "D4342": ("Quadrant scaling and root planing, 1-3 teeth. Probing depths of 4-5mm with bleeding "
              "on probing and subgingival calculus localized to the treated teeth. Periodontal "
              "charting and radiographs attached."),
    "D2391": ("Tooth {tooth}: occlusal caries extending approximately halfway into dentin on the "
              "preoperative bitewing, with brisk cold response resolving in under five seconds and "
              "no tenderness to percussion, consistent with reversible pulpitis and a vital pulp. "
              "One-surface posterior resin composite restoration placed. Radiograph attached."),
    "D2392": ("Tooth {tooth}: caries extending into dentin across two surfaces on the preoperative "
              "bitewing, pulp vital with no periapical pathology. Two-surface posterior resin "
              "composite restoration placed. Radiograph attached."),
    "D7880": ("Maxillary occlusal orthotic device. Patient presents with a reciprocal click of the "
              "left TMJ on opening at approximately 28mm and on closing, tenderness to palpation "
              "of the left masseter and temporalis, and wear facets on the posterior occlusal "
              "surfaces bilaterally with attrition of the mandibular anterior incisal edges. "
              "Diagnosis: TMJ internal derangement with reduction, myofascial pain of the "
              "masticatory muscles, and parafunctional clenching. An orthotic device is indicated "
              "to protect the dentition from further attrition and to reduce muscular symptoms."),
    "D7953": ("Site {tooth}: bone replacement graft for ridge preservation/augmentation. CBCT "
              "demonstrates buccal plate deficiency with a crestal ridge width of 4.8mm, "
              "insufficient to accommodate a standard-diameter implant fixture without "
              "augmentation. Residual ridge height 13.2mm above the inferior alveolar canal. "
              "Grafting is a prerequisite to implant placement at this site. CBCT attached."),
    "D6010": ("Site {tooth}: surgical placement of endosseous implant body following ridge "
              "augmentation. Mesiodistal space 10.5mm; adjacent teeth are sound and entirely "
              "unrestored, so a conventional fixed partial denture would require preparation of "
              "two virgin abutments. Removable partial denture and no-treatment alternatives were "
              "presented and declined by the patient. Post-graft CBCT confirms adequate ridge "
              "dimension. CBCT and clinical photographs attached."),
    "D6058": ("Site {tooth}: abutment-supported porcelain/ceramic crown restoring an integrated "
              "endosseous implant. Radiographic confirmation of osseointegration attached."),
    "D0140": ("Limited oral evaluation, problem focused. Patient presented with an acute complaint; "
              "examination and diagnostic radiographs obtained to establish a diagnosis."),
    "D0150": ("Comprehensive oral evaluation. Full examination including extraoral and intraoral "
              "soft-tissue assessment, oral cancer screening, full periodontal charting and a "
              "complete radiographic series."),
}

GENERIC_NARRATIVE = ("Tooth {tooth}: procedure performed per the clinical findings documented in "
                     "the chart note for this date of service. Supporting radiographs attached.")


def narrative_for(cdt: str, tooth: str = "") -> str:
    """The claim narrative for one procedure line.

    Tooth numbers render as "#30" — the universal-notation convention a dentist writes
    and a claim carries. Quadrant-level and appliance codes ignore the tooth entirely.
    """
    template = NARRATIVE_TEMPLATES.get(cdt.upper(), GENERIC_NARRATIVE)
    return template.format(tooth=f"#{tooth}" if tooth else "N/A")


# --------------------------------------------------------------------------------
# 3. Extractors — prose -> structured
# --------------------------------------------------------------------------------

# Universal numbering: permanent teeth 1-32, primary teeth A-T.
_TOOTH_HASH = re.compile(r"#\s*([1-9]|[12]\d|3[0-2]|[A-T])\b")
_TOOTH_WORD = re.compile(r"\btooth\s+#?\s*([1-9]|[12]\d|3[0-2]|[A-T])\b", re.IGNORECASE)
# Require a decimal point: it keeps CDT codes (D3330, D6010) from matching as ICD-10.
_ICD10_IN_PROSE = re.compile(r"\b([A-TV-Z][0-9][0-9A-Z]\.[0-9A-Z]{1,4})\b")

# Objective findings worth pulling out for the narrative. Order matters: first match wins.
_FINDING_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("periapical_radiolucency", re.compile(r"(\d+(?:\.\d+)?)\s*mm\s+periapical\s+radiolucency", re.I)),
    ("probing_depths", re.compile(r"probing\s+depths?\s+([0-9]{1,2}\s*-\s*[0-9]{1,2}\s*mm|WNL[^.\n]*)", re.I)),
    ("bop_pct", re.compile(r"BOP\s+(\d{1,3})\s*%", re.I)),
    ("max_opening", re.compile(r"max(?:imum)?\s+opening\s+(\d{1,2})\s*mm", re.I)),
    ("ridge_width", re.compile(r"ridge\s+width\s+(\d+(?:\.\d+)?)\s*mm", re.I)),
    ("mesiodistal_space", re.compile(r"mesiodistal\s+space\s+(\d+(?:\.\d+)?)\s*mm", re.I)),
]

# Clinical signs a payer's consultant looks for. Presence/absence, not a value.
_SIGN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "non_responsive_to_cold": ("non-responsive to cold", "nonresponsive to cold", "no response to cold"),
    "percussion_tender": ("tenderness to percussion", "tender to percussion"),
    "swelling": ("fluctuant swelling", "facial swelling"),
    "recurrent_caries": ("recurrent caries",),
    "caries_into_pulp": ("into pulp chamber", "extending into the pulp"),
    "subgingival_calculus": ("subgingival extension", "subgingival calculus"),
    "bone_loss": ("crestal bone loss", "horizontal bone loss", "bone loss"),
    "reciprocal_click": ("reciprocal click",),
    "wear_facets": ("wear facets", "attrition"),
    "buccal_plate_deficiency": ("buccal plate deficiency",),
    "unrestored_abutments": ("virgin abutments", "unrestored"),
}


def extract_teeth(text: str) -> list[str]:
    """Tooth numbers referenced in the note, in order of first appearance."""
    if not text:
        return []
    found: list[str] = []
    for match in _TOOTH_HASH.finditer(text):
        tooth = match.group(1).upper()
        if tooth not in found:
            found.append(tooth)
    for match in _TOOTH_WORD.finditer(text):
        tooth = match.group(1).upper()
        if tooth not in found:
            found.append(tooth)
    return found


def extract_icd10(text: str) -> str:
    """The first ICD-10-CM code written anywhere in the note.

    A dentist amending a diagnosis will usually write the code inline ("...consistent
    with K04.7...") rather than in a separate field, so the whole note is searched.
    Codes must carry a decimal, which is what keeps CDT procedure codes out.
    """
    if not text:
        return ""
    for match in _ICD10_IN_PROSE.finditer(text):
        code = match.group(1).upper()
        if is_valid_icd10(code) and not is_valid_cdt(code):
            return code
    return ""


def extract_findings(text: str) -> dict:
    """Measurable findings and clinical signs, for the claim narrative."""
    if not text:
        return {"measurements": {}, "signs": []}
    measurements: dict[str, str] = {}
    for label, pattern in _FINDING_PATTERNS:
        match = pattern.search(text)
        if match:
            measurements[label] = match.group(1).strip()
    lowered = text.lower()
    signs = [name for name, keys in _SIGN_KEYWORDS.items() if any(k in lowered for k in keys)]
    return {"measurements": measurements, "signs": signs}


def split_soap(text: str) -> dict:
    """Split a note into S/O/A/P sections when the dentist used that format.

    Falls back to putting everything in `assessment` so downstream agents always have
    something to read.
    """
    if not text:
        return {"subjective": "", "objective": "", "assessment": "", "plan": ""}
    sections = {"subjective": "", "objective": "", "assessment": "", "plan": ""}
    key_for = {"S": "subjective", "O": "objective", "A": "assessment", "P": "plan"}
    current: str | None = None
    for raw in text.splitlines():
        header = re.match(r"^\s*([SOAP])\s*:\s*(.*)$", raw)
        if header:
            current = key_for[header.group(1)]
            sections[current] = header.group(2).strip()
            continue
        if current and raw.strip():
            sections[current] = (sections[current] + " " + raw.strip()).strip()
    if not any(sections.values()):
        sections["assessment"] = text.strip()
    return sections
