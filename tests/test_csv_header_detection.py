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

def test_excel_adapter_detects_bom_sheet():
    """Ensure Excel adapter selects the BOM sheet instead of the active sheet."""
    from bomkit.adapters.excel_adapter import ExcelAdapter
    import openpyxl

    test_file = Path(__file__).parent / "multi_sheet_bom.xlsx"

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Instructions"

    ws1.append(["This is not a BOM"])
    ws1.append(["Some notes"])

    ws2 = wb.create_sheet("BOM")
    ws2.append(["Part Number", "Quantity", "Value"])
    ws2.append(["R1", 2, "10k"])

    wb.save(test_file)

    try:
        rows = ExcelAdapter().read(str(test_file))

        assert rows
        assert rows[0]["Part Number"] == "R1"
        assert rows[0]["Quantity"] == 2
        assert rows[0]["Value"] == "10k"
    finally:
        test_file.unlink(missing_ok=True)
def test_utf8_encoding_uses_sig(tmp_path):
    """Ensure UTF-8 CSV files use BOM-safe UTF-8 decoding."""
    csv_file = tmp_path / "test_utf8_encoding.csv"

    csv_file.write_text(
        "Item,Quantity\nCafé,2\n",
        encoding="utf-8"
    )

    adapter = CsvAdapter()

    assert adapter._detect_encoding(str(csv_file)) == "utf-8-sig"
    

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
