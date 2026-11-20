"""从 tarkov.dev 的游戏数据和地图目录生成各模式的地图资料。"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests

from . import paths
from .assets import ASSET_HEADERS
from .bosses import is_boss_role
from .datasets import API_BASE, is_valid_mode
from .mapconfig import MapConfig, _load
from .map_atlas import ATLAS, ASSET_BASE
from .store import DataStore

SYNC_INTERVAL = 7 * 24 * 60 * 60
MAPS_URL = "https://tarkov.dev/maps/"
_IMAGE_VARIANTS = {
	"Landscape": "横版", "Dorms": "宿舍", "Resort": "疗养院", "Tunnels": "地下通道",
	"Caches": "隐藏物资点", "Lexos": "LexOs 汽车中心",
}
_catalog_lock = threading.RLock()


def map_images(group: dict) -> list[dict]:
	images = []
	for variant in group.get("maps") or []:
		projection = variant.get("projection")
		key = variant.get("key") or ""
		if projection not in ("2D", "3D") or not re.fullmatch(r"[a-z0-9-]+", key):
			continue
		details = (variant.get("specific"), variant.get("orientation"))
		title = variant.get("displayText") or variant.get("displayVariant") or " · ".join(
			[projection, *(_IMAGE_VARIANTS.get(detail, detail) for detail in details if detail)]
		)
		original = f"{MAPS_URL}{key}.jpg"
		thumb = f"{MAPS_URL}{key}_thumb.jpg"
		images.append({
			"title": title, "type": projection, "url": thumb, "originalUrl": original, "previewUrl": thumb,
			"author": variant.get("author") or "",
		})
	return images


def _source_row(map_id: str, entry: dict, raw: dict) -> dict:
	exits = [{
		"name": extract.get("name") or "", "faction": extract.get("faction") or "shared",
		"requirementTip": extract.get("requirementTip") or "", "chance": None,
	} for extract in entry.get("extracts") or []]
	bosses = []
	for boss in entry.get("bosses") or []:
		mob_id = boss.get("mob")
		mob = raw.get("mobs", {}).get(mob_id, {})
		chance = boss.get("spawnChance")
		zones = dict.fromkeys(zone.get("name") for zone in boss.get("spawnLocations") or [])
		bosses.append({
			"id": mob_id, "name": mob.get("name") or mob_id or "", "slug": mob.get("normalizedName") or "",
			"chance": round(chance * 100, 2) if isinstance(chance, (int, float)) else None,
			"zones": "、".join(zone for zone in zones if zone),
		})
	transits = [{
		"name": transit.get("description") or "",
		"target": (raw["maps"].get(transit.get("map")) or {}).get("name") or "",
	} for transit in entry.get("transits") or []]
	hazards = []
	hazard_types = {"minefield": "地雷", "sniper": "狙击手"}
	for kind, name in dict.fromkeys((h.get("hazardType"), h.get("name")) for h in entry.get("hazards") or []):
		hazards.append({"name": name or "", "type": hazard_types.get(kind, kind)})
	if (entry.get("artillery") or {}).get("zones"):
		hazards.append({"name": "炮击区", "type": "炮击"})
	key_counts = Counter(lock["key"] for lock in entry.get("locks") or [] if lock.get("key"))
	keys = [{"id": key_id, "lockCount": count} for key_id, count in key_counts.items()]
	slug = entry["normalizedName"]
	return {
		"id": map_id, "slug": slug, "name": entry.get("name") or "", "nameEn": slug.replace("-", " ").title(),
		"players": entry.get("players"), "raidDuration": entry.get("raidDuration"),
		"description": entry.get("description") or "",
		"exitCount": len(exits), "pmcExitCount": sum(row["faction"] == "pmc" for row in exits),
		"scavExitCount": sum(row["faction"] == "scav" for row in exits),
		"bossCount": len(bosses), "keyCount": len(keys), "keys": keys, "exits": exits, "bosses": bosses,
		"transits": transits, "hazards": hazards,
	}


def _catalog_path(folder: Path) -> Path:
	return folder.parent / "maps" / folder.name / "maps.json"


def _boss_rules(source: list[dict], names: dict) -> list[dict]:
	rules = {}
	for entry in source:
		# 早期索引只存翻译键。上游 mobs 的原始名称也是角色 ID。
		role = entry.get("id") or entry["name"]
		if not is_boss_role(role):
			continue
		slug = entry["slug"] or role
		rule = rules.setdefault((slug, entry["chance"]), {
			"id": role, "name": names.get(entry["name"]) or slug.replace("-", " ").title(),
			"slug": slug, "chance": entry["chance"], "zones": {},
		})
		for zone in entry["zones"].split("、"):
			if zone:
				rule["zones"][names.get(zone) or zone] = None
	return [{**rule, "zones": "、".join(rule["zones"])} for rule in rules.values()]


def has_catalog_source(folder: Path) -> bool:
	try:
		data = json.loads(_catalog_path(folder).read_bytes())
		return bool(data.get("source") and data.get("maps"))
	except (OSError, ValueError, AttributeError):
		return False


def _local_names(folder: Path, dataset: str) -> dict:
	try:
		return json.loads((folder / f"{dataset}_zh.json").read_bytes()).get("data") or {}
	except FileNotFoundError:
		return {}


def write_catalog(
	folder: Path, raw_payload: dict | bytes | None = None, *, names: dict | None = None, items: dict | None = None,
) -> dict:
	"""从本次 maps 响应生成目录，保留原文索引供翻译变动时本地重建。"""
	if not is_valid_mode(folder.name):
		raise ValueError("无效的游戏模式目录")
	target = _catalog_path(folder)
	config = MapConfig()
	images = {group["normalizedName"]: map_images(group) for group in _load()}
	with _catalog_lock:
		if raw_payload is None:
			source = json.loads(target.read_bytes()).get("source")
			if not source:
				raise ValueError("缺少地图资料的原文索引")
		else:
			payload = json.loads(raw_payload) if isinstance(raw_payload, bytes) else raw_payload
			raw = payload.get("data") or {}
			records = raw.get("maps") or {}
			if not isinstance(records, dict) or not any("extracts" in entry or "spawns" in entry or "bosses" in entry for entry in records.values()):
				raise ValueError("地图响应缺少完整资料")
			source = [_source_row(map_id, entry, raw) for map_id, entry in records.items()]
		names = names if names is not None else _local_names(folder, "maps")
		item_names = _local_names(folder, "items")
		rows = []
		for original in source:
			row = dict(original)
			key = row["slug"]
			record = config.entry_by_normalized(key)
			row["images"] = images.get(record["normalized"] if record else key) or []
			row["previewUrl"] = row["images"][0]["previewUrl"] if row["images"] else ""
			for field in ("name", "description"):
				row[field] = names.get(original[field]) or original[field]
			for group, fields in (
				("exits", ("name", "requirementTip")),
				("transits", ("name", "target")), ("hazards", ("name",)),
			):
				row[group] = [
					{**entry, **{field: names.get(entry[field]) or entry[field] for field in fields}}
					for entry in original[group]
				]
			row["bosses"] = _boss_rules(original["bosses"], names)
			row["bossCount"] = len({boss["slug"] for boss in row["bosses"]})
			row["keys"] = [
				{**entry, "name": item_names.get(entry["id"] + " Name") or (items or {}).get(entry["id"], {}).get("name") or entry["id"]}
				for entry in original["keys"]
			]
			rows.append(row)
		stamp = datetime.now().isoformat(timespec="seconds")
		target.parent.mkdir(parents=True, exist_ok=True)
		temp = target.with_suffix(".tmp")
		temp.write_text(json.dumps({"syncedAt": stamp, "maps": rows, "source": source}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
		temp.replace(target)
	return {"ok": True, "mode": folder.name, "count": len(rows), "syncedAt": stamp}


class MapStore:
	def __init__(self, store: DataStore | None = None) -> None:
		self.store = store if store is not None else DataStore(paths.DATA_DIR, paths.load_mode())
		self.root = self.store.data_dir / "maps"
		self._lock = threading.RLock()
		self._image_lock = threading.Lock()
		self._syncing = False
		self.last_result = {}
		self._session = requests.Session()
		self._session.headers.update({**ASSET_HEADERS, "Accept": "*/*"})
		self.catalog = {group["normalizedName"]: map_images(group) for group in _load()}
		self.image_urls = {
			image[field] for variants in self.catalog.values() for image in variants for field in ("originalUrl", "previewUrl")
		}
		self.image_urls.update(image[field] for images in ATLAS.values() for image in images for field in ("url", "originalUrl"))
		self.config = MapConfig()

	def _read(self, mode: str) -> dict:
		try:
			data = json.loads((self.root / mode / "maps.json").read_bytes())
			return data if isinstance(data, dict) else {}
		except (OSError, ValueError):
			return {}

	def maps(self) -> list[dict]:
		rows = [row for row in self._read(self.store.mode).get("maps") or [] if row.get("slug") != "ground-zero-tutorial"]
		for row in rows:
			slug = row.get("slug") or ""
			record = self.config.entry_by_normalized(slug) or {}
			localized = ATLAS.get(record.get("normalized") or slug, ())
			if localized:
				row["images"] = [*localized, *(row.get("images") or [])]
				row["previewUrl"] = localized[0]["previewUrl"]
		return rows

	def status(self) -> dict:
		mode = self.store.mode
		data = self._read(mode)
		with self._lock:
			return {
				"mode": mode, "syncedAt": data.get("syncedAt") or "", "count": sum(row.get("slug") != "ground-zero-tutorial" for row in data.get("maps") or []),
				"intervalSeconds": SYNC_INTERVAL, "syncing": self._syncing, "lastResult": self.last_result,
			}

	def _fetch(self, url: str) -> dict:
		for attempt in range(3):
			try:
				response = self._session.get(url, timeout=(8, 45))
				response.raise_for_status()
				return response.json()
			except (requests.RequestException, ValueError):
				if attempt == 2:
					raise
				time.sleep(0.6 * (attempt + 1))

	def sync(self, mode: str = "") -> dict:
		mode = mode or self.store.mode
		if not is_valid_mode(mode):
			return {"ok": False, "error": "无效的游戏模式"}
		with self._lock:
			if self._syncing:
				return {"ok": False, "error": "地图资料正在同步"}
			self._syncing = True
		result = {"ok": False, "mode": mode, "error": "地图资料同步中断"}
		try:
			raw = self._fetch(f"{API_BASE}/{mode}/maps").get("data") or {}
			names = self._fetch(f"{API_BASE}/{mode}/maps_zh").get("data") or {}
			if not raw.get("maps") or not names:
				raise ValueError("地图数据或中文翻译为空")
			# 物品表随游戏模式切换。离线脚本可直接读取已同步的物品翻译。
			with self.store._lock:
				items = self.store.items if self.store.mode == mode else {}
			result = write_catalog(self.store.data_dir / mode, {"data": raw}, names=names, items=items)
		except (requests.RequestException, OSError, ValueError, KeyError, TypeError) as error:
			result = {"ok": False, "mode": mode, "error": str(error)}
		finally:
			with self._lock:
				self._syncing = False
				self.last_result = result
		return result

	def image_path(self, url: str) -> Path:
		return self.root / "images" / Path(urlsplit(url).path).name

	def fetch_image(self, url: str) -> Path | None:
		if url not in self.image_urls:
			return None
		target = self.image_path(url)
		if target.is_file():
			return target
		with self._image_lock:
			if target.is_file():
				return target
			try:
				headers = {"Accept": "image/webp" if target.suffix == ".webp" else "image/jpeg"}
				if url.startswith(ASSET_BASE):
					headers["Referer"] = "https://www.tarkovbox.com/"
				response = self._session.get(url, headers=headers, timeout=(8, 90))
				response.raise_for_status()
				content = response.content
				if target.suffix == ".webp":
					valid = content.startswith(b"RIFF") and content[8:12] == b"WEBP"
				else:
					valid = content.startswith(b"\xff\xd8\xff")
				if not valid:
					return None
				target.parent.mkdir(parents=True, exist_ok=True)
				temp = target.with_suffix(".tmp")
				temp.write_bytes(response.content)
				temp.replace(target)
				return target
			except (OSError, requests.RequestException):
				return None

	def start_scheduler(self) -> None:
		return
