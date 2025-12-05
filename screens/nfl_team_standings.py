"""NFL team standings screens."""
from screens.mlb_team_standings import (
    draw_standings_screen1 as _base_screen1,
    draw_standings_screen2 as _base_screen2,
)
from utils import log_call


def _strip_pct_leading_zero(rec, *, precision=3):
    """Return a copy of the record with pct formatted without a leading zero."""

    if not rec:
        return rec

    league_record = rec.get("leagueRecord")
    if not isinstance(league_record, dict):
        return rec

    pct_val = league_record.get("pct")
    if pct_val in (None, ""):
        return rec

    try:
        pct_txt = f"{float(pct_val):.{precision}f}"
    except Exception:
        pct_txt = str(pct_val)

    updated_record = {**league_record, "pct": pct_txt.lstrip("0")}
    return {**rec, "leagueRecord": updated_record}


@log_call
def draw_nfl_standings_screen1(display, rec, logo_path, division_name, *, transition=False):
    """Wrap the generic standings screen for NFL teams (no GB/WC columns)."""
    return _base_screen1(
        display,
        _strip_pct_leading_zero(rec),
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
        _strip_pct_leading_zero(rec),
        logo_path,
        pct_precision=3,
        split_order=("home", "away", "division", "conference"),
        show_streak=True,
        show_points=True,
        transition=transition,
    )


__all__ = ["draw_nfl_standings_screen1", "draw_nfl_standings_screen2"]
