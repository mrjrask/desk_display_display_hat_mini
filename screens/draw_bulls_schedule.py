#!/usr/bin/env python3
"""
draw_bulls_schedule.py

Bulls screens styled to match the Blackhawks cards:
- Last Bulls game: compact 2-row scoreboard (logo+abbr | PTS) with title strip and relative-date footer.
- Bulls Live: same scoreboard with live status line.
- Next Bulls game / Next at home: centered matchup + two big logos, footer with relative date + local time.

No changes to draw_hawks_schedule.py.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

# Import only symbols that exist in repo config
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

def _ts(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(TS_PATH, size)
    except Exception:
        logging.warning("TimesSquare font missing at %s; using fallback.", TS_PATH)
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except Exception:
            return ImageFont.load_default()

# Local sizes (tuned for 320x240; scales okay for larger canvases in this project)
FONT_ABBR   = _ts(33 if HEIGHT >= 240 else 28)  # team abbr in table
FONT_SCORE  = _ts(48 if HEIGHT >= 240 else 38)  # score digits
FONT_SMALL  = _ts(22 if HEIGHT >= 240 else 18)  # "PTS" header / status

# Shared sports fonts from config (keeps Hawks look)
FONT_TITLE    = FONT_TITLE_SPORTS                # title strip
FONT_BOTTOM   = FONT_DATE_SPORTS                 # footer (date/time)
FONT_NEXT_OPP = FONT_TEAM_SPORTS                 # opponent line in "next" cards

# Colors
BACKGROUND_COLOR = (0, 0, 0)
TEXT_COLOR       = (255, 255, 255)
HIGHLIGHT_COLOR  = (55, 14, 18)  # dark maroon accent for Bulls row

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
    w, _, _, _ = _measure(draw, text, font)
    return w

def _text_h(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    _, h, _, _ = _measure(draw, "Hg", font)
    return h

def _center_text(draw: ImageDraw.ImageDraw, y: int, text: str, font: ImageFont.ImageFont, *, fill=TEXT_COLOR) -> int:
    x = (WIDTH - _text_w(draw, text, font)) // 2
    draw.text((x, y), text, font=font, fill=fill)
    return _text_h(draw, font)

def _center_wrapped_text(draw, y, text, font, *, max_width: int, line_gap: int = 2, fill=TEXT_COLOR) -> int:
    words = (text or "").split()
    if not words:
        return 0
    lines, cur = [], []
    for w in words:
        cand = " ".join(cur + [w])
        if _text_w(draw, cand, font) <= max_width or not cur:
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

# ─────────────────────────────────────────────────────────────────────────────
# Logos

def _load_logo_png(abbr: str, height: int) -> Optional[Image.Image]:
    abbr = (abbr or "NBA").upper()
    path = os.path.join(NBA_DIR, f"{abbr}.png")
    try:
        if os.path.exists(path):
            img = Image.open(path).convert("RGBA")
            w0, h0 = img.size
            r = height / float(h0) if h0 else 1.0
            return img.resize((max(1, int(w0 * r)), height), Image.LANCZOS)
    except Exception:
        pass
    # fallback
    try:
        generic = os.path.join(NBA_DIR, "NBA.png")
        if os.path.exists(generic):
            img = Image.open(generic).convert("RGBA")
            w0, h0 = img.size
            r = height / float(h0) if h0 else 1.0
            return img.resize((max(1, int(w0 * r)), height), Image.LANCZOS)
    except Exception:
        pass
    return None

# ─────────────────────────────────────────────────────────────────────────────
# Game dict helpers (feed-compatible with your scheduler)

def _game_state(game: Dict) -> str:
    return (game.get("status") or {}).get("state") or ""

def _status_text(game: Dict) -> str:
    # Examples: "Final", "Q4 9:12", "Halftime", "End Q1"
    status = (game.get("status") or {})
    return status.get("detail") or status.get("short") or status.get("state") or ""

def _score_from_team_entry(entry: Dict) -> Optional[int]:
    try:
        val = entry.get("score", None)
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _extract_first(entry: Optional[Dict], candidates: Tuple[str, ...]) -> str:
    if not isinstance(entry, dict):
        return ""
    for key in candidates:
        value = entry.get(key)
        if isinstance(value, str):
            value = value.strip()
        if value:
            return str(value)
    return ""


def _team_entry(game: Dict, side: str) -> Dict[str, Optional[str]]:
    teams = game.get("teams") or {}
    entry = teams.get(side) or {}
    team_info = entry.get("team") if isinstance(entry.get("team"), dict) else None

    tri_candidates = (
        "tri",
        "triCode",
        "tricode",
        "teamTricode",
        "teamTriCode",
        "abbreviation",
        "abbr",
        "teamAbbreviation",
        "teamAbbrev",
    )
    name_candidates = (
        "name",
        "teamName",
        "fullName",
        "displayName",
        "shortName",
        "nickname",
    )
    label_candidates = (
        "label",
        "shortName",
        "abbr",
        "displayName",
        "nickname",
    )

    tri = _extract_first(entry, tri_candidates)
    if not tri and team_info:
        tri = _extract_first(team_info, tri_candidates)
    tri = (tri or "").upper()

    full = _extract_first(entry, name_candidates)
    if not full and team_info:
        full = _extract_first(team_info, name_candidates)
    if not full:
        full = tri

    label = _extract_first(entry, label_candidates)
    if not label and team_info:
        label = _extract_first(team_info, label_candidates)
    label = (label or tri or full or "").strip()

    score = _score_from_team_entry(entry)
    return {"tri": tri, "name": full or None, "score": score, "label": label or tri}

def _is_bulls_side(entry: Dict) -> bool:
    return ((entry or {}).get("tri") or "").upper() == TEAM_TRICODE

def _official_date_from_str(s: str) -> Optional[dt.date]:
    try:
        return dt.datetime.strptime(s.split("T")[0], "%Y-%m-%d").date()
    except Exception:
        return None

def _official_date(game: Dict) -> Optional[dt.date]:
    if game.get("date"):
        d = _official_date_from_str(game["date"])
        if d:
            return d
    if game.get("officialDate"):
        d = _official_date_from_str(game["officialDate"])
        if d:
            return d
    start = _get_local_start(game)
    return start.date() if isinstance(start, dt.datetime) else None

def _get_local_start(game: Dict) -> Optional[dt.datetime]:
    iso = (game.get("dateTime") or game.get("startTime") or game.get("gameDate") or "")
    if not iso:
        return None
    try:
        t = iso.replace("Z", "+00:00")
        dt_obj = dt.datetime.fromisoformat(t)
        if dt_obj.tzinfo:
            return dt_obj.astimezone(CENTRAL_TIME)
        return dt_obj.replace(tzinfo=CENTRAL_TIME)
    except Exception:
        return None

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

def _format_footer_last(game: Dict) -> str:
    d = _official_date(game)
    return _relative_label(d)

def _format_footer_next(game: Dict) -> str:
    start = _get_local_start(game)
    date  = _official_date(game)
    parts = []
    if date:  parts.append(_relative_label(date))
    if start: parts.append(_format_time(start))
    return " • ".join([p for p in parts if p]) or ""

def _format_matchup_line(game: Dict) -> str:
    away = _team_entry(game, "away")
    home = _team_entry(game, "home")
    pre  = "vs." if _is_bulls_side(home) else "@"
    opp  = (away.get("name") if _is_bulls_side(home) else home.get("name")) or ""
    return f"{pre} {opp}".strip()

# ─────────────────────────────────────────────────────────────────────────────
# Drawing

def _draw_title_line(draw: ImageDraw.ImageDraw, y: int, text: str) -> int:
    # Simple centered title line (keeps us independent of MLB helpers)
    return _center_text(draw, y, text, FONT_TITLE)

def _draw_scoreboard_table(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    top_y: int,
    rows: Tuple[Dict[str, object], ...],
    *,
    score_label: Optional[str] = "PTS",
    bottom_reserved_px: int = 0,
) -> int:
    """2-row compact table: team cell at left, score column at right, header label above score col."""
    if not rows:
        return top_y

    row_count = len(rows)
    col1_w = min(WIDTH - 24, max(84, int(WIDTH * 0.72)))
    col2_w = max(20, WIDTH - col1_w)
    x0, x1, x2 = 0, col1_w, WIDTH

    header_h = _text_h(draw, FONT_SMALL) + 4 if score_label else 0
    table_top = top_y

    total_available = max(0, HEIGHT - bottom_reserved_px - table_top)
    available_for_rows = max(0, total_available - header_h)
    row_h = max(available_for_rows // max(1, row_count), 32)
    row_h = min(row_h, 48)
    if row_h * row_count > available_for_rows and available_for_rows > 0:
        row_h = max(24, available_for_rows // max(1, row_count))
    if row_h <= 0:
        row_h = 32

    # Header label (e.g., "PTS") above score column
    if score_label:
        header_y = table_top + max(0, (header_h - _text_h(draw, FONT_SMALL)) // 2)
        label_w  = _text_w(draw, score_label, FONT_SMALL)
        label_x  = x1 + (col2_w - label_w) // 2
        draw.text((label_x, header_y), score_label, font=FONT_SMALL, fill=TEXT_COLOR)

    # Draw rows
    y = table_top + header_h
    for row in rows:
        top = y
        h = row_h
        tri = (row.get("tri") or "").upper()
        label = (row.get("label") or tri or "").strip() or tri
        score = row.get("score")
        highlight = bool(row.get("highlight"))

        # Team cell bg highlight for Bulls row
        if highlight:
            draw.rectangle([0, top, x1 - 1, top + h - 1], fill=HIGHLIGHT_COLOR)

        # Logo
        base_h = max(1, h - 6)
        logo_h = min(64, max(24, base_h))
        logo   = _load_logo_png(tri, logo_h)
        px = 6
        if logo:
            ly = top + (h - logo.height) // 2
            img.paste(logo, (px, ly), logo)
            px += logo.width + 6

        # Team label (prefer ABR font if fits; else small)
        max_text_w = max(1, x1 - 6 - px)
        use_font = FONT_ABBR if _text_w(draw, label, FONT_ABBR) <= max_text_w else FONT_SMALL
        draw.text((px, top + (h - _text_h(draw, use_font)) // 2), label, font=use_font, fill=TEXT_COLOR)

        # Score column
        if score is not None:
            s = str(score)
            sw = _text_w(draw, s, FONT_SCORE)
            sx = x1 + (col2_w - sw) // 2
            sy = top + (h - _text_h(draw, FONT_SCORE)) // 2
            draw.text((sx, sy), s, font=FONT_SCORE, fill=TEXT_COLOR)

        y += h

    return y

def _render_message(title: str, message: str) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)
    y = 2
    y += _draw_title_line(draw, y, title)
    y += 6
    _center_wrapped_text(draw, y, message, FONT_NEXT_OPP, max_width=WIDTH - 12)
    return img

def _render_scoreboard(game: Dict, *, title: str, footer: str, status_line: str) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)

    y = 2
    y += _draw_title_line(draw, y, title)
    y += 2

    away = _team_entry(game, "away")
    home = _team_entry(game, "home")

    bottom_parts = [p.strip() for p in (status_line, footer) if p and p.strip()]
    bottom_line = " • ".join(bottom_parts)
    bottom_reserved = _text_h(draw, FONT_BOTTOM) + 2 if bottom_line else 0

    rows = (
        {"tri": away["tri"], "label": away["label"], "score": away["score"], "highlight": _is_bulls_side(away)},
        {"tri": home["tri"], "label": home["label"], "score": home["score"], "highlight": _is_bulls_side(home)},
    )
    _draw_scoreboard_table(img, draw, y, rows, score_label="PTS", bottom_reserved_px=bottom_reserved)

    if bottom_line:
        by = HEIGHT - _text_h(draw, FONT_BOTTOM) - 1
        _center_text(draw, by, bottom_line, FONT_BOTTOM, fill=TEXT_COLOR)

    return img

def _render_next_game(game: Dict, *, title: str) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)

    y = 2
    y += _draw_title_line(draw, y, title)
    y += 2

    matchup = _format_matchup_line(game)
    if matchup:
        y += _center_wrapped_text(draw, y, matchup, FONT_NEXT_OPP, max_width=WIDTH - 8) + 2

    away = _team_entry(game, "away")
    home = _team_entry(game, "home")

    footer = _format_footer_next(game)
    footer_h = _text_h(draw, FONT_BOTTOM) if footer else 0
    footer_top = HEIGHT - (footer_h + 2) if footer else HEIGHT

    desired_logo_h = standard_next_game_logo_height(HEIGHT)
    available_h = max(10, footer_top - (y + 2))
    logo_h = min(desired_logo_h, available_h)
    row_y = max(y + 1, min((HEIGHT - logo_h) // 2, footer_top - logo_h - 1))

    away_logo = _load_logo_png(away["tri"], logo_h)
    home_logo = _load_logo_png(home["tri"], logo_h)
    aw = away_logo.width if away_logo else 0
    hw = home_logo.width if home_logo else 0

    gap = 10
    total_w = aw + hw + gap
    start_x = (WIDTH - total_w) // 2

    if away_logo:
        img.paste(away_logo, (start_x, row_y + (logo_h - away_logo.height) // 2), away_logo)
    if home_logo:
        img.paste(home_logo, (start_x + aw + gap, row_y + (logo_h - home_logo.height) // 2), home_logo)

    if footer:
        by = HEIGHT - _text_h(draw, FONT_BOTTOM) - 1
        _center_text(draw, by, footer, FONT_BOTTOM, fill=TEXT_COLOR)

    return img

# ─────────────────────────────────────────────────────────────────────────────
# Display push

def _push(display, img: Optional[Image.Image], *, transition: bool = False, led_override: Optional[Tuple[float, float, float]] = None):
    if img is None or display is None:
        return None
    if transition:
        return ScreenImage(img, displayed=False, led_override=led_override)

    def _show_image() -> None:
        try:
            clear_display(display)
            if hasattr(display, "image"):
                display.image(img)
            elif hasattr(display, "ShowImage"):
                buf = display.getbuffer(img) if hasattr(display, "getbuffer") else img
                display.ShowImage(buf)
            elif hasattr(display, "display"):
                display.display(img)
        except Exception as e:
            logging.exception("Failed to push Bulls screen: %s", e)

    _show_image()
    return None

# ─────────────────────────────────────────────────────────────────────────────
# Public entry points (used by screens/registry.py)

def draw_last_bulls_game(display, game: Optional[Dict], transition: bool = False):
    if not game:
        logging.warning("bulls last: no data")
        img = _render_message("Last Bulls game:", "No results available")
        return _push(display, img, transition=transition)

    footer = _format_footer_last(game)
    status_line = _status_text(game) or "Final"
    img = _render_scoreboard(game, title="Last Bulls game:", footer=footer, status_line=status_line)

    # Optional LED accent like Hawks: green on win, red on loss
    away = _team_entry(game, "away")
    home = _team_entry(game, "home")
    bulls = away if _is_bulls_side(away) else (home if _is_bulls_side(home) else None)
    opp   = home if bulls is away else away

    led_override = None
    if bulls and opp and bulls.get("score") is not None and opp.get("score") is not None:
        try:
            b, o = int(bulls["score"]), int(opp["score"])
            if b > o: led_override = (0.0, 1.0, 0.0)
            elif b < o: led_override = (1.0, 0.0, 0.0)
        except Exception:
            pass

    if led_override is not None and LED_INDICATOR_LEVEL and LED_INDICATOR_LEVEL > 0:
        with temporary_display_led(*led_override):
            return _push(display, img, transition=transition)
    return _push(display, img, transition=transition)

def draw_live_bulls_game(display, game: Optional[Dict], transition: bool = False):
    if not game or _game_state(game) != "live":
        img = _render_message("Bulls Live:", "Not in progress")
        return _push(display, img, transition=transition)

    footer = _relative_label(_official_date(game))
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
