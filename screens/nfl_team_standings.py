"""NFL team standings screens."""
from screens.mlb_team_standings import (
    draw_standings_screen1 as _base_screen1,
    draw_standings_screen2 as draw_nfl_standings_screen2,
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

__all__ = ["draw_nfl_standings_screen1", "draw_nfl_standings_screen2"]
