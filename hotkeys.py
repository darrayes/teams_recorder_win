import ctypes
import ctypes.wintypes
import logging
import threading
from typing import Callable

from platform_utils import PLATFORM

logger = logging.getLogger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
WM_HOTKEY = 0x0312

HOTKEY_TOGGLE_RECORDING = 1
HOTKEY_PAUSE_RESUME = 2
HOTKEY_TOGGLE_FLOATING_BAR = 3

VK_R = 0x52
VK_P = 0x50
VK_B = 0x42


class HotkeyManager:
    def __init__(
        self,
        on_toggle_recording: Callable[[], None],
        on_pause_resume: Callable[[], None],
        on_toggle_floating_bar: Callable[[], None],
    ):
        self._on_toggle_recording = on_toggle_recording
        self._on_pause_resume = on_pause_resume
        self._on_toggle_floating_bar = on_toggle_floating_bar
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._thread_id: int | None = None
        self._registered = False

    def start(self) -> None:
        if PLATFORM != "Windows":
            logger.info("Global hotkeys are only available on Windows")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="hotkeys")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if PLATFORM == "Windows" and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._thread_id = None

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()

        hotkeys = (
            (HOTKEY_TOGGLE_RECORDING, MOD_CONTROL | MOD_ALT, VK_R),
            (HOTKEY_PAUSE_RESUME, MOD_CONTROL | MOD_ALT, VK_P),
            (HOTKEY_TOGGLE_FLOATING_BAR, MOD_CONTROL | MOD_ALT, VK_B),
        )

        try:
            for hotkey_id, modifiers, key in hotkeys:
                if not user32.RegisterHotKey(None, hotkey_id, modifiers, key):
                    logger.warning("Could not register hotkey id=%s", hotkey_id)
                else:
                    self._registered = True

            msg = ctypes.wintypes.MSG()
            while not self._stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                if msg.message == WM_HOTKEY:
                    self._handle_hotkey(int(msg.wParam))
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            logger.warning("Hotkey loop stopped: %s", e)
        finally:
            if self._registered:
                for hotkey_id, _, _ in hotkeys:
                    user32.UnregisterHotKey(None, hotkey_id)
            self._registered = False

    def _handle_hotkey(self, hotkey_id: int) -> None:
        if hotkey_id == HOTKEY_TOGGLE_RECORDING:
            self._on_toggle_recording()
        elif hotkey_id == HOTKEY_PAUSE_RESUME:
            self._on_pause_resume()
        elif hotkey_id == HOTKEY_TOGGLE_FLOATING_BAR:
            self._on_toggle_floating_bar()
