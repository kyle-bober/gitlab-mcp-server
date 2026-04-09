"""
Integration tests for the mcp_server main() dispatch loop.

main() is exercised in-process by injecting a StringIO as sys.stdin and
capturing sys.stdout via pytest's capsys fixture. All GitLab HTTP calls are
mocked so no network access is required.

The server implements MCP over JSON-RPC 2.0. Each test sends one or more
JSON-RPC messages and validates the JSON-RPC responses.
"""
import io
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

import mcp_server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Standard JSON-RPC messages used across tests
_INIT_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
}
_INITIALIZED_NOTIFICATION = {
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
}


def _run_main(*messages, capsys):
    """
    Run mcp_server.main() with the given JSON-RPC messages as stdin lines.
    Returns all JSON objects written to stdout as a list of dicts.
    """
    parts = [json.dumps(m) for m in messages]
    stdin_text = ("\n".join(parts) + "\n") if parts else ""
    with patch("sys.stdin", io.StringIO(stdin_text)):
        mcp_server.main()
    output = capsys.readouterr().out
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def _call_request(tool_name, project, req_id=1):
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {"project": project}},
    }


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------

class TestInitialize:
    def test_returns_jsonrpc_result(self, capsys):
        outputs = _run_main(_INIT_REQUEST, capsys=capsys)
        assert outputs[0]["jsonrpc"] == "2.0"
        assert "result" in outputs[0]

    def test_returns_protocol_version(self, capsys):
        outputs = _run_main(_INIT_REQUEST, capsys=capsys)
        assert outputs[0]["result"]["protocolVersion"] == "2024-11-05"

    def test_returns_tools_capability(self, capsys):
        outputs = _run_main(_INIT_REQUEST, capsys=capsys)
        assert "tools" in outputs[0]["result"]["capabilities"]

    def test_returns_server_info(self, capsys):
        outputs = _run_main(_INIT_REQUEST, capsys=capsys)
        assert outputs[0]["result"]["serverInfo"]["name"] == "gitlab-mcp-server"

    def test_echoes_request_id(self, capsys):
        req = {**_INIT_REQUEST, "id": 42}
        outputs = _run_main(req, capsys=capsys)
        assert outputs[0]["id"] == 42

    def test_no_output_with_empty_stdin(self, capsys):
        outputs = _run_main(capsys=capsys)
        assert len(outputs) == 0


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------

class TestToolsList:
    def test_returns_tools_list(self, capsys):
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        outputs = _run_main(req, capsys=capsys)
        assert "tools" in outputs[0]["result"]

    def test_returns_all_three_tools(self, capsys):
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        outputs = _run_main(req, capsys=capsys)
        names = {t["name"] for t in outputs[0]["result"]["tools"]}
        assert names == {"list_merge_requests", "list_issues", "list_pipelines"}

    def test_each_tool_has_input_schema(self, capsys):
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        outputs = _run_main(req, capsys=capsys)
        for tool in outputs[0]["result"]["tools"]:
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"
            assert "project" in tool["inputSchema"]["properties"]
            assert "project" in tool["inputSchema"]["required"]

    def test_echoes_request_id(self, capsys):
        req = {"jsonrpc": "2.0", "id": 99, "method": "tools/list"}
        outputs = _run_main(req, capsys=capsys)
        assert outputs[0]["id"] == 99


# ---------------------------------------------------------------------------
# tools/call — routing
# ---------------------------------------------------------------------------

class TestToolsCallRouting:
    def test_routes_list_merge_requests(self, capsys):
        mr_data = [{"id": 1, "title": "MR One"}]
        with patch("mcp_server.list_merge_requests", return_value=mr_data) as mock_fn:
            outputs = _run_main(_call_request("list_merge_requests", "42"), capsys=capsys)
            mock_fn.assert_called_once_with("42")

        assert json.loads(outputs[0]["result"]["content"][0]["text"]) == mr_data

    def test_routes_list_issues(self, capsys):
        issue_data = [{"id": 10, "title": "A bug"}]
        with patch("mcp_server.list_issues", return_value=issue_data) as mock_fn:
            outputs = _run_main(_call_request("list_issues", "7"), capsys=capsys)
            mock_fn.assert_called_once_with("7")

        assert json.loads(outputs[0]["result"]["content"][0]["text"]) == issue_data

    def test_routes_list_pipelines(self, capsys):
        pipeline_data = [{"id": 100, "status": "success", "ref": "main"}]
        with patch("mcp_server.list_pipelines", return_value=pipeline_data) as mock_fn:
            outputs = _run_main(_call_request("list_pipelines", "5"), capsys=capsys)
            mock_fn.assert_called_once_with("5")

        assert json.loads(outputs[0]["result"]["content"][0]["text"]) == pipeline_data

    def test_result_content_is_text_type(self, capsys):
        with patch("mcp_server.list_issues", return_value=[]):
            outputs = _run_main(_call_request("list_issues", "1"), capsys=capsys)
        assert outputs[0]["result"]["content"][0]["type"] == "text"

    def test_echoes_request_id(self, capsys):
        with patch("mcp_server.list_merge_requests", return_value=[]):
            outputs = _run_main(_call_request("list_merge_requests", "1", req_id=77), capsys=capsys)
        assert outputs[0]["id"] == 77


# ---------------------------------------------------------------------------
# tools/call — missing project argument
# ---------------------------------------------------------------------------

class TestMissingProjectArgument:
    def test_returns_error_when_project_missing(self, capsys):
        req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "list_merge_requests", "arguments": {}}}
        outputs = _run_main(req, capsys=capsys)
        assert "error" in outputs[0]

    def test_error_code_is_invalid_params(self, capsys):
        req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "list_issues", "arguments": {}}}
        outputs = _run_main(req, capsys=capsys)
        assert outputs[0]["error"]["code"] == -32602

    def test_error_message_mentions_project(self, capsys):
        req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "list_pipelines", "arguments": {}}}
        outputs = _run_main(req, capsys=capsys)
        assert "project" in outputs[0]["error"]["message"].lower()

    def test_echoes_request_id_in_error(self, capsys):
        req = {"jsonrpc": "2.0", "id": 55, "method": "tools/call",
               "params": {"name": "list_issues", "arguments": {}}}
        outputs = _run_main(req, capsys=capsys)
        assert outputs[0]["id"] == 55


# ---------------------------------------------------------------------------
# tools/call — unknown tool
# ---------------------------------------------------------------------------

class TestUnknownTool:
    def test_returns_error_for_unknown_tool(self, capsys):
        req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "delete_everything", "arguments": {"project": "1"}}}
        outputs = _run_main(req, capsys=capsys)
        assert "error" in outputs[0]

    def test_error_code_is_method_not_found(self, capsys):
        req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "nonexistent", "arguments": {"project": "1"}}}
        outputs = _run_main(req, capsys=capsys)
        assert outputs[0]["error"]["code"] == -32601

    def test_server_continues_after_unknown_tool(self, capsys):
        with patch("mcp_server.list_issues", return_value=[{"id": 1, "title": "ok"}]):
            outputs = _run_main(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "nonexistent", "arguments": {"project": "1"}}},
                _call_request("list_issues", "1", req_id=2),
                capsys=capsys,
            )
        assert "error" in outputs[0]
        assert "result" in outputs[1]


# ---------------------------------------------------------------------------
# Unknown method
# ---------------------------------------------------------------------------

class TestUnknownMethod:
    def test_returns_method_not_found_error(self, capsys):
        req = {"jsonrpc": "2.0", "id": 1, "method": "resources/list"}
        outputs = _run_main(req, capsys=capsys)
        assert outputs[0]["error"]["code"] == -32601

    def test_error_includes_method_name(self, capsys):
        req = {"jsonrpc": "2.0", "id": 1, "method": "resources/list"}
        outputs = _run_main(req, capsys=capsys)
        assert "resources/list" in outputs[0]["error"]["message"]


# ---------------------------------------------------------------------------
# Notifications (no id → no response)
# ---------------------------------------------------------------------------

class TestNotifications:
    def test_initialized_notification_produces_no_output(self, capsys):
        outputs = _run_main(_INITIALIZED_NOTIFICATION, capsys=capsys)
        assert len(outputs) == 0

    def test_server_handles_notification_then_real_request(self, capsys):
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        outputs = _run_main(_INITIALIZED_NOTIFICATION, req, capsys=capsys)
        assert len(outputs) == 1
        assert "tools" in outputs[0]["result"]

    def test_any_message_without_id_is_a_notification(self, capsys):
        msg = {"jsonrpc": "2.0", "method": "custom/event"}
        outputs = _run_main(msg, capsys=capsys)
        assert len(outputs) == 0


# ---------------------------------------------------------------------------
# Invalid JSON
# ---------------------------------------------------------------------------

class TestInvalidJson:
    def test_returns_parse_error_code(self, capsys):
        with patch("sys.stdin", io.StringIO("this is not json\n")):
            mcp_server.main()
        lines = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip()]
        assert lines[0]["error"]["code"] == -32700

    def test_server_continues_after_invalid_json(self, capsys):
        stdin_text = (
            "bad json\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
        )
        with patch("sys.stdin", io.StringIO(stdin_text)):
            mcp_server.main()
        lines = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip()]
        assert lines[0]["error"]["code"] == -32700
        assert "tools" in lines[1]["result"]

    def test_blank_lines_are_ignored(self, capsys):
        stdin_text = "\n\n" + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
        with patch("sys.stdin", io.StringIO(stdin_text)):
            mcp_server.main()
        lines = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip()]
        assert len(lines) == 1
        assert "tools" in lines[0]["result"]


# ---------------------------------------------------------------------------
# GitLab API errors
# ---------------------------------------------------------------------------

class TestGitLabApiError:
    def test_http_error_returns_is_error_result(self, capsys):
        with patch("mcp_server.list_merge_requests", side_effect=requests.HTTPError("404")):
            outputs = _run_main(_call_request("list_merge_requests", "missing"), capsys=capsys)
        assert outputs[0]["result"]["isError"] is True
        assert "GitLab API error" in outputs[0]["result"]["content"][0]["text"]

    def test_api_error_is_a_result_not_a_jsonrpc_error(self, capsys):
        """Per MCP spec, tool errors are results with isError=True, not JSON-RPC errors."""
        with patch("mcp_server.list_issues", side_effect=requests.HTTPError("500")):
            outputs = _run_main(_call_request("list_issues", "1"), capsys=capsys)
        assert "result" in outputs[0]
        assert "error" not in outputs[0]

    def test_server_continues_after_api_error(self, capsys):
        with patch("mcp_server.list_merge_requests", side_effect=requests.HTTPError("500")), \
             patch("mcp_server.list_issues", return_value=[{"id": 5, "title": "fine"}]):
            outputs = _run_main(
                _call_request("list_merge_requests", "bad"),
                _call_request("list_issues", "good", req_id=2),
                capsys=capsys,
            )
        assert outputs[0]["result"]["isError"] is True
        assert "result" in outputs[1]


# ---------------------------------------------------------------------------
# Full MCP handshake sequence
# ---------------------------------------------------------------------------

class TestFullHandshake:
    def test_initialize_then_tools_list_then_call(self, capsys):
        mr_data = [{"id": 1, "title": "MR"}]
        with patch("mcp_server.list_merge_requests", return_value=mr_data):
            outputs = _run_main(
                _INIT_REQUEST,
                _INITIALIZED_NOTIFICATION,                      # no response
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                _call_request("list_merge_requests", "1", req_id=3),
                capsys=capsys,
            )
        # notification produces no output → 3 responses total
        assert len(outputs) == 3
        assert "protocolVersion" in outputs[0]["result"]
        assert "tools" in outputs[1]["result"]
        assert json.loads(outputs[2]["result"]["content"][0]["text"]) == mr_data


