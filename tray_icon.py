import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import pystray
from PIL import Image

from config import config
from recorder import RecorderState

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).parent / "assets"


def _load_icon(name: str) -> Image.Image:
    path = ASSETS_DIR / name
    if path.exists():
        return Image.open(str(path))
    # Fallback: generate a coloured circle programmatically
    return _make_fallback_icon(name)


def _make_fallback_icon(name: str) -> Image.Image:
    from PIL import ImageDraw

    colours = {
        "icon_idle": "#808080",
        "icon_recording": "#cc0000",
        "icon_recording_alt": "#ff6666",
        "icon_paused": "#ccaa00",
    }
    stem = name.replace(".ico", "")
    colour = colours.get(stem, "#808080")
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=colour)
    return img


class TrayIcon:
    def __init__(
        self,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_pause_resume: Callable[[], None],
        on_open_folder: Callable[[], None],
        on_settings: Callable[[], None],
        on_toggle_autodetect: Callable[[], None],
        on_view_log: Callable[[], None],
        on_about: Callable[[], None],
        on_quit: Callable[[], None],
        get_recorder_state: Callable[[], str],
        get_elapsed: Callable[[], float],
    ):
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_pause_resume = on_pause_resume
        self._on_open_folder = on_open_folder
        self._on_settings = on_settings
        self._on_toggle_autodetect = on_toggle_autodetect
        self._on_view_log = on_view_log
        self._on_about = on_about
        self._on_quit = on_quit
        self._get_state = get_recorder_state
        self._get_elapsed = get_elapsed

        self._icons = {
            "idle": _load_icon("icon_idle.ico"),
            "recording": _load_icon("icon_recording.ico"),
            "recording_alt": _load_icon("icon_recording_alt.ico"),
            "paused": _load_icon("icon_paused.ico"),
        }
        self._pulse_toggle = False

        self._tray: Optional[pystray.Icon] = None
        self._update_thread: Optional[threading.Thread] = None
        self._stop_update = threading.Event()

    def run(self):
        self._tray = pystray.Icon(
            name="TeamsRecorder",
            icon=self._icons["idle"],
            title="Idle — Auto-detect ON" if config.get("auto_detect") else "Idle",
            menu=self._build_menu(),  # built once; callables keep it dynamic
        )
        self._stop_update.clear()
        self._update_thread = threading.Thread(
            target=self._update_loop, daemon=True, name="tray-updater"
        )
        self._update_thread.start()
        self._tray.run()  # blocks until tray.stop() is called

    def stop(self):
        self._stop_update.set()
        if self._tray:
            self._tray.stop()

    def update(self):
        if self._tray is None:
            return
        state = self._get_state()
        self._tray.icon = self._current_icon(state)
        self._tray.title = self._tooltip(state)
        # Do NOT replace self._tray.menu here — pystray re-registers the
        # Win32 menu on every assignment, which destroys the hover state
        # while the menu is open.  The menu was built once with callable
        # text/enabled/visible so pystray evaluates them at display time.

    def _current_icon(self, state: str) -> Image.Image:
        if state == RecorderState.RECORDING:
            self._pulse_toggle = not self._pulse_toggle
            return self._icons["recording"] if self._pulse_toggle else self._icons["recording_alt"]
        if state == RecorderState.PAUSED:
            return self._icons["paused"]
        return self._icons["idle"]

    def _tooltip(self, state: str) -> str:
        auto = "Auto-detect ON" if config.get("auto_detect") else "Auto-detect OFF"
        if state == RecorderState.RECORDING:
            elapsed = int(self._get_elapsed())
            mins, secs = divmod(elapsed, 60)
            return f"Recording — {mins:02d}:{secs:02d}"
        if state == RecorderState.PAUSED:
            elapsed = int(self._get_elapsed())
            mins, secs = divmod(elapsed, 60)
            return f"Paused — {mins:02d}:{secs:02d}"
        return f"Idle — {auto}"

    def _update_loop(self):
        while not self._stop_update.is_set():
            try:
                self.update()
            except Exception as e:
                logger.warning("Tray update error: %s", e)
            self._stop_update.wait(timeout=0.5)

    def _build_menu(self) -> pystray.Menu:
        # All dynamic properties use callables so pystray re-evaluates them
        # at display time.  The menu object itself is never replaced, which
        # prevents the Win32 menu from losing its hover state mid-display.

        def _is_idle(_item=None):
            return self._get_state() == RecorderState.IDLE

        def _is_active(_item=None):
            return self._get_state() != RecorderState.IDLE

        def _pause_label(_item=None):
            return "Resume" if self._get_state() == RecorderState.PAUSED else "Pause"

        def _autodetect_label(_item=None):
            return f"Auto-Detect: {'ON' if config.get('auto_detect') else 'OFF'}"

        return pystray.Menu(
            pystray.MenuItem("Start Recording", self._handle_start, enabled=_is_idle),
            pystray.MenuItem("Stop Recording", self._handle_stop, enabled=_is_active),
            pystray.MenuItem(_pause_label, self._handle_pause_resume, visible=_is_active),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Recordings Folder", self._handle_open_folder),
            pystray.MenuItem("Settings...", self._handle_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(_autodetect_label, self._handle_toggle_autodetect),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("View Log", self._handle_view_log),
            pystray.MenuItem("About", self._handle_about),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._handle_quit),
        )

    # --- Handlers (called on pystray's thread; dispatch as needed) ---

    def _handle_start(self, icon, item):
        self._on_start()

    def _handle_stop(self, icon, item):
        self._on_stop()

    def _handle_pause_resume(self, icon, item):
        self._on_pause_resume()

    def _handle_open_folder(self, icon, item):
        self._on_open_folder()

    def _handle_settings(self, icon, item):
        self._on_settings()

    def _handle_toggle_autodetect(self, icon, item):
        self._on_toggle_autodetect()

    def _handle_view_log(self, icon, item):
        self._on_view_log()

    def _handle_about(self, icon, item):
        self._on_about()

    def _handle_quit(self, icon, item):
        self._on_quit()
