#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="desk_display_admin.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"

log() { printf '[INFO] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
  SUDO="sudo"
else
  SUDO=""
fi

log "Stopping $SERVICE_NAME (ignore errors if not running)."
$SUDO systemctl stop "$SERVICE_NAME" 2>/dev/null || warn "Could not stop $SERVICE_NAME"

log "Disabling $SERVICE_NAME."
$SUDO systemctl disable "$SERVICE_NAME" 2>/dev/null || warn "Could not disable $SERVICE_NAME"

if [[ -f "$SERVICE_PATH" ]]; then
  log "Removing service file at $SERVICE_PATH"
  $SUDO rm -f "$SERVICE_PATH"
else
  warn "Service file $SERVICE_PATH not found; nothing to remove."
fi

log "Reloading systemd units."
$SUDO systemctl daemon-reload

log "Uninstall complete."
