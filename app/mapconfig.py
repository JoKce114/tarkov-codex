from __future__ import annotations

import json
import math
import threading
from pathlib import Path

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
						"rotation": entry.get("coordinateRotation") or 0,
						"svg": entry.get("svgPath"),
						"svgLayer": entry.get("svgLayer"),
					}
					self._interactive[record["key"]] = record
					self._by_normalized[record["normalized"]] = record
					# 夜间工厂、零号区 21+ 这类变体与基础图共用同一套几何
					for alias in entry.get("altMaps") or []:
						self._by_normalized[alias] = record
			self._loaded = True

	def entry_by_normalized(self, normalized: str) -> dict | None:
		self._ensure()
		return self._by_normalized.get(normalized or "")

	def key_by_normalized(self, normalized: str) -> str:
		record = self.entry_by_normalized(normalized)
		return record["key"] if record else ""

	def svg_jobs(self) -> list[tuple[str, str]]:
		"""全部地图矢量图的 (缓存键, 远程地址)，用于批量预下载。"""
		self._ensure()
		seen: dict[str, str] = {}
		for record in self._interactive.values():
			key = record.get("key") or ""
			url = record.get("svg") or ""
			if key and url and key not in seen:
				seen[key] = url
		return list(seen.items())

	def to_normalized(self, key: str, x: float, z: float) -> tuple[float, float] | None:
		self._ensure()
		record = self._interactive.get(key)
		if not record or not record.get("bounds"):
			return None

		bounds = record["bounds"]
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
			(x - lng_min) / (lng_max - lng_min),
			(lat_max - z) / (lat_max - lat_min),
		)

