"""Multi-stage component cleaning pipeline (Issue #24).

Provides vendor packaging-code stripping, tolerance extraction, package /
case-size detection and value-unit canonicalization, plus the orchestrating
:class:`~bomkit.clean.pipeline.CleaningPipeline` that turns noisy rows into
structured line-item dictionaries with canonical fields.
"""

from .pipeline import CleaningPipeline, clean_row, clean_rows, DERIVED_FIELDS
from .vendor_packaging import strip_vendor_packaging, packaging_from_text, mpn_key
from .tolerance import extract_tolerance
from .package_detector import detect_package
from .units import canonical_value, value_to_si, canonical_uom

__all__ = [
    "CleaningPipeline",
    "clean_row",
    "clean_rows",
    "DERIVED_FIELDS",
    "strip_vendor_packaging",
    "packaging_from_text",
    "mpn_key",
    "extract_tolerance",
    "detect_package",
    "canonical_value",
    "value_to_si",
    "canonical_uom",
]