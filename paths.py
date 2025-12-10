from __future__ import annotations

"""Shared helpers for locating writable storage directories."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

APP_DIR_NAME = "desk_display_display_hat_mini"
_SHARED_HINT_PATH = Path(__file__).resolve().parent / ".data_dir_hint"


@dataclass(frozen=True)
class StoragePaths:
    """Resolved filesystem locations for runtime storage."""

    screenshot_dir: Path
    current_screenshot_dir: Path
    archive_base: Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def resolve_storage_paths(*, logger: Optional[object] = None) -> StoragePaths:
    """Return filesystem paths for screenshots and archives.

    Screenshots always write to ``<project_root>/screenshots`` and archives live
    in ``<project_root>/screenshot_archive``. A ``current`` folder mirrors the
    latest capture for each screen.
    """

    base_dir = _project_root()
    screenshot_dir = base_dir / "screenshots"
    archive_base = base_dir / "screenshot_archive"

    current_screenshot_dir = screenshot_dir / "current"

    screenshot_dir.mkdir(parents=True, exist_ok=True)
    current_screenshot_dir.mkdir(parents=True, exist_ok=True)
    archive_base.mkdir(parents=True, exist_ok=True)

    if logger:
        logger.info("Using screenshot directory %s", screenshot_dir)
        logger.info("Using current screenshot directory %s", current_screenshot_dir)
        logger.info("Using screenshot archive base %s", archive_base)

    return StoragePaths(
        screenshot_dir=screenshot_dir,
        current_screenshot_dir=current_screenshot_dir,
        archive_base=archive_base,
    )
