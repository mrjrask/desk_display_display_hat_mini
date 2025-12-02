#!/usr/bin/env bash
# reset_screenshots.sh
# Clears all contents of the local screenshots/ and screenshot_archive/ folders
# relative to this script's directory, without deleting the folders themselves.

set -Eeuo pipefail

# Resolve the absolute directory of this script (works with symlinks)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd -P)"

# Target directories (inside the script's directory)
TARGETS=(
  "$SCRIPT_DIR/screenshots"
  "$SCRIPT_DIR/screenshot_archive"
)

# Safety check to refuse obviously dangerous deletions
refuse_dangerous_path() {
  local path="$1"
  if [[ -z "$path" || "$path" == "/" || "$path" == "$HOME" ]]; then
    echo "❌ Refusing to operate on dangerous path: '$path'"
    exit 1
  fi
  # Ensure the path is within the script directory
  case "$path" in
    "$SCRIPT_DIR"/*) : ;; # ok
    *) echo "❌ Refusing to operate outside script directory: '$path'"; exit 1 ;;
  esac
}

echo "📂 Working in: $SCRIPT_DIR"

for dir in "${TARGETS[@]}"; do
  refuse_dangerous_path "$dir"

  if [[ ! -d "$dir" ]]; then
    echo "📁 Creating missing directory: $dir"
    mkdir -p -- "$dir"
    chmod 775 -- "$dir" || true
  else
    echo "🧹 Clearing contents of: $dir"
    # Delete everything inside the directory (files, subdirs, hidden files),
    # but not the directory itself.
    find "$dir" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  fi
done

echo "✅ Done. Cleared contents of: screenshots/ and screenshot_archive/"
