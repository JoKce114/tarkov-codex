from collections import Counter

from .map_atlas import ATLAS
from .mapconfig import MapConfig
from .store import DataStore


def _map_images(slug: str, config: MapConfig) -> list[dict]:
	asset = config.entry_by_normalized(slug) or {}
	images = list(ATLAS.get(asset.get("normalized") or slug, ()))
	if asset.get("svg"):
		images.append({"title": "地图底图", "url": asset["svg"], "originalUrl": asset["svg"]})
	return images


def _summary(row: dict, slug: str, images: list[dict]) -> dict:
	main = images[0] if images else {}
	return {
		"slug": slug,
		"name": row.get("name") or slug,
		"players": row.get("players"),
		"raidDuration": row.get("raidDuration"),
		"exitCount": len(row.get("extracts") or []),
		"previewUrl": main.get("url", ""),
		"originalUrl": main.get("originalUrl", ""),
	}


def build_map_summary(store: DataStore, map_id: str, config: MapConfig) -> dict:
	row = store.maps[map_id]
	slug = row.get("normalizedName") or map_id
	return _summary(row, slug, _map_images(slug, config))


def build_map_detail(store: DataStore, map_id: str, config: MapConfig) -> dict:
	row = store.maps[map_id]
	slug = row.get("normalizedName") or map_id
	images = _map_images(slug, config)
	key_counts = Counter(lock["key"] for lock in row.get("locks") or [] if lock.get("key"))
	for key in row.get("accessKeys") or []:
		key_counts.setdefault(key, 0)
	return {
		**_summary(row, slug, images),
		"description": row.get("description") or "",
		"wiki": row.get("wiki") or "",
		"images": images,
		"exits": row.get("extracts") or [],
		"bosses": [
			{
				"name": (store.mobs.get(boss.get("mob")) or {}).get("name") or boss.get("mob"),
				"chance": round(boss["spawnChance"] * 100, 1) if boss.get("spawnChance") is not None else None,
				"zones": "、".join(location["name"] for location in boss.get("spawnLocations") or [] if location.get("name")),
			}
			for boss in row.get("bosses") or []
		],
		"transits": [
			{"name": entry.get("description"), "target": (store.maps.get(entry.get("map")) or {}).get("name")}
			for entry in row.get("transits") or []
		],
		"hazards": [{"name": entry.get("name"), "type": entry.get("hazardType")}
			for entry in row.get("hazards") or []],
		"keys": [{"id": key, "name": (store.items.get(key) or {}).get("name") or key, "lockCount": count}
			for key, count in key_counts.items()],
	}
