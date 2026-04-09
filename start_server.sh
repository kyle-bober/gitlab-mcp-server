#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

# ---------------------------------------------------------------------------
# Validate required environment variables before doing any work
# ---------------------------------------------------------------------------
if [[ -z "${GITLAB_URL:-}" || -z "${GITLAB_TOKEN:-}" ]]; then
  echo "Error: GITLAB_URL and GITLAB_TOKEN environment variables must be set." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Bootstrap virtual environment (created once, reused on subsequent runs)
# ---------------------------------------------------------------------------
if [[ ! -f "${VENV_DIR}/bin/python" ]]; then
  echo "Creating virtual environment at ${VENV_DIR}..." >&2
  python3 -m venv "${VENV_DIR}"
fi

# ---------------------------------------------------------------------------
# Install / sync runtime dependencies
# ---------------------------------------------------------------------------
"${VENV_DIR}/bin/pip" install --quiet --require-virtualenv \
  -r "${SCRIPT_DIR}/requirements.txt"

# ---------------------------------------------------------------------------
# Run the server inside the venv
# ---------------------------------------------------------------------------
exec "${VENV_DIR}/bin/python" "${SCRIPT_DIR}/mcp_server.py"
