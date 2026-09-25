"""Composite confidence scoring and normalization telemetry reporting.

Builds on :meth:`BomNormalizer.classify_column`, which combines a header
lexical score with a content value-profile score, to compute per-line-item
and per-table composite confidence scores in [0, 1]. Every item is also
assigned a coarse *component category* so the emitted structured telemetry
report can be broken down both by column and by component category.

The public entry point is :func:`build_confidence_report`; the CLI wires
``--min-confidence`` to the ``flagged`` entries it produces.
"""

import re
import statistics
from typing import Any, Dict, List, Optional, Tuple

from .normalizer import BomNormalizer
from .schema import FIELD_SCHEMAS, STANDARD_HEADERS

# Relative weight of each standard field in the per-item composite score.
# Identity, quantity and value fields are decision-critical; cosmetic or
# metadata fields (unit, package, notes, ...) contribute less.
FIELD_WEIGHTS: Dict[str, float] = {
    "part_number": 1.0,
    "manufacturer_part_number": 1.0,
    "quantity": 1.0,
    "value": 1.0,
    "reference_designator": 0.8,
    "description": 0.8,
    "manufacturer": 0.4,
    "supplier": 0.4,
    "unit": 0.4,
    "package": 0.4,
    "notes": 0.2,
}

# Coarse component categories derived from value units and free-text
# keywords. Longer, distinctive tokens are preferred so ordinary
# description prose does not collide.
_CATEGORY_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "resistor": ("resistor", "res array", "resistive", "potentiometer", "trimmer", "r-net"),
    "capacitor": ("capacitor", "capacitance", "electrolytic", "supercapacitor"),
    "inductor": ("inductor", "coil", "choke", "ferrite bead", "winding"),
    "diode": ("diode", "schottky", "zener", "rectifier", "bridge rectifier"),
    "transistor": ("transistor", "mosfet", "bjt", "thyristor", "triac"),
    "ic": (
        "microcontroller", "mcu", "regulator", "amplifier", "op-amp", "opamp",
        "decoder", "encoder", "driver", "transceiver", "interface", "logic",
        "gate", "adc", "dac", "sensor", "fpga", "cpld", "microprocessor",
    ),
    "connector": ("connector", "header", "socket", "terminal block", "jack", "receptacle"),
    "crystal": ("crystal", "resonator", "oscillator"),
    "fuse": ("fuse",),
    "switch": ("switch", "push button", "toggle switch", "rocker"),
    "battery": ("battery", "rechargeable cell"),
    "led": ("led",),
}

# Reference designator prefixes mapped onto component categories. Two-letter
# prefixes are checked before single-letter ones (e.g. "sw" -> switch).
_PREFIX_CATEGORY: Dict[str, str] = {
    "sw": "switch",
    "bt": "battery",
    "r": "resistor",
    "c": "capacitor",
    "l": "inductor",
    "d": "diode",
    "u": "ic",
    "q": "transistor",
    "j": "connector",
    "x": "crystal",
    "y": "crystal",
    "f": "fuse",
    "b": "battery",
}

# Value-unit suffixes that unambiguously identify a passive component.
_RESISTOR_UNITS = {"r", "ohm", "ω", "Ω"}
_CAPACITOR_UNITS = {"f", "mf", "uf", "pf", "nf", "kf", "µf"}
_INDUCTOR_UNITS = {"h", "mh", "uh", "nh", "kh", "µh"}


def _value_unit(value: str) -> Optional[str]:
    """Return the canonical unit token embedded in a component value."""
    match = re.match(r"^\s*[\d.,]+\s*(?:[pnmkMGKµu])?([a-zA-ZΩ]+)?\s*$", str(value).strip())
    if not match or not match.group(1):
        return None
    return match.group(1).lower()


def classify_component(row: Dict[str, Any]) -> str:
    """Classify a normalized BOM row into a coarse component category.

    Category resolution order is: LED keyword, passive value unit, free-text
    keywords, then reference designator prefix. Falls back to ``other``.
    """
    combined = " ".join(
        str(row.get(field) or "") for field in ("value", "description", "part_number")
    ).lower()

    if "led" in combined or "light emitting diode" in combined:
        return "led"

    unit = _value_unit(str(row.get("value") or ""))
    if unit in _RESISTOR_UNITS:
        return "resistor"
    if unit in _CAPACITOR_UNITS:
        return "capacitor"
    if unit in _INDUCTOR_UNITS:
        return "inductor"

    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in combined for keyword in keywords):
            return category

    ref_prefix = re.match(r"^\s*([A-Za-z]{1,2})", str(row.get("reference_designator") or ""))
    if ref_prefix:
        prefix = ref_prefix.group(1).lower()
        if prefix in _PREFIX_CATEGORY:
            return _PREFIX_CATEGORY[prefix]

    return "other"


def _conformance(value: str, field_id: str) -> float:
    """Score how well a cell value fits its canonical field schema.

    Matches the schema's expected regex patterns; present-but-non-conforming
    values score 0.6 and empty cells score 0.0.
    """
    if not value or not value.strip():
        return 0.0
    patterns = (
        FIELD_SCHEMAS.get(field_id, {}).get("expected", {}).get("patterns", [])
    )
    if not patterns:
        return 1.0
    for pattern in patterns:
        if re.match(pattern, value.strip()):
            return 1.0
    return 0.6


class ConfidenceScorer:
    """Compute item/table composite confidence and telemetry breakdowns.

    The per-column composite confidence comes from
    :meth:`BomNormalizer.classify_column` (header lexical score blended with
    a content value-profile score). Field assignment, however, reuses
    :meth:`BomNormalizer.infer_column_mapping`, which applies the legacy
    name+content scoring and conflict resolution, so the confidence pipeline
    always scores the exact same normalized rows the normalizer produces.
    """

    def __init__(self, normalizer: Optional[BomNormalizer] = None) -> None:
        self.normalizer = normalizer if normalizer is not None else BomNormalizer()

    def classify_and_map(self, raw_rows: List[Dict[str, Any]]) -> Tuple[Dict[str, float], Dict[str, Dict[str, Any]]]:
        """Classify every column and resolve each field to its best column.

        Returns:
            (columns_by_field, classifications): columns_by_field maps a
            standard field id to the composite confidence of its assigned
            column; classifications maps each raw column to its
            :meth:`BomNormalizer.classify_column` result.
        """
        classifications = self.normalizer.classify_columns(raw_rows)
        mapping = self.normalizer.infer_column_mapping(raw_rows)

        best: Dict[str, Tuple[str, float]] = {}
        for column, field in mapping.items():
            if field is None:
                continue
            confidence = classifications.get(column, {}).get("confidence", 0.0)
            if field not in best or confidence > best[field][1]:
                best[field] = (column, confidence)

        columns_by_field: Dict[str, float] = {
            field: confidence for field, (_, confidence) in best.items()
        }
        return columns_by_field, classifications

    def _normalize(self, raw_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize raw rows with the normalizer's own mapping pipeline."""
        return self.normalizer.normalize(raw_rows)

    def score_item(self, normalized_row: Dict[str, Any], columns_by_field: Dict[str, float]) -> Tuple[float, Dict[str, Dict[str, Any]]]:
        """Score a single normalized line item.

        Returns:
            (confidence, per_field) where confidence is in [0, 1] and
            per_field maps each standard field to a dict with the field
            confidence, value score and presence flag.
        """
        numerator = 0.0
        denominator = 0.0
        per_field: Dict[str, Dict[str, Any]] = {}

        for field in STANDARD_HEADERS:
            weight = FIELD_WEIGHTS[field]
            denominator += weight

            value = str(normalized_row.get(field) or "")
            present = bool(value.strip())
            value_score = _conformance(value, field)

            column_confidence = columns_by_field.get(field, 0.0)
            field_confidence = 0.5 * column_confidence + 0.5 * value_score
            numerator += weight * field_confidence

            per_field[field] = {
                "confidence": round(field_confidence, 4),
                "value_score": round(value_score, 4),
                "present": present,
            }

        confidence = numerator / denominator if denominator else 0.0
        return confidence, per_field

    def table_statistics(self, item_confidences: List[float]) -> Dict[str, float]:
        """Aggregate per-line-item confidences into a table-level profile."""
        if not item_confidences:
            return {"rows": 0, "mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}
        return {
            "rows": len(item_confidences),
            "mean": round(statistics.mean(item_confidences), 4),
            "median": round(statistics.median(item_confidences), 4),
            "min": round(min(item_confidences), 4),
            "max": round(max(item_confidences), 4),
        }

    def build_report(self, raw_rows: List[Dict[str, Any]], min_confidence: Optional[float] = None) -> Dict[str, Any]:
        """Compute composite confidence telemetry for a raw BOM dataset.

        Args:
            raw_rows: Raw (unnormalized) BOM rows as list of dicts.
            min_confidence: Optional threshold in [0, 1]; line items scoring
                strictly below it are flagged in the report.

        Returns:
            Structured telemetry report with ``table``, ``items``,
            ``breakdown_by_column`` and ``breakdown_by_category`` sections.
        """
        if not raw_rows:
            return {
                "table": {"rows": 0, "table_confidence": 0.0},
                "items": [],
                "breakdown_by_column": {},
                "breakdown_by_category": {},
            }

        columns_by_field, classifications = self.classify_and_map(raw_rows)
        normalized_rows = self._normalize(raw_rows)
        mapping = self.normalizer.infer_column_mapping(raw_rows)

        items = []
        item_confidences = []
        for index, normalized_row in enumerate(normalized_rows, start=1):
            confidence, per_field = self.score_item(normalized_row, columns_by_field)
            item_confidences.append(confidence)
            items.append({
                "row": index,
                "confidence": round(confidence, 4),
                "category": classify_component(normalized_row),
                "flagged": min_confidence is not None and confidence < min_confidence,
                "part_number": str(normalized_row.get("part_number") or ""),
                "reference_designator": str(normalized_row.get("reference_designator") or ""),
                "fields": per_field,
            })

        table_stats = self.table_statistics(item_confidences)
        flagged_count = sum(1 for item in items if item["flagged"])

        return {
            "schema_version": 1,
            "table": {
                "rows": table_stats["rows"],
                "table_confidence": table_stats["mean"],
                "median": table_stats["median"],
                "min": table_stats["min"],
                "max": table_stats["max"],
                "flagged_count": flagged_count,
                **({"min_confidence": round(min_confidence, 4)} if min_confidence is not None else {}),
            },
            "items": items,
            "breakdown_by_column": self._breakdown_by_column(
                items, mapping, columns_by_field, normalized_rows
            ),
            "breakdown_by_category": self._breakdown_by_category(items),
        }

    def _breakdown_by_column(
        self,
        items: List[Dict[str, Any]],
        mapping: Dict[str, Optional[str]],
        columns_by_field: Dict[str, float],
        normalized_rows: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Aggregate confidence information per standard field/column."""
        header_by_field: Dict[str, str] = {}
        for column, field in mapping.items():
            if field is not None:
                header_by_field.setdefault(field, column)

        breakdown: Dict[str, Dict[str, Any]] = {}
        for field in STANDARD_HEADERS:
            filled = sum(
                1 for row in normalized_rows if str(row.get(field) or "").strip()
            )
            breakdown[field] = {
                "column": header_by_field.get(field, ""),
                "column_confidence": round(columns_by_field.get(field, 0.0), 4),
                "filled": filled,
                "value_confidence": round(
                    statistics.mean(item["fields"][field]["value_score"] for item in items),
                    4
                ) if items else 0.0,
            }
        return breakdown

    def _breakdown_by_category(self, items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Aggregate confidence, counts and flagged counts per category."""
        grouped: Dict[str, List[float]] = {}
        for item in items:
            grouped.setdefault(item["category"], []).append(item["confidence"])
        return {
            category: {
                "count": len(confidences),
                "confidence": round(statistics.mean(confidences), 4),
                "flagged": sum(1 for item in items if item["category"] == category and item["flagged"]),
            }
            for category, confidences in grouped.items()
        }


def build_confidence_report(raw_rows: List[Dict[str, Any]], min_confidence: Optional[float] = None) -> Dict[str, Any]:
    """Convenience wrapper around :class:`ConfidenceScorer`."""
    return ConfidenceScorer().build_report(raw_rows, min_confidence=min_confidence)