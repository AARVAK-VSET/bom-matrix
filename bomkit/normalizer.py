from typing import List, Dict, Any, Optional, Tuple
import difflib
import re

from .column_profiler import ColumnProfiler
from .lexical_similarity import LexicalSimilarity
from .schema import STANDARD_HEADERS, COLUMN_MAPPINGS, CANONICAL_FIELDS

# Weights applied to the header lexical score and the content value-profile
# score when both signals are available. Each contributes up to its weight;
# the combined confidence is capped at 1.0 so a strong header and strong
# content corroborate each other.
NAME_WEIGHT = 0.6
CONTENT_WEIGHT = 0.6

# Headers whose lexical score is below this are treated as empty or
# obfuscated; for such headers the content value profile governs because
# blending a weak name score would only dilute strong content evidence.
UNINFORMATIVE_HEADER_SCORE = 0.5

# Minimum composite confidence required to classify a column.
CLASSIFICATION_THRESHOLD = 0.85

# Short role labels returned alongside the canonical field ids.
_ROLE_LABELS = {
    "manufacturer_part_number": "mpn",
}

# Structured value patterns that a permissive MPN regex would otherwise
# mistake for part numbers: package footprints, dates, phone numbers and
# pure hex codes. Used to guard the content value-profile, not the header
# lexical scoring.
_FOOTPRINT_PATTERN = re.compile(
    r"^(?:\d{4}|(?:SOT|DIP|SOP|SOIC|QFN|QFP|LQFP|TSSOP|TSOP|SOD|TO|BGA|CSP|PLCC|TQFP|DFN|MSOP|WSON|PQFP|LFPAK)[- ]\d{1,3}[A-Z0-9-]*)$",
    re.IGNORECASE,
)
_DATE_PATTERN = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$")
_PHONE_PATTERN = re.compile(r"^\+?\d[\d\s.()\-]{5,17}\d$")
_HEX_PATTERN = re.compile(r"^[0-9A-Fa-f]{6}$")

# Common manufacturer or distributor names used to recognise vendor columns
# from content alone. Deliberately long/distinctive tokens so ordinary
# description prose does not collide with them.
_VENDOR_TOKENS = (
    "texas instruments", "stmicroelectronics", "analog devices", "microchip",
    "infineon", "nxp", "vishay", "rohm", "murata", "panasonic", "renesas",
    "on semiconductor", "onsemi", "toshiba", "fairchild", "maxim", "littelfuse",
    "wurth", "kemet", "tdk", "yageo", "avx", "nichicon", "epcos",
    "te connectivity", "amphenol", "molex", "harting", "phoenix contact",
    "omron", "schneider", "siemens", "samsung", "skyworks", "qorvo",
    "broadcom", "qualcomm", "digi-key", "mouser", "arrow", "avnet",
    "rs components", "farnell", "newark", "conrad", "anglia", "element14",
)


class BomNormalizer:
    """Normalizer for standardizing Bill of Materials data.

    Maps various column name variations to a standard BOM template
    and normalizes the data structure. When enabled, uses column
    profiling to disambiguate ambiguous headers and infer mappings.
    """

    def __init__(self, use_column_profiling: bool = True):
        """Initialize the normalizer with column mappings.

        Args:
            use_column_profiling: If True, use data profiling to improve
                column mapping and disambiguation (default: True).
        """
        self.use_column_profiling = use_column_profiling
        self._lexical = LexicalSimilarity()

        # Create reverse lookup: normalized column name -> list of variations
        self._normalized_to_variations = {}
        for standard, variations in COLUMN_MAPPINGS.items():
            self._normalized_to_variations[standard] = variations

        # Create forward lookup: variation -> standard column name
        self._variation_to_standard = {}
        for standard, variations in COLUMN_MAPPINGS.items():
            for variation in variations:
                self._variation_to_standard[variation.lower()] = standard

        # Precompute canonical aliases for similarity scoring
        self._canonical_aliases = {}
        for field in CANONICAL_FIELDS:
            field_id = field["id"]
            aliases = field.get("aliases", [])
            label = field.get("label")
            if label:
                aliases = aliases + [label]
            normalized_aliases = [self._normalize_header_text(a) for a in aliases]
            self._canonical_aliases[field_id] = normalized_aliases

    def get_standard_template(self) -> List[str]:
        """Get the standard BOM template headers.

        Returns:
            List of standard header names in order
        """
        return STANDARD_HEADERS.copy()

    def _normalize_header_text(self, text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r'[\s_\-]+', ' ', text)
        text = re.sub(r'[^\w\s]', '', text)
        return text

    def normalize_column_name(self, column_name: str) -> Optional[str]:
        """Normalize a column name to the standard header.

        Args:
            column_name: The original column name from the BOM

        Returns:
            Standard column name if a match is found, None otherwise
        """
        if not column_name:
            return None

        # Normalize the input: lowercase, strip whitespace, replace underscores/spaces
        normalized_input = re.sub(r'[\s_\-]+', ' ', column_name.lower().strip())
        canonical_input = self._normalize_header_text(column_name)

        # Special-case: "part number" should map to part_number (not MPN)
        if canonical_input in {"part number", "part no", "part #", "partnumber", "item number", "item no", "item #", "itemnumber"}:
            return "part_number"

        # Direct lookup
        if normalized_input in self._variation_to_standard:
            return self._variation_to_standard[normalized_input]

        # Try exact match after normalization
        for variation, standard in self._variation_to_standard.items():
            if normalized_input == variation:
                return standard

        # Try partial matching (contains)
        for variation, standard in self._variation_to_standard.items():
            if variation in normalized_input or normalized_input in variation:
                return standard

        return None

    def _name_similarity(self, column_name: str, aliases: List[str]) -> float:
        if not aliases:
            return 0.0
        normalized = self._normalize_header_text(column_name)
        ratios = []
        for alias in aliases:
            if not alias:
                continue
            ratios.append(difflib.SequenceMatcher(None, normalized, alias).ratio())
            ratios.append(self._lexical.calculate_similarity(column_name, alias))
        return max(ratios) if ratios else 0.0

    def _sample_values(self, values: List[Any], max_samples: int = 200) -> List[str]:
        samples = []
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            samples.append(text)
            if len(samples) >= max_samples:
                break
        return samples

    def _integer_ratio(self, values: List[str]) -> float:
        if not values:
            return 0.0
        count = 0
        for value in values:
            if re.fullmatch(r'[+-]?\d+', value):
                count += 1
        return count / len(values)

    def _ratio_in_set(self, values: List[str], allowed: set) -> float:
        if not values:
            return 0.0
        count = 0
        for value in values:
            if value.lower() in allowed:
                count += 1
        return count / len(values)

    def _score_column_for_field(
        self,
        column_name: str,
        profile: Dict[str, Any],
        samples: List[str],
        field_id: str,
        name_based: Optional[str]
    ) -> float:
        score = 0.0
        col_lower = column_name.lower()
        if name_based == field_id:
            score += 1.0

        score += 0.5 * self._name_similarity(column_name, self._canonical_aliases.get(field_id, []))

        type_dist = profile.get('type_distribution', {})
        regex_hits = profile.get('regex_hits', {})
        unit_presence = profile.get('unit_presence', {})
        length_stats = profile.get('length_stats', {})
        char_stats = profile.get('character_class_stats', {})
        cardinality = profile.get('cardinality', {})

        numeric_ratio = type_dist.get('numeric', 0.0)
        text_ratio = type_dist.get('text', 0.0)
        ref_like = regex_hits.get('ref_des_like', 0.0)
        mpn_like = regex_hits.get('mpn_like', 0.0)
        whitespace_pct = char_stats.get('percent_whitespace', 0.0)
        letters_pct = char_stats.get('percent_letters', 0.0)
        unique_ratio = cardinality.get('unique_ratio', 0.0)

        if field_id == "reference_designator":
            if ref_like >= 0.6:
                score += 1.0
            if ref_like >= 0.3:
                score += 0.4

        if field_id == "quantity":
            if numeric_ratio >= 0.9 and self._integer_ratio(samples) >= 0.9:
                score += 0.9
            if numeric_ratio >= 0.7 and letters_pct < 5:
                score += 0.4

        if field_id == "manufacturer_part_number":
            if any(key in col_lower for key in ["mfg", "mfr", "manufacturer", "supplier", "vendor", "mpn"]):
                score += 0.6
            if "part number" in self._normalize_header_text(column_name) and not any(
                key in col_lower for key in ["mfg", "mfr", "manufacturer", "supplier", "vendor", "mpn"]
            ):
                score -= 0.6
            if mpn_like >= 0.6:
                score += 0.8
            if mpn_like >= 0.3:
                score += 0.3
            if unique_ratio < 0.2:
                score -= 0.6
            if numeric_ratio > 0.8:
                score -= 1.0

        if field_id == "value":
            if unit_presence:
                score += 0.6
            if unit_presence and text_ratio >= 0.6:
                score += 0.3

        if field_id == "unit":
            unit_ratio = self._ratio_in_set(
                samples,
                {"ea", "each", "pcs", "pc", "pieces", "piece", "unit", "units", "kit"}
            )
            if unit_ratio >= 0.6:
                score += 0.8
            elif unit_ratio >= 0.3:
                score += 0.3

        if field_id == "package":
            if "footprint" in column_name.lower() or "package" in column_name.lower():
                score += 0.6

        if field_id == "manufacturer":
            if any(key in col_lower for key in ["supplier", "vendor", "distributor"]):
                score -= 0.5
            if any(key in col_lower for key in ["manufacturer", "mfg", "mfr", "maker", "brand"]):
                score += 0.7
            if text_ratio >= 0.9 and 4 <= length_stats.get('mean', 0) <= 30 and whitespace_pct > 5:
                score += 0.4

        if field_id == "supplier":
            if any(key in col_lower for key in ["supplier", "vendor", "distributor", "approved supplier", "preferred supplier"]):
                score += 0.8
            if any(key in col_lower for key in ["manufacturer", "mfg", "mfr", "maker", "brand"]):
                score -= 0.4
            if text_ratio >= 0.9 and 4 <= length_stats.get('mean', 0) <= 30 and whitespace_pct > 5:
                score += 0.4

        if field_id == "description":
            if text_ratio >= 0.9 and length_stats.get('mean', 0) >= 12 and whitespace_pct > 10:
                score += 0.5

        if field_id == "part_number":
            if "part number" in self._normalize_header_text(column_name) or "item number" in self._normalize_header_text(column_name):
                score += 0.6
            if any(key in col_lower for key in ["mfg", "mfr", "manufacturer", "supplier", "vendor", "mpn"]):
                score -= 0.6
            if unique_ratio < 0.2:
                score -= 0.6
            if text_ratio >= 0.8 and whitespace_pct < 5 and 2 <= length_stats.get('mean', 0) <= 40:
                score += 0.5
            if mpn_like >= 0.6:
                score -= 0.2
            if numeric_ratio >= 0.8:
                score -= 0.4

        if field_id == "notes":
            if any(key in col_lower for key in ["make/buy", "make", "buy", "revision", "rev", "lead time", "lifecycle", "unit cost", "extended cost"]):
                score += 0.6
        if field_id == "value":
            if any(key in col_lower for key in ["revision", "rev"]):
                score -= 0.6

        authoritative_abbreviations = {
            "qty": "quantity",
            "desc": "description",
            "mfr pn": "manufacturer_part_number",
            "mpn": "manufacturer_part_number",
            "ref": "reference_designator",
            "value": "value",
            "designator": "reference_designator"
        }
        normalized_col = self._normalize_header_text(column_name)
        if authoritative_abbreviations.get(normalized_col) == field_id:
            score = max(score, 0.95)

        return score

    def _name_score(self, column_name: str, field_id: str, name_based: Optional[str]) -> float:
        """Score how well a column header lexically matches a canonical field.

        Returns:
            Normalized header score in [0, 1].
        """
        if name_based == field_id:
            return 1.0
        text = str(column_name) if column_name is not None else ""
        if not text.strip():
            return 0.0
        return min(1.0, self._name_similarity(text, self._canonical_aliases.get(field_id, [])))

    def _content_is_structured_non_part_number(self, samples: List[str]) -> bool:
        """Whether cells look like structured data, not part numbers.

        Footprints (``0805``, ``SOIC-8``), dates (``2024-01-01``), phone
        numbers (``555-123-4567``) and hex codes (``FF0000``) all satisfy the
        permissive MPN regex; this guard suppresses the MPN content tier for
        columns dominated by them so they are never labelled as MPNs.
        """
        if not samples:
            return False
        n = float(len(samples))
        structured = 0
        for value in samples:
            text = str(value).strip()
            if _DATE_PATTERN.match(text) or _PHONE_PATTERN.match(text):
                structured += 1
            elif _FOOTPRINT_PATTERN.match(text) or _HEX_PATTERN.match(text):
                structured += 1
        return structured / n >= 0.5

    def _content_is_vendor_names(self, samples: List[str]) -> bool:
        """Whether most cells are known vendor (manufacturer/supplier) names.

        Used to give vendor columns a decisive content signal and keep
        description prose from swallowing them.
        """
        if not samples:
            return False
        n = float(len(samples))
        hits = 0
        for value in samples:
            text = str(value).lower()
            if any(token in text for token in _VENDOR_TOKENS):
                hits += 1
        return hits / n >= 0.6

    def _content_score(
        self,
        profile: Dict[str, Any],
        samples: List[str],
        column_name: str,
        field_id: str
    ) -> float:
        """Score how well column cell values match a canonical field.

        Uses the statistical profile produced by :class:`ColumnProfiler`
        (cell data type distribution, regex pattern hits, unit presence,
        cardinality, length and character-class statistics) to score the
        column content independent of its header.

        Returns:
            Normalized content value-profile score in [0, 1].
        """
        if not samples or not profile or 'error' in profile:
            return 0.0

        type_dist = profile.get('type_distribution', {})
        regex_hits = profile.get('regex_hits', {})
        unit_presence = profile.get('unit_presence', {})
        length_stats = profile.get('length_stats', {})
        char_stats = profile.get('character_class_stats', {})
        cardinality = profile.get('cardinality', {})

        numeric_ratio = type_dist.get('numeric', 0.0)
        text_ratio = type_dist.get('text', 0.0)
        ref_like = regex_hits.get('ref_des_like', 0.0)
        mpn_like = regex_hits.get('mpn_like', 0.0)
        whitespace_pct = char_stats.get('percent_whitespace', 0.0)
        letters_pct = char_stats.get('percent_letters', 0.0)
        unique_ratio = cardinality.get('unique_ratio', 0.0)
        mean_len = length_stats.get('mean', 0.0)

        if field_id == "reference_designator":
            if ref_like >= 0.6:
                return 1.0
            if ref_like >= 0.3:
                return 0.5
            return 0.0

        if field_id == "quantity":
            if numeric_ratio >= 0.9 and self._integer_ratio(samples) >= 0.9:
                return 1.0
            if numeric_ratio >= 0.7 and letters_pct < 5:
                return 0.6
            return 0.0

        if field_id == "manufacturer_part_number":
            if numeric_ratio >= 0.8:
                return 0.0
            if self._content_is_structured_non_part_number(samples):
                return 0.0
            if mpn_like >= 0.8 and unique_ratio >= 0.2 and mean_len >= 5 and ref_like < 0.3:
                return 1.0
            if mpn_like >= 0.6 and unique_ratio >= 0.2 and mean_len >= 5 and ref_like < 0.3:
                return 0.85
            if mpn_like >= 0.3 and mean_len >= 5:
                return 0.5
            return 0.0

        if field_id == "value":
            if unit_presence and text_ratio >= 0.6:
                return 0.8
            if unit_presence:
                return 0.5
            return 0.0

        if field_id == "unit":
            unit_ratio = self._ratio_in_set(
                samples,
                {"ea", "each", "pcs", "pc", "pieces", "piece", "unit", "units", "kit"}
            )
            if unit_ratio >= 0.6:
                return 1.0
            if unit_ratio >= 0.3:
                return 0.5
            return 0.0

        if field_id in ("manufacturer", "supplier"):
            if self._content_is_vendor_names(samples):
                return 1.0
            if text_ratio >= 0.9 and 4 <= mean_len <= 30 and whitespace_pct > 2:
                return 0.9
            if text_ratio >= 0.9 and 4 <= mean_len <= 30:
                return 0.5
            return 0.0

        if field_id == "part_number":
            if numeric_ratio >= 0.8:
                return 0.0
            if text_ratio >= 0.8 and 2 <= mean_len <= 40 and whitespace_pct < 5 and unique_ratio >= 0.2:
                return 0.5
            return 0.0

        if field_id == "description":
            if text_ratio >= 0.9 and self._content_is_structured_non_part_number(samples):
                return 0.0
            if text_ratio >= 0.9 and self._content_is_vendor_names(samples):
                return 0.0
            if text_ratio >= 0.9 and mean_len >= 12:
                return 1.0
            if text_ratio >= 0.9 and mean_len >= 8:
                return 0.85
            return 0.0

        if field_id == "package":
            if text_ratio >= 0.9 and 2 <= mean_len <= 40 and whitespace_pct < 10:
                return 0.4
            return 0.0

        if field_id == "notes":
            if text_ratio >= 0.9 and mean_len >= 15 and whitespace_pct > 8:
                return 0.6
            if text_ratio >= 0.9:
                return 0.3
            return 0.0

        return 0.0

    def _composite_confidence(self, name_score: float, content_score: float) -> float:
        """Combine the header lexical score and the content value-profile score.

        The two signals are blended using their weights, capped at 1.0. The
        content value profile is never allowed to lower an otherwise strong
        signal: when the header is empty or obfuscated, or the blend would
        dilute the content-only evidence, the stronger of the two governs.
        Keeping the content score as a floor makes the composite monotone in
        both inputs and removes the float matching instability that otherwise
        appears at the informative-header boundary.

        Returns:
            Weighted composite confidence in [0, 1].
        """
        blend = NAME_WEIGHT * name_score + CONTENT_WEIGHT * content_score
        return min(1.0, max(blend, content_score))

    def classify_column(self, column_name: Optional[str], values: List[Any]) -> Dict[str, Any]:
        """Classify a column from its header and its cell values.

        Combines the header's lexical similarity score with a content value
        profile (cell data types, regex patterns, unit presence) into a
        weighted composite confidence in [0, 1]. Columns whose header is
        empty or obfuscated fall back to the content value profile alone.

        Args:
            column_name: The column header (may be empty or None for missing
                headers)
            values: Cell values for the column

        Returns:
            A dictionary with:
                role: short role label (e.g. 'mpn' for the manufacturer part
                    number field), or None when confidence is below the
                    0.85 classification threshold
                role_id: canonical field id from ``STANDARD_HEADERS``
                confidence: weighted composite confidence in [0, 1]
                name_score: header lexical score in [0, 1]
                content_score: content value-profile score in [0, 1]
        """
        values = list(values) if values is not None else []
        name = str(column_name) if column_name is not None else ""
        samples = self._sample_values(values)
        profile = ColumnProfiler().profile_column(name, values)
        name_based = self.normalize_column_name(name) if name.strip() else None

        best = None
        for field_id in STANDARD_HEADERS:
            name_score = self._name_score(name, field_id, name_based)
            content_score = self._content_score(profile, samples, name, field_id)
            confidence = self._composite_confidence(name_score, content_score)
            if best is None or confidence > best["confidence"]:
                best = {
                    "role_id": field_id,
                    "confidence": confidence,
                    "name_score": name_score,
                    "content_score": content_score,
                }

        result = dict(best)
        if best["confidence"] >= CLASSIFICATION_THRESHOLD:
            result["role"] = _ROLE_LABELS.get(best["role_id"], best["role_id"])
        else:
            result["role"] = None
        return result

    def classify_columns(self, raw_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Classify every column in a table of raw rows.

        Args:
            raw_rows: List of dictionaries representing rows

        Returns:
            Mapping of column name to its classification result from
            :meth:`classify_column`.
        """
        if not raw_rows:
            return {}

        columns = list(raw_rows[0].keys())
        for row in raw_rows[1:]:
            for col in row.keys():
                if col not in columns:
                    columns.append(col)

        results = {}
        for col in columns:
            values = [row.get(col) for row in raw_rows]
            results[col] = self.classify_column(col, values)
        return results

    def infer_column_mapping(self, raw_rows: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
        """Infer a column mapping from raw rows to standard headers."""
        if not raw_rows:
            return {}

        # Preserve column order from the first row
        columns = list(raw_rows[0].keys())
        for row in raw_rows[1:]:
            for col in row.keys():
                if col not in columns:
                    columns.append(col)

        values_by_column = {col: [row.get(col) for row in raw_rows] for col in columns}

        profiles = {}
        if self.use_column_profiling:
            profiler = ColumnProfiler()
            profiles = profiler.profile_dataframe(raw_rows)

        candidates: Dict[str, Tuple[Optional[str], float]] = {}
        for col in columns:
            name_based = self.normalize_column_name(str(col)) if col is not None else None
            profile = profiles.get(col, {})
            samples = self._sample_values(values_by_column.get(col, []))

            best_field = None
            best_score = 0.0
            for field_id in STANDARD_HEADERS:
                score = self._score_column_for_field(str(col), profile, samples, field_id, name_based)
                if score > best_score:
                    best_score = score
                    best_field = field_id

            if best_score >= 0.6:
                candidates[col] = (best_field, best_score)
            else:
                candidates[col] = (None, best_score)

            # Fall back to content value profiling when the header alone
            # could not identify a field (empty, cryptic or obfuscated).
            if best_field is None:
                classification = self.classify_column(str(col), values_by_column.get(col, []))
                if classification["role"] is not None:
                    best_field = classification["role_id"]
                    best_score = max(best_score, classification["confidence"])
                    candidates[col] = (best_field, best_score)

        # Resolve conflicts: keep best scoring column for each field
        assigned: Dict[str, str] = {}
        assigned_scores: Dict[str, float] = {}
        sorted_candidates = sorted(
            candidates.items(),
            key=lambda item: item[1][1],
            reverse=True
        )

        for col, (field, score) in sorted_candidates:
            if field is None:
                continue
            if field not in assigned:
                assigned[field] = col
                assigned_scores[field] = score
                continue

            # Prefer significantly better score
            if score > assigned_scores[field] + 0.15:
                assigned[field] = col
                assigned_scores[field] = score

        mapping: Dict[str, Optional[str]] = {col: None for col in columns}
        for field, col in assigned.items():
            mapping[col] = field

        return mapping

    def normalize_row(self, row: Dict[str, Any], mapping: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
        """Normalize a single row to the standard template.

        Args:
            row: Dictionary representing a single BOM row
            mapping: Optional column mapping to use for normalization

        Returns:
            Dictionary with standard column names, missing columns set to empty string
        """
        normalized_row = {}

        # Initialize all standard headers with empty strings
        for header in STANDARD_HEADERS:
            normalized_row[header] = ""

        # Map original columns to standard columns
        for original_key, value in row.items():
            if original_key is None:
                continue

            if mapping is not None:
                standard_key = mapping.get(original_key)
            else:
                standard_key = self.normalize_column_name(str(original_key))

            if standard_key:
                # Handle multiple values (e.g., if multiple columns map to same standard)
                if normalized_row[standard_key]:
                    # Append if already has value (for reference_designator, notes, etc.)
                    if standard_key in ["reference_designator", "notes"]:
                        normalized_row[standard_key] = f"{normalized_row[standard_key]}, {value}"
                    else:
                        # Keep first non-empty value for other fields
                        if not normalized_row[standard_key]:
                            normalized_row[standard_key] = str(value) if value is not None else ""
                else:
                    normalized_row[standard_key] = str(value) if value is not None else ""
            else:
                # Unmapped columns go to notes
                if value:
                    if normalized_row["notes"]:
                        normalized_row["notes"] = f"{normalized_row['notes']}; {original_key}: {value}"
                    else:
                        normalized_row["notes"] = f"{original_key}: {value}"

        # Clean up values: strip whitespace, handle empty strings
        for key, value in normalized_row.items():
            if isinstance(value, str):
                normalized_row[key] = value.strip()
            elif value is None:
                normalized_row[key] = ""

        # Normalize reference designator ranges
        if normalized_row.get("reference_designator"):
            normalized_row["reference_designator"] = self.normalize_reference_designator(
                normalized_row["reference_designator"]
            )

        return normalized_row

    def normalize(self, raw_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize a list of raw rows to the standard template.

        Args:
            raw_rows: List of dictionaries representing BOM rows

        Returns:
            List of dictionaries with standard column names
        """
        if not raw_rows:
            return []

        mapping = self.infer_column_mapping(raw_rows) if self.use_column_profiling else None
        return [self.normalize_row(row, mapping=mapping) for row in raw_rows]

    def normalize_reference_designator(self, ref_des: str) -> str:
        """Normalize reference designator string to comma-separated list format.

        Expands ranges to individual designators for more effective tracking.
        Each reference designator is explicitly listed, making it easier to track
        changes at the individual component level.

        Handles:
        - Ranges: "D1-D8" -> "D1, D2, D3, D4, D5, D6, D7, D8"
        - Comma-separated lists: "R1, R2, R3" -> "R1, R2, R3" (unchanged)
        - Mixed ranges and singles: "R1-R3, R5, R7-R9" -> "R1, R2, R3, R5, R7, R8, R9"
        - Non-consecutive: "C1, C2, C4" -> "C1, C2, C4" (unchanged)

        Args:
            ref_des: Reference designator string (e.g., "R1, R2, R3" or "D1-D8")

        Returns:
            Normalized reference designator string with all designators explicitly listed,
            separated by commas (e.g., "D1, D2, D3, D4, D5, D6, D7, D8")
        """
        if not ref_des or not ref_des.strip():
            return ""

        # Clean up the input
        ref_des = ref_des.strip()

        # Remove trailing commas and clean up whitespace
        ref_des = re.sub(r',\s*$', '', ref_des)  # Remove trailing comma
        ref_des = re.sub(r'\s*,\s*', ', ', ref_des)  # Normalize comma spacing

        # Split by comma to get individual designators
        parts = [p.strip() for p in ref_des.split(',') if p.strip()]

        if not parts:
            return ""

        # Parse designators into (prefix, number) tuples or keep unparseable as strings
        parseable_designators = []  # List of (prefix, number) tuples
        unparseable = []  # List of strings that couldn't be parsed

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Check if it's already a range (e.g., "R1-R5")
            if ('-' in part or '..' in part) and not part.startswith('-'):
                range_parts = re.split(r'\s*(?:-|\.\.)\s*', part, maxsplit=1)
                if len(range_parts) == 2:
                    start = range_parts[0].strip()
                    end = range_parts[1].strip()
                    # Parse both ends
                    start_match = re.match(r'^([A-Za-z]+)(\d+)$', start)
                    end_match = re.match(r'^([A-Za-z]+)(\d+)$', end)
                    if start_match and end_match:
                        start_prefix, start_num = start_match.groups()
                        end_prefix, end_num = end_match.groups()
                        if start_prefix == end_prefix:
                            start_num = int(start_num)
                            end_num = int(end_num)

                            if start_num <= end_num:
                                # Expand the range to individual designators
                                for num in range(start_num, end_num + 1):
                                    parseable_designators.append((start_prefix, num))
                            else:
                                # Invalid reversed range, keep as-is
                                unparseable.append(part)
                        else:
                            # Different prefixes, treat as separate
                            parseable_designators.append((start_prefix, int(start_num)))
                            parseable_designators.append((end_prefix, int(end_num)))
                    else:
                        # Can't parse, keep as-is
                        unparseable.append(part)
                continue

            # Parse individual designator (e.g., "R1", "C42")
            match = re.match(r'^([A-Za-z]+)(\d+)$', part)
            if match:
                prefix, number = match.groups()
                parseable_designators.append((prefix, int(number)))
            else:
                # Can't parse, keep as-is
                unparseable.append(part)

        if not parseable_designators and not unparseable:
            return ref_des  # Return original if we can't parse anything

        # Group by prefix and sort to maintain consistent ordering
        grouped = {}

        for prefix, num in parseable_designators:
            if prefix not in grouped:
                grouped[prefix] = []
            grouped[prefix].append(num)

        # Sort numbers for each prefix
        for prefix in grouped:
            grouped[prefix].sort()

        # Build normalized output - expand all to individual designators
        result_parts = []

        # Process each prefix group
        for prefix in sorted(grouped.keys()):
            numbers = grouped[prefix]
            if not numbers:
                continue

            # Add all individual designators (no range compression)
            for num in numbers:
                result_parts.append(f"{prefix}{num}")

        # Add unparseable items
        result_parts.extend(unparseable)

        return ', '.join(result_parts)

    def get_column_profiles(self, raw_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Profile columns in raw rows for diagnostics."""
        profiler = ColumnProfiler()
        return profiler.profile_dataframe(raw_rows)

    def normalize_with_profiling(self, raw_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize using column profiling (compatibility helper)."""
        return self.normalize(raw_rows)

    def get_mapping_report(self, raw_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate a report of column mappings for debugging.

        Args:
            raw_rows: List of dictionaries representing BOM rows

        Returns:
            Dictionary with mapping information
        """
        if not raw_rows:
            return {"mapped": {}, "unmapped": []}

        mapping = self.infer_column_mapping(raw_rows) if self.use_column_profiling else {}

        mapped = {}
        unmapped = []

        for column in mapping.keys():
            standard = mapping.get(column)
            if standard:
                if standard not in mapped:
                    mapped[standard] = []
                mapped[standard].append(column)
            else:
                unmapped.append(column)

        return {
            "mapped": mapped,
            "unmapped": unmapped,
            "standard_headers": STANDARD_HEADERS
        }
