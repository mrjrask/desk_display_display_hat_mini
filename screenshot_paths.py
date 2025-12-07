"""Shared helpers for screenshot path construction."""

import os
import socket
from typing import Optional


def current_screenshot_folder_name(hostname: Optional[str] = None) -> str:
    """Return the hostname-scoped folder name for current screenshots.

    The folder is named "<hostname>current" to keep captures isolated per device.
    """

    host = socket.gethostname() if hostname is None else hostname
    return f"{host}current"


def current_screenshot_dir(base_dir: str, *, hostname: Optional[str] = None) -> str:
    """Join the base screenshot directory with the current-folder name."""

    return os.path.join(base_dir, current_screenshot_folder_name(hostname))
