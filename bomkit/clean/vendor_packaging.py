"""Vendor packaging-code stripping (cleaning stage 1).

Distributors routinely append packaging codes to an otherwise canonical
manufacturer part number: ``-CT`` (cut tape), ``-TR`` (tape & reel),
``-ND`` / ``-DKR`` (Digi-Key), ``-TB`` (tube), ``-BK`` (bulk), plus free-text
markers such as ``TAPE & REEL`` or ``16K/REEL``.

This stage separates those codes from the manufacturer part number and
records the packaging form as canonical metadata (``packaging`` and, when a
quantity hint is present, ``packaging_qty``).

Only known, end-anchored markers are stripped, and a marker must be preceded
by a separator (``- _ / ( , [ <`` or whitespace) so legitimate part-number
fragments are never damaged. A whitelist approach keeps the behaviour
deterministic and auditable; the industry-standard ambiguity (a part that
genuinely ends in ``-TR``) is resolved in favour of clean packaging metadata,
which is what BOM procurement tooling expects.
"""

import re
from typing import Optional, Tuple

# Canonical packaging forms produced by the cleaner.
_PACKAGING_REEL = "reel"
_PACKAGING_TAPE_AND_REEL = "tape_and_reel"
_PACKAGING_CUT_TAPE = "cut_tape"
_PACKAGING_TUBE = "tube"
_PACKAGING_BULK = "bulk"

# Ordered rules. Each rule is a tuple ``(regex, packaging, qty_multiplier)``.
# The regex is always end-anchored and may expose a named ``qty`` group.
# ``qty_multiplier`` is applied when a ``qty`` group is captured (e.g. ``1000``
# turns ``16K/REEL`` into 16000). ``packaging`` is ``None`` for rules that only
# carry a quantity hint and derive their packaging from the marker keywords.
_PACKAGING_PATTERN = re.compile(r"(?:^|[-_/ (,.<>])")
_PACKAGING_RULES = [
    # Distributor suffix codes (with optional leading separator / parentheses).
    (re.compile(r"(?:^|[-_/ (,.<>])-?\s*(?:t&r|tr\d{0,2})\s*\)*\s*$", re.IGNORECASE), _PACKAGING_TAPE_AND_REEL, None),
    (re.compile(r"(?:^|[-_/ (,.<>])-?\s*ct\s*\)*\s*$", re.IGNORECASE), _PACKAGING_CUT_TAPE, None),
    (re.compile(r"(?:^|[-_/ (,.<>])-?\s*(?:nd|dkgr?|rl)\s*\)*\s*$", re.IGNORECASE), _PACKAGING_REEL, None),
    (re.compile(r"(?:^|[-_/ (,.<>])-?\s*tb\s*\)*\s*$", re.IGNORECASE), _PACKAGING_TUBE, None),
    (re.compile(r"(?:^|[-_/ (,.<>])-?\s*(?:bk|cp)\s*\)*\s*$", re.IGNORECASE), _PACKAGING_BULK, None),
    # Quantity-annotated markers: "<nn>K/REEL", "<nnnn>/REEL", "REEL OF <nnnn>".
    (re.compile(r"(?:^|[-_/ (,.<>])(?P<qty>\d{1,3})\s*k\s*/\s*(?:reel|rl|ct|tape)\s*\)*\s*$", re.IGNORECASE), None, 1000),
    (re.compile(r"(?:^|[-_/ (,.<>])(?P<qty>\d{3,6})\s*/\s*(?:reel|rl|ct)\s*\)*\s*$", re.IGNORECASE), None, 1),
    (re.compile(r"(?:^|[-_/ (,.<>])reel\s*(?:of\s+)?(?P<qty>\d{3,6})\s*\)*\s*$", re.IGNORECASE), _PACKAGING_REEL, 1),
    # Free-text markers.
    (re.compile(r"(?:^|[-_/ (,.<>])cut[\s-]?tape\s*\)*\s*$", re.IGNORECASE), _PACKAGING_CUT_TAPE, None),
    (re.compile(r"(?:^|[-_/ (,.<>])tape[\s-]*(?:&|and)[\s-]*reel\s*\)*\s*$", re.IGNORECASE), _PACKAGING_TAPE_AND_REEL, None),
    (re.compile(r"(?:^|[-_/ (,.<>])(?:t&r|reel)\s*\)*\s*$", re.IGNORECASE), _PACKAGING_REEL, None),
    (re.compile(r"(?:^|[-_/ (,.<>])tube\s*\)*\s*$", re.IGNORECASE), _PACKAGING_TUBE, None),
    (re.compile(r"(?:^|[-_/ (,.<>])bulk\s*\)*\s*$", re.IGNORECASE), _PACKAGING_BULK, None),
]


# Appended distributor codes without a separator (``UVZ1E100MDD1TB``, where
# Digi-Key tacks the code straight onto the manufacturer number). Only
# recognized when the code directly follows a digit and that digit follows a
# letter, so real part-number fragments ending in digits (``STM32F103C8T6``)
# are never damaged.
_APPENDED_PATTERN = re.compile(
    r"(?<=[A-Za-z]\d)(?P<code>t&r|tr\d{0,2}|ct|tb|dkgr?|nd|rl)\s*\)*\s*$",
    re.IGNORECASE,
)
_APPENDED_PACKAGING = {
    "t&r": _PACKAGING_TAPE_AND_REEL, "tr": _PACKAGING_TAPE_AND_REEL,
    "ct": _PACKAGING_CUT_TAPE, "tb": _PACKAGING_TUBE,
    "dkgr": _PACKAGING_REEL, "dkg": _PACKAGING_REEL,
    "nd": _PACKAGING_REEL, "rl": _PACKAGING_REEL,
}


def _matches(text: str) -> Optional[Tuple[int, int, Optional[str], Optional[str], Optional[int]]]:
    """Apply the packaging rules and return (:match start, :match end,
    :packaging, :qty-marker, :qty).

    The rule that strips the longest tail wins so that quantity-annotated
    markers (e.g. ``16K/REEL``) take priority over the bare ``REEL`` marker.
    """
    best = None  # (start, end, packaging, qty)
    for regex, packaging, qty_multiplier in _PACKAGING_RULES:
        m = regex.search(text)
        if not m:
            continue
        qty = None
        if "qty" in regex.groupindex and m.groupdict().get("qty"):
            qty = int(m.group("qty"))
            if qty_multiplier:
                qty = qty * qty_multiplier
        if best is None or (m.end() - m.start()) > (best[1] - best[0]):
            best = (m.start(), m.end(), packaging, qty)

    # Appended code (no separator) only kicks in when no explicit marker won.
    if best is None:
        m = _APPENDED_PATTERN.search(text)
        if m:
            code = m.group("code").lower()
            packaging = _APPENDED_PACKAGING.get(code, _PACKAGING_REEL)
            best = (m.start(), m.end(), packaging, None)
    return best


def _strip(text: str) -> Tuple[str, Optional[str], Optional[int]]:
    """Strip a packaging marker from the tail of ``text``."""
    if not text:
        return text, None, None
    match = _matches(text)
    if match is None:
        # No packaging marker: collapse whitespace only, never mutate the
        # remaining characters (the docstring contract is "unchanged when
        # nothing matched").
        cleaned = re.sub(r"\s+", " ", text).strip()
        return cleaned, None, None

    start, _, packaging, qty = match
    cleaned = text[:start]
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(" (_,./;-")

    if packaging is not None:
        return cleaned, packaging, qty

    # Quantity-annotated-only rule: derive packaging from the marker keyword
    # present in the removed tail.
    tail = text[start:].lower()
    if "ct" in tail:
        packaging = _PACKAGING_CUT_TAPE
    elif "tape" in tail or "tr" in tail:
        packaging = _PACKAGING_TAPE_AND_REEL
    else:
        packaging = _PACKAGING_REEL
    return cleaned, packaging, qty


def strip_vendor_packaging(text: str) -> Tuple[str, Optional[str], Optional[int]]:
    """Clean a manufacturer part number by removing trailing vendor packaging
    codes.

    Args:
        text: The raw manufacturer part number (may include a packaging suffix).

    Returns:
        A tuple of ``(cleaned_mpn, packaging, packaging_qty)``:

        * ``cleaned_mpn``: the part number with the packaging marker removed
          and internal whitespace collapsed (unchanged when nothing matched);
        * ``packaging``: one of ``reel``, ``tape_and_reel``, ``cut_tape``,
          ``tube``, ``bulk`` or ``None`` when no packaging marker was found;
        * ``packaging_qty``: an integer quantity hint (e.g. ``16000`` from
          ``16K/REEL``) or ``None``.

    Examples:
        ``strip_vendor_packaging("RC0603FR-0710KL-TR") -> ("RC0603FR-0710KL", "tape_and_reel", None)``
        ``strip_vendor_packaging("GRM188R71C104KA01D-CT") -> ("GRM188R71C104KA01D", "cut_tape", None)``
        ``strip_vendor_packaging("C0603X104K3RAC7867 (Cut Tape)") -> ("C0603X104K3RAC7867", "cut_tape", None)``
        ``strip_vendor_packaging("VJ0805Y104KXATW1BC 16K/REEL") -> ("VJ0805Y104KXATW1BC", "tape_and_reel", 16000)``
    """
    if text is None:
        return "", None, None
    value = str(text).strip()
    if not value:
        return value, None, None
    return _strip(value)


def packaging_from_text(text: str) -> Tuple[Optional[str], Optional[int]]:
    """Return packaging metadata for a free-text fragment (used on value tails).

    Behaves like :func:`strip_vendor_packaging` but returns only the metadata.
    """
    _, packaging, qty = strip_vendor_packaging(text)
    return packaging, qty


def mpn_key(mpn: str) -> str:
    """Return a fuzzy key for comparing part numbers across listings.

    Uppercases the part number, removes vendor packaging suffixes and drops
    every non-alphanumeric character, so ``"rc0805fr-07 10kL-tr"`` (listing A,
    tape & reel) compares equal to ``"RC0805FR-0710KL"`` (listing B) and to
    ``"RC0805FR 0710KL"`` (listing C). Separator flakiness and distributor
    suffixes are the primary sources of near-duplicate lines in exported BOMs.
    """
    if mpn is None:
        return ""
    cleaned, _, _ = strip_vendor_packaging(str(mpn))
    return re.sub(r"[^A-Z0-9]", "", cleaned.upper())