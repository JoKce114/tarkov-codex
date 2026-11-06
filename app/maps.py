from __future__ import annotations

"""从 TarkovBox 抓取地图与标注信息。"""

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

from .paths import DATA_DIR

MAP_DIR = DATA_DIR / "maps"
MAP_IMAGE_DIR = MAP_DIR / "images"
MAP_FILE = MAP_DIR / "maps.json"
SYNC_INTERVAL = 7 * 24 * 60 * 60
TIMEOUT = 40
RETRY = 3

HEADERS = {
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
	"Accept-Language": "zh-CN,zh;q=0.9",
}

LIST_URL = "https://www.tarkovbox.com/gamewiki/maps"
DETAIL_URL = "https://www.tarkovbox.com/gamewiki/maps/{slug}"


def now_text() -> str:
	return datetime.now().isoformat(timespec="seconds")


def read_nuxt(source: str) -> list | None:
	start = source.find('id="__NUXT_DATA__"')
	if start == -1:
		return None
	chunk_start = source.find(">", start) + 1
	chunk_end = source.find("</script>", chunk_start)
	if chunk_end == -1:
		return None
	try:
		return json.loads(source[chunk_start:chunk_end])
	except ValueError:
		return None


class Table:
	"""Nuxt 的扁平表：每个格子要么是值，要么是索引。"""

	def __init__(self, data: list) -> None:
		self.data = data

	def value(self, cell):
		if isinstance(cell, bool) or cell is None:
			return cell
		if isinstance(cell, int) and 0 <= cell < len(self.data):
			return self.data[cell]
		return cell

	def row(self, cell, depth: int = 2) -> dict:
		node = self.value(cell)
		if not isinstance(node, dict):
			return {}
		result = {}
		for key, inner in node.items():
			value = self.value(inner)
			if depth > 1 and isinstance(value, dict):
				value = {k: self.value(v) for k, v in value.items()}
			result[key] = value
		return result

	def rows(self, cell) -> list[dict]:
		node = self.value(cell)
		if not isinstance(node, list):
			return []
		return [self.row(entry) for entry in node]


class MapStore:
	def __init__(self) -> None:
		self._lock = threading.RLock()
		self._image_lock = threading.Lock()
		self._session = requests.Session()
		self._session.headers.update(HEADERS)
		self._syncing = False
		self.last_result: dict = {}
		MAP_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

	def _read(self) -> dict:
		try:
			data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
			return data if isinstance(data, dict) else {}
		except (OSError, ValueError):
			return {}

	def _write(self, payload: dict) -> None:
		MAP_DIR.mkdir(parents=True, exist_ok=True)
		tmp = MAP_FILE.with_suffix(".json.tmp")
		tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
		tmp.replace(MAP_FILE)

	def _fetch(self, url: str) -> str | None:
		for attempt in range(RETRY):
			try:
				response = self._session.get(url, timeout=TIMEOUT)
				if response.status_code == 200:
					return response.text
			except requests.RequestException:
				pass
			if attempt < RETRY - 1:
				time.sleep(3)
		return None

	def _parse_summary(self, table: Table, cell) -> dict:
		summary = table.row(cell)
		return {
			"id": summary.get("id"),
			"slug": summary.get("slug") or summary.get("mapKey") or "",
			"name": summary.get("nameZh") or summary.get("nameEn") or "",
			"nameEn": summary.get("nameEn") or "",
			"players": summary.get("players") or "",
			"raidDuration": summary.get("raidDuration"),
			"previewUrl": summary.get("imageUrl") or "",
			"exitCount": summary.get("exitCount"),
			"bossCount": summary.get("bossCount"),
			"pmcExitCount": summary.get("pmcExitCount"),
			"scavExitCount": summary.get("scavExitCount"),
			"keyCount": summary.get("keyCount"),
		}

	def _parse_exits(self, table: Table, cell) -> list[dict]:
		result = []
		for entry in table.rows(cell):
			result.append(
				{
					"name": entry.get("exitNameZh") or entry.get("exitName") or "",
					"faction": entry.get("exitFaction") or "",
					"type": entry.get("exitType") or "",
					"requirement": entry.get("requirementCode") or entry.get("requirement") or "",
					"requirementTip": entry.get("requirementTip") or "",
					"chance": entry.get("chancePvpPercent") if entry.get("chancePvpPercent") is not None else entry.get("chance"),
					"chancePve": entry.get("chancePvePercent") if entry.get("chancePvePercent") is not None else entry.get("chancePve"),
				}
			)
		return result

	def _parse_bosses(self, table: Table, cell) -> list[dict]:
		result = []
		for entry in table.rows(cell):
			result.append(
				{
					"name": entry.get("bossNameZh") or entry.get("bossNameEn") or "",
					"nameEn": entry.get("bossNameEn") or "",
					"slug": entry.get("bossSlug") or "",
					"chance": entry.get("chancePvpPercent") if entry.get("chancePvpPercent") is not None else entry.get("chance"),
					"chancePve": entry.get("chancePvePercent") if entry.get("chancePvePercent") is not None else entry.get("chance"),
					"zones": entry.get("zoneCodes") or "",
				}
			)
		return result

	def _parse_transits(self, table: Table, cell) -> list[dict]:
		result = []
		for entry in table.rows(cell):
			result.append(
				{
					"name": entry.get("nameZh") or "",
					"target": entry.get("targetMapNameZh") or entry.get("targetMapName") or "",
					"description": entry.get("descriptionZh") or "",
				}
			)
		return result

	def _parse_hazards(self, table: Table, cell) -> list[dict]:
		result = []
		for entry in table.rows(cell):
			result.append(
				{
					"name": entry.get("nameZh") or entry.get("name") or entry.get("hazardType") or "",
					"type": entry.get("hazardType") or "",
				}
			)
		return result

	def _parse_keys(self, table: Table, cell) -> list[dict]:
		result = []
		for entry in table.rows(cell):
			result.append(
				{
					"id": entry.get("itemId") or "",
					"name": entry.get("itemNameZh") or entry.get("itemNameEn") or "",
					"icon": entry.get("itemIcon") or "",
					"lockCount": entry.get("lockCount") if isinstance(entry.get("lockCount"), int) else None,
				}
			)
		return result

	def _parse_images(self, table: Table, cell) -> list[dict]:
		result = []
		for entry in table.rows(cell):
			preview = entry.get("previewUrl") or ""
			original = entry.get("url") or entry.get("assetUrl") or preview
			if not preview and not original:
				continue
			result.append(
				{
					"title": entry.get("titleZh") or entry.get("title") or "",
					"type": entry.get("imageType") or "main",
					"url": preview or original,
					"originalUrl": original,
					"previewUrl": preview or original,
				}
			)
		return result

	def _parse_detail(self, source: str) -> dict | None:
		data = read_nuxt(source)
		if not data:
			return None
		table = Table(data)
		body = table.value(6)
		if not isinstance(body, dict):
			return None
		return {
			"summary": self._parse_summary(table, body.get("summary")),
			"description": str(table.value(body.get("descriptionZh")) or ""),
			"exits": self._parse_exits(table, body.get("exits")),
			"bosses": self._parse_bosses(table, body.get("bosses")),
			"transits": self._parse_transits(table, body.get("transits")),
			"hazards": self._parse_hazards(table, body.get("hazards")),
			"keys": self._parse_keys(table, body.get("keys")),
			"images": self._parse_images(table, body.get("images")),
		}

	def _parse_list(self, source: str) -> list[dict]:
		data = read_nuxt(source)
		if not data:
			return []
		table = Table(data)
		body = table.value(6)
		if not isinstance(body, dict):
			return []
		return [self._parse_summary(table, entry) for entry in table.value(body.get("items")) or []]

	def image_path(self, url: str) -> Path:
		name = url.rsplit("/", 1)[-1]
		name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
		return MAP_IMAGE_DIR / name

	def fetch_image(self, url: str) -> Path | None:
		target = self.image_path(url)
		if target.exists():
			return target
		with self._image_lock:
			try:
				# 原图可能十几 MB，读超时给足；连接超时仍设短值，避免网络不通时干等
				response = self._session.get(url, timeout=(10, 180))
				if response.status_code != 200 or not response.content:
					return None
				target.parent.mkdir(parents=True, exist_ok=True)
				tmp = target.with_suffix(target.suffix + ".tmp")
				tmp.write_bytes(response.content)
				tmp.replace(target)
				return target
			except (requests.RequestException, OSError):
				return None

	def sync(self) -> dict:
		with self._lock:
			if self._syncing:
				return {"ok": False, "error": "正在同步"}
			self._syncing = True

		try:
			list_html = self._fetch(LIST_URL)
			if not list_html:
				return {"ok": False, "error": "地图列表获取失败"}
			items = self._parse_list(list_html)

			maps = []
			for summary in items:
				slug = summary.get("slug")
				if not slug:
					continue
				detail_html = self._fetch(DETAIL_URL.format(slug=slug))
				time.sleep(0.4)
				detail = self._parse_detail(detail_html) if detail_html else None
				if not detail:
					maps.append({**summary, "exits": [], "bosses": [], "keys": [], "images": []})
					continue
				merged = {**summary, **detail["summary"]}
				merged.update(
					{
						"description": detail["description"],
						"exits": detail["exits"],
						"bosses": detail["bosses"],
						"transits": detail["transits"],
						"hazards": detail["hazards"],
						"keys": detail["keys"],
						"images": detail["images"],
					}
				)
				maps.append(merged)

			payload = {"syncedAt": now_text(), "maps": maps}
			self._write(payload)
			result = {"ok": True, "count": len(maps), "syncedAt": payload["syncedAt"]}
			self.last_result = result
			return result
		finally:
			self._syncing = False

	def maps(self) -> list[dict]:
		with self._lock:
			return self._read().get("maps") or []

	def status(self) -> dict:
		data = self._read()
		return {
			"syncedAt": data.get("syncedAt") or "",
			"count": len(data.get("maps") or []),
			"intervalSeconds": SYNC_INTERVAL,
			"syncing": self._syncing,
			"lastResult": self.last_result,
		}

	def start_scheduler(self) -> None:
		"""保留接口但不再自动运行；同步统一由界面按钮触发。"""
		return
