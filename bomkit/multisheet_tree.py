"""Utilities for reconciling nested sub-assembly trees across spreadsheet sheets.

This module intentionally keeps the recursion explicit and defensive: while expanding
sub-assemblies we maintain the active branch path. If a node reappears on the same
path, we stop descending that branch, record a cycle diagnostic, and return the
partially resolved hierarchy rather than letting Python hit a RecursionError.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple


def _as_mapping(value: Any) -> Optional[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "__dict__"):
        return vars(value)
    return None


def _coerce_node_id(node: Any, fallback: Optional[str] = None) -> str:
    if node is None:
        return fallback or "<unknown>"
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float)):
        return str(node)
    mapping = _as_mapping(node)
    if mapping:
        for key in ("id", "name", "sheet_name", "sheet", "assembly_name"):
            if key in mapping and mapping[key] is not None:
                return str(mapping[key])
    return fallback or str(node)


def _iter_child_refs(node: Any) -> List[Any]:
    mapping = _as_mapping(node)
    if mapping is None:
        return []

    candidates = []
    for key in ("sub_assemblies", "subassemblies", "children", "references", "linked_sheets", "sheets"):
        if key in mapping:
            value = mapping[key]
            if value is None:
                continue
            if isinstance(value, (list, tuple, set)):
                candidates.extend(value)
            else:
                candidates.append(value)
            break

    if candidates:
        return candidates

    # Some assemblies may expose nested references under a generic `nodes` field.
    if "nodes" in mapping:
        value = mapping["nodes"]
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    return []


def _resolve_node(node_registry: Mapping[str, Any], node_id: str) -> Any:
    if node_id in node_registry:
        return node_registry[node_id]

    for candidate in node_registry.values():
        mapping = _as_mapping(candidate)
        if mapping is None:
            continue
        for key in ("id", "name", "sheet_name", "sheet", "assembly_name"):
            if key in mapping and str(mapping[key]) == str(node_id):
                return candidate
    return node_id


def _build_cycle_diagnostic(path: Sequence[str], node_id: str) -> Dict[str, Any]:
    cycle_path = list(path)
    if node_id not in cycle_path:
        cycle_path.append(node_id)
    cycle_path = cycle_path + [node_id]
    diagnostic = {
        "type": "cycle_detected",
        "cycle_detected": True,
        "node": node_id,
        "path": cycle_path,
        "message": f"Circular sub-assembly dependency detected at '{node_id}'.",
    }
    return diagnostic


def expand_sub_assembly_tree(
    node_registry: Mapping[str, Any],
    root_id: Any,
    *,
    active_path: Optional[List[str]] = None,
    diagnostics: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Expand a nested assembly tree while guarding against cycles.

    Args:
        node_registry: Lookup of node identifiers to nodes. The values may be dicts,
            dataclass instances, or any object with a `sub_assemblies`-like attribute.
        root_id: The starting node identifier.

    Returns:
        A dictionary representing the resolved hierarchy tree. Each node includes:
            - 'id': node identifier
            - 'children': nested child trees
            - 'cycle_detected': bool
            - 'diagnostics': list of cycle diagnostics affecting this node
    """
    if node_registry is None:
        node_registry = {}
    active_path = list(active_path or [])
    diagnostics = diagnostics if diagnostics is not None else []

    node_key = _coerce_node_id(root_id)
    resolved = _resolve_node(node_registry, node_key)
    node_name = _coerce_node_id(resolved, node_key)

    if node_name in active_path:
        diagnostic = _build_cycle_diagnostic(active_path, node_name)
        diagnostics.append(diagnostic)
        return {
            "id": node_name,
            "children": [],
            "cycle_detected": True,
            "diagnostics": [diagnostic],
        }

    next_path = active_path + [node_name]
    children: List[Dict[str, Any]] = []

    raw_children = _iter_child_refs(resolved)
    for child in raw_children:
        child_id = _coerce_node_id(child)
        child_node = _resolve_node(node_registry, child_id)
        if child_node is None:
            # Preserve a leaf-like child if the registry does not know it.
            child_tree = {"id": child_id, "children": [], "cycle_detected": False, "diagnostics": []}
        else:
            child_tree = expand_sub_assembly_tree(
                node_registry,
                _coerce_node_id(child_node, child_id),
                active_path=next_path,
                diagnostics=diagnostics,
            )
        children.append(child_tree)

    result = {
        "id": node_name,
        "children": children,
        "cycle_detected": any(item.get("cycle_detected") for item in children),
        "diagnostics": [
            item for child in children for item in child.get("diagnostics", [])
        ],
    }
    if result["cycle_detected"]:
        result["diagnostics"].append({
            "type": "cycle_detected",
            "cycle_detected": True,
            "node": node_name,
            "path": next_path,
            "message": f"Circular dependency detected under '{node_name}'.",
        })
    return result


def reconcile_sub_assembly_tree(
    node_registry: Mapping[str, Any],
    root_id: Any,
) -> Dict[str, Any]:
    """Alias for expand_sub_assembly_tree with a public, issue-friendly name."""
    tree = expand_sub_assembly_tree(node_registry, root_id)
    return tree


def detect_cycle_in_branch(
    node_registry: Mapping[str, Any],
    root_id: Any,
    active_path: Optional[List[str]] = None,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """Convenience helper that reports whether a cycle exists on the current branch."""
    active_path = list(active_path or [])
    node_key = _coerce_node_id(root_id)
    if node_key in active_path:
        return True, [_build_cycle_diagnostic(active_path, node_key)]

    resolved = _resolve_node(node_registry, node_key)
    if resolved is None:
        return False, []

    diagnostics: List[Dict[str, Any]] = []
    next_path = active_path + [node_key]
    for child in _iter_child_refs(resolved):
        child_id = _coerce_node_id(child)
        cycle, child_diagnostics = detect_cycle_in_branch(node_registry, child_id, next_path)
        diagnostics.extend(child_diagnostics)
        if cycle:
            return True, diagnostics
    return False, diagnostics


__all__ = [
    "expand_sub_assembly_tree",
    "reconcile_sub_assembly_tree",
    "detect_cycle_in_branch",
]
