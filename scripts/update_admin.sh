#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="desk_display_admin.service"
PYTHON_BIN="${PYTHON:-python3}"

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR="${PROJECT_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/venv}"

COMMON_SCRIPT="$PROJECT_DIR/scripts/install_common.sh"
if [[ ! -f "$COMMON_SCRIPT" ]]; then
  echo "[ERROR] Missing common installer helpers at $COMMON_SCRIPT" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$COMMON_SCRIPT"

if [[ $EUID -ne 0 ]]; then
  SUDO="sudo"
else
  SUDO=""
fi

if command -v git >/dev/null 2>&1 && [[ -d "$PROJECT_DIR/.git" ]]; then
  log "Updating repository in $PROJECT_DIR"
  git -C "$PROJECT_DIR" pull --ff-only || warn "Git update failed; repository may require manual intervention."
else
  warn "Git not available or repository missing; skipping source update."
fi

if [[ ! -d "$VENV_DIR" ]]; then
  log "Virtual environment not found; creating one at $VENV_DIR with $PYTHON_BIN"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

pip install --upgrade pip

if [[ -f "$PROJECT_DIR/requirements.txt" ]]; then
  log "Reinstalling Python dependencies from requirements.txt"
  pip install -r "$PROJECT_DIR/requirements.txt"
else
  warn "requirements.txt not found; skipping dependency install."
fi

deactivate

log "Reloading systemd units and restarting $SERVICE_NAME"
$SUDO systemctl daemon-reload
$SUDO systemctl restart "$SERVICE_NAME"

log "Update complete. Service status:"
$SUDO systemctl status --no-pager "$SERVICE_NAME"
