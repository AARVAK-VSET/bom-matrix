"""
Model Context Protocol (MCP) Server and Tools Package for BOM Matrix.
"""

from bomkit.mcp.server import MCPJsonRpcServer, JSONRPCError
from bomkit.mcp.teamcenter_server import (
    mcp,
    handle_jsonrpc,
    json_rpc_server,
    normalize_bom,
    profile_columns,
    compare_snapshots,
    health_check,
    request,
    search_items,
    get_item,
    create_item,
    update_item,
)

__all__ = [
    "MCPJsonRpcServer",
    "JSONRPCError",
    "mcp",
    "handle_jsonrpc",
    "json_rpc_server",
    "normalize_bom",
    "profile_columns",
    "compare_snapshots",
    "health_check",
    "request",
    "search_items",
    "get_item",
    "create_item",
    "update_item",
]
