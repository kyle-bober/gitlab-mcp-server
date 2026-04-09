# GitLab MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that exposes GitLab project data as tools consumable by AI assistants (e.g., GitHub Copilot, Claude Desktop).

## Tools

### User (`read_user`)

| Tool | Description | Parameters |
|---|---|---|
| `get_current_user` | Get the authenticated user's profile | *(none)* |

### Projects & Groups (`read_api`)

| Tool | Description | Parameters |
|---|---|---|
| `list_projects` | List projects the authenticated user is a member of | `search` (optional) |
| `get_project` | Get details of a specific project | `project` |
| `list_groups` | List groups the authenticated user has access to | `search` (optional) |
| `list_project_members` | List all members of a project (including inherited) | `project` |
| `list_releases` | List releases for a project | `project` |

### Merge Requests (`read_api`)

| Tool | Description | Parameters |
|---|---|---|
| `list_merge_requests` | List open merge requests in a project | `project` |
| `get_merge_request` | Get full details of a specific merge request | `project`, `iid` |
| `list_merge_request_notes` | List comments/notes on a merge request | `project`, `iid` |

### Issues (`read_api`)

| Tool | Description | Parameters |
|---|---|---|
| `list_issues` | List issues in a project | `project` |

### Pipelines & Jobs (`read_api`)

| Tool | Description | Parameters |
|---|---|---|
| `list_pipelines` | List recent pipelines in a project | `project` |
| `get_pipeline` | Get details of a specific pipeline | `project`, `pipeline_id` |
| `list_pipeline_jobs` | List jobs in a specific pipeline | `project`, `pipeline_id` |

### Repository (`read_repository`)

| Tool | Description | Parameters |
|---|---|---|
| `list_branches` | List branches in a project repository | `project` |
| `list_tags` | List tags in a project repository | `project` |
| `list_commits` | List commits, optionally filtered by branch/tag | `project`, `ref_name` (optional) |
| `get_file` | Get the decoded content of a file | `project`, `file_path`, `ref` (optional, default: `HEAD`) |
| `list_repository_tree` | List files and directories at a given path | `project`, `path` (optional), `ref` (optional) |
| `compare_refs` | Compare two branches/tags/commits and return a diff summary | `project`, `from_ref`, `to_ref` |

### Container Registry (`read_registry`)

| Tool | Description | Parameters |
|---|---|---|
| `list_registry_repositories` | List container registry repositories for a project | `project` |
| `list_registry_tags` | List tags for a specific registry repository | `project`, `repository_id` |

### Package Registry (`read_virtual_registry`)

| Tool | Description | Parameters |
|---|---|---|
| `list_packages` | List packages in the project package registry | `project` |

The `project` parameter accepts a GitLab project ID (integer) or URL-encoded namespace/path (e.g., `mygroup%2Fmyrepo`).

## Requirements

- Python 3.8+

Runtime dependencies are listed in `requirements.txt` and are automatically installed into an isolated virtual environment when you run `start_server.sh` (see [Usage](#usage)).

To install them manually:

```bash
pip install -r requirements.txt
```

For running tests:

```bash
pip install -r requirements-test.txt
```

## Configuration

The server reads configuration from two environment variables:

| Variable | Description | Example |
|---|---|---|
| `GITLAB_URL` | Base URL of the GitLab API (v4) | `https://gitlab.example.com/api/v4` |
| `GITLAB_TOKEN` | GitLab Personal Access Token with required scopes (see below) | `glpat-xxxxxxxxxxxxxxxxxxxx` |

**Required PAT scopes:** `read_user`, `read_api`, `read_repository`, `read_registry`, `read_virtual_registry`

Export them before starting the server:

```bash
export GITLAB_URL=https://gitlab.example.com/api/v4
export GITLAB_TOKEN=your-personal-access-token
```

## Usage

### Start the server

```bash
./start_server.sh
```

On first run the script will:
1. Create a `.venv` virtual environment inside the project directory
2. Install the packages from `requirements.txt` into that venv
3. Launch `mcp_server.py` using the venv's Python interpreter

Subsequent runs reuse the existing venv and re-run the `pip install` step (which is a no-op if dependencies are already satisfied), so startup stays fast.

Or run manually (bring your own environment):

```bash
python3 mcp_server.py
```

### Protocol

The server implements the [Model Context Protocol (MCP)](https://spec.modelcontextprotocol.io/) over stdio using **JSON-RPC 2.0**, which is the standard expected by VS Code Copilot, Claude Desktop, and other MCP clients.

**Handshake sequence (performed automatically by MCP clients):**

1. Client → `initialize`
2. Server → `initialize` result (protocolVersion, capabilities, serverInfo)
3. Client → `notifications/initialized` *(notification — no response)*
4. Client → `tools/list`
5. Server → tools list

**Call a tool:**

```json
{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_merge_requests", "arguments": {"project": "123"}}}
```

**Response:**

```json
{"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": "[{\"id\": 42, \"title\": \"Fix bug\"}]"}]}}
```

**Error response (e.g. invalid or missing parameter):**

```json
{"jsonrpc": "2.0", "id": 3, "error": {"code": -32602, "message": "Invalid arguments: ..."}}
```

GitLab API failures are returned as results with `"isError": true` rather than JSON-RPC errors, per the MCP specification.

### VS Code / Copilot MCP Configuration

Add to your `mcp.json`:

```json
{
  "servers": {
    "gitlab": {
      "type": "stdio",
      "command": "/path/to/gitlab-mcp-server/start_server.sh",
      "env": {
        "GITLAB_URL": "https://gitlab.example.com/api/v4",
        "GITLAB_TOKEN": "your-personal-access-token"
      }
    }
  }
}
```

## Testing

The test suite has 152 tests across three layers. No network calls are made — all GitLab HTTP interactions are mocked.

```bash
python -m pytest
```

| Layer | File | What it tests |
|---|---|---|
| Unit | `tests/unit/test_tools.py` | All 22 tool functions and `send`/`send_result`/`send_error` helpers in isolation with mocked `requests.get` |
| Integration (in-process) | `tests/integration/test_main_loop.py` | `main()` dispatch loop via injected `sys.stdin` — routing, error handling, resilience after failures |
| Integration (subprocess) | `tests/integration/test_subprocess.py` | Real process spawned via `subprocess.Popen` — env var validation, tool discovery over the wire, wire protocol error paths |

Run a specific layer:

```bash
python -m pytest tests/unit/
python -m pytest tests/integration/
```

---

## Project Structure

```
gitlab-mcp-server/
├── mcp_server.py          # MCP server implementation
├── start_server.sh        # Startup script (bootstraps venv automatically)
├── requirements.txt       # Runtime dependencies
├── requirements-test.txt  # Test-only dependencies
├── pytest.ini             # pytest configuration
├── README.md
├── .venv/                 # Auto-created virtual environment (git-ignored)
└── tests/
    ├── conftest.py        # Shared pytest fixtures and env var setup
    ├── unit/
    │   └── test_tools.py  # Unit tests for tool functions
    └── integration/
        ├── test_main_loop.py   # In-process integration tests for main()
        └── test_subprocess.py  # Subprocess integration tests
```
