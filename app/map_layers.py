"""按游戏模式缓存地图标记。压缩包按地图分条，打开地图时只读当前条目。"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, is_zipfile

from .datasets import is_valid_mode, translation_file_name

CACHE_FILE = "map_layers_v4.zip"
_cache_lock = threading.RLock()
_point_fields = {
	"extracts", "spawns", "transits", "locks", "hazards", "lootContainers",
	"lootLoose", "switches", "stationaryWeapons", "btrStops", "artillery",
}
_extract_factions = {"pmc": "PMC", "scav": "Scav", "shared": "共享"}
_special_spawns = {
	"rogue": "游荡者", "cultist-priest": "邪教徒祭司", "black-div": "黑色军团",
	"af": "俄军", "bloodhound": "血猎犬",
}
_spawn_icons = {
	"PMC": "spawn_pmc", "Scav": "spawn_scav", "狙击 Scav": "spawn_sniper_scav", "Boss": "spawn_boss",
	**{name: "spawn_" + slug for slug, name in _special_spawns.items()},
}
_container_icons = {
	"bank-cash-register": "cash-register", "bank-safe": "safe", "civilian-body": "dead-scav",
	"pmc-body": "dead-scav", "lab-technician-body": "dead-scav", "scav-body": "dead-scav",
	"medical-supply-crate": "crate", "ration-supply-crate": "crate", "technical-supply-crate": "crate",
	"shturmans-stash": "weapon-box",
}


def _json_file(path: Path) -> dict:
	try:
		payload = json.loads(path.read_bytes())
		return payload if isinstance(payload, dict) else {}
	except (OSError, ValueError):
		return {}


def _spawn_markers(entry: dict, mobs: dict):
	# 与 tarkov.dev 一致，以出生点的区域关联 NPC。一个区域可有多个 Boss。
	zones = {}
	zone_mobs = {}
	for boss in entry.get("bosses", []):
		mob_id = boss.get("mob")
		mob = mobs.get(mob_id, {})
		kind = mob.get("normalizedName") or mob_id
		for location in boss.get("spawnLocations", []):
			zone = location.get("spawnKey")
			if zone and kind:
				zones.setdefault(zone, {})[kind] = mob.get("name") or mob_id
				zone_mobs.setdefault(zone, set()).update(
					[mob_id, *(escort["mob"] for escort in boss.get("escorts", []) if escort.get("mob"))]
				)

	for spawn in entry.get("spawns", []):
		categories = spawn.get("categories") or []
		sides = spawn.get("sides") or []
		names = []
		boss_ids = []
		kind = ""
		if "boss" in categories:
			bosses = zones.get(spawn.get("zoneName"), {})
			if bosses:
				names = list(bosses.values())
				boss_ids = sorted(zone_mobs[spawn["zoneName"]])
				kind = _special_spawns.get(next(iter(bosses)), "Boss") if len(bosses) == 1 else "Boss"
			elif "bot" in categories and "scav" in sides:
				kind = "Scav"
		elif "player" in categories:
			if "pmc" in sides or "all" in sides:
				kind = "PMC"
		elif "sniper" in categories:
			kind = "狙击 Scav"
		elif "scav" in sides and ("bot" in categories or "all" in categories):
			kind = "Scav"
		if kind:
			yield spawn.get("position"), kind, names or [kind], boss_ids


def _map_entry(entry: dict, body: dict) -> dict:
	points = []
	fallbacks = {}
	container_types = {}
	for definition in (body.get("lootContainers") or {}).values():
		slug = definition.get("normalizedName")
		if slug and definition.get("name"):
			container_types.setdefault(slug, definition["name"])

	def add(position, group, kind, label, **extra):
		if not isinstance(position, dict):
			return
		x, z = position.get("x"), position.get("z")
		if not all(type(value) in (int, float) and math.isfinite(value) for value in (x, z)):
			return
		height = position.get("y")
		if type(height) in (int, float) and math.isfinite(height):
			extra["height"] = height
		points.append({"group": group, "type": kind, "label": label or kind, "x": x, "z": z, **extra})

	for extract in entry.get("extracts", []):
		kind = _extract_factions.get(extract.get("faction") or "shared", "撤离点")
		add(extract.get("position"), "extracts", kind, extract.get("name"), icon="extract_" + (extract.get("faction") or "shared"))
	for position, kind, names, boss_ids in _spawn_markers(entry, body.get("mobs", {})):
		add(position, "spawns", kind, names, icon=_spawn_icons[kind], bossIds=boss_ids)
	for switch in entry.get("switches", []):
		add(switch.get("position"), "interactives", "开关", switch.get("name"), icon="switch")
	for lock in entry.get("locks", []):
		label = "车厢锁" if lock.get("lockType") == "trunk" else "门锁"
		add(lock.get("position"), "interactives", "锁", label, keyId=lock.get("key"), icon="lock")
	for weapon in entry.get("stationaryWeapons", []):
		definition = body.get("stationaryWeapons", {}).get(weapon.get("stationaryWeapon"), {})
		name = definition.get("name") or "固定机枪"
		fallbacks[name] = (definition.get("normalizedName") or name).replace("-", " ")
		add(weapon.get("position"), "interactives", "固定机枪", name, icon="stationarygun")
	for container in entry.get("lootContainers", []):
		definition = body.get("lootContainers", {}).get(container.get("lootContainer"), {})
		name = definition.get("name") or "容器"
		slug = definition.get("normalizedName")
		kind = container_types.get(slug, name)
		fallbacks[name] = fallbacks[kind] = (slug or name).replace("-", " ")
		add(container.get("position"), "containers", kind, name, icon="container_" + _container_icons.get(slug, slug or "crate"))
	for loot in entry.get("lootLoose", []):
		item_ids = list(dict.fromkeys(item for item in (loot.get("items") or []) if isinstance(item, str)))
		add(loot.get("position"), "loot", "散落物资", "散落物资", itemIds=item_ids, icon="loose_loot")
	for transit in entry.get("transits", []):
		add(transit.get("position"), "transits", "转移点", transit.get("description"), icon="extract_transit")
	for hazard in entry.get("hazards", []):
		kind = {"minefield": "地雷", "sniper": "狙击手"}.get(hazard.get("hazardType"), "危险区")
		add(hazard.get("position"), "hazards", kind, hazard.get("name"), icon="hazard")
	for zone in (entry.get("artillery") or {}).get("zones", []):
		add(zone.get("position"), "hazards", "炮击区", "炮击区", icon="hazard_mortar")
	for stop in entry.get("btrStops", []):
		add(stop, "transport", "BTR 停靠点", stop.get("name"), icon="btr_stop")
	return {
		"points": points, "fallbacks": fallbacks,
		"players": entry.get("players"), "raidDuration": entry.get("raidDuration"),
	}


def write_map_layers(folder: Path, payload: dict) -> bool:
	"""完整地图源生成一份原子替换的图层压缩包；旧版精简源保留已有缓存。"""
	body = payload.get("data") if isinstance(payload, dict) else None
	maps = body.get("maps") if isinstance(body, dict) else None
	if not isinstance(maps, dict) or not any(_point_fields.intersection(entry) for entry in maps.values()):
		return False
	folder.mkdir(parents=True, exist_ok=True)
	with _cache_lock:
		with NamedTemporaryFile(dir=folder, prefix="map_layers_", suffix=".tmp", delete=False) as handle:
			temp = Path(handle.name)
		try:
			with ZipFile(temp, "w", compression=ZIP_DEFLATED) as archive:
				from .bosses import boss_records

				locations = {}
				for map_id, entry in maps.items():
					result = _map_entry(entry, body)
					for point in result["points"]:
						for mob_id in point.get("bossIds", []):
							counts = locations.setdefault(mob_id, {})
							counts[map_id] = counts.get(map_id, 0) + 1
					data = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
					archive.writestr(map_id, data.encode("utf-8"))
				archive.writestr("bosses", json.dumps(boss_records(body, locations), ensure_ascii=False, separators=(",", ":")))
			temp.replace(folder / CACHE_FILE)
		finally:
			temp.unlink(missing_ok=True)
	return True


def has_map_layers(folder: Path) -> bool:
	return is_zipfile(folder / CACHE_FILE)


def restore_map_layers(folder: Path, source: Path) -> bool:
	with _cache_lock:
		if has_map_layers(folder):
			return True
		return write_map_layers(folder, _json_file(source))


def read_map_layers(data_dir: Path, mode: str, map_id: str) -> dict | None:
	if not is_valid_mode(mode):
		return None
	folder = data_dir / mode
	with _cache_lock:
		archive_path = folder / CACHE_FILE
		if not restore_map_layers(folder, folder / "maps.json"):
			archive_path = next(
				(path for path in (folder / "map_layers_v3.zip", folder / "map_layers_v2.zip") if is_zipfile(path)),
				folder / "map_layers_v1.zip",
			)
		try:
			with ZipFile(archive_path) as archive:
				entry = json.loads(archive.read(map_id))
		except (OSError, ValueError, KeyError, BadZipFile):
			return None
	names = _json_file(folder / translation_file_name("maps")).get("data")
	if not isinstance(names, dict):
		names = {}
	fallbacks = entry.pop("fallbacks", {})

	def translate(value: str) -> str:
		return names.get(value) or fallbacks.get(value) or value

	for point in entry["points"]:
		point["type"] = translate(point["type"])
		label = point["label"]
		point["label"] = "、".join(translate(name) for name in label) if isinstance(label, list) else translate(label)
	return entry
