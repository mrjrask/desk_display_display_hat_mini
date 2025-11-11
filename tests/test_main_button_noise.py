"""Tests for filtering out spurious simultaneous button presses."""

import importlib
import sys

import pytest

import data_fetch
from services import wifi_utils


@pytest.fixture
def main_for_buttons(monkeypatch):
    monkeypatch.setattr(wifi_utils, "start_monitor", lambda: None)
    monkeypatch.setattr(wifi_utils, "stop_monitor", lambda: None)
    monkeypatch.setattr(data_fetch, "fetch_weather", lambda: {})
    monkeypatch.setattr(data_fetch, "fetch_blackhawks_last_game", lambda: None)
    monkeypatch.setattr(data_fetch, "fetch_blackhawks_live_game", lambda: None)
    monkeypatch.setattr(data_fetch, "fetch_blackhawks_next_game", lambda: None)
    monkeypatch.setattr(data_fetch, "fetch_blackhawks_next_home_game", lambda: None)
    monkeypatch.setattr(data_fetch, "fetch_bulls_last_game", lambda: None)
    monkeypatch.setattr(data_fetch, "fetch_bulls_live_game", lambda: None)
    monkeypatch.setattr(data_fetch, "fetch_bulls_next_game", lambda: None)
    monkeypatch.setattr(data_fetch, "fetch_bulls_next_home_game", lambda: None)
    monkeypatch.setattr(data_fetch, "fetch_cubs_games", lambda: {})
    monkeypatch.setattr(data_fetch, "fetch_cubs_standings", lambda: None)
    monkeypatch.setattr(data_fetch, "fetch_sox_games", lambda: {})
    monkeypatch.setattr(data_fetch, "fetch_sox_standings", lambda: None)

    sys.modules.pop("main", None)
    main = importlib.import_module("main")

    if main._button_monitor_thread and main._button_monitor_thread.is_alive():
        main._shutdown_event.set()
        main._button_monitor_thread.join(timeout=1.0)
        main._shutdown_event.clear()
        main._button_monitor_thread = None

    main._manual_skip_event.clear()
    main._skip_request_pending = False
    main._BUTTON_STATE = {name: False for name in main._BUTTON_NAMES}

    yield main

    main.request_shutdown("tests")
    main._finalize_shutdown()
    sys.modules.pop("main", None)


class _FakeDisplay:
    def __init__(self, pressed=None):
        self.pressed = set(pressed or [])

    def is_button_pressed(self, name: str) -> bool:
        return name in self.pressed


def test_simultaneous_presses_are_treated_as_noise(main_for_buttons, monkeypatch):
    fake_display = _FakeDisplay({"A", "B", "X", "Y"})
    main_for_buttons.display = fake_display

    handled = []

    def fake_handle(name: str) -> bool:
        handled.append(name)
        return False

    monkeypatch.setattr(main_for_buttons, "_handle_button_down", fake_handle)

    result = main_for_buttons._check_control_buttons()

    assert result is False
    assert handled == []
    assert all(state is False for state in main_for_buttons._BUTTON_STATE.values())
    assert main_for_buttons._skip_request_pending is False


def test_single_press_still_processed(main_for_buttons, monkeypatch):
    fake_display = _FakeDisplay({"X"})
    main_for_buttons.display = fake_display

    handled = []

    def fake_handle(name: str) -> bool:
        handled.append(name)
        return name == "X"

    monkeypatch.setattr(main_for_buttons, "_handle_button_down", fake_handle)

    result = main_for_buttons._check_control_buttons()

    assert result is True
    assert handled == ["X"]
    assert main_for_buttons._BUTTON_STATE["X"] is True

    fake_display.pressed.clear()
    handled.clear()

    result = main_for_buttons._check_control_buttons()

    assert result is False
    assert handled == []
    assert main_for_buttons._BUTTON_STATE["X"] is False
