from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

import requests
try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("teamcenter")
except (ImportError, ModuleNotFoundError):
    try:
        from mcp.server.mcpserver import MCPServer
        mcp = MCPServer("teamcenter")
    except (ImportError, ModuleNotFoundError):
        class DummyMCP:
            def tool(self, *args, **kwargs):
                def decorator(fn):
                    return fn
                return decorator
            def run(self):
                pass
        mcp = DummyMCP()
from requests.auth import HTTPBasicAuth


@dataclass(frozen=True)
class TeamcenterConfig:
    base_url: str
    auth_mode: str
    username: Optional[str]
    password: Optional[str]
    bearer_token: Optional[str]
    verify_tls: object
    timeout: int
    default_headers: Dict[str, str]
    search_path: str
    search_query_param: str
    item_path_template: str
    create_item_path: str
    update_item_path_template: str


def _parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _load_config() -> TeamcenterConfig:
    base_url = os.getenv("TEAMCENTER_BASE_URL", "https://teamcenter.example.com/tc")
    auth_mode = os.getenv("TEAMCENTER_AUTH_MODE", "basic").strip().lower()
    username = os.getenv("TEAMCENTER_USERNAME", "admin")
    password = os.getenv("TEAMCENTER_PASSWORD", "password")
    bearer_token = os.getenv("TEAMCENTER_BEARER_TOKEN")

    verify_tls_env = os.getenv("TEAMCENTER_VERIFY_TLS")
    ca_bundle = os.getenv("TEAMCENTER_CA_BUNDLE")
    verify_tls: object = _parse_bool(verify_tls_env, True)
    if ca_bundle:
        verify_tls = ca_bundle

    timeout = int(os.getenv("TEAMCENTER_TIMEOUT", "30"))

    default_headers: Dict[str, str] = {}
    default_headers_env = os.getenv("TEAMCENTER_DEFAULT_HEADERS")
    if default_headers_env:
        try:
            default_headers = json.loads(default_headers_env)
        except Exception:
            default_headers = {}

    return TeamcenterConfig(
        base_url=base_url,
        auth_mode=auth_mode,
        username=username,
        password=password,
        bearer_token=bearer_token,
        verify_tls=verify_tls,
        timeout=timeout,
        default_headers=default_headers,
        search_path=os.getenv("TEAMCENTER_SEARCH_PATH", "/tc/search"),
        search_query_param=os.getenv("TEAMCENTER_SEARCH_QUERY_PARAM", "query"),
        item_path_template=os.getenv("TEAMCENTER_ITEM_PATH_TEMPLATE", "/tc/item/{item_id}"),
        create_item_path=os.getenv("TEAMCENTER_CREATE_ITEM_PATH", "/tc/item"),
        update_item_path_template=os.getenv(
            "TEAMCENTER_UPDATE_ITEM_PATH_TEMPLATE", "/tc/item/{item_id}"
        ),
    )


def _join_url(base_url: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _build_auth(config: TeamcenterConfig) -> Optional[HTTPBasicAuth]:
    if config.auth_mode == "basic":
        if not config.username or not config.password:
            raise ValueError("Basic auth requires TEAMCENTER_USERNAME and TEAMCENTER_PASSWORD")
        return HTTPBasicAuth(config.username, config.password)
    return None


def _build_headers(config: TeamcenterConfig, headers: Optional[Dict[str, str]]) -> Dict[str, str]:
    merged = dict(config.default_headers)
    if headers:
        merged.update(headers)
    if config.auth_mode == "bearer":
        if not config.bearer_token:
            raise ValueError("Bearer auth requires TEAMCENTER_BEARER_TOKEN")
        merged.setdefault("Authorization", f"Bearer {config.bearer_token}")
    return merged


def _request(
    config: TeamcenterConfig,
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    url = _join_url(config.base_url, path)
    auth = _build_auth(config)
    req_headers = _build_headers(config, headers)

    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            params=params,
            json=json_body,
            headers=req_headers,
            auth=auth,
            timeout=config.timeout,
            verify=config.verify_tls,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status": None,
            "error": str(exc),
            "url": url,
        }

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
    else:
        body = response.text

    return {
        "ok": response.ok,
        "status": response.status_code,
        "url": url,
        "headers": dict(response.headers),
        "body": body,
    }


# Initialize MCP instance
# (mcp is instantiated at top of file with fallback support)

# Instantiate JSON-RPC 2.0 Server
from bomkit.mcp.server import MCPJsonRpcServer
from bomkit.mcp import tools

json_rpc_server = MCPJsonRpcServer(name="teamcenter-mcp", version="1.0.0")

# Register all tools with FastMCP and JSON-RPC Server
@mcp.tool()
def normalize_bom(
    rows: List[Dict[str, Any]],
    headers: Optional[List[str]] = None,
    normalize_units: bool = True,
    use_column_profiling: bool = True,
) -> Dict[str, Any]:
    """Normalize raw BOM rows into canonical schema with unit conversions."""
    return tools.normalize_bom(
        rows,
        headers=headers,
        normalize_units=normalize_units,
        use_column_profiling=use_column_profiling,
    )


@mcp.tool()
def profile_columns(
    data: Any,
    headers: Optional[List[str]] = None,
    sample_size: int = 200,
) -> Dict[str, Any]:
    """Profile BOM column data distributions and infer semantic fields."""
    return tools.profile_columns(data, headers=headers, sample_size=sample_size)


@mcp.tool()
def compare_snapshots(
    snapshot_a: Any,
    snapshot_b: Any,
    snapshot_a_id: Optional[str] = None,
    snapshot_b_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare two BOM snapshots and produce field-level diffs and typed change events."""
    return tools.compare_snapshots(
        snapshot_a,
        snapshot_b,
        snapshot_a_id=snapshot_a_id,
        snapshot_b_id=snapshot_b_id,
    )


@mcp.tool()
def health_check(path: str = "/tc/controller/test") -> Dict[str, Any]:
    """Check connectivity to Teamcenter with a simple GET request."""
    return tools.health_check(path=path)


@mcp.tool()
def request(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Send an arbitrary Teamcenter REST request."""
    return tools.request(method, path, params=params, json_body=json_body, headers=headers)


@mcp.tool()
def search_items(
    query: str,
    params: Optional[Dict[str, Any]] = None,
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """Search for items via a configurable Teamcenter search endpoint."""
    return tools.search_items(query, params=params, path=path)


@mcp.tool()
def get_item(item_id: str, path_template: Optional[str] = None) -> Dict[str, Any]:
    """Fetch a Teamcenter item by ID using a configurable path template."""
    return tools.get_item(item_id, path_template=path_template)


@mcp.tool()
def create_item(
    payload: Dict[str, Any],
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a Teamcenter item using a configurable endpoint."""
    return tools.create_item(payload, path=path)


@mcp.tool()
def update_item(
    item_id: str,
    payload: Dict[str, Any],
    method: str = "PATCH",
    path_template: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a Teamcenter item using a configurable endpoint."""
    return tools.update_item(
        item_id, payload, method=method, path_template=path_template
    )


# Register tools on MCPJsonRpcServer with JSON Schemas
json_rpc_server.register_tool(
    "normalize_bom",
    "Normalize raw BOM rows into canonical schema with unit conversions",
    tools.NORMALIZE_BOM_SCHEMA,
    tools.normalize_bom,
)

json_rpc_server.register_tool(
    "profile_columns",
    "Profile BOM column data distributions and infer semantic fields",
    tools.PROFILE_COLUMNS_SCHEMA,
    tools.profile_columns,
)

json_rpc_server.register_tool(
    "compare_snapshots",
    "Compare two BOM snapshots and produce field-level diffs and typed change events",
    tools.COMPARE_SNAPSHOTS_SCHEMA,
    tools.compare_snapshots,
)

json_rpc_server.register_tool(
    "health_check",
    "Check connectivity to Teamcenter REST endpoint",
    tools.HEALTH_CHECK_SCHEMA,
    tools.health_check,
)

json_rpc_server.register_tool(
    "request",
    "Send an arbitrary Teamcenter REST request",
    tools.REQUEST_SCHEMA,
    tools.request,
)

json_rpc_server.register_tool(
    "search_items",
    "Search for items via a configurable Teamcenter search endpoint",
    tools.SEARCH_ITEMS_SCHEMA,
    tools.search_items,
)

json_rpc_server.register_tool(
    "get_item",
    "Fetch a Teamcenter item by ID using a configurable path template",
    tools.GET_ITEM_SCHEMA,
    tools.get_item,
)

json_rpc_server.register_tool(
    "create_item",
    "Create a Teamcenter item using a configurable endpoint",
    tools.CREATE_ITEM_SCHEMA,
    tools.create_item,
)

json_rpc_server.register_tool(
    "update_item",
    "Update a Teamcenter item using a configurable endpoint",
    tools.UPDATE_ITEM_SCHEMA,
    tools.update_item,
)


def handle_jsonrpc(payload: Any) -> Dict[str, Any]:
    """Helper entrypoint to process JSON-RPC requests via json_rpc_server."""
    return json_rpc_server.handle_request(payload)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
