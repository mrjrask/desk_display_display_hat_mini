#!/usr/bin/env python3
"""Wild card NHL standings screens (v2) using GP, RW, and Points columns."""
from __future__ import annotations

from contextlib import contextmanager
from typing import List, Sequence, Tuple

from PIL import Image, ImageDraw

from config import HEIGHT, WIDTH
from utils import ScreenImage, clear_display, log_call

import screens.nhl_standings as nhl_standings
from screens.nhl_standings import (
    BACKGROUND_COLOR,
    CONFERENCE_EAST_KEY,
    CONFERENCE_WEST_KEY,
    DIVISION_ORDER_EAST,
    DIVISION_ORDER_WEST,
    OVERVIEW_BOTTOM_MARGIN,
    OVERVIEW_LOGO_OVERLAP,
    OVERVIEW_LOGO_PADDING,
    OVERVIEW_MARGIN_X,
    OVERVIEW_MAX_LOGO_HEIGHT,
    OVERVIEW_MIN_LOGO_HEIGHT,
    OVERVIEW_TITLE_MARGIN_BOTTOM,
    TITLE_EAST,
    TITLE_WEST,
    TITLE_FONT,
    TITLE_MARGIN_TOP,
    _draw_centered_text,
    _animate_overview_drop,
    _apply_style_overrides,
    _compose_overview_image,
    _fetch_standings_data,
    _load_overview_logo,
    _normalize_int,
    _prepare_overview,
    _render_conference,
    _render_empty,
    _scroll_vertical,
    OVERVIEW_TITLE_EAST,
    OVERVIEW_TITLE_WEST,
)

WILDCARD_SECTION_NAME = "Wild Card"
OVERVIEW_TITLE_WEST_V3 = "NHL West Wild Card"
OVERVIEW_TITLE_EAST_V3 = "NHL East Wild Card"
TITLE_SUBTITLE_WILDCARD = "Wild Card Standings"
DIVISION_LEADERS_LABELS = {
    "Central": "Central Leaders",
    "Pacific": "Pacific Leaders",
    "Metropolitan": "Metropolitan Leaders",
    "Atlantic": "Atlantic Leaders",
}


@contextmanager
def _wildcard_columns() -> None:
    original_stats = nhl_standings.STATS_COLUMNS
    original_headers = nhl_standings.COLUMN_HEADERS
    original_column_text_height = nhl_standings.COLUMN_TEXT_HEIGHT
    original_column_row_height = nhl_standings.COLUMN_ROW_HEIGHT
    try:
        nhl_standings.STATS_COLUMNS = ("gamesPlayed", "regulationWins", "points")
        nhl_standings.COLUMN_HEADERS = [
            ("", "team", "left"),
            ("GP", "gamesPlayed", "right"),
            ("RW", "regulationWins", "right"),
            ("PTS", "points", "right"),
        ]
        yield
    finally:
        nhl_standings.STATS_COLUMNS = original_stats
        nhl_standings.COLUMN_HEADERS = original_headers
        nhl_standings.COLUMN_TEXT_HEIGHT = original_column_text_height
        nhl_standings.COLUMN_ROW_HEIGHT = original_column_row_height


def _update_column_metrics() -> None:
    nhl_standings.COLUMN_TEXT_HEIGHT = max(
        nhl_standings._text_size(
            label,
            nhl_standings.COLUMN_HEADER_FONTS.get(key, nhl_standings.COLUMN_FONT),
        )[1]
        for label, key, _ in nhl_standings.COLUMN_HEADERS
    )
    nhl_standings.COLUMN_ROW_HEIGHT = nhl_standings.COLUMN_TEXT_HEIGHT + 2


def _normalize_wildcard_team(team: dict) -> dict:
    normalized = dict(team)
    wins = _normalize_int(normalized.get("wins"))
    losses = _normalize_int(normalized.get("losses"))
    ot = _normalize_int(normalized.get("ot"))
    normalized.setdefault("gamesPlayed", wins + losses + ot)
    normalized.setdefault("regulationWins", 0)
    normalized.setdefault(
        "regulationPlusOvertimeWins",
        _normalize_int(normalized.get("row", wins)),
    )
    return normalized


def _wildcard_sort_key(team: dict) -> Tuple[int, int, int, int, int, str]:
    points = _normalize_int(team.get("points"))
    regulation_wins = _normalize_int(team.get("regulationWins"))
    regulation_plus_overtime_wins = _normalize_int(
        team.get("regulationPlusOvertimeWins", team.get("row", team.get("wins")))
    )
    wins = _normalize_int(team.get("wins"))
    games_played = _normalize_int(team.get("gamesPlayed"))
    abbr = str(team.get("abbr", ""))
    # Sort by points (desc), regulation wins (desc), regulation+OT wins (desc),
    # overall wins (desc), games played (asc), then abbreviation for determinism.
    return (
        -points,
        -regulation_wins,
        -regulation_plus_overtime_wins,
        -wins,
        games_played,
        abbr,
    )


def _conference_wildcard_standings(
    conference: dict[str, list[dict]], division_order: Sequence[str]
) -> dict[str, list[dict]]:
    wildcard_conf: dict[str, list[dict]] = {}
    remaining: list[dict] = []

    for division in division_order:
        teams = [_normalize_wildcard_team(team) for team in conference.get(division, [])]
        teams.sort(key=_wildcard_sort_key)
        wildcard_conf[division] = teams[:3]
        remaining.extend(teams[3:])

    remaining.sort(key=_wildcard_sort_key)
    if len(remaining) >= 3:
        remaining[2]["_wildcard_cutoff_before"] = True
    if remaining:
        wildcard_conf[WILDCARD_SECTION_NAME] = remaining

    return wildcard_conf


def _build_wildcard_standings(
    standings_by_conf: dict[str, dict[str, list[dict]]]
) -> dict[str, dict[str, list[dict]]]:
    wildcard: dict[str, dict[str, list[dict]]] = {}
    conference_orders = {
        CONFERENCE_WEST_KEY: DIVISION_ORDER_WEST,
        CONFERENCE_EAST_KEY: DIVISION_ORDER_EAST,
    }

    for conf_key, order in conference_orders.items():
        conference = standings_by_conf.get(conf_key, {})
        if conference:
            wildcard[conf_key] = _conference_wildcard_standings(conference, order)

    return wildcard


def _sort_by_points(teams: list[dict]) -> list[dict]:
    return sorted(teams, key=_wildcard_sort_key)


def _conference_overview_divisions(
    conference: dict[str, list[dict]],
    division_order: Sequence[str],
    label: str,
) -> list[tuple[str, list[dict]]]:
    divisions: list[tuple[str, list[dict]]] = [
        (f"{division} Top 3", _sort_by_points(conference.get(division, [])))
        for division in division_order
    ]

    wildcard = _sort_by_points(list(conference.get(WILDCARD_SECTION_NAME, [])))
    divisions.append((f"{label} Wild Card", wildcard[:2]))
    divisions.append((f"{label} Wild Card Rest", wildcard[2:]))
    return divisions


def _overview_layout_horizontal(
    rows: Sequence[tuple[str, List[dict]]],
    title: str,
) -> tuple[Image.Image, float, float]:
    base = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(base)

    y = TITLE_MARGIN_TOP
    y += _draw_centered_text(draw, title, TITLE_FONT, y)
    y += OVERVIEW_TITLE_MARGIN_BOTTOM

    logos_top = y
    available_height = max(1.0, HEIGHT - logos_top - OVERVIEW_BOTTOM_MARGIN)
    row_count = max(1, len(rows))
    row_height = available_height / row_count
    return base, logos_top, row_height


def _row_logo_height(row_height: float, team_count: int) -> int:
    if team_count <= 0:
        return OVERVIEW_MIN_LOGO_HEIGHT
    available_width = max(1.0, WIDTH - 2 * OVERVIEW_MARGIN_X)
    col_width = available_width / team_count
    logo_width_limit = max(6, int(col_width - OVERVIEW_LOGO_PADDING))
    logo_base_height = row_height + OVERVIEW_LOGO_OVERLAP
    logo_target_height = int(
        min(
            OVERVIEW_MAX_LOGO_HEIGHT,
            max(OVERVIEW_MIN_LOGO_HEIGHT, logo_base_height),
            logo_width_limit,
        )
    )
    return max(6, logo_target_height)


def _build_overview_rows_horizontal(
    rows: Sequence[tuple[str, List[dict]]],
    logos_top: float,
    row_height: float,
) -> List[List[nhl_standings.Placement]]:
    placements: List[List[nhl_standings.Placement]] = []
    available_width = max(1.0, WIDTH - 2 * OVERVIEW_MARGIN_X)

    for row_idx, (_, teams) in enumerate(rows):
        row: List[nhl_standings.Placement] = []
        if not teams:
            placements.append(row)
            continue

        team_count = len(teams)
        col_width = available_width / team_count
        col_centers = [OVERVIEW_MARGIN_X + col_width * (idx + 0.5) for idx in range(team_count)]
        logo_height = _row_logo_height(row_height, team_count)

        for col_idx, team in enumerate(teams):
            abbr = (team.get("abbr") or "").upper()
            if not abbr:
                continue
            logo = _load_overview_logo(abbr, logo_height)
            if not logo:
                continue
            x0 = int(col_centers[col_idx] - logo.width / 2)
            y_center = logos_top + row_height * (row_idx + 0.5)
            y0 = int(y_center - logo.height / 2)
            row.append((abbr, logo, x0, y0))
        placements.append(row)

    return placements


def _prepare_overview_horizontal(
    rows: Sequence[tuple[str, List[dict]]],
    title: str,
) -> tuple[Image.Image, List[List[nhl_standings.Placement]]]:
    base, logos_top, row_height = _overview_layout_horizontal(rows, title=title)
    row_positions = _build_overview_rows_horizontal(rows, logos_top, row_height)
    return base, row_positions


@log_call
def draw_nhl_standings_overview_v2_west(display, transition: bool = False) -> ScreenImage:
    with _wildcard_columns():
        standings_by_conf = _fetch_standings_data()
        wildcard_standings = _build_wildcard_standings(standings_by_conf)
        _apply_style_overrides("NHL Standings Overview v2 West")
        _update_column_metrics()

        divisions: List[tuple[str, List[dict]]] = _conference_overview_divisions(
            wildcard_standings.get(CONFERENCE_WEST_KEY, {}),
            DIVISION_ORDER_WEST,
            "West",
        )

        if not any(teams for _, teams in divisions):
            clear_display(display)
            img = _render_empty(OVERVIEW_TITLE_WEST)
            if transition:
                return ScreenImage(img, displayed=False)
            display.image(img)
            return ScreenImage(img, displayed=True)

        base, row_positions = _prepare_overview(divisions, title=OVERVIEW_TITLE_WEST)
        final_img, _ = _compose_overview_image(base, row_positions)

        clear_display(display)
        _animate_overview_drop(display, base, row_positions)
        display.image(final_img)
        if hasattr(display, "show"):
            display.show()

    return ScreenImage(final_img, displayed=True)


@log_call
def draw_nhl_overview_west_v3(display, transition: bool = False) -> ScreenImage:
    with _wildcard_columns():
        standings_by_conf = _fetch_standings_data()
        wildcard_standings = _build_wildcard_standings(standings_by_conf)
        _apply_style_overrides("NHL Overview West v3")
        _update_column_metrics()

        rows = _conference_overview_divisions(
            wildcard_standings.get(CONFERENCE_WEST_KEY, {}),
            DIVISION_ORDER_WEST,
            "West",
        )

        if not any(teams for _, teams in rows):
            clear_display(display)
            img = _render_empty(OVERVIEW_TITLE_WEST_V3)
            if transition:
                return ScreenImage(img, displayed=False)
            display.image(img)
            return ScreenImage(img, displayed=True)

        base, row_positions = _prepare_overview_horizontal(rows, title=OVERVIEW_TITLE_WEST_V3)
        final_img, _ = _compose_overview_image(base, row_positions)

        clear_display(display)
        _animate_overview_drop(display, base, row_positions)
        display.image(final_img)
        if hasattr(display, "show"):
            display.show()

    return ScreenImage(final_img, displayed=True)


@log_call
def draw_nhl_standings_overview_v2_east(display, transition: bool = False) -> ScreenImage:
    with _wildcard_columns():
        standings_by_conf = _fetch_standings_data()
        wildcard_standings = _build_wildcard_standings(standings_by_conf)
        _apply_style_overrides("NHL Standings Overview v2 East")
        _update_column_metrics()

        divisions: List[tuple[str, List[dict]]] = _conference_overview_divisions(
            wildcard_standings.get(CONFERENCE_EAST_KEY, {}),
            DIVISION_ORDER_EAST,
            "East",
        )

        if not any(teams for _, teams in divisions):
            clear_display(display)
            img = _render_empty(OVERVIEW_TITLE_EAST)
            if transition:
                return ScreenImage(img, displayed=False)
            display.image(img)
            return ScreenImage(img, displayed=True)

        base, row_positions = _prepare_overview(divisions, title=OVERVIEW_TITLE_EAST)
        final_img, _ = _compose_overview_image(base, row_positions)

        clear_display(display)
        _animate_overview_drop(display, base, row_positions)
        display.image(final_img)
        if hasattr(display, "show"):
            display.show()

    return ScreenImage(final_img, displayed=True)


@log_call
def draw_nhl_overview_east_v3(display, transition: bool = False) -> ScreenImage:
    with _wildcard_columns():
        standings_by_conf = _fetch_standings_data()
        wildcard_standings = _build_wildcard_standings(standings_by_conf)
        _apply_style_overrides("NHL Overview East v3")
        _update_column_metrics()

        rows = _conference_overview_divisions(
            wildcard_standings.get(CONFERENCE_EAST_KEY, {}),
            DIVISION_ORDER_EAST,
            "East",
        )

        if not any(teams for _, teams in rows):
            clear_display(display)
            img = _render_empty(OVERVIEW_TITLE_EAST_V3)
            if transition:
                return ScreenImage(img, displayed=False)
            display.image(img)
            return ScreenImage(img, displayed=True)

        base, row_positions = _prepare_overview_horizontal(rows, title=OVERVIEW_TITLE_EAST_V3)
        final_img, _ = _compose_overview_image(base, row_positions)

        clear_display(display)
        _animate_overview_drop(display, base, row_positions)
        display.image(final_img)
        if hasattr(display, "show"):
            display.show()

    return ScreenImage(final_img, displayed=True)


@log_call
def draw_nhl_standings_west_v2(display, transition: bool = False) -> ScreenImage:
    with _wildcard_columns():
        standings_by_conf = _fetch_standings_data()
        wildcard_standings = _build_wildcard_standings(standings_by_conf)
        _apply_style_overrides("NHL Standings West v2")
        _update_column_metrics()
        conference = wildcard_standings.get(CONFERENCE_WEST_KEY, {})
        divisions = [d for d in DIVISION_ORDER_WEST if conference.get(d)]
        if conference.get(WILDCARD_SECTION_NAME):
            divisions.append(WILDCARD_SECTION_NAME)
        if not divisions:
            clear_display(display)
            img = _render_empty(TITLE_WEST, TITLE_SUBTITLE_WILDCARD)
            if transition:
                return ScreenImage(img, displayed=False)
            display.image(img)
            return ScreenImage(img, displayed=True)

        full_img = _render_conference(
            TITLE_WEST,
            divisions,
            conference,
            subtitle=TITLE_SUBTITLE_WILDCARD,
            division_labels=DIVISION_LEADERS_LABELS,
        )
        clear_display(display)
        _scroll_vertical(display, full_img)
    return ScreenImage(full_img, displayed=True)


@log_call
def draw_nhl_standings_east_v2(display, transition: bool = False) -> ScreenImage:
    with _wildcard_columns():
        standings_by_conf = _fetch_standings_data()
        wildcard_standings = _build_wildcard_standings(standings_by_conf)
        _apply_style_overrides("NHL Standings East v2")
        _update_column_metrics()
        conference = wildcard_standings.get(CONFERENCE_EAST_KEY, {})
        divisions = [d for d in DIVISION_ORDER_EAST if conference.get(d)]
        if conference.get(WILDCARD_SECTION_NAME):
            divisions.append(WILDCARD_SECTION_NAME)
        if not divisions:
            clear_display(display)
            img = _render_empty(TITLE_EAST, TITLE_SUBTITLE_WILDCARD)
            if transition:
                return ScreenImage(img, displayed=False)
            display.image(img)
            return ScreenImage(img, displayed=True)

        full_img = _render_conference(
            TITLE_EAST,
            divisions,
            conference,
            subtitle=TITLE_SUBTITLE_WILDCARD,
            division_labels=DIVISION_LEADERS_LABELS,
        )
        clear_display(display)
        _scroll_vertical(display, full_img)
    return ScreenImage(full_img, displayed=True)


if __name__ == "__main__":  # pragma: no cover
    from utils import Display

    disp = Display()
    try:
        draw_nhl_standings_west_v2(disp)
        draw_nhl_standings_east_v2(disp)
    finally:
        clear_display(disp)
