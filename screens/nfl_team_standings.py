"""NFL team standings screens."""
from screens.mlb_team_standings import (
    draw_standings_screen1 as _base_screen1,
    draw_standings_screen2 as _base_screen2,
)
from utils import log_call


@log_call
def draw_nfl_standings_screen1(display, rec, logo_path, division_name, *, transition=False):
    """Wrap the generic standings screen for NFL teams (no GB/WC columns)."""
    return _base_screen1(
        display,
        rec,
        logo_path,
        division_name,
        show_games_back=False,
        show_wild_card=False,
        transition=transition,
    )

@log_call
def draw_nfl_standings_screen2(display, rec, logo_path, *, transition=False):
    """Customize standings screen 2 for NFL teams."""

    return _base_screen2(
        display,
        rec,
        logo_path,
        pct_precision=3,
        split_order=("home", "away", "division", "conference"),
        split_overrides={"home": "-", "away": "-"},
        show_streak=False,
        transition=transition,
    )


__all__ = ["draw_nfl_standings_screen1", "draw_nfl_standings_screen2"]
