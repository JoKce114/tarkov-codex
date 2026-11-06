from __future__ import annotations

import json
import sys
from pathlib import Path

from .datasets import DEFAULT_MODE, is_valid_mode

APP_NAME = "塔科夫百科"
APP_ID = "tarkov-codex"
APP_VERSION = "0.1.0"

FROZEN = bool(getattr(sys, "frozen", False))
PACKAGE_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", PACKAGE_DIR.parent))

BASE_DIR = Path(sys.executable).resolve().parent if FROZEN else PACKAGE_DIR.parent
DATA_DIR = BASE_DIR / "data"
ICON_DIR = DATA_DIR / "icons"
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = BASE_DIR / "logs"
META_FILE = DATA_DIR / "sync_meta.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

SEED_DIR = (RESOURCE_DIR / "seed") if FROZEN else (PACKAGE_DIR / "seed")
WEB_DIR = RESOURCE_DIR / "web"
ICON_FILE = PACKAGE_DIR / "icon.ico"


def ensure_dirs() -> None:
	for path in (DATA_DIR, ICON_DIR, CACHE_DIR, LOG_DIR):
		path.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
	try:
		data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
		return data if isinstance(data, dict) else {}
	except (OSError, ValueError):
		return {}


def save_settings(settings: dict) -> None:
	DATA_DIR.mkdir(parents=True, exist_ok=True)
	SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def load_mode() -> str:
	mode = load_settings().get("mode")
	return mode if isinstance(mode, str) and is_valid_mode(mode) else DEFAULT_MODE


def save_mode(mode: str) -> None:
	settings = load_settings()
	settings["mode"] = mode
	save_settings(settings)
