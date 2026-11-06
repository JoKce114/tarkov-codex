from __future__ import annotations

API_BASE = "https://json.tarkov.dev"
LANG = "zh"

# key: 本地文件名前缀; path: 接口路径; translated: 是否有 _zh 翻译文件
DATASETS = {
	"items": {"path": "items", "translated": True},
	"tasks": {"path": "tasks", "translated": True},
	"maps": {"path": "maps", "translated": True},
	"traders": {"path": "traders", "translated": True},
	"hideout": {"path": "hideout", "translated": True},
	"barters": {"path": "barters", "translated": False},
	"crafts": {"path": "crafts", "translated": False},
}

DATASET_KEYS = tuple(DATASETS)

GAME_MODES = {
	"pvp-season": "SEASON",
	"regular": "PVP",
	"pve": "PVE",
}

MODE_ORDER = ("pvp-season", "regular", "pve")
DEFAULT_MODE = "pve"


def is_valid_mode(mode: str) -> bool:
	return mode in GAME_MODES


def file_name(key: str) -> str:
	return f"{key}.json"


def translation_file_name(key: str) -> str:
	return f"{key}_{LANG}.json"


def translation_dataset_key(key: str) -> str:
	return f"{key}_{LANG}"
