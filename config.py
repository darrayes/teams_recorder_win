import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

CURRENT_CONFIG_VERSION = 1

DEFAULTS = {
    "config_version": CURRENT_CONFIG_VERSION,
    "output_folder": str(Path.home() / "Documents" / "Teams Recordings"),
    "file_format": "mp3",
    "mp3_bitrate": 128,
    "filename_template": "TeamsCall_{date}_{time}",
    "date_format": "YYYYMMDD",
    "time_format": "HHMMSS",
    "mic_device": "default",
    "speaker_device": "default",
    "sample_rate": 48000,
    "channels": 1,
    "auto_detect": True,
    "auto_stop_delay_seconds": 10,
    "max_recording_hours": 4,
    "start_with_windows": False,
    "show_notifications": True,
    "daily_counter": 0,
    "last_counter_date": "",
    "recording_in_progress": False,
    "recording_temp_path": "",
    "ffmpeg_path": "",
    "first_run": True,
}


class Config:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data = {}
            cls._instance._path = None
            cls._instance._loaded = False
        return cls._instance

    def load(self):
        appdata = os.environ.get("APPDATA", str(Path.home()))
        config_dir = Path(appdata) / "TeamsRecorder"
        config_dir.mkdir(parents=True, exist_ok=True)
        self._path = config_dir / "config.json"

        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self._data = {**DEFAULTS, **loaded}
                self._migrate()
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Config load failed (%s) — resetting to defaults", e)
                self._data = dict(DEFAULTS)
        else:
            self._data = dict(DEFAULTS)

        self._loaded = True
        self.save()
        logger.info("Config loaded from %s", self._path)

    def _migrate(self):
        version = self._data.get("config_version", 0)
        if version < CURRENT_CONFIG_VERSION:
            logger.info("Migrating config from version %d to %d", version, CURRENT_CONFIG_VERSION)
            self._data["config_version"] = CURRENT_CONFIG_VERSION
            self.save()

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def save(self):
        if self._path is None:
            return
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except OSError as e:
            logger.error("Config save failed: %s", e)

    def reset_to_defaults(self):
        self._data = dict(DEFAULTS)
        self._data["output_folder"] = str(Path.home() / "Documents" / "Teams Recordings")
        self.save()

    def as_dict(self):
        return dict(self._data)

    def update_from_dict(self, d: dict):
        for k, v in d.items():
            self._data[k] = v
        self.save()

    @property
    def config_dir(self) -> Path:
        return self._path.parent if self._path else Path(".")

    @property
    def log_path(self) -> Path:
        return self.config_dir / "app.log"


config = Config()
