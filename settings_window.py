import logging
import os
import tkinter as tk
import winreg
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from config import config
from utils import preview_filename

logger = logging.getLogger(__name__)

APP_NAME = "TeamsRecorder"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def open_settings(parent=None):
    win = SettingsWindow(parent)
    win.show()


class SettingsWindow:
    def __init__(self, parent=None):
        self._parent = parent
        self._root: Optional[tk.Toplevel] = None
        self._vars = {}
        self._working = {}  # copy of config being edited

    def show(self):
        self._working = config.as_dict()

        if self._parent:
            self._root = tk.Toplevel(self._parent)
        else:
            self._root = tk.Tk()
            self._root.withdraw()
            self._root = tk.Toplevel()

        self._root.title("Teams Recorder — Settings")
        self._root.resizable(False, False)
        self._root.grab_set()

        nb = ttk.Notebook(self._root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        nb.add(self._build_output_tab(nb), text="Output")
        nb.add(self._build_audio_tab(nb), text="Audio")
        nb.add(self._build_detection_tab(nb), text="Detection")
        nb.add(self._build_general_tab(nb), text="General")

        self._build_buttons(self._root)
        self._root.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._root.mainloop()

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------

    def _build_output_tab(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=10)

        # Save folder
        ttk.Label(frame, text="Save folder:").grid(row=0, column=0, sticky="w", pady=4)
        folder_var = tk.StringVar(value=self._working.get("output_folder", ""))
        self._vars["output_folder"] = folder_var
        ttk.Entry(frame, textvariable=folder_var, width=40).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ttk.Button(frame, text="Browse…", command=self._browse_folder).grid(row=0, column=2, padx=4)

        # File format
        ttk.Label(frame, text="File format:").grid(row=1, column=0, sticky="w", pady=4)
        fmt_var = tk.StringVar(value=self._working.get("file_format", "mp3").upper())
        self._vars["file_format"] = fmt_var
        ffmpeg_ok = _ffmpeg_available()
        fmt_combo = ttk.Combobox(frame, textvariable=fmt_var, values=["WAV", "MP3"], state="readonly", width=8)
        fmt_combo.grid(row=1, column=1, sticky="w", padx=(4, 0))
        if not ffmpeg_ok:
            fmt_var.set("WAV")
            fmt_combo.configure(state="disabled")
            ttk.Label(frame, text="(ffmpeg not found — MP3 unavailable)", foreground="gray").grid(
                row=1, column=2, sticky="w"
            )

        # MP3 bitrate
        ttk.Label(frame, text="MP3 bitrate:").grid(row=2, column=0, sticky="w", pady=4)
        br_var = tk.StringVar(value=str(self._working.get("mp3_bitrate", 128)))
        self._vars["mp3_bitrate"] = br_var
        br_combo = ttk.Combobox(frame, textvariable=br_var, values=["64", "128", "192"], state="readonly", width=8)
        br_combo.grid(row=2, column=1, sticky="w", padx=(4, 0))
        ttk.Label(frame, text="kbps").grid(row=2, column=2, sticky="w")

        def _toggle_bitrate(*_):
            br_combo.configure(state="readonly" if fmt_var.get() == "MP3" else "disabled")

        fmt_var.trace_add("write", _toggle_bitrate)
        _toggle_bitrate()

        # Separator
        ttk.Separator(frame, orient="horizontal").grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)

        # Filename template
        ttk.Label(frame, text="Filename template:").grid(row=4, column=0, sticky="w", pady=4)
        tpl_var = tk.StringVar(value=self._working.get("filename_template", "TeamsCall_{date}_{time}"))
        self._vars["filename_template"] = tpl_var
        ttk.Entry(frame, textvariable=tpl_var, width=40).grid(row=4, column=1, columnspan=2, sticky="ew", padx=(4, 0))

        ttk.Label(frame, text="Placeholders: {date} {time} {datetime} {user} {counter}", foreground="gray").grid(
            row=5, column=0, columnspan=3, sticky="w"
        )

        preview_var = tk.StringVar()
        self._vars["_preview"] = preview_var
        ttk.Label(frame, text="Preview:").grid(row=6, column=0, sticky="w", pady=4)
        ttk.Label(frame, textvariable=preview_var, foreground="#005500").grid(
            row=6, column=1, columnspan=2, sticky="w", padx=(4, 0)
        )

        # Date / Time format
        ttk.Label(frame, text="Date format:").grid(row=7, column=0, sticky="w", pady=4)
        date_var = tk.StringVar(value=self._working.get("date_format", "YYYYMMDD"))
        self._vars["date_format"] = date_var
        ttk.Combobox(
            frame, textvariable=date_var,
            values=["YYYYMMDD", "YYYY-MM-DD", "DDMMYYYY"],
            state="readonly", width=14,
        ).grid(row=7, column=1, sticky="w", padx=(4, 0))

        ttk.Label(frame, text="Time format:").grid(row=8, column=0, sticky="w", pady=4)
        time_var = tk.StringVar(value=self._working.get("time_format", "HHMMSS"))
        self._vars["time_format"] = time_var
        ttk.Combobox(
            frame, textvariable=time_var,
            values=["HHMMSS", "HH-MM-SS"],
            state="readonly", width=14,
        ).grid(row=8, column=1, sticky="w", padx=(4, 0))

        def _update_preview(*_):
            try:
                preview = preview_filename(tpl_var.get(), date_var.get(), time_var.get())
                preview_var.set(preview)
            except Exception:
                preview_var.set("(invalid template)")

        tpl_var.trace_add("write", _update_preview)
        date_var.trace_add("write", _update_preview)
        time_var.trace_add("write", _update_preview)
        _update_preview()

        frame.columnconfigure(1, weight=1)
        return frame

    def _build_audio_tab(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=10)

        mic_devices = _list_input_devices()
        spk_devices = _list_output_devices()

        ttk.Label(frame, text="Microphone:").grid(row=0, column=0, sticky="w", pady=4)
        mic_var = tk.StringVar(value=self._working.get("mic_device", "default"))
        self._vars["mic_device"] = mic_var
        ttk.Combobox(frame, textvariable=mic_var, values=mic_devices, state="readonly", width=36).grid(
            row=0, column=1, sticky="ew", padx=(4, 0)
        )

        ttk.Label(frame, text="Speaker (loopback):").grid(row=1, column=0, sticky="w", pady=4)
        spk_var = tk.StringVar(value=self._working.get("speaker_device", "default"))
        self._vars["speaker_device"] = spk_var
        ttk.Combobox(frame, textvariable=spk_var, values=spk_devices, state="readonly", width=36).grid(
            row=1, column=1, sticky="ew", padx=(4, 0)
        )

        ttk.Label(frame, text="Sample rate:").grid(row=2, column=0, sticky="w", pady=4)
        sr_var = tk.StringVar(value=str(self._working.get("sample_rate", 48000)))
        self._vars["sample_rate"] = sr_var
        ttk.Combobox(frame, textvariable=sr_var, values=["44100", "48000"], state="readonly", width=10).grid(
            row=2, column=1, sticky="w", padx=(4, 0)
        )

        ttk.Label(frame, text="Channels:").grid(row=3, column=0, sticky="w", pady=4)
        ch_var = tk.StringVar(value="Mono" if self._working.get("channels", 1) == 1 else "Stereo")
        self._vars["channels"] = ch_var
        ttk.Combobox(frame, textvariable=ch_var, values=["Mono", "Stereo"], state="readonly", width=10).grid(
            row=3, column=1, sticky="w", padx=(4, 0)
        )

        frame.columnconfigure(1, weight=1)
        return frame

    def _build_detection_tab(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=10)

        auto_var = tk.BooleanVar(value=self._working.get("auto_detect", True))
        self._vars["auto_detect"] = auto_var
        ttk.Checkbutton(frame, text="Auto-detect Teams audio", variable=auto_var).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=4
        )

        ttk.Label(frame, text="Auto-stop delay (seconds):").grid(row=1, column=0, sticky="w", pady=4)
        delay_var = tk.StringVar(value=str(self._working.get("auto_stop_delay_seconds", 10)))
        self._vars["auto_stop_delay_seconds"] = delay_var
        ttk.Spinbox(frame, textvariable=delay_var, from_=5, to=120, width=8).grid(
            row=1, column=1, sticky="w", padx=(4, 0)
        )

        ttk.Label(frame, text="Max recording length (hours):").grid(row=2, column=0, sticky="w", pady=4)
        max_var = tk.StringVar(value=str(self._working.get("max_recording_hours", 4)))
        self._vars["max_recording_hours"] = max_var
        ttk.Spinbox(frame, textvariable=max_var, from_=1, to=24, width=8).grid(
            row=2, column=1, sticky="w", padx=(4, 0)
        )

        frame.columnconfigure(1, weight=1)
        return frame

    def _build_general_tab(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=10)

        startup_var = tk.BooleanVar(value=self._working.get("start_with_windows", False))
        self._vars["start_with_windows"] = startup_var
        ttk.Checkbutton(frame, text="Start with Windows", variable=startup_var).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=4
        )

        notif_var = tk.BooleanVar(value=self._working.get("show_notifications", True))
        self._vars["show_notifications"] = notif_var
        ttk.Checkbutton(frame, text="Show notifications", variable=notif_var).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=4
        )

        ttk.Label(frame, text="Minimize to tray on close: always", foreground="gray").grid(
            row=2, column=0, columnspan=2, sticky="w"
        )

        frame.columnconfigure(1, weight=1)
        return frame

    def _build_buttons(self, parent):
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btn_frame, text="Reset to Defaults", command=self._on_reset).pack(side="left")
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side="right", padx=4)
        ttk.Button(btn_frame, text="Save", command=self._on_save).pack(side="right")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _browse_folder(self):
        current = self._vars["output_folder"].get()
        chosen = filedialog.askdirectory(initialdir=current or str(Path.home()), title="Select save folder")
        if chosen:
            self._vars["output_folder"].set(chosen)

    def _on_save(self):
        updates = self._collect_values()
        if updates is None:
            return
        config.update_from_dict(updates)
        _apply_startup(updates.get("start_with_windows", False))
        logger.info("Settings saved")
        self._root.destroy()

    def _on_cancel(self):
        self._root.destroy()

    def _on_reset(self):
        if messagebox.askyesno("Reset", "Reset all settings to defaults?", parent=self._root):
            config.reset_to_defaults()
            self._root.destroy()
            logger.info("Settings reset to defaults")

    def _collect_values(self) -> Optional[dict]:
        try:
            fmt = self._vars["file_format"].get().lower()
            ch_str = self._vars["channels"].get()
            channels = 1 if ch_str == "Mono" else 2

            return {
                "output_folder": self._vars["output_folder"].get().strip(),
                "file_format": fmt,
                "mp3_bitrate": int(self._vars["mp3_bitrate"].get()),
                "filename_template": self._vars["filename_template"].get().strip(),
                "date_format": self._vars["date_format"].get(),
                "time_format": self._vars["time_format"].get(),
                "mic_device": self._vars["mic_device"].get(),
                "speaker_device": self._vars["speaker_device"].get(),
                "sample_rate": int(self._vars["sample_rate"].get()),
                "channels": channels,
                "auto_detect": bool(self._vars["auto_detect"].get()),
                "auto_stop_delay_seconds": int(self._vars["auto_stop_delay_seconds"].get()),
                "max_recording_hours": int(self._vars["max_recording_hours"].get()),
                "start_with_windows": bool(self._vars["start_with_windows"].get()),
                "show_notifications": bool(self._vars["show_notifications"].get()),
            }
        except (ValueError, KeyError) as e:
            messagebox.showerror("Invalid input", str(e), parent=self._root)
            return None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _ffmpeg_available() -> bool:
    import shutil
    from pydub.utils import get_encoder_name
    ffmpeg_path = config.get("ffmpeg_path", "")
    if ffmpeg_path and Path(ffmpeg_path).exists():
        return True
    return shutil.which("ffmpeg") is not None


def _list_input_devices() -> list[str]:
    devices = ["default"]
    try:
        import pyaudiowpatch as pyaudio
        p = pyaudio.PyAudio()
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                devices.append(info["name"])
        p.terminate()
    except Exception as e:
        logger.warning("Could not enumerate input devices: %s", e)
    return devices


def _list_output_devices() -> list[str]:
    devices = ["default"]
    try:
        import pyaudiowpatch as pyaudio
        p = pyaudio.PyAudio()
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info["maxOutputChannels"] > 0:
                devices.append(info["name"])
        p.terminate()
    except Exception as e:
        logger.warning("Could not enumerate output devices: %s", e)
    return devices


def _apply_startup(enable: bool):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        if enable:
            exe = sys.executable
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
            logger.info("Added to startup: %s", exe)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
                logger.info("Removed from startup")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except OSError as e:
        logger.warning("Registry startup update failed: %s", e)
