import tkinter as tk
from typing import Callable

from config import config
from recorder import RecorderState


BG = "#0b0a09"
SURFACE = "#151310"
SURFACE_HOVER = "#24211d"
TEXT = "#f5f1ea"
MUTED = "#9b958e"
AMBER = "#f6ad33"
RED = "#ff424d"
PAUSED = "#b28bf2"
DIVIDER = "#29241f"


class FloatingBar:
    def __init__(
        self,
        parent: tk.Tk,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_pause_resume: Callable[[], None],
        on_settings: Callable[[], None],
        get_state: Callable[[], str],
        get_elapsed: Callable[[], float],
    ):
        self._parent = parent
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_pause_resume = on_pause_resume
        self._on_settings = on_settings
        self._get_state = get_state
        self._get_elapsed = get_elapsed
        self._drag_offset = (0, 0)
        self._visible = False
        self._wave_phase = 0

        self._win = tk.Toplevel(parent)
        self._win.title("Recorder")
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.configure(bg=BG, padx=10, pady=8)
        self._win.protocol("WM_DELETE_WINDOW", self.hide)

        self._handle = tk.Label(
            self._win,
            text="::",
            bg=BG,
            fg="#5d554d",
            font=("Segoe UI", 12, "bold"),
            cursor="fleur",
        )
        self._handle.pack(side="left", padx=(0, 8))

        self._pause = tk.Button(
            self._win,
            text="Ⅱ",
            width=3,
            command=self._on_pause_resume,
            relief="flat",
            bd=0,
            bg=SURFACE_HOVER,
            activebackground=SURFACE_HOVER,
            fg=TEXT,
            activeforeground=TEXT,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        self._pause.pack(side="left", padx=(0, 8), ipady=5)

        self._start_stop = tk.Button(
            self._win,
            text="■",
            width=3,
            command=self._handle_start_stop,
            relief="flat",
            bd=0,
            bg=BG,
            activebackground=SURFACE_HOVER,
            fg=MUTED,
            activeforeground=TEXT,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self._start_stop.pack(side="left", padx=(0, 8), ipady=5)

        self._status = tk.Label(
            self._win,
            text="● 00:00",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10, "bold"),
            width=8,
            anchor="w",
        )
        self._status.pack(side="left", padx=(0, 10))

        self._wave = tk.Canvas(
            self._win,
            width=92,
            height=28,
            bg=BG,
            highlightthickness=0,
            bd=0,
        )
        self._wave.pack(side="left", padx=(0, 12))

        self._separator = tk.Frame(self._win, width=1, bg=DIVIDER)
        self._separator.pack(side="left", fill="y", padx=(0, 10), pady=4)

        self._mute = tk.Button(
            self._win,
            text="🎙",
            width=3,
            command=lambda: None,
            relief="flat",
            bd=0,
            bg=BG,
            activebackground=SURFACE_HOVER,
            fg=MUTED,
            activeforeground=TEXT,
            font=("Segoe UI", 10),
            cursor="arrow",
            state="disabled",
            disabledforeground="#6d665e",
        )
        self._mute.pack(side="left", padx=(0, 6), ipady=4)

        self._settings = tk.Button(
            self._win,
            text="⚙",
            width=3,
            command=self._on_settings,
            relief="flat",
            bd=0,
            bg=BG,
            activebackground=SURFACE_HOVER,
            fg=MUTED,
            activeforeground=TEXT,
            font=("Segoe UI", 10),
            cursor="hand2",
            disabledforeground="#6d665e",
        )
        self._settings.pack(side="left", padx=(0, 6), ipady=4)

        self._close = tk.Button(
            self._win,
            text="−",
            width=3,
            command=self.hide,
            relief="flat",
            bd=0,
            bg=BG,
            activebackground=SURFACE_HOVER,
            fg=MUTED,
            activeforeground=TEXT,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        self._close.pack(side="left", padx=(6, 0))

        for widget in (self._win, self._handle, self._status, self._wave):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)
            widget.bind("<ButtonRelease-1>", self._save_position)

        self._win.withdraw()
        self._win.after(250, self._update)

    def show(self) -> None:
        if self._visible:
            return
        self._visible = True
        self._apply_geometry()
        self._win.deiconify()
        self._win.lift()

    def hide(self) -> None:
        self._visible = False
        self._win.withdraw()

    def toggle(self) -> None:
        if self._visible:
            self.hide()
        else:
            self.show()

    def _handle_start_stop(self) -> None:
        if self._get_state() == RecorderState.IDLE:
            self._on_start()
        else:
            self._on_stop()

    def _update(self) -> None:
        state = self._get_state()
        if state == RecorderState.RECORDING:
            elapsed = int(self._get_elapsed())
            mins, secs = divmod(elapsed, 60)
            self._status.configure(text=f"● {mins:02d}:{secs:02d}", fg=TEXT)
            self._start_stop.configure(text="■", state="normal", fg=MUTED)
            self._pause.configure(text="Ⅱ", state="normal")
            self._draw_wave(active=True, color=AMBER)
        elif state == RecorderState.PAUSED:
            elapsed = int(self._get_elapsed())
            mins, secs = divmod(elapsed, 60)
            self._status.configure(text=f"Ⅱ {mins:02d}:{secs:02d}", fg=PAUSED)
            self._start_stop.configure(text="■", state="normal", fg=MUTED)
            self._pause.configure(text="▶", state="normal")
            self._draw_wave(active=False, color="#756d63")
        else:
            self._status.configure(text="● 00:00", fg=MUTED)
            self._start_stop.configure(text="●", state="normal", fg=RED)
            self._pause.configure(text="Ⅱ", state="disabled")
            self._draw_wave(active=False, color="#3b352f")

        self._win.after(500, self._update)

    def _draw_wave(self, active: bool, color: str) -> None:
        self._wave.delete("all")
        heights = [8, 16, 12, 22, 14, 26, 18, 24, 13, 20, 16, 10, 18, 12]
        if active:
            self._wave_phase = (self._wave_phase + 1) % len(heights)
        else:
            self._wave_phase = 0

        x = 5
        center = 14
        for index in range(14):
            h = heights[(index + self._wave_phase) % len(heights)]
            self._wave.create_line(
                x,
                center - h // 2,
                x,
                center + h // 2,
                fill=color,
                width=2,
                capstyle=tk.ROUND,
            )
            x += 6

    def _apply_geometry(self) -> None:
        saved = config.get("floating_bar_geometry", "")
        if saved:
            self._win.geometry(saved)
            return

        self._win.update_idletasks()
        width = self._win.winfo_width()
        sw = self._win.winfo_screenwidth()
        x = max(sw - width - 24, 0)
        self._win.geometry(f"+{x}+24")

    def _start_drag(self, event) -> None:
        self._drag_offset = (event.x_root - self._win.winfo_x(), event.y_root - self._win.winfo_y())

    def _drag(self, event) -> None:
        dx, dy = self._drag_offset
        self._win.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _save_position(self, _event=None) -> None:
        geometry = f"+{self._win.winfo_x()}+{self._win.winfo_y()}"
        config.set("floating_bar_geometry", geometry)
        config.save()
