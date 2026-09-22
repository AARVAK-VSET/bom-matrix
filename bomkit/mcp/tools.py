"""
MCP Tool Definitions and Schemas for BOM Matrix.

Provides tools for BOM normalization, column profiling, snapshot comparison,
and Teamcenter REST PLM synchronization.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from bomkit.column_profiler import ColumnProfiler
from bomkit.confidence import ConfidenceScorer
from bomkit.diff.change_events import classify_and_summarize
from bomkit.diff.snapshot_diff import (
    DiffResult,
    ModifiedItem,
    SnapshotItemState,
    diff_snapshot_item,
)
from bomkit.mcp.teamcenter_server import _load_config, _request
from bomkit.normalizer import BomNormalizer
from bomkit.unit_normalizer import UnitNormalizer


# =============================================================================
# TOOL SCHEMAS (JSON Schema Format)
# =============================================================================

NORMALIZE_BOM_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {"type": "object"},
            "description": "List of raw BOM row dictionaries",
        },
        "headers": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional explicit column headers list",
        },
        "normalize_units": {
            "type": "boolean",
            "default": True,
            "description": "Whether to normalize electrical and mechanical units",
        },
        "use_column_profiling": {
            "type": "boolean",
            "default": True,
            "description": "Whether to use statistical column profiling for disambiguation",
        },
    },
    "required": ["rows"],
}

PROFILE_COLUMNS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "data": {
            "type": ["array", "object"],
            "description": "BOM row records, column-oriented dict, or 2D matrix to profile",
        },
        "headers": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional list of column names if data is a matrix",
        },
        "sample_size": {
            "type": "integer",
            "default": 200,
            "description": "Maximum number of non-null samples per column",
        },
    },
    "required": ["data"],
}

COMPARE_SNAPSHOTS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "snapshot_a": {
            "type": ["array", "object"],
            "description": "Baseline BOM snapshot items or rows",
        },
        "snapshot_b": {
            "type": ["array", "object"],
            "description": "Comparison BOM snapshot items or rows",
        },
        "snapshot_a_id": {
            "type": "string",
            "description": "Optional identifier for snapshot A",
        },
        "snapshot_b_id": {
            "type": "string",
            "description": "Optional identifier for snapshot B",
        },
    },
    "required": ["snapshot_a", "snapshot_b"],
}

HEALTH_CHECK_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "default": "/tc/controller/test",
            "description": "Health check endpoint path",
        }
    },
}

REQUEST_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "method": {
            "type": "string",
            "description": "HTTP method (GET, POST, PUT, PATCH, DELETE)",
        },
        "path": {
            "type": "string",
            "description": "REST API path or relative endpoint",
        },
        "params": {
            "type": "object",
            "description": "URL query parameters",
        },
        "json_body": {
            "type": "object",
            "description": "JSON body payload",
        },
        "headers": {
            "type": "object",
            "description": "Additional HTTP request headers",
        },
    },
    "required": ["method", "path"],
}

SEARCH_ITEMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query keyword or part ID",
        },
        "params": {
            "type": "object",
            "description": "Additional search query parameters",
        },
        "path": {
            "type": "string",
            "description": "Override default search endpoint path",
        },
    },
    "required": ["query"],
}

GET_ITEM_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "item_id": {
            "type": "string",
            "description": "Teamcenter item identifier",
        },
        "path_template": {
            "type": "string",
            "description": "Path template for fetching item",
        },
    },
    "required": ["item_id"],
}

CREATE_ITEM_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "payload": {
            "type": "object",
            "description": "Item attributes and structure for item creation",
        },
        "path": {
            "type": "string",
            "description": "Override item creation endpoint",
        },
    },
    "required": ["payload"],
}

UPDATE_ITEM_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "item_id": {
            "type": "string",
            "description": "Target item identifier to update",
        },
        "payload": {
            "type": "object",
            "description": "Attributes to update",
        },
        "method": {
            "type": "string",
            "default": "PATCH",
            "description": "HTTP method for update (PATCH or PUT)",
        },
        "path_template": {
            "type": "string",
            "description": "Override update endpoint path template",
        },
    },
    "required": ["item_id", "payload"],
}


# =============================================================================
# TOOL HANDLERS
# =============================================================================

def normalize_bom(
    rows: List[Dict[str, Any]],
    headers: Optional[List[str]] = None,
    normalize_units: bool = True,
    use_column_profiling: bool = True,
) -> Dict[str, Any]:
    """Normalize raw BOM rows into canonical schema with unit conversions."""
    normalizer = BomNormalizer(use_column_profiling=use_column_profiling)
    unit_normalizer = UnitNormalizer()

    normalized_rows = normalizer.normalize(rows)

    if normalize_units:
        for row in normalized_rows:
            for field_name, val in list(row.items()):
                if isinstance(val, str) and field_name in {
                    "value",
                    "capacitance",
                    "resistance",
                    "inductance",
                    "voltage",
                }:
                    norm_val, orig_unit, norm_unit = unit_normalizer.normalize_element(val)
                    if orig_unit or norm_unit:
                        row[f"{field_name}_normalized"] = {
                            "value": norm_val,
                            "original_unit": orig_unit,
                            "normalized_unit": norm_unit,
                        }

    sample_headers = headers or (list(rows[0].keys()) if rows else [])
    header_mappings: Dict[str, str] = {}
    for h in sample_headers:
        norm_h = normalizer.normalize_column_name(h)
        if norm_h:
            header_mappings[h] = norm_h

    confidence_report: Dict[str, Any] = {}
    if normalized_rows:
        try:
            confidence_report = ConfidenceScorer().build_report(normalized_rows)
        except Exception:
            confidence_report = {}

    return {
        "normalized_rows": normalized_rows,
        "header_mappings": header_mappings,
        "confidence_report": confidence_report,
        "total_rows": len(normalized_rows),
    }


def profile_columns(
    data: Any,
    headers: Optional[List[str]] = None,
    sample_size: int = 200,
) -> Dict[str, Any]:
    """Profile BOM column data distributions and infer semantic fields."""
    profiler = ColumnProfiler(sample_size=sample_size)

    if isinstance(data, list) and data and isinstance(data[0], dict):
        profile_results = profiler.profile(data)
    elif isinstance(data, dict):
        profile_results = {}
        for col_name, col_values in data.items():
            if isinstance(col_values, list):
                profile_results[col_name] = profiler.profile_column(col_name, col_values)
            else:
                profile_results[col_name] = profiler.profile_column(col_name, [col_values])
    elif isinstance(data, list):
        cols: Dict[str, List[Any]] = {}
        h_names = headers or (
            [f"col_{i}" for i in range(len(data[0]))] if data and isinstance(data[0], list) else []
        )
        for row in data:
            if isinstance(row, list):
                for idx, val in enumerate(row):
                    h = h_names[idx] if idx < len(h_names) else f"col_{idx}"
                    cols.setdefault(h, []).append(val)
        profile_results = {
            col_name: profiler.profile_column(col_name, vals) for col_name, vals in cols.items()
        }
    else:
        profile_results = {}

    return {
        "profiles": profile_results,
        "total_columns": len(profile_results),
        "sample_size": sample_size,
    }


def _to_snapshot_item_states(items: Any) -> Dict[UUID, SnapshotItemState]:
    if isinstance(items, dict) and "items" in items:
        items = items["items"]
    if not isinstance(items, list):
        items = [items]

    states: Dict[UUID, SnapshotItemState] = {}
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            item = {"value": item}

        item_id_str = str(
            item.get("bom_item_id")
            or item.get("id")
            or item.get("part_number")
            or item.get("mpn")
            or f"item_{idx}"
        )
        try:
            item_uuid = UUID(item_id_str)
        except ValueError:
            item_uuid = UUID(bytes=hashlib.md5(item_id_str.encode("utf-8")).digest())

        qty = item.get("quantity") if "quantity" in item else item.get("qty")
        if qty is not None:
            try:
                qty = float(qty)
            except (ValueError, TypeError):
                qty = 1.0

        part_id_val = item.get("part_id")
        part_uuid: Optional[UUID] = None
        if part_id_val:
            try:
                part_uuid = UUID(str(part_id_val))
            except ValueError:
                part_uuid = UUID(bytes=hashlib.md5(str(part_id_val).encode("utf-8")).digest())

        attrs = item.get("attributes")
        if not isinstance(attrs, dict):
            attrs = {
                k: v
                for k, v in item.items()
                if k not in {"id", "bom_item_id", "quantity", "qty", "part_id", "checksum", "assembly_path"}
            }

        checksum = item.get("checksum") or hashlib.md5(
            json.dumps(attrs, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        states[item_uuid] = SnapshotItemState(
            bom_item_id=item_uuid,
            quantity=qty,
            attributes=attrs,
            checksum=checksum,
            part_id=part_uuid,
            assembly_path=item.get("assembly_path"),
        )
    return states


def compare_snapshots(
    snapshot_a: Any,
    snapshot_b: Any,
    snapshot_a_id: Optional[str] = None,
    snapshot_b_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare two BOM snapshots and produce field-level diffs and typed change events."""
    id_a = UUID(snapshot_a_id) if snapshot_a_id else uuid4()
    id_b = UUID(snapshot_b_id) if snapshot_b_id else uuid4()

    state_a = _to_snapshot_item_states(snapshot_a)
    state_b = _to_snapshot_item_states(snapshot_b)

    keys_a = set(state_a.keys())
    keys_b = set(state_b.keys())

    added_items = list(keys_b - keys_a)
    removed_items = list(keys_a - keys_b)

    common_keys = keys_a & keys_b
    modified_items: List[ModifiedItem] = []
    unchanged_count = 0

    for k in common_keys:
        item_a = state_a[k]
        item_b = state_b[k]
        if item_a.checksum == item_b.checksum and item_a.quantity == item_b.quantity:
            unchanged_count += 1
        else:
            changes = diff_snapshot_item(item_a, item_b)
            if changes:
                modified_items.append(
                    ModifiedItem(
                        bom_item_id=k, changes=changes, assembly_path=item_b.assembly_path
                    )
                )
            else:
                unchanged_count += 1

    diff_result = DiffResult(
        snapshot_a_id=id_a,
        snapshot_b_id=id_b,
        added_items=added_items,
        removed_items=removed_items,
        modified_items=modified_items,
        unchanged_count=unchanged_count,
    )

    classified = classify_and_summarize(diff_result)

    return {
        "snapshot_a_id": str(id_a),
        "snapshot_b_id": str(id_b),
        "summary": {
            "added": len(added_items),
            "removed": len(removed_items),
            "modified": len(modified_items),
            "unchanged": unchanged_count,
        },
        "diff_result": {
            "added_items": [str(x) for x in added_items],
            "removed_items": [str(x) for x in removed_items],
            "modified_items": [
                {
                    "bom_item_id": str(m.bom_item_id),
                    "assembly_path": m.assembly_path,
                    "changes": [
                        {
                            "type": c.type,
                            "field": c.field,
                            "from_value": c.from_value,
                            "to_value": c.to_value,
                        }
                        for c in m.changes
                    ],
                }
                for m in modified_items
            ],
            "unchanged_count": unchanged_count,
        },
        "change_events": classified,
    }


def health_check(path: str = "/tc/controller/test") -> Dict[str, Any]:
    """Check connectivity to Teamcenter REST service."""
    config = _load_config()
    return _request(config, "GET", path)


def request(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Send arbitrary HTTP REST request to Teamcenter server."""
    config = _load_config()
    return _request(config, method, path, params=params, json_body=json_body, headers=headers)


def search_items(
    query: str,
    params: Optional[Dict[str, Any]] = None,
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """Search items in Teamcenter."""
    config = _load_config()
    search_params = dict(params or {})
    search_params.setdefault(config.search_query_param, query)
    return _request(config, "GET", path or config.search_path, params=search_params)


def get_item(item_id: str, path_template: Optional[str] = None) -> Dict[str, Any]:
    """Fetch item details by item ID."""
    config = _load_config()
    template = path_template or config.item_path_template
    path = template.format(item_id=item_id)
    return _request(config, "GET", path)


def create_item(payload: Dict[str, Any], path: Optional[str] = None) -> Dict[str, Any]:
    """Create a new item in Teamcenter PLM."""
    config = _load_config()
    return _request(config, "POST", path or config.create_item_path, json_body=payload)


def update_item(
    item_id: str,
    payload: Dict[str, Any],
    method: str = "PATCH",
    path_template: Optional[str] = None,
) -> Dict[str, Any]:
    """Update item in Teamcenter PLM."""
    config = _load_config()
    template = path_template or config.update_item_path_template
    path = template.format(item_id=item_id)
    return _request(config, method, path, json_body=payload)
