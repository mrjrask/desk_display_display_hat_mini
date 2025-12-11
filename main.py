#!/usr/bin/env python3
"""
Main display loop driving the Pimoroni Display HAT Mini LCD,
with optional screenshot capture, H.264 MP4 video capture, Wi-Fi triage,
screen-config sequencing, and batch screenshot archiving.

Changes:
- Stop pruning single files; instead, when screenshots/ has >= ARCHIVE_THRESHOLD
  images, archive the whole set into screenshot_archive/<screen>/.
- Avoid creating empty archive folders.
- Guard logo screens when the image file is missing.
- Sort archived screenshots inside screenshot_archive/<screen>/ so they mirror
  the live screenshots/ folder structure.
"""
import warnings
from gpiozero.exc import PinFactoryFallback, NativePinFactoryFallback

warnings.filterwarnings("ignore", category=PinFactoryFallback)
warnings.filterwarnings("ignore", category=NativePinFactoryFallback)

import os
import time
import logging
import threading
import datetime
import signal
import shutil
import subprocess
from contextlib import nullcontext
from typing import Callable, Dict, Optional, Set

gc = __import__('gc')

from PIL import Image, ImageDraw

from config import (
    WIDTH,
    HEIGHT,
    SCREEN_DELAY,
    SCHEDULE_UPDATE_INTERVAL,
    FONT_DATE_SPORTS,
    ENABLE_SCREENSHOTS,
    ENABLE_VIDEO,
    VIDEO_FPS,
    ENABLE_WEATHER,
    ENABLE_WIFI_MONITOR,
    CENTRAL_TIME,
    TRAVEL_ACTIVE_WINDOW,
    DARK_HOURS_ENABLED,
    is_within_dark_hours,
    AHL_TEAM_TRICODE,
)
from utils import (
    Display,
    ScreenImage,
    animate_fade_in,
    clear_display,
    draw_text_centered,
    resume_display_updates,
    suspend_display_updates,
    temporary_display_led,
)
import data_fetch
from services import wifi_utils
from paths import resolve_storage_paths

from screens.draw_date_time import draw_date, draw_time
from screens.draw_travel_time import (
    get_travel_active_window,
    is_travel_screen_active,
)
from screens.registry import ScreenContext, ScreenDefinition, build_screen_registry
from schedule import ScreenScheduler, build_scheduler, load_schedule_config

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.info("🖥️  Starting display service…")

# ─── Paths ───────────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "screens_config.json")

# ─── Screenshot archiving (batch) ────────────────────────────────────────────
ARCHIVE_THRESHOLD = 500  # archive when we reach this many images
ARCHIVE_DEFAULT_FOLDER = "Screens"
ALLOWED_SCREEN_EXTS = (".png", ".jpg", ".jpeg")  # images only

_storage_paths = resolve_storage_paths(logger=logging.getLogger(__name__))
SCREENSHOT_DIR = str(_storage_paths.screenshot_dir)
CURRENT_SCREENSHOT_DIR = str(_storage_paths.current_screenshot_dir)
SCREENSHOT_ARCHIVE_BASE = str(_storage_paths.archive_base)
SCREENSHOT_ARCHIVE_MIRROR = SCREENSHOT_ARCHIVE_BASE

_screen_config_mtime: Optional[float] = None
screen_scheduler: Optional[ScreenScheduler] = None
_requested_screen_ids: Set[str] = set()

_skip_request_pending = False
_last_screen_id: Optional[str] = None

_SKIP_BUTTON_SCREEN_IDS = {"date", "time"}

_shutdown_event = threading.Event()
_shutdown_complete = threading.Event()
_display_cleared = threading.Event()

BUTTON_POLL_INTERVAL = 0.1
_BUTTON_NAMES = ("A", "B", "X", "Y")
_BUTTON_STATE = {name: False for name in _BUTTON_NAMES}
_manual_skip_event = threading.Event()
_button_monitor_thread: Optional[threading.Thread] = None

_dark_hours_active = False

BRIGHTNESS_STEP = 0.1


def _handle_button_down(name: str) -> bool:
    """React to a newly pressed control button."""

    global _skip_request_pending

    name = name.upper()
    if name == "X":
        logging.info("⏭️  X button pressed – skipping to next screen.")
        _skip_request_pending = True
        _manual_skip_event.set()
        return True
    if name == "Y":
        logging.info("🔁 Y button pressed – restarting desk_display service…")
        _restart_desk_display_service()
        return False
    if name == "A":
        new_level = display.adjust_backlight(-BRIGHTNESS_STEP)
        logging.info("🅰️  A button pressed – dimming to %.0f%%.", new_level * 100)
        return False
    if name == "B":
        new_level = display.adjust_backlight(BRIGHTNESS_STEP)
        logging.info("🅱️  B button pressed – brightening to %.0f%%.", new_level * 100)
        return False
    return False


def _button_event_callback(name: str) -> None:
    """Hardware callback fired when a control button is pressed."""

    upper = name.upper()
    if upper not in _BUTTON_STATE:
        return

    if _BUTTON_STATE[upper]:
        return

    _BUTTON_STATE[upper] = True
    _handle_button_down(upper)


def _load_scheduler_from_config() -> Optional[ScreenScheduler]:
    try:
        config_data = load_schedule_config(CONFIG_PATH)
    except Exception as exc:
        logging.warning(f"Could not load schedule configuration: {exc}")
        return None

    try:
        scheduler = build_scheduler(config_data)
    except ValueError as exc:
        logging.error(f"Invalid schedule configuration: {exc}")
        return None

    return scheduler


def refresh_schedule_if_needed(force: bool = False) -> None:
    global _screen_config_mtime, screen_scheduler, _requested_screen_ids
    global _last_screen_id, _skip_request_pending

    try:
        mtime = os.path.getmtime(CONFIG_PATH)
    except OSError:
        mtime = None

    if not force and mtime == _screen_config_mtime and screen_scheduler is not None:
        return

    scheduler = _load_scheduler_from_config()
    if scheduler is None:
        return

    screen_scheduler = scheduler
    _requested_screen_ids = scheduler.requested_ids
    _screen_config_mtime = mtime
    _last_screen_id = None
    _skip_request_pending = False
    logging.info("🔁 Loaded schedule configuration with %d node(s).", scheduler.node_count)


# ─── Display & Wi-Fi monitor ─────────────────────────────────────────────────
display = Display()
try:
    display.set_button_callback(_button_event_callback)
except Exception:
    logging.debug("Button callback registration unavailable.")
if ENABLE_WIFI_MONITOR:
    logging.info("🔌 Starting Wi-Fi monitor…")
    wifi_utils.start_monitor()

refresh_schedule_if_needed(force=True)


def _clear_display_immediately(reason: Optional[str] = None) -> None:
    """Clear the LCD as soon as a shutdown is requested."""

    already_cleared = _display_cleared.is_set()

    if reason and not already_cleared:
        logging.info("🧹 Clearing display (%s)…", reason)

    try:
        resume_display_updates()
        clear_display(display)
        try:
            display.show()
        except Exception:
            pass
    except Exception:
        pass
    finally:
        _display_cleared.set()
        suspend_display_updates()


def request_shutdown(reason: str) -> None:
    """Signal the main loop to exit and blank the screen immediately."""

    if _shutdown_event.is_set():
        _clear_display_immediately(reason)
        return

    logging.info("✋ Shutdown requested (%s).", reason)
    _shutdown_event.set()
    _clear_display_immediately(reason)


def _restart_desk_display_service() -> None:
    """Restart the desk_display systemd service."""

    request_shutdown("service restart")
    try:
        subprocess.run(
            ["sudo", "systemctl", "restart", "desk_display.service"],
            check=False,
        )
    except Exception as exc:
        logging.error("Failed to restart desk_display.service: %s", exc)


def _check_control_buttons() -> bool:
    """Handle Display HAT Mini control buttons.

    Returns True when the caller should skip to the next screen immediately.
    """

    global _skip_request_pending

    if _shutdown_event.is_set():
        return False

    new_presses = []
    skip_requested = False

    for name in _BUTTON_NAMES:
        try:
            pressed = display.is_button_pressed(name)
        except Exception as exc:
            logging.debug("Button poll failed for %s: %s", name, exc)
            pressed = False

        previously_pressed = _BUTTON_STATE[name]

        if pressed and not previously_pressed:
            new_presses.append(name)
        elif not pressed and previously_pressed:
            logging.debug("Button %s released.", name)

        _BUTTON_STATE[name] = pressed

    if len(new_presses) > 1:
        logging.warning(
            "Ignoring simultaneous button presses (%s); treating as noise.",
            ", ".join(new_presses),
        )
        for name in new_presses:
            _BUTTON_STATE[name] = False
        return False

    for name in new_presses:
        if _handle_button_down(name):
            skip_requested = True

    if skip_requested or _manual_skip_event.is_set():
        return True

    return False


def _wait_with_button_checks(duration: float) -> bool:
    """Sleep for *duration* seconds while checking for control button presses.

    Returns True if the caller should skip the rest of the current screen.
    """

    if _manual_skip_event.is_set() or _skip_request_pending:
        _manual_skip_event.clear()
        return True

    end = time.monotonic() + duration
    while not _shutdown_event.is_set():
        if _manual_skip_event.is_set() or _skip_request_pending:
            _manual_skip_event.clear()
            return True

        if _check_control_buttons():
            _manual_skip_event.clear()
            return True

        remaining = end - time.monotonic()
        if remaining <= 0:
            break

        sleep_for = min(BUTTON_POLL_INTERVAL, remaining)
        if sleep_for > 0:
            if _manual_skip_event.wait(sleep_for):
                _manual_skip_event.clear()
                return True

            if _shutdown_event.is_set():
                return False

    return False


def _monitor_control_buttons() -> None:
    """Background poller to catch brief button presses."""

    logging.debug("Starting control button monitor thread.")

    try:
        while not _shutdown_event.is_set():
            try:
                _check_control_buttons()
            except Exception as exc:
                logging.debug("Button monitor loop failed: %s", exc)

            if _shutdown_event.wait(BUTTON_POLL_INTERVAL):
                break
    finally:
        logging.debug("Control button monitor thread exiting.")


_button_monitor_thread = threading.Thread(
    target=_monitor_control_buttons,
    name="control-button-monitor",
    daemon=True,
)
_button_monitor_thread.start()


def _next_screen_from_registry(
    registry: Dict[str, ScreenDefinition]
) -> Optional[ScreenDefinition]:
    """Return the next screen, honoring any pending skip requests."""

    global _skip_request_pending

    scheduler = screen_scheduler
    if scheduler is None:
        _skip_request_pending = False
        return None

    entry = scheduler.next_available(registry)
    if entry is None:
        _skip_request_pending = False
        return None

    if not _skip_request_pending:
        return entry

    first_entry = entry
    avoided = set(_SKIP_BUTTON_SCREEN_IDS)
    if _last_screen_id:
        avoided.add(_last_screen_id)

    attempts = scheduler.node_count
    while entry and entry.id in avoided and attempts > 1:
        logging.debug(
            "Manual skip dropping '%s' from queue.",
            entry.id,
        )
        entry = scheduler.next_available(registry)
        attempts -= 1

    if entry and entry.id in avoided:
        logging.debug(
            "Manual skip fallback to '%s' (no alternative available).",
            entry.id,
        )
        entry = first_entry

    _skip_request_pending = False
    return entry

# ─── Screenshot / video outputs ──────────────────────────────────────────────
if ENABLE_SCREENSHOTS:
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    os.makedirs(CURRENT_SCREENSHOT_DIR, exist_ok=True)
    os.makedirs(SCREENSHOT_ARCHIVE_BASE, exist_ok=True)

video_out = None
if ENABLE_VIDEO:
    import cv2, numpy as np
    FOURCC     = cv2.VideoWriter_fourcc(*"mp4v")
    video_path = os.path.join(SCREENSHOT_DIR, "display_output.mp4")
    logging.info(f"🎥 Starting video capture → {video_path} @ {VIDEO_FPS} FPS using mp4v")
    video_out = cv2.VideoWriter(video_path, FOURCC, VIDEO_FPS, (WIDTH, HEIGHT))
    if not video_out.isOpened():
        logging.error("❌ Cannot open video writer; disabling video output")
        video_out = None

_archive_lock = threading.Lock()


def _release_video_writer() -> None:
    global video_out

    if video_out:
        video_out.release()
        logging.info("🎬 Video finalized cleanly.")
        video_out = None


def _finalize_shutdown() -> None:
    """Run the shutdown cleanup sequence once."""

    if _shutdown_complete.is_set():
        return

    _clear_display_immediately("final cleanup")

    if video_out:
        logging.info("🎬 Finalizing video…")
    _release_video_writer()

    if ENABLE_WIFI_MONITOR:
        wifi_utils.stop_monitor()

    global _button_monitor_thread
    if _button_monitor_thread and _button_monitor_thread.is_alive():
        _button_monitor_thread.join(timeout=1.0)
        _button_monitor_thread = None

    _shutdown_complete.set()
    logging.info("👋 Shutdown cleanup finished.")


def _sanitize_directory_name(name: str) -> str:
    """Return a filesystem-friendly directory name while keeping spaces."""

    safe = name.strip().replace("/", "-").replace("\\", "-")
    safe = "".join(ch for ch in safe if ch.isalnum() or ch in (" ", "-", "_"))
    return safe or "Screens"


def _sanitize_filename_prefix(name: str) -> str:
    """Return a filesystem-friendly filename prefix."""

    safe = name.strip().replace("/", "-").replace("\\", "-")
    safe = safe.replace(" ", "_")
    safe = "".join(ch for ch in safe if ch.isalnum() or ch in ("_", "-"))
    return safe or "screen"


def _save_screenshot(sid: str, img: Image.Image) -> None:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = _sanitize_directory_name(sid)
    prefix = _sanitize_filename_prefix(sid)
    target_dir = os.path.join(SCREENSHOT_DIR, folder)
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, f"{prefix}_{ts}.png")

    try:
        img.save(path)
    except Exception:
        logging.warning(f"⚠️ Screenshot save failed for '{sid}'")

    try:
        os.makedirs(CURRENT_SCREENSHOT_DIR, exist_ok=True)
        for entry in os.scandir(CURRENT_SCREENSHOT_DIR):
            if not entry.is_file():
                continue
            stem, ext = os.path.splitext(entry.name)
            if stem == prefix and ext.lower() in ALLOWED_SCREEN_EXTS:
                os.remove(entry.path)
        current_path = os.path.join(CURRENT_SCREENSHOT_DIR, f"{prefix}.png")
        img.save(current_path)
    except Exception:
        logging.warning(f"⚠️ Failed to update current screenshot for '{sid}'")


def _list_screenshot_files():
    try:
        results = []
        for root, dirs, files in os.walk(SCREENSHOT_DIR):
            if os.path.abspath(root) == os.path.abspath(CURRENT_SCREENSHOT_DIR):
                dirs.clear()
                continue
            for fname in files:
                if not fname.lower().endswith(ALLOWED_SCREEN_EXTS):
                    continue
                rel_dir = os.path.relpath(root, SCREENSHOT_DIR)
                rel_path = fname if rel_dir == "." else os.path.join(rel_dir, fname)
                results.append(rel_path)
        return sorted(results)
    except Exception:
        return []

def maybe_archive_screenshots():
    """
    When screenshots/ reaches ARCHIVE_THRESHOLD images, move the current images
    into screenshot_archive/<screen>/ so the archive mirrors the live
    screenshots/ folder layout. Avoid creating empty archive folders.
    """
    if not ENABLE_SCREENSHOTS:
        return
    files = _list_screenshot_files()
    if len(files) < ARCHIVE_THRESHOLD:
        return

    with _archive_lock:
        files = _list_screenshot_files()
        if len(files) < ARCHIVE_THRESHOLD:
            return

        moved = 0
        created_archive_dirs = set()

        for fname in files:
            src = os.path.join(SCREENSHOT_DIR, fname)
            try:
                parts = fname.split(os.sep)
                if len(parts) > 1:
                    screen_folder, remainder = parts[0], os.path.join(*parts[1:])
                else:
                    screen_folder, remainder = ARCHIVE_DEFAULT_FOLDER, parts[0]

                archive_dir = os.path.join(
                    SCREENSHOT_ARCHIVE_MIRROR,
                    screen_folder,
                )
                if not os.path.exists(archive_dir):
                    created_archive_dirs.add(archive_dir)
                dest = os.path.join(archive_dir, remainder)
                dest_dir = os.path.dirname(dest)
                if dest_dir and not os.path.exists(dest_dir):
                    os.makedirs(dest_dir, exist_ok=True)
                shutil.move(src, dest)
                moved += 1
            except Exception as e:
                logging.warning(f"⚠️  Could not move '{fname}' to archive: {e}")

        if moved == 0:
            for archive_dir in sorted(created_archive_dirs, reverse=True):
                if os.path.isdir(archive_dir) and not os.listdir(archive_dir):
                    try:
                        shutil.rmtree(archive_dir)
                    except Exception:
                        pass

        if moved:
            logging.info(
                "🗃️  Archived %s screenshot(s) → %s/",
                moved,
                SCREENSHOT_ARCHIVE_MIRROR,
            )

# ─── SIGTERM handler ─────────────────────────────────────────────────────────
def _handle_sigterm(signum, frame):
    logging.info("✋ SIGTERM caught—requesting shutdown…")
    request_shutdown("SIGTERM")

signal.signal(signal.SIGTERM, _handle_sigterm)

# ─── Logos ───────────────────────────────────────────────────────────────────
IMAGES_DIR = os.path.join(SCRIPT_DIR, "images")
# Logos scroll across the screen; keep them just a bit shorter than the display
# while preserving aspect ratio during resize.
LOGO_SCREEN_HEIGHT = max(1, HEIGHT - 30)
TEAM_LOGO_HEIGHT   = LOGO_SCREEN_HEIGHT


def load_logo(fn, height=LOGO_SCREEN_HEIGHT):
    path = os.path.join(IMAGES_DIR, fn)
    try:
        with Image.open(path) as img:
            has_transparency = (
                img.mode in ("RGBA", "LA")
                or (img.mode == "P" and "transparency" in img.info)
            )
            target_mode = "RGBA" if has_transparency else "RGB"
            img = img.convert(target_mode)
            ratio = height / img.height if img.height else 1
            resized = img.resize((int(img.width * ratio), height), Image.ANTIALIAS)
        return resized
    except Exception as e:
        logging.warning(f"Logo load failed '{fn}': {e}")
        return None


def _load_wolves_logo() -> Optional[Image.Image]:
    wolves_tri = (AHL_TEAM_TRICODE or "CHI").strip() or "CHI"
    for variant in {wolves_tri.upper(), wolves_tri.lower()}:
        wolves_logo = load_logo(f"ahl/{variant}.png", height=TEAM_LOGO_HEIGHT)
        if wolves_logo:
            return wolves_logo
    return load_logo("wolves.jpg", height=TEAM_LOGO_HEIGHT)


_LOGO_LOADERS: Dict[str, Callable[[], Optional[Image.Image]]] = {
    "weather logo": lambda: load_logo("weather.jpg"),
    "verano logo": lambda: load_logo("verano.jpg"),
    "bears logo": lambda: load_logo("nfl/chi.png"),
    "nfl logo": lambda: load_logo("nfl/nfl.png"),
    "hawks logo": lambda: load_logo("nhl/CHI.png", height=TEAM_LOGO_HEIGHT),
    "nhl logo": lambda: load_logo("nhl/nhl.png") or load_logo("nhl/NHL.png"),
    "wolves logo": _load_wolves_logo,
    "cubs logo": lambda: load_logo("mlb/CUBS.png", height=TEAM_LOGO_HEIGHT),
    "sox logo": lambda: load_logo("mlb/SOX.png", height=TEAM_LOGO_HEIGHT),
    "mlb logo": lambda: load_logo("mlb/MLB.png"),
    "nba logo": lambda: load_logo("nba/NBA.png"),
    "bulls logo": lambda: load_logo("nba/CHI.png", height=TEAM_LOGO_HEIGHT),
}


class LogoCache:
    def __init__(self, loaders: Dict[str, Callable[[], Optional[Image.Image]]]):
        self._loaders = loaders
        self._cache: Dict[str, Optional[Image.Image]] = {}

    def get(self, name: str) -> Optional[Image.Image]:
        if name in self._cache:
            return self._cache[name]

        loader = self._loaders.get(name)
        image = loader() if loader else None
        self._cache[name] = image
        return image


logo_cache = LogoCache(_LOGO_LOADERS)

# ─── Data cache & refresh ────────────────────────────────────────────────────
cache = {
    "bears":  {"stand": None},
    "weather": None,
    "hawks":   {"stand":None, "last":None, "live":None, "next":None, "next_home":None},
    "wolves":  {"last":None, "live":None, "next":None, "next_home":None},
    "bulls":   {"stand":None, "last":None, "live":None, "next":None, "next_home":None},
    "cubs":    {"stand":None, "last":None, "live":None, "next":None, "next_home":None},
    "sox":     {"stand":None, "last":None, "live":None, "next":None, "next_home":None},
}

_FEED_DEPENDENCIES: Dict[str, Set[str]] = {
    "weather": {"weather1", "weather2", "weather hourly", "weather radar", "weather logo"},
    "bears": {"bears stand1", "bears stand2"},
    "hawks": {"hawks stand1", "hawks stand2", "hawks last", "hawks live", "hawks next", "hawks next home", "hawks logo"},
    "wolves": {"wolves last", "wolves live", "wolves next", "wolves next home", "wolves logo"},
    "bulls": {"bulls stand1", "bulls stand2", "bulls last", "bulls live", "bulls next", "bulls next home", "bulls logo"},
    "cubs": {
        "cubs stand1",
        "cubs stand2",
        "cubs last",
        "cubs result",
        "cubs live",
        "cubs next",
        "cubs next home",
        "cubs logo",
    },
    "sox": {
        "sox stand1",
        "sox stand2",
        "sox last",
        "sox live",
        "sox next",
        "sox next home",
        "sox logo",
    },
}

_FEED_REFRESH_INTERVALS: Dict[str, int] = {
    "weather": SCHEDULE_UPDATE_INTERVAL,
    "hawks": SCHEDULE_UPDATE_INTERVAL,
    "bulls": SCHEDULE_UPDATE_INTERVAL,
    "wolves": SCHEDULE_UPDATE_INTERVAL,
    "bears": 1800,
    "cubs": 1800,
    "sox": 1800,
}

_last_feed_refresh: Dict[str, float] = {}


def _requested_data_feeds() -> Set[str]:
    feeds: Set[str] = set()
    for feed, screen_ids in _FEED_DEPENDENCIES.items():
        if feed == "weather" and not ENABLE_WEATHER:
            continue
        if _requested_screen_ids & screen_ids:
            feeds.add(feed)
    return feeds


def _refresh_weather() -> None:
    cache["weather"] = data_fetch.fetch_weather()


def _refresh_bears() -> None:
    cache["bears"].update({
        "stand": data_fetch.fetch_bears_standings(),
    })


def _refresh_hawks() -> None:
    cache["hawks"].update({
        "stand": data_fetch.fetch_blackhawks_standings(),
        "last": data_fetch.fetch_blackhawks_last_game(),
        "live": data_fetch.fetch_blackhawks_live_game(),
        "next": data_fetch.fetch_blackhawks_next_game(),
        "next_home": data_fetch.fetch_blackhawks_next_home_game(),
    })


def _refresh_wolves() -> None:
    wolves_games = data_fetch.fetch_wolves_games() or {}
    cache["wolves"].update({
        "last": wolves_games.get("last_game"),
        "live": wolves_games.get("live_game"),
        "next": wolves_games.get("next_game"),
        "next_home": wolves_games.get("next_home_game"),
    })


def _refresh_bulls() -> None:
    cache["bulls"].update({
        "stand": data_fetch.fetch_bulls_standings(),
        "last": data_fetch.fetch_bulls_last_game(),
        "live": data_fetch.fetch_bulls_live_game(),
        "next": data_fetch.fetch_bulls_next_game(),
        "next_home": data_fetch.fetch_bulls_next_home_game(),
    })


def _refresh_cubs() -> None:
    cubg = data_fetch.fetch_cubs_games() or {}
    cache["cubs"].update({
        "stand": data_fetch.fetch_cubs_standings(),
        "last":  cubg.get("last_game"),
        "live":  cubg.get("live_game"),
        "next":  cubg.get("next_game"),
        "next_home": cubg.get("next_home_game"),
    })


def _refresh_sox() -> None:
    soxg = data_fetch.fetch_sox_games() or {}
    cache["sox"].update({
        "stand": data_fetch.fetch_sox_standings(),
        "last":  soxg.get("last_game"),
        "live":  soxg.get("live_game"),
        "next":  soxg.get("next_game"),
        "next_home": soxg.get("next_home_game"),
    })


_FEED_REFRESHERS: Dict[str, Callable[[], None]] = {
    "weather": _refresh_weather,
    "bears": _refresh_bears,
    "hawks": _refresh_hawks,
    "wolves": _refresh_wolves,
    "bulls": _refresh_bulls,
    "cubs": _refresh_cubs,
    "sox": _refresh_sox,
}


def refresh_all(force: bool = False) -> None:
    required_feeds = _requested_data_feeds()
    if not required_feeds:
        logging.info("⏭️  No scheduled data-dependent screens; skipping refresh.")
        return

    now = time.monotonic()
    due_feeds: Set[str] = set()
    for feed in required_feeds:
        interval = _FEED_REFRESH_INTERVALS.get(feed, SCHEDULE_UPDATE_INTERVAL)
        last_run = _last_feed_refresh.get(feed, 0.0)
        elapsed = now - last_run if last_run else float("inf")

        if force or elapsed >= interval:
            due_feeds.add(feed)
        else:
            remaining = int(interval - elapsed)
            logging.info("⏭️  Skipping %s refresh; %ds until next update.", feed, remaining)

    if not due_feeds:
        return

    logging.info("🔄 Refreshing data for feeds: %s", ", ".join(sorted(due_feeds)))
    for feed in sorted(due_feeds):
        refresher = _FEED_REFRESHERS.get(feed)
        if not refresher:
            continue
        try:
            refresher()
            _last_feed_refresh[feed] = time.monotonic()
        except Exception as exc:
            logging.error("Failed to refresh %s feed: %s", feed, exc)

def _background_refresh() -> None:
    time.sleep(30)
    while not _shutdown_event.is_set():
        feeds = _requested_data_feeds()
        if not feeds:
            logging.info("⏸️  Background refresh idle; no data-driven screens active.")
        else:
            refresh_all()

        if _shutdown_event.wait(SCHEDULE_UPDATE_INTERVAL):
            break


threading.Thread(
    target=_background_refresh,
    daemon=True
).start()
refresh_all(force=True)

# ─── Main loop ───────────────────────────────────────────────────────────────
loop_count = 0
_travel_schedule_state: Optional[str] = None

def main_loop():
    global loop_count, _travel_schedule_state, _last_screen_id, _dark_hours_active

    refresh_schedule_if_needed(force=True)

    try:
        while not _shutdown_event.is_set():
            refresh_schedule_if_needed()

            # Always drain button events, but keep skip requests active so the
            # currently visible screen (or the very next one) can react
            # immediately instead of idling on the previous frame for another
            # full iteration.
            _check_control_buttons()

            current_time = datetime.datetime.now(CENTRAL_TIME)

            if DARK_HOURS_ENABLED and is_within_dark_hours(current_time):
                if not _dark_hours_active:
                    logging.info("🌙 Entering configured dark hours; blanking display.")
                    try:
                        resume_display_updates()
                        clear_display(display)
                        display.show()
                    except Exception:
                        pass
                    suspend_display_updates()
                _dark_hours_active = True

                if _shutdown_event.is_set():
                    break

                if _wait_with_button_checks(SCREEN_DELAY):
                    continue

                gc.collect()
                continue

            if _dark_hours_active:
                logging.info("🌅 Leaving dark hours; resuming screen rotation.")
                _dark_hours_active = False
                resume_display_updates()

            # Wi-Fi outage handling
            if ENABLE_WIFI_MONITOR:
                wifi_state, wifi_ssid = wifi_utils.get_wifi_state()
            else:
                wifi_state, wifi_ssid = ("ok", None)

            if ENABLE_WIFI_MONITOR and wifi_state != "ok":
                img = Image.new("RGB", (WIDTH, HEIGHT), "black")
                d   = ImageDraw.Draw(img)
                if wifi_state == "no_wifi":
                    draw_text_centered(d, "No Wi-Fi.", FONT_DATE_SPORTS, fill=(255,0,0))
                else:
                    draw_text_centered(d, "Wi-Fi ok.",     FONT_DATE_SPORTS, y_offset=-12, fill=(255,255,0))
                    draw_text_centered(d, wifi_ssid or "", FONT_DATE_SPORTS, fill=(255,255,0))
                    draw_text_centered(d, "No internet.",  FONT_DATE_SPORTS, y_offset=12,  fill=(255,0,0))
                display.image(img)
                display.show()

                if _shutdown_event.is_set():
                    break

                if not _wait_with_button_checks(SCREEN_DELAY):
                    for fn in (draw_date, draw_time):
                        img2 = fn(display, transition=True)
                        animate_fade_in(display, img2, steps=8, delay=0.015)
                        if _shutdown_event.is_set():
                            break
                        if _wait_with_button_checks(SCREEN_DELAY):
                            break

                gc.collect()
                continue

            if screen_scheduler is None:
                logging.warning(
                    "No schedule available; sleeping for %s seconds.", SCREEN_DELAY
                )
                if _shutdown_event.is_set():
                    break
                if _wait_with_button_checks(SCREEN_DELAY):
                    continue
                gc.collect()
                continue

            travel_requested = "travel" in _requested_screen_ids
            context = ScreenContext(
                display=display,
                cache=cache,
                logos=logo_cache,
                image_dir=IMAGES_DIR,
                travel_requested=travel_requested,
                travel_active=is_travel_screen_active(),
                travel_window=get_travel_active_window(),
                previous_travel_state=_travel_schedule_state,
                now=datetime.datetime.now(CENTRAL_TIME),
            )
            registry, metadata = build_screen_registry(context)
            _travel_schedule_state = metadata.get("travel_state", _travel_schedule_state)

            entry = _next_screen_from_registry(registry)
            if entry is None:
                logging.info(
                    "No eligible screens available; sleeping for %s seconds.",
                    SCREEN_DELAY,
                )
                if _shutdown_event.is_set():
                    break
                if _wait_with_button_checks(SCREEN_DELAY):
                    continue
                gc.collect()
                continue

            sid = entry.id
            loop_count += 1
            logging.info("🎬 Presenting '%s' (iteration %d)", sid, loop_count)

            try:
                result = entry.render()
            except Exception as exc:
                logging.error(f"Error in screen '{sid}': {exc}")
                gc.collect()
                if _shutdown_event.is_set():
                    break
                if _wait_with_button_checks(SCREEN_DELAY):
                    continue
                continue

            already_displayed = False
            led_override = None
            img = None

            if result is None:
                logging.info(
                    "Screen '%s' returned no image; using current display buffer for outputs.",
                    sid,
                )
                current = getattr(display, "current_image", None)
                if isinstance(current, Image.Image):
                    img = current.copy()
                    already_displayed = True
            elif isinstance(result, ScreenImage):
                img = result.image
                already_displayed = result.displayed
                led_override = result.led_override
            elif isinstance(result, Image.Image):
                img = result

            if img is None:
                logging.info("Screen '%s' produced no drawable image.", sid)
                gc.collect()
                if _shutdown_event.is_set():
                    break
                if _wait_with_button_checks(SCREEN_DELAY):
                    continue
                continue

            skip_delay = False
            led_context = (
                temporary_display_led(*led_override)
                if led_override is not None
                else nullcontext()
            )
            with led_context:
                if isinstance(img, Image.Image):
                    if "logo" in sid:
                        if ENABLE_SCREENSHOTS:
                            _save_screenshot(sid, img)
                            maybe_archive_screenshots()
                        if ENABLE_VIDEO and video_out:
                            import cv2, numpy as np

                            frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                            video_out.write(frame)
                    else:
                        if not already_displayed:
                            animate_fade_in(display, img, steps=8, delay=0.015)
                        if ENABLE_SCREENSHOTS:
                            _save_screenshot(sid, img)
                            maybe_archive_screenshots()
                        if ENABLE_VIDEO and video_out:
                            import cv2, numpy as np

                            frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                            video_out.write(frame)
                else:
                    logging.info("Screen '%s' produced no drawable image.", sid)

                if _shutdown_event.is_set():
                    break

                _last_screen_id = sid
                skip_delay = _wait_with_button_checks(SCREEN_DELAY)

            if _shutdown_event.is_set():
                break

            if skip_delay:
                continue
            gc.collect()

    finally:
        _finalize_shutdown()

if __name__ == '__main__':
    try:
        main_loop()
    except KeyboardInterrupt:
        logging.info("✋ CTRL-C caught—requesting shutdown…")
        request_shutdown("CTRL-C")
    finally:
        _finalize_shutdown()

    os._exit(0)
