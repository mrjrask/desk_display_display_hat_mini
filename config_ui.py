#!/usr/bin/env python3
"""Web UI for editing the screen rotation configuration."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request

from schedule import build_scheduler
from screens_catalog import SCREEN_IDS

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.environ.get(
    "SCREENS_CONFIG_PATH", os.path.join(SCRIPT_DIR, "screens_config.json")
)
LOCAL_CONFIG_PATH = os.environ.get(
    "SCREENS_CONFIG_LOCAL_PATH", os.path.join(SCRIPT_DIR, "screens_config.local.json")
)

SCREEN_CONFIG_HOST = os.environ.get("SCREEN_CONFIG_HOST", "0.0.0.0")
SCREEN_CONFIG_PORT = int(os.environ.get("SCREEN_CONFIG_PORT", "5002"))

app = Flask(__name__)


def _load_config(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"screens": {}}
    if not isinstance(data, dict):
        raise ValueError("Configuration must be a JSON object")
    screens = data.get("screens")
    if not isinstance(screens, dict):
        raise ValueError("Configuration must include a 'screens' mapping")
    return data


def _load_active_config() -> Dict[str, Any]:
    if os.path.exists(LOCAL_CONFIG_PATH):
        return _load_config(LOCAL_CONFIG_PATH)
    return _load_config(DEFAULT_CONFIG_PATH)


def _parse_alt_screen(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [item.strip() for item in value.split(",")]
    parts = [item for item in parts if item]
    return parts or None


def _serialize_alt_screen(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value if item)
    if isinstance(value, str):
        return value
    return ""


def _build_screen_entries(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    screens = config.get("screens", {})
    if not isinstance(screens, dict):
        return []

    entries: List[Dict[str, Any]] = []
    for screen_id, raw in screens.items():
        entry: Dict[str, Any] = {
            "id": screen_id,
            "frequency": 0,
            "alt_screen": "",
            "alt_frequency": "",
        }
        if isinstance(raw, dict):
            entry["frequency"] = raw.get("frequency", 0)
            alt = raw.get("alt") if isinstance(raw.get("alt"), dict) else None
            if alt:
                entry["alt_screen"] = _serialize_alt_screen(alt.get("screen"))
                entry["alt_frequency"] = alt.get("frequency", "")
        else:
            entry["frequency"] = raw
        entries.append(entry)

    return entries


def _build_config(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    screens: Dict[str, Any] = {}
    for entry in entries:
        screen_id = str(entry.get("id", "")).strip()
        if not screen_id:
            continue
        frequency = int(entry.get("frequency", 0))
        alt_screen_raw = entry.get("alt_screen")
        alt_frequency = entry.get("alt_frequency")
        alt_screen = _parse_alt_screen(str(alt_screen_raw).strip()) if alt_screen_raw is not None else None
        if alt_screen:
            alt_frequency_int = int(alt_frequency) if alt_frequency not in ("", None) else 1
            alt_payload: Dict[str, Any] = {"screen": alt_screen[0] if len(alt_screen) == 1 else alt_screen}
            alt_payload["frequency"] = alt_frequency_int
            screens[screen_id] = {"frequency": frequency, "alt": alt_payload}
        else:
            screens[screen_id] = frequency
    return {"screens": screens}


def _save_config(config: Dict[str, Any]) -> None:
    tmp_path = f"{LOCAL_CONFIG_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")
    os.replace(tmp_path, LOCAL_CONFIG_PATH)


def run_config_ui(host: str = SCREEN_CONFIG_HOST, port: int = SCREEN_CONFIG_PORT) -> None:
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


@app.route("/", methods=["GET"])
def screen_config() -> str:
    config = _load_active_config()
    entries = _build_screen_entries(config)
    return render_template(
        "screen_config.html",
        screens=entries,
        screen_ids=sorted(SCREEN_IDS),
        config_path=DEFAULT_CONFIG_PATH,
    )


@app.get("/api/screens")
def get_screens() -> Any:
    config = _load_active_config()
    return jsonify(
        {
            "screens": _build_screen_entries(config),
            "screen_ids": sorted(SCREEN_IDS),
        }
    )


@app.get("/api/screens/defaults")
def get_default_screens() -> Any:
    config = _load_config(DEFAULT_CONFIG_PATH)
    return jsonify({"screens": _build_screen_entries(config)})


@app.get("/api/screens/export")
def export_screens() -> Any:
    config = _load_active_config()
    payload = json.dumps(config, indent=2)
    return (
        payload,
        200,
        {
            "Content-Type": "application/json",
            "Content-Disposition": "attachment; filename=screens_config.export.json",
        },
    )


@app.post("/api/screens")
def save_screens() -> Any:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid payload"}), 400
    entries = payload.get("screens")
    if not isinstance(entries, list):
        return jsonify({"error": "Screens list required"}), 400

    try:
        config = _build_config(entries)
        build_scheduler(config)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    _save_config(config)
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    run_config_ui()
