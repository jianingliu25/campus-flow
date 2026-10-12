"""Resolve runtime settings without creating directories or loading models."""

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    timezone: str
    data_dir: Path
    demo_date: date


def get_settings() -> Settings:
    load_dotenv(ROOT / ".env", override=False)
    timezone = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
    zone = ZoneInfo(timezone)
    configured = os.getenv("DATA_DIR", "").strip()
    if configured:
        data_dir = Path(configured).expanduser().resolve()
    elif os.name == "nt":
        data_dir = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "CampusFlow"
    else:
        data_dir = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "campus-flow"
    frozen_date = os.getenv("DEMO_REFERENCE_DATE", "").strip()
    return Settings(timezone, data_dir, date.fromisoformat(frozen_date) if frozen_date else datetime.now(zone).date())
