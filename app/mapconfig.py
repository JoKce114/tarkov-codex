from __future__ import annotations

import json
import math
import re
import threading

from . import paths

_CONFIG_FILE = (paths.RESOURCE_DIR / "map_config.json") if paths.FROZEN else (paths.PACKAGE_DIR / "map_config.json")


def _load() -> list[dict]:
	try:
		return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
	except (OSError, ValueError):
		return []


def _rotate(x: float, y: float, rotation: float) -> tuple[float, float]:
	angle = math.radians(rotation or 0)
	cos_a, sin_a = math.cos(angle), math.sin(angle)
	return x * cos_a - y * sin_a, x * sin_a + y * cos_a


class MapConfig:
	"""把游戏坐标换算成地图矢量图上的坐标。

	换算规则取自 tarkov.dev 的 Leaflet CRS.Simple 实现：先按 coordinateRotation
	旋转，再按 bounds 归一化到 SVG 的 viewBox。
	"""

	def __init__(self) -> None:
		self._lock = threading.Lock()
		self._loaded = False
		self._interactive: dict[str, dict] = {}
		self._by_normalized: dict[str, dict] = {}

	def _ensure(self) -> None:
		if self._loaded:
			return
		with self._lock:
			if self._loaded:
				return
			for group in _load():
				for entry in group.get("maps") or []:
					if entry.get("projection") != "interactive":
						continue
					record = {
						"key": entry.get("key"),
						"normalized": group.get("normalizedName"),
						"bounds": entry.get("bounds"),
						"svgBounds": entry.get("svgBounds"),
						"rotation": entry.get("coordinateRotation") or 0,
						"svg": entry.get("svgPath"),
						"svgLayer": entry.get("svgLayer"),
						"labels": entry.get("labels") or [],
						"author": entry.get("author") or "",
						"tilePath": entry.get("tilePath") or "",
						"tileSize": entry.get("tileSize") or 256,
						"transform": entry.get("transform"),
						"floors": {},
						"width": 0.0,
						"height": 0.0,
					}
					for index, layer in enumerate(entry.get("layers") or []):
						if layer.get("tilePath") and layer["tilePath"] == record["tilePath"]:
							record["baseName"] = layer.get("name")
						elif layer.get("tilePath") or layer.get("svgLayer"):
							record["floors"][f"floor-{index}"] = layer
					self._interactive[record["key"]] = record
					self._by_normalized[record["normalized"]] = record
					# 夜间工厂、零号区 21+ 这类变体与基础图共用同一套几何
					for alias in entry.get("altMaps") or []:
						self._by_normalized[alias] = record
					if record["normalized"] == "ground-zero":
						self._by_normalized["ground-zero-tutorial"] = record
			self._loaded = True

	def entry_by_normalized(self, normalized: str) -> dict | None:
		self._ensure()
		return self._by_normalized.get(normalized or "")

	def entries(self) -> list[dict]:
		self._ensure()
		return list(self._interactive.values())

	def key_by_normalized(self, normalized: str) -> str:
		record = self.entry_by_normalized(normalized)
		return record["key"] if record else ""

	def set_viewbox(self, key: str, width: float, height: float) -> None:
		self._ensure()
		record = self._interactive.get(key)
		if record:
			record["width"] = width
			record["height"] = height

	def to_svg(
		self, key: str, x: float, z: float, viewport: tuple[float, float] | None = None,
		*, bounds: list | None = None,
	) -> tuple[float, float] | None:
		self._ensure()
		record = self._interactive.get(key)
		if not record or not record.get("bounds"):
			return None
		width, height = viewport or (record.get("width") or 0.0, record.get("height") or 0.0)
		if width <= 0 or height <= 0:
			return None

		bounds = bounds or record["bounds"]
		rotation = record["rotation"]
		lng_min, lng_max = bounds[1][0], bounds[0][0]
		lat_min, lat_max = bounds[0][1], bounds[1][1]

		if rotation:
			x, z = _rotate(x, z, rotation)
			lng_a, lat_a = _rotate(lng_min, lat_min, rotation)
			lng_b, lat_b = _rotate(lng_max, lat_max, rotation)
			lng_min, lng_max = min(lng_a, lng_b), max(lng_a, lng_b)
			lat_min, lat_max = min(lat_a, lat_b), max(lat_a, lat_b)

		if lng_max == lng_min or lat_max == lat_min:
			return None

		return (
			(x - lng_min) / (lng_max - lng_min) * width,
			(lat_max - z) / (lat_max - lat_min) * height,
		)


def svg_viewbox(svg_text: str) -> tuple[float, float, float, float] | None:
	root = re.search(r"<svg\b[^>]*>", svg_text[:8192])
	match = re.search(r"""\bviewBox\s*=\s*(["'])([^"']+)\1""", root[0]) if root else None
	if not match:
		return None
	parts = match.group(2).replace(",", " ").split()
	if len(parts) != 4:
		return None
	try:
		x, y, width, height = map(float, parts)
	except ValueError:
		return None
	if min(width, height) <= 0 or not all(math.isfinite(value) for value in (x, y, width, height)):
		return None
	return x, y, width, height


def read_viewbox(svg_text: str) -> tuple[float, float] | None:
	box = svg_viewbox(svg_text)
	return box[2:] if box else None


def tile_viewport(record: dict, zoom: int, bounds: list | None = None) -> tuple[float, float, float, float]:
	"""Leaflet 的世界像素边界，瓦片编号与点位共用这套原点与尺度。"""
	scale_x, margin_x, scale_y, margin_y = record["transform"]
	pixels = []
	for x, z in bounds or record["bounds"]:
		x, z = _rotate(x, z, record["rotation"])
		pixels.append(((scale_x * x + margin_x) * 2**zoom, (margin_y - scale_y * z) * 2**zoom))
	(first_x, first_y), (last_x, last_y) = pixels
	return min(first_x, last_x), min(first_y, last_y), abs(last_x - first_x), abs(last_y - first_y)
