"""
src/shared/medical_codes.py

Validators for the real coding systems used across the pipeline. These implement
the actual format + checksum rules so the demo data is genuinely well-formed:

  NPI     - 10 digits, Luhn checksum over the 80840 prefix (CMS/NPPES rule)
  DEA     - 2 letters + 7 digits, DEA registrant checksum
  ICD-10  - ICD-10-CM format (e.g. E11.9, I10, S82.101A)
  CPT     - Category I 5-digit code
  CDT     - Current Dental Terminology (ADA): 'D' + 4 digits (e.g. D0150, D7140)
  HCPCS   - Level II: 1 letter + 4 digits (e.g. J1885)
  NDC     - National Drug Code, hyphenated 5-4-2 / 5-3-2 / 4-4-2 / 5-4-1 or 10-11 digits
  LOINC   - format n...n-c (numeric with a check digit)
  RxNorm  - numeric RXCUI

Each `is_valid_*` returns a bool; `validate_*` raises ValueError with a reason.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- NPI
def is_valid_npi(npi: str) -> bool:
    """10-digit NPI validated with the Luhn algorithm over prefix '80840'.

    Per the CMS check-digit rule the payload is '80840' + the first 9 NPI digits;
    alternate digits are doubled beginning with the RIGHTMOST payload digit.
    """
    if not isinstance(npi, str) or not re.fullmatch(r"\d{10}", npi):
        return False
    payload = "80840" + npi[:9]
    total = 0
    # double the rightmost payload digit and every second one moving left
    for pos, ch in enumerate(reversed(payload)):
        d = int(ch)
        if pos % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    check = (10 - total % 10) % 10
    return check == int(npi[9])


# --------------------------------------------------------------------------- DEA
def is_valid_dea(dea: str) -> bool:
    """DEA number: 2 letters + 7 digits, with the standard registrant checksum."""
    if not isinstance(dea, str) or not re.fullmatch(r"[A-Za-z]{2}\d{7}", dea):
        return False
    n = [int(c) for c in dea[2:]]
    check = (n[0] + n[2] + n[4] + 2 * (n[1] + n[3] + n[5])) % 10
    return check == n[6]


# ------------------------------------------------------------------------- ICD-10
_ICD10 = re.compile(r"^[A-TV-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$")

def is_valid_icd10(code: str) -> bool:
    return isinstance(code, str) and bool(_ICD10.match(code.upper()))


# ---------------------------------------------------------------------------- CPT
def is_valid_cpt(code: str) -> bool:
    return isinstance(code, str) and bool(re.fullmatch(r"\d{5}", code))


# ---------------------------------------------------------------------------- CDT
def is_valid_cdt(code: str) -> bool:
    """CDT (Current Dental Terminology, ADA-owned) procedure code: 'D' + 4 digits."""
    return isinstance(code, str) and bool(re.fullmatch(r"D\d{4}", code.upper()))


# -------------------------------------------------------------------------- HCPCS
def is_valid_hcpcs(code: str) -> bool:
    return isinstance(code, str) and bool(re.fullmatch(r"[A-CEGHJ-MP-V]\d{4}", code.upper()))


# ---------------------------------------------------------------------------- NDC
_NDC = re.compile(r"^\d{4,5}-\d{3,4}-\d{1,2}$")

def is_valid_ndc(code: str) -> bool:
    """Accepts hyphenated 5-4-2 / 5-3-2 / 4-4-2 / 5-4-1, or plain 10-11 digits."""
    if not isinstance(code, str):
        return False
    return bool(_NDC.match(code)) or bool(re.fullmatch(r"\d{10,11}", code))


# -------------------------------------------------------------------------- LOINC
def is_valid_loinc(code: str) -> bool:
    """LOINC format: 1-7 digits, a dash, then a single check digit."""
    return isinstance(code, str) and bool(re.fullmatch(r"\d{1,7}-\d", code))


# ------------------------------------------------------------------------- RxNorm
def is_valid_rxcui(code: str) -> bool:
    return isinstance(code, str) and code.isdigit() and 1 <= len(code) <= 8


# ----------------------------------------------------------------- raise-on-error
def _mk(validator, label):
    def _v(code: str) -> str:
        if not validator(code):
            raise ValueError(f"Invalid {label}: {code!r}")
        return code
    return _v


validate_npi = _mk(is_valid_npi, "NPI")
validate_dea = _mk(is_valid_dea, "DEA number")
validate_icd10 = _mk(is_valid_icd10, "ICD-10-CM code")
validate_cpt = _mk(is_valid_cpt, "CPT code")
validate_cdt = _mk(is_valid_cdt, "CDT code")
validate_hcpcs = _mk(is_valid_hcpcs, "HCPCS code")
validate_ndc = _mk(is_valid_ndc, "NDC")
validate_loinc = _mk(is_valid_loinc, "LOINC code")
validate_rxcui = _mk(is_valid_rxcui, "RxNorm RXCUI")
