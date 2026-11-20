from collections import Counter

from .mapconfig import MapConfig
from .store import DataStore


def build_map_summary(store: DataStore, map_id: str, config: MapConfig) -> dict:
	row = store.maps[map_id]
	slug = row.get("normalizedName") or map_id
	asset = config.entry_by_normalized(slug) or {}
	return {
		"slug": slug,
		"name": row.get("name") or slug,
		"players": row.get("players"),
		"raidDuration": row.get("raidDuration"),
		"exitCount": len(row.get("extracts") or []),
		"previewUrl": asset.get("svg") or "",
	}


def build_map_detail(store: DataStore, map_id: str, config: MapConfig) -> dict:
	row = store.maps[map_id]
	summary = build_map_summary(store, map_id, config)
	url = summary["previewUrl"]
	key_counts = Counter(lock["key"] for lock in row.get("locks") or [] if lock.get("key"))
	for key in row.get("accessKeys") or []:
		key_counts.setdefault(key, 0)
	return {
		**summary,
		"description": row.get("description") or "",
		"wiki": row.get("wiki") or "",
		"images": [{"title": "地图底图", "url": url}] if url else [],
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
