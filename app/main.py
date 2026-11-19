from __future__ import annotations

import ctypes
import os
import socket
import sys
import threading
import time

from .logging_setup import redirect_std_streams

redirect_std_streams()

import requests
import uvicorn

from . import paths
from .api import create_app
from .cdk import CdkStore
from .guides import GuideStore
from .maps import MapStore
from .progress import ProgressStore
from .store import DataStore
from .sync import SyncManager, seed_if_missing


def pick_free_port() -> int:
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
		probe.bind(("127.0.0.1", 0))
		return probe.getsockname()[1]


def acquire_single_instance() -> bool:
	"""用命名互斥量保证只开一个实例；已有实例时把它的窗口叫到前台并退出本进程。"""
	kernel32 = ctypes.windll.kernel32
	user32 = ctypes.windll.user32
	kernel32.CreateMutexW(None, False, "Global\\TarkovCodexSingleInstance")
	ERROR_ALREADY_EXISTS = 183
	if kernel32.GetLastError() != ERROR_ALREADY_EXISTS:
		return True

	handle = user32.FindWindowW(None, paths.APP_NAME)
	if handle:
		user32.ShowWindow(handle, 9)
		user32.SetForegroundWindow(handle)
	return False


def wait_until_ready(port: int, timeout: float = 20.0) -> bool:
	deadline = time.monotonic() + timeout
	url = f"http://127.0.0.1:{port}/api/health"
	while time.monotonic() < deadline:
		try:
			if requests.get(url, timeout=1).status_code == 200:
				return True
		except requests.RequestException:
			pass
		time.sleep(0.2)
	return False


def start_server(
	store: DataStore,
	sync_manager: SyncManager,
	progress,
	cdk: CdkStore,
	guides: GuideStore,
	map_store: MapStore,
) -> uvicorn.Server:
	app = create_app(store, sync_manager, progress, cdk, guides, map_store)
	port = int(os.environ.get("TARKOV_DEV_PORT") or 0) if not paths.FROZEN else 0
	port = port or pick_free_port()
	config = uvicorn.Config(
		app,
		host="127.0.0.1",
		port=port,
		log_config=None,
		access_log=False,
	)
	server = uvicorn.Server(config)
	threading.Thread(target=server.run, daemon=True, name="uvicorn").start()
	if not wait_until_ready(port):
		raise RuntimeError("本地服务启动失败")
	return server


def run() -> None:
	if not acquire_single_instance():
		return

	paths.ensure_dirs()
	seed_if_missing(paths.DATA_DIR, paths.SEED_DIR)

	store = DataStore(paths.DATA_DIR, paths.load_mode())
	store.load()

	sync_manager = SyncManager(paths.DATA_DIR)
	progress = ProgressStore(paths.DATA_DIR / "progress.json")
	cdk = CdkStore()
	guides = GuideStore(store)
	map_store = MapStore(store)
	server = start_server(store, sync_manager, progress, cdk, guides, map_store)
	url = f"http://127.0.0.1:{server.config.port}"
	# 全部改为手动同步：启动时不联网，避免游玩时占用资源

	if os.environ.get("TARKOV_NO_WINDOW") == "1":
		print(url, flush=True)
		while True:
			time.sleep(3600)

	import webview

	icon_path = str(paths.ICON_FILE) if paths.ICON_FILE.exists() else None

	window = webview.create_window(
		paths.APP_NAME,
		f"{url}/",
		width=1360,
		height=900,
		min_size=(1024, 700),
		text_select=True,
		background_color="#12100E",
	)
	from .window import apply_async

	apply_async(paths.APP_NAME, icon_path)
	debug = not paths.FROZEN and os.environ.get("TARKOV_DEV_WINDOW") == "1"
	if debug:
		webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
	webview.start(debug=debug)

	server.should_exit = True


def main() -> None:
	try:
		run()
	except Exception as error:
		from .logging_setup import write_crash

		target = write_crash(error)
		if sys.stdout is not None:
			print(f"启动失败，详情见 {target}", flush=True)
		raise


if __name__ == "__main__":
	main()
