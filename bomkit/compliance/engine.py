"""Environmental compliance rule evaluation engine for RoHS and REACH standards."""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

from .standards import get_substance_threshold


class ComplianceStatus(str, Enum):
    """
    Summary compliance status for a BOM line item.

    COMPLIANT: All declared substance concentrations are within threshold limits.
    NON_COMPLIANT: One or more declared substances exceed regulatory thresholds.
    UNKNOWN: Material declaration is missing, empty, or unspecified.
    """
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    UNKNOWN = "UNKNOWN"


@dataclass
class ComplianceViolation:
    """Represents a single substance regulatory threshold violation."""
    substance: str
    measured_percentage: float
    threshold: float
    standard: str = "RoHS"
    message: str = ""

    def __post_init__(self):
        if not self.message:
            self.message = (
                f"Substance '{self.substance}' measured at {self.measured_percentage}% "
                f"exceeds {self.standard} threshold limit of {self.threshold}%."
            )


@dataclass
class ComplianceResult:
    """Summary compliance evaluation result for a line item."""
    status: ComplianceStatus
    violations: List[ComplianceViolation] = field(default_factory=list)
    standard: str = "RoHS"


def _parse_percentage(value: Any, substance: str) -> float:
    """
    Validate and parse substance concentration percentage.

    Rejects None, non-numeric values, NaN, Infinity, and negative numbers.
    """
    if value is None:
        raise ValueError(f"Missing percentage value for substance '{substance}'")

    if isinstance(value, str):
        cleaned = value.strip().rstrip("%").strip()
        try:
            val_float = float(cleaned)
        except ValueError:
            raise ValueError(f"Invalid numeric concentration '{value}' for substance '{substance}'")
    elif isinstance(value, (int, float)):
        val_float = float(value)
    else:
        raise ValueError(f"Unsupported concentration type {type(value)} for substance '{substance}'")

    if not math.isfinite(val_float) or val_float < 0:
        raise ValueError(f"Concentration must be a finite non-negative number for '{substance}', got {val_float}")

    return val_float


def evaluate_compliance(
    item: Any = None,
    standard: Optional[str] = "RoHS",
    custom_thresholds: Optional[Dict[str, float]] = None,
    **kwargs
) -> ComplianceResult:
    """
    Evaluate environmental compliance for a BOM line item.

    Compares declared substance percentages against RoHS or REACH screening thresholds.

    Args:
        item: Line item (dict with 'material_declaration', direct declaration dict,
              or object with .material_declaration attribute).
        standard: 'RoHS' (default) or 'REACH'.
        custom_thresholds: Optional custom substance -> threshold percentage mapping.
        **kwargs: Optional keyword arguments (e.g. material_declaration={...}).

    Returns:
        ComplianceResult with status (COMPLIANT, NON_COMPLIANT, UNKNOWN) and violations list.
    """
    active_standard = (standard or "RoHS").strip()

    # Extract material declaration from supported item structures
    declaration = kwargs.get("material_declaration")

    if declaration is None and isinstance(item, dict):
        declaration = item.get("material_declaration")
        # Direct substance declaration dict (e.g. {"Pb": 0.12})
        if declaration is None and not any(k in item for k in ("part_number", "id", "attributes", "description", "quantity")):
            declaration = item
    elif declaration is None and item is not None:
        declaration = getattr(item, "material_declaration", None)

    # Missing or empty declaration -> UNKNOWN
    if declaration is None or not isinstance(declaration, dict) or len(declaration) == 0:
        return ComplianceResult(
            status=ComplianceStatus.UNKNOWN,
            violations=[],
            standard=active_standard
        )

    # Evaluate each declared substance against applicable threshold limits
    violations: List[ComplianceViolation] = []

    for substance in sorted(declaration.keys()):
        raw_val = declaration[substance]
        measured_percentage = _parse_percentage(raw_val, substance)

        threshold = get_substance_threshold(
            substance,
            standard=active_standard,
            custom_thresholds=custom_thresholds
        )
        if threshold is not None and measured_percentage > threshold:
            violations.append(
                ComplianceViolation(
                    substance=substance,
                    measured_percentage=measured_percentage,
                    threshold=threshold,
                    standard=active_standard,
                )
            )

    status = ComplianceStatus.NON_COMPLIANT if violations else ComplianceStatus.COMPLIANT

    return ComplianceResult(
        status=status,
        violations=violations,
        standard=active_standard
    )


def generate_compliance_delta_events(
    items: List[Dict[str, Any]],
    standard: Optional[str] = "RoHS",
    custom_thresholds: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """
    Generate compliance violation events for line items in a BOM delta report.
    """
    events = []
    for item in items:
        res = evaluate_compliance(item, standard=standard, custom_thresholds=custom_thresholds)
        if res.status == ComplianceStatus.NON_COMPLIANT:
            item_id = item.get("id") or item.get("bom_item_id") or item.get("part_number")
            for v in res.violations:
                events.append({
                    "event_type": "COMPLIANCE_VIOLATION",
                    "domain": "QUALITY",
                    "severity": "HIGH",
                    "substance": v.substance,
                    "measured_percentage": v.measured_percentage,
                    "threshold": v.threshold,
                    "standard": v.standard,
                    "message": v.message,
                    "item_id": str(item_id) if item_id else None,
                })
    return events
