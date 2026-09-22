"""Package / case-size detection (cleaning stage 3).

When a BOM row does not carry an explicit package column, the footprint can
often be recovered from the component's value, description or notes:

* SMD chip case sizes: ``0402``, ``0603``, ``0805``, ``1206`` (EIA imperial)
  and their metric counterparts (``1608`` = 0603, ``2012`` = 0805, …);
* moulded / through-hole families: ``SOT-23``, ``SOIC-8``, ``QFN-16``,
  ``TO-92``, ``DIP-14`` and so on.

Detection is deliberately whitelist-based: a bare 4-digit token (e.g. a year
like ``2024``) is never reported unless it belongs to a known case code.
An already-populated ``package`` field is returned unchanged.
"""

import re
from typing import Optional

# SMD chip case sizes in EIA imperial notation. Values are stored as
# normalized 4-digit uppercase tokens.
_CHIP_SIZES = frozenset({
    "01005", "008004", "0201", "0402", "0603", "0612", "0805", "1005",
    "1020", "1111", "1206", "1210", "1506", "1806", "1812", "2009", "2010",
    "2512", "2920", "3225", "3925", "4508", "4525", "5025",
})

# Metric chip codes map to their EIA imperial canonical form.
_METRIC_TO_IMPERIAL = {
    "1608": "0603",
    "1005": "0402",
    "2012": "0805",
    "3216": "1206",
    "3225": "1210",
    "5025": "2010",
    "6332": "2512",
}

_FAMILY_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:SOT|SOIC|SOP|TSSOP|TSOP|MSOP|QFN|QFP|LQFP|TQFP|PQFP|DFN|WSON|BGA|CSP"
    r"|PLCC|LGA|DIP|SIP|SOD|SC|SMA|SMB|SMC|TO|DO|MELF|PTH)"
    r"-?\d{1,4}(?:-[A-Z0-9]+)?",
    re.IGNORECASE,
)
_CHIP_RE = re.compile(r"\b(?P<size>\d{4})\b")
# A 4-digit case code embedded in a part number (``RC0603FR``, ``C2012X``,
# ``CRCW1206-10K``). Only recognized when flanked on the left by a letter and
# not followed by another digit, so merged magnitude runs like
# ``CRCW040210K0FKED`` (0603 + "10") are never misread.
_MPN_CHIP_RE = re.compile(r"(?<=[A-Za-z])(?P<size>\d{4})(?![0-9])")


def _canonicalize_family(token: str) -> str:
    return token.upper()


def detect_package(value: str = "", description: str = "", notes: str = "",
                   mpn: str = "", package: str = "") -> Optional[str]:
    """Detect a package / case size for a BOM row.

    Args:
        value: Component value (e.g. ``"10kΩ 0603"``).
        description: Component description (e.g. ``"Chip resistor SMD 0805"``).
        notes: Free-form notes.
        mpn: Manufacturer part number (footprint codes are commonly embedded,
            e.g. ``RC0603FR-0710KL``).
        package: An already-resolved package field (returned unchanged when
            non-empty).

    Returns:
        The canonical package token (``"0603"``, ``"SOT-23"``, ``"SOIC-8"``…)
        or ``None`` when nothing was detected.
    """
    if package and str(package).strip():
        return str(package).strip()

    text = " ".join(filter(None, [
        str(value or ""), str(description or ""), str(notes or ""), str(mpn or ""),
    ]))
    if not text:
        return None

    # Family patterns take precedence (they are more specific) and may use all
    # fields.
    m = _FAMILY_RE.search(text)
    if m:
        return _canonicalize_family(m.group(0))

    # SMD chip sizes: full scan (imperial + metric mapping) over the structured
    # fields — value, description, manufacturer part number. Notes are excluded
    # from metric mapping because free-form prose is far too ambiguous ("lot
    # 2012 units" must never be read as an 0805 package); notes may only carry
    # an already-canonical EIA imperial code such as "0805" (common in exports).
    structured = " ".join(filter(None, [
        str(value or ""), str(description or ""), str(mpn or ""),
    ]))
    m = _CHIP_RE.search(structured)
    if m:
        size = m.group("size")
        if size in _CHIP_SIZES:
            return size
        if size in _METRIC_TO_IMPERIAL:
            return _METRIC_TO_IMPERIAL[size]

    # Notes: exact EIA imperial tokens only (never a metric code).
    m = _CHIP_RE.search(str(notes or ""))
    if m and m.group("size") in _CHIP_SIZES:
        return m.group("size")

    # Embedded case code in the manufacturer part number (conservative: only
    # the MPN, letter-flanked, not digit-continued).
    mpn_text = str(mpn or "")
    m = _MPN_CHIP_RE.search(mpn_text)
    if m:
        size = m.group("size")
        if size in _CHIP_SIZES:
            return size
        if size in _METRIC_TO_IMPERIAL:
            return _METRIC_TO_IMPERIAL[size]
    return None