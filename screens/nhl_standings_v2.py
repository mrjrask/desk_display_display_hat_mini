#!/usr/bin/env python3
"""Wild card NHL standings screens (v2) using GP, RW, and Points columns."""
from __future__ import annotations

from contextlib import contextmanager
from typing import List, Sequence, Tuple

from utils import ScreenImage, clear_display, log_call

import screens.nhl_standings as nhl_standings
from screens.nhl_standings import (
    CONFERENCE_EAST_KEY,
    CONFERENCE_WEST_KEY,
    DIVISION_ORDER_EAST,
    DIVISION_ORDER_WEST,
    TITLE_EAST,
    TITLE_WEST,
    _animate_overview_drop,
    _apply_style_overrides,
    _compose_overview_image,
    _fetch_standings_data,
    _normalize_int,
    _prepare_overview,
    _render_conference,
    _render_empty,
    _scroll_vertical,
    OVERVIEW_TITLE,
)

WILDCARD_SECTION_NAME = "Wild Card"


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
    return normalized


def _wildcard_sort_key(team: dict) -> Tuple[int, int, int, int, str]:
    points = _normalize_int(team.get("points"))
    regulation_wins = _normalize_int(team.get("regulationWins"))
    wins = _normalize_int(team.get("wins"))
    games_played = _normalize_int(team.get("gamesPlayed"))
    abbr = str(team.get("abbr", ""))
    # Sort by points (desc), regulation wins (desc), overall wins (desc),
    # games played (asc), then abbreviation for determinism.
    return (-points, -regulation_wins, -wins, games_played, abbr)


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
    wildcards = remaining[:2]
    if wildcards:
        wildcard_conf[WILDCARD_SECTION_NAME] = wildcards

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


def _wildcard_overview_divisions(
    wildcard_standings: dict[str, dict[str, list[dict]]]
) -> list[tuple[str, list[dict]]]:
    divisions: list[tuple[str, list[dict]]] = []
    for conf_key, label, division_order in (
        (CONFERENCE_WEST_KEY, "West", DIVISION_ORDER_WEST),
        (CONFERENCE_EAST_KEY, "East", DIVISION_ORDER_EAST),
    ):
        conference = wildcard_standings.get(conf_key, {})
        teams: list[dict] = []
        for division in division_order:
            teams.extend(conference.get(division, []))
        teams.extend(conference.get(WILDCARD_SECTION_NAME, []))
        divisions.append((label, teams))

    return divisions


@log_call
def draw_nhl_standings_overview_v2(display, transition: bool = False) -> ScreenImage:
    with _wildcard_columns():
        standings_by_conf = _fetch_standings_data()
        wildcard_standings = _build_wildcard_standings(standings_by_conf)
        _apply_style_overrides("NHL Standings Overview v2")
        _update_column_metrics()

        divisions: List[tuple[str, List[dict]]] = _wildcard_overview_divisions(
            wildcard_standings
        )

        if not any(teams for _, teams in divisions):
            clear_display(display)
            img = _render_empty(OVERVIEW_TITLE)
            if transition:
                return ScreenImage(img, displayed=False)
            display.image(img)
            return ScreenImage(img, displayed=True)

        base, row_positions = _prepare_overview(divisions)
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
            img = _render_empty(TITLE_WEST)
            if transition:
                return ScreenImage(img, displayed=False)
            display.image(img)
            return ScreenImage(img, displayed=True)

        full_img = _render_conference(TITLE_WEST, divisions, conference)
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
            img = _render_empty(TITLE_EAST)
            if transition:
                return ScreenImage(img, displayed=False)
            display.image(img)
            return ScreenImage(img, displayed=True)

        full_img = _render_conference(TITLE_EAST, divisions, conference)
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
