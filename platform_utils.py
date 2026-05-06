"""
Cross-platform helpers: single-instance lock, file/folder opening,
startup registration, and config directory.
"""

import logging
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PLATFORM = platform.system()  # "Windows", "Darwin", "Linux"

APP_NAME = "TeamsRecorder"
_LOCK_FD = None  # macOS / Linux lock file descriptor


# ---------------------------------------------------------------------------
# Config directory
# ---------------------------------------------------------------------------

def get_config_dir() -> Path:
    if PLATFORM == "Windows":
        base = os.environ.get("APPDATA", str(Path.home()))
        return Path(base) / APP_NAME
    if PLATFORM == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    # Linux / other
    xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(xdg) / APP_NAME


# ---------------------------------------------------------------------------
# Open a file or folder in the system default application
# ---------------------------------------------------------------------------

def open_path(path: str | Path):
    path = str(path)
    try:
        if PLATFORM == "Windows":
            os.startfile(path)
        elif PLATFORM == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        logger.warning("open_path(%s) failed: %s", path, e)


# ---------------------------------------------------------------------------
# Single-instance enforcement
# ---------------------------------------------------------------------------

def acquire_single_instance() -> bool:
    if PLATFORM == "Windows":
        return _acquire_mutex()
    return _acquire_lockfile()


def release_single_instance():
    if PLATFORM == "Windows":
        _release_mutex()
    else:
        _release_lockfile()


def _acquire_mutex() -> bool:
    import ctypes
    global _LOCK_FD
    MUTEX_NAME = f"{APP_NAME}SingleInstance"
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    _LOCK_FD = handle  # reuse slot to store handle
    return ctypes.windll.kernel32.GetLastError() != 183  # 183 = ERROR_ALREADY_EXISTS


def _release_mutex():
    global _LOCK_FD
    if _LOCK_FD:
        import ctypes
        ctypes.windll.kernel32.CloseHandle(_LOCK_FD)
        _LOCK_FD = None


def _acquire_lockfile() -> bool:
    import fcntl
    global _LOCK_FD
    lock_path = Path(tempfile.gettempdir()) / f"{APP_NAME.lower()}.lock"
    try:
        fd = open(lock_path, "w")
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd.write(str(os.getpid()))
        fd.flush()
        _LOCK_FD = fd
        return True
    except OSError:
        return False


def _release_lockfile():
    global _LOCK_FD
    if _LOCK_FD:
        try:
            import fcntl
            fcntl.lockf(_LOCK_FD, fcntl.LOCK_UN)
            _LOCK_FD.close()
        except Exception:
            pass
        _LOCK_FD = None


# ---------------------------------------------------------------------------
# Launch-at-login / startup registration
# ---------------------------------------------------------------------------

def set_startup(enable: bool, exe_path: Optional[str] = None):
    exe = exe_path or sys.executable
    try:
        if PLATFORM == "Windows":
            _set_startup_windows(enable, exe)
        elif PLATFORM == "Darwin":
            _set_startup_macos(enable, exe)
        else:
            _set_startup_linux(enable, exe)
    except Exception as e:
        logger.warning("set_startup(%s) failed: %s", enable, e)


def _set_startup_windows(enable: bool, exe: str):
    import winreg
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
    if enable:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
        logger.info("Added to Windows startup: %s", exe)
    else:
        try:
            winreg.DeleteValue(key, APP_NAME)
            logger.info("Removed from Windows startup")
        except FileNotFoundError:
            pass
    winreg.CloseKey(key)


def _set_startup_macos(enable: bool, exe: str):
    import html as _html
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_path = plist_dir / f"com.{APP_NAME.lower()}.plist"

    if enable:
        plist_dir.mkdir(parents=True, exist_ok=True)
        exe_escaped = _html.escape(exe, quote=False)
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.{APP_NAME.lower()}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe_escaped}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
"""
        plist_path.write_text(plist_content)
        subprocess.run(["launchctl", "load", str(plist_path)], check=False)
        logger.info("Added macOS LaunchAgent: %s", plist_path)
    else:
        if plist_path.exists():
            subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
            plist_path.unlink()
            logger.info("Removed macOS LaunchAgent")


def _set_startup_linux(enable: bool, exe: str):
    autostart_dir = Path.home() / ".config" / "autostart"
    desktop_path = autostart_dir / f"{APP_NAME.lower()}.desktop"

    if enable:
        autostart_dir.mkdir(parents=True, exist_ok=True)
        desktop_content = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Exec={exe}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
"""
        desktop_path.write_text(desktop_content)
        logger.info("Added Linux autostart: %s", desktop_path)
    else:
        if desktop_path.exists():
            desktop_path.unlink()
            logger.info("Removed Linux autostart")


# ---------------------------------------------------------------------------
# Loopback device discovery (sounddevice backend)
# ---------------------------------------------------------------------------

# Keywords to identify loopback input devices on each platform
LOOPBACK_KEYWORDS = {
    "Darwin": ["blackhole", "soundflower", "loopback"],
    "Linux": ["monitor"],
}


def find_loopback_device_sounddevice() -> Optional[str]:
    """Return the name of a usable loopback input device, or None."""
    try:
        import sounddevice as sd
    except ImportError:
        return None

    keywords = LOOPBACK_KEYWORDS.get(PLATFORM, [])
    for dev in sd.query_devices():
        if dev["max_input_channels"] > 0:
            name_lower = dev["name"].lower()
            if any(kw in name_lower for kw in keywords):
                return dev["name"]
    return None


def list_input_devices_sounddevice() -> list[str]:
    try:
        import sounddevice as sd
        return ["default"] + [
            d["name"] for d in sd.query_devices()
            if d["max_input_channels"] > 0
        ]
    except Exception:
        return ["default"]


def list_output_devices_sounddevice() -> list[str]:
    try:
        import sounddevice as sd
        return ["default"] + [
            d["name"] for d in sd.query_devices()
            if d["max_output_channels"] > 0
        ]
    except Exception:
        return ["default"]
