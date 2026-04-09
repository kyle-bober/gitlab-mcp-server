"""
Subprocess integration tests for mcp_server.py.

These tests spawn the actual server process via subprocess.Popen / subprocess.run,
verifying startup behaviour, environment variable validation, and the MCP JSON-RPC
wire protocol without mocking any Python internals.

GitLab HTTP calls that would reach a real API are avoided by only sending inputs
that trigger pure-logic paths (initialize, tools/list, error cases). Tests that
require real GitLab API responses belong in dedicated E2E tests.
"""
import json
import os
import sys
import subprocess
from pathlib import Path

import pytest

# Absolute path to the server script so tests can be run from any working directory.
MSERVER_PATH = str(Path(__file__).parent.parent.parent / "mcp_server.py")

_BASE_ENV = {k: v for k, v in os.environ.items() if k not in ("GITLAB_URL", "GITLAB_TOKEN")}

_VALID_ENV = {
    **_BASE_ENV,
    "GITLAB_URL": "http://fake-gitlab.test/api/v4",
    "GITLAB_TOKEN": "fake-test-token",
}

# Canned JSON-RPC messages
_INIT_MSG = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
})
_TOOLS_LIST_MSG = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
_INITIALIZED_NOTIFICATION = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _send_and_collect(input_text="", env=None, timeout=5):
    """Start the server, send input_text to stdin, return (parsed_lines, stderr, returncode)."""
    proc = subprocess.Popen(
        [sys.executable, "-u", MSERVER_PATH],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env or _VALID_ENV,
    )
    stdout, stderr = proc.communicate(input=input_text, timeout=timeout)
    lines = [json.loads(l) for l in stdout.splitlines() if l.strip()]
    return lines, stderr, proc.returncode


# ---------------------------------------------------------------------------
# Environment variable validation
# ---------------------------------------------------------------------------

class TestEnvironmentValidation:
    def test_exits_nonzero_when_both_vars_missing(self):
        result = subprocess.run(
            [sys.executable, MSERVER_PATH],
            capture_output=True, text=True, env=_BASE_ENV, timeout=5,
        )
        assert result.returncode == 1

    def test_prints_error_message_to_stderr_when_vars_missing(self):
        result = subprocess.run(
            [sys.executable, MSERVER_PATH],
            capture_output=True, text=True, env=_BASE_ENV, timeout=5,
        )
        assert "GITLAB_URL" in result.stderr
        assert "GITLAB_TOKEN" in result.stderr

    def test_exits_nonzero_when_only_gitlab_url_missing(self):
        env = {**_BASE_ENV, "GITLAB_TOKEN": "some-token"}
        result = subprocess.run(
            [sys.executable, MSERVER_PATH],
            capture_output=True, text=True, env=env, timeout=5,
        )
        assert result.returncode == 1

    def test_exits_nonzero_when_only_gitlab_token_missing(self):
        env = {**_BASE_ENV, "GITLAB_URL": "http://fake.test/api/v4"}
        result = subprocess.run(
            [sys.executable, MSERVER_PATH],
            capture_output=True, text=True, env=env, timeout=5,
        )
        assert result.returncode == 1

    def test_starts_successfully_when_both_vars_present(self):
        _, _, returncode = _send_and_collect(input_text="")
        assert returncode == 0


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------

class TestInitialize:
    def test_responds_to_initialize(self):
        lines, _, _ = _send_and_collect(input_text=_INIT_MSG + "\n")
        assert len(lines) == 1
        assert "result" in lines[0]

    def test_returns_protocol_version(self):
        lines, _, _ = _send_and_collect(input_text=_INIT_MSG + "\n")
        assert lines[0]["result"]["protocolVersion"] == "2024-11-05"

    def test_returns_server_info(self):
        lines, _, _ = _send_and_collect(input_text=_INIT_MSG + "\n")
        assert lines[0]["result"]["serverInfo"]["name"] == "gitlab-mcp-server"

    def test_returns_tools_capability(self):
        lines, _, _ = _send_and_collect(input_text=_INIT_MSG + "\n")
        assert "tools" in lines[0]["result"]["capabilities"]

    def test_no_output_with_empty_stdin(self):
        lines, _, returncode = _send_and_collect(input_text="")
        assert lines == []
        assert returncode == 0


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------

class TestToolsList:
    def test_responds_to_tools_list(self):
        lines, _, _ = _send_and_collect(input_text=_TOOLS_LIST_MSG + "\n")
        assert "tools" in lines[0]["result"]

    def test_returns_all_tools(self):
        lines, _, _ = _send_and_collect(input_text=_TOOLS_LIST_MSG + "\n")
        names = {t["name"] for t in lines[0]["result"]["tools"]}
        assert names == {
            "list_merge_requests", "list_issues", "list_pipelines",
            "get_current_user",
            "list_projects", "get_project", "list_groups", "list_project_members", "list_releases",
            "get_merge_request", "list_merge_request_notes",
            "get_pipeline", "list_pipeline_jobs",
            "list_branches", "list_tags", "list_commits", "get_file", "list_repository_tree", "compare_refs",
            "list_registry_repositories", "list_registry_tags",
            "list_packages",
        }

    def test_each_tool_has_input_schema(self):
        lines, _, _ = _send_and_collect(input_text=_TOOLS_LIST_MSG + "\n")
        for tool in lines[0]["result"]["tools"]:
            assert "inputSchema" in tool


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class TestNotifications:
    def test_initialized_notification_produces_no_output(self):
        lines, _, returncode = _send_and_collect(input_text=_INITIALIZED_NOTIFICATION + "\n")
        assert lines == []
        assert returncode == 0


# ---------------------------------------------------------------------------
# Wire protocol — pure error paths
# ---------------------------------------------------------------------------

class TestWireProtocolErrorPaths:
    def test_invalid_json_returns_parse_error_code(self):
        lines, _, _ = _send_and_collect(input_text="this is not json\n")
        assert lines[0]["error"]["code"] == -32700

    def test_unknown_method_returns_method_not_found(self):
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "resources/list"}) + "\n"
        lines, _, _ = _send_and_collect(input_text=payload)
        assert lines[0]["error"]["code"] == -32601

    def test_missing_project_returns_invalid_params(self):
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "list_merge_requests", "arguments": {}},
        }) + "\n"
        lines, _, _ = _send_and_collect(input_text=payload)
        assert lines[0]["error"]["code"] == -32602

    def test_server_handles_multiple_errors_without_crashing(self):
        stdin = (
            "bad json\n"
            + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "resources/list"}) + "\n"
            + "also bad\n"
        )
        _, _, returncode = _send_and_collect(input_text=stdin)
        assert returncode == 0

    def test_all_output_is_valid_jsonrpc(self):
        """Every output line must be a valid JSON-RPC 2.0 object."""
        stdin = (
            "bad json\n"
            + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "unknown"}) + "\n"
        )
        proc = subprocess.Popen(
            [sys.executable, "-u", MSERVER_PATH],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=_VALID_ENV,
        )
        stdout, _ = proc.communicate(input=stdin, timeout=5)
        for line in stdout.splitlines():
            if line.strip():
                msg = json.loads(line)
                assert msg.get("jsonrpc") == "2.0"

