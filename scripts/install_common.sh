#!/usr/bin/env bash
set -euo pipefail

log() { printf '[INFO] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*"; }

# Return the preferred libtiff development package for the given codename.
select_libtiff_pkg() {
  local codename="$1"
  case "$codename" in
    bookworm) echo "libtiff5-dev" ;;
    trixie) echo "libtiff6-dev" ;;
    *) echo "libtiff-dev" ;;
  esac
}

# Choose the gdk-pixbuf development package for the given codename, preferring
# codename-specific names while still allowing a fallback if the package cache
# does not know the preferred option.
select_gdk_pixbuf_pkg() {
  local codename="$1"
  local candidates=()

  case "$codename" in
    bookworm) candidates=(libgdk-pixbuf2.0-dev libgdk-pixbuf-2.0-dev) ;;
    trixie) candidates=(libgdk-pixbuf-2.0-dev) ;;
    *) candidates=(libgdk-pixbuf-2.0-dev libgdk-pixbuf2.0-dev) ;;
  esac

  for pkg in "${candidates[@]}"; do
    if apt-cache show "$pkg" >/dev/null 2>&1; then
      echo "$pkg"
      return 0
    fi
  done

  warn "Could not find a gdk-pixbuf dev package; defaulting to ${candidates[-1]}"
  echo "${candidates[-1]}"
}

install_apt_packages() {
  local codename="${EXPECTED_CODENAME:-}"
  if [[ -z "$codename" ]]; then
    warn "EXPECTED_CODENAME is not set; defaulting to detected release name"
    codename=$(lsb_release -sc 2>/dev/null || echo "")
  fi

  local shared_packages=(
    python3-venv python3-pip python3-dev python3-opencv
    build-essential libjpeg-dev libopenblas0 libopenblas-dev
    libopenjp2-7-dev libcairo2-dev libpango1.0-dev
    libffi-dev network-manager wireless-tools
    i2c-tools fonts-dejavu-core libgl1 libx264-dev ffmpeg git
  )

  local packages=("${shared_packages[@]}")
  packages+=("$(select_libtiff_pkg "$codename")")
  packages+=("$(select_gdk_pixbuf_pkg "$codename")")

  log "Updating apt package index."
  ${SUDO:-} apt-get update

  log "Installing apt dependencies: ${packages[*]}"
  ${SUDO:-} apt-get install -y "${packages[@]}"
}
