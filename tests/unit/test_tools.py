"""
Unit tests for mcp_server tool functions and transport helpers.

Each tool function is tested in isolation by patching requests.get.
No network calls are made; no subprocess is spawned.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

import mcp_server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(payload, status_code=200):
    """Build a mock requests.Response that returns *payload* from .json()."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = payload
    # raise_for_status is a no-op for 2xx, so default is fine.
    return mock


def _http_error_response(status_code=404):
    """Build a mock requests.Response whose raise_for_status raises HTTPError."""
    mock = MagicMock()
    mock.raise_for_status.side_effect = requests.HTTPError(
        f"{status_code} Error", response=mock
    )
    return mock


# ---------------------------------------------------------------------------
# send / send_result / send_error
# ---------------------------------------------------------------------------

class TestSend:
    def test_writes_valid_json_to_stdout(self, capsys):
        mcp_server.send({"key": "value", "num": 42})
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {"key": "value", "num": 42}

    def test_output_ends_with_newline(self, capsys):
        mcp_server.send({"x": 1})
        captured = capsys.readouterr()
        assert captured.out.endswith("\n")

    def test_empty_dict(self, capsys):
        mcp_server.send({})
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {}

    def test_nested_payload(self, capsys):
        payload = {"result": [{"id": 1}, {"id": 2}]}
        mcp_server.send(payload)
        captured = capsys.readouterr()
        assert json.loads(captured.out) == payload


class TestSendResult:
    def test_sends_jsonrpc_result(self, capsys):
        mcp_server.send_result(1, {"tools": []})
        msg = json.loads(capsys.readouterr().out)
        assert msg == {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}

    def test_echoes_request_id(self, capsys):
        mcp_server.send_result(99, {})
        msg = json.loads(capsys.readouterr().out)
        assert msg["id"] == 99

    def test_result_payload_preserved(self, capsys):
        payload = {"content": [{"type": "text", "text": "hello"}]}
        mcp_server.send_result(2, payload)
        msg = json.loads(capsys.readouterr().out)
        assert msg["result"] == payload


class TestSendError:
    def test_sends_jsonrpc_error(self, capsys):
        mcp_server.send_error(1, -32601, "Method not found")
        msg = json.loads(capsys.readouterr().out)
        assert msg == {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}

    def test_none_id_for_parse_errors(self, capsys):
        mcp_server.send_error(None, -32700, "Parse error")
        msg = json.loads(capsys.readouterr().out)
        assert msg["id"] is None

    def test_error_code_preserved(self, capsys):
        mcp_server.send_error(5, -32602, "Invalid params")
        msg = json.loads(capsys.readouterr().out)
        assert msg["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# list_merge_requests
# ---------------------------------------------------------------------------

class TestListMergeRequests:
    def test_returns_id_and_title_only(self):
        gitlab_response = [
            {"iid": 1, "title": "Fix parser bug", "description": "long desc", "state": "opened"},
            {"iid": 2, "title": "Add feature X", "description": "another desc", "state": "opened"},
        ]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_merge_requests("123")

        assert result == [
            {"id": 1, "title": "Fix parser bug"},
            {"id": 2, "title": "Add feature X"},
        ]

    def test_calls_correct_url_with_state_filter(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_merge_requests("my-project")

        expected_url = f"{mcp_server.GITLAB_URL}/projects/my-project/merge_requests?state=opened"
        mock_get.assert_called_once_with(expected_url, headers=mcp_server.HEADERS)

    def test_passes_auth_header(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_merge_requests("99")

        _, kwargs = mock_get.call_args
        assert kwargs["headers"] == mcp_server.HEADERS

    def test_returns_empty_list_when_no_merge_requests(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            result = mcp_server.list_merge_requests("123")

        assert result == []

    def test_raises_http_error_on_4xx(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(404)):
            with pytest.raises(requests.HTTPError):
                mcp_server.list_merge_requests("nonexistent")

    def test_raises_http_error_on_5xx(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(500)):
            with pytest.raises(requests.HTTPError):
                mcp_server.list_merge_requests("broken-project")

    def test_url_encoded_project_path(self):
        """Project can be a URL-encoded namespace/path (e.g. mygroup%2Frepo)."""
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_merge_requests("mygroup%2Frepo")

        url_called = mock_get.call_args[0][0]
        assert "mygroup%2Frepo" in url_called


# ---------------------------------------------------------------------------
# list_issues
# ---------------------------------------------------------------------------

class TestListIssues:
    def test_returns_id_and_title_only(self):
        gitlab_response = [
            {"iid": 10, "title": "Bug report", "state": "opened", "labels": ["bug"]},
            {"iid": 11, "title": "Feature request", "state": "opened", "labels": []},
        ]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_issues("456")

        assert result == [
            {"id": 10, "title": "Bug report"},
            {"id": 11, "title": "Feature request"},
        ]

    def test_calls_correct_url(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_issues("my-project")

        expected_url = f"{mcp_server.GITLAB_URL}/projects/my-project/issues"
        mock_get.assert_called_once_with(expected_url, headers=mcp_server.HEADERS)

    def test_returns_empty_list_when_no_issues(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            result = mcp_server.list_issues("123")

        assert result == []

    def test_raises_http_error_on_403(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(403)):
            with pytest.raises(requests.HTTPError):
                mcp_server.list_issues("restricted-project")

    def test_raises_http_error_on_404(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(404)):
            with pytest.raises(requests.HTTPError):
                mcp_server.list_issues("nonexistent")

    def test_single_issue(self):
        with patch(
            "mcp_server.requests.get",
            return_value=_mock_response([{"iid": 1, "title": "Only issue"}]),
        ):
            result = mcp_server.list_issues("proj")

        assert result == [{"id": 1, "title": "Only issue"}]


# ---------------------------------------------------------------------------
# list_pipelines
# ---------------------------------------------------------------------------

class TestListPipelines:
    def test_returns_id_status_ref_only(self):
        gitlab_response = [
            {"id": 100, "status": "success", "ref": "main", "sha": "abc123", "web_url": "..."},
            {"id": 101, "status": "failed", "ref": "feature-branch", "sha": "def456", "web_url": "..."},
        ]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_pipelines("789")

        assert result == [
            {"id": 100, "status": "success", "ref": "main"},
            {"id": 101, "status": "failed", "ref": "feature-branch"},
        ]

    def test_calls_correct_url(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_pipelines("my-project")

        expected_url = f"{mcp_server.GITLAB_URL}/projects/my-project/pipelines"
        mock_get.assert_called_once_with(expected_url, headers=mcp_server.HEADERS)

    def test_returns_empty_list_when_no_pipelines(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            result = mcp_server.list_pipelines("123")

        assert result == []

    def test_raises_http_error_on_500(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(500)):
            with pytest.raises(requests.HTTPError):
                mcp_server.list_pipelines("broken")

    def test_pipeline_statuses_preserved(self):
        """Verify various pipeline status strings pass through unchanged."""
        statuses = ["created", "waiting_for_resource", "preparing", "pending",
                    "running", "success", "failed", "canceled", "skipped", "manual", "scheduled"]
        gitlab_response = [
            {"id": i, "status": s, "ref": "main"} for i, s in enumerate(statuses)
        ]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_pipelines("proj")

        assert [r["status"] for r in result] == statuses
