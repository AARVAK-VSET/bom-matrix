import pytest
"""Test suite for unit normalization, including European decimal comma support."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bomkit.unit_normalizer import UnitNormalizer


def _normalize(value):
    return UnitNormalizer().normalize_element(value)


def test_decimal_comma_resistance():
    """'4,7k' should parse to 4700.0 Ohms."""
    normalized_value, original_unit, normalized_unit = _normalize("4,7k")
    assert normalized_value == 4700.0
    assert original_unit == "k"
    assert normalized_unit == "ohm"


def test_decimal_comma_capacitance():
    """'2,2uF' should parse to 2.2e-6 Farads."""
    normalized_value, original_unit, _ = _normalize("2,2uF")
    assert normalized_value == pytest.approx(2.2e-6)
    assert original_unit == "uF"


def test_decimal_comma_plain_number():
    """A bare comma decimal should remain a valid float."""
    normalized_value, original_unit, normalized_unit = _normalize("4,7")
    assert normalized_value == 4.7
    assert original_unit is None
    assert normalized_unit is None


def test_decimal_comma_equivalence():
    """Comma and period decimals should normalize identically."""
    comma = _normalize("2,2uF")
    period = _normalize("2.2uF")
    assert comma[0] == period[0]
    assert comma[2] == period[2]


def test_decimal_comma_with_megaohm():
    """Comma decimal with a unit variant should work."""
    normalized_value, original_unit, _ = _normalize("1,5 MΩ")
    assert normalized_value == 1.5e6
    assert original_unit == "MΩ"


def test_decimal_comma_voltage():
    """Comma decimal voltage should normalize to Volts."""
    comma = _normalize("3,3V")
    period = _normalize("3.3V")
    assert comma[0] == 3.3
    assert comma[2] == period[2]


def test_existing_behavior_unchanged():
    """Period-based values should continue to normalize as before."""
    normalized_value, original_unit, _ = _normalize("10nF")
    assert normalized_value == 1e-8
    assert original_unit == "nF"


def test_decimal_comma_helper():
    """The comma replacement helper only rewrites unambiguous decimals."""
    normalizer = UnitNormalizer()
    assert normalizer._replace_decimal_comma("4,7k") == "4.7k"
    assert normalizer._replace_decimal_comma("2,2uF") == "2.2uF"
    assert normalizer._replace_decimal_comma("4,7") == "4.7"


def test_existing_period_helper_untouched():
    """A value with an existing period is not given a second separator."""
    normalizer = UnitNormalizer()
    assert normalizer._replace_decimal_comma("1,234.5") == "1,234.5"
    assert normalizer._replace_decimal_comma("1.234,5") == "1.234,5"


def test_existing_period_value_preserved():
    """Mixed-convention numbers keep their pre-existing behavior."""
    normalized_value, _, _ = _normalize("1,234.5")
    assert normalized_value == 1234.5


def test_decimal_comma_exponent():
    """Comma decimal with exponent notation should still parse."""
    normalized_value, _, _ = _normalize("1,5e3")
    assert normalized_value == 1500


def test_comma_list_helper_untouched():
    """Comma-separated lists are out of scope and must not be mangled."""
    normalizer = UnitNormalizer()
    assert normalizer._replace_decimal_comma("10, 20") == "10, 20"
    assert normalizer._replace_decimal_comma("1,2,3") == "1,2,3"


def test_malformed_helper_unchanged():
    """Malformed comma inputs are never rewritten by the helper."""
    normalizer = UnitNormalizer()
    for malformed in ["4,,7k", ",7k", "4,", "4,7.8k", "4,7,8k"]:
        assert normalizer._replace_decimal_comma(malformed) == malformed


def test_malformed_element_stable():
    """Malformed inputs still return a well-formed tuple without raising."""
    for malformed in ["4,,7k", ",7k", "4,", "4,7.8k", "4,7,8k", "abc", "k", "uF"]:
        result = _normalize(malformed)
        assert isinstance(result, tuple) and len(result) == 3


def test_thousands_vs_decimal_comma():
    """A single unspaced comma between digits is read as a decimal separator."""
    normalized_value, _, _ = _normalize("4,700")
    assert normalized_value == 4.7


def test_normalize_row_structure():
    """normalize_row keeps keys and converts comma decimals without touching comma lists."""
    normalizer = UnitNormalizer()
    row = {"designator": "R1", "value": "4,7k", "notes": "R1, R2", "qty": "10,5"}
    normalized = normalizer.normalize_row(row)
    assert list(normalized.keys()) == list(row.keys())
    assert normalized["value"] == 4700.0
    assert normalized["notes"] == "R1, R2"
    assert normalized["qty"] == 10.5


def test_normalize_data_structure():
    """normalize_data preserves list length and per-row conversion."""
    normalizer = UnitNormalizer()
    data = [{"value": "2,2uF"}, {"value": "4,7"}, {"value": "10nF"}]
    normalized = normalizer.normalize_data(data)
    assert len(normalized) == len(data)
    assert normalized[0]["value"] == pytest.approx(2.2e-6)
    assert normalized[1]["value"] == 4.7
    assert normalized[2]["value"] == 1e-8


def test_punctuational_comma_helper_untouched():
    """Commas not flanked by digits are not treated as decimals."""
    normalizer = UnitNormalizer()
    assert normalizer._replace_decimal_comma("R1, R2") == "R1, R2"
    assert normalizer._replace_decimal_comma(",5") == ",5"
    assert normalizer._replace_decimal_comma("5,") == "5,"