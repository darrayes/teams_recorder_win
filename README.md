# Teams Call Recorder

A lightweight Windows system tray app that records Microsoft Teams PSTN calls by capturing your **microphone** and **system audio output** simultaneously, mixing them into a single file saved locally.

---

## How it works

The app records at the Windows audio layer — no Teams API access, no screen capture:

- **Mic** → your voice via the active input device
- **Loopback** → the other party's voice via WASAPI loopback on the active output device (works for both speakers and headphones)
- Both streams are mixed at -3 dB each (to prevent clipping) and written to disk

---

## Requirements

- Windows 10 or 11
- Python 3.10+ (for running from source)
- `ffmpeg.exe` on PATH or placed next to `TeamsRecorder.exe` (required for MP3 export; WAV works without it)

---

## Installation

### Option A — Run from source

```bash
git clone https://github.com/your-username/teams-recorder.git
cd teams-recorder/teams_recorder_win

pip install -r requirements.txt
python main.py
```

### Option B — Build a standalone `.exe`

1. Place `ffmpeg.exe` in the project root (download from [ffmpeg.org](https://ffmpeg.org/download.html))
2. Install PyInstaller: `pip install pyinstaller`
3. Build:
   ```bash
   pyinstaller build.spec
   ```
4. The output is in `dist/TeamsRecorder/` — run `TeamsRecorder.exe`

---

## Usage

The app launches silently into the system tray (bottom-right of the taskbar).

| Action | How |
|---|---|
| Start recording | Right-click tray icon → **Start Recording**, or left-click the icon |
| Stop recording | Right-click → **Stop Recording**, or left-click again |
| Pause / Resume | Right-click → **Pause** / **Resume** (only visible while recording) |
| Open recordings folder | Right-click → **Open Recordings Folder** |
| Change settings | Right-click → **Settings…** |
| Toggle auto-detect | Right-click → **Auto-Detect: ON/OFF** |
| View log | Right-click → **View Log** |
| Quit | Right-click → **Quit** |

### Tray icon states

| Icon colour | Meaning |
|---|---|
| Grey | Idle |
| Red (pulsing) | Recording |
| Yellow | Paused |

### Auto-detect mode

When enabled, the app watches for Teams audio activity via the Windows Core Audio API. Recording starts automatically within ~4 seconds of a call beginning, and stops ~10 seconds after the call ends. Both thresholds are configurable in Settings.

---

## Settings

Open via right-click → **Settings…**

| Setting | Default |
|---|---|
| Save folder | `Documents\Teams Recordings` |
| File format | MP3 (if ffmpeg available), else WAV |
| MP3 bitrate | 128 kbps |
| Filename template | `TeamsCall_{date}_{time}` |
| Microphone | System default |
| Speaker (loopback) | System default |
| Sample rate | 48000 Hz |
| Channels | Mono |
| Auto-detect Teams audio | On |
| Auto-stop delay | 10 seconds |
| Max recording length | 4 hours (auto-splits) |
| Start with Windows | Off |
| Show notifications | On |

### Filename template placeholders

| Placeholder | Example |
|---|---|
| `{date}` | `20250506` |
| `{time}` | `143022` |
| `{datetime}` | `20250506_143022` |
| `{user}` | `john.doe` (Windows login name) |
| `{counter}` | `3` (resets daily) |

---

## Project structure

```
teams_recorder_win/
├── main.py              # Entry point — single-instance lock, wires all components
├── recorder.py          # Dual-stream audio capture, mixing, file writing
├── detector.py          # Teams audio activity polling via pycaw
├── settings_window.py   # Tkinter settings dialog
├── tray_icon.py         # pystray tray icon, menu, animated state
├── config.py            # JSON config load/save/migrate
├── utils.py             # Filename generation, daily counter
├── assets/              # Tray icon .ico files
├── make_icons.py        # Script to regenerate placeholder icons
├── requirements.txt
└── build.spec           # PyInstaller build spec
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `pyaudiowpatch` | WASAPI loopback capture (Windows) |
| `soundfile` | Incremental WAV writing |
| `samplerate` | Resampling when devices use different native rates |
| `numpy` | Stream mixing |
| `pystray` | System tray icon |
| `Pillow` | Icon image rendering |
| `pycaw` | Windows Core Audio API (auto-detect) |
| `comtypes` | Windows COM bindings (required by pycaw) |
| `pydub` | MP3 export |
| `plyer` | Windows toast notifications |

---

## Configuration file

Stored at `%APPDATA%\TeamsRecorder\config.json`. Auto-created on first run with defaults. If the file is corrupted it is silently reset to defaults.

---

## Crash recovery

Recordings are written incrementally to a `.wav` file. If the app crashes mid-recording, the partial file is preserved. On the next launch, the app detects the interrupted recording and asks whether to keep or delete it.

---

## Legal notice

⚠️ Recording calls may be regulated by law in your jurisdiction. Many regions require explicit consent from all parties before a call can be recorded. **You are solely responsible for complying with all applicable laws and for obtaining any required consent.** This app does not provide legal advice.

---

## Out of scope (planned for Phase 2)

- SharePoint / cloud upload
- Speech-to-text transcription
- Per-call metadata (caller, duration, tags)
- Audio enhancement (noise suppression, AGC)
- Encrypted storage
- Multi-user dashboard
