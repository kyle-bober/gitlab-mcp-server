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


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------

class TestGetCurrentUser:
    def test_returns_user_fields(self):
        gitlab_response = {"id": 42, "username": "kyle", "name": "Kyle Bober", "email": "kyle@example.com"}
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.get_current_user()
        assert result == {"id": 42, "username": "kyle", "name": "Kyle Bober", "email": "kyle@example.com"}

    def test_calls_correct_url(self):
        with patch("mcp_server.requests.get", return_value=_mock_response(
            {"id": 1, "username": "u", "name": "n"}
        )) as mock_get:
            mcp_server.get_current_user()
        mock_get.assert_called_once_with(f"{mcp_server.GITLAB_URL}/user", headers=mcp_server.HEADERS)

    def test_email_defaults_to_empty_string_when_absent(self):
        with patch("mcp_server.requests.get", return_value=_mock_response({"id": 1, "username": "u", "name": "n"})):
            result = mcp_server.get_current_user()
        assert result["email"] == ""

    def test_raises_http_error_on_401(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(401)):
            with pytest.raises(requests.HTTPError):
                mcp_server.get_current_user()


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------

class TestListProjects:
    def test_returns_id_name_path(self):
        gitlab_response = [{"id": 1, "name": "My Repo", "path_with_namespace": "group/my-repo"}]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_projects()
        assert result == [{"id": 1, "name": "My Repo", "path_with_namespace": "group/my-repo"}]

    def test_always_includes_membership_filter(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_projects()
        assert "membership=true" in mock_get.call_args[0][0]

    def test_appends_search_when_provided(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_projects(search="ndle")
        assert "search=ndle" in mock_get.call_args[0][0]

    def test_no_search_param_when_omitted(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_projects()
        assert "search=" not in mock_get.call_args[0][0]

    def test_returns_empty_list(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            assert mcp_server.list_projects() == []

    def test_raises_http_error_on_403(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(403)):
            with pytest.raises(requests.HTTPError):
                mcp_server.list_projects()


# ---------------------------------------------------------------------------
# get_project
# ---------------------------------------------------------------------------

class TestGetProject:
    def test_returns_project_fields(self):
        gitlab_response = {
            "id": 99, "name": "Repo", "path_with_namespace": "grp/repo",
            "description": "A repo", "default_branch": "main",
            "visibility": "private", "web_url": "https://gl.example.com/grp/repo",
        }
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.get_project("99")
        assert result["id"] == 99
        assert result["default_branch"] == "main"
        assert result["visibility"] == "private"

    def test_calls_correct_url(self):
        with patch("mcp_server.requests.get", return_value=_mock_response({
            "id": 1, "name": "r", "path_with_namespace": "g/r"
        })) as mock_get:
            mcp_server.get_project("my-project")
        mock_get.assert_called_once_with(
            f"{mcp_server.GITLAB_URL}/projects/my-project", headers=mcp_server.HEADERS
        )

    def test_raises_http_error_on_404(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(404)):
            with pytest.raises(requests.HTTPError):
                mcp_server.get_project("nonexistent")


# ---------------------------------------------------------------------------
# list_groups
# ---------------------------------------------------------------------------

class TestListGroups:
    def test_returns_id_name_full_path(self):
        gitlab_response = [{"id": 10, "name": "NDLE", "full_path": "charter/ndle"}]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_groups()
        assert result == [{"id": 10, "name": "NDLE", "full_path": "charter/ndle"}]

    def test_includes_min_access_level_filter(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_groups()
        assert "min_access_level=10" in mock_get.call_args[0][0]

    def test_appends_search_when_provided(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_groups(search="ndle")
        assert "search=ndle" in mock_get.call_args[0][0]

    def test_returns_empty_list(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            assert mcp_server.list_groups() == []


# ---------------------------------------------------------------------------
# list_project_members
# ---------------------------------------------------------------------------

class TestListProjectMembers:
    def test_returns_member_fields(self):
        gitlab_response = [{"id": 1, "username": "kyle", "name": "Kyle", "access_level": 50}]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_project_members("proj")
        assert result == [{"id": 1, "username": "kyle", "name": "Kyle", "access_level": 50}]

    def test_calls_members_all_endpoint(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_project_members("123")
        assert mock_get.call_args[0][0].endswith("/members/all")

    def test_raises_http_error_on_404(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(404)):
            with pytest.raises(requests.HTTPError):
                mcp_server.list_project_members("missing")


# ---------------------------------------------------------------------------
# list_releases
# ---------------------------------------------------------------------------

class TestListReleases:
    def test_returns_tag_name_and_name(self):
        gitlab_response = [{"tag_name": "v1.0.0", "name": "Release 1.0", "released_at": "2025-01-01"}]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_releases("proj")
        assert result == [{"tag_name": "v1.0.0", "name": "Release 1.0", "released_at": "2025-01-01"}]

    def test_released_at_is_none_when_absent(self):
        gitlab_response = [{"tag_name": "v2.0.0", "name": "v2"}]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_releases("proj")
        assert result[0]["released_at"] is None

    def test_returns_empty_list(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            assert mcp_server.list_releases("proj") == []


# ---------------------------------------------------------------------------
# get_merge_request
# ---------------------------------------------------------------------------

class TestGetMergeRequest:
    def test_returns_mr_details(self):
        gitlab_response = {
            "iid": 5, "title": "Fix bug", "description": "details",
            "state": "opened", "author": {"username": "kyle"},
            "source_branch": "fix/bug", "target_branch": "main",
            "labels": ["bug"], "web_url": "https://gl.example.com/mr/5",
        }
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.get_merge_request("proj", 5)
        assert result["iid"] == 5
        assert result["author"] == "kyle"
        assert result["labels"] == ["bug"]

    def test_calls_correct_url(self):
        with patch("mcp_server.requests.get", return_value=_mock_response({
            "iid": 1, "title": "t", "state": "opened"
        })) as mock_get:
            mcp_server.get_merge_request("my-proj", 1)
        assert mock_get.call_args[0][0].endswith("/merge_requests/1")

    def test_raises_http_error_on_404(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(404)):
            with pytest.raises(requests.HTTPError):
                mcp_server.get_merge_request("proj", 999)


# ---------------------------------------------------------------------------
# list_merge_request_notes
# ---------------------------------------------------------------------------

class TestListMergeRequestNotes:
    def test_returns_note_fields(self):
        gitlab_response = [{"id": 1, "author": {"username": "alice"}, "body": "LGTM"}]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_merge_request_notes("proj", 3)
        assert result == [{"id": 1, "author": "alice", "body": "LGTM"}]

    def test_author_is_none_when_author_missing(self):
        gitlab_response = [{"id": 2, "body": "system note"}]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_merge_request_notes("proj", 3)
        assert result[0]["author"] is None

    def test_returns_empty_list(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            assert mcp_server.list_merge_request_notes("proj", 1) == []


# ---------------------------------------------------------------------------
# get_pipeline
# ---------------------------------------------------------------------------

class TestGetPipeline:
    def test_returns_pipeline_fields(self):
        gitlab_response = {
            "id": 100, "status": "success", "ref": "main", "sha": "abc123",
            "web_url": "https://gl.example.com/pipelines/100",
            "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T01:00:00Z",
        }
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.get_pipeline("proj", 100)
        assert result["id"] == 100
        assert result["sha"] == "abc123"
        assert result["created_at"] == "2025-01-01T00:00:00Z"

    def test_calls_correct_url(self):
        with patch("mcp_server.requests.get", return_value=_mock_response({
            "id": 5, "status": "running", "ref": "main"
        })) as mock_get:
            mcp_server.get_pipeline("my-proj", 5)
        assert mock_get.call_args[0][0].endswith("/pipelines/5")

    def test_raises_http_error_on_404(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(404)):
            with pytest.raises(requests.HTTPError):
                mcp_server.get_pipeline("proj", 9999)


# ---------------------------------------------------------------------------
# list_pipeline_jobs
# ---------------------------------------------------------------------------

class TestListPipelineJobs:
    def test_returns_job_fields(self):
        gitlab_response = [
            {"id": 1, "name": "build", "status": "success", "stage": "build",
             "web_url": "https://gl.example.com/jobs/1"},
        ]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_pipeline_jobs("proj", 10)
        assert result == [{"id": 1, "name": "build", "status": "success", "stage": "build",
                           "web_url": "https://gl.example.com/jobs/1"}]

    def test_calls_correct_url(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_pipeline_jobs("my-proj", 42)
        assert mock_get.call_args[0][0].endswith("/pipelines/42/jobs")

    def test_returns_empty_list(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            assert mcp_server.list_pipeline_jobs("proj", 1) == []


# ---------------------------------------------------------------------------
# list_branches
# ---------------------------------------------------------------------------

class TestListBranches:
    def test_returns_branch_fields(self):
        gitlab_response = [
            {"name": "main", "merged": False, "protected": True},
            {"name": "develop", "merged": False, "protected": False},
        ]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_branches("proj")
        assert result == [
            {"name": "main", "merged": False, "protected": True},
            {"name": "develop", "merged": False, "protected": False},
        ]

    def test_defaults_merged_and_protected_to_false(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([{"name": "feat"}])):
            result = mcp_server.list_branches("proj")
        assert result[0]["merged"] is False
        assert result[0]["protected"] is False

    def test_returns_empty_list(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            assert mcp_server.list_branches("proj") == []

    def test_raises_http_error_on_404(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(404)):
            with pytest.raises(requests.HTTPError):
                mcp_server.list_branches("missing")


# ---------------------------------------------------------------------------
# list_tags
# ---------------------------------------------------------------------------

class TestListTags:
    def test_returns_tag_fields(self):
        gitlab_response = [
            {"name": "v1.0.0", "message": "Release 1.0", "commit": {"id": "abc123"}},
        ]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_tags("proj")
        assert result == [{"name": "v1.0.0", "message": "Release 1.0", "commit": "abc123"}]

    def test_commit_is_none_when_absent(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([{"name": "v2.0"}])):
            result = mcp_server.list_tags("proj")
        assert result[0]["commit"] is None

    def test_returns_empty_list(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            assert mcp_server.list_tags("proj") == []


# ---------------------------------------------------------------------------
# list_commits
# ---------------------------------------------------------------------------

class TestListCommits:
    def test_returns_commit_fields(self):
        gitlab_response = [{
            "id": "abc123def", "short_id": "abc123", "title": "Fix bug",
            "author_name": "Kyle", "created_at": "2025-01-01T00:00:00Z",
        }]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_commits("proj")
        assert result[0]["short_id"] == "abc123"
        assert result[0]["author_name"] == "Kyle"

    def test_calls_url_without_ref_when_omitted(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_commits("proj")
        url = mock_get.call_args[0][0]
        assert url.endswith("/commits")

    def test_appends_ref_name_when_provided(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_commits("proj", ref_name="develop")
        assert "ref_name=develop" in mock_get.call_args[0][0]

    def test_returns_empty_list(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            assert mcp_server.list_commits("proj") == []


# ---------------------------------------------------------------------------
# get_file
# ---------------------------------------------------------------------------

class TestGetFile:
    def test_decodes_base64_content(self):
        import base64
        content = "hello world"
        encoded = base64.b64encode(content.encode()).decode()
        gitlab_response = {"file_path": "README.md", "ref": "main", "encoding": "base64", "content": encoded}
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.get_file("proj", "README.md")
        assert result["content"] == content
        assert result["file_path"] == "README.md"

    def test_url_encodes_slash_in_file_path(self):
        import base64
        with patch("mcp_server.requests.get", return_value=_mock_response({
            "file_path": "src/main.py", "ref": "main", "encoding": "base64",
            "content": base64.b64encode(b"x").decode(),
        })) as mock_get:
            mcp_server.get_file("proj", "src/main.py")
        assert "src%2Fmain.py" in mock_get.call_args[0][0]

    def test_uses_head_as_default_ref(self):
        import base64
        with patch("mcp_server.requests.get", return_value=_mock_response({
            "file_path": "f.txt", "ref": "HEAD", "encoding": "base64",
            "content": base64.b64encode(b"t").decode(),
        })) as mock_get:
            mcp_server.get_file("proj", "f.txt")
        assert "ref=HEAD" in mock_get.call_args[0][0]

    def test_uses_custom_ref(self):
        import base64
        with patch("mcp_server.requests.get", return_value=_mock_response({
            "file_path": "f.txt", "ref": "develop", "encoding": "base64",
            "content": base64.b64encode(b"t").decode(),
        })) as mock_get:
            mcp_server.get_file("proj", "f.txt", ref="develop")
        assert "ref=develop" in mock_get.call_args[0][0]

    def test_raises_http_error_on_404(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(404)):
            with pytest.raises(requests.HTTPError):
                mcp_server.get_file("proj", "missing.txt")


# ---------------------------------------------------------------------------
# list_repository_tree
# ---------------------------------------------------------------------------

class TestListRepositoryTree:
    def test_returns_tree_items(self):
        gitlab_response = [
            {"id": "abc", "name": "src", "type": "tree", "path": "src"},
            {"id": "def", "name": "README.md", "type": "blob", "path": "README.md"},
        ]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_repository_tree("proj")
        assert len(result) == 2
        assert result[0]["type"] == "tree"
        assert result[1]["type"] == "blob"

    def test_calls_url_without_params_when_none_provided(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_repository_tree("proj")
        url = mock_get.call_args[0][0]
        assert url.endswith("/repository/tree")

    def test_appends_path_when_provided(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_repository_tree("proj", path="src")
        assert "path=src" in mock_get.call_args[0][0]

    def test_appends_ref_when_provided(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_repository_tree("proj", ref="develop")
        assert "ref=develop" in mock_get.call_args[0][0]

    def test_returns_empty_list(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            assert mcp_server.list_repository_tree("proj") == []


# ---------------------------------------------------------------------------
# compare_refs
# ---------------------------------------------------------------------------

class TestCompareRefs:
    def test_returns_comparison_summary(self):
        gitlab_response = {
            "commit": {"id": "abc123"},
            "commits": [{"id": "abc123", "title": "Fix bug"}],
            "diffs": [{"old_path": "a.py", "new_path": "a.py"}],
            "compare_same_ref": False,
        }
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.compare_refs("proj", "main", "feature")
        assert result["commit"] == "abc123"
        assert result["diffs_count"] == 1
        assert result["compare_same_ref"] is False

    def test_calls_correct_url(self):
        with patch("mcp_server.requests.get", return_value=_mock_response({
            "commit": None, "commits": [], "diffs": [], "compare_same_ref": False
        })) as mock_get:
            mcp_server.compare_refs("proj", "main", "develop")
        url = mock_get.call_args[0][0]
        assert "from=main" in url
        assert "to=develop" in url

    def test_handles_empty_diffs(self):
        with patch("mcp_server.requests.get", return_value=_mock_response({
            "commit": None, "commits": [], "diffs": [], "compare_same_ref": True
        })):
            result = mcp_server.compare_refs("proj", "main", "main")
        assert result["diffs_count"] == 0
        assert result["compare_same_ref"] is True


# ---------------------------------------------------------------------------
# list_registry_repositories
# ---------------------------------------------------------------------------

class TestListRegistryRepositories:
    def test_returns_repository_fields(self):
        gitlab_response = [
            {"id": 1, "name": "my-image", "path": "group/proj/my-image",
             "location": "registry.example.com/group/proj/my-image"},
        ]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_registry_repositories("proj")
        assert result[0]["id"] == 1
        assert result[0]["name"] == "my-image"

    def test_calls_correct_url(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_registry_repositories("123")
        assert mock_get.call_args[0][0].endswith("/registry/repositories")

    def test_returns_empty_list(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            assert mcp_server.list_registry_repositories("proj") == []

    def test_raises_http_error_on_404(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(404)):
            with pytest.raises(requests.HTTPError):
                mcp_server.list_registry_repositories("missing")


# ---------------------------------------------------------------------------
# list_registry_tags
# ---------------------------------------------------------------------------

class TestListRegistryTags:
    def test_returns_tag_fields(self):
        gitlab_response = [
            {"name": "latest", "path": "group/proj/img:latest", "location": "registry.example.com/img:latest"},
        ]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_registry_tags("proj", 7)
        assert result == [{"name": "latest", "path": "group/proj/img:latest",
                           "location": "registry.example.com/img:latest"}]

    def test_calls_correct_url(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_registry_tags("my-proj", 42)
        assert mock_get.call_args[0][0].endswith("/registry/repositories/42/tags")

    def test_returns_empty_list(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            assert mcp_server.list_registry_tags("proj", 1) == []


# ---------------------------------------------------------------------------
# list_packages
# ---------------------------------------------------------------------------

class TestListPackages:
    def test_returns_package_fields(self):
        gitlab_response = [
            {"id": 1, "name": "ndle-common", "version": "0.0.1", "package_type": "pypi"},
        ]
        with patch("mcp_server.requests.get", return_value=_mock_response(gitlab_response)):
            result = mcp_server.list_packages("proj")
        assert result == [{"id": 1, "name": "ndle-common", "version": "0.0.1", "package_type": "pypi"}]

    def test_calls_correct_url(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])) as mock_get:
            mcp_server.list_packages("123")
        assert mock_get.call_args[0][0].endswith("/packages")

    def test_version_is_none_when_absent(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([{"id": 2, "name": "pkg", "package_type": "npm"}])):
            result = mcp_server.list_packages("proj")
        assert result[0]["version"] is None

    def test_returns_empty_list(self):
        with patch("mcp_server.requests.get", return_value=_mock_response([])):
            assert mcp_server.list_packages("proj") == []

    def test_raises_http_error_on_404(self):
        with patch("mcp_server.requests.get", return_value=_http_error_response(404)):
            with pytest.raises(requests.HTTPError):
                mcp_server.list_packages("missing")
