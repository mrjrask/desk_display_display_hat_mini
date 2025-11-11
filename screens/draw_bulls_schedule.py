#!/usr/bin/env python3
"""
draw_bulls_schedule.py

Bulls screens styled to match the Blackhawks cards:
- Last Bulls game: compact 2-row scoreboard (logo+abbr | score) with title strip and relative-date footer.
- Bulls Live: same scoreboard with live status line.
- Next Bulls game / Next at home: centered matchup + two big logos with an '@' between them,
  footer with relative date + local time.

Changes:
- Removed colored background behind Bulls score row.
- Removed "PTS" label above score column.
- Added '@' between the two team logos on both Next-game screens.
- Opponent now shown as "City Team".
- Bottom footer line moved up 5px.
"""

from __future__ import annotations
import datetime as dt
import logging
import os
from typing import Dict, List, Optional, Sequence, Tuple
from PIL import Image, ImageDraw, ImageFont

from config import (
    FONT_DATE_SPORTS,
    FONT_TEAM_SPORTS,
    FONT_TITLE_SPORTS,
    NBA_IMAGES_DIR,         # images/nba/
    NBA_TEAM_TRICODE,       # e.g., "CHI"
    TIMES_SQUARE_FONT_PATH, # TimesSquare-m105.ttf
    WIDTH,
    HEIGHT,
    CENTRAL_TIME,
)

from utils import (
    clear_display,
    LED_INDICATOR_LEVEL,
    ScreenImage,
    standard_next_game_logo_height,
    temporary_display_led,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fonts & layout

TS_PATH = TIMES_SQUARE_FONT_PATH
NBA_DIR = NBA_IMAGES_DIR
TEAM_TRICODE = (NBA_TEAM_TRICODE or "CHI").upper()

NBA_TEAM_NICKNAMES = {
    "ATL": "Hawks",
    "BOS": "Celtics",
    "BKN": "Nets",
    "BRK": "Nets",
    "CHA": "Hornets",
    "CHO": "Hornets",
    "CHI": "Bulls",
    "CLE": "Cavaliers",
    "DAL": "Mavericks",
    "DEN": "Nuggets",
    "DET": "Pistons",
    "GSW": "Warriors",
    "GS": "Warriors",
    "HOU": "Rockets",
    "IND": "Pacers",
    "LAC": "Clippers",
    "LAL": "Lakers",
    "MEM": "Grizzlies",
    "MIA": "Heat",
    "MIL": "Bucks",
    "MIN": "Timberwolves",
    "NOP": "Pelicans",
    "NO": "Pelicans",
    "NYK": "Knicks",
    "NY": "Knicks",
    "OKC": "Thunder",
    "ORL": "Magic",
    "PHI": "76ers",
    "PHL": "76ers",
    "PHX": "Suns",
    "PHO": "Suns",
    "POR": "Trail Blazers",
    "SAC": "Kings",
    "SAS": "Spurs",
    "SA": "Spurs",
    "TOR": "Raptors",
    "UTA": "Jazz",
    "UTAH": "Jazz",
    "WAS": "Wizards",
    "WSH": "Wizards",
}

def _ts(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(TS_PATH, size)
    except Exception:
        logging.warning("TimesSquare font missing at %s; using fallback.", TS_PATH)
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except Exception:
            return ImageFont.load_default()

# Tuned for 320x240; scales acceptably for larger canvases
FONT_ABBR   = _ts(33 if HEIGHT >= 240 else 28)
FONT_SCORE  = _ts(48 if HEIGHT >= 240 else 38)
FONT_SMALL  = _ts(22 if HEIGHT >= 240 else 18)

FONT_TITLE    = FONT_TITLE_SPORTS
FONT_BOTTOM   = FONT_DATE_SPORTS
FONT_NEXT_OPP = FONT_TEAM_SPORTS

# Adjusted bottom line margin (moved up by 5 pixels)
BOTTOM_LINE_MARGIN = 8

# Colors
BACKGROUND_COLOR = (0, 0, 0)
TEXT_COLOR       = (255, 255, 255)

# ─────────────────────────────────────────────────────────────────────────────
# Text helpers

def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    try:
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return r - l, b - t, l, t
    except Exception:
        w, h = draw.textsize(text, font=font)
        return w, h, 0, 0

def _text_w(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    return _measure(draw, text, font)[0]

def _center_text(draw: ImageDraw.ImageDraw, y: int, text: str, font: ImageFont.ImageFont):
    w, h, _, _ = _measure(draw, text, font)
    x = (WIDTH - w) // 2
    draw.text((x, y), text, font=font, fill=TEXT_COLOR)
    return y + h

# ─────────────────────────────────────────────────────────────────────────────
# Core helpers

def _team_entry(game: Dict, side: str) -> Dict[str, Optional[str]]:
    teams = game.get("teams") or {}
    entry = teams.get(side) or {}
    team_info = entry.get("team") if isinstance(entry.get("team"), dict) else None

    tri_candidates = (
        "tri", "triCode", "tricode", "teamTricode", "teamTriCode",
        "abbreviation", "abbr", "teamAbbreviation", "teamAbbrev",
    )
    name_candidates = (
        "nickname", "teamNickname", "shortName", "teamShortName",
        "teamName", "name", "displayName", "fullName",
        "clubName", "clubNickname",
    )
    location_candidates = (
        "city", "teamCity", "teamLocation", "cityName",
        "market", "location", "homeCity",
    )

    score = entry.get("score")
    try:
        score = int(score) if score is not None and str(score).strip() != "" else None
    except Exception:
        score = None

    tri = ""
    if team_info and isinstance(team_info, dict):
        for k in tri_candidates:
            if team_info.get(k):
                tri = str(team_info[k])
                break
    if not tri:
        for k in tri_candidates:
            if entry.get(k):
                tri = str(entry[k])
                break

    names: List[str] = []
    locations: List[str] = []

    if team_info and isinstance(team_info, dict):
        for key in name_candidates:
            v = team_info.get(key)
            if isinstance(v, str) and v.strip():
                names.append(v.strip())
        for key in location_candidates:
            v = team_info.get(key)
            if isinstance(v, str) and v.strip():
                locations.append(v.strip())

    for key in name_candidates:
        v = entry.get(key)
        if isinstance(v, str) and v.strip():
            names.append(v.strip())
    for key in location_candidates:
        v = entry.get(key)
        if isinstance(v, str) and v.strip():
            locations.append(v.strip())

    tri_upper = (tri or "").upper()
    nickname = NBA_TEAM_NICKNAMES.get(tri_upper)

    label = (nickname or (names[0] if names else tri) or "").strip() or "NBA"
    return {"tri": tri or label, "name": nickname or names[0] if names else label, "label": label, "score": score}

def _is_bulls_side(entry: Dict[str, Optional[str]]) -> bool:
    tri = (entry.get("tri") or "").upper()
    return tri == TEAM_TRICODE or tri == "CHI"

# ─────────────────────────────────────────────────────────────────────────────
# Format helpers

def _format_footer_next(game: Dict) -> str:
    start = _get_local_start(game)
    if not isinstance(start, dt.datetime):
        return _relative_label(_official_date(game))
    return start.strftime("%a, %b %-d · %-I:%M %p")

def _format_footer_live(game: Dict) -> str:
    status = _status_text(game).strip()
    if not status:
        status = "Live"
    date_label = _relative_label(_official_date(game))
    parts = [p for p in (status, date_label) if p]
    return " • ".join(parts)

def _format_matchup_line(game: Dict) -> str:
    away = _team_entry(game, "away")
    home = _team_entry(game, "home")
    bulls_home = _is_bulls_side(home)
    opponent = away if bulls_home else home

    city = opponent.get("city") or opponent.get("teamCity") or opponent.get("market") or ""
    name = opponent.get("name") or opponent.get("label") or opponent.get("tri") or ""
    opponent_full = f"{city.strip()} {name.strip()}".strip()
    opponent_full = " ".join(opponent_full.split())

    prefix = "vs." if bulls_home else "@"
    return f"{prefix} {opponent_full}".strip()

# ─────────────────────────────────────────────────────────────────────────────
# Public screen functions

def draw_last_bulls_game(display, game: Optional[Dict], transition: bool = False):
    if not game:
        img = _render_message("Last Bulls game:", "No results")
        return _push(display, img, transition=transition)

    footer = _format_footer_last(game)
    img = _render_scoreboard(game, title="Last Bulls game:", footer=footer)

    led_override = None
    away = _team_entry(game, "away")
    home = _team_entry(game, "home")
    bulls = away if _is_bulls_side(away) else home
    opp = home if bulls is away else away
    if bulls and opp and bulls.get("score") is not None and opp.get("score") is not None:
        try:
            b, o = int(bulls["score"]), int(opp["score"])
            if b > o:
                led_override = (0.0, 1.0, 0.0)
            elif b < o:
                led_override = (1.0, 0.0, 0.0)
        except Exception:
            pass

    if led_override and LED_INDICATOR_LEVEL and LED_INDICATOR_LEVEL > 0:
        with temporary_display_led(*led_override):
            return _push(display, img, transition=transition)
    return _push(display, img, transition=transition)

def draw_live_bulls_game(display, game: Optional[Dict], transition: bool = False):
    if not game or _game_state(game) != "live":
        img = _render_message("Bulls Live:", "Not in progress")
        return _push(display, img, transition=transition)
    footer = _format_footer_live(game)
    status = _status_text(game) or "Live"
    img = _render_scoreboard(game, title="Bulls Live:", footer=footer, status_line=status)
    return _push(display, img, transition=transition)

def draw_sports_screen_bulls(display, game: Optional[Dict], transition: bool = False):
    if not game:
        img = _render_message("Next Bulls game:", "No upcoming games scheduled")
        return _push(display, img, transition=transition)
    img = _render_next_game(game, title="Next Bulls game:")
    return _push(display, img, transition=transition)

def draw_bulls_next_home_game(display, game: Optional[Dict], transition: bool = False):
    if not game:
        img = _render_message("Next at home...", "No United Center games scheduled")
        return _push(display, img, transition=transition)
    img = _render_next_game(game, title="Next at home...")
    return _push(display, img, transition=transition)
