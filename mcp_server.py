#!/usr/bin/env python3
"""
GitLab MCP server — implements the Model Context Protocol (MCP) over stdio
using JSON-RPC 2.0, as required by VS Code Copilot and other MCP-compatible
AI assistants.

Required environment variables:
  GITLAB_URL   – GitLab API v4 base URL  (e.g. https://gitlab.example.com/api/v4)
  GITLAB_TOKEN – GitLab Personal Access Token with api scope
"""
import sys
import json
import os
import requests

GITLAB_URL = os.environ.get("GITLAB_URL")
GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN")

if not GITLAB_URL or not GITLAB_TOKEN:
    sys.stderr.write("Error: GITLAB_URL and GITLAB_TOKEN must be set\n")
    sys.exit(1)

HEADERS = {"PRIVATE-TOKEN": GITLAB_TOKEN}

_SERVER_INFO = {"name": "gitlab-mcp-server", "version": "1.0.0"}
_PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "list_merge_requests",
        "description": "List open merge requests in a GitLab project",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "GitLab project ID or URL-encoded namespace/path (e.g. mygroup%2Fmyrepo)"
                }
            },
            "required": ["project"]
        }
    },
    {
        "name": "list_issues",
        "description": "List issues in a GitLab project",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "GitLab project ID or URL-encoded namespace/path"
                }
            },
            "required": ["project"]
        }
    },
    {
        "name": "list_pipelines",
        "description": "List recent pipelines in a GitLab project",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "GitLab project ID or URL-encoded namespace/path"
                }
            },
            "required": ["project"]
        }
    }
]

# ---------------------------------------------------------------------------
# Transport helpers
# ---------------------------------------------------------------------------

def send(message: dict) -> None:
    """Write a single JSON-RPC message to stdout."""
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def send_result(request_id, result: dict) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def send_error(request_id, code: int, message: str) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


# ---------------------------------------------------------------------------
# GitLab API tool implementations
# ---------------------------------------------------------------------------

def list_merge_requests(project: str):
    url = f"{GITLAB_URL}/projects/{project}/merge_requests?state=opened"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return [{"id": mr["iid"], "title": mr["title"]} for mr in resp.json()]


def list_issues(project: str):
    url = f"{GITLAB_URL}/projects/{project}/issues"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return [{"id": issue["iid"], "title": issue["title"]} for issue in resp.json()]


def list_pipelines(project: str):
    url = f"{GITLAB_URL}/projects/{project}/pipelines"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return [{"id": pl["id"], "status": pl["status"], "ref": pl["ref"]} for pl in resp.json()]


# ---------------------------------------------------------------------------
# MCP request handlers
# ---------------------------------------------------------------------------

_ALLOWED_TOOLS = frozenset({"list_merge_requests", "list_issues", "list_pipelines"})


def handle_initialize(request_id, params: dict) -> None:
    send_result(request_id, {
        "protocolVersion": _PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": _SERVER_INFO,
    })


def handle_tools_list(request_id) -> None:
    send_result(request_id, {"tools": TOOLS})


def handle_tools_call(request_id, params: dict) -> None:
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    project = arguments.get("project")

    if not project:
        send_error(request_id, -32602, "Missing required argument: 'project'")
        return

    if tool_name not in _ALLOWED_TOOLS:
        send_error(request_id, -32601, f"Unknown tool: {tool_name}")
        return

    # Resolve via globals() at call time so unittest.mock.patch works in tests.
    fn = globals()[tool_name]
    try:
        data = fn(project)
        send_result(request_id, {
            "content": [{"type": "text", "text": json.dumps(data, indent=2)}]
        })
    except requests.RequestException as e:
        # Per MCP spec, tool-level errors are returned as results with isError=True,
        # not as JSON-RPC errors.
        send_result(request_id, {
            "content": [{"type": "text", "text": f"GitLab API error: {e}"}],
            "isError": True,
        })


# ---------------------------------------------------------------------------
# Main dispatch loop
# ---------------------------------------------------------------------------

def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            send_error(None, -32700, "Parse error: invalid JSON")
            continue

        method = message.get("method", "")
        request_id = message.get("id")   # None for notifications
        params = message.get("params") or {}

        # Notifications have no id and must not receive a response.
        if request_id is None:
            continue

        if method == "initialize":
            handle_initialize(request_id, params)
        elif method == "tools/list":
            handle_tools_list(request_id)
        elif method == "tools/call":
            handle_tools_call(request_id, params)
        else:
            send_error(request_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()