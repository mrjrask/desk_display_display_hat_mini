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

from flask import Flask, abort, jsonify, render_template, request

from schedule import build_scheduler
from config_store import ConfigStore

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "screens_config.json")
SCREENSHOT_DIR = os.path.join(SCRIPT_DIR, "screenshots")
CURRENT_SCREENSHOT_DIR = os.path.join(SCREENSHOT_DIR, "current")
STYLE_CONFIG_PATH = os.environ.get(
    "SCREENS_STYLE_PATH", os.path.join(SCRIPT_DIR, "screens_style.json")
)
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
FONTS_DIR = os.path.join(SCRIPT_DIR, "fonts")

app = Flask(__name__, static_folder="screenshots", static_url_path="/screenshots")
_logger = logging.getLogger(__name__)
_auto_render_lock = threading.Lock()
_auto_render_done = False
_STYLE_STORE = ConfigStore(STYLE_CONFIG_PATH)


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
    prefix = _sanitize_directory_name(screen_id).replace(" ", "_")
    if os.path.isdir(CURRENT_SCREENSHOT_DIR):
        latest_current: Optional[tuple[str, float]] = None
        for entry in os.scandir(CURRENT_SCREENSHOT_DIR):
            if not entry.is_file():
                continue
            name, ext = os.path.splitext(entry.name)
            if name != prefix or ext.lower() not in ALLOWED_EXTENSIONS:
                continue
            mtime = entry.stat().st_mtime
            if latest_current is None or mtime > latest_current[1]:
                latest_current = (os.path.join("current", entry.name), mtime)
        if latest_current:
            rel_path, mtime = latest_current
            return rel_path.replace(os.sep, "/"), datetime.fromtimestamp(mtime)

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


def _load_style_overrides() -> Dict[str, Dict[str, Dict[str, dict]]]:
    payload = _STYLE_STORE.load()
    if not isinstance(payload, dict):
        payload = {}
    screens = payload.get("screens")
    if not isinstance(screens, dict):
        screens = {}
    return {"screens": screens}


def _save_style_overrides(
    config: Dict[str, Dict[str, Dict[str, dict]]],
    *,
    actor: str,
    summary: str,
    metadata: Optional[Dict[str, str]] = None,
) -> int:
    version = _STYLE_STORE.save(
        config,
        actor=actor,
        summary=summary,
        metadata=metadata,
    )
    try:
        from config import reload_style_config  # type: ignore

        reload_style_config()
    except Exception:  # pragma: no cover - cache refresh best-effort
        pass
    return version


def _list_font_options() -> List[str]:
    fonts: List[str] = []
    try:
        for entry in sorted(os.listdir(FONTS_DIR)):
            if entry.lower().endswith((".ttf", ".otf")):
                fonts.append(entry)
    except FileNotFoundError:
        return []
    return fonts


class StyleValidationError(Exception):
    def __init__(self, errors: List[Dict[str, str]]):
        super().__init__("Invalid style payload")
        self.errors = errors


def _validate_style_payload(payload: Dict) -> Dict[str, Dict[str, Dict[str, float]]]:
    if not isinstance(payload, dict):
        raise StyleValidationError([
            {"field": "body", "message": "JSON object expected"},
        ])

    if payload.get("clear"):
        return {}

    errors: List[Dict[str, str]] = []

    fonts_payload = payload.get("fonts")
    fonts: Dict[str, Dict[str, object]] = {}
    if fonts_payload is not None:
        if not isinstance(fonts_payload, dict):
            errors.append({"field": "fonts", "message": "Fonts must be an object"})
        else:
            for slot, spec in fonts_payload.items():
                if not isinstance(slot, str) or not slot.strip():
                    errors.append(
                        {"field": "fonts", "message": "Font slot names must be strings"}
                    )
                    continue
                if not isinstance(spec, dict):
                    errors.append(
                        {
                            "field": f"fonts.{slot}",
                            "message": "Font overrides must be objects",
                        }
                    )
                    continue
                entry: Dict[str, object] = {}
                family = spec.get("family")
                if isinstance(family, str) and family.strip():
                    entry["family"] = family.strip()
                size = spec.get("size")
                if size is not None:
                    if isinstance(size, int) and size > 0:
                        entry["size"] = size
                    else:
                        errors.append(
                            {
                                "field": f"fonts.{slot}.size",
                                "message": "Font size must be a positive integer",
                            }
                        )
                if entry:
                    fonts[slot] = entry

    images_payload = payload.get("images")
    images: Dict[str, Dict[str, float]] = {}
    if images_payload is not None:
        if not isinstance(images_payload, dict):
            errors.append({"field": "images", "message": "Images must be an object"})
        else:
            for slot, spec in images_payload.items():
                if not isinstance(slot, str) or not slot.strip():
                    errors.append(
                        {"field": "images", "message": "Image slot names must be strings"}
                    )
                    continue
                if not isinstance(spec, dict):
                    errors.append(
                        {
                            "field": f"images.{slot}",
                            "message": "Image overrides must be objects",
                        }
                    )
                    continue
                scale = spec.get("scale")
                try:
                    scale_value = float(scale)
                except (TypeError, ValueError):
                    errors.append(
                        {
                            "field": f"images.{slot}.scale",
                            "message": "Scale must be a positive number",
                        }
                    )
                    continue
                if scale_value <= 0:
                    errors.append(
                        {
                            "field": f"images.{slot}.scale",
                            "message": "Scale must be greater than zero",
                        }
                    )
                    continue
                images[slot] = {"scale": scale_value}

    if errors:
        raise StyleValidationError(errors)

    entry: Dict[str, Dict] = {}
    if fonts:
        entry["fonts"] = fonts
    if images:
        entry["images"] = images

    if not entry:
        raise StyleValidationError(
            [
                {
                    "field": "body",
                    "message": "Provide at least one font or image override or set clear=true",
                }
            ]
        )

    return entry


def _require_api_token() -> str:
    expected = os.environ.get("ADMIN_API_TOKEN")
    if not expected:
        abort(403, description="ADMIN_API_TOKEN is not configured on the server")

    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.headers.get("X-Admin-Token", "").strip()

    if not token or token != expected:
        abort(401, description="Invalid or missing admin token")
    return token


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
    style_config = _load_style_overrides()
    font_options = _list_font_options()
    return render_template(
        "admin.html",
        screens=screens,
        error=error,
        style_config=style_config.get("screens", {}),
        font_options=font_options,
    )


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


@app.route("/api/style-overrides", methods=["GET"])
def api_style_overrides():
    _require_api_token()
    config = _load_style_overrides()
    return jsonify(status="ok", config=config)


@app.route("/api/style-overrides/<path:screen_id>", methods=["PATCH", "POST"])
def api_update_style_override(screen_id: str):
    _require_api_token()
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify(status="error", message="JSON body is required"), 400

    try:
        entry = _validate_style_payload(payload)
    except StyleValidationError as exc:
        return (
            jsonify(status="error", message="Invalid payload", errors=exc.errors),
            400,
        )

    config = _load_style_overrides()
    screens = config.setdefault("screens", {})
    summary: str
    if entry:
        screens[screen_id] = entry
        summary = f"Update style overrides for {screen_id}"
    else:
        screens.pop(screen_id, None)
        summary = f"Clear style overrides for {screen_id}"

    version = _save_style_overrides(
        config,
        actor="admin-ui",
        summary=summary,
        metadata={"screen_id": screen_id},
    )
    return jsonify(status="ok", config=screens.get(screen_id, {}), version=version)


if __name__ == "__main__":  # pragma: no cover
    host = os.environ.get("ADMIN_HOST", "0.0.0.0")
    port = int(os.environ.get("ADMIN_PORT", "5001"))
    debug = os.environ.get("ADMIN_DEBUG") == "1" or os.environ.get("FLASK_DEBUG") == "1"

    if debug:
        app.run(host=host, port=port, debug=True)
    else:
        from waitress import serve

        serve(app, host=host, port=port)
