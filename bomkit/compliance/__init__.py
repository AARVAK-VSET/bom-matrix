"""Environmental compliance evaluation package for RoHS and REACH standards."""

from .engine import (
    ComplianceStatus,
    ComplianceViolation,
    ComplianceResult,
    evaluate_compliance,
    generate_compliance_delta_events,
)
from .standards import (
    ROHS_THRESHOLDS,
    REACH_SVHC_THRESHOLD,
    REACH_SVHC_SCREENING_REGISTRY,
    get_substance_threshold,
)

__all__ = [
    "ComplianceStatus",
    "ComplianceViolation",
    "ComplianceResult",
    "evaluate_compliance",
    "generate_compliance_delta_events",
    "ROHS_THRESHOLDS",
    "REACH_SVHC_THRESHOLD",
    "REACH_SVHC_SCREENING_REGISTRY",
    "get_substance_threshold",
]
