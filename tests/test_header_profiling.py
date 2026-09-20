"""Tests for adaptive column header detection via lexical + value profiling."""

import sys
from pathlib import Path

# Add parent directory to path to import bomkit
sys.path.insert(0, str(Path(__file__).parent.parent))

from bomkit import BomNormalizer


MPN_VALUES = [
    "STM32F401RCT6",
    "STM32F103C8T6",
    "ATmega328P",
    "ESP32-WROOM-32",
    "RC0603FR-0710KL",
    "LM358",
    "1N4148",
    "2N3904",
    "MAX232",
    "74LS138",
]


def test_content_fallback_detection():
    """A column with an empty header but MPN-like cell values must be
    classified from its content value profile with confidence >= 0.85."""
    rows = [{"": value} for value in MPN_VALUES]

    normalizer = BomNormalizer()
    classification = normalizer.classify_column("", [row[""] for row in rows])

    assert classification["role"] == "mpn"
    assert classification["role_id"] == "manufacturer_part_number"
    assert classification["confidence"] >= 0.85
    assert classification["name_score"] < 0.35
    assert classification["content_score"] >= 0.85


def test_classify_columns_on_table_with_empty_header():
    """Every column of a 10-row table with an empty header is classified
    from its contents."""
    rows = [{"": value} for value in MPN_VALUES]

    normalizer = BomNormalizer()
    classifications = normalizer.classify_columns(rows)

    assert "" in classifications
    result = classifications[""]
    assert result["role"] == "mpn"
    assert result["confidence"] >= 0.85


def test_content_fallback_detection_with_obfuscated_header():
    """A cryptic header that has no lexical signal falls back to content
    value profiling (e.g. 'Column7' holding MPNs)."""
    rows = [{"Column7": value} for value in MPN_VALUES]

    normalizer = BomNormalizer()
    classification = normalizer.classify_column("Column7", [row["Column7"] for row in rows])

    assert classification["role"] == "mpn"
    assert classification["confidence"] >= 0.85


def test_empty_column_is_not_classified():
    """A column with no usable cell values must not be classified."""
    normalizer = BomNormalizer()

    assert normalizer.classify_column("", [])["role"] is None
    assert normalizer.classify_column("", [])["confidence"] == 0.0

    assert normalizer.classify_column("", [None, "", None])["role"] is None
    assert normalizer.classify_column("", [None, "", None])["confidence"] == 0.0


def test_whitespace_only_header_uses_content_fallback():
    """A whitespace-only header is uninformative and falls back to content."""
    normalizer = BomNormalizer()
    classification = normalizer.classify_column("   ", MPN_VALUES)

    assert classification["role"] == "mpn"
    assert classification["confidence"] >= 0.85
    assert classification["name_score"] < 0.35


def test_numeric_column_classified_as_quantity():
    """A column of positive integers with an empty header maps to quantity."""
    normalizer = BomNormalizer()
    classification = normalizer.classify_column(
        "", ["10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]
    )

    assert classification["role"] == "quantity"
    assert classification["confidence"] >= 0.85


def test_reference_designator_column_not_confused_with_mpn():
    """Short ref-des values (C1, R5, ...) must not be read as MPNs."""
    normalizer = BomNormalizer()
    classification = normalizer.classify_column(
        "", ["C1", "C2", "C3", "R5", "R6", "R7", "U1", "D2", "L1", "Q1"]
    )

    assert classification["role"] == "reference_designator"
    assert classification["confidence"] >= 0.85


def test_supplier_values_not_classified_as_mpn():
    """Supplier-like names (no mpn pattern) must not classify as mpn."""
    normalizer = BomNormalizer()
    classification = normalizer.classify_column(
        "",
        [
            "Digi-Key",
            "Mouser",
            "Arrow Electronics",
            "Avnet",
            "Farnell",
            "RS Components",
            "Newark",
            "TME",
            "Conrad",
            "Anglia Components",
        ],
    )

    assert classification["role"] != "mpn"


def test_description_header_not_confused_with_manufacturer():
    """A column named 'Description' with short-phrase text must classify as
    description, not as manufacturer."""
    normalizer = BomNormalizer()
    classification = normalizer.classify_column(
        "Description",
        [
            "Unpolarized capacitor",
            "Light emitting diode",
            "Voltage regulator",
            "Crystal oscillator",
            "Connector header",
            "Diode switching",
            "Transistor NPN",
            "Optocoupler DIP4",
            "Ceramic capacitor",
            "Resistor network",
        ],
    )

    assert classification["role"] == "description"
    assert classification["confidence"] >= 0.85


def test_date_column_not_classified_as_mpn():
    """ISO date strings must never be read as MPNs or descriptions."""
    normalizer = BomNormalizer()
    classification = normalizer.classify_column(
        "",
        ["2024-01-01", "2023-12-31", "2022-06-15", "2021-03-08", "2020-11-30"],
    )

    assert classification["role"] != "mpn"


def test_phone_numbers_not_classified_as_mpn():
    """Dashed phone numbers must never be read as MPNs."""
    normalizer = BomNormalizer()
    classification = normalizer.classify_column(
        "",
        ["555-123-4567", "555-234-5678", "555-345-6789", "555-456-7890", "555-567-8901"],
    )

    assert classification["role"] != "mpn"


def test_hex_codes_not_classified_as_mpn():
    """Pure hex codes (e.g. colors) must never be read as MPNs."""
    normalizer = BomNormalizer()
    classification = normalizer.classify_column(
        "",
        ["FF0000", "00FF00", "0000FF", "FFFF00", "00FFFF", "FF00FF", "000000", "FFFFFF", "123ABC", "ABCDEF"],
    )

    assert classification["role"] != "mpn"


def test_footprints_not_classified_as_mpn():
    """Package footprints (0805, SOIC-8, ...) must never be read as MPNs."""
    normalizer = BomNormalizer()
    classification = normalizer.classify_column(
        "",
        ["0805", "0603", "SOIC-8", "DIP-14", "SOT-23", "QFN-32", "TO-92", "0402", "1206", "BGA-100"],
    )

    assert classification["role"] != "mpn"


def test_vendor_names_classified_from_content():
    """Multi-word manufacturer names are recognised from content alone."""
    normalizer = BomNormalizer()
    classification = normalizer.classify_column(
        "",
        [
            "Texas Instruments",
            "Analog Devices",
            "STMicroelectronics",
            "Microchip Technology",
            "ON Semiconductor",
            "Renesas Electronics",
            "Infineon Technologies",
            "NXP Semiconductors",
            "Vishay Intertechnology",
            "ROHM Semiconductor",
        ],
    )

    assert classification["role"] == "manufacturer"
    assert classification["confidence"] >= 0.85


def test_classify_column_none_values_is_safe():
    """Values=None must return an inert empty classification, not crash."""
    normalizer = BomNormalizer()
    classification = normalizer.classify_column("", None)

    assert classification["role"] is None
    assert classification["confidence"] == 0.0


def test_composite_confidence_is_monotonic():
    """The composite must never drop when either signal improves."""
    normalizer = BomNormalizer()
    grid = [i / 20 for i in range(21)]

    for name in grid:
        for low, high in zip(grid[:-1], grid[1:]):
            assert normalizer._composite_confidence(name, low) <= normalizer._composite_confidence(name, high) + 1e-9
    for content in grid:
        for low, high in zip(grid[:-1], grid[1:]):
            assert normalizer._composite_confidence(low, content) <= normalizer._composite_confidence(high, content) + 1e-9