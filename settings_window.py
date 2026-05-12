import logging
from datetime import datetime as _dt
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from config import config
from platform_utils import PLATFORM, set_startup
from utils import DATE_FORMATS, TIME_FORMATS, preview_filename

logger = logging.getLogger(__name__)

APP_NAME = "TeamsRecorder"
APP_VERSION = "1.0.0"

_STARTUP_LABEL = {
    "Windows": "Launch at login",
    "Darwin": "Launch at login",
}.get(PLATFORM, "Launch at login")

BG = "#050505"
SIDEBAR = "#11100e"
SURFACE = "#1b1916"
SURFACE_ALT = "#24211d"
LINE = "#2d2924"
TEXT = "#f6f1ea"
MUTED = "#9a938b"
DIM = "#6f675e"
ACCENT = "#f8b13c"
RED = "#ff454f"
CYAN = "#20c0c7"
PURPLE = "#a779df"
GREEN = "#65bd6a"


def open_settings(parent=None):
    win = SettingsWindow(parent)
    win.show()


class SettingsWindow:
    def __init__(self, parent=None):
        self._parent = parent
        self._root: Optional[tk.Toplevel] = None
        self._tk_root: Optional[tk.Tk] = None
        self._vars = {}
        self._working = {}
        self._nav_buttons: dict[str, tk.Button] = {}
        self._content: Optional[tk.Frame] = None
        self._canvas: Optional[tk.Canvas] = None

    def show(self):
        self._working = config.as_dict()
        self._vars = {}

        if self._parent:
            self._root = tk.Toplevel(self._parent)
        else:
            self._tk_root = tk.Tk()
            self._tk_root.withdraw()
            self._root = tk.Toplevel(self._tk_root)

        self._root.title("Recorder Settings")
        self._root.configure(bg=BG)
        self._root.geometry("980x620")
        self._root.minsize(920, 580)
        self._root.resizable(True, True)
        try:
            self._root.grab_set()
        except tk.TclError:
            pass

        self._configure_ttk()
        self._build_shell()
        self._set_active("General")
        self._root.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._root.wait_window()
        self._destroy_root()

    # ------------------------------------------------------------------
    # Shell and common UI
    # ------------------------------------------------------------------

    def _configure_ttk(self) -> None:
        style = ttk.Style(self._root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Recorder.TCombobox",
            fieldbackground=SURFACE,
            background=SURFACE,
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=LINE,
            lightcolor=LINE,
            darkcolor=LINE,
            padding=6,
        )
        style.map(
            "Recorder.TCombobox",
            fieldbackground=[("readonly", SURFACE), ("disabled", "#151311")],
            foreground=[("readonly", TEXT), ("disabled", DIM)],
        )
        style.configure(
            "Recorder.TSpinbox",
            fieldbackground=SURFACE,
            background=SURFACE,
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=LINE,
            lightcolor=LINE,
            darkcolor=LINE,
            padding=6,
        )

    def _build_shell(self) -> None:
        outer = tk.Frame(self._root, bg=BG, padx=14, pady=14)
        outer.pack(fill="both", expand=True)

        app = tk.Frame(outer, bg=BG, highlightbackground=LINE, highlightthickness=1)
        app.pack(fill="both", expand=True)
        app.grid_columnconfigure(1, weight=1)
        app.grid_rowconfigure(0, weight=1)

        sidebar = tk.Frame(app, bg=SIDEBAR, width=248)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)

        brand = tk.Frame(sidebar, bg=SIDEBAR)
        brand.pack(fill="x", padx=18, pady=(18, 16))
        tk.Label(
            brand,
            text="⌄",
            width=2,
            bg=SURFACE,
            fg=ACCENT,
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left", padx=(0, 10), ipady=4)
        tk.Label(
            brand,
            text="Settings",
            bg=SIDEBAR,
            fg=TEXT,
            font=("Segoe UI", 15, "bold"),
        ).pack(side="left")

        for name, icon in [
            ("General", "⚙"),
            ("Audio", "♬"),
            ("Hotkeys", "⌨"),
            ("Storage", "▣"),
            ("Cloud & Account", "☁"),
            ("Privacy", "◇"),
            ("Advanced", "△"),
            ("Updates", "↻"),
            ("About", "ⓘ"),
        ]:
            self._add_nav_button(sidebar, name, icon)

        tk.Label(
            sidebar,
            text=f"v{APP_VERSION}",
            bg=SIDEBAR,
            fg=DIM,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(side="bottom", fill="x", padx=22, pady=20)

        main = tk.Frame(app, bg=BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)

        content_wrap = tk.Frame(main, bg=BG)
        content_wrap.grid(row=0, column=0, sticky="nsew", padx=36, pady=(30, 10))
        content_wrap.grid_rowconfigure(0, weight=1)
        content_wrap.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(content_wrap, bg=BG, bd=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(content_wrap, orient="vertical", command=canvas.yview, bg=SIDEBAR)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self._content = tk.Frame(canvas, bg=BG)
        content_window = canvas.create_window((0, 0), window=self._content, anchor="nw")

        def _sync_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _sync_width(event) -> None:
            canvas.itemconfigure(content_window, width=event.width)

        self._canvas = canvas
        self._content.bind("<Configure>", _sync_scroll_region)
        canvas.bind("<Configure>", _sync_width)
        canvas.bind("<MouseWheel>", self._on_mousewheel)

        actions = tk.Frame(main, bg=BG)
        actions.grid(row=1, column=0, sticky="ew", padx=36, pady=(0, 22))
        tk.Button(
            actions,
            text="Reset to Defaults",
            command=self._on_reset,
            bd=0,
            bg=BG,
            fg=MUTED,
            activebackground=SURFACE,
            activeforeground=TEXT,
            font=("Segoe UI", 10),
            cursor="hand2",
        ).pack(side="left")
        self._action_button(actions, "Save", self._on_save, primary=True).pack(side="right", padx=(8, 0))
        self._action_button(actions, "Cancel", self._on_cancel).pack(side="right")

    def _add_nav_button(self, parent: tk.Frame, name: str, icon: str) -> None:
        btn = tk.Button(
            parent,
            text=f"{icon}   {name}",
            command=lambda n=name: self._set_active(n),
            anchor="w",
            bd=0,
            bg=SIDEBAR,
            fg="#c9c2ba",
            activebackground=SURFACE,
            activeforeground=TEXT,
            font=("Segoe UI", 11),
            padx=14,
            pady=10,
            cursor="hand2",
        )
        btn.pack(fill="x", padx=14, pady=1)
        self._nav_buttons[name] = btn

    def _set_active(self, name: str) -> None:
        self._sync_vars_to_working()
        for tab, btn in self._nav_buttons.items():
            active = tab == name
            btn.configure(
                bg=SURFACE if active else SIDEBAR,
                fg=TEXT if active else "#c9c2ba",
                font=("Segoe UI", 11, "bold" if active else "normal"),
            )
        for child in self._content.winfo_children():
            child.destroy()
        builders: dict[str, Callable[[], None]] = {
            "General": self._build_general_page,
            "Audio": self._build_audio_page,
            "Hotkeys": self._build_hotkeys_page,
            "Storage": self._build_storage_page,
            "Cloud & Account": self._build_cloud_page,
            "Privacy": self._build_privacy_page,
            "Advanced": self._build_advanced_page,
            "Updates": self._build_updates_page,
            "About": self._build_about_page,
        }
        builders[name]()
        self._bind_mousewheel_recursive(self._content)

    def _bind_mousewheel_recursive(self, widget: tk.Widget) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel)
        for child in widget.winfo_children():
            self._bind_mousewheel_recursive(child)

    def _on_mousewheel(self, event) -> None:
        if self._canvas is not None:
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _sync_vars_to_working(self) -> None:
        if not self._vars:
            return

        simple_keys = [
            "output_folder",
            "filename_template",
            "mic_device",
            "speaker_device",
            "sample_rate",
            "auto_detect",
            "auto_stop_delay_seconds",
            "max_recording_hours",
            "start_with_windows",
            "show_notifications",
            "enable_hotkeys",
            "show_floating_bar",
        ]
        for key in simple_keys:
            if key in self._vars:
                self._working[key] = self._vars[key].get()

        if "file_format" in self._vars:
            self._working["file_format"] = self._vars["file_format"].get().lower()
        if "mp3_bitrate" in self._vars:
            self._working["mp3_bitrate"] = self._vars["mp3_bitrate"].get()
        if "channels" in self._vars:
            self._working["channels"] = 1 if self._vars["channels"].get() == "Mono" else 2
        if "date_format" in self._vars:
            strip = self._vars.get("_date_strip", lambda x: x)
            self._working["date_format"] = strip(self._vars["date_format"].get())
        if "time_format" in self._vars:
            strip = self._vars.get("_time_strip", lambda x: x)
            self._working["time_format"] = strip(self._vars["time_format"].get())

    def _page_header(self, title: str, subtitle: str) -> int:
        tk.Label(
            self._content,
            text=title,
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 19, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="ew")
        tk.Label(
            self._content,
            text=subtitle,
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 11),
            anchor="w",
        ).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 18))
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_columnconfigure(1, weight=0)
        return 2

    def _row(self, row: int, title: str, description: str = "") -> tk.Frame:
        tk.Frame(self._content, height=1, bg=LINE).grid(row=row, column=0, columnspan=3, sticky="ew")
        text = tk.Frame(self._content, bg=BG)
        text.grid(row=row + 1, column=0, sticky="ew", pady=14)
        tk.Label(
            text,
            text=title,
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).pack(fill="x")
        if description:
            tk.Label(
                text,
                text=description,
                bg=BG,
                fg=MUTED,
                font=("Segoe UI", 10),
                anchor="w",
                wraplength=410,
                justify="left",
            ).pack(fill="x", pady=(4, 0))
        control = tk.Frame(self._content, bg=BG)
        control.grid(row=row + 1, column=1, columnspan=2, sticky="e", pady=14)
        return control

    def _entry(self, parent: tk.Frame, var: tk.StringVar, width: int = 34) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=var,
            width=width,
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightbackground=LINE,
            highlightcolor=ACCENT,
            highlightthickness=1,
            font=("Segoe UI", 10),
        )

    def _combo(self, parent: tk.Frame, var: tk.StringVar, values: list[str], width: int = 26, enabled: bool = True):
        combo = ttk.Combobox(
            parent,
            textvariable=var,
            values=values,
            state="readonly" if enabled else "disabled",
            width=width,
            style="Recorder.TCombobox",
        )
        return combo

    def _switch(self, parent: tk.Frame, var: tk.BooleanVar, enabled: bool = True) -> tk.Checkbutton:
        def _sync():
            switch.configure(text="ON" if var.get() else "OFF")

        switch = tk.Checkbutton(
            parent,
            text="ON" if var.get() else "OFF",
            variable=var,
            command=_sync,
            indicatoron=False,
            width=5,
            bd=0,
            relief="flat",
            selectcolor=ACCENT,
            bg=SURFACE_ALT,
            fg=TEXT,
            activebackground=ACCENT,
            activeforeground="#15100b",
            disabledforeground=DIM,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2" if enabled else "arrow",
            state="normal" if enabled else "disabled",
        )
        return switch

    def _action_button(self, parent: tk.Frame, text: str, command: Callable[[], None], primary: bool = False):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bd=0,
            bg=ACCENT if primary else SURFACE,
            fg="#17110a" if primary else TEXT,
            activebackground="#ffc660" if primary else SURFACE_ALT,
            activeforeground="#17110a" if primary else TEXT,
            font=("Segoe UI", 10, "bold" if primary else "normal"),
            padx=18,
            pady=9,
            cursor="hand2",
        )

    def _placeholder_pill(self, parent: tk.Frame, text: str) -> tk.Label:
        label = tk.Label(
            parent,
            text=text,
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 10),
            padx=12,
            pady=8,
        )
        return label

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    def _build_general_page(self) -> None:
        row = self._page_header("General", "Startup, appearance and behaviour.")

        startup_var = tk.BooleanVar(value=self._working.get("start_with_windows", False))
        self._vars["start_with_windows"] = startup_var
        self._switch(self._row(row, _STARTUP_LABEL, "Open Recorder when you sign in to your computer."), startup_var).pack()
        row += 2

        appearance = tk.StringVar(value="Match system")
        self._combo(self._row(row, "Appearance", "Match your system, or pick a fixed theme."), appearance, ["Match system"], enabled=False).pack()
        row += 2

        swatches = tk.Frame(self._row(row, "Accent color", "Used for highlights. Recording UI remains red."), bg=BG)
        for color in [ACCENT, "#ff7b72", CYAN, PURPLE, GREEN]:
            tk.Label(swatches, text="", bg=color, width=3, height=1).pack(side="left", padx=4, ipady=5)
        swatches.pack()
        row += 2

        bar_var = tk.BooleanVar(value=self._working.get("show_floating_bar", True))
        self._vars["show_floating_bar"] = bar_var
        self._switch(self._row(row, "Floating bar at startup", "Show the bar as soon as Recorder launches."), bar_var).pack()
        row += 2

        notif_var = tk.BooleanVar(value=self._working.get("show_notifications", True))
        self._vars["show_notifications"] = notif_var
        self._switch(self._row(row, "Show notifications", "Display local status notifications when recordings start or finish."), notif_var).pack()
        row += 2

        self._switch(self._row(row, "Reduce motion", "Less animation on the bar and waveform."), tk.BooleanVar(value=False), enabled=False).pack()
        row += 2

        lang = tk.StringVar(value="English (US)")
        self._combo(self._row(row, "Language"), lang, ["English (US)"], enabled=False).pack()

    def _build_audio_page(self) -> None:
        row = self._page_header("Audio", "Input, output and processing.")

        mic_devices = _list_input_devices()
        spk_devices = _list_output_devices()

        mic_var = tk.StringVar(value=self._working.get("mic_device", "default"))
        self._vars["mic_device"] = mic_var
        self._combo(self._row(row, "Input device", "Recorder will switch to this when active."), mic_var, mic_devices, width=32).pack()
        row += 2

        meter = tk.Frame(self._row(row, "Input level", "Aim for the meter to peak in the amber range."), bg=BG)
        for i in range(22):
            tk.Label(meter, text="", bg=ACCENT if i < 12 else SURFACE_ALT, width=1).pack(side="left", padx=1, ipady=8)
        tk.Label(meter, text="  72 %", bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(side="left")
        meter.pack()
        row += 2

        spk_var = tk.StringVar(value=self._working.get("speaker_device", "default"))
        self._vars["speaker_device"] = spk_var
        self._combo(self._row(row, "Monitoring output", "Where Recorder plays back recordings."), spk_var, spk_devices, width=32).pack()
        row += 2

        fmt_values = ["WAV", "MP3"]
        fmt_var = tk.StringVar(value=self._working.get("file_format", "wav").upper())
        self._vars["file_format"] = fmt_var
        ffmpeg_ok = _ffmpeg_available()
        fmt_control = self._row(row, "Format", "Lossless preserves the original; MP3 creates smaller files.")
        fmt_combo = self._combo(fmt_control, fmt_var, fmt_values, width=32, enabled=ffmpeg_ok)
        fmt_combo.pack()
        if not ffmpeg_ok:
            fmt_var.set("WAV")
        row += 2

        br_var = tk.StringVar(value=str(self._working.get("mp3_bitrate", 128)))
        self._vars["mp3_bitrate"] = br_var
        br_combo = self._combo(self._row(row, "MP3 bitrate", "Used only when MP3 is available."), br_var, ["64", "128", "192"], width=10, enabled=ffmpeg_ok)
        br_combo.pack(side="left")
        tk.Label(br_combo.master, text=" kbps", bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(side="left")

        def _toggle_bitrate(*_):
            br_combo.configure(state="readonly" if ffmpeg_ok and fmt_var.get() == "MP3" else "disabled")

        fmt_var.trace_add("write", _toggle_bitrate)
        _toggle_bitrate()
        row += 2

        sr_var = tk.StringVar(value=str(self._working.get("sample_rate", 48000)))
        self._vars["sample_rate"] = sr_var
        self._combo(self._row(row, "Sample rate"), sr_var, ["44100", "48000"], width=10).pack()
        row += 2

        ch_var = tk.StringVar(value="Mono" if self._working.get("channels", 1) == 1 else "Stereo")
        self._vars["channels"] = ch_var
        self._combo(self._row(row, "Channels"), ch_var, ["Mono", "Stereo"], width=10).pack()
        row += 2

        self._switch(self._row(row, "Noise suppression", "Subtracts steady background noise. Best for indoor speech."), tk.BooleanVar(value=True), enabled=False).pack()
        row += 2

        self._switch(self._row(row, "Auto-gain", "Smooths out loud and quiet sections in real time."), tk.BooleanVar(value=False), enabled=False).pack()

    def _build_hotkeys_page(self) -> None:
        row = self._page_header("Hotkeys", "Global shortcuts work even when Recorder is in the background.")

        hotkeys_var = tk.BooleanVar(value=self._working.get("enable_hotkeys", True))
        self._vars["enable_hotkeys"] = hotkeys_var
        self._switch(self._row(row, "Enable shortcuts", "Turn global Recorder shortcuts on or off."), hotkeys_var).pack()
        row += 2

        for title, keys in [
            ("Start / stop recording", "Ctrl  Alt  R"),
            ("Pause / resume", "Ctrl  Alt  P"),
            ("Show / hide floating bar", "Ctrl  Alt  B"),
            ("Mute microphone", "Ctrl  Alt  M"),
            ("Drop a marker", "Ctrl  Alt  Space"),
            ("Open library", "Ctrl  Alt  L"),
            ("Open settings", "Ctrl  ,"),
            ("Quit Recorder", "Ctrl  Q"),
        ]:
            control = self._row(row, title)
            self._placeholder_pill(control, keys).pack(side="left", padx=(0, 8))
            self._placeholder_pill(control, "Rebind").pack(side="left")
            row += 2

    def _build_storage_page(self) -> None:
        row = self._page_header("Storage", "Where Recorder keeps your audio files.")

        folder_var = tk.StringVar(value=self._working.get("output_folder", ""))
        self._vars["output_folder"] = folder_var
        folder = self._row(row, "Library location", "Choose where completed recordings are saved.")
        self._entry(folder, folder_var, width=36).pack(side="left", ipady=8)
        self._action_button(folder, "Choose…", self._browse_folder).pack(side="left", padx=(8, 0))
        row += 2

        tpl_var = tk.StringVar(value=self._working.get("filename_template", "TeamsCall_{date}_{time}"))
        self._vars["filename_template"] = tpl_var
        self._entry(self._row(row, "Filename template", "Used when saving new recordings."), tpl_var, width=42).pack(ipady=8)
        row += 2

        preview_var = tk.StringVar()
        self._vars["_preview"] = preview_var
        preview_label = self._placeholder_pill(
            self._row(row, "Preview", "Placeholders: {date} {time} {datetime} {user} {counter}"),
            preview_var.get(),
        )
        preview_label.pack()
        row += 2

        now = _dt.now()
        date_choices = [f"{k}  →  {now.strftime(v)}" for k, v in DATE_FORMATS.items()]
        time_choices = [f"{k}  →  {now.strftime(v)}" for k, v in TIME_FORMATS.items()]

        def _strip_example(val: str) -> str:
            return val.split("  →  ")[0].strip()

        saved_date = self._working.get("date_format", "YYYYMMDD")
        date_var = tk.StringVar(value=next((c for c in date_choices if c.startswith(saved_date)), date_choices[0]))
        self._vars["date_format"] = date_var
        self._vars["_date_strip"] = _strip_example
        self._combo(self._row(row, "Date format"), date_var, date_choices, width=28).pack()
        row += 2

        saved_time = self._working.get("time_format", "HHMMSS")
        time_var = tk.StringVar(value=next((c for c in time_choices if c.startswith(saved_time)), time_choices[0]))
        self._vars["time_format"] = time_var
        self._vars["_time_strip"] = _strip_example
        self._combo(self._row(row, "Time format"), time_var, time_choices, width=28).pack()
        row += 2

        def _update_preview(*_):
            try:
                preview = preview_filename(tpl_var.get(), _strip_example(date_var.get()), _strip_example(time_var.get()))
                preview_var.set(preview)
            except Exception:
                preview_var.set("(invalid template)")
            preview_label.configure(text=preview_var.get())

        tpl_var.trace_add("write", _update_preview)
        date_var.trace_add("write", _update_preview)
        time_var.trace_add("write", _update_preview)
        _update_preview()

        auto_delete = tk.StringVar(value="Never")
        self._combo(self._row(row, "Auto-delete after", "Older recordings move to the trash automatically."), auto_delete, ["Never"], enabled=False).pack()
        row += 2

        self._switch(self._row(row, "Encrypt local files", "Recordings are encrypted at rest with your account key."), tk.BooleanVar(value=False), enabled=False).pack()

    def _build_cloud_page(self) -> None:
        row = self._page_header("Cloud & Account", "Sync your library across devices.")
        account = self._row(row, "Account", "Sign-in and plan management are not available in this build.")
        self._placeholder_pill(account, "Not signed in").pack(side="left", padx=(0, 8))
        self._placeholder_pill(account, "Manage").pack(side="left")
        row += 2
        self._switch(self._row(row, "Sync new recordings", "Upload to your account so they appear on other devices."), tk.BooleanVar(value=False), enabled=False).pack()
        row += 2
        self._switch(self._row(row, "Sync on cellular", "Allow uploads when your computer is tethered or on hotspot."), tk.BooleanVar(value=False), enabled=False).pack()
        row += 2
        trans = tk.StringVar(value="Off")
        self._combo(self._row(row, "Transcription", "Generate searchable transcripts after each recording."), trans, ["Off"], enabled=False).pack()
        row += 2
        self._placeholder_pill(self._row(row, "Sync status"), "Local only").pack()

    def _build_privacy_page(self) -> None:
        row = self._page_header("Privacy", "What Recorder can see and what it shares.")
        self._placeholder_pill(self._row(row, "Microphone access", "Required to record. Managed by your operating system."), "System managed").pack()
        row += 2
        self._placeholder_pill(self._row(row, "Accessibility access", "Needed for global hotkeys on some systems."), "System managed").pack()
        row += 2
        self._switch(self._row(row, "Anonymous diagnostics", "Crash reports and feature usage. No audio content is sent."), tk.BooleanVar(value=False), enabled=False).pack()
        row += 2
        self._switch(self._row(row, "On-device transcription", "Run speech-to-text locally instead of in the cloud."), tk.BooleanVar(value=False), enabled=False).pack()
        row += 2
        self._placeholder_pill(self._row(row, "Erase all cloud data…"), "Unavailable").pack()

    def _build_advanced_page(self) -> None:
        row = self._page_header("Advanced", "Experimental features and developer settings.")

        auto_var = tk.BooleanVar(value=self._working.get("auto_detect", True))
        self._vars["auto_detect"] = auto_var
        self._switch(self._row(row, "Auto-detect Teams audio", "Start and stop recording when Teams audio activity changes."), auto_var).pack()
        row += 2

        delay_var = tk.StringVar(value=str(self._working.get("auto_stop_delay_seconds", 10)))
        self._vars["auto_stop_delay_seconds"] = delay_var
        ttk.Spinbox(
            self._row(row, "Auto-stop delay", "Seconds to wait after call audio stops."),
            textvariable=delay_var,
            from_=5,
            to=120,
            width=8,
            style="Recorder.TSpinbox",
        ).pack()
        row += 2

        max_var = tk.StringVar(value=str(self._working.get("max_recording_hours", 4)))
        self._vars["max_recording_hours"] = max_var
        ttk.Spinbox(
            self._row(row, "Max recording length", "Hours before an active recording is split."),
            textvariable=max_var,
            from_=1,
            to=24,
            width=8,
            style="Recorder.TSpinbox",
        ).pack()
        row += 2

        self._switch(self._row(row, "Voice activity detection", "Pause silent stretches automatically."), tk.BooleanVar(value=False), enabled=False).pack()
        row += 2
        self._switch(self._row(row, "Multi-channel input", "Record up to 8 inputs in parallel. Beta."), tk.BooleanVar(value=False), enabled=False).pack()
        row += 2
        log_level = tk.StringVar(value="Default")
        self._combo(self._row(row, "Log level"), log_level, ["Default"], enabled=False).pack()

    def _build_updates_page(self) -> None:
        row = self._page_header("Updates", "Channel, release notes and install behaviour.")
        self._placeholder_pill(self._row(row, "Recorder", "Update checks are not available in this build."), f"v{APP_VERSION}").pack()
        row += 2
        channel = tk.StringVar(value="Stable")
        self._combo(self._row(row, "Update channel", "Beta receives new features earlier."), channel, ["Stable"], enabled=False).pack()
        row += 2
        self._switch(self._row(row, "Install updates automatically"), tk.BooleanVar(value=False), enabled=False).pack()
        row += 2
        self._placeholder_pill(self._row(row, "Release notes"), "No bundled release notes").pack()

    def _build_about_page(self) -> None:
        row = self._page_header("About", "App version and credits.")
        self._placeholder_pill(self._row(row, "Recorder", "A focused voice recorder for Microsoft Teams calls."), f"v{APP_VERSION}").pack()
        row += 2
        self._placeholder_pill(self._row(row, "Website"), "Placeholder").pack()
        row += 2
        self._placeholder_pill(self._row(row, "Privacy"), "Local recordings by default").pack()
        row += 2
        self._placeholder_pill(self._row(row, "Acknowledgements"), "Python, Tkinter, pystray, sounddevice").pack()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _browse_folder(self):
        current = self._vars["output_folder"].get()
        chosen = filedialog.askdirectory(initialdir=current or str(Path.home()), title="Select save folder")
        if chosen:
            self._vars["output_folder"].set(chosen)

    def _destroy_root(self):
        if self._tk_root is not None:
            try:
                self._tk_root.destroy()
            except Exception:
                pass
            self._tk_root = None

    def _on_save(self):
        self._sync_vars_to_working()
        updates = self._collect_values()
        if updates is None:
            return
        config.update_from_dict(updates)
        set_startup(updates.get("start_with_windows", False))
        logger.info("Settings saved")
        self._root.destroy()

    def _on_cancel(self):
        self._root.destroy()

    def _on_reset(self):
        if messagebox.askyesno("Reset", "Reset all settings to defaults?", parent=self._root):
            config.reset_to_defaults()
            set_startup(False)
            self._root.destroy()
            logger.info("Settings reset to defaults")

    def _collect_values(self) -> Optional[dict]:
        try:
            fmt = str(self._working.get("file_format", "wav")).lower()
            channels = int(self._working.get("channels", 1))
            return {
                "output_folder": str(self._working.get("output_folder", "")).strip(),
                "file_format": fmt,
                "mp3_bitrate": int(self._working.get("mp3_bitrate", 128)),
                "filename_template": str(self._working.get("filename_template", "")).strip(),
                "date_format": str(self._working.get("date_format", "YYYYMMDD")),
                "time_format": str(self._working.get("time_format", "HHMMSS")),
                "mic_device": str(self._working.get("mic_device", "default")),
                "speaker_device": str(self._working.get("speaker_device", "default")),
                "sample_rate": int(self._working.get("sample_rate", 48000)),
                "channels": channels,
                "auto_detect": bool(self._working.get("auto_detect", True)),
                "auto_stop_delay_seconds": int(self._working.get("auto_stop_delay_seconds", 10)),
                "max_recording_hours": int(self._working.get("max_recording_hours", 4)),
                "start_with_windows": bool(self._working.get("start_with_windows", False)),
                "show_notifications": bool(self._working.get("show_notifications", True)),
                "enable_hotkeys": bool(self._working.get("enable_hotkeys", True)),
                "show_floating_bar": bool(self._working.get("show_floating_bar", True)),
            }
        except (ValueError, KeyError) as e:
            messagebox.showerror("Invalid input", str(e), parent=self._root)
            return None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _ffmpeg_available() -> bool:
    import shutil

    ffmpeg_path = config.get("ffmpeg_path", "")
    if ffmpeg_path and Path(ffmpeg_path).exists():
        return True
    return shutil.which("ffmpeg") is not None


def _list_input_devices() -> list[str]:
    if PLATFORM == "Windows":
        return _list_devices_windows(input=True)
    from platform_utils import list_input_devices_sounddevice

    return list_input_devices_sounddevice()


def _list_output_devices() -> list[str]:
    if PLATFORM == "Windows":
        return _list_devices_windows(input=False)
    from platform_utils import list_output_devices_sounddevice

    return list_output_devices_sounddevice()


def _list_devices_windows(input: bool) -> list[str]:
    devices = ["default"]
    try:
        import pyaudiowpatch as pyaudio

        p = pyaudio.PyAudio()
        key = "maxInputChannels" if input else "maxOutputChannels"
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info[key] > 0:
                devices.append(info["name"])
        p.terminate()
    except Exception as e:
        logger.warning("Could not enumerate devices: %s", e)
    return devices
