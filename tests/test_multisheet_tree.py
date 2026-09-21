"""Regression tests for sub-assembly tree expansion and cycle detection."""

from bomkit.multisheet_tree import reconcile_sub_assembly_tree


def test_cycle_detection_no_recursion_error():
    """Circular sheet references should be reported without crashing recursion."""
    sheets = {
        "Sheet A": {"id": "Sheet A", "sub_assemblies": ["Sheet B"]},
        "Sheet B": {"id": "Sheet B", "sub_assemblies": ["Sheet A"]},
    }

    result = reconcile_sub_assembly_tree(sheets, "Sheet A")

    assert result["id"] == "Sheet A"
    assert result["children"]
    diagnostics = [
        item
        for child in result["children"]
        for item in child.get("diagnostics", [])
    ]
    assert any(item.get("cycle_detected") or item.get("type") == "cycle_detected" for item in diagnostics)
