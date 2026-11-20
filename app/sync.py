from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import requests

from . import slim
from .datasets import API_BASE, DATASETS, DEFAULT_MODE, LANG, MODE_ORDER, file_name, is_valid_mode
from .store import DataStore


def now_text() -> str:
	return datetime.now().isoformat(timespec="seconds")


def write_json(path: Path, payload: dict) -> None:
	tmp = path.with_suffix(".json.tmp")
	tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
	os.replace(tmp, path)


def validate_dataset(key: str, payload: dict) -> None:
	data = payload.get("data") if isinstance(payload, dict) else None
	if key in ("items", "tasks", "maps"):
		data = data.get(key) if isinstance(data, dict) else None
	expected = list if key in ("barters", "crafts") else dict
	if not isinstance(data, expected) or not data:
		raise ValueError("资料为空或 JSON 结构异常")
	if not key.endswith(f"_{LANG}"):
		rows = data.values() if isinstance(data, dict) else data
		if not all(isinstance(row, dict) for row in rows):
			raise ValueError("资料条目格式异常")


class SyncManager:
	"""生成完整资料后一次启用。查询始终持有一份已加载的 DataStore。"""

	def __init__(self, data_dir: Path, mode: str = DEFAULT_MODE, seed_dir: Path | None = None) -> None:
		self.data_dir = data_dir
		self._lock = threading.Lock()
		self._mode = mode
		self._stores = {key: DataStore(data_dir, key) for key in MODE_ORDER}
		self._running = False
		self._worker: threading.Thread | None = None
		self._progress = {"done": 0, "total": 0, "label": ""}
		self.last_finished_at = ""
		self.last_result: dict | None = None
		self._session = requests.Session()
		self._session.headers.update({"Accept": "application/json", "User-Agent": "Tarkov-Codex"})
		self._generation = ""
		for directory in (data_dir, seed_dir):
			if directory is not None and self._load_generation(directory):
				break

	def _load_generation(self, directory: Path) -> bool:
		try:
			manifest = json.loads((directory / "current.json").read_text(encoding="utf-8"))
			generation = manifest["generation"]
			if not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{32}", generation):
				return False
			root = directory / "snapshots" / generation
			stores = {}
			for mode in MODE_ORDER:
				store = DataStore(root, mode)
				store.load()
				if not (store.items and store.tasks and store.maps and all(store.stats()["datasets"].values())):
					return False
				stores[mode] = store
		except (OSError, ValueError, KeyError, TypeError, AttributeError):
			return False
		self._stores = stores
		self.last_finished_at = manifest.get("finishedAt", "")
		if directory == self.data_dir:
			self._generation = generation
		return True

	@property
	def current(self) -> DataStore:
		with self._lock:
			return self._stores[self._mode]

	def set_mode(self, mode: str) -> DataStore:
		if not is_valid_mode(mode):
			raise ValueError("无效的游戏模式")
		with self._lock:
			self._mode = mode
			return self._stores[mode]

	def status(self) -> dict:
		with self._lock:
			return {
				"mode": self._mode,
				"running": self._running,
				"progress": dict(self._progress),
				"lastFinishedAt": self.last_finished_at,
				"lastResult": self.last_result,
			}

	def _request(self, url: str) -> requests.Response:
		for attempt in range(3):
			try:
				response = self._session.get(url, timeout=(5, 30))
				response.raise_for_status()
				return response
			except requests.RequestException:
				if attempt == 2:
					raise
				time.sleep(attempt + 1)
		raise RuntimeError("请求失败")

	def _reserve(self) -> bool:
		with self._lock:
			if self._running:
				return False
			self._running = True
			self.last_result = None
			self._progress = {
				"done": 0,
				"total": len(MODE_ORDER) * sum(1 + spec["translated"] for spec in DATASETS.values()),
				"label": "",
			}
			return True

	def sync_all(self) -> dict:
		if not self._reserve():
			return {"ok": False, "error": "正在重建资料"}
		return self._rebuild()

	def start_background(self) -> bool:
		if not self._reserve():
			return False
		self._worker = threading.Thread(target=self._rebuild, daemon=True, name="rebuild-data")
		self._worker.start()
		return True

	def _rebuild(self) -> dict:
		started = time.monotonic()
		generation = uuid4().hex
		root = self.data_dir / "snapshots" / generation
		stores = {}
		mode = key = ""
		previous = ""
		published = False
		result = {"ok": False, "errors": []}
		try:
			for mode in MODE_ORDER:
				target = root / mode
				target.mkdir(parents=True)
				for dataset, spec in DATASETS.items():
					suffixes = ("", f"_{LANG}") if spec["translated"] else ("",)
					for suffix in suffixes:
						key = dataset + suffix
						with self._lock:
							self._progress["label"] = f"{mode} / {key}"
						response = self._request(f"{API_BASE}/{mode}/{spec['path']}{suffix}")
						payload = json.loads(response.content)
						validate_dataset(key, payload)
						write_json(target / file_name(key), slim.apply(key, payload))
						with self._lock:
							self._progress["done"] += 1
				key = "索引"
				store = DataStore(root, mode)
				store.load()
				store.validate_references()
				stores[mode] = store
			mode = ""
			key = "启用资料"
			finished = now_text()
			write_json(self.data_dir / "current.json", {"generation": generation, "finishedAt": finished})
			with self._lock:
				previous, self._generation = self._generation, generation
				previous_stores = self._stores
				self._stores = stores
				self.last_finished_at = finished
			published = True
			result["ok"] = True
			# 释放旧索引可能遍历数千条对象，避免在查询需要的锁内释放。
			del previous_stores
		except Exception as error:
			result["errors"].append({"mode": mode, "key": key, "error": str(error)})
		finally:
			if not published:
				shutil.rmtree(root, ignore_errors=True)
			elif previous:
				shutil.rmtree(root.parent / previous, ignore_errors=True)
			result.update(finishedAt=now_text(), seconds=round(time.monotonic() - started, 2))
			with self._lock:
				self.last_result = result
				self._running = False
		return result
