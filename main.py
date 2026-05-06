"""
Teams Recorder — entry point.

Thread architecture:
  - Main thread:  tkinter mainloop (all Tk/dialog calls happen here)
  - tray thread:  pystray icon + its message loop (daemon)
  - tray-updater: updates icon/tooltip every 0.5 s (daemon)
  - detector:     polls Teams audio (daemon)
  - mixer:        real-time audio mixing (daemon)
  - mp3-convert:  background MP3 export (daemon)

Tray callbacks arrive on the tray thread. Any function that touches tkinter
is dispatched to the main thread via _dispatch().
"""

import logging
import logging.handlers
import os
import queue
import re
import sys
import threading
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable, Optional
import tkinter as tk

from config import config
from platform_utils import (
    PLATFORM,
    acquire_single_instance,
    release_single_instance,
    get_config_dir,
    open_path,
)

APP_NAME = "Teams Recorder"
APP_VERSION = "1.0.0"

# Persistent Tk root created once on the main thread.
_tk_root: Optional[tk.Tk] = None
_dispatch_queue: queue.Queue[Callable[[], Any]] = queue.Queue()


# ---------------------------------------------------------------------------
# Thread-to-main-thread dispatch
# ---------------------------------------------------------------------------

def _dispatch(fn: Callable[[], Any]) -> None:
    """Schedule fn to run on the main (tkinter) thread. Safe from any thread."""
    _dispatch_queue.put(fn)


def _process_dispatch_queue() -> None:
    while True:
        try:
            fn = _dispatch_queue.get_nowait()
        except queue.Empty:
            break
        try:
            fn()
        except Exception as e:
            logger.error("Dispatched callback failed: %s", e, exc_info=True)
    if _tk_root is not None:
        _tk_root.after(50, _process_dispatch_queue)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        str(log_path), maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if os.environ.get("TEAMS_REC_DEBUG"):
        root.addHandler(logging.StreamHandler(sys.stderr))


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ffmpeg path setup
# ---------------------------------------------------------------------------

def _setup_ffmpeg() -> None:
    from pydub import AudioSegment

    cfg_path = config.get("ffmpeg_path", "")
    if cfg_path and Path(cfg_path).exists():
        AudioSegment.converter = cfg_path
        logger.info("ffmpeg path from config: %s", cfg_path)
        return

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
# Startup dialogs (run on main thread before tray thread starts)
# ---------------------------------------------------------------------------

def _show_consent_if_needed() -> None:
    if not config.get("first_run", True):
        return

    accepted = messagebox.askyesno(
        "Legal Notice — Teams Recorder",
        "Recording calls may be regulated by law in your jurisdiction.\n\n"
        "Many regions require explicit consent from all parties before recording.\n\n"
        "By clicking Yes, you confirm that you will comply with all applicable "
        "call recording laws in your jurisdiction and obtain any required consent.\n\n"
        "Do you accept?",
        parent=_tk_root,
    )
    if not accepted:
        sys.exit(0)

    config.set("first_run", False)
    config.save()


def _check_orphaned_wav() -> None:
    if not config.get("recording_in_progress", False):
        return

    temp_path = config.get("recording_temp_path", "")
    config.set("recording_in_progress", False)
    config.set("recording_temp_path", "")
    config.save()

    if not temp_path or not Path(temp_path).exists():
        return

    keep = messagebox.askyesno(
        "Interrupted Recording",
        f"A previous recording was interrupted:\n{temp_path}\n\nKeep the partial file?",
        parent=_tk_root,
    )
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

def notify(title: str, message: str) -> None:
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
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    global _tk_root

    early_log = get_config_dir() / "app.log"
    _setup_logging(early_log)
    logger.info("Teams Recorder %s starting (platform=%s)", APP_VERSION, PLATFORM)

    # Single-instance check before creating the persistent root
    if not acquire_single_instance():
        _tmp = tk.Tk()
        _tmp.withdraw()
        messagebox.showinfo(APP_NAME, "Teams Recorder is already running.", parent=_tmp)
        _tmp.destroy()
        sys.exit(0)

    # Create the persistent Tk root on the main thread.
    # All subsequent tkinter calls must happen on this thread.
    _tk_root = tk.Tk()
    _tk_root.withdraw()
    _tk_root.protocol("WM_DELETE_WINDOW", lambda: None)  # ignore accidental close
    _tk_root.after(50, _process_dispatch_queue)

    config.load()
    _setup_logging(config.log_path)

    try:
        _setup_ffmpeg()
    except Exception as e:
        logger.warning("ffmpeg setup error: %s", e)

    # These run on the main thread before the tray thread starts — safe.
    _show_consent_if_needed()
    _check_orphaned_wav()

    from recorder import Recorder, RecorderState

    recorder = Recorder(on_state_change=lambda s: logger.debug("Recorder state → %s", s))

    from detector import Detector

    def on_call_start() -> None:
        if recorder.state != RecorderState.IDLE:
            return
        recorder.start_recording()

    def on_call_end() -> None:
        if recorder.state == RecorderState.IDLE:
            return
        # Dispatch to main thread: the save dialog must run there.
        _dispatch(lambda: _finish_recording(recorder))

    detector = Detector(on_call_start=on_call_start, on_call_end=on_call_end)
    if config.get("auto_detect", True):
        detector.start()

    # ------------------------------------------------------------------
    # Tray action callbacks.
    # These are called from the pystray (tray) thread.
    # Audio/config ops are thread-safe.
    # Anything that opens a tkinter window uses _dispatch().
    # ------------------------------------------------------------------

    def start_recording() -> None:
        if recorder.state != RecorderState.IDLE:
            notify(APP_NAME, "Already recording.")
            return
        ok = recorder.start_recording()
        if ok:
            notify(APP_NAME, "Recording started.")
        else:
            notify(APP_NAME, "Error: could not start recording. Check audio devices.")

    def stop_recording() -> None:
        if recorder.state == RecorderState.IDLE:
            return
        _dispatch(lambda: _finish_recording(recorder))

    def pause_resume() -> None:
        if recorder.state == RecorderState.RECORDING:
            recorder.pause()
        elif recorder.state == RecorderState.PAUSED:
            recorder.resume()

    def open_folder() -> None:
        folder = config.get(
            "output_folder", str(Path.home() / "Documents" / "Teams Recordings")
        )
        Path(folder).mkdir(parents=True, exist_ok=True)
        open_path(folder)

    def open_settings() -> None:
        from settings_window import open_settings as _open
        _dispatch(lambda: _open(parent=_tk_root))

    def toggle_autodetect() -> None:
        new_val = not config.get("auto_detect", True)
        config.set("auto_detect", new_val)
        config.save()
        if new_val:
            detector.start()
        else:
            detector.stop()

    def view_log() -> None:
        if config.log_path.exists():
            open_path(config.log_path)

    def show_about() -> None:
        _dispatch(lambda: messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME} v{APP_VERSION}\n\n"
            "Records Microsoft Teams PSTN calls by capturing microphone input\n"
            "and system audio output simultaneously.\n\n"
            "⚠ Legal Notice: You are responsible for complying with all applicable\n"
            "call recording laws in your jurisdiction and for obtaining any\n"
            "required consent from other parties.",
            parent=_tk_root,
        ))

    def quit_app() -> None:
        def _do_quit() -> None:
            logger.info("Quitting")
            detector.stop()
            if recorder.state != RecorderState.IDLE:
                _finish_recording(recorder)
            release_single_instance()
            tray.stop()
            _tk_root.quit()

        _dispatch(_do_quit)

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

    # Run pystray in a daemon thread so the main thread is free to run
    # the tkinter event loop.  All tray callbacks will arrive on this thread
    # and dispatch UI work via _dispatch() to the main thread.
    tray_thread = threading.Thread(target=tray.run, daemon=True, name="tray")
    tray_thread.start()

    logger.info("Entering tkinter mainloop")
    _tk_root.mainloop()
    logger.info("Exited mainloop — bye")


# ---------------------------------------------------------------------------
# Save-name dialog (must be called on main thread)
# ---------------------------------------------------------------------------

def _ask_save_name(default_stem: str) -> str:
    result = {"stem": default_stem}

    dlg = tk.Toplevel(_tk_root)
    dlg.title("Save Recording As")
    dlg.resizable(False, False)
    try:
        dlg.grab_set()
    except tk.TclError:
        pass
    dlg.lift()
    dlg.focus_force()

    pad = {"padx": 12, "pady": 6}

    tk.Label(dlg, text="Recording name:", anchor="w").grid(
        row=0, column=0, columnspan=2, sticky="w", **pad
    )

    entry_var = tk.StringVar(value=default_stem)
    entry = tk.Entry(dlg, textvariable=entry_var, width=52)
    entry.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 4))
    entry.select_range(0, tk.END)
    entry.focus_set()

    tk.Label(
        dlg,
        text="Extension (.wav / .mp3) will be added automatically.",
        fg="gray",
        font=("TkDefaultFont", 8),
    ).grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 8))

    _ILLEGAL = re.compile(r'[\\/:*?"<>|]')

    def _save(_event=None) -> None:
        chosen = entry_var.get().strip()
        if chosen:
            chosen = _ILLEGAL.sub("_", chosen).strip(". ")
            result["stem"] = chosen or default_stem
        dlg.destroy()

    def _keep_default() -> None:
        dlg.destroy()

    btn_frame = tk.Frame(dlg)
    btn_frame.grid(row=3, column=0, columnspan=2, sticky="e", padx=12, pady=(0, 10))
    tk.Button(btn_frame, text="Keep Default Name", command=_keep_default, width=18).pack(
        side="left", padx=(0, 6)
    )
    tk.Button(btn_frame, text="Save", command=_save, width=10, default="active").pack(
        side="left"
    )

    entry.bind("<Return>", _save)
    dlg.protocol("WM_DELETE_WINDOW", _keep_default)

    dlg.update_idletasks()
    w, h = dlg.winfo_width(), dlg.winfo_height()
    sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
    dlg.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    dlg.wait_window()
    return result["stem"]


# ---------------------------------------------------------------------------
# Finish recording (must be called on main thread)
# ---------------------------------------------------------------------------

def _finish_recording(recorder: Any) -> None:
    from recorder import convert_to_mp3
    from utils import unique_path

    wav_paths = recorder.stop_recording()
    if not wav_paths:
        return

    first_wav = wav_paths[0]
    chosen_stem = _ask_save_name(first_wav.stem)
    folder = config.get(
        "output_folder", str(Path.home() / "Documents" / "Teams Recordings")
    )

    finalized_paths: list[Path] = []
    for index, wav_path in enumerate(wav_paths, start=1):
        target_stem = chosen_stem if index == 1 else f"{chosen_stem} (part_{index})"
        if target_stem == wav_path.stem:
            finalized_paths.append(wav_path)
            continue

        new_wav = unique_path(folder, target_stem, ".wav")
        try:
            wav_path.rename(new_wav)
            finalized_paths.append(new_wav)
            logger.info("Recording renamed to: %s", new_wav)
        except OSError as e:
            logger.warning("Could not rename recording: %s — keeping original name", e)
            finalized_paths.append(wav_path)

    fmt = config.get("file_format", "wav")
    if fmt == "mp3":
        remaining = {"count": len(finalized_paths), "failed": False}
        remaining_lock = threading.Lock()

        def _on_converted(mp3_path: Optional[Path]) -> None:
            with remaining_lock:
                if mp3_path is None:
                    remaining["failed"] = True
                remaining["count"] -= 1
                done = remaining["count"] == 0
                failed = remaining["failed"]

            if not done:
                return
            if failed:
                notify(APP_NAME, "Saved as WAV (one or more MP3 conversions failed).")
                return
            if len(finalized_paths) == 1:
                name = finalized_paths[0].with_suffix(".mp3").name
                notify(APP_NAME, f"Recording saved: {name}")
                return
            notify(APP_NAME, f"Recording saved: {len(finalized_paths)} MP3 parts.")

        for wav_path in finalized_paths:
            convert_to_mp3(wav_path, on_done=_on_converted)
    else:
        if len(finalized_paths) == 1:
            notify(APP_NAME, f"Recording saved: {finalized_paths[0].name}")
        else:
            notify(APP_NAME, f"Recording saved: {len(finalized_paths)} WAV parts.")


if __name__ == "__main__":
    main()
