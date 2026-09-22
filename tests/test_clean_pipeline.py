"""Test suite for the Issue #24 comprehensive component cleaning pipeline.

Covers the four cleaning stages (vendor packaging-code strip, tolerance
extraction, package detection, value-unit canonicalization / SI conversion),
the additive-only line-item contract, the wiring into ``BomNormalizer``
(default-on) and ``snapshot_ingest``, and the standard noisy-dataset accuracy
acceptance test (≥ 90% per issue #24).
"""

import json
import sys
from pathlib import Path

# Add parent directory to path to import bomkit
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from bomkit import BomNormalizer
from bomkit.adapters.csv_adapter import CsvAdapter
from bomkit.clean import (
    CleaningPipeline,
    canonical_value,
    clean_row,
    detect_package,
    extract_tolerance,
    mpn_key,
    strip_vendor_packaging,
    value_to_si,
)
from bomkit.ingest.snapshot_ingest import normalize_row_from_dict

DATA_DIR = Path(__file__).parent / "data"
DATASET = DATA_DIR / "noisy_bom.csv"
EXPECTED = DATA_DIR / "noisy_bom_expected.json"


def _raw_row(**overrides):
    row = {
        "part_number": "C7",
        "description": "Capacitor",
        "quantity": "4",
        "unit": "pcs",
        "manufacturer": "Nichicon",
        "supplier": "Mouser",
        "manufacturer_part_number": "UVZ1E100MDD1TB",
        "reference_designator": "C8",
        "value": "10µF ±20%",
        "package": "",
        "notes": "",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Stage 1: vendor packaging-code stripping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected_mpn,expected_packaging", [
    ("RC0603FR-0710KL-TR", "RC0603FR-0710KL", "tape_and_reel"),
    ("RC0805FR-07200KL-TR1", "RC0805FR-07200KL", "tape_and_reel"),
    ("CR0603-FX-1002ELF-TR7", "CR0603-FX-1002ELF", "tape_and_reel"),
    ("BAS40-05-TR", "BAS40-05", "tape_and_reel"),
    ("GRM188R71C104KA01D-CT", "GRM188R71C104KA01D", "cut_tape"),
    ("C0402C104K4RACTU (Cut Tape)", "C0402C104K4RACTU", "cut_tape"),
    ("1N4148WS (Cut Tape)", "1N4148WS", "cut_tape"),
    ("1N4148,215 (Cut Tape)", "1N4148,215", "cut_tape"),
    ("CRCW0603-ND", "CRCW0603", "reel"),
    ("GRM155R71C104KA88D-ND", "GRM155R71C104KA88D", "reel"),
    ("AT3011F04 (Tube)", "AT3011F04", "tube"),
    ("760310108 (Tube)", "760310108", "tube"),
    ("744043100 (Reel)", "744043100", "reel"),
    ("UVZ1E100MDD1TB", "UVZ1E100MDD1", "tube"),
])
def test_strip_vendor_packaging_suffixes(raw, expected_mpn, expected_packaging):
    mpn, packaging, qty = strip_vendor_packaging(raw)
    assert mpn == expected_mpn
    assert packaging == expected_packaging
    assert qty is None


@pytest.mark.parametrize("raw,tail", [
    ("MAX3323EEUE+T", "T"),
    ("MAX3221EEAE+T", "T"),
    ("74HC595D+T", "T"),
    ("2N7002-T1G", ""),
    ("IRF540N", ""),
    ("BAT54S", ""),
    ("7805", ""),
    ("STM32F103C8T6", ""),
    ("744233-1", ""),
    ("VLS201610CX-1R0M1R9-1K", ""),
    ("RR0510P-102-D", ""),
    ("1SMB5927BT3G", ""),
])
def test_strip_vendor_packaging_leaves_real_part_numbers(raw, tail):
    mpn, packaging, _ = strip_vendor_packaging(raw)
    assert packaging is None
    assert mpn == raw


def test_strip_vendor_packaging_quantity_hints():
    mpn, packaging, qty = strip_vendor_packaging("C0603X104K3RAC7867 16K/REEL")
    assert (mpn, packaging, qty) == ("C0603X104K3RAC7867", "reel", 16000)

    mpn, packaging, qty = strip_vendor_packaging("C0603X104K3RAC7867 2500/REEL")
    assert (mpn, packaging, qty) == ("C0603X104K3RAC7867", "reel", 2500)

    mpn, packaging, qty = strip_vendor_packaging("T491A106M010AT 3K/CT")
    assert (mpn, packaging, qty) == ("T491A106M010AT", "cut_tape", 3000)

    mpn, packaging, qty = strip_vendor_packaging("RC0603FR-0710KL 5000/RL")
    assert (mpn, packaging, qty) == ("RC0603FR-0710KL", "reel", 5000)


def test_strip_vendor_packaging_whitespace_collapse():
    mpn, packaging, _ = strip_vendor_packaging("RC0603FR-0710KL   (Cut Tape)")
    assert (mpn, packaging) == ("RC0603FR-0710KL", "cut_tape")


def test_mpn_key_fuzzy_equality():
    assert mpn_key("rc0603fr-07 10kL-tr") == mpn_key("RC0603FR-0710KL")
    assert mpn_key("1Nd14") == "1ND14"
    assert mpn_key(None) == ""
    assert mpn_key("a/b_c.d,e") == "ABCDE"


# ---------------------------------------------------------------------------
# Stage 2: tolerance extraction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected_value,expected_tolerance", [
    ("10kΩ ±5%", "10kΩ", "±5%"),
    ("1kΩ 1%", "1kΩ", "±1%"),
    ("100nF 10%", "100nF", "±10%"),
    ("(±1%)", "", "±1%"),
    ("(±5%) 1206", "1206", "±5%"),
    ("100nF (±10%)", "100nF", "±10%"),
    ("10kΩ +/-5%", "10kΩ", "±5%"),
    ("1kΩ ±0.5%", "1kΩ", "±0.5%"),
    ("±0.1pF", "", "±0.1pF"),
])
def test_tolerance_percent_and_absolute(raw, expected_value, expected_tolerance):
    value, tolerance = extract_tolerance(raw)
    assert tolerance == expected_tolerance
    assert value == expected_value


@pytest.mark.parametrize("raw,expected_value,expected_tolerance", [
    ("100nF J", "100nF", "±5%"),
    ("100nF F", "100nF", "±1%"),
    ("100nF K", "100nF", "±10%"),
    ("100nF (K)", "100nF", "±10%"),
    ("100nF ±5% J", "100nF", "±5%"),
])
def test_tolerance_letter_codes(raw, expected_value, expected_tolerance):
    value, tolerance = extract_tolerance(raw)
    assert tolerance == expected_tolerance
    assert value == expected_value


@pytest.mark.parametrize("raw", [
    "1M",         # no unit / magnitude-qualifying token -> "Mega" not code
    "1M 200W",    # guard channel: keep the whole value untouched
    "SMD",        # not a value at all
    "220R",       # trailing R is the unit, not a code (no whitespace)
    "LED100",     # letter glued to number cannot be a code
])
def test_tolerance_letter_codes_never_false_positive(raw):
    value, tolerance = extract_tolerance(raw)
    assert tolerance == ""
    assert value == raw


def test_tolerance_from_notes():
    value, tolerance = extract_tolerance("100Ω", "Tolerance: 1%")
    assert (value, tolerance) == ("100Ω", "±1%")

    value, tolerance = extract_tolerance("100Ω", "Tol 5%")
    assert (value, tolerance) == ("100Ω", "±5%")

    value, tolerance = extract_tolerance("100Ω", "no tolerance info here")
    assert (value, tolerance) == ("100Ω", "")


def test_tolerance_no_paren_residue():
    value, _ = extract_tolerance("(±1%)")
    assert not value
    value, _ = extract_tolerance("10kΩ (±5%)")
    assert value == "10kΩ"


# ---------------------------------------------------------------------------
# Stage 3: package detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,description,notes,mpn,expected", [
    ("10kΩ", "Chip resistor SMD 0603", "", "", "0603"),
    ("10kΩ 0603", "", "", "", "0603"),
    ("0.1uF", "Cap X7R 0805", "", "", "0805"),
    ("470nF", "Cap", "SMD 1206", "", "1206"),
    ("100nF", "Cap 1608", "", "", "0603"),       # metric -> imperial
    ("100nF", "Cap 2012", "", "", "0805"),
    ("100nF", "Cap 3216", "", "", "1206"),
    ("10kΩ", "", "", "RC0603FR-0710KL", "0603"),
    ("10kΩ", "", "", "C2012X7R1H104K125AC", "0805"),
    ("10kΩ", "", "", "CRCW1206-10K", "1206"),
    ("10kΩ", "", "", "RC0402FR-074K7L", "0402"),
    # Start-anchored sizes ("0402W8F1002T5E") are deliberately not detected —
    # the embedded rule only accepts letter-flanked codes.
    ("10kΩ", "", "", "0402W8F1002T5E", None),
    ("", "Regulator", "", "", None),
    ("2024-01-01", "", "", "", None),            # a date is not a case code
    ("10uH", "", "", "VLS201610CX-1R0M1R9-1K", None),  # 2016 is not exotic? excluded
])
def test_detect_package_chip(value, description, notes, mpn, expected):
    assert detect_package(value, description, notes, mpn) == expected


@pytest.mark.parametrize("text,expected", [
    ("SOT-23", "SOT-23"),
    ("SOIC-8", "SOIC-8"),
    ("TO-92", "TO-92"),
    ("QFN-16", "QFN-16"),
    ("DIP-14", "DIP-14"),
])
def test_detect_package_family(text, expected):
    assert detect_package(value=text) == expected


def test_detect_package_explicit_wins():
    assert detect_package(value="0603", package="0805") == "0805"


def test_detect_package_merged_magnitude_never_misread():
    # "CRCW040210K0FKED" concatenates the 0402 size with the 10k value; the
    # embedded rule must refuse digit-op-era merges.
    assert detect_package(mpn="CRCW040210K0FKED") is None


# ---------------------------------------------------------------------------
# Stage 4: units
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("10uF", "10uF"),
    ("10µF", "10uF"),
    ("10μF", "10uF"),      # Greek mu
    ("10 uF", "10uF"),
    ("10k Ω", "10kΩ"),
    ("4,7kΩ", "4,7kΩ"),
    ("10 µH", "10uH"),
    (" 10 uF ", "10uF"),
])
def test_canonical_value(raw, expected):
    assert canonical_value(raw) == expected


@pytest.mark.parametrize("value,expected", [
    ("10uF", "1e-05 F"),
    ("100nF", "1e-07 F"),
    ("0.1uF", "1e-07 F"),
    ("1uF", "1e-06 F"),
    ("10µF", "1e-05 F"),
    ("10 μF", "1e-05 F"),
    ("1uH", "1e-06 H"),
    ("10uH", "1e-05 H"),
    ("10kΩ", "10000 Ω"),
    ("4,7kΩ", "4700 Ω"),
    ("470R", "470 Ω"),
    ("10Ω", "10 Ω"),
    ("200kΩ", "200000 Ω"),
    ("0.5V", "0.5 V"),
    ("12V", "12 V"),
    ("100mA", "0.1 A"),
    ("0.1pF", "1e-13 F"),
    ("10MHz", "1e+07 Hz"),
])
def test_value_to_si_convertible(value, expected):
    assert value_to_si(value) == expected


@pytest.mark.parametrize("value", [
    "10k",        # engineering-only, ambiguous dimension
    "100n",       # engineering-only
    "104k",       # not a unit
    "LED",        # no magnitude
    "1M",         # no unit
    "",           # empty
    None,
])
def test_value_to_si_unconvertible(value):
    assert value_to_si(value) is None


# ---------------------------------------------------------------------------
# Pipeline / integration
# ---------------------------------------------------------------------------

def test_clean_row_noop_is_byte_identical():
    row = _raw_row(
        part_number="F1", description="LED indicator",
        manufacturer_part_number="", value="LED",
    )
    cleaned = clean_row(dict(row))
    assert cleaned == row
    for key in ("tolerance", "packaging", "packaging_qty", "value_si"):
        assert key not in cleaned


def test_clean_row_additive_only():
    cleaned = clean_row(_raw_row())
    assert cleaned["manufacturer_part_number"] == "UVZ1E100MDD1"
    assert cleaned["value"] == "10uF"
    assert cleaned["tolerance"] == "±20%"
    assert cleaned["packaging"] == "tube"
    assert cleaned["value_si"] == "1e-05 F"
    for key in ("part_number", "description", "quantity", "unit",
                "manufacturer", "supplier", "reference_designator", "notes"):
        assert cleaned[key] == _raw_row()[key]


def test_normalize_cleans_by_default():
    out = BomNormalizer().normalize([_raw_row()])[0]
    assert out["value"] == "10uF"
    assert out["tolerance"] == "±20%"
    assert out["packaging"] == "tube"
    assert out["value_si"] == "1e-05 F"


def test_normalize_clean_false_is_noop():
    out = BomNormalizer().normalize([_raw_row()], clean=False)[0]
    assert out == _raw_row()


def test_normalize_clean_override_param():
    norm = BomNormalizer(clean=False)
    assert norm.normalize([_raw_row()])[0] == _raw_row()
    assert norm.normalize([_raw_row()], clean=True)[0]["tolerance"] == "±20%"

    norm_on = BomNormalizer(clean=True)
    assert norm_on.normalize([_raw_row()], clean=False)[0] == _raw_row()


def test_snapshot_tolerance_attribute():
    cleaned = BomNormalizer().normalize([_raw_row()])[0]
    snapshot = normalize_row_from_dict(cleaned, 0)
    assert snapshot.attributes["tolerance"] == "±20%"
    assert snapshot.attributes["value"] == "10uF"


# ---------------------------------------------------------------------------
# Standard noisy dataset (issue #24 acceptance: >= 90% accuracy)
# ---------------------------------------------------------------------------

def test_standard_dataset_has_decent_coverage():
    csv_rows = CsvAdapter().read(str(DATASET))
    assert len(csv_rows) >= 40
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert len(expected) == len(csv_rows)
    parts = {row["part_number"] for row in csv_rows}
    assert parts == set(expected.keys())


def test_standard_dataset_accuracy():
    """Line-level accuracy on the hand-labelled noisy BOM dataset.

    A line item is a *full match* when every canonical field asserted in the
    ground truth equals the cleaned output for that part number. The issue #24
    acceptance bar is >= 90% accuracy on the standard test dataset.
    """
    csv_rows = CsvAdapter().read(str(DATASET))
    cleaned = BomNormalizer().normalize(csv_rows)
    by_part = {row["part_number"]: row for row in cleaned}
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))

    line_results = {}
    field_asserts = 0
    field_misses = 0
    for part, want in expected.items():
        got = by_part.get(part)
        assert got is not None, f"missing cleaned row for {part}"
        ok = []
        for field, expected_value in want.items():
            field_asserts += 1
            match = str(got.get(field)) == str(expected_value)
            ok.append(match)
            if not match:
                field_misses += 1
        line_results[part] = all(ok)

    full_matches = sum(line_results.values())
    accuracy = full_matches / len(line_results)

    failures = [p for p, ok in line_results.items() if not ok]
    assert field_misses == 0, f"asserted-field mismatches in: {failures}"
    assert accuracy >= 0.90, (
        f"accuracy {accuracy:.2%} is below the 90% bar; failing parts: {failures}"
    )


def test_standard_dataset_field_level():
    """Field-level victories the dataset is required to hit."""
    csv_rows = CsvAdapter().read(str(DATASET))
    cleaned = BomNormalizer().normalize(csv_rows)
    by_part = {row["part_number"]: row for row in cleaned}

    assert by_part["R2"]["manufacturer_part_number"] == "RC0603FR-0710KL"
    assert by_part["R2"]["packaging"] == "tape_and_reel"
    assert by_part["R2"]["package"] == "0603"
    assert by_part["C7"]["manufacturer_part_number"] == "UVZ1E100MDD1"
    assert by_part["C7"]["packaging"] == "tube"
    assert by_part["C7"]["tolerance"] == "±20%"
    assert by_part["D4"]["manufacturer_part_number"] == "1N4148,215"
    assert by_part["D4"]["packaging"] == "cut_tape"
    assert by_part["R15"]["tolerance"] == "±1%"          # from notes
    assert by_part["R15"]["value_si"] == "100 Ω"
    assert by_part["R12"]["tolerance"] == "±5%"          # ASCII +/-5%
    assert by_part["R13"]["package"] == "1206"           # embedded MPN case