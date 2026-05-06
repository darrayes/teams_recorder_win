import logging
import threading
from typing import Callable, Optional

from config import config
from platform_utils import PLATFORM

logger = logging.getLogger(__name__)

TEAMS_PROCESS_NAMES = {"teams", "teams.exe", "ms-teams.exe", "msteams.exe", "msteams"}
POLL_INTERVAL = 2.0
ACTIVE_THRESHOLD = 2    # consecutive active checks before triggering start


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
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="detector"
        )
        self._thread.start()
        logger.info("Detector started (platform=%s)", PLATFORM)

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

            elif self._in_call and self._inactive_seconds() >= self._stop_delay_seconds():
                self._in_call = False
                self._active_count = 0
                logger.info("Teams audio gone — triggering recording stop")
                try:
                    self._on_call_end()
                except Exception as e:
                    logger.error("on_call_end error: %s", e)

            self._stop_event.wait(timeout=POLL_INTERVAL)

    def _inactive_seconds(self) -> float:
        return self._inactive_count * POLL_INTERVAL

    def _stop_delay_seconds(self) -> float:
        try:
            return max(float(config.get("auto_stop_delay_seconds", 10)), POLL_INTERVAL)
        except (TypeError, ValueError):
            return 10.0

    def _is_teams_audio_active(self) -> bool:
        if PLATFORM == "Windows":
            return self._detect_windows()
        return self._detect_unix()

    # ------------------------------------------------------------------
    # Windows: pycaw — checks Teams audio session peak meter
    # ------------------------------------------------------------------

    def _detect_windows(self) -> bool:
        try:
            from pycaw.pycaw import AudioUtilities, AudioSessionState, IAudioMeterInformation
        except ImportError:
            logger.warning("pycaw not available — auto-detect disabled on Windows")
            return False

        sessions = AudioUtilities.GetAllSessions()
        for session in sessions:
            try:
                proc = session.Process
                if proc is None:
                    continue
                if proc.name().lower() not in TEAMS_PROCESS_NAMES:
                    continue
                if session.State != AudioSessionState.Active:
                    continue
                meter = session._ctl.QueryInterface(IAudioMeterInformation)
                if meter.GetPeakValue() > 0.0:
                    return True
            except Exception:
                continue
        return False

    # ------------------------------------------------------------------
    # macOS / Linux: psutil — checks if Teams is running AND has an open
    # audio device (audio file handles contain "audio", "sound", "coreaudio",
    # "pulse", "alsa" in their path on the respective platforms).
    # Falls back to process-running-only check if psutil isn't available.
    # ------------------------------------------------------------------

    def _detect_unix(self) -> bool:
        try:
            import psutil
        except ImportError:
            logger.warning("psutil not available — auto-detect disabled on this platform")
            return False

        audio_path_keywords = ("audio", "sound", "pulse", "alsa", "coreaudio", "core audio")

        for proc in psutil.process_iter(["name", "status"]):
            try:
                name = proc.info["name"].lower() if proc.info["name"] else ""
                # Strip extension for cross-platform matching
                stem = name.replace(".exe", "").replace(".app", "")
                if stem not in TEAMS_PROCESS_NAMES:
                    continue
                if proc.info["status"] not in (
                    psutil.STATUS_RUNNING, psutil.STATUS_SLEEPING
                ):
                    continue

                # Try to check if it has audio file handles open
                try:
                    open_files = proc.open_files()
                    has_audio = any(
                        any(kw in f.path.lower() for kw in audio_path_keywords)
                        for f in open_files
                    )
                    if has_audio:
                        return True
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    # Can't inspect file handles — process exists, treat as active
                    return True

            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue

        return False
