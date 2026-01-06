#!/usr/bin/env python3
"""Render a traffic map for the configured commute routes."""

from __future__ import annotations

import logging
import math
from io import BytesIO
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import requests
from PIL import Image, ImageDraw, ImageEnhance

from config import (
    FONT_TRAVEL_HEADER,
    FONT_TRAVEL_VALUE,
    GOOGLE_MAPS_API_KEY,
    HEIGHT,
    LATITUDE,
    LONGITUDE,
    TRAVEL_TITLE,
    WIDTH,
)
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
MAP_COLOR = (36, 36, 36)
MAP_BRIGHTNESS = 1.35
STATIC_MAP_TIMEOUT = 6
STATIC_MAP_USER_AGENT = "desk-display/traffic-map"
MAP_ZOOM_LEVELS = range(15, 6, -1)
MAP_DARK_STYLES = (
    "style=element:geometry|color:0x1b1b1b",
    "style=element:labels.text.fill|color:0xffffff",
    "style=element:labels.text.stroke|color:0x000000|lightness:80",
    "style=feature:road|element:geometry|color:0x303030",
    "style=feature:road.highway|element:geometry|color:0x3a3a3a",
    "style=feature:poi|visibility:off",
    "style=feature:transit|visibility:off",
    "style=feature:water|element:geometry|color:0x0d171f",
)


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
        return _traffic_color_for_ratio(ratio)

    return (160, 160, 160)


def _traffic_color_for_ratio(ratio: Optional[float]) -> Tuple[int, int, int]:
    if ratio is None:
        return (160, 160, 160)

    if ratio <= 1.1:
        return (40, 200, 120)
    if ratio <= 1.35:
        return (255, 195, 60)
    return (240, 80, 80)


def _route_ratio(route: Optional[dict]) -> Optional[float]:
    if not route:
        return None
    traffic = route.get("_duration_sec")
    baseline = route.get("_duration_base_sec")
    if traffic and baseline:
        return traffic / baseline if baseline else None
    return None


def _step_ratio(step: dict, fallback: Optional[float]) -> Optional[float]:
    duration = (step.get("duration") or {}).get("value")
    traffic = (step.get("duration_in_traffic") or {}).get("value")
    baseline = duration
    value = traffic or duration
    if value and baseline:
        return value / baseline
    return fallback


def _step_points(step: dict) -> List[Tuple[float, float]]:
    if not isinstance(step, dict):
        return []

    polyline = step.get("polyline") if isinstance(step, dict) else None
    encoded_step = None
    if isinstance(polyline, dict):
        encoded_step = polyline.get("points")
    elif isinstance(polyline, str):
        encoded_step = polyline
    if not encoded_step or not isinstance(encoded_step, str):
        return []
    try:
        return _decode_polyline(encoded_step)
    except Exception:
        logging.warning("Travel map: failed to decode step polyline")
    return []


def _extract_route_segments(
    routes: Dict[str, Optional[dict]],
) -> Dict[str, List[Tuple[List[Tuple[float, float]], Tuple[int, int, int]]]]:
    """Return decoded route segments with per-step traffic colors."""

    segments: Dict[str, List[Tuple[List[Tuple[float, float]], Tuple[int, int, int]]]] = {}
    for key, route in routes.items():
        if not route:
            continue

        route_ratio = _route_ratio(route)
        steps = ((route.get("legs") or [{}])[0].get("steps") or [])
        for step in steps:
            points = _step_points(step)
            if len(points) < 2:
                continue
            ratio = _step_ratio(step, route_ratio)
            color = _traffic_color_for_ratio(ratio)
            segments.setdefault(key, []).append((points, color))

        if segments.get(key):
            continue

        overview = route.get("overview_polyline")
        if isinstance(overview, dict):
            encoded = overview.get("points")
        elif isinstance(overview, str):
            encoded = overview
        else:
            encoded = None

        if encoded and isinstance(encoded, str):
            try:
                decoded = _decode_polyline(encoded)
                color = _traffic_color(route)
                segments[key] = [(decoded, color)]
            except Exception:
                logging.warning("Travel map: failed to decode overview polyline for %s", key)

    return segments


def _extract_polylines(routes: Dict[str, Optional[dict]]) -> Dict[str, List[Tuple[float, float]]]:
    """Backward-compatible helper for tests and ancillary callers."""

    polylines: Dict[str, List[Tuple[float, float]]] = {}
    segments = _extract_route_segments(routes)
    for key, route_segments in segments.items():
        combined: List[Tuple[float, float]] = []
        for points, _ in route_segments:
            combined.extend(points)
        if combined:
            polylines[key] = combined
    return polylines


def _latlng_to_world_xy(lat: float, lng: float, zoom: int) -> Tuple[float, float]:
    siny = math.sin(math.radians(lat))
    siny = min(max(siny, -0.9999), 0.9999)
    scale = 256 * (2 ** zoom)
    x = (lng + 180.0) / 360.0 * scale
    y = (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi)) * scale
    return x, y


def _project_to_map(
    point: Tuple[float, float],
    center: Tuple[float, float],
    zoom: int,
    width: int,
    height: int,
) -> Tuple[int, int]:
    lat, lng = point
    center_lat, center_lng = center
    center_x, center_y = _latlng_to_world_xy(center_lat, center_lng, zoom)
    x, y = _latlng_to_world_xy(lat, lng, zoom)
    return int((x - center_x) + width / 2), int((y - center_y) + height / 2)


def _select_map_view(
    polylines: Iterable[Sequence[Tuple[float, float]]],
    canvas_size: Tuple[int, int],
    fallback_center: Tuple[float, float],
) -> Tuple[Tuple[float, float], int]:
    all_points = _flatten(polylines)
    if not all_points:
        return fallback_center, 12

    (min_lat, min_lng), (max_lat, max_lng) = _bounds(all_points)
    center = ((min_lat + max_lat) / 2, (min_lng + max_lng) / 2)
    available_w = max(1, canvas_size[0] - 2 * MAP_MARGIN)
    available_h = max(1, canvas_size[1] - 2 * MAP_MARGIN)

    for zoom in MAP_ZOOM_LEVELS:
        xs: List[float] = []
        ys: List[float] = []
        for lat, lng in ((min_lat, min_lng), (min_lat, max_lng), (max_lat, min_lng), (max_lat, max_lng)):
            x, y = _latlng_to_world_xy(lat, lng, zoom)
            xs.append(x)
            ys.append(y)
        span_x = max(xs) - min(xs)
        span_y = max(ys) - min(ys)
        if span_x <= available_w and span_y <= available_h:
            return center, zoom

    return center, 8


def _fetch_base_map(
    center: Tuple[float, float],
    zoom: int,
    size: Tuple[int, int],
) -> Optional[Image.Image]:
    lat, lng = center
    width, height = size
    if not GOOGLE_MAPS_API_KEY:
        logging.warning("Traffic map: GOOGLE_MAPS_API_KEY not set; skipping base map fetch")
        return None

    url = (
        "https://maps.googleapis.com/maps/api/staticmap?"
        f"center={lat},{lng}&zoom={zoom}&size={width}x{height}&maptype=roadmap&"
        + "&".join(MAP_DARK_STYLES)
        + f"&key={GOOGLE_MAPS_API_KEY}"
    )
    headers = {"User-Agent": STATIC_MAP_USER_AGENT}
    try:
        resp = requests.get(url, timeout=STATIC_MAP_TIMEOUT, headers=headers)
        resp.raise_for_status()
        return Image.open(BytesIO(resp.content)).convert("RGB")
    except Exception as exc:  # pragma: no cover - non-fatal network issues
        logging.warning("Traffic map: base map fetch failed from %s: %s", url, exc)
        return None


def _draw_routes(
    draw: ImageDraw.ImageDraw,
    route_segments: Dict[str, List[Tuple[List[Tuple[float, float]], Tuple[int, int, int]]]],
    canvas_size: Tuple[int, int],
    map_view: Optional[Tuple[Tuple[float, float], int]] = None,
) -> None:
    if not route_segments:
        return

    if map_view:
        center, zoom = map_view
        projector = lambda pt: _project_to_map(pt, center, zoom, *canvas_size)
    else:
        all_points = _flatten(points for segments in route_segments.values() for points, _ in segments)
        top_left, bottom_right = _bounds(all_points)
        projector = lambda pt: _project(pt, top_left, bottom_right, *canvas_size)

    for segments in route_segments.values():
        for points, color in segments:
            if len(points) < 2:
                continue
            projected = [projector(pt) for pt in points]
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
    map_height = HEIGHT
    route_segments = _extract_route_segments(routes)
    polylines = [points for segments in route_segments.values() for points, _ in segments]
    map_view = _select_map_view(polylines, (WIDTH, map_height), (LATITUDE, LONGITUDE))

    base_map = _fetch_base_map(map_view[0], map_view[1], (WIDTH, map_height))
    if base_map is None:
        canvas = Image.new("RGB", (WIDTH, map_height), MAP_COLOR)
    else:
        canvas = ImageEnhance.Brightness(base_map).enhance(MAP_BRIGHTNESS)

    draw = ImageDraw.Draw(canvas)
    _draw_routes(draw, route_segments, (WIDTH, map_height), map_view=map_view)

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
