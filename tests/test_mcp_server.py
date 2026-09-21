"""
Unit and integration tests for Model Context Protocol (MCP) server & tools.
Tests JSON-RPC 2.0 specification, JSON schema validation, BOM normalization,
column profiling, and snapshot comparison tools.
"""

import json
import pytest
from bomkit.mcp import handle_jsonrpc, MCPJsonRpcServer, normalize_bom, profile_columns, compare_snapshots


def test_jsonrpc_initialize():
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
    }
    resp = handle_jsonrpc(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert "result" in resp
    assert resp["result"]["serverInfo"]["name"] == "teamcenter-mcp"
    assert "protocolVersion" in resp["result"]


def test_jsonrpc_ping():
    req = {"jsonrpc": "2.0", "id": "test-ping", "method": "ping"}
    resp = handle_jsonrpc(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == "test-ping"
    assert resp["result"] == {}


def test_jsonrpc_tools_list():
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    resp = handle_jsonrpc(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 2
    tools = resp["result"]["tools"]
    tool_names = {t["name"] for t in tools}

    assert "normalize_bom" in tool_names
    assert "profile_columns" in tool_names
    assert "compare_snapshots" in tool_names
    assert "health_check" in tool_names
    assert "search_items" in tool_names
    assert "get_item" in tool_names

    # Check that every tool declares a valid inputSchema
    for t in tools:
        schema = t["inputSchema"]
        assert isinstance(schema, dict)
        assert schema.get("type") == "object"


def test_normalize_bom_tool():
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "normalize_bom",
            "arguments": {
                "rows": [
                    {
                        "Part_Number": "RES-10K-0805",
                        "quantitiy": 10,
                        "value": "10k",
                        "refdes": "R1-R10",
                    }
                ]
            },
        },
    }
    resp = handle_jsonrpc(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 3
    assert "result" in resp
    assert resp["result"]["isError"] is False

    content_text = resp["result"]["content"][0]["text"]
    data = json.loads(content_text)
    assert "normalized_rows" in data
    assert len(data["normalized_rows"]) == 1
    assert int(data["normalized_rows"][0].get("quantity")) == 10
    assert "header_mappings" in data


def test_profile_columns_tool():
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "profile_columns",
            "arguments": {
                "data": [
                    {"mpn": "LM358N", "qty": 2, "value": "10nF"},
                    {"mpn": "NE555P", "qty": 5, "value": "100nF"},
                ]
            },
        },
    }
    resp = handle_jsonrpc(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 4
    assert resp["result"]["isError"] is False

    data = json.loads(resp["result"]["content"][0]["text"])
    assert "profiles" in data
    assert "mpn" in data["profiles"]
    assert "qty" in data["profiles"]


def test_compare_snapshots_tool():
    snap_a = [
        {"id": "item1", "part_number": "CAP-10UF", "quantity": 5, "value": "10uF"},
        {"id": "item2", "part_number": "RES-1K", "quantity": 2, "value": "1k"},
    ]
    snap_b = [
        {"id": "item1", "part_number": "CAP-10UF", "quantity": 10, "value": "10uF"},
        {"id": "item3", "part_number": "MCU-STM32", "quantity": 1, "value": "3.3V"},
    ]

    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "call_tool",
        "params": {
            "name": "compare_snapshots",
            "arguments": {
                "snapshot_a": snap_a,
                "snapshot_b": snap_b,
            },
        },
    }
    resp = handle_jsonrpc(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 5
    assert resp["result"]["isError"] is False

    data = json.loads(resp["result"]["content"][0]["text"])
    assert data["summary"]["added"] == 1
    assert data["summary"]["removed"] == 1
    assert data["summary"]["modified"] == 1
    assert "change_events" in data


def test_json_schema_validation_failure():
    """Verify that missing required arguments fail gracefully with JSON-RPC error code -32602."""
    req = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "normalize_bom",
            "arguments": {
                # missing required 'rows'
                "use_column_profiling": True
            },
        },
    }
    resp = handle_jsonrpc(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 6
    assert "error" in resp
    assert resp["error"]["code"] == -32602
    assert "Invalid params" in resp["error"]["message"]
    assert "'rows' is a required property" in resp["error"]["message"]


def test_unknown_tool():
    req = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "non_existent_tool",
            "arguments": {},
        },
    }
    resp = handle_jsonrpc(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 7
    assert "error" in resp
    assert resp["error"]["code"] == -32601
    assert "not found" in resp["error"]["message"]


def test_invalid_jsonrpc_request():
    req = {
        "jsonrpc": "1.0",
        "id": 8,
        "method": "ping",
    }
    resp = handle_jsonrpc(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 8
    assert "error" in resp
    assert resp["error"]["code"] == -32600


def test_parse_error():
    resp = handle_jsonrpc("invalid raw json string {{{")
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] is None
    assert "error" in resp
    assert resp["error"]["code"] == -32700
