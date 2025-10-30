"""Screen registry utilities for mapping screen IDs to render callables."""
from __future__ import annotations

import datetime as _dt
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

from PIL import Image

from utils import ScreenImage, animate_scroll
from screens.draw_bears_schedule import show_bears_next_game
from screens.draw_bulls_schedule import (
    draw_bulls_next_home_game,
    draw_last_bulls_game,
    draw_live_bulls_game,
    draw_sports_screen_bulls,
)
from screens.draw_hawks_schedule import (
    draw_hawks_next_home_game,
    draw_last_hawks_game,
    draw_live_hawks_game,
    draw_sports_screen_hawks,
)
from screens.draw_inside import draw_inside
from screens.draw_travel_time import draw_travel_time_screen
from screens.draw_vrnof import draw_vrnof_screen
from screens.draw_weather import draw_weather_screen_1, draw_weather_screen_2
from screens.draw_date_time import draw_date, draw_time
from screens.mlb_schedule import (
    draw_box_score,
    draw_cubs_result,
    draw_last_game,
    draw_next_home_game,
    draw_sports_screen,
)
from screens.mlb_scoreboard import draw_mlb_scoreboard
from screens.mlb_standings import (
    draw_AL_Central,
    draw_AL_East,
    draw_AL_Overview,
    draw_AL_West,
    draw_AL_WildCard,
    draw_NL_Central,
    draw_NL_East,
    draw_NL_Overview,
    draw_NL_West,
    draw_NL_WildCard,
)
from screens.mlb_team_standings import draw_standings_screen1, draw_standings_screen2
from screens.nba_scoreboard import draw_nba_scoreboard
from screens.nfl_scoreboard import draw_nfl_scoreboard
from screens.nfl_standings import (
    draw_nfl_overview_afc,
    draw_nfl_overview_nfc,
    draw_nfl_standings_afc,
    draw_nfl_standings_nfc,
)
from screens.nhl_scoreboard import draw_nhl_scoreboard
from screens.nhl_standings import (
    draw_nhl_standings_east,
    draw_nhl_standings_overview,
    draw_nhl_standings_west,
)

RenderCallable = Callable[[], Optional[Image.Image | ScreenImage]]


@dataclass
class ScreenDefinition:
    """Represents one renderable screen."""

    id: str
    render: RenderCallable
    available: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScreenContext:
    """Runtime context required to build screen callables."""

    display: Any
    cache: Dict[str, Any]
    logos: Dict[str, Optional[Image.Image]]
    image_dir: str
    travel_requested: bool
    travel_active: bool
    travel_window: Optional[Tuple[Optional[_dt.time], Optional[_dt.time]]]
    previous_travel_state: Optional[str]
    now: _dt.datetime


def _show_logo(display, image: Image.Image) -> Image.Image:
    animate_scroll(display, image)
    return image


def _extract_team_id(blob):
    if not isinstance(blob, dict):
        return None
    team = blob.get("team") if isinstance(blob.get("team"), dict) else blob
    if isinstance(team, dict):
        for key in ("id", "teamId", "team_id"):
            if team.get(key) is not None:
                return team.get(key)
    return None


def _games_match(game_a, game_b):
    if not game_a or not game_b:
        return False

    for key in ("gamePk", "id", "gameId", "gameUUID"):
        a_val = game_a.get(key)
        b_val = game_b.get(key)
        if a_val and b_val and a_val == b_val:
            return True

    def _teams(game, prefix):
        teams = game.get("teams")
        if isinstance(teams, dict):
            return teams.get(prefix) or {}
        return game.get(f"{prefix}Team") or game.get(f"{prefix}_team") or {}

    date_a = (game_a.get("gameDate") or game_a.get("officialDate") or "")[:10]
    date_b = (game_b.get("gameDate") or game_b.get("officialDate") or "")[:10]
    if date_a and date_b and date_a == date_b:
        home_a = _extract_team_id(_teams(game_a, "home"))
        home_b = _extract_team_id(_teams(game_b, "home"))
        away_a = _extract_team_id(_teams(game_a, "away"))
        away_b = _extract_team_id(_teams(game_b, "away"))
        return home_a and home_a == home_b and away_a and away_a == away_b

    return False


def _format_time(value: Optional[_dt.time]) -> str:
    if isinstance(value, _dt.time):
        return value.strftime("%I:%M %p").lstrip("0").replace(" 0", " ")
    return "all day"


def build_screen_registry(context: ScreenContext) -> Tuple[Dict[str, ScreenDefinition], Dict[str, Any]]:
    """Create a registry mapping screen IDs to render callables."""

    registry: Dict[str, ScreenDefinition] = {}
    metadata: Dict[str, Any] = {}

    def register(screen_id: str, func: RenderCallable, available: bool = True, **extra):
        registry[screen_id] = ScreenDefinition(
            id=screen_id,
            render=func,
            available=available,
            metadata=extra,
        )

    register("date", lambda: draw_date(context.display, transition=False))
    register("time", lambda: draw_time(context.display, transition=True))

    weather_data = context.cache.get("weather")
    weather_logo = context.logos.get("weather logo")
    if weather_logo is not None:
        register(
            "weather logo",
            lambda img=weather_logo: _show_logo(context.display, img),
            available=True,
        )
    register(
        "weather1",
        lambda data=weather_data: draw_weather_screen_1(context.display, data, transition=True),
        available=bool(weather_data),
    )
    register(
        "weather2",
        lambda data=weather_data: draw_weather_screen_2(context.display, data, transition=True),
        available=bool(weather_data),
    )
    register("inside", lambda: draw_inside(context.display, transition=True))

    verano_logo = context.logos.get("verano logo")
    if verano_logo is not None:
        register(
            "verano logo",
            lambda img=verano_logo: _show_logo(context.display, img),
            available=True,
        )
    register("vrnof", lambda: draw_vrnof_screen(context.display, "VRNOF", transition=True))

    travel_state = context.previous_travel_state
    travel_available = False
    if context.travel_requested:
        window = context.travel_window
        window_desc = (
            f"{_format_time(window[0])} – {_format_time(window[1])}" if window else "all day"
        )

        if context.travel_active:
            travel_state = "scheduled"
            travel_available = True
            if context.previous_travel_state != travel_state:
                logging.info("🧭 Travel screen enabled (window %s).", window_desc)
        else:
            travel_state = "outside_window" if window else "inactive"
            if context.previous_travel_state != travel_state:
                if window:
                    logging.info(
                        "🧭 Travel screen skipped—outside active window (%s, now %s).",
                        window_desc,
                        _format_time(context.now.time()),
                    )
                else:
                    logging.info("🧭 Travel screen enabled (no active window configured).")
        register(
            "travel",
            lambda: draw_travel_time_screen(context.display, transition=True),
            available=travel_available,
        )
    else:
        if context.travel_active:
            travel_state = "disabled"
            if context.previous_travel_state != travel_state:
                logging.info("🧭 Travel screen disabled via configuration.")
        else:
            travel_state = "inactive"
    metadata["travel_state"] = travel_state

    def register_logo(screen_id: str):
        image = context.logos.get(screen_id)
        if image is None:
            return
        register(screen_id, lambda img=image: _show_logo(context.display, img), available=True)

    for base_logo in ("bears logo", "nfl logo", "mlb logo", "nba logo"):
        register_logo(base_logo)

    register("bears next", lambda: show_bears_next_game(context.display, transition=True))
    register("NFL Scoreboard", lambda: draw_nfl_scoreboard(context.display, transition=True))
    register("NFL Overview NFC", lambda: draw_nfl_overview_nfc(context.display, transition=True))
    register("NFL Overview AFC", lambda: draw_nfl_overview_afc(context.display, transition=True))
    register("NFL Standings NFC", lambda: draw_nfl_standings_nfc(context.display, transition=True))
    register("NFL Standings AFC", lambda: draw_nfl_standings_afc(context.display, transition=True))

    hawks = context.cache.get("hawks") or {}
    if any(hawks.values()):
        register_logo("hawks logo")
        hawks_next = hawks.get("next")
        hawks_next_home = hawks.get("next_home")
        if _games_match(hawks_next_home, hawks_next):
            hawks_next_home = None
        register(
            "hawks last",
            lambda data=hawks.get("last"): draw_last_hawks_game(
                context.display, data, transition=True
            ),
            available=bool(hawks.get("last")),
        )
        register(
            "hawks live",
            lambda data=hawks.get("live"): draw_live_hawks_game(
                context.display, data, transition=True
            ),
            available=bool(hawks.get("live")),
        )
        register(
            "hawks next",
            lambda data=hawks_next: draw_sports_screen_hawks(
                context.display, data, transition=True
            ),
            available=bool(hawks_next),
        )
        if hawks_next_home:
            register(
                "hawks next home",
                lambda data=hawks_next_home: draw_hawks_next_home_game(
                    context.display, data, transition=True
                ),
                available=True,
            )

        register_logo("nhl logo")
        register("NHL Scoreboard", lambda: draw_nhl_scoreboard(context.display, transition=True))
        register(
            "NHL Standings Overview",
            lambda: draw_nhl_standings_overview(context.display, transition=True),
        )
        register(
            "NHL Standings West",
            lambda: draw_nhl_standings_west(context.display, transition=True),
        )
        register(
            "NHL Standings East",
            lambda: draw_nhl_standings_east(context.display, transition=True),
        )

    cubs = context.cache.get("cubs") or {}
    if any(cubs.values()):
        register_logo("cubs logo")
        cubs_next = cubs.get("next")
        cubs_next_home = cubs.get("next_home")
        if _games_match(cubs_next_home, cubs_next):
            cubs_next_home = None

        register(
            "cubs stand1",
            lambda data=cubs.get("stand"): draw_standings_screen1(
                context.display,
                data,
                os.path.join(context.image_dir, "cubs.jpg"),
                "NL Central",
                transition=True,
            ),
            available=bool(cubs.get("stand")),
        )
        register(
            "cubs stand2",
            lambda data=cubs.get("stand"): draw_standings_screen2(
                context.display,
                data,
                os.path.join(context.image_dir, "cubs.jpg"),
                transition=True,
            ),
            available=bool(cubs.get("stand")),
        )
        register(
            "cubs last",
            lambda data=cubs.get("last"): draw_last_game(
                context.display,
                data,
                "Last Cubs game...",
                transition=True,
            ),
            available=bool(cubs.get("last")),
        )
        register(
            "cubs result",
            lambda data=cubs.get("last"): draw_cubs_result(
                context.display, data, transition=True
            ),
            available=bool(cubs.get("last")),
        )
        register(
            "cubs live",
            lambda data=cubs.get("live"): draw_box_score(
                context.display,
                data,
                "Cubs Live...",
                transition=True,
            ),
            available=bool(cubs.get("live")),
        )
        register(
            "cubs next",
            lambda data=cubs_next: draw_sports_screen(
                context.display,
                data,
                "Next Cubs game...",
                transition=True,
            ),
            available=bool(cubs_next),
        )
        if cubs_next_home:
            register(
                "cubs next home",
                lambda data=cubs_next_home: draw_next_home_game(
                    context.display,
                    data,
                    transition=True,
                ),
                available=True,
            )

    sox = context.cache.get("sox") or {}
    if any(sox.values()):
        register_logo("sox logo")
        sox_next = sox.get("next")
        sox_next_home = sox.get("next_home")
        if _games_match(sox_next_home, sox_next):
            sox_next_home = None

        register(
            "sox stand1",
            lambda data=sox.get("stand"): draw_standings_screen1(
                context.display,
                data,
                os.path.join(context.image_dir, "sox.jpg"),
                "AL Central",
                transition=True,
            ),
            available=bool(sox.get("stand")),
        )
        register(
            "sox stand2",
            lambda data=sox.get("stand"): draw_standings_screen2(
                context.display,
                data,
                os.path.join(context.image_dir, "sox.jpg"),
                transition=True,
            ),
            available=bool(sox.get("stand")),
        )
        register(
            "sox last",
            lambda data=sox.get("last"): draw_last_game(
                context.display,
                data,
                "Last Sox game...",
                transition=True,
            ),
            available=bool(sox.get("last")),
        )
        register(
            "sox live",
            lambda data=sox.get("live"): draw_box_score(
                context.display,
                data,
                "Sox Live...",
                transition=True,
            ),
            available=bool(sox.get("live")),
        )
        register(
            "sox next",
            lambda data=sox_next: draw_sports_screen(
                context.display,
                data,
                "Next Sox game...",
                transition=True,
            ),
            available=bool(sox_next),
        )
        if sox_next_home:
            register(
                "sox next home",
                lambda data=sox_next_home: draw_next_home_game(
                    context.display,
                    data,
                    transition=True,
                ),
                available=True,
            )

    register("MLB Scoreboard", lambda: draw_mlb_scoreboard(context.display, transition=True))
    register("NBA Scoreboard", lambda: draw_nba_scoreboard(context.display, transition=True))

    register("NL Overview", lambda: draw_NL_Overview(context.display, transition=True))
    register("NL East", lambda: draw_NL_East(context.display, transition=True))
    register("NL Central", lambda: draw_NL_Central(context.display, transition=True))
    register("NL West", lambda: draw_NL_West(context.display, transition=True))
    register("NL Wild Card", lambda: draw_NL_WildCard(context.display, transition=True))
    register("AL Overview", lambda: draw_AL_Overview(context.display, transition=True))
    register("AL East", lambda: draw_AL_East(context.display, transition=True))
    register("AL Central", lambda: draw_AL_Central(context.display, transition=True))
    register("AL West", lambda: draw_AL_West(context.display, transition=True))
    register("AL Wild Card", lambda: draw_AL_WildCard(context.display, transition=True))

    bulls = context.cache.get("bulls") or {}
    if any(bulls.values()):
        register_logo("bulls logo")
        bulls_next = bulls.get("next")
        bulls_next_home = bulls.get("next_home")
        if _games_match(bulls_next_home, bulls_next):
            bulls_next_home = None

        register(
            "bulls last",
            lambda data=bulls.get("last"): draw_last_bulls_game(
                context.display, data, transition=True
            ),
            available=bool(bulls.get("last")),
        )
        register(
            "bulls live",
            lambda data=bulls.get("live"): draw_live_bulls_game(
                context.display, data, transition=True
            ),
            available=bool(bulls.get("live")),
        )
        register(
            "bulls next",
            lambda data=bulls_next: draw_sports_screen_bulls(
                context.display, data, transition=True
            ),
            available=bool(bulls_next),
        )
        if bulls_next_home:
            register(
                "bulls next home",
                lambda data=bulls_next_home: draw_bulls_next_home_game(
                    context.display, data, transition=True
                ),
                available=True,
            )

    return registry, metadata

