from __future__ import annotations

"""Shared helpers for locating writable storage directories."""

import logging
import os
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import storage_overrides

APP_DIR_NAME = "desk_display_display_hat_mini"


@dataclass(frozen=True)
class StoragePaths:
    """Resolved filesystem locations for runtime storage."""

    screenshot_dir: Path
    current_screenshot_dir: Path
    archive_base: Path


def _expand(path_str: str) -> Path:
    return Path(path_str).expanduser()


def _iter_candidate_roots() -> Iterable[Path]:
    env_root = os.environ.get("DESK_DISPLAY_DATA_DIR")
    if env_root:
        yield _expand(env_root)

    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        yield _expand(xdg_data) / APP_DIR_NAME

    yield Path.home() / ".local" / "share" / APP_DIR_NAME
    yield Path.home() / APP_DIR_NAME


_SHARED_HINT_PATH = Path(tempfile.gettempdir()) / f"{APP_DIR_NAME}_screenshot_dir.txt"


def _read_shared_hint(logger: Optional[logging.Logger]) -> Optional[Path]:
    try:
        raw = _SHARED_HINT_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    candidate = Path(raw)
    if _ensure_writable(candidate, logger):
        return candidate
    return None


def _write_shared_hint(path: Path, logger: Optional[logging.Logger]) -> None:
    try:
        _SHARED_HINT_PATH.write_text(str(path), encoding="utf-8")
    except OSError as exc:
        if logger:
            logger.debug("Could not record screenshot hint %s: %s", _SHARED_HINT_PATH, exc)


def _iter_candidate_screenshot_dirs() -> Iterable[Path]:
    for root in _iter_candidate_roots():
        yield root / "screenshots"

    script_dir = Path(__file__).resolve().parent
    yield script_dir / "screenshots"


def _ensure_writable(path: Path, logger: Optional[logging.Logger]) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if logger:
            logger.debug("Could not create directory %s: %s", path, exc)
        return False

    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(path))
    except OSError as exc:
        if logger:
            logger.debug("Directory %s is not writable: %s", path, exc)
        return False

    os.close(fd)
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    return True


def _hostname() -> str:
    return socket.gethostname()


def _select_screenshot_dir(logger: Optional[logging.Logger]) -> Path:
    overrides = []
    env_override = os.environ.get("DESK_DISPLAY_SCREENSHOT_DIR")
    if env_override:
        overrides.append(_expand(env_override))

    config_override = storage_overrides.SCREENSHOT_DIR
    if config_override:
        overrides.append(_expand(config_override))

    for override in overrides:
        if _ensure_writable(override, logger):
            _write_shared_hint(override, logger)
            return override

    shared_hint = _read_shared_hint(logger)
    if shared_hint is not None:
        return shared_hint

    for candidate in _iter_candidate_screenshot_dirs():
        if _ensure_writable(candidate, logger):
            _write_shared_hint(candidate, logger)
            return candidate

    fallback = Path(__file__).resolve().parent / "screenshots"
    if logger:
        logger.warning(
            "Falling back to %s for screenshots; no writable directory was found.",
            fallback,
        )
    fallback.mkdir(parents=True, exist_ok=True)
    _write_shared_hint(fallback, logger)
    return fallback


def resolve_storage_paths(*, logger: Optional[logging.Logger] = None) -> StoragePaths:
    """Return writable paths for screenshots and archives."""

    screenshot_dir = _select_screenshot_dir(logger)
    hostname = _hostname()
    current_name = f"{hostname}current" if hostname else "current"
    current_screenshot_dir = screenshot_dir / current_name
    archive_base = screenshot_dir.parent / "screenshot_archive"
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
