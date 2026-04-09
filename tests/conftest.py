import os
import sys

# Add the project root to sys.path so `import mcp_server` works from any test directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# These MUST be set before mcp_server is first imported. The module-level guard in
# mcp_server.py calls sys.exit(1) if either variable is missing, which would abort
# the entire pytest session. setdefault leaves real values untouched if already set.
os.environ.setdefault("GITLAB_URL", "http://fake-gitlab.test/api/v4")
os.environ.setdefault("GITLAB_TOKEN", "fake-test-token")
