"""
Unit and integration tests for Environmental Compliance Rule Evaluation Engine.

Tests:
1. Primary acceptance test: test_rohs_lead_violation (Pb 0.12% -> NON_COMPLIANT)
2. Strict boundary semantics for RoHS (Directive 2011/65/EU Annex II)
3. REACH SVHC Candidate List screening threshold (Regulation (EC) No 1907/2006 Article 33)
4. Non-SVHC substance exemption under REACH (e.g., Copper 0.2% is COMPLIANT)
5. Deterministic multi-substance evaluation and ordering
6. Missing, empty, and invalid declaration handling (UNKNOWN / ValueError)
7. Delta report event generation and classification integration
"""

import bomkit.ingest  # Pre-import to resolve upstream circular dependency in bomkit.diff

import pytest
from uuid import uuid4

from bomkit.compliance import (
    evaluate_compliance,
    ComplianceStatus,
    ComplianceViolation,
    ComplianceResult,
    generate_compliance_delta_events,
)
from bomkit.diff.snapshot_diff import DiffResult, ModifiedItem, FieldChange
from bomkit.diff.change_events import classify_diff, ChangeEventType, Severity, Domain


# =============================================================================
# PRIMARY ACCEPTANCE TEST (Issue #26 Requirement)
# =============================================================================

def test_rohs_lead_violation():
    """
    Primary Acceptance Test for Issue #26:
    Line item with material_declaration={"Pb": 0.12} (above RoHS 0.1% threshold)
    asserts evaluate_compliance() returns status NON_COMPLIANT and a violation
    event naming substance Pb with measured percentage 0.12.
    """
    line_item = {"material_declaration": {"Pb": 0.12}}
    result = evaluate_compliance(line_item)

    assert result.status == ComplianceStatus.NON_COMPLIANT
    assert result.status == "NON_COMPLIANT"
    assert len(result.violations) == 1

    violation = result.violations[0]
    assert violation.substance == "Pb"
    assert violation.measured_percentage == 0.12
    assert violation.threshold == 0.1
    assert violation.standard == "RoHS"
    assert "Pb" in violation.message
    assert "0.12" in violation.message


# =============================================================================
# THRESHOLD BOUNDARY TESTS (RoHS & REACH SVHC)
# =============================================================================

class TestThresholdBoundaries:
    """Tests boundary condition semantics (strict > threshold)."""

    def test_rohs_lead_exact_boundary(self):
        """Lead (Pb) at exactly 0.10% is COMPLIANT (within 1000 ppm limit)."""
        result = evaluate_compliance({"material_declaration": {"Pb": 0.10}})
        assert result.status == ComplianceStatus.COMPLIANT
        assert len(result.violations) == 0

    def test_rohs_lead_above_boundary(self):
        """Lead (Pb) at 0.100001% is NON_COMPLIANT (> 0.1%)."""
        result = evaluate_compliance({"material_declaration": {"Pb": 0.100001}})
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert len(result.violations) == 1
        assert result.violations[0].substance == "Pb"
        assert result.violations[0].threshold == 0.1

    def test_rohs_cadmium_exact_boundary(self):
        """Cadmium (Cd) threshold is 0.01% (100 ppm). Exactly 0.01% is COMPLIANT."""
        result = evaluate_compliance({"material_declaration": {"Cd": 0.01}})
        assert result.status == ComplianceStatus.COMPLIANT
        assert len(result.violations) == 0

    def test_rohs_cadmium_above_boundary(self):
        """Cadmium (Cd) at 0.02% is NON_COMPLIANT (> 0.01%)."""
        result = evaluate_compliance({"material_declaration": {"Cd": 0.02}})
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert len(result.violations) == 1
        assert result.violations[0].substance == "Cd"
        assert result.violations[0].threshold == 0.01

    def test_reach_svhc_screening_threshold(self):
        """Under REACH Article 33, Candidate List SVHC screening threshold is 0.1% w/w."""
        # 0.10% Anthracene is compliant with SVHC screening threshold
        result_ok = evaluate_compliance({"material_declaration": {"Anthracene": 0.10}}, standard="REACH")
        assert result_ok.status == ComplianceStatus.COMPLIANT
        assert len(result_ok.violations) == 0

        # 0.12% Anthracene triggers SVHC screening violation
        result_fail = evaluate_compliance({"material_declaration": {"Anthracene": 0.12}}, standard="REACH")
        assert result_fail.status == ComplianceStatus.NON_COMPLIANT
        assert len(result_fail.violations) == 1
        assert result_fail.violations[0].threshold == 0.1
        assert result_fail.violations[0].standard == "REACH"

    def test_reach_non_svhc_substance_not_flagged(self):
        """Non-SVHC substances like Copper or Gold are not falsely flagged under REACH."""
        result = evaluate_compliance({"material_declaration": {"Copper": 0.20}}, standard="REACH")
        assert result.status == ComplianceStatus.COMPLIANT
        assert len(result.violations) == 0

    def test_reach_custom_registry_override(self):
        """Custom SVHC substance registry allows project-specific substance screening."""
        result = evaluate_compliance(
            {"material_declaration": {"CustomChemical": 0.15}},
            standard="REACH",
            custom_thresholds={"CustomChemical": 0.1}
        )
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert len(result.violations) == 1
        assert result.violations[0].substance == "CustomChemical"


# =============================================================================
# MULTIPLE SUBSTANCES & DETERMINISM
# =============================================================================

class TestMultipleSubstances:
    """Tests evaluating multiple substances and deterministic ordering."""

    def test_multiple_violations_all_reported(self):
        """Both Pb (0.12%) and Cd (0.02%) exceeding thresholds must both be reported."""
        item = {"material_declaration": {"Pb": 0.12, "Cd": 0.02}}
        result = evaluate_compliance(item)

        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert len(result.violations) == 2

        # Deterministic alphabetical ordering by substance
        substances = [v.substance for v in result.violations]
        assert substances == ["Cd", "Pb"]

        cd_violation = next(v for v in result.violations if v.substance == "Cd")
        assert cd_violation.measured_percentage == 0.02
        assert cd_violation.threshold == 0.01

        pb_violation = next(v for v in result.violations if v.substance == "Pb")
        assert pb_violation.measured_percentage == 0.12
        assert pb_violation.threshold == 0.1

    def test_fully_compliant_multiple_substances(self):
        """All declared substances below limits produce COMPLIANT with 0 violations."""
        item = {
            "material_declaration": {
                "Pb": 0.05,
                "Cd": 0.005,
                "Hg": 0.02,
                "Cr6+": 0.01,
            }
        }
        result = evaluate_compliance(item)
        assert result.status == ComplianceStatus.COMPLIANT
        assert len(result.violations) == 0

    def test_case_insensitive_substance_names(self):
        """Substance keys like 'lead', 'LEAD', 'pb', 'cd' match thresholds correctly."""
        result1 = evaluate_compliance({"material_declaration": {"lead": 0.15}})
        assert result1.status == ComplianceStatus.NON_COMPLIANT
        assert result1.violations[0].substance == "lead"

        result2 = evaluate_compliance({"material_declaration": {"cadmium": 0.05}})
        assert result2.status == ComplianceStatus.NON_COMPLIANT
        assert result2.violations[0].substance == "cadmium"


# =============================================================================
# MISSING, EMPTY, AND INVALID INPUT HANDLING
# =============================================================================

class TestInputValidation:
    """Tests for missing declarations, empty declarations, and invalid inputs."""

    def test_missing_declaration_returns_unknown(self):
        """Missing material declaration returns status UNKNOWN."""
        assert evaluate_compliance({}).status == ComplianceStatus.UNKNOWN
        assert evaluate_compliance(None).status == ComplianceStatus.UNKNOWN
        assert evaluate_compliance({"part_number": "RES-001"}).status == ComplianceStatus.UNKNOWN

    def test_empty_declaration_returns_unknown(self):
        """Empty material declaration dict returns status UNKNOWN."""
        assert evaluate_compliance({"material_declaration": {}}).status == ComplianceStatus.UNKNOWN

    def test_unregulated_substance_compliant(self):
        """Substance outside regulated rule set is not falsely flagged."""
        result = evaluate_compliance({"material_declaration": {"Gold": 99.5, "Copper": 0.5}})
        assert result.status == ComplianceStatus.COMPLIANT
        assert len(result.violations) == 0

    def test_invalid_percentage_types_raise_error(self):
        """Non-numeric values (None, 'abc', NaN, Infinity, negative) raise ValueError."""
        with pytest.raises(ValueError):
            evaluate_compliance({"material_declaration": {"Pb": "not_a_number"}})

        with pytest.raises(ValueError):
            evaluate_compliance({"material_declaration": {"Pb": None}})

        with pytest.raises(ValueError):
            evaluate_compliance({"material_declaration": {"Pb": float("nan")}})

        with pytest.raises(ValueError):
            evaluate_compliance({"material_declaration": {"Pb": float("inf")}})

        with pytest.raises(ValueError):
            evaluate_compliance({"material_declaration": {"Pb": -0.05}})


# =============================================================================
# DELTA REPORT & VIOLATION EVENT GENERATION
# =============================================================================

class TestDeltaReportIntegration:
    """Tests for generating compliance violation events in delta reports."""

    def test_generate_compliance_delta_events(self):
        """A modified part with hazardous substance violation produces event in delta report."""
        modified_items = [
            {
                "id": "ITEM-101",
                "part_number": "CAP-CER-10UF",
                "material_declaration": {"Pb": 0.15},  # Exceeds RoHS 0.1%
            },
            {
                "id": "ITEM-102",
                "part_number": "RES-10K",
                "material_declaration": {"Pb": 0.05},  # Compliant
            }
        ]

        delta_events = generate_compliance_delta_events(modified_items)

        assert len(delta_events) == 1
        event = delta_events[0]
        assert event["event_type"] == "COMPLIANCE_VIOLATION"
        assert event["severity"] == "HIGH"
        assert event["domain"] == "QUALITY"
        assert event["substance"] == "Pb"
        assert event["measured_percentage"] == 0.15
        assert event["threshold"] == 0.1
        assert event["item_id"] == "ITEM-101"

    def test_classify_diff_with_compliance_violation(self):
        """Layer 2 classify_diff identifies COMPLIANCE_VIOLATION change events."""
        bom_id = uuid4()
        modified = ModifiedItem(
            bom_item_id=bom_id,
            changes=[
                FieldChange(
                    type="ATTRIBUTE_CHANGED",
                    field="compliance_status",
                    from_value="COMPLIANT",
                    to_value="NON_COMPLIANT"
                )
            ]
        )

        diff = DiffResult(
            snapshot_a_id=uuid4(),
            snapshot_b_id=uuid4(),
            added_items=[],
            removed_items=[],
            modified_items=[modified],
            unchanged_count=5
        )

        result = classify_diff(diff)
        assert len(result.events) == 1
        event = result.events[0]
        assert event.event_type == ChangeEventType.COMPLIANCE_VIOLATION
        assert event.severity == Severity.HIGH
        assert Domain.QUALITY in event.affected_domains
        assert event.bom_item_id == bom_id
