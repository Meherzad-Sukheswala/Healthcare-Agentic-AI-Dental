"""Validators must accept real, well-formed codes and reject malformed ones."""
import pytest

from src.shared import medical_codes as mc


def test_npi_luhn():
    assert mc.is_valid_npi("1234567893")      # canonical valid NPI (check digit 3)
    assert not mc.is_valid_npi("1234567890")  # bad check digit
    assert not mc.is_valid_npi("12345")       # wrong length


def test_dea_checksum():
    assert mc.is_valid_dea("AB1234563")       # checksum: (1+3+5)+2*(2+4+6)=33 -> 3
    assert not mc.is_valid_dea("AB1234567")   # wrong check digit
    assert not mc.is_valid_dea("1234563AB")   # wrong format


def test_icd10():
    for good in ("E11.9", "I10", "S82.101A", "Z00.00"):
        assert mc.is_valid_icd10(good), good
    for bad in ("123", "e", "11.9"):
        assert not mc.is_valid_icd10(bad), bad


def test_cpt_hcpcs():
    assert mc.is_valid_cpt("99213")
    assert not mc.is_valid_cpt("9921")
    assert mc.is_valid_hcpcs("J1885")
    assert not mc.is_valid_hcpcs("1885")


def test_ndc_loinc_rxcui():
    assert mc.is_valid_ndc("0069-2587-10")
    assert mc.is_valid_ndc("00693587123")     # 11 plain digits
    assert not mc.is_valid_ndc("12-34")
    assert mc.is_valid_loinc("2160-0")
    assert not mc.is_valid_loinc("2160")
    assert mc.is_valid_rxcui("1049502")
    assert not mc.is_valid_rxcui("abc")


def test_validate_raises():
    with pytest.raises(ValueError):
        mc.validate_npi("0000000000")
    assert mc.validate_cpt("99213") == "99213"
