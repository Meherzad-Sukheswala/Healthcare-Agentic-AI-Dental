"""
src/shared/codegen.py

Helpers that MANUFACTURE valid identifiers (correct checksums) so seed / demo
data is guaranteed well-formed. Built on the same rules as medical_codes.py.
"""
from __future__ import annotations

from .medical_codes import is_valid_dea, is_valid_npi


def npi_check_digit(base9: str) -> int:
    """Return the Luhn check digit for a 9-digit NPI base (prefix 80840)."""
    if not (base9.isdigit() and len(base9) == 9):
        raise ValueError("base9 must be exactly 9 digits")
    payload = "80840" + base9
    total = 0
    for pos, ch in enumerate(reversed(payload)):
        d = int(ch)
        if pos % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10


def make_npi(base9: str) -> str:
    """Full 10-digit valid NPI from a 9-digit base."""
    npi = base9 + str(npi_check_digit(base9))
    assert is_valid_npi(npi), npi
    return npi


def dea_check_digit(letters2: str, base6: str) -> int:
    """DEA check digit for 2 letters + 6 digits."""
    if len(base6) != 6 or not base6.isdigit():
        raise ValueError("base6 must be exactly 6 digits")
    n = [int(c) for c in base6]
    return (n[0] + n[2] + n[4] + 2 * (n[1] + n[3] + n[5])) % 10


def make_dea(letters2: str, base6: str) -> str:
    """Full DEA number (2 letters + 7 digits) with a valid checksum."""
    dea = letters2.upper() + base6 + str(dea_check_digit(letters2, base6))
    assert is_valid_dea(dea), dea
    return dea
