#!/usr/bin/env python3
"""Minimal admin service that surfaces the latest screenshots per screen."""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from flask import Flask, jsonify, render_template

from schedule import build_scheduler

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "screens_config.json")
SCREENSHOT_DIR = os.path.join(SCRIPT_DIR, "screenshots")
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}

app = Flask(__name__, static_folder="screenshots", static_url_path="/screenshots")
_logger = logging.getLogger(__name__)
_auto_render_lock = threading.Lock()
_auto_render_done = False


@dataclass
class ScreenInfo:
    id: str
    frequency: int
    last_screenshot: Optional[str]
    last_captured: Optional[str]


def _sanitize_directory_name(name: str) -> str:
    safe = name.strip().replace("/", "-").replace("\\", "-")
    safe = "".join(ch for ch in safe if ch.isalnum() or ch in (" ", "-", "_"))
    return safe or "Screens"


def _latest_screenshot(screen_id: str) -> Optional[tuple[str, datetime]]:
    folder = os.path.join(SCREENSHOT_DIR, _sanitize_directory_name(screen_id))
    if not os.path.isdir(folder):
        return None

    latest_path: Optional[str] = None
    latest_mtime: float = -1.0

    for entry in os.scandir(folder):
        if not entry.is_file():
            continue
        _, ext = os.path.splitext(entry.name)
        if ext.lower() not in ALLOWED_EXTENSIONS:
            continue
        mtime = entry.stat().st_mtime
        if mtime > latest_mtime:
            latest_mtime = mtime
            rel_path = os.path.join(os.path.basename(folder), entry.name)
            latest_path = rel_path.replace(os.sep, "/")

    if latest_path is None:
        return None

    captured = datetime.fromtimestamp(latest_mtime)
    return latest_path, captured


def _load_config() -> Dict[str, Dict[str, int]]:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"screens": {}}

    if not isinstance(data, dict):
        raise ValueError("Configuration must be a JSON object")
    screens = data.get("screens")
    if not isinstance(screens, dict):
        raise ValueError("Configuration must contain a 'screens' mapping")
    return {"screens": screens}


def _collect_screen_info() -> List[ScreenInfo]:
    config = _load_config()
    # Validate the configuration by attempting to build a scheduler.
    build_scheduler(config)

    screens: List[ScreenInfo] = []
    for screen_id, freq in config["screens"].items():
        try:
            frequency = int(freq)
        except (TypeError, ValueError):
            frequency = 0
        latest = _latest_screenshot(screen_id)
        if latest is None:
            screens.append(ScreenInfo(screen_id, frequency, None, None))
        else:
            rel_path, captured = latest
            screens.append(
                ScreenInfo(
                    screen_id,
                    frequency,
                    rel_path,
                    captured.isoformat(timespec="seconds"),
                )
            )
    return screens


def _run_startup_renderer() -> None:
    """Render the latest screenshots when the service starts."""

    if app.config.get("TESTING"):
        return

    if os.environ.get("ADMIN_DISABLE_AUTO_RENDER") == "1":
        _logger.info("Skipping automatic screen render due to environment override.")
        return

    try:
        from render_all_screens import render_all_screens as _render_all_screens
    except Exception as exc:  # pragma: no cover - import errors are unexpected
        _logger.warning("Initial render unavailable: %s", exc)
        return

    try:
        _logger.info("Rendering all screens to refresh admin gallery…")
        result = _render_all_screens(sync_screenshots=True, create_archive=False)
        if result != 0:
            _logger.warning("Initial render exited with status %s", result)
    except Exception as exc:  # pragma: no cover - runtime failure is logged
        _logger.exception("Initial render failed: %s", exc)


@app.before_request
def _prime_screenshots() -> None:
    global _auto_render_done

    if _auto_render_done:
        return

    with _auto_render_lock:
        if _auto_render_done:
            return
        _run_startup_renderer()
        _auto_render_done = True


@app.route("/")
def index() -> str:
    try:
        screens = _collect_screen_info()
        error = None
    except ValueError as exc:
        screens = []
        error = str(exc)
    return render_template("admin.html", screens=screens, error=error)


@app.route("/api/screens")
def api_screens():
    try:
        screens = _collect_screen_info()
        return jsonify(status="ok", screens=[screen.__dict__ for screen in screens])
    except ValueError as exc:
        return jsonify(status="error", message=str(exc)), 500


@app.route("/api/config")
def api_config():
    try:
        config = _load_config()
        return jsonify(status="ok", config=config)
    except ValueError as exc:
        return jsonify(status="error", message=str(exc)), 500


if __name__ == "__main__":  # pragma: no cover
    host = os.environ.get("ADMIN_HOST", "0.0.0.0")
    port = int(os.environ.get("ADMIN_PORT", "5001"))
    debug = os.environ.get("ADMIN_DEBUG") == "1" or os.environ.get("FLASK_DEBUG") == "1"

    if debug:
        app.run(host=host, port=port, debug=True)
    else:
        from waitress import serve

        serve(app, host=host, port=port)
