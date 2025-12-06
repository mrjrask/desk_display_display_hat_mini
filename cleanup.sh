#!/bin/bash
set -euo pipefail
IFS=$'\n\t'

# Ensure Unix line endings and executable bit:
#   sed -i 's/\r$//' cleanup.sh && chmod +x cleanup.sh

echo "⏱  Running cleanup at $(date +%Y%m%d_%H%M%S)…"

dir="$(dirname "$0")"
cd "$dir"

# Prefer the repo's virtualenv interpreter when available so optional
# dependencies such as Pillow are on the path even during shutdown.
python_bin="python3"
if [[ -x "${dir}/venv/bin/python" ]]; then
  python_bin="${dir}/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  python_bin="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  python_bin="$(command -v python)"
fi

# 1) Clear the display before touching the filesystem
echo "    → Clearing display…"
# Force headless mode so cleanup doesn't fight a still-shutting-down service
# for the Display HAT Mini hardware.
DESK_DISPLAY_FORCE_HEADLESS=1 "${python_bin}" - <<'PY'
import logging

try:
    from utils import Display, clear_display
except Exception as exc:  # pragma: no cover - best effort during shutdown
    logging.warning("Display cleanup skipped: %s", exc)
else:
    try:
        display = Display()
        clear_display(display)
    except Exception as exc:  # pragma: no cover - best effort during shutdown
        logging.warning("Display cleanup failed: %s", exc)
PY

# 2) Remove __pycache__ directories
echo "    → Removing __pycache__ directories…"
find . -type d -name "__pycache__" -prune -exec rm -rf {} +

# 3) Archive any straggler screenshots/videos left behind
SCREENSHOTS_DIR="screenshots"
ARCHIVE_BASE="screenshot_archive"   # singular, to match main.py
ARCHIVE_DEFAULT_FOLDER="Screens"
timestamp="$(date +%Y%m%d_%H%M%S)"
batch="${timestamp#*_}"

declare -a leftover_files=()
if [[ -d "${SCREENSHOTS_DIR}" ]]; then
  while IFS= read -r -d $'\0' file; do
    leftover_files+=("$file")
  done < <(
    find "${SCREENSHOTS_DIR}" \
      -path "${SCREENSHOTS_DIR}/current" -prune -o \
      -type f \
      \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \
         -o -iname '*.mp4' -o -iname '*.avi' \) -print0 | sort -z
  )
fi

if (( ${#leftover_files[@]} > 0 )); then
  echo "    → Archiving leftover screenshots/videos to screenshot_archive/<screen>/"
  for src in "${leftover_files[@]}"; do
    rel_path="${src#${SCREENSHOTS_DIR}/}"
    screen_folder="${ARCHIVE_DEFAULT_FOLDER}"
    remainder="${rel_path}"

    if [[ "${rel_path}" != "${src}" ]]; then
      IFS='/' read -r first rest <<< "${rel_path}"
      if [[ -n "${rest}" ]]; then
        screen_folder="${first}"
        remainder="${rest}"
      else
        remainder="${first}"
      fi
    else
      remainder="$(basename "${src}")"
    fi

    dest_dir="${ARCHIVE_BASE}/${screen_folder}"
    dest="${dest_dir}/${remainder}"
    mkdir -p "$(dirname "${dest}")"

    if [[ -e "${dest}" ]]; then
      ext="${dest##*.}"
      base="${dest%.*}"
      dest="${base}_cleanup_${batch}.${ext}"
    fi

    mv -f "${src}" "${dest}"
  done
  if [[ -d "${SCREENSHOTS_DIR}" ]]; then
    find "${SCREENSHOTS_DIR}" -type d -empty -delete
  fi
else
  echo "    → No leftover screenshots/videos to archive."
fi

echo "🏁  Cleanup complete."
