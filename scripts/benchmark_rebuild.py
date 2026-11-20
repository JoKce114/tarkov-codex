"""Measure local API queries during a real background rebuild using disposable data."""

import asyncio
import math
import tempfile
import time
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.api import create_app
from app.paths import SEED_DIR
from app.progress import ProgressStore
from app.sync import SyncManager


async def run(data_dir: Path) -> None:
	manager = SyncManager(data_dir, seed_dir=SEED_DIR)
	store = manager.current
	if not store.items or not store.tasks:
		raise RuntimeError("请先生成出厂资料")
	app = create_app(manager, ProgressStore(data_dir / "progress.json"), auto_update=False)
	async with AsyncClient(transport=ASGITransport(app=app), base_url="http://local") as client:
		paths = {
			"items": "/api/items?limit=60",
			"item": f"/api/items/{next(iter(store.items))}",
			"tasks": "/api/tasks?limit=60",
			"task": f"/api/tasks/{next(iter(store.tasks))}",
		}
		measurements = {key: [] for key in paths}
		for url in paths.values():
			assert (await client.get(url)).raise_for_status().json()["ok"]
		assert (await client.post("/api/sync/now")).json()["ok"]
		while manager.status()["running"]:
			for label, url in paths.items():
				started = time.perf_counter()
				result = await client.get(url)
				measurements[label].append((time.perf_counter() - started) * 1000)
				assert result.raise_for_status().json()["ok"]
			await asyncio.sleep(0.1)
		result = manager.status()["lastResult"]
		assert result["ok"], result
		assert manager.current is not store
		for mode in ("regular", "pvp-season", "pve"):
			manager.set_mode(mode)
			stats = (await client.get("/api/stats")).json()
			summaries = (await client.get("/api/game-maps")).json()["maps"]
			assert stats["mode"] == mode and len(summaries) == stats["counts"]["maps"]
			for entry in summaries:
				assert (await client.get(f"/api/game-maps/{entry['slug']}")).raise_for_status().json()["ok"]
			print(mode, stats["counts"])
		print("Rebuild seconds:", result["seconds"])
		for label, samples in measurements.items():
			ordered = sorted(samples)
			p95 = ordered[math.ceil(len(samples) * 0.95) - 1]
			print(f"{label}: n={len(samples)}, p95={p95:.1f} ms, max={max(samples):.1f} ms")


if __name__ == "__main__":
	with tempfile.TemporaryDirectory() as directory:
		asyncio.run(run(Path(directory)))
