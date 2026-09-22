"""Tolerance extraction (cleaning stage 2).

Electrical values arrive with tolerances in many shapes: explicit percents
(``10kΩ ±5%``, ``1kΩ 1%``, ``(±20%)``), EIA letter codes (``J`` = ±5%,
``F`` = ±1%, ``K`` = ±10%, …) and absolute forms (``±0.1pF``). This stage
separates the tolerance from the value and emits it as a canonical field.

The value keeps its magnitude and unit (sans the extracted tolerance), so a
single uniform schema can hold ``value`` + ``tolerance``.
"""

import re
from typing import Optional, Tuple

# Explicit percent tolerance, tolerating surrounding parentheses and spaces:
# "±5%", " 5 %", "(±1%)", "+10/-5%". The trailing space before a letter code
# ("100nF ±5% J") is intentionally left in place so the letter code stays
# whitespace-separated for the later stage.
#
# Separator classes are bounded to a single optional character (instead of an
# unbounded run) so pathological long fields cannot trigger quadratic
# backtracking.
_PERCENT_RE = re.compile(r"[\s\-,;(]?([±+\-]?\s*\d+(?:\.\d+)?\s*%(?:\s*/\s*[±+\-]?\s*\d+(?:\.\d+)?\s*%)?)[\-,;)]?")

# Asymmetric percentage tolerance: percent on both parts ("+10%/-5%") or on
# the second part only ("+10/-5%").
_ASYMMETRIC_PERCENT_RE = re.compile(
    r"(?P<tok>"
    r"[±+\-]?\s*\d+(?:\.\d+)?\s*%\s*/\s*[±+\-]?\s*\d+(?:\.\d+)?\s*%"
    r"|[±+\-]?\s*\d+(?:\.\d+)?\s*/\s*[±+\-]?\s*\d+(?:\.\d+)?\s*%"
    r")[\-,;)]?"
)

# Absolute tolerance prefixed with a plus-or-minus sign: "±0.1pF", "+/-1uF".
_ABSOLUTE_RE = re.compile(r"[\s\-(;]?([±+\-]\s*\d+(?:\.\d+)?\s*(?:[pnumkMG]?[A-Za-zΩµμ]+))[\-,;)]?")

# EIA/letter tolerance codes, uppercase, only recognized when space-separated
# from the value so unit letters already consumed by the magnitude (e.g. the
# trailing "M" of "1M") are never misread. Allowed when the value contains a
# unit or a numeric magnitude.
_LETTER_CODES = {
    "B": "±0.1%", "C": "±0.25%", "D": "±0.5%", "F": "±1%",
    "G": "±2%", "J": "±5%", "K": "±10%", "M": "±20%",
    "P": "+100%/-0%", "Z": "+80%/-20%", "A": "±0.05%",
}
_LETTER_RE = re.compile(r"\s+[\(]?([A-HJKMNPZ])[\)]?\s*$")
_HAS_UNIT_RE = re.compile(r"\d\s*[pnumkMGμµ]?[A-Za-zΩ]+")
_HAS_NUMBER_RE = re.compile(r"\d")

# Notes patterns ("Tolerance: 5%", "Tol ±10%", "1% tolerance").
_NOTES_PERCENT_RE = re.compile(
    r"(?:tolerance|tol)\s*[:=]?\s*([±+\-]?\s*\d+(?:\.\d+)?\s*%)", re.IGNORECASE
)
_NOTES_PERCENT_SUFFIX_RE = re.compile(
    r"([±+\-]?\s*\d+(?:\.\d+)?\s*%)\s*(?:tolerance|tol)\b", re.IGNORECASE
)


def _normalize_tolerance(raw: str) -> str:
    """Normalize a raw tolerance to the canonical ``±%`` form."""
    raw = re.sub(r"\s+", "", raw)
    if raw.startswith(("±", "+", "-")):
        return raw
    return "±" + raw


def extract_tolerance(value: str, notes: str = "") -> Tuple[str, str]:
    """Extract a tolerance from a BOM value string (and optionally notes).

    Args:
        value: The raw value string (e.g. ``"10kΩ ±5%"``).
        notes: Optional notes text that may carry ``Tolerance: 5%``.

    Returns:
        A ``(cleaned_value, tolerance)`` pair. ``cleaned_value`` is the value
        with every extracted tolerance token removed and whitespace collapsed;
        ``tolerance`` is the canonical tolerance string (``"±5%"``) or ``""``
        when none was found.
    """
    if value is None:
        value = ""
    value = str(value).strip()
    # ASCII "+/-" is a common stand-in for the ± sign ("10kΩ +/-5%").
    value = re.sub(r"\+/[-−]\s*", "±", value)
    cleaned = value
    tolerance = ""

    # Remove every tolerance token from the value (all matches, not just the
    # first) so a doubly-annotated value like "1kΩ ±5% ±2%" is fully cleaned
    # and a second cleaning pass is a no-op.
    for pattern in (_ASYMMETRIC_PERCENT_RE, _PERCENT_RE, _ABSOLUTE_RE):
        while cleaned:
            m = pattern.search(cleaned)
            if not m:
                break
            token = (m.groupdict().get("tok") or m.group(1)).strip()
            if not tolerance:
                tolerance = _normalize_tolerance(token)
            # Remove the whole match span (including wrapping parentheses /
            # spaces) so no ``()`` residue is left behind.
            cleaned = cleaned[: m.start()] + cleaned[m.end():]

    # Letter codes: only for values that look electrical (a unit or a numeric
    # magnitude) and where the code is whitespace-separated so it can never be
    # confused with the unit itself (e.g. the trailing "M" of "1M"). The code
    # is stripped from the value even when an explicit percent tolerance was
    # already found ("100nF ±5% J"), since it is redundant; the tolerance is
    # only assigned from the code when nothing was recovered yet.
    if cleaned and _HAS_NUMBER_RE.search(cleaned) and _HAS_UNIT_RE.search(cleaned):
        m = _LETTER_RE.search(cleaned)
        if m:
            code = m.group(1)
            if code in _LETTER_CODES:
                cleaned = cleaned[: m.start()].rstrip()
                if not tolerance:
                    tolerance = _LETTER_CODES[code]

    # Notes tolerance (percent only), canonicalized the same way. Handles both
    # "Tolerance: 5%" and "1% tolerance" phrasings.
    if not tolerance and notes:
        nm = _NOTES_PERCENT_RE.search(str(notes)) or _NOTES_PERCENT_SUFFIX_RE.search(str(notes))
        if nm:
            tolerance = _normalize_tolerance(nm.group(1).strip())

    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip("( ")
    return cleaned, tolerance


def extract_tolerance_from_value(value: str) -> Tuple[str, str]:
    """Convenience wrapper that extracts tolerance from a value alone."""
    return extract_tolerance(value, "")