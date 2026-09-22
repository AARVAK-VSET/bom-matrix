"""Comprehensive component-cleaning pipeline (Issue #24).

Runs the multi-stage cleaning stages over normalized ``STANDARD_HEADERS`` rows
to produce structured line-item dictionaries with canonical fields:

1. :mod:`~bomkit.clean.vendor_packaging` — extract and strip vendor packaging
   codes (``-TR``, ``-CT``, ``TAPE & REEL``, ``16K/REEL``, …) from the
   manufacturer part number;
2. :mod:`~bomkit.clean.tolerance` — extract tolerances (``±5%``, letter codes,
   ``±0.1pF``) out of the value;
3. :mod:`~bomkit.clean.package_detector` — detect the footprint / case size
   from value, description and notes;
4. :mod:`~bomkit.clean.units` — canonicalize value units and emit a
   deterministic SI conversion (``value_si``).

The canonical line-item dictionary keeps the 11 standard headers and, only
when something was actually recovered, adds the derived fields
``tolerance``, ``packaging``, ``packaging_qty``, ``value_si`` and a detected
``package``. Rows that needed no cleaning are returned byte-identical, so the
pipeline is purely additive and backward compatible.
"""

from typing import Any, Dict, List

from .tolerance import extract_tolerance
from .units import canonical_uom, canonical_value, value_to_si
from .package_detector import detect_package
from .vendor_packaging import strip_vendor_packaging

# Fields recovered by the pipeline, added only when non-empty.
DERIVED_FIELDS = ("tolerance", "packaging", "packaging_qty", "value_si")


class CleaningPipeline:
    """Multi-stage cleaner producing canonical line-item dictionaries."""

    def clean_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Clean a single row and return its canonical line-item dictionary.

        Args:
            row: A BOM row (raw or normalized; standard header keys used).

        Returns:
            A line-item dictionary with canonical fields (see module docstring).
        """
        out = dict(row)

        # --- Stage 1: vendor packaging-code strip (MPN + value tail) ---------
        mpn = str(out.get("manufacturer_part_number") or "").strip()
        if mpn:
            cleaned_mpn, packaging, packaging_qty = strip_vendor_packaging(mpn)
            # A marker-only value ("TR", "REEL") must never wipe the part
            # number: when nothing legitimately remains, keep the original
            # untouched and drop the (unsupported) packaging metadata.
            if cleaned_mpn:
                if cleaned_mpn != mpn or packaging:
                    out["manufacturer_part_number"] = cleaned_mpn
                if packaging:
                    out["packaging"] = packaging
                if packaging_qty is not None:
                    out["packaging_qty"] = str(packaging_qty)

        value_raw = str(out.get("value") or "").strip()
        if value_raw:
            cleaned_val, val_pkg, val_qty = strip_vendor_packaging(value_raw)
            # Vendor packaging on a value tail is unusual but possible
            # ("1kΩ 16K/REEL"); when detected, honour it without touching the
            # magnitude text.
            if val_pkg and not out.get("packaging"):
                out["packaging"] = val_pkg
            if val_qty is not None and not out.get("packaging_qty"):
                out["packaging_qty"] = str(val_qty)
            if val_pkg or val_qty is not None:
                value_raw = cleaned_val

        # --- Stage 3: package detection from context -------------------------
        detected = detect_package(
            value=value_raw,
            description=str(out.get("description") or ""),
            notes=str(out.get("notes") or ""),
            mpn=str(out.get("manufacturer_part_number") or ""),
            package=str(out.get("package") or ""),
        )
        if detected and not str(out.get("package") or "").strip():
            out["package"] = detected

        # --- Stage 2: tolerance extraction -----------------------------------
        notes = str(out.get("notes") or "")
        if value_raw:
            cleaned_value, tolerance = extract_tolerance(value_raw, notes)
        else:
            cleaned_value, tolerance = "", ""
        out["value"] = cleaned_value
        if tolerance:
            out["tolerance"] = tolerance

        # --- Stage 4: value-unit canonicalization + SI conversion ------------
        out["value"] = canonical_value(out["value"])
        if out["value"] and "value_si" not in out:
            si = value_to_si(out["value"])
            if si:
                out["value_si"] = si

        # --- Unit-of-measure canonicalization --------------------------------
        if out.get("unit"):
            out["unit"] = canonical_uom(str(out["unit"]))

        return out

    def clean_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Clean a batch of rows."""
        return [self.clean_row(row) for row in rows]


def clean_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Module-level convenience wrapper for :meth:`CleaningPipeline.clean_row`."""
    return CleaningPipeline().clean_row(row)


def clean_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Module-level convenience wrapper for :meth:`CleaningPipeline.clean_rows`."""
    return CleaningPipeline().clean_rows(rows)