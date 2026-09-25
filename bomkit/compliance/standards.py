"""
Environmental compliance screening standards and substance threshold limits.

Defines regulatory screening limits for:
1. RoHS 3 (Directive 2011/65/EU as amended by 2015/863): Maximum concentration
   values tolerated by weight in homogeneous materials (Annex II).
2. REACH (Regulation (EC) No 1907/2006): Screening thresholds for Substances of
   Very High Concern (SVHC) on the Candidate List (0.1% w/w per Article 33).

Note:
    These rules represent automated screening thresholds for BOM review and
    comparison under Issue #26. They evaluate configured substances against
    screening limits (RoHS Annex II MCVs & REACH Article 33 SVHC 0.1% w/w threshold).
    They do not constitute a full legal compliance or context-dependent Annex XVII
    determination engine.
"""

from typing import Dict, Optional

# RoHS 3 maximum concentration values in homogeneous materials (wt %)
# Reference: Directive 2011/65/EU Annex II
ROHS_THRESHOLDS: Dict[str, float] = {
    # Heavy metals
    "pb": 0.1,
    "lead": 0.1,
    "hg": 0.1,
    "mercury": 0.1,
    "cd": 0.01,  # Cadmium limit is strictly 0.01% (100 ppm)
    "cadmium": 0.01,
    "cr6+": 0.1,
    "cr(vi)": 0.1,
    "hexavalent chromium": 0.1,
    # Flame retardants
    "pbb": 0.1,
    "pbde": 0.1,
    # Phthalates (RoHS 3 amendment 2015/863)
    "dehp": 0.1,
    "bbp": 0.1,
    "dbp": 0.1,
    "dibp": 0.1,
}

# Standard screening threshold for Candidate List SVHCs under REACH Article 33 (% w/w)
REACH_SVHC_THRESHOLD: float = 0.1

# Project screening registry for known SVHCs screened in electrical/electronic assemblies.
# This is intentionally not represented as the complete ECHA Candidate List.
# Production deployments should synchronize this registry with the current ECHA Candidate List.
REACH_SVHC_SCREENING_REGISTRY: Dict[str, float] = {
    "anthracene": REACH_SVHC_THRESHOLD,
    "4,4'-diaminodiphenylmethane": REACH_SVHC_THRESHOLD,
    "dibutyl phthalate": REACH_SVHC_THRESHOLD,
    "dbp": REACH_SVHC_THRESHOLD,
    "benzyl butyl phthalate": REACH_SVHC_THRESHOLD,
    "bbp": REACH_SVHC_THRESHOLD,
    "bis(2-ethylhexyl)phthalate": REACH_SVHC_THRESHOLD,
    "dehp": REACH_SVHC_THRESHOLD,
    "diisobutyl phthalate": REACH_SVHC_THRESHOLD,
    "dibp": REACH_SVHC_THRESHOLD,
    "lead": REACH_SVHC_THRESHOLD,
    "pb": REACH_SVHC_THRESHOLD,
    "cadmium": REACH_SVHC_THRESHOLD,
    "cd": REACH_SVHC_THRESHOLD,
    "cadmium oxide": REACH_SVHC_THRESHOLD,
    "lead monoxide": REACH_SVHC_THRESHOLD,
    "trilead dioxide phosphonate": REACH_SVHC_THRESHOLD,
    "boric acid": REACH_SVHC_THRESHOLD,
    "disodium tetraborate": REACH_SVHC_THRESHOLD,
}


def get_substance_threshold(
    substance: str,
    standard: str = "RoHS",
    custom_thresholds: Optional[Dict[str, float]] = None,
) -> Optional[float]:
    """
    Get the screening threshold percentage for a substance under RoHS or REACH.

    Args:
        substance: Chemical symbol or substance name (e.g. 'Pb', 'Anthracene').
        standard: Standard name ('RoHS' [default] or 'REACH').
        custom_thresholds: Optional dictionary of substance -> threshold mappings.

    Returns:
        Threshold limit as float percentage, or None if substance is unregulated.
    """
    if not substance or not isinstance(substance, str):
        return None

    key = substance.strip().lower()

    if custom_thresholds:
        for k, v in custom_thresholds.items():
            if k.strip().lower() == key:
                return float(v)

    std = (standard or "RoHS").strip().upper()
    if std == "ROHS":
        return ROHS_THRESHOLDS.get(key)
    elif std == "REACH":
        return REACH_SVHC_SCREENING_REGISTRY.get(key)

    return None
