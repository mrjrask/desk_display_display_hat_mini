#!/usr/bin/env python3
"""
data_fetch.py

All remote data fetchers for weather, Blackhawks, MLB, etc.,
with resilient retries via a shared requests.Session.
"""

import datetime
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import pytz
import requests

from services.http_client import NHL_HEADERS, get_session
from screens.nba_scoreboard import _fetch_games_for_date as _nba_fetch_games_for_date

from config import (
    OWM_API_KEY,
    ONE_CALL_URL,
    LATITUDE,
    LONGITUDE,
    NHL_API_URL,
    NHL_TEAM_ID,
    MLB_API_URL,
    MLB_CUBS_TEAM_ID,
    MLB_SOX_TEAM_ID,
    CENTRAL_TIME,
    OPEN_METEO_URL,
    OPEN_METEO_PARAMS,
    NBA_TEAM_ID,
    NBA_TEAM_TRICODE,
    AHL_API_BASE_URL,
    AHL_API_KEY,
    AHL_CLIENT_CODE,
    AHL_LEAGUE_ID,
    AHL_SCHEDULE_ICS_URL,
    AHL_SEASON_ID,
    AHL_SITE_ID,
    AHL_TEAM_ID,
    AHL_TEAM_NAME,
    AHL_TEAM_TRICODE,
)

# ─── Shared HTTP session ─────────────────────────────────────────────────────
_session = get_session()

# Track last time we received a 429 from OWM
_last_owm_429 = None

# -----------------------------------------------------------------------------
# WEATHER
# -----------------------------------------------------------------------------
def fetch_weather():
    """
    Fetch weather from OpenWeatherMap OneCall, falling back to Open-Meteo on errors
    or if recently rate-limited.
    """
    global _last_owm_429
    now = datetime.datetime.now()
    if not OWM_API_KEY:
        logging.warning("OpenWeatherMap API key missing; using fallback provider")
        return fetch_weather_fallback()
    # If we got a 429 within the last 2 hours, skip OWM and fallback
    if _last_owm_429 and (now - _last_owm_429) < datetime.timedelta(hours=2):
        logging.warning("Skipping OpenWeatherMap due to recent 429; using fallback")
        return fetch_weather_fallback()

    try:
        params = {
            "lat": LATITUDE,
            "lon": LONGITUDE,
            "appid": OWM_API_KEY,
            "units": "imperial",
        }
        r = _session.get(ONE_CALL_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    except requests.exceptions.HTTPError as http_err:
        if r.status_code == 429:
            logging.warning("HTTP 429 from OWM; falling back and pausing OWM for 2h")
            _last_owm_429 = datetime.datetime.now()
            return fetch_weather_fallback()
        logging.error("HTTP error fetching weather: %s", http_err)
        return None

    except Exception as e:
        logging.error("Error fetching weather: %s", e)
        return None


def fetch_weather_fallback():
    """
    Fallback using Open-Meteo API for weather data.
    """
    try:
        r = _session.get(OPEN_METEO_URL, params=OPEN_METEO_PARAMS, timeout=10)
        r.raise_for_status()
        data = r.json()
        logging.debug("Weather data (Open-Meteo): %s", data)

        current = data.get("current_weather", {})
        daily   = data.get("daily", {})

        mapped = {
            "current": {
                "temp":        current.get("temperature"),
                "feels_like":  current.get("temperature"),
                "weather": [{
                    "description": weather_code_to_description(
                        current.get("weathercode", -1)
                    )
                }],
                "wind_speed":  current.get("windspeed"),
                "wind_deg":    current.get("winddirection"),
                "humidity":    (daily.get("relativehumidity_2m") or [0])[0],
                "pressure":    (daily.get("surface_pressure")   or [0])[0],
                "uvi":         0,
                "sunrise":     (daily.get("sunrise")  or [None])[0],
                "sunset":      (daily.get("sunset")   or [None])[0],
            },
            "daily": [{
                "temp": {
                    "max": (daily.get("temperature_2m_max") or [None])[0],
                    "min": (daily.get("temperature_2m_min") or [None])[0],
                },
                "sunrise": (daily.get("sunrise") or [None])[0],
                "sunset":  (daily.get("sunset")  or [None])[0],
            }],
        }
        return mapped

    except Exception as e:
        logging.error("Error fetching fallback weather: %s", e)
        return None


def weather_code_to_description(code):
    mapping = {
        0:  "Clear sky",     1: "Mainly clear",  2: "Partly cloudy", 3: "Overcast",
        45: "Fog",           48: "Rime fog",     51: "Light drizzle", 53: "Mod. drizzle",
        55: "Dense drizzle", 61: "Slight rain",  63: "Mod. rain",     65: "Heavy rain",
        80: "Rain showers",  81: "Mod. showers", 82: "Violent showers",
        95: "Thunderstorm",  96: "Thunder w/ hail", 99: "Thunder w/ hail"
    }
    return mapping.get(code, f"Code {code}")


# -----------------------------------------------------------------------------
# NHL — Blackhawks
# -----------------------------------------------------------------------------
def fetch_blackhawks_next_game():
    try:
        r = _session.get(NHL_API_URL, timeout=10, headers=NHL_HEADERS)
        r.raise_for_status()
        games = r.json().get("games", [])
        fut   = [g for g in games if g.get("gameState") == "FUT"]

        for g in fut:
            if not g.get("startTimeCentral"):
                utc = g.get("startTimeUTC")
                if utc:
                    dt = datetime.datetime.strptime(utc, "%Y-%m-%dT%H:%M:%SZ")
                    dt = dt.replace(tzinfo=pytz.utc).astimezone(CENTRAL_TIME)
                    g["startTimeCentral"] = dt.strftime("%I:%M %p").lstrip("0")
                else:
                    g["startTimeCentral"] = "TBD"

        fut.sort(key=lambda g: g.get("gameDate", ""))
        return fut[0] if fut else None

    except Exception as e:
        logging.error("Error fetching next Blackhawks game: %s", e)
        return None


def _extract_team_value(team, *keys):
    """Return the first string value found for the provided keys."""
    if not isinstance(team, dict):
        return ""
    for key in keys:
        value = team.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for subkey in ("default", "en", "fullName"):
                subval = value.get(subkey)
                if isinstance(subval, str) and subval.strip():
                    return subval.strip()
    return ""


def _is_blackhawks_team(team):
    if not isinstance(team, dict):
        return False
    if isinstance(team.get("team"), dict):
        team = team["team"]
    team_id = team.get("id") or team.get("teamId")
    if team_id == NHL_TEAM_ID:
        return True
    name = _extract_team_value(team, "commonName", "name", "teamName", "clubName")
    return "blackhawks" in name.lower() if name else False


def _team_id(team):
    if not isinstance(team, dict):
        return None
    if isinstance(team.get("team"), dict):
        return _team_id(team["team"])
    return team.get("id") or team.get("teamId")


def _same_game(a, b):
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    for key in ("id", "gamePk", "gameId", "gameUUID"):
        av = a.get(key)
        bv = b.get(key)
        if av and bv and av == bv:
            return True
    a_date = a.get("gameDate")
    b_date = b.get("gameDate")
    if a_date and b_date and a_date == b_date:
        a_home = _team_id(a.get("homeTeam") or a.get("home_team") or {})
        b_home = _team_id(b.get("homeTeam") or b.get("home_team") or {})
        a_away = _team_id(a.get("awayTeam") or a.get("away_team") or {})
        b_away = _team_id(b.get("awayTeam") or b.get("away_team") or {})
        return a_home == b_home and a_away == b_away
    return False


# -----------------------------------------------------------------------------
# NBA — Chicago Bulls
# -----------------------------------------------------------------------------
_BULLS_TEAM_ID = str(NBA_TEAM_ID)
_BULLS_TRICODE = (NBA_TEAM_TRICODE or "CHI").upper()
_NBA_LOOKBACK_DAYS = 7
_NBA_LOOKAHEAD_DAYS = 30


def _parse_nba_datetime(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            parsed = datetime.datetime.strptime(text, fmt)
        except Exception:
            continue
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(CENTRAL_TIME)
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(CENTRAL_TIME)


def _copy_nba_team(entry):
    if not isinstance(entry, dict):
        return {}
    cloned = dict(entry)
    team_info = cloned.get("team")
    if isinstance(team_info, dict):
        cloned["team"] = dict(team_info)
    return cloned


def _augment_nba_game(game):
    if not isinstance(game, dict):
        return None
    cloned = dict(game)
    teams = cloned.get("teams")
    if isinstance(teams, dict):
        cloned_teams = {}
        for side in ("home", "away"):
            cloned_teams[side] = _copy_nba_team(teams.get(side) or {})
        cloned["teams"] = cloned_teams
    start_local = cloned.get("_start_local")
    if not isinstance(start_local, datetime.datetime):
        start_local = _parse_nba_datetime(cloned.get("gameDate"))
    if isinstance(start_local, datetime.datetime):
        cloned["_start_local"] = start_local
        cloned["officialDate"] = start_local.date().isoformat()
    else:
        date_text = (cloned.get("officialDate") or cloned.get("gameDate") or "").strip()
        cloned["officialDate"] = date_text[:10]
    return cloned


def _is_bulls_team(entry):
    if not isinstance(entry, dict):
        return False
    team_info = entry.get("team") if isinstance(entry.get("team"), dict) else entry
    team_id = str(team_info.get("id") or team_info.get("teamId") or "")
    if team_id and team_id == _BULLS_TEAM_ID:
        return True
    tri = str(team_info.get("triCode") or team_info.get("abbreviation") or "").upper()
    return tri == _BULLS_TRICODE if tri else False


def _is_bulls_game(game):
    if not isinstance(game, dict):
        return False
    teams = game.get("teams") or {}
    return _is_bulls_team(teams.get("home")) or _is_bulls_team(teams.get("away"))


def _nba_game_state(game):
    status = game.get("status") or {}
    abstract = str(status.get("abstractGameState") or "").lower()
    if abstract:
        return abstract
    detailed = str(status.get("detailedState") or "").lower()
    if "final" in detailed:
        return "final"
    if "live" in detailed or "progress" in detailed:
        return "live"
    if "preview" in detailed or "schedule" in detailed or "pregame" in detailed:
        return "preview"
    code = str(status.get("statusCode") or "")
    if code == "3":
        return "final"
    if code == "2":
        return "live"
    if code == "1":
        return "preview"
    return detailed


def _get_bulls_games_for_day(day):
    try:
        games = _nba_fetch_games_for_date(day)
    except Exception as exc:
        logging.error("Failed to fetch NBA scoreboard for %s: %s", day, exc)
        return []
    results = []
    for game in games or []:
        if not _is_bulls_game(game):
            continue
        augmented = _augment_nba_game(game)
        if augmented:
            results.append(augmented)
    return results


def _future_bulls_games(days_forward):
    today = datetime.datetime.now(CENTRAL_TIME).date()
    for delta in range(0, days_forward + 1):
        day = today + datetime.timedelta(days=delta)
        for game in _get_bulls_games_for_day(day):
            yield game


def _past_bulls_games(days_back):
    today = datetime.datetime.now(CENTRAL_TIME).date()
    for delta in range(0, days_back + 1):
        day = today - datetime.timedelta(days=delta)
        games = _get_bulls_games_for_day(day)
        for game in reversed(games):
            yield game


def fetch_bulls_next_game():
    try:
        for game in _future_bulls_games(_NBA_LOOKAHEAD_DAYS):
            if _nba_game_state(game) in {"preview", "scheduled", "pregame"}:
                return game
    except Exception as exc:
        logging.error("Error fetching next Bulls game: %s", exc)
    return None


def fetch_bulls_next_home_game():
    try:
        fallback_game = None
        for game in _future_bulls_games(_NBA_LOOKAHEAD_DAYS):
            teams = game.get("teams") or {}
            if not _is_bulls_team(teams.get("home")):
                continue

            state = _nba_game_state(game)
            if state in {"preview", "scheduled", "pregame"}:
                return game
            if fallback_game is None and state not in {"final", "postponed"}:
                fallback_game = game
        return fallback_game
    except Exception as exc:
        logging.error("Error fetching next Bulls home game: %s", exc)
    return None


def fetch_bulls_last_game():
    try:
        for game in _past_bulls_games(_NBA_LOOKBACK_DAYS):
            if _nba_game_state(game) == "final":
                return game
    except Exception as exc:
        logging.error("Error fetching last Bulls game: %s", exc)
    return None


def fetch_bulls_live_game():
    try:
        for game in _future_bulls_games(0):
            if _nba_game_state(game) == "live":
                return game
        for game in _past_bulls_games(1):
            if _nba_game_state(game) == "live":
                return game
    except Exception as exc:
        logging.error("Error fetching live Bulls game: %s", exc)
    return None


def fetch_blackhawks_next_home_game():
    try:
        next_game = fetch_blackhawks_next_game()
        r = _session.get(NHL_API_URL, timeout=10, headers=NHL_HEADERS)
        r.raise_for_status()
        games = r.json().get("games", [])
        home  = []
        skipped_duplicate = False

        for g in games:
            if g.get("gameState") != "FUT":
                continue
            team = g.get("homeTeam", {}) or g.get("home_team", {})
            if _is_blackhawks_team(team):
                if next_game and _same_game(next_game, g):
                    skipped_duplicate = True
                    continue
                utc = g.get("startTimeUTC")
                if utc:
                    dt = datetime.datetime.strptime(utc, "%Y-%m-%dT%H:%M:%SZ")
                    dt = dt.replace(tzinfo=pytz.utc).astimezone(CENTRAL_TIME)
                    g["startTimeCentral"] = dt.strftime("%I:%M %p").lstrip("0")
                else:
                    g["startTimeCentral"] = "TBD"
                home.append(g)

        home.sort(key=lambda g: g.get("gameDate", ""))
        if not home:
            if skipped_duplicate:
                logging.info(
                    "Next home Blackhawks game matches the next scheduled game; suppressing duplicate screen."
                )
            else:
                logging.info("No upcoming additional Blackhawks home games were found.")
        return home[0] if home else None

    except Exception as e:
        logging.error("Error fetching next home Blackhawks game: %s", e)
        return None


def fetch_blackhawks_last_game():
    try:
        r = _session.get(NHL_API_URL, timeout=10, headers=NHL_HEADERS)
        r.raise_for_status()
        data  = r.json()
        games = []

        if "dates" in data:
            for di in data["dates"]:
                games.extend(di.get("games", []))
        else:
            games = data.get("games", [])

        offs = [g for g in games if g.get("gameState") == "OFF"]
        if offs:
            offs.sort(key=lambda g: g.get("gameDate", ""))
            return offs[-1]
        return None

    except Exception as e:
        logging.error("Error fetching last Blackhawks game: %s", e)
        return None


def fetch_blackhawks_live_game():
    try:
        r = _session.get(NHL_API_URL, timeout=10, headers=NHL_HEADERS)
        r.raise_for_status()
        games = r.json().get("games", [])
        for g in games:
            state = g.get("gameState", "").lower()
            if state in ("live", "in progress"):
                if not g.get("startTimeCentral"):
                    utc = g.get("startTimeUTC")
                    if utc:
                        dt = datetime.datetime.strptime(utc, "%Y-%m-%dT%H:%M:%SZ")
                        dt = dt.replace(tzinfo=pytz.utc).astimezone(CENTRAL_TIME)
                        g["startTimeCentral"] = dt.strftime("%I:%M %p").lstrip("0")
                    else:
                        g["startTimeCentral"] = "TBD"
                return g
        return None

    except Exception as e:
        logging.error("Error fetching live Blackhawks game: %s", e)
        return None


# -----------------------------------------------------------------------------
# MLB — schedule helper + Cubs/Sox wrappers
# -----------------------------------------------------------------------------
def _fetch_mlb_schedule(team_id):
    try:
        today = datetime.datetime.now(CENTRAL_TIME).date()
        start = today - datetime.timedelta(days=3)
        end   = today + datetime.timedelta(days=30)

        url = (
            f"{MLB_API_URL}"
            f"?sportId=1&teamId={team_id}"
            f"&startDate={start}&endDate={end}&hydrate=team,linescore"
        )
        r = _session.get(url, timeout=10)
        r.raise_for_status()
        data   = r.json()
        result = {
            "next_game": None,
            "next_home_game": None,
            "live_game": None,
            "last_game": None,
        }
        finished = []
        home_candidates = []
        skipped_home_duplicate = False
        team_id_int = int(team_id)

        for di in data.get("dates", []):
            day = datetime.datetime.strptime(di["date"], "%Y-%m-%d").date()
            for g in di.get("games", []):
                # Convert UTC to Central
                utc = g.get("gameDate")
                local_dt = None
                if utc:
                    dt = datetime.datetime.strptime(utc, "%Y-%m-%dT%H:%M:%SZ")
                    dt = dt.replace(tzinfo=pytz.utc).astimezone(CENTRAL_TIME)
                    g["startTimeCentral"] = dt.strftime("%I:%M %p").lstrip("0")
                    local_dt = dt
                else:
                    g["startTimeCentral"] = "TBD"
                    try:
                        local_dt = CENTRAL_TIME.localize(
                            datetime.datetime.combine(day, datetime.time(12, 0))
                        )
                    except Exception:
                        local_dt = None

                # Determine game state
                status      = g.get("status", {})
                code        = status.get("statusCode", "").upper()
                abstract    = status.get("abstractGameState", "").lower()
                detailed    = status.get("detailedState", "").lower()

                # Track upcoming home games for dedicated screen
                home_team_id = (
                    ((g.get("teams") or {}).get("home") or {}).get("team", {})
                ).get("id")
                is_home_game = False
                try:
                    is_home_game = int(home_team_id) == team_id_int
                except Exception:
                    is_home_game = False

                if is_home_game and local_dt and local_dt.date() >= today:
                    is_scheduled = code in {"S", "I"} or abstract in {
                        "preview",
                        "scheduled",
                        "live",
                    } or "progress" in detailed
                    is_postponed = any(
                        kw in detailed for kw in ("postponed", "suspended")
                    )
                    if is_scheduled and not is_postponed:
                        home_candidates.append((local_dt, g))

                # Live game
                if code == "I" or abstract == "live" or "progress" in detailed:
                    result["live_game"] = g

                # Next game (today scheduled)
                if day == today and (code == "S" or abstract in ("preview","scheduled")):
                    result["next_game"] = g

                # Finished up to today
                if day <= today and code not in ("S","I") and abstract not in ("preview","scheduled","live"):
                    finished.append(g)

        # Fallback next future
        if not result["next_game"]:
            for di in data.get("dates", []):
                day = datetime.datetime.strptime(di["date"], "%Y-%m-%d").date()
                if day > today:
                    for g in di.get("games", []):
                        status   = g.get("status", {})
                        code2    = status.get("statusCode", "").upper()
                        abs2     = status.get("abstractGameState", "").lower()
                        if code2 == "S" or abs2 in ("preview","scheduled"):
                            result["next_game"] = g
                            break
                    if result["next_game"]:
                        break

        # Pick earliest upcoming home game
        if home_candidates:
            home_candidates.sort(key=lambda item: item[0])

            next_game_pk = None
            if result["next_game"]:
                next_game_pk = result["next_game"].get("gamePk")

            for _, home_game in home_candidates:
                # If the upcoming game is already a home game, skip duplicating it
                if next_game_pk and home_game.get("gamePk") == next_game_pk:
                    skipped_home_duplicate = True
                    continue
                if (
                    result["next_game"]
                    and home_game.get("gameDate") == result["next_game"].get("gameDate")
                ):
                    skipped_home_duplicate = True
                    continue

                result["next_home_game"] = home_game
                break

        if not result["next_home_game"] and skipped_home_duplicate:
            logging.info(
                "Next MLB home game for team %s matches the upcoming game; suppressing duplicate home screen.",
                team_id,
            )

        # Pick last finished
        if finished:
            finished.sort(key=lambda x: x.get("officialDate",""))
            result["last_game"] = finished[-1]

        return result

    except Exception as e:
        logging.error("Error fetching MLB schedule for %s: %s", team_id, e)
        return {
            "next_game": None,
            "next_home_game": None,
            "live_game": None,
            "last_game": None,
        }


def fetch_cubs_games():
    return _fetch_mlb_schedule(MLB_CUBS_TEAM_ID)


def fetch_sox_games():
    return _fetch_mlb_schedule(MLB_SOX_TEAM_ID)


# -----------------------------------------------------------------------------
# MLB — standings helper + Cubs/Sox wrappers
# -----------------------------------------------------------------------------
def _fetch_mlb_standings(league_id, division_id, team_id):
    try:
        url = (
            "https://statsapi.mlb.com/api/v1/standings"
            f"?season=2025&leagueId={league_id}&divisionId={division_id}"
        )
        r = _session.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        for rec in data.get("records", []):
            for tr in rec.get("teamRecords", []):
                if tr.get("team", {}).get("id") == int(team_id):
                    return tr

        logging.warning("Team %s not found in standings (L%d/D%d)", team_id, league_id, division_id)
        return None

    except Exception as e:
        logging.error("Error fetching standings for team %s: %s", team_id, e)
        return None


def fetch_cubs_standings():
    return _fetch_mlb_standings(104, 205, MLB_CUBS_TEAM_ID)


def fetch_sox_standings():
    return _fetch_mlb_standings(103, 202, MLB_SOX_TEAM_ID)


# -----------------------------------------------------------------------------
# AHL — Chicago Wolves schedule + scores (HockeyTech / AHL stats feed)
# -----------------------------------------------------------------------------
_AHL_SEASON_CACHE: Optional[str] = None
_AHL_DEFAULT_BASE = "https://lscluster.hockeytech.com/feed/index.php"


def _ahl_endpoint() -> str:
    base = (AHL_API_BASE_URL or "").strip()
    if not base:
        return _AHL_DEFAULT_BASE

    if not base.startswith(("http://", "https://")):
        base = f"https://{base.lstrip('/')}"

    if "?" in base or base.endswith(".php"):
        return base

    trimmed = base.rstrip("/")
    if trimmed.endswith("/feed"):
        return f"{trimmed}/index.php"
    return f"{trimmed}/index.php"


def _sanitize_ahl_payload(raw_text: str) -> str:
    """Remove common HockeyTech JSON padding and whitespace guards."""
    if not isinstance(raw_text, str):
        return ""

    cleaned = raw_text.lstrip("\ufeff\r\n\t ")

    # Some HockeyTech responses start with "while(1);" or similar guards.
    guards = ("while(1);", "while(1){", "while(1){;", "while(1) {", "while(1) { }")
    for guard in guards:
        if cleaned.startswith(guard):
            cleaned = cleaned[len(guard) :].lstrip(";\r\n\t ")
            cleaned = cleaned.lstrip("\ufeff")
            break

    if cleaned.startswith("/*"):
        end = cleaned.find("*/")
        if end != -1:
            cleaned = cleaned[end + 2 :].lstrip()

    return cleaned


def _ahl_request(view: str, *, feed: str = "statviewfeed", **extra_params):
    params: Dict[str, object] = {
        "feed": feed,
        "view": view,
        "client_code": AHL_CLIENT_CODE,
        "site_id": AHL_SITE_ID,
        "league_id": AHL_LEAGUE_ID,
        "format": "json",
        "lang": "en",
    }
    for key, value in extra_params.items():
        if value is not None:
            params[key] = value

    use_key = bool(AHL_API_KEY)
    no_key_attempted = False
    if not use_key:
        logging.warning("AHL API key missing; attempting request without authentication")

    endpoint = _ahl_endpoint()

    headers = {
        "User-Agent": "desk-display/1.0",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://theahl.com/stats/",
        "X-Requested-With": "XMLHttpRequest",
    }
    while True:
        attempt_params = dict(params)
        if use_key:
            attempt_params["key"] = AHL_API_KEY
        else:
            if not no_key_attempted:
                no_key_attempted = True

        try:
            resp = _session.get(endpoint, params=attempt_params, headers=headers, timeout=10)
            resp.raise_for_status()
            payload = _sanitize_ahl_payload(resp.text)
            if not payload:
                logging.error(
                    "Empty response when fetching AHL %s data (status %s)",
                    view,
                    resp.status_code,
                )
                return None
            try:
                return json.loads(payload)
            except json.JSONDecodeError:  # pragma: no cover - depends on upstream
                snippet = payload[:200].replace("\n", " ").replace("\r", " ")
                snippet_lower = snippet.lower()
                if "invalid key" in snippet_lower:
                    if use_key and not no_key_attempted:
                        logging.info(
                            "AHL API rejected the configured key for %s; retrying without a key",
                            view,
                        )
                        use_key = False
                        continue
                    logging.debug(
                        "AHL feed for %s responded with 'Invalid key' (feed=%s); skipping",
                        view,
                        feed,
                    )
                    return None
                logging.error(
                    "Error parsing AHL %s data (status %s, content-type %s): %s",  # noqa: B950
                    view,
                    resp.status_code,
                    resp.headers.get("content-type"),
                    snippet,
                )
                logging.debug("Full AHL %s payload: %s", view, payload)
                return None
        except Exception as exc:
            logging.error("Error fetching AHL %s data: %s", view, exc)
            return None


def _dict_rows(value) -> List[Dict]:
    rows: List[Dict] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                rows.append(item)
    elif isinstance(value, dict):
        inner = value.get("rows") or value.get("data") or value.get("schedule")
        if isinstance(inner, list):
            for item in inner:
                if isinstance(item, dict):
                    rows.append(item)
        elif isinstance(inner, dict):
            maybe_rows = inner.get("rows")
            if isinstance(maybe_rows, list):
                for item in maybe_rows:
                    if isinstance(item, dict):
                        rows.append(item)
    return rows


def _rows_from_table(table: Dict) -> List[Dict]:
    columns: List[str] = []
    for col in table.get("columns", []):
        if isinstance(col, dict):
            name = col.get("name") or col.get("field") or col.get("key")
            if name:
                columns.append(str(name))
        elif isinstance(col, str):
            columns.append(col)

    rows: List[Dict] = []
    for raw_row in table.get("rows", []):
        if isinstance(raw_row, dict):
            rows.append(raw_row)
            continue
        if not isinstance(raw_row, list):
            continue
        entry: Dict[str, object] = {}
        for idx, value in enumerate(raw_row):
            if idx < len(columns):
                entry[columns[idx]] = value
        if entry:
            rows.append(entry)
    return rows


def _extract_rows(payload: Optional[Dict], *keys: str) -> List[Dict]:
    rows: List[Dict] = []
    if not isinstance(payload, dict):
        return rows

    site = payload.get("SiteKit") or payload
    for key in keys:
        block = site.get(key)
        rows.extend(_dict_rows(block))
        if isinstance(block, dict):
            table = block.get("table")
            if isinstance(table, dict):
                rows.extend(_rows_from_table(table))

    if not rows:
        rows.extend(_dict_rows(site))
        table = site.get("table") if isinstance(site, dict) else None
        if isinstance(table, dict):
            rows.extend(_rows_from_table(table))

    return rows


def _current_ahl_season_id() -> Optional[str]:
    if AHL_SEASON_ID:
        return str(AHL_SEASON_ID)

    global _AHL_SEASON_CACHE
    if _AHL_SEASON_CACHE:
        return _AHL_SEASON_CACHE

    data = _ahl_request("season")
    rows = _extract_rows(data, "Seasons", "Season")
    if not rows:
        alt = _ahl_request("season", feed="modulekit")
        rows = _extract_rows(alt, "Seasons", "Season")
    for row in rows:
        flag = row.get("is_current") or row.get("isCurrent") or row.get("current")
        if str(flag).lower() in {"1", "true", "yes"}:
            season_id = row.get("season_id") or row.get("seasonId") or row.get("id")
            if season_id:
                _AHL_SEASON_CACHE = str(season_id)
                return _AHL_SEASON_CACHE

    if rows:
        season_id = rows[0].get("season_id") or rows[0].get("seasonId") or rows[0].get("id")
        if season_id:
            _AHL_SEASON_CACHE = str(season_id)
            return _AHL_SEASON_CACHE

    logging.warning("Unable to determine current AHL season id from feed")
    return None


def _first_value(entry: Dict, *keys: str):
    for key in keys:
        if not key:
            continue
        if key in entry and entry[key] not in (None, ""):
            return entry[key]
    return None


def _extract_team_info(row: Dict, prefix: str) -> Optional[Dict]:
    base = (
        row.get(f"{prefix}_team")
        or row.get(f"{prefix}Team")
        or row.get(prefix)
        or {}
    )
    if not isinstance(base, dict):
        base = {}

    def _get(*candidates):
        for cand in candidates:
            val = base.get(cand)
            if val not in (None, ""):
                return val
        return None

    team_id = _first_value(
        {**row, **base},
        f"{prefix}_team_id",
        f"{prefix}_teamid",
        f"{prefix}TeamID",
        "team_id",
        "teamId",
        "id",
    )
    name = _get("name", "fullName") or row.get(f"{prefix}_team_name")
    city = row.get(f"{prefix}_city") or base.get("city")
    nickname = (
        row.get(f"{prefix}_nickname")
        or row.get(f"{prefix}_short_name")
        or base.get("nickname")
        or base.get("shortname")
    )
    if not name:
        if city and nickname:
            name = f"{city} {nickname}".strip()
        elif nickname:
            name = nickname
        elif city:
            name = city

    abbr = (
        row.get(f"{prefix}_code")
        or row.get(f"{prefix}_abbr")
        or row.get(f"{prefix}_abbrev")
        or row.get(f"{prefix}_short")
        or base.get("abbrev")
        or base.get("code")
    )
    if isinstance(abbr, str):
        abbr = abbr.upper()

    score = _first_value({**row, **base}, f"{prefix}_score", "score")
    shots = _first_value(
        {**row, **base},
        f"{prefix}_shots",
        f"{prefix}_sog",
        f"{prefix}Shots",
        "shots",
    )

    def _as_int(value):
        try:
            if value in (None, ""):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    if not (name or abbr):
        return None

    return {
        "id": team_id,
        "name": name,
        "abbr": (abbr or "").upper() or None,
        "nickname": nickname,
        "score": _as_int(score),
        "shots": _as_int(shots),
    }


def _parse_datetime_candidates(row: Dict) -> Optional[datetime.datetime]:
    candidates = [
        row.get("game_date_time"),
        row.get("game_date_time_local"),
        row.get("game_date_time_utc"),
        row.get("game_date_utc"),
        row.get("game_time_utc"),
        row.get("gameTimeUTC"),
        row.get("gameDate"),
    ]
    for text in candidates:
        if not isinstance(text, str):
            continue
        cleaned = text.strip()
        if not cleaned:
            continue
        try:
            if cleaned.endswith("Z"):
                cleaned = cleaned[:-1] + "+00:00"
            if len(cleaned) > 5 and cleaned[-3] != ":" and cleaned[-5] in "+-":
                cleaned = f"{cleaned[:-2]}:{cleaned[-2:]}"
            dt_obj = datetime.datetime.fromisoformat(cleaned)
            if dt_obj.tzinfo is None:
                return pytz.UTC.localize(dt_obj)
            return dt_obj
        except Exception:
            pass

    date_only = row.get("game_date") or row.get("date")
    time_only = row.get("game_time") or row.get("time")
    if isinstance(date_only, str) and isinstance(time_only, str):
        for fmt in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M"):
            try:
                naive = datetime.datetime.strptime(f"{date_only} {time_only}", fmt)
                return CENTRAL_TIME.localize(naive)
            except Exception:
                continue
    if isinstance(date_only, str):
        try:
            naive = datetime.datetime.strptime(date_only, "%Y-%m-%d")
            return CENTRAL_TIME.localize(naive)
        except Exception:
            return None
    return None


def _normalize_status(raw_status: Optional[str]) -> str:
    if not raw_status:
        return "FUT"
    text = str(raw_status).strip().upper()
    if not text:
        return "FUT"
    if "FINAL" in text or text.startswith("F"):
        return "FINAL"
    if any(token in text for token in ("LIVE", "IN PROGRESS", "INPROGRESS", "CRIT")):
        return "LIVE"
    if any(token in text for token in ("PREGAME", "SCHEDULED", "FUT", "PRE")):
        return "FUT"
    return text


def _format_local_time(dt_obj: datetime.datetime) -> str:
    fmt = "%-I:%M %p" if os.name != "nt" else "%#I:%M %p"
    try:
        return dt_obj.strftime(fmt).lstrip("0")
    except Exception:
        return dt_obj.strftime("%I:%M %p").lstrip("0")


def _normalize_ahl_game(row: Dict) -> Optional[Dict]:
    home = _extract_team_info(row, "home")
    away = _extract_team_info(row, "away")
    start = _parse_datetime_candidates(row)
    if not home or not away or not start:
        return None

    state = _normalize_status(row.get("game_status") or row.get("status"))
    detail = str(row.get("game_status") or row.get("status_detail") or row.get("result") or state).strip()
    period = row.get("period_desc") or row.get("period") or row.get("periodName")
    clock = row.get("period_time") or row.get("time_remaining") or row.get("clock")
    note = row.get("status_note") or row.get("note")
    venue = row.get("venue") or row.get("venue_name")
    game_id = (
        row.get("game_id")
        or row.get("gameId")
        or row.get("id")
        or row.get("gameUuid")
    )

    start_utc = start.astimezone(pytz.UTC)
    central = start.astimezone(CENTRAL_TIME)
    official_date = start.date().isoformat()

    return {
        "game_id": str(game_id) if game_id else None,
        "home": home,
        "away": away,
        "start": start,
        "start_utc": start_utc,
        "start_iso": start_utc.isoformat(),
        "start_time_central": _format_local_time(central),
        "official_date": official_date,
        "status": {
            "state": state,
            "detail": detail,
            "period": period,
            "clock": clock,
            "note": note,
        },
        "venue": venue,
        "is_home": str(home.get("id")) == str(AHL_TEAM_ID),
    }


def _fetch_ahl_schedule() -> List[Dict]:
    def _fetch_rows(season_id: Optional[str]) -> List[Dict]:
        params: Dict[str, Optional[str]] = {"team_id": AHL_TEAM_ID}
        if season_id:
            params["season_id"] = season_id
        data = _ahl_request("schedule", **params)
        rows = _extract_rows(data, "Schedule", "TeamSchedule")
        if not rows:
            alt = _ahl_request("schedule", feed="modulekit", **params)
            rows = _extract_rows(alt, "Schedule", "TeamSchedule")
        return rows

    rows: List[Dict] = []

    if AHL_SEASON_ID:
        rows = _fetch_rows(str(AHL_SEASON_ID))

    if not rows:
        rows = _fetch_rows(None)

    if not rows:
        season_id = _current_ahl_season_id()
        if season_id:
            rows = _fetch_rows(season_id)

    if not rows:
        return []

    games: List[Dict] = []
    for row in rows:
        normalized = _normalize_ahl_game(row)
        if normalized:
            games.append(normalized)
    games.sort(key=lambda g: g.get("start_utc"))
    return games


def _classify_wolves_games(games: List[Dict]) -> Dict[str, Optional[Dict]]:
    now = datetime.datetime.now(pytz.UTC)
    last_final: Optional[Dict] = None
    live_game: Optional[Dict] = None
    upcoming: List[Dict] = []

    for game in games:
        start = game.get("start_utc") or now
        state = (game.get("status") or {}).get("state", "").upper()
        if state.startswith("FIN"):
            if not last_final or start > last_final.get("start_utc", start):
                last_final = game
            continue
        if state in {"LIVE", "CRIT", "IN PROGRESS", "INPROGRESS"}:
            if live_game is None or start < live_game.get("start_utc", start):
                live_game = game
            continue
        if start >= now:
            upcoming.append(game)
        elif not last_final or start > last_final.get("start_utc", start):
            last_final = game

    upcoming.sort(key=lambda g: g.get("start_utc"))
    next_game = upcoming[0] if upcoming else None
    next_home = None
    for game in upcoming:
        if game.get("is_home"):
            next_home = game
            break

    return {
        "last_game": last_final,
        "live_game": live_game,
        "next_game": next_game,
        "next_home_game": next_home,
    }


def _wolves_schedule_url() -> Optional[str]:
    url = (AHL_SCHEDULE_ICS_URL or "").strip()
    if not url:
        return None
    if url.startswith("webcal://"):
        return "https://" + url[len("webcal://") :].lstrip("/")
    return url


def _unfold_ics_lines(text: str) -> List[str]:
    lines: List[str] = []
    buffer: List[str] = []
    for raw_line in text.splitlines():
        if raw_line.startswith((" ", "\t")) and buffer:
            buffer[-1] += raw_line[1:]
        else:
            buffer.append(raw_line.rstrip())
    lines.extend(buffer)
    return lines


def _parse_ics_events(text: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    params: Dict[str, Dict[str, str]] = {}
    for line in _unfold_ics_lines(text):
        if not line:
            continue
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            current = {}
            params = {}
            continue
        if upper == "END:VEVENT":
            if current:
                if params:
                    current["__params__"] = params
                events.append(current)
            current = {}
            params = {}
            continue
        if ":" not in line:
            continue
        key_part, value = line.split(":", 1)
        key_bits = key_part.split(";")
        key = key_bits[0].upper()
        param_map: Dict[str, str] = {}
        for bit in key_bits[1:]:
            if "=" in bit:
                p_key, p_val = bit.split("=", 1)
                param_map[p_key.upper()] = p_val
        if param_map:
            params[key] = param_map
        current[key] = value
    return events


def _parse_ics_datetime(value: Optional[str], meta: Dict[str, str]) -> Optional[datetime.datetime]:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    tzid = meta.get("TZID") if isinstance(meta, dict) else None
    val_type = (meta.get("VALUE") or "").upper() if isinstance(meta, dict) else ""
    fmts = ["%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%dT%H%M"]
    if val_type == "DATE" or ("T" not in text and len(text) == 8):
        fmts = ["%Y%m%d"]
    last_error: Optional[Exception] = None
    for fmt in fmts:
        try:
            dt = datetime.datetime.strptime(text, fmt)
            if fmt.endswith("Z") or text.endswith("Z"):
                return pytz.UTC.localize(dt)
            if tzid:
                try:
                    tz = pytz.timezone(tzid)
                except Exception:
                    tz = CENTRAL_TIME
                return tz.localize(dt)
            return CENTRAL_TIME.localize(dt)
        except Exception as exc:
            last_error = exc
            continue
    logging.debug("Unable to parse ICS datetime '%s': %s", text, last_error)
    return None


def _derive_team_abbr(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ]+", "", name or "").strip()
    if not cleaned:
        return "TBD"
    parts = cleaned.split()
    if len(parts) == 1:
        return parts[0][:3].upper()
    abbr = "".join(part[0] for part in parts[:3])
    return (abbr or cleaned[:3]).upper()


def _nickname_from_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name or "").strip()
    if not cleaned:
        return ""
    parts = cleaned.split(" ")
    if len(parts) == 1:
        return cleaned
    return parts[-1]


def _ics_team_payload(name: str, is_wolves: bool) -> Dict[str, Any]:
    if is_wolves:
        abbr = (AHL_TEAM_TRICODE or _derive_team_abbr(name)).upper()
        team_id: Optional[int] = AHL_TEAM_ID
    else:
        abbr = _derive_team_abbr(name)
        team_id = None
    return {
        "id": team_id,
        "abbr": abbr,
        "name": name,
        "nickname": _nickname_from_name(name),
        "score": None,
        "shots": None,
    }


_RESULT_SUFFIX_RE = re.compile(r"\s*\(([WL]|WIN|LOSS)\)\s*$", re.IGNORECASE)
_SCORE_PAIR_RE = re.compile(r"([^()]+?)\s*\((\d+)\)")


def _clean_ics_team_fragment(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = _RESULT_SUFFIX_RE.sub("", cleaned)
    return cleaned.strip(" \t-–—✔✓✖✕•")


def _extract_ics_score_line(description: Optional[str]) -> Optional[str]:
    if not description:
        return None
    for raw_line in description.replace("\r", "").splitlines():
        line = raw_line.strip()
        if not line or "(" not in line or ")" not in line:
            continue
        if any(ch.isdigit() for ch in line):
            return line.lstrip("✔✓✖✕•-–— ").strip()
    return None


def _parse_ics_note_scores(description: Optional[str]) -> Optional[Dict[str, Any]]:
    line = _extract_ics_score_line(description)
    if not line:
        return None
    entries: List[Tuple[str, int]] = []
    for raw_name, score_text in _SCORE_PAIR_RE.findall(line):
        name = _clean_ics_team_fragment(raw_name)
        if not name:
            continue
        try:
            score = int(score_text)
        except ValueError:
            continue
        entries.append((name, score))
    if len(entries) < 2:
        return None
    return {"line": line, "entries": entries}


def _match_score_for_team(name: str, entries: List[Tuple[str, int]]) -> Optional[int]:
    if not name:
        return None
    name_lower = name.lower()
    for entry_name, score in entries:
        entry_lower = entry_name.lower()
        if name_lower in entry_lower or entry_lower in name_lower:
            return score
    return None


def _split_wolves_summary(summary: str) -> Optional[Dict[str, Any]]:
    if not summary:
        return None
    clean = summary.strip()
    if not clean:
        return None
    wolves = (AHL_TEAM_NAME or "Chicago Wolves").lower()
    patterns = [
        (r"(.+?)\s+at\s+(.+)", False),
        (r"(.+?)\s+@\s+(.+)", False),
        (r"(.+?)\s+vs\.?\s+(.+)", True),
        (r"(.+?)\s+v\.?\s+(.+)", True),
    ]
    for pattern, first_is_home in patterns:
        match = re.match(pattern, clean, re.IGNORECASE)
        if not match:
            continue
        first = match.group(1).strip()
        second = match.group(2).strip()
        if first_is_home:
            home_name, away_name = first, second
        else:
            away_name, home_name = first, second
        home_name = _clean_ics_team_fragment(home_name)
        away_name = _clean_ics_team_fragment(away_name)
        home_lower = home_name.lower()
        away_lower = away_name.lower()
        wolves_home = wolves in home_lower
        wolves_away = wolves in away_lower
        if not (wolves_home or wolves_away):
            continue
        return {
            "home_name": home_name,
            "away_name": away_name,
            "wolves_is_home": wolves_home,
            "wolves_is_away": wolves_away,
        }
    return None


def _normalize_wolves_ics_game(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if event.get("STATUS", "CONFIRMED").upper() == "CANCELLED":
        return None
    params = (event.get("__params__") or {}).get("DTSTART") or {}
    start = _parse_ics_datetime(event.get("DTSTART"), params)
    if not start:
        return None
    summary = event.get("SUMMARY")
    parsed = _split_wolves_summary(summary or "")
    if not parsed:
        return None
    home_name = parsed["home_name"]
    away_name = parsed["away_name"]
    wolves_is_home = bool(parsed.get("wolves_is_home"))
    wolves_is_away = bool(parsed.get("wolves_is_away"))
    if not (wolves_is_home or wolves_is_away):
        return None
    home_team = _ics_team_payload(home_name, wolves_is_home)
    away_team = _ics_team_payload(away_name, wolves_is_away)
    description = event.get("DESCRIPTION") or event.get("X-ALT-DESC")
    note_scores = _parse_ics_note_scores(description)
    status_state = "FUT"
    status_detail = "Scheduled"
    status_note: Optional[str] = None
    if note_scores:
        entries = note_scores["entries"]
        home_score = _match_score_for_team(home_name, entries)
        away_score = _match_score_for_team(away_name, entries)
        if home_score is not None:
            home_team["score"] = home_score
        if away_score is not None:
            away_team["score"] = away_score
        if home_score is not None and away_score is not None:
            status_state = "FINAL"
            status_detail = "Final"
            status_note = note_scores.get("line")
    start_utc = start.astimezone(pytz.UTC)
    start_central = start.astimezone(CENTRAL_TIME)
    return {
        "game_id": event.get("UID"),
        "home": home_team,
        "away": away_team,
        "start": start,
        "start_utc": start_utc,
        "start_iso": start_utc.isoformat(),
        "start_time_central": _format_local_time(start_central),
        "official_date": start.date().isoformat(),
        "status": {
            "state": status_state,
            "detail": status_detail,
            "period": None,
            "clock": None,
            "note": status_note,
        },
        "venue": event.get("LOCATION"),
        "is_home": wolves_is_home,
    }


def _fetch_wolves_ics_games() -> List[Dict[str, Any]]:
    url = _wolves_schedule_url()
    if not url:
        logging.warning("AHL schedule ICS URL not configured")
        return []
    headers = {
        "User-Agent": "desk-display/1.0",
        "Accept": "text/calendar, text/plain;q=0.9, */*;q=0.8",
        "Referer": "https://stanzacal.com/",
    }
    try:
        resp = _session.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        events = _parse_ics_events(resp.text)
    except Exception as exc:
        logging.error("Error fetching Wolves ICS schedule: %s", exc)
        return []
    games: List[Dict[str, Any]] = []
    for event in events:
        normalized = _normalize_wolves_ics_game(event)
        if normalized:
            games.append(normalized)
    games.sort(key=lambda g: g.get("start_utc"))
    return games


def _ics_game_has_scores(game: Dict[str, Any]) -> bool:
    home = game.get("home") or {}
    away = game.get("away") or {}
    return isinstance(home.get("score"), int) and isinstance(away.get("score"), int)


def _classify_wolves_ics_games(games: List[Dict[str, Any]]) -> Dict[str, Optional[Dict]]:
    now = datetime.datetime.now(pytz.UTC)
    upcoming: List[Dict[str, Any]] = []
    last_final: Optional[Dict[str, Any]] = None
    for game in games:
        start = game.get("start_utc")
        status_state = ((game.get("status") or {}).get("state") or "").upper()
        has_scores = _ics_game_has_scores(game)
        if has_scores and isinstance(start, datetime.datetime):
            if status_state.startswith("FIN") or start <= now:
                if not last_final or start > last_final.get("start_utc", start):
                    last_final = game
                continue
        if isinstance(start, datetime.datetime) and start >= now - datetime.timedelta(hours=1):
            upcoming.append(game)
    upcoming.sort(key=lambda g: g.get("start_utc"))
    next_game = upcoming[0] if upcoming else None
    next_home = None
    for game in upcoming:
        if game.get("is_home"):
            next_home = game
            break
    return {"last_game": last_final, "next_game": next_game, "next_home_game": next_home}


_WOLVES_CACHE_TTL = 15 * 60  # seconds
_wolves_cache: Dict[str, Any] = {"expires": 0.0, "data": None}


def fetch_wolves_games(force_refresh: bool = False) -> Dict[str, Optional[Dict]]:
    now = time.time()
    cached = _wolves_cache.get("data")
    expires = _wolves_cache.get("expires", 0.0)
    if (
        not force_refresh
        and isinstance(expires, (int, float))
        and isinstance(cached, dict)
        and now < float(expires)
    ):
        return cached

    last_game: Optional[Dict] = None
    live_game: Optional[Dict] = None
    next_game: Optional[Dict] = None
    next_home: Optional[Dict] = None

    try:
        games = _fetch_ahl_schedule()
        if games:
            classified = _classify_wolves_games(games)
            last_game = classified.get("last_game")
            live_game = classified.get("live_game")
    except Exception as exc:
        logging.error("Error fetching Chicago Wolves score data: %s", exc)

    try:
        ics_games = _fetch_wolves_ics_games()
        if ics_games:
            classified_ics = _classify_wolves_ics_games(ics_games)
            next_game = classified_ics.get("next_game")
            next_home = classified_ics.get("next_home_game")
            if not last_game:
                last_game = classified_ics.get("last_game")
    except Exception as exc:
        logging.error("Error parsing Wolves ICS schedule: %s", exc)

    payload = {
        "last_game": last_game,
        "live_game": live_game,
        "next_game": next_game,
        "next_home_game": next_home,
    }
    _wolves_cache["data"] = payload
    _wolves_cache["expires"] = now + _WOLVES_CACHE_TTL
    return payload
