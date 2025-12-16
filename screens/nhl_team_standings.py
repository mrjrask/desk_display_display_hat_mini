"""NHL team standings screens."""
from screens.mlb_team_standings import (
    draw_standings_screen1 as _base_screen1,
    draw_standings_screen2 as _base_screen2,
    _format_int,
)
from config import FONT_STAND1_RANK
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
        pct_txt = f"{float(pct_val):.{precision}f}".lstrip("0")
    except Exception:
        pct_txt = str(pct_val).lstrip("0")

    updated_record = {**league_record, "pct": pct_txt}
    return {**rec, "leagueRecord": updated_record}


def _format_division_name(rec, default_name):
    name = None
    if isinstance(rec, dict):
        name = rec.get("divisionName") or rec.get("divisionAbbrev")

    name = name or default_name
    if not name:
        return name

    if "division" not in str(name).lower():
        return f"{name} Division"
    return name


def _format_conference_name(rec):
    name = None
    if isinstance(rec, dict):
        name = rec.get("conferenceName") or rec.get("conferenceAbbrev")

    if not name:
        return "conference"

    lower_name = str(name).lower()
    if "conference" in lower_name:
        trimmed = str(name).replace("Conference", "").strip()
        return f"{trimmed} Conf." if trimmed else "conference"

    if "conf" in lower_name:
        return name

    name = str(name).replace("Conference", "").strip()
    return f"{name} Conf." if name else "conference"


@log_call
def draw_nhl_standings_screen1(display, rec, logo_path, division_name, *, transition=False):
    """Wrap the generic standings screen for NHL teams (no GB/WC columns)."""

    rec_clean = _strip_pct_leading_zero(rec)

    division_display = _format_division_name(rec_clean, division_name)
    conference_display = _format_conference_name(rec_clean)
    rec_for_display = (
        {**rec_clean, "conferenceName": conference_display} if rec_clean else rec_clean
    )

    return _base_screen1(
        display,
        rec_for_display,
        logo_path,
        division_display,
        show_games_back=False,
        show_wild_card=False,
        points_font=FONT_STAND1_RANK,
        ot_label="OTL",
        points_label="points",
        conference_label="conference",
        show_conference_rank=True,
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
        _strip_pct_leading_zero(rec),
        logo_path,
        record_details_fn=_nhl_record_details,
        split_order=("division", "conference", "home", "away"),
        show_streak=False,
        show_points=False,
        transition=transition,
    )

__all__ = ["draw_nhl_standings_screen1", "draw_nhl_standings_screen2"]
