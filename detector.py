import logging
import threading
import time
from typing import Callable, Optional

from config import config

logger = logging.getLogger(__name__)

TEAMS_PROCESS_NAMES = {"teams.exe", "ms-teams.exe", "msteams.exe"}
POLL_INTERVAL = 2.0
ACTIVE_THRESHOLD = 2      # consecutive active checks before triggering start
INACTIVE_THRESHOLD = 5    # consecutive inactive checks before triggering stop


class Detector:
    def __init__(
        self,
        on_call_start: Callable[[], None],
        on_call_end: Callable[[], None],
    ):
        self._on_call_start = on_call_start
        self._on_call_end = on_call_end
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active_count = 0
        self._inactive_count = 0
        self._in_call = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="detector")
        self._thread.start()
        logger.info("Detector started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Detector stopped")

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                active = self._is_teams_audio_active()
            except Exception as e:
                logger.warning("Detector poll error: %s", e)
                active = False

            if active:
                self._active_count += 1
                self._inactive_count = 0
            else:
                self._inactive_count += 1
                self._active_count = 0

            if not self._in_call and self._active_count >= ACTIVE_THRESHOLD:
                self._in_call = True
                self._inactive_count = 0
                logger.info("Teams audio detected — triggering recording start")
                try:
                    self._on_call_start()
                except Exception as e:
                    logger.error("on_call_start error: %s", e)

            elif self._in_call and self._inactive_count >= INACTIVE_THRESHOLD:
                self._in_call = False
                self._active_count = 0
                logger.info("Teams audio gone — triggering recording stop")
                try:
                    self._on_call_end()
                except Exception as e:
                    logger.error("on_call_end error: %s", e)

            self._stop_event.wait(timeout=POLL_INTERVAL)

    def _is_teams_audio_active(self) -> bool:
        try:
            from pycaw.pycaw import AudioUtilities, AudioSessionState
        except ImportError:
            logger.warning("pycaw not available — auto-detect disabled")
            return False

        sessions = AudioUtilities.GetAllSessions()
        for session in sessions:
            try:
                proc = session.Process
                if proc is None:
                    continue
                name = proc.name().lower()
                if name not in TEAMS_PROCESS_NAMES:
                    continue

                if session.State != AudioSessionState.Active:
                    continue

                # Check peak meter value
                meter = session._ctl.QueryInterface(
                    _get_audio_meter_interface()
                )
                peak = meter.GetPeakValue()
                if peak > 0.0:
                    return True
            except Exception:
                continue

        return False


def _get_audio_meter_interface():
    from ctypes import POINTER
    from pycaw.pycaw import IAudioMeterInformation
    return IAudioMeterInformation
