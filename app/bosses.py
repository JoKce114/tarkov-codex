"""从各模式 maps 数据提取首领的装备、随身物品及出没地图。"""

from __future__ import annotations

import json
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from . import paths
from .assets import IconCache
from .map_layers import CACHE_FILE, _json_file, restore_map_layers
from .store import DataStore

_BOSS_ROLES = {"sectantPriest", "infectedTagilla", "followerBigPipe", "followerBirdEye", "ExUsec", "exUsecFree", "PmcBot"}
_BODY_PARTS = {"Head": "头部", "Chest": "胸部", "Stomach": "腹部", "LeftArm": "左臂", "RightArm": "右臂", "LeftLeg": "左腿", "RightLeg": "右腿"}


def is_boss_role(mob_id: str) -> bool:
	return isinstance(mob_id, str) and (mob_id.startswith("boss") or mob_id in _BOSS_ROLES)


def boss_records(body: dict, locations: dict) -> dict:
	records = {}
	for mob_id, mob in (body.get("mobs") or {}).items():
		if not is_boss_role(mob_id):
			continue
		equipment = {}
		for kit in mob.get("equipment") or []:
			if kit.get("item"):
				equipment.setdefault(kit["item"], None)
			for part in kit.get("contains") or []:
				if part.get("item"):
					equipment.setdefault(part["item"], None)
		records[mob_id] = {
			"id": mob_id, "slug": mob.get("normalizedName") or mob_id, "name": mob.get("name") or mob_id,
			"portrait": mob.get("imagePortraitLink") or "", "equipment": list(equipment),
			"loot": list(dict.fromkeys(row["id"] for row in mob.get("items") or [] if row.get("id"))),
			"health": {_BODY_PARTS.get(row["id"], row["id"]): row["max"] for row in mob.get("health") or [] if row.get("id") and "max" in row},
			"maps": [],
		}
	for map_id, entry in body["maps"].items():
		appearances = {}
		for spawn in entry.get("bosses") or []:
			leader = spawn.get("mob")
			escorts = [escort["mob"] for escort in spawn.get("escorts") or [] if escort.get("mob") and escort["mob"] != leader]
			actors = [leader, *escorts]
			zones = [zone.get("name") or zone.get("spawnKey") for zone in spawn.get("spawnLocations") or []]
			for mob_id in actors:
				if mob_id in records:
					appearance = appearances.setdefault(mob_id, {"chances": set(), "zones": {}, "escorts": {}})
					appearance["zones"].update(dict.fromkeys(zone for zone in zones if zone))
					if mob_id == leader:
						appearance["escorts"].update(dict.fromkeys(
							(body.get("mobs", {}).get(escort_id) or {}).get("name") or escort_id for escort_id in escorts
						))
					chance = spawn.get("spawnChance")
					if isinstance(chance, (float, int)) and 0 <= chance <= 1:
						appearance["chances"].add(chance)
		for mob_id, appearance in appearances.items():
			records[mob_id]["maps"].append({
				"key": entry.get("normalizedName"), "name": entry.get("name") or entry.get("normalizedName"),
				"chances": sorted(appearance["chances"]), "pointCount": locations.get(mob_id, {}).get(map_id, 0),
				"zones": list(appearance["zones"]), "escorts": list(appearance["escorts"]),
			})
	return records


def _data(store: DataStore) -> tuple[dict | None, dict]:
	folder = store.data_dir / store.mode
	archive_path = folder / CACHE_FILE
	if not restore_map_layers(folder, folder / "maps.json"):
		archive_path = folder / "map_layers_v3.zip"
	try:
		with ZipFile(archive_path) as archive:
			records = json.loads(archive.read("bosses"))
	except (OSError, BadZipFile, KeyError, ValueError):
		return None, {}
	return records, _json_file(folder / "maps_zh.json").get("data") or {}


def _summary(record: dict, names: dict) -> dict:
	return {
		"id": record["id"], "name": names.get(record["name"]) or record["slug"].replace("-", " ").title(),
		"slug": record["slug"], "portrait": record["portrait"],
		"maps": [{
			**entry, "name": names.get(entry["name"]) or entry["key"],
			**{field: list(dict.fromkeys(names.get(key) or key for key in entry.get(field, []))) for field in ("zones", "escorts")},
		} for entry in record["maps"]],
	}


def boss_router(store: DataStore) -> APIRouter:
	router = APIRouter(prefix="/api/bosses")
	images = IconCache(store.data_dir / "icons")

	@router.get("")
	def catalog():
		with store._lock:
			records, names = _data(store)
			return {"mode": store.mode, "available": records is not None, "bosses": [
				_summary(record, names) for record in (records or {}).values()
			]}

	@router.get("/{mob_id}")
	def detail(mob_id: str):
		with store._lock:
			records, names = _data(store)
			record = (records or {}).get(mob_id)
			if not record:
				raise HTTPException(404, "当前模式没有此首领")
			summary = _summary(record, names)
			descriptions = _json_file(paths.WEB_DIR / "bosses_zh.json")
			slug = record["slug"]
			info = {
				**summary, "mode": store.mode, "health": record["health"],
				"bio": descriptions.get(slug + "-bio") or "", "description": descriptions.get(slug + "-description") or "",
			}
			for key in ("equipment", "loot"):
				info[key] = [
					{"id": item_id, "name": (store.items.get(item_id) or {}).get("name") or item_id,
					 "available": item_id in store.items}
					for item_id in record[key]
				]
			return info

	@router.get("/{mob_id}/portrait")
	def portrait(mob_id: str):
		with store._lock:
			records, _ = _data(store)
			record = (records or {}).get(mob_id)
			if not record or not record["portrait"].startswith("https://assets.tarkov.dev/"):
				raise HTTPException(404, "暂无首领图片")
			url = record["portrait"]
		image = images.get("boss-" + mob_id, url)
		if not image:
			raise HTTPException(404, "首领图片暂不可用")
		return Response(image[0], media_type=image[1], headers={"Cache-Control": "public, max-age=604800"})

	return router
