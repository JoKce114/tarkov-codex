from __future__ import annotations

import json
import threading
from pathlib import Path

DEFAULT_LEVEL = 1
MAX_LEVEL = 79


class ProgressStore:
	def __init__(self, path: Path) -> None:
		self.path = path
		self._lock = threading.RLock()
		self.data = self._read()

	def _read(self) -> dict:
		try:
			payload = json.loads(self.path.read_text(encoding="utf-8"))
			return payload if isinstance(payload, dict) else {}
		except (OSError, ValueError):
			return {}

	def _write(self) -> None:
		self.path.parent.mkdir(parents=True, exist_ok=True)
		tmp = self.path.with_suffix(".json.tmp")
		tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
		tmp.replace(self.path)

	def _mode_entry(self, mode: str) -> dict:
		entry = self.data.get(mode)
		if not isinstance(entry, dict):
			entry = {}
			self.data[mode] = entry
		completed = entry.get("completed")
		if not isinstance(completed, list):
			entry["completed"] = []
		level = entry.get("playerLevel")
		if not isinstance(level, int) or not DEFAULT_LEVEL <= level <= MAX_LEVEL:
			entry["playerLevel"] = DEFAULT_LEVEL
		return entry

	def snapshot(self, mode: str) -> dict:
		with self._lock:
			entry = self._mode_entry(mode)
			return {
				"mode": mode,
				"completed": list(entry["completed"]),
				"completedCount": len(entry["completed"]),
				"playerLevel": entry["playerLevel"],
			}

	def completed_set(self, mode: str) -> set[str]:
		with self._lock:
			return set(self._mode_entry(mode)["completed"])

	def player_level(self, mode: str) -> int:
		with self._lock:
			return self._mode_entry(mode)["playerLevel"]

	def set_task(self, mode: str, task_id: str, completed: bool) -> dict:
		with self._lock:
			entry = self._mode_entry(mode)
			current = set(entry["completed"])
			if completed:
				current.add(task_id)
			else:
				current.discard(task_id)
			entry["completed"] = sorted(current)
			self._write()
			return self.snapshot(mode)

	def set_level(self, mode: str, level: int) -> dict:
		with self._lock:
			entry = self._mode_entry(mode)
			entry["playerLevel"] = max(DEFAULT_LEVEL, min(MAX_LEVEL, int(level)))
			self._write()
			return self.snapshot(mode)

	def reset(self, mode: str) -> dict:
		with self._lock:
			self.data[mode] = {"completed": [], "playerLevel": DEFAULT_LEVEL}
			self._write()
			return self.snapshot(mode)
