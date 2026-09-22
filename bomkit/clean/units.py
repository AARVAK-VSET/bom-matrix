"""Value-unit canonicalization and SI conversion (cleaning stage 4).

Informal electrical units arrive in many spellings: ``µF``/``μF`` (both micro
signs), ``ohm``/``Ω``/``R``, ``uH`` vs ``µH``, digits separated from their unit
by a space (``10 uF``), and European decimal commas (``4,7k``).

This stage canonicalizes the *display* form of a value (single micro token
``u``, no digit-to-unit spaces, collapsed whitespace) and, when the value
contains an unambiguous unit, emits a deterministic SI conversion
(``value_si``) such as ``1e-05 F`` for ``10uF``.
"""

import re
from typing import Dict, List, Optional, Tuple

# Unify both micro signs to the ASCII micro token used elsewhere in the repo.
_MICRO_TRANSLATION = str.maketrans({"µ": "u", "μ": "u"})

# (explicit unit regex, base unit, factor multiplier) for unambiguous
# conversions. The bare-engineering forms (``10n``, ``100k``) are intentionally
# excluded because their dimension is ambiguous.
_SI_FAMILIES: List[Tuple[str, str, Dict[str, float]]] = [
    ("F", "F", {"pf": 1e-12, "nf": 1e-9, "uf": 1e-6, "mf": 1e-3, "f": 1.0}),
    ("Ω", "Ω", {"mΩ": 1e-3, "Ω": 1.0, "ohm": 1.0, "r": 1.0, "kΩ": 1e3,
                 "kohm": 1e3, "kr": 1e3, "MΩ": 1e6, "mohm": 1e6, "mr": 1e6}),
    ("H", "H", {"ph": 1e-12, "nh": 1e-9, "uh": 1e-6, "mh": 1e-3, "h": 1.0}),
    ("V", "V", {"mv": 1e-3, "v": 1.0, "kv": 1e3}),
    ("A", "A", {"ua": 1e-6, "ma": 1e-3, "a": 1.0}),
    ("W", "W", {"mw": 1e-3, "w": 1.0, "kw": 1e3}),
    ("Hz", "Hz", {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}),
    ("s", "s", {"us": 1e-6, "ms": 1e-3, "s": 1.0}),
]
# SI prefixes. Case matters: "M" is mega, "m" is milli, "K"/"k" kilo,
# "G"/"g" giga. Prefixes are kept case-sensitive so "1MΩ" (mega-ohm) is never
# folded onto milli-ohm.
_SI_PREFIXES: Dict[str, float] = {
    "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6,
    "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "g": 1e9, "G": 1e9, "T": 1e12,
}

# Base (multiplier-1.0) units per family, used for prefix resolution.
_BASE_LOOKUP: Dict[str, Tuple[str, float]] = {}
for _base, _si, _factors in _SI_FAMILIES:
    for _alias, _mult in _factors.items():
        if _mult == 1.0 and _alias not in _BASE_LOOKUP:
            _BASE_LOOKUP[_alias] = (_si, 1.0)

_VALUE_RE = re.compile(r"^([\d.,]+)\s*([a-zA-ZΩ]+)$")
# Resistor R-decimal notation ("0R1", "4R7", "1R5") where "R" is the
# decimal point in the ohm family. Only a single R is allowed.
_R_DECIMAL_RE = re.compile(r"(\d*)[Rr](\d*)")


def _resolve_unit(unit: str) -> Optional[Tuple[str, float]]:
    """Resolve a unit token to ``(si_unit, multiplier)``.

    The leading SI prefix is matched case-sensitively (``M`` = mega, ``m`` =
    milli), so ``"MΩ"`` never collides with ``"mΩ"``; the rest of the token is
    matched case-insensitively.
    """
    u = unit.replace("ω", "Ω")
    # Legacy "MF"/"MFD" (uppercase M + F) commonly denotes microfarads in
    # older BOMs; "mF" stays milli-farad.
    if u in ("MF", "MFD"):
        return "F", 1e-6
    if len(u) >= 2 and u[0] in _SI_PREFIXES and u[1].isalpha():
        prefix_mult = _SI_PREFIXES[u[0]]
        base = u[1:].lower().replace("ω", "Ω")
        if "µ" in base or "μ" in base:
            return None  # rarely reachable: canonical_value already maps micro->u
        entry = _BASE_LOOKUP.get(base)
        return None if entry is None else (entry[0], prefix_mult * entry[1])
    base = u.lower().replace("ω", "Ω")
    if "µ" in base or "μ" in base:
        return None
    return _BASE_LOOKUP.get(base)


def _replace_decimal_comma(value: str) -> str:
    """Replace a single digit-flanked comma (European decimal) with a period."""
    if value.count(",") != 1 or "." in value:
        return value
    idx = value.index(",")
    if idx == 0 or idx == len(value) - 1:
        return value
    if value[idx - 1].isdigit() and value[idx + 1].isdigit():
        return value[:idx] + "." + value[idx + 1:]
    return value


def canonical_value(value: str) -> str:
    """Produce a canonical display form for a component value.

    Unifies micro tokens (``µF``/``μF`` → ``uF``), removes the space between a
    magnitude and its unit (``10 uF`` → ``10uF``) and collapses whitespace.
    """
    if value is None:
        return ""
    s = str(value).translate(_MICRO_TRANSLATION)
    s = re.sub(r"(?<=[\dpnumkMGμµ])\s+(?=[pnumkMGμµ]?[A-Za-zΩ])", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def value_to_si(value: str) -> Optional[str]:
    """Convert an unambiguous value with unit to SI base units.

    Args:
        value: A cleaned value string (e.g. ``"10uF"``, ``"4.7kΩ"``, ``"100uH"``).

    Returns:
        A canonical SI string (e.g. ``"1e-05 F"``, ``"4700 Ω"``, ``"0.0001 H"``)
        or ``None`` when the value carries no convertible unit.
    """
    if not value:
        return None
    s = canonical_value(value)
    s = _replace_decimal_comma(s)
    # Resistor R-decimal notation: "0R1" -> 0.1 Ω, "4R7" -> 4.7 Ω.
    rm = _R_DECIMAL_RE.fullmatch(s)
    if rm and s.count("R") + s.count("r") == 1:
        whole, frac = rm.group(1) or "0", rm.group(2) or "0"
        magnitude = float(f"{whole}.{frac}") if rm.group(2) else float(whole)
        return None if magnitude == 0 else f"{magnitude:g} Ω"
    m = _VALUE_RE.match(s)
    if not m:
        return None
    try:
        magnitude = float(m.group(1))
    except ValueError:
        return None
    if magnitude == 0:
        return None
    resolved = _resolve_unit(m.group(2))
    if resolved is None:
        return None
    si_unit, factor = resolved
    return f"{magnitude * factor:g} {si_unit}"


def canonical_uom(unit: str) -> str:
    """Canonicalize a unit-of-measure token (lowercase, synonym unify)."""
    if unit is None:
        return ""
    u = str(unit).strip().lower()
    synonyms = {
        "pc": "pcs",
        "piece": "pieces",
    }
    return synonyms.get(u, u)