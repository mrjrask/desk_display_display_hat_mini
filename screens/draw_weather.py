#!/usr/bin/env python3
"""
draw_weather.py

Two weather screens (basic + detailed) in RGB.

Screen 1:
  • Temp & description at top
  • 64×64 weather icon
  • Two-line Feels/Hi/Lo: labels on the line above values, each centered.

Screen 2:
  • Detailed info: Sunrise/Sunset, Wind, Gust, Humidity, Pressure, UV Index
  • Each label/value pair vertically centered within its row.
"""

import datetime
import logging
import math
import time
from io import BytesIO
from typing import Optional, Tuple

import requests
from PIL import Image, ImageDraw

from config import (
    WIDTH,
    HEIGHT,
    CENTRAL_TIME,
    OWM_API_KEY,
    FONT_TEMP,
    FONT_CONDITION,
    FONT_WEATHER_LABEL,
    FONT_WEATHER_DETAILS,
    FONT_WEATHER_DETAILS_BOLD,
    FONT_WEATHER_DETAILS_SMALL,
    FONT_WEATHER_DETAILS_TINY,
    FONT_WEATHER_DETAILS_SMALL_BOLD,
    FONT_EMOJI,
    FONT_EMOJI_SMALL,
    WEATHER_ICON_SIZE,
    WEATHER_DESC_GAP,
    HOURLY_FORECAST_HOURS,
    LATITUDE,
    LONGITUDE,
)
from utils import (
    LED_INDICATOR_LEVEL,
    ScreenImage,
    clear_display,
    fetch_weather_icon,
    log_call,
    temporary_display_led,
    timestamp_to_datetime,
    uv_index_color,
    wind_direction,
)

ALERT_SYMBOL = "⚠️"
ALERT_PRIORITY = {"warning": 3, "watch": 2, "hazard": 1}
ALERT_LED_COLORS = {
    "warning": (LED_INDICATOR_LEVEL, 0.0, 0.0),
    "watch": (LED_INDICATOR_LEVEL, LED_INDICATOR_LEVEL * 0.5, 0.0),
    "hazard": (LED_INDICATOR_LEVEL, LED_INDICATOR_LEVEL, 0.0),
}
ALERT_ICON_COLORS = {
    "warning": (255, 64, 64),
    "watch": (255, 165, 0),
    "hazard": (255, 215, 0),
}


def _pop_pct_from(entry):
    if not isinstance(entry, dict):
        return None
    pop_raw = entry.get("pop")
    if pop_raw is None:
        pop_raw = entry.get("probabilityOfPrecipitation")
    if pop_raw is None:
        return None
    try:
        pop_val = float(pop_raw)
    except Exception:
        return None
    if 0 <= pop_val <= 1:
        pop_val *= 100
    return int(round(pop_val))


def _normalise_alerts(weather: object) -> list:
    alerts = []
    if isinstance(weather, dict):
        raw_alerts = weather.get("alerts")
    else:
        raw_alerts = None

    if isinstance(raw_alerts, list):
        alerts = [alert for alert in raw_alerts if isinstance(alert, dict)]
    elif isinstance(raw_alerts, dict):
        inner = raw_alerts.get("alerts")
        if isinstance(inner, list):
            alerts = [alert for alert in inner if isinstance(alert, dict)]
        else:
            alerts = [raw_alerts]
    return alerts


def _classify_alert(alert: dict) -> Optional[str]:
    texts = []
    for key in ("event", "title", "headline"):
        value = alert.get(key)
        if isinstance(value, str):
            texts.append(value.lower())
    tags = alert.get("tags")
    if isinstance(tags, (list, tuple, set)):
        texts.extend(str(tag).lower() for tag in tags if tag)
    description = alert.get("description")
    if isinstance(description, str):
        texts.append(description.lower())

    for text in texts:
        if "warning" in text:
            return "warning"
    for text in texts:
        if "watch" in text:
            return "watch"
    for text in texts:
        if any(token in text for token in ("hazard", "alert", "advisory")):
            return "hazard"
    return None


def _render_precip_icon(is_snow: bool, size: int, color: Tuple[int, int, int]) -> Image.Image:
    """Return a simple precipitation marker that doesn't rely on emoji fonts.

    Some systems don't ship an emoji font Pillow can render, which results in
    an empty box for the precipitation glyph. Drawing a small vector icon keeps
    the UI legible regardless of available fonts.
    """

    size = max(8, size)
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    icon_draw = ImageDraw.Draw(icon)

    if is_snow:
        center = size / 2
        radius = size * 0.42
        arm_width = max(1, int(round(size * 0.09)))
        branch = radius * 0.4
        for idx in range(6):
            angle = math.radians(idx * 60)
            end_x = center + radius * math.cos(angle)
            end_y = center + radius * math.sin(angle)
            icon_draw.line((center, center, end_x, end_y), fill=color, width=arm_width)

            branch_dx = branch * math.sin(angle)
            branch_dy = branch * math.cos(angle)
            icon_draw.line(
                (end_x, end_y, end_x - branch_dx, end_y + branch_dy),
                fill=color,
                width=max(1, arm_width - 1),
            )
            icon_draw.line(
                (end_x, end_y, end_x + branch_dx, end_y - branch_dy),
                fill=color,
                width=max(1, arm_width - 1),
            )
    else:
        top = (size * 0.5, size * 0.05)
        left = (size * 0.24, size * 0.58)
        right = (size * 0.76, size * 0.58)
        bottom = (size * 0.5, size * 0.95)
        icon_draw.polygon([top, left, bottom, right], fill=color)
        ellipse_height = size * 0.32
        icon_draw.ellipse(
            (
                size * 0.22,
                size * 0.56,
                size * 0.78,
                size * 0.56 + ellipse_height,
            ),
            fill=color,
        )

    return icon


def _detect_weather_alert(weather: object) -> Tuple[Optional[str], Optional[Tuple[float, float, float]]]:
    alerts = _normalise_alerts(weather)
    severity: Optional[str] = None
    for alert in alerts:
        level = _classify_alert(alert)
        if level is None:
            continue
        if severity is None or ALERT_PRIORITY[level] > ALERT_PRIORITY[severity]:
            severity = level
            if severity == "warning":
                break
    return severity, ALERT_LED_COLORS.get(severity)


def _draw_alert_indicator(draw: ImageDraw.ImageDraw, severity: Optional[str]) -> None:
    if not severity:
        return
    icon_color = ALERT_ICON_COLORS.get(severity, (255, 215, 0))
    w_icon, h_icon = draw.textsize(ALERT_SYMBOL, font=FONT_EMOJI_SMALL)
    x_icon = WIDTH - w_icon - 2
    y_icon = HEIGHT - h_icon - 2
    draw.text((x_icon, y_icon), ALERT_SYMBOL, font=FONT_EMOJI_SMALL, fill=icon_color)

# ─── Screen 1: Basic weather + two-line Feels/Hi/Lo ────────────────────────────
@log_call
def draw_weather_screen_1(display, weather, transition=False):
    if not weather:
        return None

    severity, led_color = _detect_weather_alert(weather)

    current = weather.get("current", {})
    daily   = weather.get("daily", [{}])[0]
    hourly  = weather.get("hourly") if isinstance(weather.get("hourly"), list) else None

    temp  = round(current.get("temp", 0))
    desc  = current.get("weather", [{}])[0].get("description", "").title()

    feels = round(current.get("feels_like", 0))
    hi    = round(daily.get("temp", {}).get("max", 0))
    lo    = round(daily.get("temp", {}).get("min", 0))

    clear_display(display)
    img  = Image.new("RGB", (WIDTH, HEIGHT), "black")
    draw = ImageDraw.Draw(img)

    # Temperature
    temp_str = f"{temp}°F"
    w_temp, h_temp = draw.textsize(temp_str, font=FONT_TEMP)
    draw.text(((WIDTH - w_temp)//2, 0), temp_str, font=FONT_TEMP, fill=(255,255,255))

    font_desc = FONT_CONDITION
    w_desc, h_desc = draw.textsize(desc, font=font_desc)
    if w_desc > WIDTH:
        font_desc = FONT_WEATHER_DETAILS_BOLD
        w_desc, h_desc = draw.textsize(desc, font=font_desc)
    draw.text(
        ((WIDTH - w_desc)//2, h_temp + WEATHER_DESC_GAP),
        desc,
        font=font_desc,
        fill=(255,255,255)
    )

    icon_code = current.get("weather", [{}])[0].get("icon")
    icon_img = fetch_weather_icon(icon_code, WEATHER_ICON_SIZE)

    cloud_cover = current.get("clouds")
    try:
        cloud_cover = int(round(float(cloud_cover)))
    except Exception:
        cloud_cover = None

    pop_pct = None
    next_hour = None
    if hourly:
        current_dt = current.get("dt")
        if isinstance(current_dt, (int, float)):
            for hour in hourly:
                if not isinstance(hour, dict):
                    continue
                hour_dt = hour.get("dt")
                if isinstance(hour_dt, (int, float)) and hour_dt > current_dt:
                    next_hour = hour
                    break
        if next_hour is None:
            if len(hourly) > 1 and isinstance(hourly[1], dict):
                next_hour = hourly[1]
            elif hourly and isinstance(hourly[0], dict):
                next_hour = hourly[0]
        pop_pct = _pop_pct_from(next_hour)

    if pop_pct is None:
        pop_pct = _pop_pct_from(daily)

    daily_weather_list = daily.get("weather") if isinstance(daily.get("weather"), list) else []
    daily_weather = (daily_weather_list or [{}])[0]
    weather_id = daily_weather.get("id")
    weather_main = (daily_weather.get("main") or "").strip().lower()
    is_snow = False
    if weather_main == "snow":
        is_snow = True
    elif isinstance(weather_id, int) and 600 <= weather_id < 700:
        is_snow = True
    elif daily.get("snow") or current.get("snow"):
        is_snow = True

    precip_emoji = "❄" if is_snow else "💧"
    precip_percent = None
    if pop_pct is not None:
        precip_percent = f"{max(0, min(pop_pct, 100))}%"

    cloud_percent = None
    if cloud_cover is not None:
        cloud_percent = f"{max(0, min(cloud_cover, 100))}%"

    # Feels/Hi/Lo groups
    labels    = ["Feels", "Hi", "Lo"]
    values    = [f"{feels}°", f"{hi}°", f"{lo}°"]
    # dynamic colors
    if feels > hi:
        feels_col = (255,165,0)
    elif feels < lo:
        feels_col = uv_index_color(2)
    else:
        feels_col = (255,255,255)
    val_colors = [feels_col, (255,0,0), (0,0,255)]

    groups = []
    for lbl, val in zip(labels, values):
        lw, lh = draw.textsize(lbl, font=FONT_WEATHER_LABEL)
        vw, vh = draw.textsize(val, font=FONT_WEATHER_DETAILS)
        gw = max(lw, vw)
        groups.append((lbl, lw, lh, val, vw, vh, gw))

    # horizontal layout
    SPACING_X = 12
    total_w   = sum(g[6] for g in groups) + SPACING_X * (len(groups)-1)
    x0        = (WIDTH - total_w)//2

    # vertical positions
    max_val_h = max(g[5] for g in groups)
    max_lbl_h = max(g[2] for g in groups)
    y_val     = HEIGHT - max_val_h - 9
    LABEL_GAP = 2
    y_lbl     = y_val - max_lbl_h - LABEL_GAP

    # paste icon between desc and labels
    top_of_icons = h_temp + h_desc + WEATHER_DESC_GAP * 2
    y_icon = top_of_icons + ((y_lbl - top_of_icons - WEATHER_ICON_SIZE)//2)
    icon_x = (WIDTH - WEATHER_ICON_SIZE) // 2
    icon_center_y = top_of_icons + max(0, (y_lbl - top_of_icons) // 2)

    if icon_img:
        img.paste(icon_img, (icon_x, y_icon), icon_img)

    side_font = FONT_WEATHER_DETAILS
    stack_gap = 2
    if precip_percent:
        emoji_color = (173, 216, 230) if precip_emoji == "❄" else (135, 206, 250)
        icon_size = FONT_EMOJI.size if hasattr(FONT_EMOJI, "size") else 26
        precip_icon = _render_precip_icon(is_snow, icon_size, emoji_color)
        emoji_w, emoji_h = precip_icon.size
        pct_w, pct_h = draw.textsize(precip_percent, font=side_font)
        block_w = max(emoji_w, pct_w)
        block_h = emoji_h + stack_gap + pct_h
        precip_x = icon_x - 6 - block_w
        if precip_x < 0:
            precip_x = 0
        block_y = icon_center_y - block_h // 2
        emoji_x = precip_x + (block_w - emoji_w) // 2
        pct_x = precip_x + (block_w - pct_w) // 2
        img.paste(precip_icon, (emoji_x, block_y), precip_icon)
        draw.text((pct_x, block_y + emoji_h + stack_gap), precip_percent, font=side_font, fill=emoji_color)

    if cloud_percent:
        cloud_emoji = "☁"
        emoji_w, emoji_h = draw.textsize(cloud_emoji, font=FONT_EMOJI)
        pct_w, pct_h = draw.textsize(cloud_percent, font=side_font)
        block_w = max(emoji_w, pct_w)
        block_h = emoji_h + stack_gap + pct_h
        cloud_x = icon_x + WEATHER_ICON_SIZE + 6
        if cloud_x + block_w > WIDTH:
            cloud_x = WIDTH - block_w
        block_y = icon_center_y - block_h // 2
        emoji_x = cloud_x + (block_w - emoji_w) // 2
        pct_x = cloud_x + (block_w - pct_w) // 2
        draw.text((emoji_x, block_y), cloud_emoji, font=FONT_EMOJI, fill=(211, 211, 211))
        draw.text((pct_x, block_y + emoji_h + stack_gap), cloud_percent, font=side_font, fill=(211, 211, 211))

    # draw groups
    x = x0
    for idx, (lbl, lw, lh, val, vw, vh, gw) in enumerate(groups):
        cx = x + gw//2
        draw.text((cx - lw//2, y_lbl), lbl, font=FONT_WEATHER_LABEL,      fill=(255,255,255))
        draw.text((cx - vw//2, y_val), val, font=FONT_WEATHER_DETAILS,     fill=val_colors[idx])
        x += gw + SPACING_X

    _draw_alert_indicator(draw, severity)

    if transition:
        return ScreenImage(img, displayed=False, led_override=led_color)

    def _render_screen() -> None:
        display.image(img)
        display.show()

    if led_color is not None:
        with temporary_display_led(*led_color):
            _render_screen()
    else:
        _render_screen()
    return None


def _format_hour_label(timestamp: Optional[int], *, index: int) -> str:
    dt = timestamp_to_datetime(timestamp, CENTRAL_TIME)
    if dt:
        return dt.strftime("%-I%p").lower()
    return f"+{index}h"


def _normalise_condition(hour: dict) -> str:
    if not isinstance(hour, dict):
        return ""
    weather_list = hour.get("weather") if isinstance(hour.get("weather"), list) else []
    if weather_list:
        main_val = weather_list[0].get("main") or weather_list[0].get("description")
        if isinstance(main_val, str) and main_val.strip():
            return main_val.title()
    return ""


def _wind_arrow(degrees: Optional[float]) -> str:
    try:
        deg_val = float(degrees)
    except (TypeError, ValueError):
        return ""

    arrows = ["↑", "↗", "→", "↘", "↓", "↙", "←", "↖"]
    idx = int((deg_val % 360) / 45.0 + 0.5) % len(arrows)
    return arrows[idx]


def _gather_hourly_forecast(weather: object, hours: int) -> list[dict]:
    if not isinstance(weather, dict):
        return []
    hourly = weather.get("hourly") if isinstance(weather.get("hourly"), list) else []
    forecast = []
    for idx, hour in enumerate(hourly[:hours]):
        if not isinstance(hour, dict):
            continue
        wind_speed = None
        try:
            wind_speed = int(round(float(hour.get("wind_speed", 0))))
        except Exception:
            wind_speed = None
        wind_dir = ""
        if hour.get("wind_deg") is not None:
            wind_dir = _wind_arrow(hour.get("wind_deg")) or wind_direction(hour.get("wind_deg"))
        uvi_val = None
        try:
            uvi_val = int(round(float(hour.get("uvi", 0))))
        except Exception:
            uvi_val = None
        entry = {
            "temp": round(hour.get("temp", 0)),
            "time": _format_hour_label(hour.get("dt"), index=idx + 1),
            "condition": _normalise_condition(hour),
            "icon": None,
            "pop": _pop_pct_from(hour),
            "wind_speed": wind_speed,
            "wind_dir": wind_dir,
            "uvi": uvi_val,
        }
        weather_list = hour.get("weather") if isinstance(hour.get("weather"), list) else []
        if weather_list:
            entry["icon"] = weather_list[0].get("icon")
        forecast.append(entry)
    return forecast


@log_call
def draw_weather_hourly(display, weather, transition: bool = False, hours: int = HOURLY_FORECAST_HOURS):
    forecast = _gather_hourly_forecast(weather, hours)
    if not forecast:
        img = Image.new("RGB", (WIDTH, HEIGHT), "black")
        draw = ImageDraw.Draw(img)
        msg = "No hourly data"
        w, h = draw.textsize(msg, font=FONT_WEATHER_DETAILS_BOLD)
        draw.text(((WIDTH - w) // 2, (HEIGHT - h) // 2), msg, font=FONT_WEATHER_DETAILS_BOLD, fill=(255, 255, 255))
        return ScreenImage(img, displayed=False)

    clear_display(display)
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    draw = ImageDraw.Draw(img)

    hours_to_show = len(forecast)
    title = f"Next {hours_to_show} Hours"
    title_w, title_h = draw.textsize(title, font=FONT_WEATHER_LABEL)
    draw.text(((WIDTH - title_w) // 2, 2), title, font=FONT_WEATHER_LABEL, fill=(200, 200, 200))

    gap = 4
    available_width = WIDTH - gap * (hours_to_show + 1)
    col_w = max(1, available_width // hours_to_show)
    icon_cache: dict[str, Optional[Image.Image]] = {}
    icon_size = max(32, min(WEATHER_ICON_SIZE, col_w - 10))

    card_top = title_h + 6
    card_bottom = HEIGHT - 6
    card_height = card_bottom - card_top
    x_start = (WIDTH - (hours_to_show * col_w + gap * (hours_to_show - 1))) // 2

    card_layouts = []
    temps = []

    for idx, hour in enumerate(forecast):
        x0 = x_start + idx * (col_w + gap)
        x1 = x0 + col_w
        cx = (x0 + x1) // 2

        draw.rounded_rectangle(
            (x0, card_top, x1, card_bottom),
            radius=6,
            fill=(18, 18, 28),
            outline=(40, 40, 60),
        )

        time_label = hour.get("time", "")
        time_w, time_h = draw.textsize(time_label, font=FONT_WEATHER_DETAILS_BOLD)

        trend_area_top = card_top + 6 + time_h + 6
        trend_area_bottom = card_top + int(card_height * 0.4)
        if trend_area_bottom - trend_area_top < 16:
            trend_area_bottom = trend_area_top + 16

        icon_area_top = trend_area_bottom + 6
        icon_area_bottom = card_top + int(card_height * 0.68)

        stat_area_top = icon_area_bottom + 6
        stat_area_bottom = card_bottom - 6

        card_layouts.append(
            {
                "hour": hour,
                "x0": x0,
                "x1": x1,
                "cx": cx,
                "time_label": time_label,
                "time_size": (time_w, time_h),
                "trend_area": (trend_area_top, trend_area_bottom),
                "icon_area": (icon_area_top, icon_area_bottom),
                "stat_area": (stat_area_top, stat_area_bottom),
            }
        )
        temps.append(hour.get("temp", 0))

    if temps:
        min_temp = min(temps)
        max_temp = max(temps)
    else:
        min_temp = max_temp = 0

    temp_range = max(1, max_temp - min_temp)

    for layout in card_layouts:
        hour = layout["hour"]
        x0, x1 = layout["x0"], layout["x1"]
        cx = layout["cx"]
        time_label = layout["time_label"]
        time_w, time_h = layout["time_size"]
        trend_top, trend_bottom = layout["trend_area"]
        icon_area_top, icon_area_bottom = layout["icon_area"]
        stat_area_top, stat_area_bottom = layout["stat_area"]
        stat_area_height = max(1, stat_area_bottom - stat_area_top)

        temp_val = hour.get("temp", 0)
        temp_frac = (temp_val - min_temp) / temp_range
        temp_y = int(trend_bottom - temp_frac * (trend_bottom - trend_top))
        layout["temp_y"] = temp_y

        draw.text((cx - time_w // 2, card_top + 6), time_label, font=FONT_WEATHER_DETAILS_BOLD, fill=(235, 235, 235))

    for layout in card_layouts:
        hour = layout["hour"]
        x0, x1 = layout["x0"], layout["x1"]
        cx = layout["cx"]
        trend_top, trend_bottom = layout["trend_area"]
        icon_area_top, icon_area_bottom = layout["icon_area"]
        stat_area_top, stat_area_bottom = layout["stat_area"]
        stat_area_height = max(1, stat_area_bottom - stat_area_top)
        temp_y = layout.get("temp_y", trend_bottom)

        temp_val = hour.get("temp", 0)
        temp_str = f"{temp_val}°"
        temp_w, temp_h = draw.textsize(temp_str, font=FONT_CONDITION)
        temp_text_y = max(trend_top, min(trend_bottom - temp_h, temp_y - temp_h // 2))
        draw.text((cx - temp_w // 2, temp_text_y), temp_str, font=FONT_CONDITION, fill=(255, 255, 255))

        icon_code = hour.get("icon")
        icon_img = None
        if icon_code:
            if icon_code not in icon_cache:
                icon_cache[icon_code] = fetch_weather_icon(icon_code, icon_size)
            icon_img = icon_cache[icon_code]

        if icon_img:
            icon_y = icon_area_top + max(0, (icon_area_bottom - icon_area_top - icon_size) // 2)
            img.paste(icon_img, (cx - icon_size // 2, icon_y), icon_img)
        else:
            condition = hour.get("condition", "")
            if condition:
                display_text = condition
                cond_w, cond_h = draw.textsize(display_text, font=FONT_WEATHER_DETAILS)
                while cond_w > col_w - 10 and len(display_text) > 3:
                    display_text = display_text[:-1]
                    cond_w, cond_h = draw.textsize(display_text + "…", font=FONT_WEATHER_DETAILS)
                if display_text != condition:
                    display_text = display_text + "…"
                    cond_w, cond_h = draw.textsize(display_text, font=FONT_WEATHER_DETAILS)
                cond_y = icon_area_top + max(0, (icon_area_bottom - icon_area_top - cond_h) // 2)
                draw.text((cx - cond_w // 2, cond_y), display_text, font=FONT_WEATHER_DETAILS, fill=(170, 180, 240))

        draw.line((x0 + 6, stat_area_top, x1 - 6, stat_area_top), fill=(50, 50, 80), width=1)

        stat_items = []

        wind_speed = hour.get("wind_speed")
        wind_dir = hour.get("wind_dir", "") or ""
        if wind_speed is not None:
            wind_text = f"{wind_speed} mph"
            if wind_dir:
                wind_text = f"{wind_text} {wind_dir}"
            stat_items.append((wind_text, FONT_WEATHER_DETAILS_TINY, (180, 225, 255)))

        pop = hour.get("pop")
        if pop is not None:
            clamped_pop = max(0, min(pop, 100))
            pop_text = f"💧 {clamped_pop}%"
            stat_items.append((pop_text, FONT_WEATHER_DETAILS_TINY, (135, 206, 250)))

        uvi_val = hour.get("uvi")
        if uvi_val is not None:
            uv_color = uv_index_color(uvi_val)
            uv_text = f"UV {uvi_val}"
            stat_items.append((uv_text, FONT_WEATHER_DETAILS_TINY, uv_color))

        if stat_items:
            slots = len(stat_items) + 1
            for idx, (text, font, color) in enumerate(stat_items, start=1):
                text_w, text_h = draw.textsize(text, font=font)
                text_y = int(stat_area_top + (stat_area_height * idx / slots) - text_h / 2)
                text_y = max(stat_area_top, min(text_y, stat_area_bottom - text_h))
                draw.text((cx - text_w // 2, text_y), text, font=font, fill=color)


    if transition:
        return ScreenImage(img, displayed=False)

    display.image(img)
    display.show()
    return None


# ─── Screen 2: Detailed (with UV index) ───────────────────────────────────────
def draw_weather_screen_2(display, weather, transition=False):
    if not weather:
        return None

    severity, led_color = _detect_weather_alert(weather)

    current = weather.get("current", {})
    daily   = weather.get("daily", [{}])[0]

    now = datetime.datetime.now(CENTRAL_TIME)
    s_r = timestamp_to_datetime(daily.get("sunrise"), CENTRAL_TIME)
    s_s = timestamp_to_datetime(daily.get("sunset"), CENTRAL_TIME)

    # Sunrise or Sunset first
    if s_r and now < s_r:
        items = [("Sunrise:", s_r.strftime("%-I:%M %p"))]
    elif s_s:
        items = [("Sunset:",  s_s.strftime("%-I:%M %p"))]
    else:
        items = []

    # Other details
    wind_speed = round(current.get('wind_speed', 0))
    wind_dir = wind_direction(current.get('wind_deg'))
    wind_value = f"{wind_speed} mph"
    if wind_dir:
        wind_value = f"{wind_value} {wind_dir}"

    items += [
        ("Wind:",     wind_value),
        ("Gust:",     f"{round(current.get('wind_gust',0))} mph"),
        ("Humidity:", f"{current.get('humidity',0)}%"),
        ("Pressure:", f"{round(current.get('pressure',0)*0.0338639,2)} inHg"),
    ]

    uvi = round(current.get("uvi", 0))
    uv_col = uv_index_color(uvi)
    items.append(("UV Index:", str(uvi), uv_col))

    clear_display(display)
    img  = Image.new("RGB", (WIDTH, HEIGHT), "black")
    draw = ImageDraw.Draw(img)

    # compute per-row heights
    row_metrics = []
    total_h = 0
    for it in items:
        lbl, val = it[0], it[1]
        h1 = draw.textsize(lbl, font=FONT_WEATHER_DETAILS_BOLD)[1]
        h2 = draw.textsize(val, font=FONT_WEATHER_DETAILS)[1]
        row_h = max(h1, h2)
        row_metrics.append((lbl, val, row_h, h1, h2, it[2] if len(it)==3 else (255,255,255)))
        total_h += row_h

    # vertical spacing
    space = (HEIGHT - total_h) // (len(items) + 1)
    y = space

    # render each row, vertically centering label & value
    for lbl, val, row_h, h_lbl, h_val, color in row_metrics:
        lw, _ = draw.textsize(lbl, font=FONT_WEATHER_DETAILS_BOLD)
        vw, _ = draw.textsize(val, font=FONT_WEATHER_DETAILS)
        row_w = lw + 4 + vw
        x0    = (WIDTH - row_w)//2

        y_lbl = y + (row_h - h_lbl)//2
        y_val = y + (row_h - h_val)//2

        draw.text((x0,          y_lbl), lbl, font=FONT_WEATHER_DETAILS_BOLD, fill=(255,255,255))
        draw.text((x0 + lw + 4, y_val), val, font=FONT_WEATHER_DETAILS,      fill=color)
        y += row_h + space

    _draw_alert_indicator(draw, severity)

    if transition:
        return ScreenImage(img, displayed=False, led_override=led_color)

    def _render_screen() -> None:
        display.image(img)
        display.show()

    if led_color is not None:
        with temporary_display_led(*led_color):
            _render_screen()
    else:
        _render_screen()
    return None


def _latlon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int, float, float]:
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x_float = (lon + 180.0) / 360.0 * n
    y_float = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    x_tile = int(x_float)
    y_tile = int(y_float)
    return x_tile, y_tile, x_float - x_tile, y_float - y_tile


def _fetch_radar_frames(zoom: int = 7, max_frames: int = 6) -> list[Image.Image]:
    frames = _fetch_rainviewer_frames(zoom=zoom, max_frames=max_frames)
    if frames:
        return frames

    return _fetch_openweather_frame(zoom=zoom)


def _fetch_rainviewer_frames(zoom: int = 7, max_frames: int = 6) -> list[Image.Image]:
    try:
        meta_resp = requests.get(
            "https://api.rainviewer.com/public/weather-maps.json", timeout=6
        )
        meta_resp.raise_for_status()
        metadata = meta_resp.json()
    except Exception as exc:
        logging.warning("Radar metadata fetch failed: %s", exc)
        return []

    host = metadata.get("host", "https://tilecache.rainviewer.com")
    radar_info = metadata.get("radar") or {}
    frames = (radar_info.get("past") or []) + (radar_info.get("nowcast") or [])
    frames = frames[-max_frames:]

    x_tile, y_tile, x_offset, y_offset = _latlon_to_tile(LATITUDE, LONGITUDE, zoom)
    images: list[Image.Image] = []

    for frame in frames:
        path = frame.get("path") if isinstance(frame, dict) else None
        if not path:
            continue
        url = (
            f"{host.rstrip('/')}/{path.strip('/')}/256/{zoom}/{x_tile}/{y_tile}/2/1_1.png"
        )
        try:
            tile_resp = requests.get(url, timeout=6)
            tile_resp.raise_for_status()
            tile = Image.open(BytesIO(tile_resp.content)).convert("RGBA")
        except Exception as exc:  # pragma: no cover - network failures are non-fatal
            logging.warning("Radar tile fetch failed: %s", exc)
            continue

        frame_img = Image.new("RGBA", tile.size, (0, 0, 0, 255))
        frame_img.alpha_composite(tile)
        marker_x = int((x_offset or 0.5) * tile.width)
        marker_y = int((y_offset or 0.5) * tile.height)
        draw = ImageDraw.Draw(frame_img)
        draw.ellipse((marker_x - 3, marker_y - 3, marker_x + 3, marker_y + 3), fill=(255, 0, 0, 255))

        final_frame = frame_img.resize((WIDTH, HEIGHT), Image.LANCZOS).convert("RGB")
        images.append(final_frame)

    return images


def _fetch_openweather_frame(zoom: int = 7) -> list[Image.Image]:
    if not OWM_API_KEY:
        logging.warning("Radar fallback requires OpenWeatherMap API key; skipping fetch")
        return []

    try:
        x_tile, y_tile, x_offset, y_offset = _latlon_to_tile(LATITUDE, LONGITUDE, zoom)
        url = (
            "https://tile.openweathermap.org/map/precipitation_new/"
            f"{zoom}/{x_tile}/{y_tile}.png?appid={OWM_API_KEY}"
        )
        resp = requests.get(url, timeout=6)
        resp.raise_for_status()
        tile = Image.open(BytesIO(resp.content)).convert("RGBA")
    except Exception as exc:  # pragma: no cover - network failures are non-fatal
        logging.warning("OpenWeather radar fetch failed: %s", exc)
        return []

    frame_img = Image.new("RGBA", tile.size, (0, 0, 0, 255))
    frame_img.alpha_composite(tile)
    marker_x = int((x_offset or 0.5) * tile.width)
    marker_y = int((y_offset or 0.5) * tile.height)
    draw = ImageDraw.Draw(frame_img)
    draw.ellipse((marker_x - 3, marker_y - 3, marker_x + 3, marker_y + 3), fill=(255, 0, 0, 255))

    final_frame = frame_img.resize((WIDTH, HEIGHT), Image.LANCZOS).convert("RGB")
    return [final_frame]


def _fetch_base_map(zoom: int = 7) -> Optional[Image.Image]:
    x_tile, y_tile, x_offset, y_offset = _latlon_to_tile(LATITUDE, LONGITUDE, zoom)
    headers = {
        "User-Agent": "desk-display/1.0 (+https://github.com/lukemaryon/desk_display)",
    }
    tile_urls = [
        f"https://tile.open-meteo.com/v1/osm/{zoom}/{x_tile}/{y_tile}.png",
        f"https://tile.openstreetmap.org/{zoom}/{x_tile}/{y_tile}.png",
    ]

    tile: Optional[Image.Image] = None
    for url in tile_urls:
        try:
            resp = requests.get(url, timeout=6, headers=headers)
            resp.raise_for_status()
            tile = Image.open(BytesIO(resp.content)).convert("RGBA")
            break
        except Exception as exc:  # pragma: no cover - network failures are non-fatal
            logging.warning("Base map fetch failed from %s: %s", url, exc)

    if tile is None:
        return None

    marker_x = int((x_offset or 0.5) * tile.width)
    marker_y = int((y_offset or 0.5) * tile.height)
    draw = ImageDraw.Draw(tile)
    draw.ellipse((marker_x - 3, marker_y - 3, marker_x + 3, marker_y + 3), fill=(255, 64, 64, 255), outline=(255, 255, 255, 255))
    draw.text((marker_x + 6, marker_y - 8), "You", font=FONT_WEATHER_DETAILS, fill=(255, 255, 255, 255))
    return tile.convert("RGB")


@log_call
def draw_weather_radar(display, weather=None, transition: bool = False):
    zoom_level = 7
    frames = _fetch_radar_frames(zoom=zoom_level)
    base_map = _fetch_base_map(zoom=zoom_level)
    if not frames:
        img = Image.new("RGB", (WIDTH, HEIGHT), "black")
        draw = ImageDraw.Draw(img)
        msg = "Radar unavailable"
        w, h = draw.textsize(msg, font=FONT_WEATHER_DETAILS_BOLD)
        draw.text(((WIDTH - w) // 2, (HEIGHT - h) // 2), msg, font=FONT_WEATHER_DETAILS_BOLD, fill=(255, 255, 255))
        return ScreenImage(img, displayed=False)

    clear_display(display)
    loops = 2
    delay = 0.5
    radar_height = int(HEIGHT * 0.65)
    separator_y = radar_height
    map_section = None
    if base_map:
        map_section = base_map.resize((WIDTH, HEIGHT - radar_height), Image.LANCZOS)

    def _compose_frame(frame: Image.Image) -> Image.Image:
        if map_section is None:
            return frame
        combined = Image.new("RGB", (WIDTH, HEIGHT), "black")
        radar_resized = frame.resize((WIDTH, radar_height), Image.LANCZOS)
        combined.paste(radar_resized, (0, 0))
        combined.paste(map_section, (0, radar_height))
        draw = ImageDraw.Draw(combined)
        draw.line((0, separator_y, WIDTH, separator_y), fill=(60, 60, 60))
        draw.text((4, radar_height + 4), "Map overview", font=FONT_WEATHER_DETAILS_BOLD, fill=(220, 220, 220))
        return combined

    composed_frames = [_compose_frame(frame) for frame in frames]

    for _ in range(loops):
        for frame in composed_frames:
            display.image(frame)
            display.show()
            time.sleep(delay)

    last_frame = composed_frames[-1]
    if transition:
        return ScreenImage(last_frame, displayed=True)

    display.image(last_frame)
    display.show()
    return None
