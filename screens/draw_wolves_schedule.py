#!/usr/bin/env python3
"""Chicago Wolves schedule + score screens that mirror the Hawks layouts."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw

from config import (
    AHL_FALLBACK_LOGO,
    AHL_IMAGES_DIR,
    AHL_TEAM_ID,
    AHL_TEAM_TRICODE,
    HEIGHT,
    WIDTH,
)
from utils import LED_INDICATOR_LEVEL

import screens.draw_hawks_schedule as _hawks


_WOLVES_TRI = (AHL_TEAM_TRICODE or "WOL").upper()


@contextmanager
def _wolves_assets():
    prev_dir = getattr(_hawks, "NHL_DIR", AHL_IMAGES_DIR)
    prev_logo = getattr(_hawks, "FALLBACK_LOGO", AHL_FALLBACK_LOGO)
    prev_id = getattr(_hawks, "TEAM_ID", AHL_TEAM_ID)
    prev_tri = getattr(_hawks, "TEAM_TRICODE", _WOLVES_TRI)
    _hawks.NHL_DIR = AHL_IMAGES_DIR
    _hawks.FALLBACK_LOGO = AHL_FALLBACK_LOGO
    _hawks.TEAM_ID = AHL_TEAM_ID
    _hawks.TEAM_TRICODE = _WOLVES_TRI
    try:
        yield
    finally:
        _hawks.NHL_DIR = prev_dir
        _hawks.FALLBACK_LOGO = prev_logo
        _hawks.TEAM_ID = prev_id
        _hawks.TEAM_TRICODE = prev_tri


def _team_payload(team: Optional[Dict]) -> Dict:
    if not isinstance(team, dict):
        return {}
    info = {
        "id": team.get("id"),
        "abbrev": team.get("abbr"),
        "name": team.get("name"),
        "shortName": team.get("nickname") or team.get("name"),
    }
    return {"team": info, "score": team.get("score")}


def _tri(team: Optional[Dict], fallback: str) -> str:
    if isinstance(team, dict):
        abbr = team.get("abbr")
        if isinstance(abbr, str) and abbr.strip():
            return abbr.strip().upper()
    return fallback


def _scoreboard_values(
    game: Dict,
) -> Tuple[str, Optional[int], Optional[int], str, Optional[int], Optional[int]]:
    away = game.get("away") or {}
    home = game.get("home") or {}
    return (
        _tri(away, "AWY"),
        away.get("score"),
        away.get("shots"),
        _tri(home, "HME"),
        home.get("score"),
        home.get("shots"),
    )


def _relative_date_label(game: Dict) -> str:
    date_text = (game.get("official_date") or "")[:10]
    iso = (game.get("start_iso") or "")[:10]
    helper = getattr(_hawks, "_MLB_REL_DATE_ONLY", None)
    if callable(helper):
        label = helper(date_text or iso)
        if label:
            return label
    return _hawks._format_last_date_bottom(game.get("start_iso", ""))


def _wolves_last_bottom_line(game: Dict) -> str:
    status = ((game.get("status") or {}).get("detail") or "Final").strip()
    label = _relative_date_label(game)
    parts = [p for p in (status, label) if p]
    return " • ".join(parts)


def _wolves_led_override(game: Dict) -> Optional[Tuple[float, float, float]]:
    home = game.get("home") or {}
    away = game.get("away") or {}
    wolves_home = str(home.get("id")) == str(AHL_TEAM_ID)
    wolves_score = home.get("score") if wolves_home else away.get("score")
    opp_score = away.get("score") if wolves_home else home.get("score")
    if not isinstance(wolves_score, int) or not isinstance(opp_score, int) or wolves_score == opp_score:
        return None
    if wolves_score > opp_score:
        return (0.0, LED_INDICATOR_LEVEL, 0.0)
    return (LED_INDICATOR_LEVEL, 0.0, 0.0)


def _prepare_next_payload(game: Dict) -> Optional[Dict]:
    if not isinstance(game, dict):
        return None

    def _entry(team: Dict) -> Dict:
        payload = _team_payload(team)
        team_obj = payload.get("team") or {}
        return {
            "team": team_obj,
            "abbrev": team_obj.get("abbrev"),
            "score": payload.get("score"),
        }

    away = game.get("away") or {}
    home = game.get("home") or {}
    return {
        "gameDate": game.get("start_iso"),
        "officialDate": game.get("official_date"),
        "startTimeCentral": game.get("start_time_central"),
        "gameState": (game.get("status") or {}).get("state"),
        "awayTeam": _entry(away),
        "homeTeam": _entry(home),
        "teams": {"away": _entry(away), "home": _entry(home)},
    }


def draw_last_wolves_game(display, game, transition: bool = False):
    if not isinstance(game, dict):
        logging.warning("wolves last: missing game data")
        return None

    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    draw = ImageDraw.Draw(img)
    y = 2
    y += _hawks._draw_title_line(img, draw, y, "Last Wolves game:", _hawks.FONT_TITLE)

    bottom_line = _wolves_last_bottom_line(game)
    reserve = (_hawks._text_h(draw, _hawks.FONT_BOTTOM) + 2) if bottom_line else 0
    away_tri, away_score, away_sog, home_tri, home_score, home_sog = _scoreboard_values(game)
    away_payload = _team_payload(game.get("away"))
    home_payload = _team_payload(game.get("home"))

    with _wolves_assets():
        _hawks._draw_scoreboard(
            img,
            draw,
            y,
            away_tri,
            away_score,
            away_sog,
            home_tri,
            home_score,
            home_sog,
            away_label=_hawks._team_scoreboard_label(away_payload, away_tri),
            home_label=_hawks._team_scoreboard_label(home_payload, home_tri),
            put_sog_label=True,
            bottom_reserved_px=reserve,
        )

    if bottom_line:
        _hawks._center_bottom_text(draw, bottom_line, _hawks.FONT_BOTTOM)

    led_override = _wolves_led_override(game)
    return _hawks._push(display, img, transition=transition, led_override=led_override)


def draw_sports_screen_wolves(display, game, transition: bool = False):
    payload = _prepare_next_payload(game)
    if not payload:
        logging.warning("wolves next: missing payload")
        return None
    with _wolves_assets():
        return _hawks._draw_next_card(
            display,
            payload,
            title="Next Wolves game:",
            transition=transition,
            log_label="wolves next",
        )


def draw_wolves_next_home_game(display, game, transition: bool = False):
    payload = _prepare_next_payload(game)
    if not payload:
        logging.warning("wolves next home: missing payload")
        return None
    with _wolves_assets():
        return _hawks._draw_next_card(
            display,
            payload,
            title="Next at home...",
            transition=transition,
            log_label="wolves next home",
        )
