#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="desk_display_admin.service"
PYTHON_BIN="${PYTHON:-python3}"

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/venv}"
SERVICE_USER="${SUDO_USER:-$(whoami)}"
ADMIN_HOST="${ADMIN_HOST:-0.0.0.0}"
ADMIN_PORT="${ADMIN_PORT:-5001}"
ADMIN_ENV_FILE="${ADMIN_ENV_FILE:-$PROJECT_DIR/.env.admin}"

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

install_apt_packages

if [[ ! -d "$PROJECT_DIR" ]]; then
  log "Creating project directory: $PROJECT_DIR"
  mkdir -p "$PROJECT_DIR"
fi

if [[ ! -d "$PROJECT_DIR/.git" ]]; then
  warn "No git repository detected in $PROJECT_DIR. Clone the project before running this installer."
fi

if [[ ! -d "$VENV_DIR" ]]; then
  log "Creating virtual environment with $PYTHON_BIN at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  log "Virtual environment already exists at $VENV_DIR"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

pip install --upgrade pip

if [[ -f "$PROJECT_DIR/requirements.txt" ]]; then
  log "Installing Python dependencies from requirements.txt"
  pip install -r "$PROJECT_DIR/requirements.txt"
else
  warn "requirements.txt not found; skipping pip install."
fi

deactivate

SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
log "Writing systemd service to $SERVICE_PATH"
$SUDO tee "$SERVICE_PATH" >/dev/null <<SERVICE
[Unit]
Description=Desk Display Admin Service
After=network-online.target

[Service]
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV_DIR/bin/python $PROJECT_DIR/admin.py
Restart=on-failure
User=$SERVICE_USER
Environment="ADMIN_HOST=$ADMIN_HOST"
Environment="ADMIN_PORT=$ADMIN_PORT"
EnvironmentFile=-$ADMIN_ENV_FILE

[Install]
WantedBy=multi-user.target
SERVICE

log "Reloading systemd, enabling and starting $SERVICE_NAME"
$SUDO systemctl daemon-reload
$SUDO systemctl enable "$SERVICE_NAME"
$SUDO systemctl restart "$SERVICE_NAME"

log "Installation complete. Service status:"
$SUDO systemctl status --no-pager "$SERVICE_NAME"
