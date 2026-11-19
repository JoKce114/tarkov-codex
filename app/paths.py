from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
from tempfile import NamedTemporaryFile
from pathlib import Path

from .datasets import DEFAULT_MODE, MODE_ORDER, is_valid_mode

APP_NAME = "塔科夫百科"
APP_ID = "tarkov-codex"
APP_VERSION = "0.3.0"

FROZEN = bool(getattr(sys, "frozen", False))
PACKAGE_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", PACKAGE_DIR.parent))

BASE_DIR = Path(sys.executable).resolve().parent if FROZEN else PACKAGE_DIR.parent
USER_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "TarkovCodex" if FROZEN else BASE_DIR
DATA_DIR = USER_DIR / "data"
ICON_DIR = DATA_DIR / "icons"
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = USER_DIR / "logs"
META_FILE = DATA_DIR / "sync_meta.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
_SETTINGS_LOCK = threading.RLock()

SEED_DIR = (RESOURCE_DIR / "seed") if FROZEN else (PACKAGE_DIR / "seed")
WEB_DIR = RESOURCE_DIR / "web"
ICON_FILE = (RESOURCE_DIR if FROZEN else PACKAGE_DIR) / "icon.ico"


def migrate_data(source: Path, destination: Path) -> None:
	"""迁移旧版便携目录。目标已有的文件优先，未完成的复制可在下次启动时继续。"""
	if source.resolve() == destination.resolve() or not source.is_dir():
		return
	def copy_missing(previous: Path, target: Path) -> None:
		if previous.is_symlink() or not previous.is_file():
			return
		if target.exists():
			return
		target.parent.mkdir(parents=True, exist_ok=True)
		with NamedTemporaryFile(dir=target.parent, delete=False) as handle:
			temp = Path(handle.name)
		try:
			shutil.copy2(previous, temp)
			temp.replace(target)
		finally:
			temp.unlink(missing_ok=True)
	try:
		generation = json.loads((source / "current.json").read_text(encoding="utf-8"))["generation"]
	except (OSError, KeyError, ValueError, TypeError):
		generation = None
	if isinstance(generation, str) and re.fullmatch("[0-9a-f]{32}", generation):
		active = source / "snapshots" / generation
		for mode in MODE_ORDER:
			for previous in (active / mode).glob("*"):
				copy_missing(previous, destination / mode / previous.name)
	for previous in source.iterdir():
		if previous.name in {"snapshots", "update", "installers"} or previous.is_symlink():
			continue
		if previous.is_dir():
			for child in previous.rglob("*"):
				copy_missing(child, destination / child.relative_to(source))
		else:
			copy_missing(previous, destination / previous.name)


def ensure_dirs() -> None:
	if FROZEN and not (DATA_DIR / ".portable_migrated").exists():
		source = BASE_DIR / "data"
		migrate_data(source, DATA_DIR)
		DATA_DIR.mkdir(parents=True, exist_ok=True)
		if source.is_dir():
			(DATA_DIR / ".portable_migrated").touch()
	for path in (DATA_DIR, ICON_DIR, CACHE_DIR, LOG_DIR):
		path.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
	try:
		data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
		return data if isinstance(data, dict) else {}
	except (OSError, ValueError):
		return {}


def save_settings(settings: dict) -> None:
	with _SETTINGS_LOCK:
		DATA_DIR.mkdir(parents=True, exist_ok=True)
		with NamedTemporaryFile(mode="w", encoding="utf-8", dir=DATA_DIR, delete=False) as output:
			json.dump(settings, output, ensure_ascii=False, indent="\t")
		Path(output.name).replace(SETTINGS_FILE)


def save_update_proxy(proxy: str) -> None:
	with _SETTINGS_LOCK:
		settings = load_settings()
		update = settings.get("update")
		settings["update"] = {**(update if isinstance(update, dict) else {}), "proxy": proxy}
		save_settings(settings)


def load_mode() -> str:
	mode = load_settings().get("mode")
	return mode if isinstance(mode, str) and is_valid_mode(mode) else DEFAULT_MODE


def save_mode(mode: str) -> None:
	with _SETTINGS_LOCK:
		settings = load_settings()
		settings["mode"] = mode
		save_settings(settings)
