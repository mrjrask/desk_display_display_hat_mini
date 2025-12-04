"""NHL team standings screens."""
from screens.mlb_team_standings import (
    draw_standings_screen1 as _base_screen1,
    draw_standings_screen2 as _base_screen2,
    _format_int,
)
from utils import log_call


@log_call
def draw_nhl_standings_screen1(display, rec, logo_path, division_name, *, transition=False):
    """Wrap the generic standings screen for NHL teams (no GB/WC columns)."""
    return _base_screen1(
        display,
        rec,
        logo_path,
        division_name,
        show_games_back=False,
        show_wild_card=False,
        ot_label="OTL",
        points_label="points",
        conference_label="conference",
        transition=transition,
    )


def _nhl_record_details(rec, base_rec):
    pts_val = _format_int(rec.get("points"))
    return f"{base_rec} ({pts_val} pts)"


@log_call
def draw_nhl_standings_screen2(display, rec, logo_path, *, transition=False):
    """Customize standings screen 2 for NHL teams."""

    return _base_screen2(
        display,
        rec,
        logo_path,
        record_details_fn=_nhl_record_details,
        split_order=("division", "conference", "lastTen", "home", "away"),
        split_overrides={"lastTen": "-", "home": "-", "away": "-"},
        show_streak=False,
        show_points=False,
        transition=transition,
    )

__all__ = ["draw_nhl_standings_screen1", "draw_nhl_standings_screen2"]
