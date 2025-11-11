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
    load_team_logo,
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
    date_fmt = "%a, %b %-d" if os.name != "nt" else "%a, %b %#d"
    time_fmt = "%-I:%M %p" if os.name != "nt" else "%#I:%M %p"
    return f"{start.strftime(date_fmt)} · {start.strftime(time_fmt)}"

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
# Date/time helpers & status formatting

def _parse_local_datetime(value) -> Optional[dt.datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            parsed = dt.datetime.strptime(text, fmt)
        except Exception:
            continue
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(CENTRAL_TIME)
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(CENTRAL_TIME)


def _get_local_start(game: Dict) -> Optional[dt.datetime]:
    if not isinstance(game, dict):
        return None
    start = game.get("_start_local")
    if isinstance(start, dt.datetime):
        try:
            return start.astimezone(CENTRAL_TIME)
        except Exception:
            if start.tzinfo is None:
                try:
                    return start.replace(tzinfo=dt.timezone.utc).astimezone(CENTRAL_TIME)
                except Exception:
                    return start
            return start
    for candidate in (
        game.get("gameDate"),
        game.get("startTimeUTC"),
        game.get("startTime"),
        game.get("date"),
    ):
        parsed = _parse_local_datetime(candidate)
        if isinstance(parsed, dt.datetime):
            return parsed
    return None


def _official_date(game: Dict) -> str:
    if not isinstance(game, dict):
        return ""
    official = game.get("officialDate")
    if isinstance(official, dt.date):
        return official.isoformat()
    if isinstance(official, str) and official.strip():
        return official.strip()[:10]
    start = _get_local_start(game)
    if isinstance(start, dt.datetime):
        return start.date().isoformat()
    fallback = game.get("gameDate")
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()[:10]
    return ""


def _relative_label(value) -> str:
    if isinstance(value, dt.datetime):
        date_value = value.date()
    elif isinstance(value, dt.date):
        date_value = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                date_value = dt.datetime.strptime(text[: len(fmt)], fmt).date()
                break
            except Exception:
                continue
        else:
            return text
    else:
        return ""

    today = dt.datetime.now(CENTRAL_TIME).date()
    delta = (date_value - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta == -1:
        return "Yesterday"
    if 2 <= delta <= 7:
        return date_value.strftime("%A")
    if -7 <= delta <= -2:
        return f"{abs(delta)} days ago"
    fmt = "%a, %b %#d" if os.name == "nt" else "%a, %b %-d"
    return date_value.strftime(fmt)


def _format_footer_last(game: Dict) -> str:
    label = _relative_label(_official_date(game))
    return label or "Final"


def _format_clock(clock_value: Optional[str]) -> str:
    if not clock_value:
        return ""
    if isinstance(clock_value, (int, float)):
        total_seconds = int(clock_value)
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"
    text = str(clock_value).strip()
    if not text:
        return ""
    if text.startswith("PT"):
        rem = text[2:]
        minutes = 0
        seconds = 0
        try:
            if "M" in rem:
                min_part, rem = rem.split("M", 1)
                minutes = int(float(min_part))
            if "S" in rem:
                sec_part = rem.split("S", 1)[0]
                seconds = int(float(sec_part))
        except Exception:
            return text
        return f"{minutes}:{seconds:02d}"
    return text


def _game_state(game: Dict) -> str:
    status = (game or {}).get("status") or {}
    abstract = str(status.get("abstractGameState") or "").lower()
    if abstract:
        return abstract
    detailed = str(status.get("detailedState") or "").lower()
    if "final" in detailed:
        return "final"
    if "live" in detailed or "progress" in detailed:
        return "live"
    if any(word in detailed for word in ("preview", "schedule", "pregame")):
        return "preview"
    code = str(status.get("statusCode") or "")
    if code == "3":
        return "final"
    if code == "2":
        return "live"
    if code == "1":
        return "preview"
    return detailed or abstract or ""


def _status_text(game: Dict) -> str:
    state = _game_state(game)
    status = (game or {}).get("status") or {}
    detailed = str(status.get("detailedState") or "").strip()
    linescore = (game or {}).get("linescore") or {}

    if state == "final":
        return detailed or "Final"

    if state == "live":
        lower_detailed = detailed.lower()
        if "halftime" in lower_detailed:
            return "Halftime"
        clock_value = (
            linescore.get("currentPeriodTimeRemaining")
            or linescore.get("gameClock")
            or status.get("gameClock")
            or status.get("clock")
        )
        clock = _format_clock(clock_value)
        period = (
            linescore.get("currentPeriodOrdinal")
            or linescore.get("currentPeriod")
            or linescore.get("period")
            or status.get("period")
        )
        if isinstance(period, dict):
            period = period.get("current") or period.get("period") or period.get("number")
        if isinstance(period, int):
            ord_map = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
            period = ord_map.get(period, f"{period}th")
        period_text = str(period).strip() if period else ""
        parts = [p for p in (clock, period_text) if p]
        if parts:
            return " ".join(parts)
        return detailed or "Live"

    if detailed:
        return detailed
    abstract = str(status.get("abstractGameState") or "").strip()
    if abstract:
        return abstract.title()
    return ""


def _load_logo(entry: Dict[str, Optional[str]], *, height: int) -> Optional[Image.Image]:
    tri = (entry.get("tri") or entry.get("label") or "").strip()
    if not tri:
        return None
    candidates = [tri, tri.upper(), tri.lower()]
    for candidate in candidates:
        try:
            logo = load_team_logo(NBA_DIR, candidate.lower(), height=height)
        except Exception:
            logo = None
        if logo:
            return logo
    return None


def _render_message(title: str, message: str) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)

    y = _center_text(draw, 0, title, FONT_TITLE)
    y += 12
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if not lines:
        lines = [""]
    for line in lines:
        y = _center_text(draw, y, line, FONT_NEXT_OPP) + 8
    return img


def _draw_score_row(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    entry: Dict[str, Optional[str]],
    y: int,
    height: int,
    highlight: bool,
    score: Optional[int],
) -> None:
    padding = 20
    logo_height = max(28, height - 18)
    logo = _load_logo(entry, height=logo_height)

    if logo:
        y_logo = y + (height - logo.height) // 2
        img.paste(logo, (padding, y_logo), logo)
        text_x = padding + logo.width + 10
    else:
        text_x = padding

    label = (entry.get("label") or entry.get("tri") or "NBA").upper()
    _, label_h, _, _ = _measure(draw, label, FONT_ABBR)
    label_y = y + (height - label_h) // 2
    draw.text((text_x, label_y), label, font=FONT_ABBR, fill=TEXT_COLOR)

    score_text = "-" if score is None else str(score)
    score_w, score_h, _, _ = _measure(draw, score_text, FONT_SCORE)
    score_x = WIDTH - padding - score_w
    score_y = y + (height - score_h) // 2
    fill = TEXT_COLOR if highlight else (200, 200, 200)
    draw.text((score_x, score_y), score_text, font=FONT_SCORE, fill=fill)

    if highlight and LED_INDICATOR_LEVEL:
        underline_y = y + height - 4
        draw.line((padding, underline_y, WIDTH - padding, underline_y), fill=TEXT_COLOR, width=2)


def _render_scoreboard(
    game: Dict,
    *,
    title: str,
    footer: str = "",
    status_line: Optional[str] = None,
) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)

    y = _center_text(draw, 0, title, FONT_TITLE)
    y += 8

    footer_h = _measure(draw, footer, FONT_BOTTOM)[1] if footer else 0
    status_h = _measure(draw, status_line, FONT_SMALL)[1] if status_line else 0

    available = HEIGHT - y - footer_h - BOTTOM_LINE_MARGIN
    if status_line:
        available -= status_h + 8

    row_gap = 6
    min_row_height = max(
        _measure(draw, "88", FONT_SCORE)[1],
        _measure(draw, "CHI", FONT_ABBR)[1],
    ) + 12
    row_height = max(min_row_height, (available - row_gap) // 2 if available > 0 else min_row_height)

    table_height = row_height * 2 + row_gap
    if available > 0 and table_height > available:
        row_height = max(min_row_height, (available - row_gap) // 2)
        table_height = row_height * 2 + row_gap

    table_top = y
    away = _team_entry(game, "away")
    home = _team_entry(game, "home")

    for idx, team in enumerate((away, home)):
        row_y = table_top + idx * (row_height + row_gap)
        _draw_score_row(
            img,
            draw,
            entry=team,
            y=row_y,
            height=row_height,
            highlight=_is_bulls_side(team),
            score=team.get("score"),
        )

    content_bottom = table_top + table_height
    if status_line:
        content_bottom += 4
        _center_text(draw, content_bottom, status_line, FONT_SMALL)
        content_bottom += status_h + 4

    if footer:
        footer_y = HEIGHT - footer_h - BOTTOM_LINE_MARGIN
        _center_text(draw, footer_y, footer, FONT_BOTTOM)

    return img


def _render_next_game(game: Dict, *, title: str) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)

    y = _center_text(draw, 0, title, FONT_TITLE)
    y += 10

    matchup = _format_matchup_line(game)
    y = _center_text(draw, y, matchup, FONT_NEXT_OPP) + 12

    footer = _format_footer_next(game)
    footer_h = _measure(draw, footer, FONT_BOTTOM)[1] if footer else 0
    footer_y = HEIGHT - footer_h - BOTTOM_LINE_MARGIN

    logos_top = y
    available = footer_y - logos_top - 12
    desired_height = standard_next_game_logo_height(HEIGHT)
    logo_height = max(36, min(desired_height, available)) if available > 0 else desired_height

    away = _team_entry(game, "away")
    home = _team_entry(game, "home")
    logo_images: List[Image.Image] = []
    for entry in (away, home):
        logo = _load_logo(entry, height=logo_height)
        if logo:
            logo_images.append(logo)
        else:
            text = (entry.get("tri") or entry.get("label") or "?").upper()
            w, h, _, _ = _measure(draw, text, FONT_ABBR)
            img_placeholder = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(img_placeholder).text((0, 0), text, font=FONT_ABBR, fill=TEXT_COLOR)
            logo_images.append(img_placeholder)

    spacing = 18
    at_text = "@"
    at_w, at_h, _, _ = _measure(draw, at_text, FONT_ABBR)
    total_w = at_w + spacing * 2
    for logo in logo_images:
        total_w += logo.width

    x = max(0, (WIDTH - total_w) // 2)
    y_logo = logos_top + max(0, (available - logo_height) // 2)

    if logo_images:
        img.paste(logo_images[0], (x, y_logo), logo_images[0])
        x += logo_images[0].width + spacing

    at_y = y_logo + (logo_height - at_h) // 2
    draw.text((x, at_y), at_text, font=FONT_ABBR, fill=TEXT_COLOR)
    x += at_w + spacing

    if len(logo_images) > 1:
        img.paste(logo_images[1], (x, y_logo), logo_images[1])

    if footer:
        _center_text(draw, footer_y, footer, FONT_BOTTOM)

    return img


def _push(display, img: Optional[Image.Image], *, transition: bool = False, led_override=None):
    if img is None or display is None:
        return None
    if transition:
        return ScreenImage(img, displayed=False, led_override=led_override)

    def _show_image():
        try:
            clear_display(display)
        except Exception:
            pass
        try:
            if hasattr(display, "image"):
                display.image(img)
            elif hasattr(display, "ShowImage"):
                buf = display.getbuffer(img) if hasattr(display, "getbuffer") else img
                display.ShowImage(buf)
            elif hasattr(display, "display"):
                display.display(img)
        except Exception as exc:
            logging.exception("Failed to push Bulls image: %s", exc)

    if led_override is not None:
        with temporary_display_led(*led_override):
            _show_image()
    else:
        _show_image()
    return None

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
