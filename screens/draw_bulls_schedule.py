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
    FONT_DATE_SPORTS,
    FONT_TEAM_SPORTS,
    FONT_TITLE_SPORTS,
    NBA_IMAGES_DIR,
    NBA_TEAM_ID,
    NBA_TEAM_TRICODE,
    TIMES_SQUARE_FONT_PATH,
    WIDTH,
    HEIGHT,
    CENTRAL_TIME,
)

from utils import clear_display, load_team_logo, standard_next_game_logo_height

TS_PATH = TIMES_SQUARE_FONT_PATH
NBA_DIR = NBA_IMAGES_DIR
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



def _ts(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(TS_PATH, size)
    except Exception:
        logging.warning("TimesSquare font missing at %s; using default.", TS_PATH)
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except Exception:
            return ImageFont.load_default()


FONT_ABBR = _ts(33 if HEIGHT > 64 else 30)
FONT_SCORE = _ts(48 if HEIGHT > 64 else 37)
FONT_SMALL = _ts(22 if HEIGHT > 64 else 19)

FONT_TITLE = FONT_TITLE_SPORTS
FONT_BOTTOM = FONT_DATE_SPORTS
FONT_NEXT_OPP = FONT_TEAM_SPORTS

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
    width, _, _, _ = _measure(draw, text, font)
    return width


def _text_h(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    _, height, _, _ = _measure(draw, "Hg", font)
    return height


def _center_text(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.ImageFont,
    *,
    fill=TEXT_COLOR,
) -> int:
    if not text:
        return 0
    width, height, left, top = _measure(draw, text, font)
    x = (WIDTH - width) // 2 - left
    draw.text((x, y - top), text, font=font, fill=fill)
    return height


def _center_wrapped_text(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.ImageFont,
    *,
    max_width: Optional[int] = None,
    line_spacing: int = 1,
    fill=TEXT_COLOR,
) -> int:
    if not text:
        return 0

    max_width = min(max_width or WIDTH, WIDTH)
    text_height = _text_h(draw, font)

    if _text_w(draw, text, font) <= max_width:
        _center_text(draw, y, text, font, fill=fill)
        return text_height

    words = text.split()
    if not words:
        return 0

    lines: list[str] = []
    current = words[0]

    for word in words[1:]:
        candidate = f"{current} {word}" if current else word
        if _text_w(draw, candidate, font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    fixed_lines: list[str] = []
    for line in lines:
        if _text_w(draw, line, font) <= max_width:
            fixed_lines.append(line)
            continue

        chunk = ""
        for char in line:
            candidate = f"{chunk}{char}"
            if chunk and _text_w(draw, candidate, font) > max_width:
                fixed_lines.append(chunk)
                chunk = char
            else:
                chunk = candidate
        if chunk:
            fixed_lines.append(chunk)

    lines = fixed_lines or lines

    total_height = 0
    for idx, line in enumerate(lines):
        line_y = y + idx * (text_height + line_spacing)
        _center_text(draw, line_y, line, font, fill=fill)
        total_height = (idx + 1) * text_height + idx * line_spacing

    return total_height


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


def _team_scoreboard_label(entry: Dict[str, Optional[str]]) -> str:
    name = (entry.get("name") or "").strip()
    if name:
        pieces = [piece for piece in name.replace("-", " ").split() if piece]
        if len(pieces) >= 2:
            return pieces[-1]
        return name
    tri = entry.get("tri") or ""
    return tri.strip()


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

    table_height = header_h + (row_h * row_count)
    if total_available:
        table_height = min(table_height, total_available)
    if table_height < (header_h + 2):
        table_height = header_h + 2
    table_bottom = min(table_top + table_height, HEIGHT - bottom_reserved_px)
    table_height = max(header_h + 2, table_bottom - table_top)
    table_bottom = table_top + table_height

    header_bottom = table_top + header_h
    row_area_height = max(2, table_height - header_h)

    # Determine row slices ensuring we use the whole available space.
    row_slices: list[Tuple[int, int]] = []
    next_top = header_bottom
    remaining = row_area_height
    remaining_rows = row_count
    for _ in rows:
        if remaining_rows <= 0:
            break
        height = max(1, remaining // remaining_rows)
        row_slices.append((next_top, height))
        next_top += height
        remaining -= height
        remaining_rows -= 1
    if row_slices:
        last_top, last_height = row_slices[-1]
        row_slices[-1] = (last_top, table_bottom - last_top)

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

    def _fits(font: ImageFont.ImageFont) -> bool:
        for spec in specs:
            if spec["max_width"] <= 0 or not spec["text"]:
                continue
            if _text_w(draw, spec["text"], font) > spec["max_width"]:
                return False
        return True

    name_font = FONT_ABBR
    if not _fits(name_font):
        size = getattr(FONT_ABBR, "size", None) or (33 if HEIGHT > 64 else 30)
        min_size = max(10, int(round(size * 0.6)))
        chosen = None
        for candidate_size in range(size - 1, min_size - 1, -1):
            candidate_font = _ts(candidate_size)
            if _fits(candidate_font):
                chosen = candidate_font
                break
        name_font = chosen or _ts(min_size)

    for spec in specs:
        row_top = spec["top"]
        row_height = spec["height"]
        cy = row_top + row_height // 2
        highlight = spec["highlight"]

        if highlight:
            draw.rectangle((x0 + 2, row_top + 1, x2 - 2, row_top + row_height - 1), fill=HIGHLIGHT_COLOR)

        logo = spec["logo"]
        text_left = x0 + 6
        if logo:
            lw, lh = logo.size
            ly = cy - lh // 2
            try:
                img.paste(logo, (text_left, ly), logo)
            except Exception:
                pass
            text_left += lw + 6

        text = spec["text"]
        max_width = spec["max_width"]
        if text and _text_w(draw, text, name_font) > max_width:
            ellipsis = "…"
            trimmed = text
            while trimmed and _text_w(draw, trimmed + ellipsis, name_font) > max_width:
                trimmed = trimmed[:-1]
            text = trimmed + ellipsis if trimmed else ellipsis

        if text:
            text_w = _text_w(draw, text, name_font)
            text_h = _text_h(draw, name_font)
            text_left = min(text_left, x1 - text_w - 4)
            text_left = max(text_left, x0 + 4)
            _, _, t_left, t_top = _measure(draw, text, name_font)
            tx = text_left - t_left
            ty = cy - text_h // 2 - t_top
            draw.text((tx, ty), text, font=name_font, fill=TEXT_COLOR)

        score_val = spec["score"]
        score_txt = "-" if score_val is None else str(score_val)
        score_w, score_h, s_left, s_top = _measure(draw, score_txt, FONT_SCORE)
        sx = x1 + (col2_w - score_w) // 2 - s_left
        sy = cy - score_h // 2 - s_top
        score_color = BULLS_RED if highlight else TEXT_COLOR
        draw.text((sx, sy), score_txt, font=FONT_SCORE, fill=score_color)

    return table_bottom


def _parse_datetime(value: str) -> Optional[dt.datetime]:
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
    start = game.get("_start_local")
    if isinstance(start, dt.datetime):
        return start.astimezone(CENTRAL_TIME) if start.tzinfo else CENTRAL_TIME.localize(start)
    return _parse_datetime(game.get("gameDate"))


def _get_official_date(game: Dict) -> Optional[dt.date]:
    official = game.get("officialDate")
    if isinstance(official, str) and official:
        try:
            return dt.date.fromisoformat(official[:10])
        except ValueError:
            pass
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
    team_info = entry.get("team") if isinstance(entry.get("team"), dict) else {}
    tri = (team_info.get("triCode") or team_info.get("abbreviation") or "").upper()
    name = team_info.get("name") or ""
    team_id = str(team_info.get("id") or "")
    score_raw = entry.get("score")
    try:
        score = int(score_raw)
    except (TypeError, ValueError):
        score = None
    return {
        "tri": tri,
        "name": name,
        "id": team_id,
        "score": score,
    }


def _is_bulls_side(entry: Dict[str, Optional[str]]) -> bool:
    return (entry.get("id") and entry["id"] == BULLS_TEAM_ID) or (entry.get("tri") and entry["tri"].upper() == BULLS_TRICODE)


def _game_state(game: Dict) -> str:
    status = game.get("status") or {}
    abstract = str(status.get("abstractGameState") or "").lower()
    if abstract:
        return abstract
    detailed = str(status.get("detailedState") or "").lower()
    if "final" in detailed:
        return "final"
    if "live" in detailed or "progress" in detailed:
        return "live"
    if "preview" in detailed or "schedule" in detailed or "pregame" in detailed:
        return "preview"
    code = str(status.get("statusCode") or "")
    if code == "3":
        return "final"
    if code == "2":
        return "live"
    if code == "1":
        return "preview"
    return detailed


def _status_text(game: Dict) -> str:
    status = game.get("status") or {}
    return str(status.get("detailedState") or status.get("abstractGameState") or "").strip()


def _live_status(game: Dict) -> str:
    linescore = game.get("linescore") or {}
    clock = (linescore.get("currentPeriodTimeRemaining") or "").strip()
    period = (linescore.get("currentPeriodOrdinal") or "").strip()
    pieces = [piece for piece in (clock, period) if piece]
    if not pieces:
        return _status_text(game) or "Live"
    return " • ".join(pieces)


def _render_message(title: str, message: str) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)
    y = 2
    y += _draw_title_line(img, draw, y, title, FONT_TITLE)
    y += 4
    _center_text(draw, y, message, FONT_BOTTOM)
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
    bottom_text = " — ".join(bottom_parts)
    bottom_reserved = (_text_h(draw, FONT_BOTTOM) + 2) if bottom_text else 0

    rows = (
        {
            "tri": away.get("tri") or "AWY",
            "label": _team_scoreboard_label(away),
            "score": away.get("score"),
            "highlight": _is_bulls_side(away),
        },
        {
            "tri": home.get("tri") or "HME",
            "label": _team_scoreboard_label(home),
            "score": home.get("score"),
            "highlight": _is_bulls_side(home),
        },
    )

    _draw_scoreboard_table(img, draw, y, rows, score_label="PTS", bottom_reserved_px=bottom_reserved)

    if bottom_text:
        bottom_y = HEIGHT - _text_h(draw, FONT_BOTTOM) - 1
        _center_text(draw, bottom_y, bottom_text, FONT_BOTTOM)

    return img


def _format_footer_last(game: Dict) -> str:
    official = (game.get("officialDate") or "").strip()
    label = ""
    if callable(_MLB_REL_DATE_ONLY):
        try:
            label = _MLB_REL_DATE_ONLY(official)
        except Exception:
            label = ""
    if not label:
        label = _relative_label(_get_official_date(game))
    away = _team_entry(game, "away")
    home = _team_entry(game, "home")
    bulls_home = _is_bulls_side(home)
    opponent = away if bulls_home else home
    opponent_name = opponent.get("name") or opponent.get("tri") or ""
    if label and opponent_name:
        return f"{label} vs {opponent_name}" if bulls_home else f"{label} @ {opponent_name}"
    return label or opponent_name


def _format_footer_next(game: Dict) -> str:
    start = _get_local_start(game)
    official = (game.get("officialDate") or "").strip()
    if not official and isinstance(start, dt.datetime):
        official = start.date().isoformat()

    time_label = _format_time(start)
    if callable(_MLB_FORMAT_GAME_LABEL):
        try:
            return _MLB_FORMAT_GAME_LABEL(official, time_label)
        except Exception:
            pass

    if not isinstance(start, dt.datetime):
        if official:
            try:
                date_val = dt.date.fromisoformat(official[:10])
            except ValueError:
                return official
            return _relative_label(date_val)
        return ""

    today = dt.datetime.now(CENTRAL_TIME)
    if time_label:
        time_str = time_label
    else:
        time_fmt = "%-I:%M %p" if os.name != "nt" else "%#I:%M %p"
        time_str = start.strftime(time_fmt)
    game_date = start.date()

    if game_date == today.date():
        prefix = "Tonight" if start.hour >= 18 else "Today"
        return f"{prefix} {time_str}".strip()
    if game_date == today.date() + dt.timedelta(days=1):
        return f"Tomorrow {time_str}".strip()

    date_str = start.strftime("%a %b %-d") if os.name != "nt" else start.strftime("%a %b %#d")
    if time_str:
        return f"{date_str} {time_str}".strip()
    return date_str


def _format_matchup_line(game: Dict) -> str:
    away = _team_entry(game, "away")
    home = _team_entry(game, "home")
    bulls_home = _is_bulls_side(home)
    opponent = away if bulls_home else home
    prefix = "vs." if bulls_home else "@"
    return f"{prefix} {opponent.get('name') or opponent.get('tri') or ''}".strip()


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

    at_text = "@"
    at_w = _text_w(draw, at_text, FONT_NEXT_OPP)
    at_h = _text_h(draw, FONT_NEXT_OPP)
    at_x = (WIDTH - at_w) // 2
    at_y = row_y + (logo_h - at_h) // 2
    draw.text((at_x, at_y), at_text, font=FONT_NEXT_OPP, fill=TEXT_COLOR)

    if away_logo:
        aw, ah = away_logo.size
        ax = max(2, at_x - 6 - aw)
        ay = row_y + (logo_h - ah) // 2
        img.paste(away_logo, (ax, ay), away_logo)
    else:
        fallback = (away_tri or "AWY")
        tx = (at_x - 6) // 2 - _text_w(draw, fallback, FONT_NEXT_OPP) // 2
        tx = max(2, tx)
        ty = row_y + (logo_h - at_h) // 2
        draw.text((tx, ty), fallback, font=FONT_NEXT_OPP, fill=TEXT_COLOR)

    if home_logo:
        hw, hh = home_logo.size
        hx = min(WIDTH - hw - 2, at_x + at_w + 6)
        hy = row_y + (logo_h - hh) // 2
        img.paste(home_logo, (hx, hy), home_logo)
    else:
        fallback = (home_tri or "HME")
        tx = at_x + at_w + ((WIDTH - (at_x + at_w)) // 2) - _text_w(draw, fallback, FONT_NEXT_OPP) // 2
        tx = min(WIDTH - _text_w(draw, fallback, FONT_NEXT_OPP) - 2, max(at_x + at_w + 2, tx))
        ty = row_y + (logo_h - at_h) // 2
        draw.text((tx, ty), fallback, font=FONT_NEXT_OPP, fill=TEXT_COLOR)

    if footer:
        footer_y = HEIGHT - footer_height - 1
        _center_text(draw, footer_y, footer, FONT_BOTTOM)

    return img


def _push(display, img: Optional[Image.Image], *, transition: bool = False) -> Optional[Image.Image]:
    if img is None or display is None:
        return None
    if transition:
        return img
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
        logging.exception("Failed to push Bulls screen: %s", exc)
    return None


def draw_last_bulls_game(display, game: Optional[Dict], transition: bool = False):
    if not game:
        logging.warning("bulls last: no data")
        img = _render_message("Last Bulls game:", "No results available")
        return _push(display, img, transition=transition)

    footer = _format_footer_last(game)
    status_line = _status_text(game) or "Final"
    img = _render_scoreboard(game, title="Last Bulls game:", footer=footer, status_line=status_line)
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
        logging.warning("bulls next: no upcoming game")
        img = _render_message("Next Bulls game:", "No upcoming game found")
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
