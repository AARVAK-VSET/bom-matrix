"""Tests for CSV header detection and normalization robustness."""

import sys
from pathlib import Path

# Add parent directory to path to import bomkit
sys.path.insert(0, str(Path(__file__).parent.parent))

from bomkit import BomParser
from bomkit.adapters.csv_adapter import CsvAdapter


def test_header_detection_with_preamble_rows():
    """Ensure header detection skips preamble rows and maps correctly."""
    test_dir = Path(__file__).parent
    csv_file = test_dir / "Desktop FDM 3D Printer.csv"

    parser = BomParser(normalize=True)
    parser.register_adapter(CsvAdapter())

    rows = parser.parse(str(csv_file))
    assert rows, "No rows parsed from Desktop FDM 3D Printer.csv"

    first = rows[0]
    assert first["part_number"] == "FRM-ALU-2040"
    assert first["quantity"] == "4"
    assert first["unit"].lower() in {"ea", "each", "unit", "units"}
    assert first.get("supplier", "").lower() in {"misumi uk"}


def test_normalization_of_bom_4():
    """Ensure BOM-4.csv normalizes key columns."""
    test_dir = Path(__file__).parent
    csv_file = test_dir / "BOM-4.csv"

    parser = BomParser(normalize=True)
    parser.register_adapter(CsvAdapter())

    rows = parser.parse(str(csv_file))
    assert rows, "No rows parsed from BOM-4.csv"

    first = rows[0]
    assert first["reference_designator"].startswith("C1")
    assert first["quantity"] == "3"
    assert first["value"] == "10n"
    assert first["package"]


def test_obfuscated_header_row_is_not_leaked_as_data(tmp_path):
    """A cryptic header row (e.g. Column1,Column2,Column3) must be used as
    the header rather than leaking into the data rows."""
    csv_file = tmp_path / "obfuscated.csv"
    values = [
        "STM32F401RCT6", "STM32F103C8T6", "ATmega328P", "ESP32-WROOM-32",
        "RC0603FR-0710KL", "LM358", "1N4148", "2N3904", "MAX232", "74LS138",
    ]
    with open(csv_file, "w", newline="") as f:
        f.write("Column1,Column2,Column3\n")
        for i, value in enumerate(values):
            f.write(f"{value},{i + 1},R{i + 1}\n")

    parser = BomParser(normalize=True)
    parser.register_adapter(CsvAdapter())

    rows = parser.parse(str(csv_file))
    assert len(rows) == 10
    assert all(row["manufacturer_part_number"] in values for row in rows)
    assert all(str(row["reference_designator"]).startswith("R") for row in rows)
