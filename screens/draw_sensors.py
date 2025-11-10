#!/usr/bin/env python3
"""draw_sensors.py (RGB, 320x240)

Display live readings from the Pimoroni Multi-Sensor Stick (PIM745).

The stick exposes three sensors:
  • BME280  – already rendered by :mod:`draw_inside`
  • LTR559  – ambient light + proximity
  • LSM6DS3 – 6-axis IMU (accelerometer + gyroscope)

This screen focuses on the latter two so that when the board is connected we
can glance at motion and light changes in real time. Cards include subtle
progress bars to hint at movement and illumination trends as the values update
with every refresh cycle.
"""

from __future__ import annotations

import logging
import math
import time
from importlib import import_module
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw

import config
from utils import clear_display, clone_font, fit_font, measure_text

W, H = config.WIDTH, config.HEIGHT

# Screen colours -------------------------------------------------------------
_BG = (8, 12, 22)
_TEXT = (238, 242, 255)
_MUTED_TEXT = (180, 187, 205)
_CARD_AMBER = getattr(config, "INSIDE_CHIP_AMBER", (233, 165, 36))
_CARD_BLUE = getattr(config, "INSIDE_CHIP_BLUE", (34, 124, 236))
_CARD_PURPLE = getattr(config, "INSIDE_CHIP_PURPLE", (150, 70, 200))
_CARD_TEAL = (42, 182, 170)

_LTR559_SENSOR: Optional[Any] = None
_LTR559_PROBED = False
_LSM6DS3_SENSOR: Optional[Any] = None
_LSM6DS3_PROBED = False


# ----------------------------------------------------------------------------
# Hardware access helpers
# ----------------------------------------------------------------------------

def _import_first(*module_names: str) -> Optional[Any]:
    for name in module_names:
        try:
            return import_module(name)
        except ModuleNotFoundError:
            continue
        except Exception as exc:  # pragma: no cover - hardware import
            logging.debug("draw_sensors: error importing %s: %s", name, exc)
            continue
    return None


def _get_ltr559() -> Optional[Any]:
    global _LTR559_SENSOR, _LTR559_PROBED
    if _LTR559_SENSOR is not None:
        return _LTR559_SENSOR
    if _LTR559_PROBED:
        return None

    module = _import_first("ltr559", "pimoroni_ltr559")
    if module is None:
        _LTR559_PROBED = True
        logging.debug("draw_sensors: LTR559 driver not available")
        return None

    sensor_cls = getattr(module, "LTR559", None)
    if sensor_cls is None:
        logging.debug("draw_sensors: LTR559 class missing in %s", module.__name__)
        _LTR559_PROBED = True
        return None

    try:
        _LTR559_SENSOR = sensor_cls()  # type: ignore[call-arg]
    except Exception as exc:  # pragma: no cover - hardware access
        logging.warning("draw_sensors: failed to initialise LTR559 sensor: %s", exc)
        _LTR559_SENSOR = None
    _LTR559_PROBED = True
    return _LTR559_SENSOR


def _get_lsm6ds3() -> Optional[Any]:
    global _LSM6DS3_SENSOR, _LSM6DS3_PROBED
    if _LSM6DS3_SENSOR is not None:
        return _LSM6DS3_SENSOR
    if _LSM6DS3_PROBED:
        return None

    module = _import_first("lsm6ds3", "pimoroni_lsm6ds3")
    if module is None:
        _LSM6DS3_PROBED = True
        logging.debug("draw_sensors: LSM6DS3 driver not available")
        return None

    sensor_cls = getattr(module, "LSM6DS3", None)
    if sensor_cls is None:
        logging.debug("draw_sensors: LSM6DS3 class missing in %s", module.__name__)
        _LSM6DS3_PROBED = True
        return None

    try:
        _LSM6DS3_SENSOR = sensor_cls()  # type: ignore[call-arg]
    except Exception as exc:  # pragma: no cover - hardware access
        logging.warning("draw_sensors: failed to initialise LSM6DS3 sensor: %s", exc)
        _LSM6DS3_SENSOR = None
    _LSM6DS3_PROBED = True
    return _LSM6DS3_SENSOR


# ----------------------------------------------------------------------------
# Reading helpers
# ----------------------------------------------------------------------------

def _clean_float(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _read_ltr559(sensor: Any) -> Dict[str, Optional[float]]:
    readings: Dict[str, Optional[float]] = {"lux": None, "proximity": None}
    try:
        lux = sensor.get_lux()
        readings["lux"] = _clean_float(lux if lux is not None else None)
    except Exception as exc:  # pragma: no cover - hardware read
        logging.debug("draw_sensors: failed to read LTR559 lux: %s", exc)
    try:
        proximity = sensor.get_proximity()
        readings["proximity"] = _clean_float(proximity if proximity is not None else None)
    except Exception as exc:  # pragma: no cover - hardware read
        logging.debug("draw_sensors: failed to read LTR559 proximity: %s", exc)
    return readings


def _read_lsm6ds3(sensor: Any) -> Dict[str, Optional[Tuple[float, float, float]]]:
    accel: Optional[Tuple[float, float, float]] = None
    gyro: Optional[Tuple[float, float, float]] = None
    temp: Optional[float] = None

    try:
        accel_tuple = sensor.get_accelerometer_g_forces()
        if isinstance(accel_tuple, (list, tuple)) and len(accel_tuple) >= 3:
            accel = tuple(float(v) for v in accel_tuple[:3])  # type: ignore[assignment]
    except Exception as exc:  # pragma: no cover - hardware read
        logging.debug("draw_sensors: failed to read LSM6DS3 accelerometer: %s", exc)

    try:
        gyro_tuple = sensor.get_gyroscope_dps()
        if isinstance(gyro_tuple, (list, tuple)) and len(gyro_tuple) >= 3:
            gyro = tuple(float(v) for v in gyro_tuple[:3])  # type: ignore[assignment]
    except Exception as exc:  # pragma: no cover - hardware read
        logging.debug("draw_sensors: failed to read LSM6DS3 gyroscope: %s", exc)

    if hasattr(sensor, "get_temperature"):
        try:
            temp = _clean_float(sensor.get_temperature())
        except Exception as exc:  # pragma: no cover - hardware read
            logging.debug("draw_sensors: failed to read LSM6DS3 temperature: %s", exc)

    return {"accel": accel, "gyro": gyro, "temp": temp}


def _collect_readings() -> Optional[Dict[str, Dict[str, Optional[Any]]]]:
    payload: Dict[str, Dict[str, Optional[Any]]] = {}

    ltr = _get_ltr559()
    if ltr is not None:
        payload["light"] = _read_ltr559(ltr)

    imu = _get_lsm6ds3()
    if imu is not None:
        payload["motion"] = _read_lsm6ds3(imu)

    if not payload:
        return None
    return payload


# ----------------------------------------------------------------------------
# Rendering helpers
# ----------------------------------------------------------------------------

def _mix(color_a: Tuple[int, int, int], color_b: Tuple[int, int, int], weight: float) -> Tuple[int, int, int]:
    weight = max(0.0, min(1.0, weight))
    return tuple(
        int(round(channel_a + (channel_b - channel_a) * weight))
        for channel_a, channel_b in zip(color_a, color_b)
    )


def _format_triplet(values: Optional[Tuple[float, float, float]], suffix: str) -> str:
    if not values:
        return "—"
    return "  ".join(f"{val:+.2f}{suffix}" for val in values)


def _magnitude(values: Optional[Tuple[float, float, float]]) -> Optional[float]:
    if not values:
        return None
    return math.sqrt(sum(v * v for v in values))


def _normalise(value: Optional[float], scale: float) -> Optional[float]:
    if value is None or scale <= 0:
        return None
    return max(0.0, min(1.0, value / scale))


def _normalise_log(value: Optional[float], denom: float) -> Optional[float]:
    if value is None or value <= 0 or denom <= 0:
        return None
    ratio = math.log10(value + 1.0) / math.log10(denom + 1.0)
    return max(0.0, min(1.0, ratio))


def _resolve_fonts() -> Dict[str, Any]:
    title_font = getattr(config, "FONT_TITLE_SPORTS", getattr(config, "FONT_DATE_SPORTS", None))
    if title_font is None:
        raise RuntimeError("Title font unavailable")

    subtitle_base = getattr(
        config, "FONT_INSIDE_SUBTITLE", getattr(config, "FONT_DATE_SPORTS", title_font)
    )
    body_base = getattr(config, "FONT_DATE_SPORTS", title_font)

    subtitle_font = clone_font(subtitle_base, max(16, getattr(subtitle_base, "size", 24) - 4))
    label_font = clone_font(body_base, max(14, getattr(body_base, "size", 24) - 6))
    detail_font = clone_font(body_base, max(12, getattr(body_base, "size", 24) - 8))
    value_font = clone_font(title_font, max(22, getattr(title_font, "size", 30) - 4))

    return {
        "title": title_font,
        "subtitle": subtitle_font,
        "label": label_font,
        "value": value_font,
        "detail": detail_font,
    }


def _draw_title(draw: ImageDraw.ImageDraw, fonts: Dict[str, Any]) -> Tuple[int, int]:
    title = "Sensor Stick"
    subtitle = "Pimoroni Multi-Sensor (LTR559 · LSM6DS3)"

    title_font = fonts["title"]
    subtitle_font = fonts["subtitle"]

    title_w, title_h = measure_text(draw, title, title_font)
    draw.text(((W - title_w) // 2, 8), title, font=title_font, fill=_TEXT)

    subtitle_w, subtitle_h = measure_text(draw, subtitle, subtitle_font)
    draw.text(((W - subtitle_w) // 2, 12 + title_h), subtitle, font=subtitle_font, fill=_MUTED_TEXT)

    return title_h + subtitle_h + 16, subtitle_h


def _draw_chip(
    draw: ImageDraw.ImageDraw,
    rect: Tuple[int, int, int, int],
    label: str,
    value: str,
    detail: str,
    accent: Tuple[int, int, int],
    fonts: Dict[str, Any],
    progress: Optional[float] = None,
) -> None:
    x0, y0, x1, y1 = rect
    radius = 16
    fill = _mix(_BG, accent, 0.25)
    outline = _mix(accent, (255, 255, 255), 0.35)
    draw.rounded_rectangle(rect, radius=radius, fill=fill, outline=outline, width=2)

    label_font = fonts["label"]
    label_w, label_h = measure_text(draw, label, label_font)
    draw.text((x0 + 16, y0 + 14), label, font=label_font, fill=_MUTED_TEXT)

    value_area_top = y0 + 14 + label_h + 4
    value_area_bottom = y1 - 24

    if progress is not None:
        value_area_bottom -= 18

    value_font_base = fonts["value"]
    value_font = fit_font(
        draw,
        value,
        value_font_base,
        max_width=x1 - x0 - 32,
        max_height=max(18, value_area_bottom - value_area_top - 8),
        min_pt=14,
        max_pt=getattr(value_font_base, "size", 32),
    )
    value_w, value_h = measure_text(draw, value, value_font)
    draw.text(
        (x0 + (x1 - x0 - value_w) // 2, value_area_top + max(0, (value_area_bottom - value_area_top - value_h) // 2)),
        value,
        font=value_font,
        fill=_TEXT,
    )

    detail_font = fonts["detail"]
    detail_w, detail_h = measure_text(draw, detail, detail_font)
    detail_y = y1 - 16 - detail_h

    if progress is not None:
        bar_margin = 18
        bar_height = 8
        bar_rect = (x0 + bar_margin, y1 - bar_margin - bar_height, x1 - bar_margin, y1 - bar_margin)
        track = _mix(_BG, accent, 0.18)
        draw.rounded_rectangle(bar_rect, radius=bar_height // 2, fill=track)
        if progress > 0:
            prog = max(0.0, min(1.0, progress))
            prog_rect = (
                bar_rect[0],
                bar_rect[1],
                bar_rect[0] + int((bar_rect[2] - bar_rect[0]) * prog),
                bar_rect[3],
            )
            draw.rounded_rectangle(prog_rect, radius=bar_height // 2, fill=accent)
        detail_y = bar_rect[1] - 6 - detail_h

    draw.text(((x0 + x1 - detail_w) // 2, detail_y), detail, font=detail_font, fill=_MUTED_TEXT)


def _render(readings: Dict[str, Dict[str, Optional[Any]]]) -> Image.Image:
    fonts = _resolve_fonts()
    img = Image.new("RGB", (W, H), _BG)
    draw = ImageDraw.Draw(img)

    title_block_h, _ = _draw_title(draw, fonts)
    content_top = title_block_h + 6
    bottom_margin = 14

    cards = []
    light = readings.get("light", {})
    lux = _clean_float(light.get("lux")) if light else None
    prox = _clean_float(light.get("proximity")) if light else None

    lux_value = "—" if lux is None else f"{lux:,.1f} lx"
    prox_value = "—" if prox is None else f"{prox:,.0f}"

    lux_detail = "waiting for light" if lux is None else "ambient lux"
    if lux is not None:
        lux_detail = "higher = brighter"

    prox_detail = "waiting for motion" if prox is None else "closer = higher"

    cards.append(
        {
            "label": "Ambient light",
            "value": lux_value,
            "detail": lux_detail,
            "accent": _CARD_AMBER,
            "progress": _normalise_log(lux, 1500.0),
        }
    )
    cards.append(
        {
            "label": "Proximity",
            "value": prox_value,
            "detail": prox_detail,
            "accent": _CARD_BLUE,
            "progress": _normalise(prox, 2047.0),
        }
    )

    motion = readings.get("motion", {})
    accel = motion.get("accel") if motion else None
    gyro = motion.get("gyro") if motion else None
    temp = motion.get("temp") if motion else None

    accel_mag = _magnitude(accel)
    gyro_mag = _magnitude(gyro)

    accel_detail = _format_triplet(accel, "g")
    gyro_detail = _format_triplet(gyro, "°/s")

    accel_value = "—" if accel_mag is None else f"{accel_mag:.2f} g"
    gyro_value = "—" if gyro_mag is None else f"{gyro_mag:.1f}°/s"

    cards.append(
        {
            "label": "Motion force",
            "value": accel_value,
            "detail": accel_detail,
            "accent": _CARD_PURPLE,
            "progress": _normalise(accel_mag, 4.0),
        }
    )

    gyro_detail_text = gyro_detail
    if temp is not None:
        gyro_detail_text = f"{gyro_detail}   ·   {temp:.1f}°C"

    cards.append(
        {
            "label": "Rotation",
            "value": gyro_value,
            "detail": gyro_detail_text,
            "accent": _CARD_TEAL,
            "progress": _normalise(gyro_mag, 500.0),
        }
    )

    columns = 2
    rows = math.ceil(len(cards) / columns) if cards else 1
    rows = max(rows, 1)

    margin_x = 14
    gap_x = 12
    gap_y = 12
    content_bottom = H - bottom_margin
    available_height = max(20, content_bottom - content_top)

    card_width = max(80, (W - 2 * margin_x - gap_x * (columns - 1)) // columns)
    card_height = max(70, (available_height - gap_y * (rows - 1)) // rows)

    total_height = rows * card_height + gap_y * (rows - 1)
    y_offset = content_top + max(0, (available_height - total_height) // 2)

    for index, card in enumerate(cards):
        row = index // columns
        col = index % columns
        x0 = margin_x + col * (card_width + gap_x)
        y0 = y_offset + row * (card_height + gap_y)
        rect = (x0, y0, x0 + card_width, y0 + card_height)
        _draw_chip(
            draw,
            rect,
            card["label"],
            card["value"],
            card["detail"],
            card["accent"],
            fonts,
            card.get("progress"),
        )

    timestamp = time.strftime("%I:%M:%S %p").lstrip("0")
    footer = f"Updated {timestamp}"
    footer_font = fonts["detail"]
    footer_w, footer_h = measure_text(draw, footer, footer_font)
    draw.text((W - footer_w - 12, H - footer_h - 8), footer, font=footer_font, fill=_MUTED_TEXT)

    return img


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def draw_sensors(display, transition: bool = False):
    readings = _collect_readings()
    if readings is None:
        logging.warning("draw_sensors: Pimoroni sensor stick not detected")
        return None

    try:
        img = _render(readings)
    except Exception as exc:  # pragma: no cover - rendering error
        logging.error("draw_sensors: failed to render sensor screen: %s", exc)
        return None

    if transition:
        return img

    if display is None:
        return img

    clear_display(display)
    display.image(img)
    display.show()
    time.sleep(5)
    return None


if __name__ == "__main__":
    preview = draw_sensors(None, transition=True)
    if isinstance(preview, Image.Image):
        preview.show()
