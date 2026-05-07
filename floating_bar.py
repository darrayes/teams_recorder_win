import tkinter as tk
from typing import Callable

from config import config
from recorder import RecorderState


class FloatingBar:
    def __init__(
        self,
        parent: tk.Tk,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_pause_resume: Callable[[], None],
        get_state: Callable[[], str],
        get_elapsed: Callable[[], float],
    ):
        self._parent = parent
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_pause_resume = on_pause_resume
        self._get_state = get_state
        self._get_elapsed = get_elapsed
        self._drag_offset = (0, 0)
        self._visible = False

        self._win = tk.Toplevel(parent)
        self._win.title("Teams Recorder")
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.configure(bg="#202124", padx=6, pady=6)
        self._win.protocol("WM_DELETE_WINDOW", self.hide)

        self._status = tk.Label(
            self._win,
            text="Idle",
            bg="#202124",
            fg="#ffffff",
            font=("Segoe UI", 9, "bold"),
            width=11,
            anchor="w",
        )
        self._status.pack(side="left", padx=(2, 6))

        self._start_stop = tk.Button(
            self._win,
            text="Start",
            width=7,
            command=self._handle_start_stop,
            relief="flat",
        )
        self._start_stop.pack(side="left", padx=2)

        self._pause = tk.Button(
            self._win,
            text="Pause",
            width=7,
            command=self._on_pause_resume,
            relief="flat",
        )
        self._pause.pack(side="left", padx=2)

        self._close = tk.Button(
            self._win,
            text="x",
            width=2,
            command=self.hide,
            relief="flat",
        )
        self._close.pack(side="left", padx=(6, 0))

        for widget in (self._win, self._status):
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
            self._status.configure(text=f"REC {mins:02d}:{secs:02d}", fg="#ff6b6b")
            self._start_stop.configure(text="Stop", state="normal")
            self._pause.configure(text="Pause", state="normal")
        elif state == RecorderState.PAUSED:
            elapsed = int(self._get_elapsed())
            mins, secs = divmod(elapsed, 60)
            self._status.configure(text=f"PAUSED {mins:02d}:{secs:02d}", fg="#ffd166")
            self._start_stop.configure(text="Stop", state="normal")
            self._pause.configure(text="Resume", state="normal")
        else:
            self._status.configure(text="Idle", fg="#ffffff")
            self._start_stop.configure(text="Start", state="normal")
            self._pause.configure(text="Pause", state="disabled")

        self._win.after(500, self._update)

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
