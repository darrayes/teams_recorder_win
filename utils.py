import os
import re
from datetime import date, datetime
from pathlib import Path

from config import config

_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')


def resolve_filename(template: str | None = None) -> str:
    template = template or config.get("filename_template", "TeamsCall_{date}_{time}")
    date_fmt = config.get("date_format", "YYYYMMDD")
    time_fmt = config.get("time_format", "HHMMSS")

    now = datetime.now()
    today = now.date()

    date_str = _format_date(now, date_fmt)
    time_str = _format_time(now, time_fmt)
    datetime_str = f"{date_str}_{time_str}"
    user_str = os.environ.get("USERNAME", "User")
    counter_str = _next_counter(today)

    name = template
    name = name.replace("{date}", date_str)
    name = name.replace("{time}", time_str)
    name = name.replace("{datetime}", datetime_str)
    name = name.replace("{user}", user_str)
    name = name.replace("{counter}", str(counter_str))

    name = _ILLEGAL_CHARS.sub("_", name)
    return name


DATE_FORMATS: dict[str, str] = {
    "YYYYMMDD":    "%Y%m%d",       # 20250506
    "YYYY-MM-DD":  "%Y-%m-%d",     # 2025-05-06
    "YYYY_MM_DD":  "%Y_%m_%d",     # 2025_05_06
    "DD-MM-YYYY":  "%d-%m-%Y",     # 06-05-2025
    "MM-DD-YYYY":  "%m-%d-%Y",     # 05-06-2025
    "DDMMYYYY":    "%d%m%Y",       # 06052025
    "DD.MM.YYYY":  "%d.%m.%Y",     # 06.05.2025
}

TIME_FORMATS: dict[str, str] = {
    "HHMMSS":    "%H%M%S",         # 143022
    "HH-MM-SS":  "%H-%M-%S",       # 14-30-22
    "HH_MM_SS":  "%H_%M_%S",       # 14_30_22
    "HH.MM.SS":  "%H.%M.%S",       # 14.30.22
}


def _format_date(dt: datetime, fmt: str) -> str:
    return dt.strftime(DATE_FORMATS.get(fmt, "%Y%m%d"))


def _format_time(dt: datetime, fmt: str) -> str:
    return dt.strftime(TIME_FORMATS.get(fmt, "%H%M%S"))


def _next_counter(today: date) -> int:
    last_date_str = config.get("last_counter_date", "")
    counter = config.get("daily_counter", 0)

    if last_date_str != today.isoformat():
        counter = 1
        config.set("last_counter_date", today.isoformat())
    else:
        counter += 1

    config.set("daily_counter", counter)
    config.save()
    return counter


def unique_path(folder: str, stem: str, ext: str) -> Path:
    folder_path = Path(folder)
    folder_path.mkdir(parents=True, exist_ok=True)

    candidate = folder_path / f"{stem}{ext}"
    if not candidate.exists():
        return candidate

    n = 1
    while True:
        candidate = folder_path / f"{stem} ({n}){ext}"
        if not candidate.exists():
            return candidate
        n += 1


def preview_filename(template: str, date_fmt: str, time_fmt: str) -> str:
    now = datetime.now()
    today = now.date()
    date_str = _format_date(now, date_fmt)
    time_str = _format_time(now, time_fmt)
    datetime_str = f"{date_str}_{time_str}"
    user_str = os.environ.get("USERNAME", "User")

    name = template
    name = name.replace("{date}", date_str)
    name = name.replace("{time}", time_str)
    name = name.replace("{datetime}", datetime_str)
    name = name.replace("{user}", user_str)
    name = name.replace("{counter}", "1")
    return _ILLEGAL_CHARS.sub("_", name)
