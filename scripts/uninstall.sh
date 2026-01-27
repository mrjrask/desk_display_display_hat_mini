#!/usr/bin/env bash
set -euo pipefail

log() { printf '[INFO] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*"; }

SERVICE_NAME="desk_display.service"

detect_existing_venv() {
  local project_dir="$1"
  local candidates=(
    "$project_dir/venv"
    "$project_dir/.venv"
  )

  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate/pyvenv.cfg" ]]; then
      echo "$candidate"
      return 0
    fi
  done

  local venv_cfg
  venv_cfg=$(find "$project_dir" -maxdepth 2 -mindepth 2 -type f -name pyvenv.cfg -print -quit 2>/dev/null || true)
  if [[ -n "$venv_cfg" ]]; then
    dirname "$venv_cfg"
    return 0
  fi

  return 1
}

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR="${PROJECT_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
VENV_DIR=$(detect_existing_venv "$PROJECT_DIR" || true)
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"

if [[ $EUID -ne 0 ]]; then
  SUDO="sudo"
else
  SUDO=""
fi

log "Starting uninstall for $PROJECT_DIR"

if command -v systemctl >/dev/null 2>&1; then
  if systemctl list-unit-files | grep -q "^$SERVICE_NAME"; then
    log "Stopping $SERVICE_NAME"
    $SUDO systemctl stop "$SERVICE_NAME" || warn "Failed to stop $SERVICE_NAME"
    log "Disabling $SERVICE_NAME"
    $SUDO systemctl disable "$SERVICE_NAME" || warn "Failed to disable $SERVICE_NAME"
  else
    warn "$SERVICE_NAME not registered with systemd"
  fi

  if [[ -f "$SERVICE_PATH" ]]; then
    log "Removing systemd unit at $SERVICE_PATH"
    $SUDO rm -f "$SERVICE_PATH"
    log "Reloading systemd daemon"
    $SUDO systemctl daemon-reload || warn "Failed to reload systemd daemon"
  else
    warn "No systemd unit found at $SERVICE_PATH"
  fi
else
  warn "systemctl not found; skipping service removal"
fi

if [[ -n "$VENV_DIR" && -d "$VENV_DIR" ]]; then
  if [[ "${KEEP_VENV:-}" == "1" ]]; then
    log "Keeping virtual environment at $VENV_DIR (KEEP_VENV=1)"
  elif [[ -t 0 ]]; then
    read -r -p "Keep virtual environment at $VENV_DIR? [y/N]: " keep_reply
    if [[ "$keep_reply" =~ ^[Yy]$ ]]; then
      log "Keeping virtual environment at $VENV_DIR"
    else
      log "Removing virtual environment at $VENV_DIR"
      rm -rf "$VENV_DIR"
    fi
  else
    warn "No interactive terminal detected; removing virtual environment at $VENV_DIR"
    rm -rf "$VENV_DIR"
  fi
else
  warn "No virtual environment found for $PROJECT_DIR"
fi

log "Uninstall complete. Project files remain in $PROJECT_DIR"
