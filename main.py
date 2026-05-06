"""
Teams Recorder — entry point.

Launch order:
  1. Setup logging
  2. Single-instance mutex
  3. Load config / setup ffmpeg path
  4. First-run consent dialog
  5. Orphaned WAV check
  6. Wire up Recorder, Detector, TrayIcon
  7. Start tray (blocks until quit)
"""

import ctypes
import logging
import logging.handlers
import os
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import messagebox
import tkinter as tk

APP_NAME = "Teams Recorder"
APP_VERSION = "1.0.0"
MUTEX_NAME = "TeamsRecorderSingleInstance"

# ---------------------------------------------------------------------------
# Logging setup (called before config so we can log config load errors)
# ---------------------------------------------------------------------------

def _setup_logging(log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        str(log_path), maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Also log to stderr in debug mode
    if os.environ.get("TEAMS_REC_DEBUG"):
        root.addHandler(logging.StreamHandler(sys.stderr))


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single-instance lock
# ---------------------------------------------------------------------------

_mutex_handle = None

def _acquire_single_instance() -> bool:
    global _mutex_handle
    kernel32 = ctypes.windll.kernel32
    _mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_err = kernel32.GetLastError()
    if last_err == 183:  # ERROR_ALREADY_EXISTS
        return False
    return True


def _release_single_instance():
    global _mutex_handle
    if _mutex_handle:
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None


# ---------------------------------------------------------------------------
# ffmpeg path setup
# ---------------------------------------------------------------------------

def _setup_ffmpeg():
    from pydub import AudioSegment

    cfg_path = config.get("ffmpeg_path", "")
    if cfg_path and Path(cfg_path).exists():
        AudioSegment.converter = cfg_path
        logger.info("ffmpeg path from config: %s", cfg_path)
        return

    # When running as a PyInstaller bundle, check next to the executable
    exe_dir = Path(sys.executable).parent
    local_ffmpeg = exe_dir / "ffmpeg.exe"
    if local_ffmpeg.exists():
        AudioSegment.converter = str(local_ffmpeg)
        logger.info("ffmpeg found next to executable: %s", local_ffmpeg)
        return

    import shutil
    if shutil.which("ffmpeg"):
        logger.info("ffmpeg found on PATH")
        return

    logger.warning("ffmpeg not found — MP3 export disabled")


# ---------------------------------------------------------------------------
# First-run consent dialog
# ---------------------------------------------------------------------------

def _show_consent_if_needed():
    if not config.get("first_run", True):
        return

    root = tk.Tk()
    root.withdraw()

    accepted = messagebox.askyesno(
        "Legal Notice — Teams Recorder",
        "Recording calls may be regulated by law in your jurisdiction.\n\n"
        "Many regions require explicit consent from all parties before recording.\n\n"
        "By clicking Yes, you confirm that you will comply with all applicable "
        "call recording laws in your jurisdiction and obtain any required consent.\n\n"
        "Do you accept?",
    )
    root.destroy()

    if not accepted:
        sys.exit(0)

    config.set("first_run", False)
    config.save()


# ---------------------------------------------------------------------------
# Orphaned WAV recovery
# ---------------------------------------------------------------------------

def _check_orphaned_wav():
    if not config.get("recording_in_progress", False):
        return

    temp_path = config.get("recording_temp_path", "")
    config.set("recording_in_progress", False)
    config.set("recording_temp_path", "")
    config.save()

    if not temp_path or not Path(temp_path).exists():
        return

    root = tk.Tk()
    root.withdraw()
    keep = messagebox.askyesno(
        "Interrupted Recording",
        f"A previous recording was interrupted:\n{temp_path}\n\nKeep the partial file?",
    )
    root.destroy()

    if not keep:
        try:
            Path(temp_path).unlink()
            logger.info("Deleted orphaned WAV: %s", temp_path)
        except OSError as e:
            logger.warning("Could not delete orphaned WAV: %s", e)
    else:
        logger.info("Kept orphaned WAV: %s", temp_path)


# ---------------------------------------------------------------------------
# Notification helper
# ---------------------------------------------------------------------------

def notify(title: str, message: str):
    if not config.get("show_notifications", True):
        return
    try:
        from plyer import notification
        notification.notify(
            app_name=APP_NAME,
            title=title,
            message=message,
            timeout=4,
        )
    except Exception as e:
        logger.debug("Notification failed: %s", e)


# ---------------------------------------------------------------------------
# Main application wiring
# ---------------------------------------------------------------------------

def main():
    # --- Logging (temporary path until config loads) ---
    appdata = os.environ.get("APPDATA", str(Path.home()))
    early_log = Path(appdata) / "TeamsRecorder" / "app.log"
    _setup_logging(early_log)

    logger.info("Teams Recorder %s starting", APP_VERSION)

    # --- Single instance ---
    if not _acquire_single_instance():
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(APP_NAME, "Teams Recorder is already running.")
        root.destroy()
        sys.exit(0)

    # --- Config ---
    from config import config
    config.load()
    _setup_logging(config.log_path)  # re-init with correct path

    # --- ffmpeg ---
    try:
        _setup_ffmpeg()
    except Exception as e:
        logger.warning("ffmpeg setup error: %s", e)

    # --- First-run consent ---
    _show_consent_if_needed()

    # --- Orphaned WAV ---
    _check_orphaned_wav()

    # --- Recorder ---
    from recorder import Recorder, RecorderState, convert_to_mp3

    def on_state_change(new_state: str):
        logger.debug("Recorder state → %s", new_state)

    recorder = Recorder(on_state_change=on_state_change)

    # --- Detector ---
    from detector import Detector

    def on_call_start():
        if recorder.state != RecorderState.IDLE:
            return
        recorder.start_recording()

    def on_call_end():
        if recorder.state == RecorderState.IDLE:
            return
        _finish_recording(recorder)

    detector = Detector(on_call_start=on_call_start, on_call_end=on_call_end)
    if config.get("auto_detect", True):
        detector.start()

    # --- Tray actions ---

    def start_recording():
        if recorder.state != RecorderState.IDLE:
            notify(APP_NAME, "Already recording.")
            return
        ok = recorder.start_recording()
        if ok:
            notify(APP_NAME, "Recording started.")
        else:
            notify(APP_NAME, "Error: could not start recording. Check audio devices.")

    def stop_recording():
        if recorder.state == RecorderState.IDLE:
            return
        _finish_recording(recorder)

    def pause_resume():
        if recorder.state == RecorderState.RECORDING:
            recorder.pause()
        elif recorder.state == RecorderState.PAUSED:
            recorder.resume()

    def open_folder():
        folder = config.get("output_folder", str(Path.home() / "Documents" / "Teams Recordings"))
        Path(folder).mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def open_settings():
        from settings_window import open_settings as _open
        _open()

    def toggle_autodetect():
        new_val = not config.get("auto_detect", True)
        config.set("auto_detect", new_val)
        config.save()
        if new_val:
            detector.start()
        else:
            detector.stop()

    def view_log():
        if config.log_path.exists():
            os.startfile(str(config.log_path))

    def show_about():
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME} v{APP_VERSION}\n\n"
            "Records Microsoft Teams PSTN calls by capturing microphone input\n"
            "and system audio output simultaneously.\n\n"
            "⚠ Legal Notice: You are responsible for complying with all applicable\n"
            "call recording laws in your jurisdiction and for obtaining any\n"
            "required consent from other parties.\n\n"
            "Click OK then visit the project page for more information.",
        )
        root.destroy()

    def quit_app():
        logger.info("Quitting")
        detector.stop()
        if recorder.state != RecorderState.IDLE:
            _finish_recording(recorder)
        _release_single_instance()
        tray.stop()

    # --- Tray icon ---
    from tray_icon import TrayIcon

    tray = TrayIcon(
        on_start=start_recording,
        on_stop=stop_recording,
        on_pause_resume=pause_resume,
        on_open_folder=open_folder,
        on_settings=open_settings,
        on_toggle_autodetect=toggle_autodetect,
        on_view_log=view_log,
        on_about=show_about,
        on_quit=quit_app,
        get_recorder_state=lambda: recorder.state,
        get_elapsed=lambda: recorder.elapsed_seconds,
    )

    logger.info("Entering tray loop")
    tray.run()
    logger.info("Exited tray loop — bye")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finish_recording(recorder):
    from recorder import convert_to_mp3

    wav_path = recorder.stop_recording()
    if wav_path is None:
        return

    fmt = config.get("file_format", "wav")
    if fmt == "mp3":
        def _on_converted(mp3_path):
            if mp3_path:
                notify(APP_NAME, f"Recording saved: {mp3_path.name}")
            else:
                notify(APP_NAME, f"Saved as WAV (MP3 conversion failed): {wav_path.name}")

        convert_to_mp3(wav_path, on_done=_on_converted)
    else:
        notify(APP_NAME, f"Recording saved: {wav_path.name}")


if __name__ == "__main__":
    main()
