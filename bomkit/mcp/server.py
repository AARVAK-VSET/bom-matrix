"""
JSON-RPC 2.0 Protocol Engine and Argument Validator for MCP.

Implements standard JSON-RPC 2.0 request/response processing and argument
validation against declared JSON schemas as specified in Model Context Protocol.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Union

import jsonschema


class JSONRPCError(Exception):
    """Exception representing a JSON-RPC 2.0 error."""

    def __init__(self, code: int, message: str, data: Optional[Any] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            res["data"] = self.data
        return res


@dataclass
class MCPTool:
    """Registered MCP Tool representation."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[..., Any]


class MCPJsonRpcServer:
    """Standard JSON-RPC 2.0 MCP Server with JSON Schema argument validation."""

    def __init__(self, name: str = "bom-matrix", version: str = "1.0.0"):
        self.name = name
        self.version = version
        self.tools: Dict[str, MCPTool] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable[..., Any],
    ) -> None:
        """Register a tool with its JSON schema and execution handler."""
        self.tools[name] = MCPTool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
        )

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return declared tools list matching MCP protocol specification."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in self.tools.values()
        ]

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Validate arguments against tool JSON schema and execute tool.

        Raises:
            JSONRPCError(-32601) if tool not found.
            JSONRPCError(-32602) if schema validation fails.
        """
        if name not in self.tools:
            raise JSONRPCError(-32601, f"Tool '{name}' not found")

        tool = self.tools[name]
        args = arguments if isinstance(arguments, dict) else {}

        # Validate tool arguments against declared JSON schema
        try:
            jsonschema.validate(instance=args, schema=tool.input_schema)
        except jsonschema.ValidationError as err:
            raise JSONRPCError(
                -32602,
                f"Invalid params for tool '{name}': {err.message}",
                data={"path": list(err.path), "schema_path": list(err.schema_path)},
            )
        except jsonschema.SchemaError as err:
            raise JSONRPCError(-32603, f"Invalid JSON schema for tool '{name}': {err.message}")

        try:
            result = tool.handler(**args)
            formatted_text = (
                json.dumps(result, indent=2, default=str)
                if not isinstance(result, str)
                else result
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": formatted_text,
                    }
                ],
                "isError": False,
            }
        except Exception as exc:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error executing tool '{name}': {str(exc)}",
                    }
                ],
                "isError": True,
            }

    def handle_request(
        self, request_payload: Union[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Process a standard JSON-RPC 2.0 request and return structured response."""
        if isinstance(request_payload, str):
            try:
                payload = json.loads(request_payload)
            except Exception as exc:
                return self._make_error_response(
                    None, -32700, f"Parse error: {str(exc)}"
                )
        else:
            payload = request_payload

        if not isinstance(payload, dict):
            return self._make_error_response(
                None, -32600, "Invalid Request: Payload must be a JSON object"
            )

        req_id = payload.get("id")
        jsonrpc = payload.get("jsonrpc")

        if jsonrpc != "2.0":
            return self._make_error_response(
                req_id, -32600, "Invalid Request: 'jsonrpc' must be '2.0'"
            )

        method = payload.get("method")
        params = payload.get("params", {})

        if not method or not isinstance(method, str):
            return self._make_error_response(
                req_id, -32600, "Invalid Request: 'method' string required"
            )

        try:
            if method in {"initialize"}:
                res = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": self.name, "version": self.version},
                }
                return self._make_success_response(req_id, res)

            if method in {"ping"}:
                return self._make_success_response(req_id, {})

            if method in {"tools/list", "list_tools"}:
                return self._make_success_response(req_id, {"tools": self.list_tools()})

            if method in {"tools/call", "call_tool"}:
                if not isinstance(params, dict):
                    raise JSONRPCError(-32602, "Params must be an object")

                tool_name = params.get("name")
                if not tool_name:
                    raise JSONRPCError(-32602, "Tool name is required in params ('name')")

                arguments = params.get("arguments", {})
                if not isinstance(arguments, dict):
                    raise JSONRPCError(-32602, "'arguments' must be an object")

                tool_result = self.call_tool(tool_name, arguments)
                return self._make_success_response(req_id, tool_result)

            raise JSONRPCError(-32601, f"Method '{method}' not found")

        except JSONRPCError as err:
            return self._make_error_response(req_id, err.code, err.message, err.data)
        except Exception as exc:
            return self._make_error_response(req_id, -32603, f"Internal error: {str(exc)}")

    def _make_success_response(self, req_id: Any, result: Any) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
        }

    def _make_error_response(
        self, req_id: Any, code: int, message: str, data: Optional[Any] = None
    ) -> Dict[str, Any]:
        err_dict: Dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err_dict["data"] = data
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": err_dict,
        }
