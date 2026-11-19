from __future__ import annotations

import math
from collections.abc import Iterator
from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.etree import ElementTree

import requests

from .assets import ASSET_HEADERS, SvgCache
from .map_layers import read_map_layers
from .mapconfig import MapConfig, svg_viewbox, tile_viewport
from .progress import ProgressStore
from .store import DataStore


BASE_MAP_NAMES = {
	"streets-of-tarkov": "塔科夫街区", "ground-zero": "零号区", "customs": "海关",
	"factory": "工厂", "icebreaker": "破冰船", "interchange": "立交桥",
	"the-lab": "实验室", "the-labyrinth": "迷宫", "lighthouse": "灯塔",
	"reserve": "储备站", "shoreline": "海岸线", "terminal": "码头", "woods": "森林",
}
FLOOR_NAMES = {
	"2nd Floor": "二楼", "3rd Floor": "三楼", "4th Floor": "四楼", "5th Floor": "五楼",
	"Underground": "地下", "Bunkers": "地下掩体", "Garage": "车库", "Tunnels": "地道",
	"Second Level": "二层", "Technical": "技术层", "Infirmary": "医务室", "Helipad": "直升机停机坪",
	"Gym/Canteen": "健身房与餐厅", "Accommodation (lower)": "居住区下层",
	"Accommodation (mid)": "居住区中层", "Accommodation (upper)": "居住区上层",
	"Officers' Deck": "军官甲板", "Stairs (blocked)": "封锁楼梯", "Bridge": "舰桥",
	"Bridge Roof": "舰桥顶部", "Control Room": "控制室", "Engine Room": "轮机舱",
	"Engine Room (upper)": "轮机舱上层", "Fuel Pumps (lower)": "燃油泵下层",
	"Fuel Pumps": "燃油泵", "Storage/Security": "仓储与安保区",
}
TILE_ZOOM = 3
MAX_TILE_BYTES = 2 * 1024 * 1024
PNG_HEADER = b"\x89PNG\r\n\x1a\n"
ElementTree.register_namespace("", "http://www.w3.org/2000/svg")
ElementTree.register_namespace("xlink", "http://www.w3.org/1999/xlink")


def map_catalog(maps: dict, config: MapConfig) -> list[dict]:
	names = {entry["normalizedName"]: entry.get("name") for entry in maps.values() if entry.get("normalizedName")}
	result = []
	for record in config.entries():
		base = record["normalized"]
		keys = [base] if base in names or not maps else []
		keys.extend(key for key in names if key != base and config.key_by_normalized(key) == record["key"])
		for key in keys:
			result.append({"key": key, "name": names.get(key) or BASE_MAP_NAMES.get(key) or key})
	return result


def map_geometry(record: dict, svg_cache: SvgCache) -> dict | None:
	if record["svg"]:
		box = svg_viewbox(svg_cache.get(record["key"], record["svg"]) or "")
		if box is None:
			return None
		origin_x, origin_y, width, height = box
	elif record["tilePath"]:
		_, _, width, height = tile_viewport(record, TILE_ZOOM)
		origin_x = origin_y = 0
	else:
		return None
	return {
		"width": width, "height": height, "originX": origin_x, "originY": origin_y,
		"hasSvg": bool(record["svg"]),
	}


def map_tiles(record: dict, floor: str = "base", geometry: dict | None = None) -> Iterator[tuple[int, int, dict]]:
	left, top, width, height = tile_viewport(record, TILE_ZOOM)
	# 瓦片编号使用地图范围，叠加到 SVG 时位置与尺寸使用底图自己的范围。
	view_left, view_top, view_width, view_height = left, top, width, height
	if geometry and geometry["hasSvg"] and record["svgBounds"]:
		view_left, view_top, view_width, view_height = tile_viewport(record, TILE_ZOOM, record["svgBounds"])
	size = record["tileSize"]
	scale_x = geometry["width"] / view_width if geometry else 1
	scale_y = geometry["height"] / view_height if geometry else 1
	suffix = f"?floor={floor}" if floor != "base" else ""
	for column in range(math.floor(left / size), math.ceil((left + width) / size)):
		for row in range(math.floor(top / size), math.ceil((top + height) / size)):
			yield column, row, {
				"x": (column * size - view_left) * scale_x, "y": (row * size - view_top) * scale_y,
				"width": size * scale_x, "height": size * scale_y,
				"url": f"/api/atlas/tile/{record['key']}/{TILE_ZOOM}/{column}/{row}{suffix}",
			}


def read_tile(cache_dir: Path, record: dict | None, zoom: int, column: int, row: int, floor: str = "base") -> bytes | None:
	if not record:
		return None
	layer = record if floor == "base" else record["floors"].get(floor, {})
	template = layer.get("tilePath") or ""
	if (
		zoom != TILE_ZOOM or not template.startswith("https://assets.tarkov.dev/maps/")
		or not any(x == column and y == row for x, y, _ in map_tiles(record))
	):
		return None
	target = cache_dir / "tiles" / record["key"] / floor / str(zoom) / str(column) / f"{row}.png"
	temp_path = None
	try:
		if target.is_file():
			return target.read_bytes()
		url = template.format(z=zoom, x=column, y=row)
		headers = {**ASSET_HEADERS, "Accept": "image/png"}
		with requests.get(url, headers=headers, timeout=(5, 15), stream=True, allow_redirects=False) as response:
			if response.status_code != 200:
				return None
			payload = bytearray()
			for chunk in response.iter_content(65536):
				payload.extend(chunk)
				if len(payload) > MAX_TILE_BYTES:
					return None
		if not payload.startswith(PNG_HEADER):
			return None
		target.parent.mkdir(parents=True, exist_ok=True)
		with NamedTemporaryFile(dir=target.parent, delete=False) as temp:
			temp_path = Path(temp.name)
			temp.write(payload)
		temp_path.replace(target)
		return bytes(payload)
	except (OSError, requests.RequestException):
		return None
	finally:
		if temp_path is not None:
			temp_path.unlink(missing_ok=True)


def floor_svg(svg: str, record: dict, floor: str) -> bytes | None:
	if floor != "base" and floor not in record["floors"]:
		return None
	try:
		root = ElementTree.fromstring(svg)
	except ElementTree.ParseError:
		return None
	base = record["svgLayer"]
	selected = record["floors"].get(floor, {}).get("svgLayer")
	for group in list(root):
		group_id = group.get("id")
		if not group.tag.endswith("}g") or not group_id:
			continue
		if selected and group_id == selected:
			# 地下层也需要覆盖在地面之上，不受源 SVG 节点顺序影响。
			root.remove(group)
			root.append(group)
		elif group_id != base and group.get("data-keep-with-group") != base:
			root.remove(group)
	return ElementTree.tostring(root, encoding="utf-8")


def _floors(record: dict, geometry: dict) -> list[dict]:
	if not record["floors"]:
		return []
	result = []
	for key, layer in [("base", record), *record["floors"].items()]:
		name = layer.get("name") or record.get("baseName") or ("地面层" if record["svg"] else "一层")
		floor = {"key": key, "name": FLOOR_NAMES.get(name, name)}
		if record["svg"]:
			floor["svgUrl"] = f"/api/map/svg/{record['key']}?floor={key}"
		if layer.get("tilePath") and (not record["svg"] or not layer.get("svgLayer")):
			floor["tiles"] = [tile for _, _, tile in map_tiles(record, key, geometry)]
		result.append(floor)
	return result


def _floor_keys(
	record: dict, x: float, z: float, height: float | None, bottom: float | None = None, top: float | None = None,
) -> list[str]:
	if not record["floors"]:
		return []
	if top is None and bottom is None:
		if not isinstance(height, (int, float)):
			return []
		bottom = top = height
	else:
		bottom = -math.inf if bottom is None else bottom
		top = math.inf if top is None else top
	if bottom > top:
		return []
	matches = []
	covered = []
	for key, layer in record["floors"].items():
		for extent in layer.get("extents") or []:
			low, high = extent["height"]
			if bottom == top:
				overlaps = low <= bottom < high
			else:
				overlaps = bottom < high and top > low
			if not overlaps:
				continue
			bounds = extent.get("bounds") or []
			if not bounds or any(
				min(first[0], second[0]) <= x <= max(first[0], second[0])
				and min(first[1], second[1]) <= z <= max(first[1], second[1])
				for first, second, *_ in bounds
			):
				if key not in matches:
					matches.append(key)
				covered.append((max(low, bottom), min(high, top)))
	if not matches:
		return ["base"]
	if bottom < top:
		# 跨层建筑标注也应出现在楼层覆盖区间之外的地面部分。
		end = bottom
		for low, high in sorted(covered):
			if low > end:
				break
			end = max(end, high)
		if end < top:
			matches.insert(0, "base")
	return matches


def _project(config: MapConfig, record: dict, geometry: dict, position: dict, *, legacy: bool = False) -> dict | None:
	x, z = position.get("x"), position.get("z")
	if not isinstance(x, (float, int)) or not isinstance(z, (float, int)):
		return None
	width, height = geometry["width"], geometry["height"]
	bounds = record["svgBounds"] if geometry["hasSvg"] and not legacy else None
	point = config.to_svg(record["key"], x, z, (width, height), bounds=bounds)
	# 与已有任务小地图相同，保留边界附近 2% 的标记，过滤数据源中的异常坐标。
	if point is None or not (-width * 0.02 <= point[0] <= width * 1.02 and -height * 0.02 <= point[1] <= height * 1.02):
		return None
	return {"x": round(point[0], 1), "y": round(point[1], 1)}


def _task_locations(task: dict) -> Iterator[tuple[int, int, dict, dict, str]]:
	for objective_index, objective in enumerate(task.get("objectives") or []):
		zones = objective.get("zones") or []
		for zone_index, zone in enumerate(zones):
			yield objective_index, zone_index, objective, zone, "目标"
		# 各张地图的候选物品位置排在同一目标的区域之后，索引不受地图筛选影响。
		point_index = len(zones)
		for location in objective.get("possibleLocations") or []:
			for position in location.get("positions") or []:
				yield objective_index, point_index, objective, {"map": location.get("map"), "position": position}, "物品"
				point_index += 1


def _task_map_groups(
	task: dict, maps: dict, config: MapConfig, svg_cache: SvgCache,
	geometries: dict, selected_map: str = "",
) -> list[dict]:
	groups = {}
	for objective_index, point_index, objective, zone, kind in _task_locations(task):
		entry = maps.get(zone.get("map")) or {}
		normalized = entry.get("normalizedName") or ""
		record = config.entry_by_normalized(normalized)
		if record is None:
			continue
		key = record["key"]
		if selected_map and selected_map != normalized:
			continue
		if key not in geometries:
			geometries[key] = map_geometry(record, svg_cache)
		geometry = geometries[key]
		if not geometry:
			continue
		position = zone.get("position") or {}
		point = _project(config, record, geometry, position, legacy=not selected_map)
		if point is None:
			continue
		if key not in groups:
			groups[key] = {"mapKey": record["normalized"], "mapName": entry.get("name") or "", **geometry, "points": []}
		group = groups[key]
		if normalized == record["normalized"]:
			group["mapName"] = entry.get("name") or group["mapName"]
		size = zone.get("size") or {}
		group["points"].append({
			**point, "label": objective.get("description") or "", "type": objective.get("type") or "",
			"optional": bool(objective.get("optional")), "radiusX": round(float(size.get("x") or 0) * 0.5, 1),
			"radiusZ": round(float(size.get("z") or 0) * 0.5, 1),
			"objectiveIndex": objective_index, "pointIndex": point_index, "taskKind": kind,
			"icon": "quest_item" if kind == "物品" else "quest_objective",
			"mapKey": normalized, "mapName": entry.get("name") or BASE_MAP_NAMES.get(normalized) or normalized,
			"floorKeys": _floor_keys(record, position["x"], position["z"], position.get("y")),
		})
	return list(groups.values())


def build_task_map(task: dict, store: DataStore, map_config: MapConfig, svg_cache: SvgCache) -> dict:
	return {"maps": _task_map_groups(task, store.maps, map_config, svg_cache, {})}


def atlas_detail(
	map_key: str, record: dict, geometry: dict, config: MapConfig, store: DataStore,
	progress: ProgressStore, svg_cache: SvgCache,
) -> dict:
	points = []
	item_ids = set()
	for label in record["labels"]:
		position = label.get("position") or []
		name = (label.get("text") or "").strip()
		if len(position) < 2 or not any(char.isalnum() for char in name):
			continue
		point = _project(config, record, geometry, {"x": position[0], "z": position[1]})
		if point:
			height = position[2] if len(position) > 2 else None
			points.append({
				**point, "group": "landmarks", "type": "地标", "label": name,
				"floorKeys": _floor_keys(record, position[0], position[1], height, label.get("bottom"), label.get("top")),
			})

	# 把同一模式的翻译、任务进度和图层一起读取，避免切换模式时混用两个存档。
	with store._lock:
		map_id, map_entry = next(
			((map_id, entry) for map_id, entry in store.maps.items() if entry.get("normalizedName") == map_key),
			("", {}),
		)
		layers = read_map_layers(store.data_dir, store.mode, map_id) if map_id else None
		for marker in (layers or {}).get("points", []):
			point = _project(config, record, geometry, marker)
			if point is None:
				continue
			projected = {field: value for field, value in marker.items() if field not in ("x", "z")}
			if marker.get("keyId"):
				projected["itemIds"] = list(dict.fromkeys([*(marker.get("itemIds") or []), marker["keyId"]]))
			item_ids.update(projected.get("itemIds") or [])
			projected["floorKeys"] = _floor_keys(record, marker["x"], marker["z"], marker.get("height"))
			points.append({**projected, **point})
		names = {}
		categories = {}
		for item_id in item_ids:
			item = store.items.get(item_id) or {}
			if item.get("name"):
				names[item_id] = item["name"]
			# 游戏数据的 categories 从具体分类到根分类排列。
			for category_id in item.get("categories") or []:
				category = store.categories.get(category_id) or {}
				if category.get("name"):
					categories[item_id] = category["name"]
					break
		state = progress.snapshot(store.mode)
		completed = set(state["completed"])
		geometries = {record["key"]: geometry}
		for task_id, task in store.tasks.items():
			groups = _task_map_groups(task, store.maps, config, svg_cache, geometries, map_key)
			if not groups:
				continue
			status = "已完成" if task_id in completed else (
				"可接" if store.is_unlocked(task, completed, state["playerLevel"]) else "未解锁"
			)
			for point in groups[0]["points"]:
				points.append({**point, "group": "tasks", "type": status, "taskId": task_id, "taskName": task.get("name") or ""})
	return {
		"mapKey": map_key, "mapName": map_entry.get("name") or BASE_MAP_NAMES.get(map_key) or map_key,
		**geometry, "author": record["author"], "players": (layers or {}).get("players") or "",
		"raidDuration": (layers or {}).get("raidDuration"), "hasLayers": layers is not None,
		"tiles": [] if geometry["hasSvg"] else [tile for _, _, tile in map_tiles(record)],
		"floors": _floors(record, geometry),
		"points": points, "itemNames": names, "itemCategories": categories,
	}
