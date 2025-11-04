#!/usr/bin/env python3
"""draw_bulls_schedule.py

Chicago Bulls schedule screens mirroring the Blackhawks layout: last game,
live game, next game, and next home game cards with NBA logos.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
from config import (
    TIMES_SQUARE_FONT_PATH,
    TIMES_SQUARE_EXTRA_BOLD_FONT_PATH,
    MLB_TITLE_FONT_PATH,
    MLB_TITLE_EXTRA_BOLD_FONT_PATH,
    MLB_BOTTOM_FONT_PATH,
    MLB_SMALL_FONT_PATH,
    NBA_IMAGE_DIR as NBA_IMAGE_DIR,
    NBA_TEAM_ID,
    NBA_TEAM_TRICODE,
    WIDTH,
    HEIGHT,
    CENTRAL_TIME,
)

from utils import (
    LED_INDICATOR_LEVEL,
    ScreenImage,
    clear_display,
    load_team_logo,
    standard_next_game_logo_height,
    temporary_display_led,
)

TS_PATH = TIMES_SQUARE_FONT_PATH
NBA_DIR = NBA_IMAGE_DIR
BULLS_TEAM_ID = str(NBA_TEAM_ID)
BULLS_TRICODE = (NBA_TEAM_TRICODE or "CHI").upper()


# Mirror the Hawks/MLB layout helpers when available for consistent typography.
_MLB = None
try:
    import screens.mlb_schedule as _MLB  # noqa: N816 - third-party helper module
except Exception:  # pragma: no cover - best effort import
    _MLB = None

_MLB_DRAW_TITLE = getattr(_MLB, "_draw_title_with_bold_result", None) if _MLB else None
_MLB_REL_DATE_ONLY = getattr(_MLB, "_rel_date_only", None) if _MLB else None
_MLB_FORMAT_GAME_LABEL = getattr(_MLB, "_format_game_label", None) if _MLB else None


def _font_try(paths, size, fallback=("DejaVuSans.ttf",)):
    """Best-effort font loader with graceful fallback and consistent sizing."""
    if not isinstance(paths, (list, tuple)):
        paths = [paths] if paths else []
    for p in list(paths) + list(fallback or []):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


# Typography aligned to Hawks/MLB layouts
FONT_TITLE = _font_try(
    [MLB_TITLE_EXTRA_BOLD_FONT_PATH, TIMES_SQUARE_EXTRA_BOLD_FONT_PATH, MLB_TITLE_FONT_PATH, TS_PATH], 26
)
FONT_TITLE_SPORTS = _font_try([TIMES_SQUARE_EXTRA_BOLD_FONT_PATH, TS_PATH, MLB_TITLE_FONT_PATH], 24)
FONT_ABBR = _font_try([TIMES_SQUARE_EXTRA_BOLD_FONT_PATH, TS_PATH], 28)
FONT_SCORE = _font_try([TIMES_SQUARE_EXTRA_BOLD_FONT_PATH, TS_PATH], 28)
FONT_SMALL = _font_try([MLB_SMALL_FONT_PATH, TS_PATH], 14)
FONT_BOTTOM = _font_try([MLB_BOTTOM_FONT_PATH, TS_PATH], 16)
FONT_NEXT_OPP = _font_try([TIMES_SQUARE_EXTRA_BOLD_FONT_PATH, TS_PATH], 20)

BACKGROUND_COLOR = (0, 0, 0)
HIGHLIGHT_COLOR = (55, 14, 18)
TEXT_COLOR = (255, 255, 255)
BULLS_RED = (200, 32, 45)

_LOGO_CACHE: Dict[Tuple[str, int], Optional[Image.Image]] = {}


def _load_logo_cached(abbr: str, height: int) -> Optional[Image.Image]:
    key = ((abbr or "").upper(), height)
    if key in _LOGO_CACHE:
        logo = _LOGO_CACHE[key]
        return logo.copy() if logo else None

    logo = load_team_logo(NBA_DIR, key[0], height=height)
    if logo is None and key[0] != "NBA":
        logo = load_team_logo(NBA_DIR, "NBA", height=height)
    _LOGO_CACHE[key] = logo
    return logo.copy() if logo else None


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int, int, int]:
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        return right - left, bottom - top, left, top
    except Exception:
        width, height = draw.textsize(text, font=font)
        return width, height, 0, 0


def _text_w(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    w, _, _, _ = _measure(draw, text, font)
    return w


def _text_h(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    _, h, _, _ = _measure(draw, "Hg", font)
    return h


def _center_text(draw: ImageDraw.ImageDraw, y: int, text: str, font: ImageFont.ImageFont, *, fill=TEXT_COLOR) -> int:
    w = _text_w(draw, text, font)
    x = (WIDTH - w) // 2
    draw.text((x, y), text, font=font, fill=fill)
    return _text_h(draw, font)


def _center_wrapped_text(draw, y, text, font, *, max_width: int, line_gap: int = 2, fill=TEXT_COLOR) -> int:
    words = (text or "").split()
    if not words:
        return 0
    lines = []
    cur = []
    for w in words:
        test = " ".join(cur + [w])
        if _text_w(draw, test, font) <= max_width or not cur:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))

    total = 0
    for line in lines:
        total += _center_text(draw, y + total, line, font, fill=fill)
        total += line_gap
    return max(0, total - line_gap)


def _draw_title_line(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.ImageFont = FONT_TITLE_SPORTS,
    *,
    fill=TEXT_COLOR,
) -> int:
    top = y
    if callable(_MLB_DRAW_TITLE):
        strip_height = _text_h(draw, font) + 4
        strip = Image.new("RGBA", (WIDTH, strip_height), (0, 0, 0, 0))
        strip_draw = ImageDraw.Draw(strip)
        try:
            _, used_height = _MLB_DRAW_TITLE(strip_draw, text)
        except Exception:
            used_height = _text_h(draw, font)
            strip_draw.text(((WIDTH - _text_w(strip_draw, text, font)) // 2, 0), text, font=font, fill=fill)
        img.paste(strip, (0, top), strip)
        return max(strip_height, used_height)

    width, height, left, top_offset = _measure(draw, text, font)
    x = (WIDTH - width) // 2 - left
    draw.text((x, top - top_offset), text, font=font, fill=fill)
    return height


def _draw_scoreboard_table(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    top_y: int,
    rows: Tuple[Dict[str, object], ...],
    *,
    score_label: Optional[str] = "PTS",
    bottom_reserved_px: int = 0,
) -> int:
    if not rows:
        return top_y

    header_h = _text_h(draw, FONT_SMALL) + 2
    table_top = top_y
    content_top = table_top + header_h

    total_available = max(0, HEIGHT - bottom_reserved_px - table_top)
    row_h = 34
    if total_available and total_available < (header_h + row_h * 2):
        row_h = max(24, (total_available - header_h) // 2)

    col0_w = WIDTH * 11 // 20  # Team/logo cell ~55%
    col2_w = WIDTH * 3 // 20   # Score column ~15%
    col1_w = WIDTH - (col0_w + col2_w)

    x0 = 4
    x1 = x0 + col0_w
    x2 = x1 + col1_w
    x3 = WIDTH - 4

    table_height = header_h + (row_h * 2)
    if total_available:
        table_height = min(table_height, total_available)
    if table_height < (header_h + 2):
        table_height = header_h + 2
    table_bottom = min(table_top + table_height, HEIGHT - bottom_reserved_px)
    table_height = max(header_h + 2, table_bottom - table_top)
    table_bottom = table_top + table_height

    header_bottom = table_top + header_h
    row_area_height = max(2, table_height - header_h)
    row1_h = max(1, row_area_height // 2)
    row2_h = row_area_height - row1_h

    row_slices = [(content_top, row1_h), (content_top + row1_h, row2_h)]

    # Header label above score column (like SOG on Hawks)
    if score_label and header_h:
        header_y = table_top + (header_h - _text_h(draw, FONT_SMALL)) // 2
        label_w = _text_w(draw, score_label, FONT_SMALL)
        label_x = x1 + (col2_w - label_w) // 2
        draw.text((label_x, header_y), score_label, font=FONT_SMALL, fill=TEXT_COLOR)

    specs = []
    for row, (row_top, slice_h) in zip(rows, row_slices):
        row_height = max(1, slice_h)
        tri = str(row.get("tri") or "")
        base_logo_height = max(1, row_height - 4)
        logo_height = min(64, max(24, base_logo_height))
        logo = _load_logo_cached(tri, logo_height)
        logo_w = logo.width if logo else 0
        text = (str(row.get("label") or "").strip() or tri or "—").strip()
        text_start = x0 + 6 + (logo_w + 6 if logo else 0)
        max_width = max(1, x1 - text_start - 4)
        specs.append(
            {
                "top": row_top,
                "height": row_height,
                "tri": tri,
                "score": row.get("score"),
                "text": text,
                "logo": logo,
                "max_width": max_width,
                "highlight": bool(row.get("highlight")),
            }
        )

    # Render rows
    for spec in specs:
        top = spec["top"]
        h = spec["height"]
        tri = spec["tri"]
        score = spec["score"]
        text = spec["text"]
        logo = spec["logo"]
        max_text_width = spec["max_width"]
        highlight = spec["highlight"]

        if highlight:
            draw.rectangle([x0, top, x1 - 1, top + h - 1], fill=HIGHLIGHT_COLOR)

        # Team cell with logo and abbr/label
        px = x0 + 6
        if logo:
            ly = top + (h - logo.height) // 2
            img.paste(logo, (px, ly), logo)
            px += logo.width + 6

        # Try abbr-style bold font if it fits, else fall back to small
        if _text_w(draw, text, FONT_ABBR) <= max_text_width:
            draw.text((px, top + (h - _text_h(draw, FONT_ABBR)) // 2), text, font=FONT_ABBR, fill=TEXT_COLOR)
        else:
            draw.text((px, top + (h - _text_h(draw, FONT_SMALL)) // 2), text, font=FONT_SMALL, fill=TEXT_COLOR)

        # Score column
        if score is not None:
            sw = _text_w(draw, str(score), FONT_SCORE)
            sx = x1 + (col2_w - sw) // 2
            sy = top + (h - _text_h(draw, FONT_SCORE)) // 2
            draw.text((sx, sy), f"{score}", font=FONT_SCORE, fill=TEXT_COLOR)

    return table_bottom


def _game_state(game: Dict) -> str:
    return (game.get("status") or {}).get("state") or ""


def _status_text(game: Dict) -> str:
    # NBA: "Final", "Q4 9:12", "Halftime", "End Q1", etc. Pass-through from scheduler/feed.
    return (game.get("status") or {}).get("detail") or (game.get("status") or {}).get("short") or ""


def _score_from_team_entry(entry: Dict) -> Optional[int]:
    try:
        val = entry.get("score", None)
        if val is None:
            return None
        return int(val)
    except (TypeError, ValueError):
        return None


def _team_tricode(entry: Dict) -> str:
    tri = (entry or {}).get("tri") or ""
    return tri.strip()


def _official_date(game: Dict) -> Optional[dt.date]:
    try:
        d = (game.get("date") or "").split("T")[0]
        return dt.datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        pass
    try:
        d2 = (game.get("officialDate") or "").split("T")[0]
        return dt.datetime.strptime(d2, "%Y-%m-%d").date()
    except Exception:
        return None


def _get_local_start(game: Dict) -> Optional[dt.datetime]:
    # Either isoStart or scheduled local time already in CENTRAL_TIME, per project norms
    iso = (game.get("dateTime") or game.get("startTime") or game.get("gameDate") or "")
    if not iso:
        return None
    try:
        # Expecting something like "2025-11-03T19:00:00-06:00" or Z
        # We'll parse minimal safely:
        t = iso.replace("Z", "+00:00")
        dt_obj = dt.datetime.fromisoformat(t)
        # Normalize to CENTRAL_TIME if tz-aware:
        if dt_obj.tzinfo:
            return dt_obj.astimezone(CENTRAL_TIME)
        return dt_obj.replace(tzinfo=CENTRAL_TIME)
    except Exception:
        return None


def _get_official_date(game: Dict) -> Optional[dt.date]:
    od = _official_date(game)
    if od:
        return od
    start = _get_local_start(game)
    return start.date() if isinstance(start, dt.datetime) else None


def _relative_label(date_obj: Optional[dt.date]) -> str:
    if not isinstance(date_obj, dt.date):
        return ""
    today = dt.datetime.now(CENTRAL_TIME).date()
    if date_obj == today:
        return "Today"
    if date_obj == today + dt.timedelta(days=1):
        return "Tomorrow"
    if date_obj == today - dt.timedelta(days=1):
        return "Yesterday"
    fmt = "%a %b %-d" if os.name != "nt" else "%a %b %#d"
    return date_obj.strftime(fmt)


def _format_time(start: Optional[dt.datetime]) -> str:
    if not isinstance(start, dt.datetime):
        return ""
    fmt = "%-I:%M %p" if os.name != "nt" else "%#I:%M %p"
    return start.strftime(fmt).replace(" 0", " ").lstrip("0")


def _team_entry(game: Dict, side: str) -> Dict[str, Optional[str]]:
    teams = game.get("teams") or {}
    entry = teams.get(side) or {}
    tri = (entry.get("tri") or "").upper()
    full = entry.get("name") or entry.get("teamName") or entry.get("fullName") or tri
    score = _score_from_team_entry(entry)
    # label shows tricode by default; if bulls, bold highlight row
    label = tri
    return {"tri": tri, "name": full, "score": score, "label": label}


def _is_bulls_side(entry: Dict) -> bool:
    return ((entry or {}).get("tri") or "").upper() == BULLS_TRICODE


def _format_matchup_line(game: Dict) -> str:
    away = _team_entry(game, "away")
    home = _team_entry(game, "home")
    away_full = away.get("name") or away.get("tri") or ""
    home_full = home.get("name") or home.get("tri") or ""
    pre = "vs." if _is_bulls_side(home) else "@"
    opp = away_full if _is_bulls_side(home) else home_full
    return f"{pre} {opp}".strip()


def _format_footer_last(game: Dict) -> str:
    # Hawks style: relative date or weekday+month+day (no year)
    d = _get_official_date(game)
    if callable(_MLB_REL_DATE_ONLY):
        try:
            txt = _MLB_REL_DATE_ONLY(d)
            if txt:
                return txt
        except Exception:
            pass
    return _relative_label(d)


def _format_footer_next(game: Dict) -> str:
    start = _get_local_start(game)
    date = _get_official_date(game)
    parts = []
    if date:
        parts.append(_relative_label(date))
    if start:
        parts.append(_format_time(start))
    return " • ".join([p for p in parts if p]) or ""


def _render_message(title: str, message: str) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)

    y = 2
    y += _draw_title_line(img, draw, y, title, FONT_TITLE)
    y += 6
    y += _center_wrapped_text(draw, y, message, FONT_NEXT_OPP, max_width=WIDTH - 12)
    return img


def _render_scoreboard(game: Dict, *, title: str, footer: str, status_line: str) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)

    y = 2
    y += _draw_title_line(img, draw, y, title, FONT_TITLE)
    y += 2

    away = _team_entry(game, "away")
    home = _team_entry(game, "home")

    bottom_parts = [part.strip() for part in (status_line, footer) if part and part.strip()]
    bottom_line = " • ".join([p for p in bottom_parts if p])
    bottom_reserved = _text_h(draw, FONT_BOTTOM) + 2 if bottom_line else 0

    # Rows with highlight if the row is Bulls
    rows = (
        {"tri": away.get("tri"), "label": away.get("label"), "score": away.get("score"), "highlight": _is_bulls_side(away)},
        {"tri": home.get("tri"), "label": home.get("label"), "score": home.get("score"), "highlight": _is_bulls_side(home)},
    )
    table_bottom = _draw_scoreboard_table(img, draw, y, rows, score_label="PTS", bottom_reserved_px=bottom_reserved)

    # Footer/status line centered at bottom
    if bottom_line:
        by = HEIGHT - _text_h(draw, FONT_BOTTOM) - 1
        _center_text(draw, by, bottom_line, FONT_BOTTOM, fill=TEXT_COLOR)

    return img


def _render_next_game(game: Dict, *, title: str) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)

    y = 2
    y += _draw_title_line(img, draw, y, title, FONT_TITLE)
    y += 2

    matchup = _format_matchup_line(game)
    if matchup:
        y += _center_wrapped_text(draw, y, matchup, FONT_NEXT_OPP, max_width=WIDTH - 8) + 2

    away = _team_entry(game, "away")
    home = _team_entry(game, "home")
    away_tri = away.get("tri")
    home_tri = home.get("tri")

    footer = _format_footer_next(game)
    footer_height = _text_h(draw, FONT_BOTTOM) if footer else 0
    footer_top = HEIGHT - (footer_height + 2) if footer else HEIGHT

    desired_logo_h = standard_next_game_logo_height(HEIGHT)
    available_h = max(10, footer_top - (y + 2))
    logo_h = min(desired_logo_h, available_h)
    centered_top = (HEIGHT - logo_h) // 2
    row_y = max(y + 1, min(centered_top, footer_top - logo_h - 1))

    away_logo = _load_logo_cached(away_tri, logo_h)
    home_logo = _load_logo_cached(home_tri, logo_h)

    # Horizontal positions: center logos with even gap
    gap = 10
    aw = away_logo.width if away_logo else 0
    hw = home_logo.width if home_logo else 0
    total_w = aw + hw + gap
    start_x = (WIDTH - total_w) // 2

    if away_logo:
        img.paste(away_logo, (start_x, row_y + (logo_h - away_logo.height) // 2), away_logo)
    if home_logo:
        img.paste(home_logo, (start_x + aw + gap, row_y + (logo_h - home_logo.height) // 2), home_logo)

    # Footer
    if footer:
        by = HEIGHT - _text_h(draw, FONT_BOTTOM) - 1
        _center_text(draw, by, footer, FONT_BOTTOM)

    return img


def _live_status(game: Dict) -> str:
    # Expect scheduler to supply something like "Q3 5:42" / "Halftime". Fallback to "Live".
    return _status_text(game) or "Live"


def _push(display, img: Image.Image, transition: bool = False):
    """Unified image push consistent with the project utils."""
    if isinstance(display, ScreenImage):
        display.set(img)
        return None

    def _show_image():
        try:
            clear_display(display)
            if hasattr(display, "display") and callable(display.display):
                display.display(img)
            elif hasattr(display, "image") and callable(display.image):
                display.image(img)
            elif hasattr(display, "set") and callable(display.set):
                display.set(img)
            else:
                # Fallback: try PIL Image to display-like object
                if hasattr(display, "set_image"):
                    display.set_image(img)
                elif hasattr(display, "display"):
                    display.display(img)
        except Exception as exc:
            logging.exception("Failed to push Bulls screen: %s", exc)

    if LED_INDICATOR_LEVEL and LED_INDICATOR_LEVEL > 0:
        # Blink team color for Bulls W/L if applicable is handled by caller when desired.
        _show_image()
    else:
        _show_image()
    return None


def draw_last_bulls_game(display, game: Optional[Dict], transition: bool = False):
    if not game:
        logging.warning("bulls last: no data")
        img = _render_message("Last Bulls game:", "No results available")
        return _push(display, img, transition=transition)

    footer = _format_footer_last(game)
    status_line = _status_text(game) or "Final"
    img = _render_scoreboard(game, title="Last Bulls game:", footer=footer, status_line=status_line)

    away_entry = _team_entry(game, "away")
    home_entry = _team_entry(game, "home")
    led_override: Optional[Tuple[float, float, float]] = None

    bulls_entry = None
    opponent_entry = None
    if _is_bulls_side(away_entry):
        bulls_entry, opponent_entry = away_entry, home_entry
    elif _is_bulls_side(home_entry):
        bulls_entry, opponent_entry = home_entry, away_entry

    # Optional LED accent similar to Hawks file behavior
    if bulls_entry and (bulls_entry.get("score") is not None) and (opponent_entry and opponent_entry.get("score") is not None):
        try:
            b = int(bulls_entry["score"])
            o = int(opponent_entry["score"])
            if b > o:
                led_override = (0.0, 1.0, 0.0)  # green-ish for win
            elif b < o:
                led_override = (1.0, 0.0, 0.0)  # red for loss
        except Exception:
            pass

    if led_override is not None:
        with temporary_display_led(*led_override):
            return _push(display, img, transition=transition)

    return _push(display, img, transition=transition)


def draw_live_bulls_game(display, game: Optional[Dict], transition: bool = False):
    if not game:
        logging.info("bulls live: no live game")
        img = _render_message("Bulls Live:", "Not in progress")
        return _push(display, img, transition=transition)

    if _game_state(game) != "live":
        logging.info("bulls live: game not live (state=%s)", _game_state(game))
        img = _render_message("Bulls Live:", "Not in progress")
        return _push(display, img, transition=transition)

    footer = _relative_label(_get_official_date(game))
    img = _render_scoreboard(game, title="Bulls Live:", footer=footer, status_line=_live_status(game))
    return _push(display, img, transition=transition)


def draw_sports_screen_bulls(display, game: Optional[Dict], transition: bool = False):
    if not game:
        logging.info("bulls next: no upcoming game")
        img = _render_message("Next Bulls game:", "No upcoming games scheduled")
        return _push(display, img, transition=transition)

    img = _render_next_game(game, title="Next Bulls game:")
    return _push(display, img, transition=transition)


def draw_bulls_next_home_game(display, game: Optional[Dict], transition: bool = False):
    if not game:
        logging.info("bulls next home: no upcoming home game")
        img = _render_message("Next at home...", "No United Center games scheduled")
        return _push(display, img, transition=transition)

    img = _render_next_game(game, title="Next at home...")
    return _push(display, img, transition=transition)
