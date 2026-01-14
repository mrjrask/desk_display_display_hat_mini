#!/usr/bin/env python3
"""
draw_bears_schedule.py

Shows the next Chicago Bears game with:
  - Title at y=0
  - Opponent wrapped in up to two lines, prefixed by '@' if the Bears are away,
    or 'vs.' if the Bears are home.
  - Between those and the bottom line, a row of logos: AWAY @ HOME, each logo
    auto-sized similarly to the Hawks schedule screen.
  - Bottom lines with week above date/time.
"""

import datetime
import os
from PIL import Image, ImageDraw
import config
from config import BEARS_BOTTOM_MARGIN, BEARS_SCHEDULE, NFL_TEAM_ABBREVIATIONS
from utils import (
    load_team_logo,
    next_game_from_schedule,
    standard_next_game_logo_frame_width,
    standard_next_game_logo_height_for_space,
    wrap_text,
)


def _text_size(draw, text, *, font):
    try:
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return (r - l, b - t)
    except Exception:
        return draw.textsize(text, font=font)


def _format_game_date(date_text: str) -> str:
    if not date_text:
        return ""
    date_text = str(date_text).strip()
    if not date_text:
        return ""
    for fmt in ("%a, %b %d %Y", "%a, %b %d, %Y", "%a, %b %d"):
        try:
            dt0 = datetime.datetime.strptime(date_text, fmt)
            return f"{dt0.month}/{dt0.day}"
        except Exception:
            continue
    return date_text


NFL_LOGO_DIR = os.path.join(config.IMAGES_DIR, "nfl")
def show_bears_next_game(display, transition=False):
    game = next_game_from_schedule(BEARS_SCHEDULE)
    title = "Next for Da Bears:"
    img   = Image.new("RGB", (config.WIDTH, config.HEIGHT), "black")
    draw  = ImageDraw.Draw(img)

    # Title
    tw, th = draw.textsize(title, font=config.FONT_TITLE_SPORTS)
    draw.text(((config.WIDTH - tw)//2, 0), title,
              font=config.FONT_TITLE_SPORTS, fill=(255,255,255))

    if game:
        opp = game["opponent"]
        ha  = game["home_away"].lower()
        prefix = "@" if ha == "away" else "vs."

        # Opponent text (up to 2 lines)
        lines  = wrap_text(f"{prefix} {opp}", config.FONT_TEAM_SPORTS, config.WIDTH)[:2]
        y_txt  = th + 4
        for ln in lines:
            w_ln, h_ln = draw.textsize(ln, font=config.FONT_TEAM_SPORTS)
            draw.text(((config.WIDTH - w_ln)//2, y_txt),
                      ln, font=config.FONT_TEAM_SPORTS, fill=(255,255,255))
            y_txt += h_ln + 2

        # Logos row: AWAY @ HOME
        bears_ab = "chi"
        opp_key = opp.split()[-1].lower()
        opp_ab = NFL_TEAM_ABBREVIATIONS.get(opp_key, opp_key[:3])
        week_label = str(game.get("week", "") or "")
        if opp.strip().upper() == "TBD":
            if "super bowl" in week_label.lower():
                opp_ab = "afc"
            else:
                opp_ab = "nfc"
        if opp_ab == "was":
            opp_ab = "wsh"
        if ha == "away":
            away_ab, home_ab = bears_ab, opp_ab
        else:
            away_ab, home_ab = opp_ab, bears_ab

        # Bottom lines text — week above date/time
        wk = (game.get("week") or "").strip()
        if not wk:
            game_no = str(game.get("game_no", "")).strip()
            wk = f"Game {game_no}" if game_no else ""
        date_txt = _format_game_date(game.get("date", ""))
        t_txt = game["time"].strip()
        date_time = " ".join(part for part in (date_txt, t_txt) if part).strip()
        bottom_lines = [line for line in (wk, date_time) if line]
        line_gap = 2
        if bottom_lines:
            heights = [
                _text_size(draw, line, font=config.FONT_DATE_SPORTS)[1]
                for line in bottom_lines
            ]
            bottom_h = sum(heights) + (line_gap * (len(bottom_lines) - 1))
        else:
            bottom_h = 0
        bottom_y = config.HEIGHT - bottom_h - BEARS_BOTTOM_MARGIN  # keep on-screen

        available_h = max(10, bottom_y - (y_txt + 2))
        logo_h = standard_next_game_logo_height_for_space(config.HEIGHT, available_h)

        logo_away = load_team_logo(NFL_LOGO_DIR, away_ab, height=logo_h)
        logo_home = load_team_logo(NFL_LOGO_DIR, home_ab, height=logo_h)

        gap = max(6, min(10, config.WIDTH // 30))
        frame_w = standard_next_game_logo_frame_width(logo_h, (logo_away, logo_home))
        at_symbol = "@"
        try:
            l, t, r, b = draw.textbbox((0, 0), at_symbol, font=config.FONT_TEAM_SPORTS)
            at_w, at_h, at_t = r - l, b - t, t
        except Exception:
            at_w, at_h = draw.textsize(at_symbol, font=config.FONT_TEAM_SPORTS)
            at_t = 0

        block_h = logo_h if (logo_away or logo_home) else at_h
        total_w = (frame_w * 2) + (gap * 2) + at_w

        if total_w > config.WIDTH:
            gap = max(4, int(round(gap * (config.WIDTH / max(total_w, 1)))))
            total_w = (frame_w * 2) + (gap * 2) + at_w

        if total_w > config.WIDTH:
            max_frame = max(1, (config.WIDTH - at_w - (gap * 2)) // 2)
            if max_frame < frame_w:
                scale = max_frame / frame_w if frame_w else 1.0
                logo_h = max(1, int(round(logo_h * scale)))
                logo_away = load_team_logo(NFL_LOGO_DIR, away_ab, height=logo_h)
                logo_home = load_team_logo(NFL_LOGO_DIR, home_ab, height=logo_h)
                frame_w = min(standard_next_game_logo_frame_width(logo_h, (logo_away, logo_home)), max_frame)

            def _fit_logo(logo):
                if logo and logo.width > frame_w:
                    ratio = frame_w / logo.width
                    new_h = max(1, int(round(logo.height * ratio)))
                    return logo.resize((frame_w, new_h), Image.ANTIALIAS)
                return logo

            logo_away = _fit_logo(logo_away)
            logo_home = _fit_logo(logo_home)
            block_h = max((logo.height for logo in (logo_away, logo_home) if logo), default=at_h if not (logo_away or logo_home) else logo_h)
            total_w = (frame_w * 2) + (gap * 2) + at_w

        x0 = max(0, (config.WIDTH - total_w) // 2)

        # Vertical center of logos/text block between opponent text and bottom label
        y_logo = y_txt + ((bottom_y - y_txt) - block_h)//2

        left_x = x0
        at_x = left_x + frame_w + gap
        right_x = at_x + at_w + gap

        def _paste_logo(logo, frame_x):
            if not logo:
                return
            lx = frame_x + (frame_w - logo.width)//2
            ly = y_logo + (logo_h - logo.height)//2
            img.paste(logo, (lx, ly), logo)

        _paste_logo(logo_away, left_x)
        at_y = y_logo + (block_h - at_h)//2 - at_t
        draw.text((at_x, at_y), at_symbol, font=config.FONT_TEAM_SPORTS, fill=(255,255,255))
        _paste_logo(logo_home, right_x)

        # Draw bottom text
        if bottom_lines:
            y_bottom_text = bottom_y
            for line in bottom_lines:
                w_line, h_line = _text_size(draw, line, font=config.FONT_DATE_SPORTS)
                draw.text(
                    ((config.WIDTH - w_line) // 2, y_bottom_text),
                    line,
                    font=config.FONT_DATE_SPORTS,
                    fill=(255, 255, 255),
                )
                y_bottom_text += h_line + line_gap

    if transition:
        return img

    display.image(img)
    display.show()
    return None
