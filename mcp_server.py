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
import base64
import requests
from urllib.parse import quote

GITLAB_URL = os.environ.get("GITLAB_URL")
GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN")

if not GITLAB_URL or not GITLAB_TOKEN:
    sys.stderr.write("Error: GITLAB_URL and GITLAB_TOKEN must be set\n")
    sys.exit(1)

HEADERS = {"PRIVATE-TOKEN": GITLAB_TOKEN}

_SERVER_INFO = {"name": "gitlab-mcp-server", "version": "1.0.0"}
_PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    # ── Existing ───────────────────────────────────────────────────────────
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
    },
    # ── read_user ───────────────────────────────────────────────────────────
    {
        "name": "get_current_user",
        "description": "Get the authenticated user's profile (id, username, name, email)",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # ── read_api: projects & groups ─────────────────────────────────────────
    {
        "name": "list_projects",
        "description": "List projects the authenticated user is a member of, with optional search",
        "inputSchema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Optional keyword to filter projects by name"}
            }
        }
    },
    {
        "name": "get_project",
        "description": "Get details of a specific GitLab project (name, default branch, visibility)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"}
            },
            "required": ["project"]
        }
    },
    {
        "name": "list_groups",
        "description": "List GitLab groups the authenticated user has access to",
        "inputSchema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Optional keyword to filter groups by name"}
            }
        }
    },
    {
        "name": "list_project_members",
        "description": "List all members of a GitLab project including inherited members",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"}
            },
            "required": ["project"]
        }
    },
    {
        "name": "list_releases",
        "description": "List releases for a GitLab project",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"}
            },
            "required": ["project"]
        }
    },
    # ── read_api: merge requests ────────────────────────────────────────────
    {
        "name": "get_merge_request",
        "description": "Get full details of a specific merge request (description, labels, branches, author)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"},
                "iid": {"type": "integer", "description": "Merge request internal ID (iid)"}
            },
            "required": ["project", "iid"]
        }
    },
    {
        "name": "list_merge_request_notes",
        "description": "List comments/notes on a merge request",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"},
                "iid": {"type": "integer", "description": "Merge request internal ID (iid)"}
            },
            "required": ["project", "iid"]
        }
    },
    # ── read_api: pipelines & jobs ──────────────────────────────────────────
    {
        "name": "get_pipeline",
        "description": "Get details of a specific pipeline (status, ref, sha, timestamps)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"},
                "pipeline_id": {"type": "integer", "description": "Pipeline ID"}
            },
            "required": ["project", "pipeline_id"]
        }
    },
    {
        "name": "list_pipeline_jobs",
        "description": "List jobs in a specific pipeline with their status and stage",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"},
                "pipeline_id": {"type": "integer", "description": "Pipeline ID"}
            },
            "required": ["project", "pipeline_id"]
        }
    },
    # ── read_repository ─────────────────────────────────────────────────────
    {
        "name": "list_branches",
        "description": "List branches in a GitLab project repository",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"}
            },
            "required": ["project"]
        }
    },
    {
        "name": "list_tags",
        "description": "List tags in a GitLab project repository",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"}
            },
            "required": ["project"]
        }
    },
    {
        "name": "list_commits",
        "description": "List commits in a GitLab project repository, optionally filtered by branch or tag",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"},
                "ref_name": {"type": "string", "description": "Branch, tag, or commit SHA to list commits from (default: default branch)"}
            },
            "required": ["project"]
        }
    },
    {
        "name": "get_file",
        "description": "Get the decoded content of a file from a GitLab project repository",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"},
                "file_path": {"type": "string", "description": "Path to the file within the repository (e.g. src/main.py)"},
                "ref": {"type": "string", "description": "Branch, tag, or commit SHA to read from (default: HEAD)"}
            },
            "required": ["project", "file_path"]
        }
    },
    {
        "name": "list_repository_tree",
        "description": "List files and directories in a GitLab project repository at a given path",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"},
                "path": {"type": "string", "description": "Directory path within the repository (default: root)"},
                "ref": {"type": "string", "description": "Branch, tag, or commit SHA (default: default branch)"}
            },
            "required": ["project"]
        }
    },
    {
        "name": "compare_refs",
        "description": "Compare two branches, tags, or commits and return a diff summary",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"},
                "from_ref": {"type": "string", "description": "Source ref (branch, tag, or commit SHA)"},
                "to_ref": {"type": "string", "description": "Target ref (branch, tag, or commit SHA)"}
            },
            "required": ["project", "from_ref", "to_ref"]
        }
    },
    # ── read_registry ───────────────────────────────────────────────────────
    {
        "name": "list_registry_repositories",
        "description": "List container registry repositories for a GitLab project",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"}
            },
            "required": ["project"]
        }
    },
    {
        "name": "list_registry_tags",
        "description": "List tags for a specific container registry repository",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"},
                "repository_id": {"type": "integer", "description": "Container registry repository ID"}
            },
            "required": ["project", "repository_id"]
        }
    },
    # ── read_virtual_registry (packages) ────────────────────────────────────
    {
        "name": "list_packages",
        "description": "List packages in a GitLab project package registry",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "GitLab project ID or URL-encoded namespace/path"}
            },
            "required": ["project"]
        }
    },
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


# -- read_user ----------------------------------------------------------------

def get_current_user():
    resp = requests.get(f"{GITLAB_URL}/user", headers=HEADERS)
    resp.raise_for_status()
    u = resp.json()
    return {"id": u["id"], "username": u["username"], "name": u["name"], "email": u.get("email", "")}


# -- read_api: projects & groups ----------------------------------------------

def list_projects(search: str = None):
    params = "membership=true"
    if search:
        params += f"&search={search}"
    resp = requests.get(f"{GITLAB_URL}/projects?{params}", headers=HEADERS)
    resp.raise_for_status()
    return [
        {"id": p["id"], "name": p["name"], "path_with_namespace": p["path_with_namespace"]}
        for p in resp.json()
    ]


def get_project(project: str):
    resp = requests.get(f"{GITLAB_URL}/projects/{project}", headers=HEADERS)
    resp.raise_for_status()
    p = resp.json()
    return {
        "id": p["id"],
        "name": p["name"],
        "path_with_namespace": p["path_with_namespace"],
        "description": p.get("description"),
        "default_branch": p.get("default_branch"),
        "visibility": p.get("visibility"),
        "web_url": p.get("web_url"),
    }


def list_groups(search: str = None):
    params = "min_access_level=10"
    if search:
        params += f"&search={search}"
    resp = requests.get(f"{GITLAB_URL}/groups?{params}", headers=HEADERS)
    resp.raise_for_status()
    return [{"id": g["id"], "name": g["name"], "full_path": g["full_path"]} for g in resp.json()]


def list_project_members(project: str):
    resp = requests.get(f"{GITLAB_URL}/projects/{project}/members/all", headers=HEADERS)
    resp.raise_for_status()
    return [
        {"id": m["id"], "username": m["username"], "name": m["name"], "access_level": m["access_level"]}
        for m in resp.json()
    ]


def list_releases(project: str):
    resp = requests.get(f"{GITLAB_URL}/projects/{project}/releases", headers=HEADERS)
    resp.raise_for_status()
    return [
        {"tag_name": r["tag_name"], "name": r["name"], "released_at": r.get("released_at")}
        for r in resp.json()
    ]


# -- read_api: merge requests -------------------------------------------------

def get_merge_request(project: str, iid: int):
    resp = requests.get(f"{GITLAB_URL}/projects/{project}/merge_requests/{iid}", headers=HEADERS)
    resp.raise_for_status()
    mr = resp.json()
    return {
        "iid": mr["iid"],
        "title": mr["title"],
        "description": mr.get("description"),
        "state": mr.get("state"),
        "author": mr.get("author", {}).get("username"),
        "source_branch": mr.get("source_branch"),
        "target_branch": mr.get("target_branch"),
        "labels": mr.get("labels", []),
        "web_url": mr.get("web_url"),
    }


def list_merge_request_notes(project: str, iid: int):
    resp = requests.get(
        f"{GITLAB_URL}/projects/{project}/merge_requests/{iid}/notes", headers=HEADERS
    )
    resp.raise_for_status()
    return [
        {"id": n["id"], "author": n.get("author", {}).get("username"), "body": n["body"]}
        for n in resp.json()
    ]


# -- read_api: pipelines & jobs -----------------------------------------------

def get_pipeline(project: str, pipeline_id: int):
    resp = requests.get(f"{GITLAB_URL}/projects/{project}/pipelines/{pipeline_id}", headers=HEADERS)
    resp.raise_for_status()
    pl = resp.json()
    return {
        "id": pl["id"],
        "status": pl["status"],
        "ref": pl["ref"],
        "sha": pl.get("sha"),
        "web_url": pl.get("web_url"),
        "created_at": pl.get("created_at"),
        "updated_at": pl.get("updated_at"),
    }


def list_pipeline_jobs(project: str, pipeline_id: int):
    resp = requests.get(
        f"{GITLAB_URL}/projects/{project}/pipelines/{pipeline_id}/jobs", headers=HEADERS
    )
    resp.raise_for_status()
    return [
        {"id": j["id"], "name": j["name"], "status": j["status"], "stage": j["stage"], "web_url": j.get("web_url")}
        for j in resp.json()
    ]


# -- read_repository ----------------------------------------------------------

def list_branches(project: str):
    resp = requests.get(f"{GITLAB_URL}/projects/{project}/repository/branches", headers=HEADERS)
    resp.raise_for_status()
    return [
        {"name": b["name"], "merged": b.get("merged", False), "protected": b.get("protected", False)}
        for b in resp.json()
    ]


def list_tags(project: str):
    resp = requests.get(f"{GITLAB_URL}/projects/{project}/repository/tags", headers=HEADERS)
    resp.raise_for_status()
    return [
        {"name": t["name"], "message": t.get("message"), "commit": t.get("commit", {}).get("id")}
        for t in resp.json()
    ]


def list_commits(project: str, ref_name: str = None):
    url = f"{GITLAB_URL}/projects/{project}/repository/commits"
    if ref_name:
        url += f"?ref_name={ref_name}"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return [
        {
            "id": c["id"],
            "short_id": c["short_id"],
            "title": c["title"],
            "author_name": c["author_name"],
            "created_at": c["created_at"],
        }
        for c in resp.json()
    ]


def get_file(project: str, file_path: str, ref: str = "HEAD"):
    encoded_path = quote(file_path, safe="")
    url = f"{GITLAB_URL}/projects/{project}/repository/files/{encoded_path}?ref={ref}"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    f = resp.json()
    if f.get("encoding") == "base64":
        content = base64.b64decode(f["content"]).decode("utf-8")
    else:
        content = f.get("content", "")
    return {"file_path": f["file_path"], "ref": f["ref"], "encoding": f.get("encoding"), "content": content}


def list_repository_tree(project: str, path: str = None, ref: str = None):
    params = []
    if path:
        params.append(f"path={path}")
    if ref:
        params.append(f"ref={ref}")
    query = "&".join(params)
    url = f"{GITLAB_URL}/projects/{project}/repository/tree" + (f"?{query}" if query else "")
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return [
        {"id": item["id"], "name": item["name"], "type": item["type"], "path": item["path"]}
        for item in resp.json()
    ]


def compare_refs(project: str, from_ref: str, to_ref: str):
    url = f"{GITLAB_URL}/projects/{project}/repository/compare?from={from_ref}&to={to_ref}"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()
    return {
        "commit": (data.get("commit") or {}).get("id"),
        "commits": [{"id": c["id"], "title": c["title"]} for c in data.get("commits", [])],
        "diffs_count": len(data.get("diffs", [])),
        "compare_same_ref": data.get("compare_same_ref", False),
    }


# -- read_registry ------------------------------------------------------------

def list_registry_repositories(project: str):
    resp = requests.get(f"{GITLAB_URL}/projects/{project}/registry/repositories", headers=HEADERS)
    resp.raise_for_status()
    return [
        {"id": r["id"], "name": r.get("name"), "path": r.get("path"), "location": r.get("location")}
        for r in resp.json()
    ]


def list_registry_tags(project: str, repository_id: int):
    resp = requests.get(
        f"{GITLAB_URL}/projects/{project}/registry/repositories/{repository_id}/tags",
        headers=HEADERS,
    )
    resp.raise_for_status()
    return [
        {"name": t["name"], "path": t.get("path"), "location": t.get("location")}
        for t in resp.json()
    ]


# -- read_virtual_registry (packages) -----------------------------------------

def list_packages(project: str):
    resp = requests.get(f"{GITLAB_URL}/projects/{project}/packages", headers=HEADERS)
    resp.raise_for_status()
    return [
        {"id": p["id"], "name": p["name"], "version": p.get("version"), "package_type": p.get("package_type")}
        for p in resp.json()
    ]


# ---------------------------------------------------------------------------
# MCP request handlers
# ---------------------------------------------------------------------------

_ALLOWED_TOOLS = frozenset({
    "list_merge_requests", "list_issues", "list_pipelines",
    "get_current_user",
    "list_projects", "get_project", "list_groups", "list_project_members", "list_releases",
    "get_merge_request", "list_merge_request_notes",
    "get_pipeline", "list_pipeline_jobs",
    "list_branches", "list_tags", "list_commits", "get_file", "list_repository_tree", "compare_refs",
    "list_registry_repositories", "list_registry_tags",
    "list_packages",
})


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

    if tool_name not in _ALLOWED_TOOLS:
        send_error(request_id, -32601, f"Unknown tool: {tool_name}")
        return

    # Resolve via globals() at call time so unittest.mock.patch works in tests.
    fn = globals()[tool_name]
    try:
        data = fn(**arguments)
        send_result(request_id, {
            "content": [{"type": "text", "text": json.dumps(data, indent=2)}]
        })
    except TypeError as e:
        # Missing or unexpected arguments — surface as invalid params JSON-RPC error.
        send_error(request_id, -32602, f"Invalid arguments: {e}")
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