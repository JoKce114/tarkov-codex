from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

from . import slim
from .datasets import (
	API_BASE,
	DATASETS,
	MODE_ORDER,
	DATASET_KEYS,
	LANG,
	file_name,
	translation_file_name,
	translation_dataset_key,
)

SYNC_INTERVAL = 2 * 60 * 60
TIMEOUT = 180
RETRY_TIMES = 3
RETRY_GAP = 5.0

HEADERS = {
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
	"Referer": "https://tarkov.dev/",
	"Accept": "application/json",
}


def now_text() -> str:
	return datetime.now().isoformat(timespec="seconds")


def read_meta(path: Path) -> dict:
	try:
		return json.loads(path.read_text(encoding="utf-8"))
	except (OSError, ValueError):
		return {}


def write_meta(path: Path, meta: dict) -> None:
	tmp = path.with_suffix(".json.tmp")
	tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
	os.replace(tmp, path)


def write_bytes(path: Path, payload: bytes) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix(path.suffix + ".tmp")
	tmp.write_bytes(payload)
	os.replace(tmp, path)


def mode_dir(data_dir: Path, mode: str) -> Path:
	return data_dir / mode


def slim_payload(key: str, raw: bytes) -> bytes:
	"""落盘前精简，避免每次启动加载用不到的大字段。"""
	if key not in ("items", "maps", "tasks"):
		return raw
	try:
		payload = json.loads(raw.decode("utf-8"))
	except (ValueError, UnicodeDecodeError):
		return raw
	payload = slim.apply(key, payload)
	return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class SyncManager:
	def __init__(self, data_dir: Path) -> None:
		self.data_dir = data_dir
		self.meta_file = data_dir / "sync_meta.json"
		self.meta = read_meta(self.meta_file)
		self._lock = threading.Lock()
		self._running = False
		self._session = requests.Session()
		self._session.headers.update(HEADERS)
		self.last_result = None
		self.last_finished_at = self._latest_synced_at()

	def _mode_meta(self, mode: str) -> dict:
		entry = self.meta.get(mode)
		if not isinstance(entry, dict):
			entry = {}
			self.meta[mode] = entry
		return entry

	def _latest_synced_at(self) -> str:
		stamps = []
		for mode_entry in self.meta.values():
			if not isinstance(mode_entry, dict):
				continue
			for item in mode_entry.values():
				if isinstance(item, dict) and item.get("syncedAt"):
					stamps.append(item["syncedAt"])
		return max(stamps) if stamps else ""

	def status(self, mode: str) -> dict:
		mode_entry = self.meta.get(mode) or {}
		return {
			"mode": mode,
			"running": self._running,
			"intervalSeconds": SYNC_INTERVAL,
			"lastFinishedAt": self.last_finished_at,
			"modeLastSyncedAt": max(
				[item.get("syncedAt", "") for item in mode_entry.values() if isinstance(item, dict)] or [""]
			),
			"lastResult": self.last_result,
			"datasets": {
				key: {
					"syncedAt": mode_entry.get(key, {}).get("syncedAt", ""),
					"bytes": mode_entry.get(key, {}).get("bytes", 0),
				}
				for key in DATASET_KEYS
			},
		}

	def _request(self, url: str, etag: str) -> requests.Response:
		headers = {"If-None-Match": etag} if etag else {}
		last_error = None
		for attempt in range(RETRY_TIMES):
			try:
				response = self._session.get(url, headers=headers, timeout=TIMEOUT)
				if response.status_code in (200, 304, 404):
					return response
				last_error = f"HTTP {response.status_code}"
			except requests.RequestException as error:
				last_error = str(error)
			if attempt < RETRY_TIMES - 1:
				time.sleep(RETRY_GAP)
		raise RuntimeError(last_error or "请求失败")

	def _sync_one(self, mode: str, key: str, url_path: str, force: bool) -> dict:
		mode_entry = self._mode_meta(mode)
		entry = mode_entry.get(key, {})
		etag = "" if force else entry.get("etag", "")
		response = self._request(f"{API_BASE}/{mode}/{url_path}", etag)
		if response.status_code == 304:
			return {"mode": mode, "key": key, "changed": False, "bytes": 0}
		if response.status_code == 404:
			return {"mode": mode, "key": key, "changed": False, "bytes": 0, "missing": True}
		payload = response.content
		payload = slim_payload(key, payload)
		write_bytes(mode_dir(self.data_dir, mode) / file_name(key), payload)
		mode_entry[key] = {
			"etag": response.headers.get("ETag", ""),
			"syncedAt": now_text(),
			"bytes": len(payload),
		}
		return {"mode": mode, "key": key, "changed": True, "bytes": len(payload)}

	def sync_mode(self, mode: str, force: bool = False) -> dict:
		started = time.monotonic()
		results = []
		errors = []
		for key in DATASET_KEYS:
			spec = DATASETS[key]
			try:
				results.append(self._sync_one(mode, key, spec["path"], force))
				if spec["translated"]:
					results.append(
						self._sync_one(mode, translation_dataset_key(key), f"{spec['path']}_{LANG}", force)
					)
			except Exception as error:
				errors.append({"mode": mode, "key": key, "error": str(error)})
		changed = [item["key"] for item in results if item.get("changed")]
		return {
			"ok": not errors,
			"mode": mode,
			"changed": changed,
			"changedCount": len(changed),
			"errors": errors,
			"seconds": round(time.monotonic() - started, 2),
			"finishedAt": now_text(),
		}

	def sync_all(self, force: bool = False) -> dict:
		with self._lock:
			if self._running:
				return {"skipped": True, "reason": "正在同步"}
			self._running = True

		started = time.monotonic()
		mode_results = []
		try:
			for mode in MODE_ORDER:
				mode_results.append(self.sync_mode(mode, force))
			write_meta(self.meta_file, self.meta)
			self.last_finished_at = self._latest_synced_at()
		finally:
			with self._lock:
				self._running = False

		changed = [f"{item['mode']}/{key}" for item in mode_results for key in item["changed"]]
		results = {
			"ok": all(item["ok"] for item in mode_results),
			"changed": changed,
			"changedCount": len(changed),
			"errors": [error for item in mode_results for error in item["errors"]],
			"seconds": round(time.monotonic() - started, 2),
			"finishedAt": now_text(),
		}
		self.last_result = results
		return results

	def start_background(self, force: bool = False) -> bool:
		with self._lock:
			if self._running:
				return False
		threading.Thread(target=self.sync_all, args=(force,), daemon=True).start()
		return True

	def start_scheduler(self) -> None:
		"""保留接口但不再自动运行；同步统一由界面按钮触发。"""
		return


def seed_if_missing(data_dir: Path, seed_dir: Path) -> int:
	"""首次运行时把打包内的出厂数据（含地图预览图、攻略截图）复制到 data 目录。"""
	copied = 0
	if not seed_dir.is_dir():
		return copied
	for source in seed_dir.rglob("*"):
		if not source.is_file():
			continue
		relative = source.relative_to(seed_dir)
		target = data_dir / relative
		if target.exists():
			continue
		target.parent.mkdir(parents=True, exist_ok=True)
		target.write_bytes(source.read_bytes())
		copied += 1
	return copied
