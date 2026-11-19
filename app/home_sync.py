from __future__ import annotations

import threading

from .map_icons import sync_map_icons
from .sync import now_text, read_meta


class HomeSync:
	"""首页发起的资料同步按依赖顺序执行，状态可跨页面查看。"""

	def __init__(self, store, manager, guides, cdk):
		self.store = store
		self.manager = manager
		self.guides = guides
		self.cdk = cdk
		self._lock = threading.Lock()
		self._running = False
		self._revision = 0
		self._jobs = {}

	def status(self) -> dict:
		with self._lock:
			status = {"running": self._running, "revision": self._revision, "jobs": dict(self._jobs)}
		# 任务索引在加载时整体替换，同一次状态读取使用同一模式下的数据。
		with self.store._lock:
			stats = self.store.stats()
			tasks = self.store.tasks
		mode = stats["mode"]
		game = self.manager.status(mode)
		checks = game["checks"]
		catalog = read_meta(self.store.data_dir / "maps" / mode / "maps.json")
		maps = catalog.get("maps") or []
		guide_status = self.guides.status()
		guides = guide_status["sources"]["optarkov"]
		guided = self.guides.guided_task_ids().intersection(tasks)
		if guide_status["syncing"]:
			status["running"] = True
			status["jobs"]["guides"] = {
				"state": "running", "progress": guide_status.get("progress") or {},
			}
		codes = self.cdk.status()
		status["history"] = {
			"game": {
				"lastSuccessfulAt": "", "updatedAt": game["modeLastSyncedAt"], **checks.get("game", {}),
				"loaded": sum(stats["datasets"].values()), "total": len(stats["datasets"]),
			},
			"maps": {
				"lastSuccessfulAt": "", "updatedAt": catalog.get("syncedAt", ""), **checks.get("maps", {}),
				"maps": len(maps), "bosses": len({
					boss.get("slug") or boss.get("name") for entry in maps for boss in entry.get("bosses") or []
					if boss.get("slug") or boss.get("name")
				}),
			},
			"guides": {
				**{key: guides.get(key) for key in ("lastSuccessfulAt", "matched", "discovered", "unmatched", "failed")},
				"coverage": {"mode": mode, "guided": len(guided), "total": len(tasks)},
				"lastResult": guide_status.get("lastResult") or {},
			},
			"cdk": {"lastSuccessfulAt": codes["syncedAt"], "count": codes["count"]},
		}
		return status

	def start(self, scope: str) -> dict:
		steps = ("game", "guides", "cdk") if scope == "all" else (scope,)
		if any(step not in ("game", "maps", "guides", "cdk") for step in steps):
			return {"ok": False, "error": "同步类型无效"}
		with self._lock:
			if self._running:
				return {"ok": False, "error": "首页已有同步任务正在运行"}
			self._running = True
			self._jobs = {step: {"state": "queued"} for step in steps}
			mode = self.store.mode
		threading.Thread(target=self._run, args=(steps, mode), daemon=True).start()
		return {"ok": True, "running": True}

	def _run(self, steps: tuple, mode: str) -> None:
		try:
			for step in steps:
				with self._lock:
					self._jobs[step] = {"state": "running"}
				try:
					if step == "game":
						result = self.manager.sync_all()
					elif step == "maps":
						result = self.manager.sync_map_layers(mode)
					elif step == "guides":
						result = self.guides.sync()
					else:
						result = self.cdk.sync()
					if step in ("game", "maps"):
						self.store.load()
						icons = sync_map_icons(self.store.data_dir)
					else:
						icons = {}
					ok = result.get("ok", False)
					error = result.get("error") or result.get("reason") or ""
					if result.get("errors"):
						error = "、".join(f"{row['mode']}/{row['key']} ({row['error']})" for row in result["errors"])
					if icons and not icons["ok"]:
						ok = False
						error = "；".join(filter(None, (error, icons["error"])))
					guide_counts = result.get("sources", {}).get("optarkov", {})
					row = {"state": "done" if ok else "error", "error": error,
						"finishedAt": now_text(), "count": result.get("count"), "guides": guide_counts, "icons": icons}
				except Exception as error:
					row = {"state": "error", "error": str(error), "finishedAt": now_text()}
				with self._lock:
					self._jobs[step] = row
					self._revision += 1
		finally:
			with self._lock:
				self._running = False
