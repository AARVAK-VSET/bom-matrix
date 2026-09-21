"""Test suite for composite confidence scoring and telemetry reporting.

Covers the item/table composite confidence model (0.0 to 1.0), the
structured telemetry report broken down by column and component category,
and the ``--min-confidence`` CLI threshold flag.
"""

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bomkit.confidence import ConfidenceScorer, classify_component, build_confidence_report

# A 5-item BOM fixture. Rows 3 and 5 are deliberately incomplete (nearly all
# core fields missing) so exactly 2 items score below any reasonable
# threshold; rows 1, 2 and 4 are complete and well-formed.
FIVE_ITEM_ROWS = [
    {
        "Part Number": "R_Small",
        "Qty": "4",
        "Value": "10kΩ",
        "Unit": "pcs",
        "Manufacturer": "Vishay",
        "Supplier": "Digi-Key",
        "Manufacturer Part Number": "RC0603FR-0710KL",
        "Reference": "R1-R4",
        "Package": "0603",
        "Description": "Resistor, small symbol",
        "Notes": "Alt: CRCW0603",
    },
    {
        "Part Number": "C_Small",
        "Qty": "3",
        "Value": "10uF",
        "Unit": "pcs",
        "Manufacturer": "Murata",
        "Supplier": "Mouser",
        "Manufacturer Part Number": "GRM188R61A106K",
        "Reference": "C1-C3",
        "Package": "0402",
        "Description": "Capacitor, ceramic",
        "Notes": "X5R",
    },
    {
        "Part Number": "",
        "Qty": "",
        "Value": "",
        "Unit": "pcs",
        "Manufacturer": "",
        "Supplier": "",
        "Manufacturer Part Number": "",
        "Reference": "",
        "Package": "",
        "Description": "",
        "Notes": "check stock",
    },
    {
        "Part Number": "LED",
        "Qty": "8",
        "Value": "3.3V",
        "Unit": "pcs",
        "Manufacturer": "Cree",
        "Supplier": "Arrow",
        "Manufacturer Part Number": "CREE-XPEBWT-L1",
        "Reference": "D8-D15",
        "Package": "5050",
        "Description": "Light emitting diode",
        "Notes": "White 3.3V",
    },
    {
        "Part Number": "",
        "Qty": "",
        "Value": "",
        "Unit": "pcs",
        "Manufacturer": "",
        "Supplier": "",
        "Manufacturer Part Number": "",
        "Reference": "",
        "Package": "",
        "Description": "",
        "Notes": "backorder",
    },
]


def _write_csv(path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(FIVE_ITEM_ROWS[0].keys()))
        writer.writeheader()
        writer.writerows(FIVE_ITEM_ROWS)


def test_min_confidence_flag(tmp_path: Path) -> None:
    """--min-confidence flags exactly 2 items and exits non-zero."""
    csv_file = tmp_path / "bom.csv"
    _write_csv(csv_file)

    result = subprocess.run(
        [sys.executable, "-m", "bomkit.cli", str(csv_file), "--min-confidence", "0.9"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )

    assert result.returncode != 0

    text = result.stdout + result.stderr
    assert "Flagged low-confidence line items" in text
    assert "row 3" in text
    assert "row 5" in text

    report, _ = json.JSONDecoder().raw_decode(result.stdout[result.stdout.index("{"):])
    assert report["table"]["flagged_count"] == 2
    flagged = [item["row"] for item in report["items"] if item["flagged"]]
    assert flagged == [3, 5]


def test_min_confidence_passes_with_all_good_items(tmp_path: Path) -> None:
    """No flags means a zero exit status and a passing summary."""
    rows = [dict(FIVE_ITEM_ROWS[0]), dict(FIVE_ITEM_ROWS[1]), dict(FIVE_ITEM_ROWS[3])]
    csv_file = tmp_path / "clean.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = subprocess.run(
        [sys.executable, "-m", "bomkit.cli", str(csv_file), "--min-confidence", "0.5"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )

    assert result.returncode == 0
    assert "Confidence check passed" in result.stdout


def test_table_confidence_within_bounds() -> None:
    """Table and item confidences stay within [0, 1]."""
    report = build_confidence_report(FIVE_ITEM_ROWS)

    assert 0.0 <= report["table"]["table_confidence"] <= 1.0
    assert report["table"]["rows"] == 5
    for item in report["items"]:
        assert 0.0 <= item["confidence"] <= 1.0


def test_incomplete_items_score_lower() -> None:
    """Incomplete rows must score below complete rows for the same table."""
    report = build_confidence_report(FIVE_ITEM_ROWS)
    by_row = {item["row"]: item["confidence"] for item in report["items"]}

    assert by_row[3] < by_row[1]
    assert by_row[5] < by_row[2]
    assert by_row[3] < 0.9
    assert by_row[5] < 0.9
    assert by_row[1] >= 0.9
    assert by_row[2] >= 0.9
    assert by_row[4] >= 0.9


def test_telemetry_breakdown_structure() -> None:
    """Report breaks confidence down by column and by component category."""
    report = build_confidence_report(FIVE_ITEM_ROWS, min_confidence=0.9)

    assert "breakdown_by_column" in report
    assert "breakdown_by_category" in report
    assert "part_number" in report["breakdown_by_column"]
    assert "quantity" in report["breakdown_by_column"]
    assert report["table"]["flagged_count"] == 2

    categories = report["breakdown_by_category"]
    assert "resistor" in categories
    assert "capacitor" in categories
    assert "led" in categories
    assert "other" in categories
    for stats in categories.values():
        assert stats["count"] >= 1
        assert 0.0 <= stats["confidence"] <= 1.0


def test_component_category_classification() -> None:
    """Coarse component categories are derived from standard fields."""
    assert classify_component({"value": "10kΩ", "description": "", "part_number": ""}) == "resistor"
    assert classify_component({"value": "10uF", "description": "", "part_number": ""}) == "capacitor"
    assert classify_component({"value": "100uH", "description": "", "part_number": ""}) == "inductor"
    assert classify_component({"value": "3.3V", "description": "Light emitting diode", "part_number": ""}) == "led"
    assert classify_component({"value": "", "description": "MCU 32-bit", "part_number": ""}) == "ic"
    assert classify_component({"value": "", "description": "", "part_number": "R_Small"}) == "other"


def test_scorer_scales_with_data_quality() -> None:
    """A fully populated table scores higher than a sparse one."""
    scorer = ConfidenceScorer()
    good_report = scorer.build_report([dict(FIVE_ITEM_ROWS[0])] * 3)
    sparse_report = scorer.build_report([dict(FIVE_ITEM_ROWS[2])] * 3)

    assert good_report["table"]["table_confidence"] > sparse_report["table"]["table_confidence"]