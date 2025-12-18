#!/usr/bin/env python3
"""Render a traffic map for the configured commute routes."""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from config import FONT_TRAVEL_HEADER, FONT_TRAVEL_VALUE, HEIGHT, TRAVEL_TITLE, WIDTH
from screens.draw_travel_time import (
    TRAVEL_ICON_294,
    TRAVEL_ICON_90,
    TRAVEL_ICON_94,
    TRAVEL_ICON_LSD,
    TravelTimeResult,
    _compose_icons,
    get_travel_routes,
    is_travel_screen_active,
)
from utils import ScreenImage, log_call

ROUTE_ICON_HEIGHT = 26
MAP_MARGIN = 12
LEGEND_GAP = 6
BACKGROUND_COLOR = (18, 18, 18)
MAP_COLOR = (60, 60, 60)


def _decode_polyline(polyline: str) -> List[Tuple[float, float]]:
    # https://developers.google.com/maps/documentation/utilities/polylinealgorithm
    points: List[Tuple[float, float]] = []
    index = 0
    lat = lng = 0

    while index < len(polyline):
        shift = result = 0
        while True:
            b = ord(polyline[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if result & 1 else result >> 1
        lat += dlat

        shift = result = 0
        while True:
            b = ord(polyline[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if result & 1 else result >> 1
        lng += dlng

        points.append((lat / 1e5, lng / 1e5))

    return points


def _flatten(points_by_route: Iterable[Sequence[Tuple[float, float]]]) -> List[Tuple[float, float]]:
    flattened: List[Tuple[float, float]] = []
    for points in points_by_route:
        flattened.extend(points)
    return flattened


def _bounds(points: Sequence[Tuple[float, float]]):
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return (min(lats), min(lngs)), (max(lats), max(lngs))


def _project(point: Tuple[float, float], top_left, bottom_right, width: int, height: int) -> Tuple[int, int]:
    (min_lat, min_lng) = top_left
    (max_lat, max_lng) = bottom_right
    lat, lng = point

    if max_lat == min_lat or max_lng == min_lng:
        return width // 2, height // 2

    x = (lng - min_lng) / (max_lng - min_lng)
    y = 1 - (lat - min_lat) / (max_lat - min_lat)

    return int(MAP_MARGIN + x * (width - 2 * MAP_MARGIN)), int(
        MAP_MARGIN + y * (height - 2 * MAP_MARGIN)
    )


def _traffic_color(route: Optional[dict]) -> Tuple[int, int, int]:
    if not route:
        return (180, 180, 180)

    traffic = route.get("_duration_sec")
    baseline = route.get("_duration_base_sec")
    if traffic and baseline:
        ratio = traffic / baseline if baseline else 1
        if ratio <= 1.1:
            return (40, 200, 120)
        if ratio <= 1.35:
            return (255, 195, 60)
        return (240, 80, 80)

    return (160, 160, 160)


def _draw_routes(draw: ImageDraw.ImageDraw, routes: Dict[str, Optional[dict]], canvas_size: Tuple[int, int]) -> None:
    polylines: Dict[str, List[Tuple[float, float]]] = {}
    for key, route in routes.items():
        encoded = None
        overview = route.get("overview_polyline") if route else None
        if isinstance(overview, dict):
            encoded = overview.get("points")
        if not encoded or not isinstance(encoded, str):
            continue
        try:
            polylines[key] = _decode_polyline(encoded)
        except Exception:
            logging.warning("Travel map: failed to decode polyline for %s", key)

    if not polylines:
        return

    all_points = _flatten(polylines.values())
    top_left, bottom_right = _bounds(all_points)

    for key, points in polylines.items():
        if len(points) < 2:
            continue
        color = _traffic_color(routes.get(key))
        projected = [
            _project(pt, top_left, bottom_right, *canvas_size) for pt in points
        ]
        draw.line(projected, fill=color, width=5, joint="curve")


def _compose_legend_entry(
    label: str, value: str, icon_paths: Sequence[str], fill: Tuple[int, int, int]
) -> Image.Image:
    icon = _compose_icons(icon_paths, height=ROUTE_ICON_HEIGHT)
    swatch = Image.new("RGBA", (icon.width, icon.height), fill + (255,))
    swatch.putalpha(128)
    swatch = swatch.convert("RGB")

    entry_height = max(icon.height, 24)
    padding = 6
    measurement = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    label_w, label_h = measurement.textsize(label, font=FONT_TRAVEL_HEADER)
    value_w, value_h = measurement.textsize(value, font=FONT_TRAVEL_VALUE)

    width = max(icon.width, label_w + value_w + padding) + padding * 2
    canvas = Image.new("RGB", (width, entry_height), (0, 0, 0))

    canvas.paste(swatch, (padding, (entry_height - swatch.height) // 2))
    canvas.paste(icon, (padding, (entry_height - icon.height) // 2), icon)

    draw = ImageDraw.Draw(canvas)
    text_y = (entry_height - label_h) // 2
    draw.text((icon.width + padding * 2, text_y), label, font=FONT_TRAVEL_HEADER, fill=(230, 230, 230))
    draw.text(
        (width - value_w - padding, (entry_height - value_h) // 2),
        value,
        font=FONT_TRAVEL_VALUE,
        fill=fill,
    )

    return canvas


def _compose_travel_map(routes: Dict[str, Optional[dict]]) -> Image.Image:
    times = {key: TravelTimeResult.from_route(route) for key, route in routes.items()}

    canvas = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(canvas)

    map_height = int(HEIGHT * 0.55)
    draw.rectangle((0, 0, WIDTH, map_height), fill=MAP_COLOR)

    _draw_routes(draw, routes, (WIDTH, map_height))

    legend_entries: List[Tuple[str, Image.Image]] = []
    legend_entries.append(
        (
            "Lake Shore → Sheridan",
            _compose_legend_entry(
                "Lake Shore",
                times.get("lake_shore", TravelTimeResult("N/A")).normalized(),
                [TRAVEL_ICON_LSD],
                _traffic_color(routes.get("lake_shore")),
            ),
        )
    )
    legend_entries.append(
        (
            "Kennedy → Edens",
            _compose_legend_entry(
                "Kennedy/Edens",
                times.get("kennedy_edens", TravelTimeResult("N/A")).normalized(),
                [TRAVEL_ICON_90, TRAVEL_ICON_94],
                _traffic_color(routes.get("kennedy_edens")),
            ),
        )
    )
    legend_entries.append(
        (
            "Kennedy → 294",
            _compose_legend_entry(
                "Kennedy/294",
                times.get("kennedy_294", TravelTimeResult("N/A")).normalized(),
                [TRAVEL_ICON_90, TRAVEL_ICON_294],
                _traffic_color(routes.get("kennedy_294")),
            ),
        )
    )

    y = map_height + LEGEND_GAP
    padding = 6
    for _label, entry in legend_entries:
        canvas.paste(entry, (padding, y))
        y += entry.height + LEGEND_GAP

    title_w, title_h = draw.textsize(TRAVEL_TITLE, font=FONT_TRAVEL_HEADER)
    draw.text(((WIDTH - title_w) // 2, max(2, (map_height - title_h) // 2)), TRAVEL_TITLE, font=FONT_TRAVEL_HEADER, fill=(240, 240, 240))

    return canvas


@log_call
def draw_travel_map_screen(display, transition: bool = False) -> Optional[Image.Image | ScreenImage]:
    if not is_travel_screen_active():
        return None

    routes = get_travel_routes()
    img = _compose_travel_map(routes)

    if display is not None:
        display.image(img)
        display.show()

    return ScreenImage(img, displayed=display is not None)


__all__ = ["draw_travel_map_screen"]
