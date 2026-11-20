from __future__ import annotations

"""按需下载远端文件到本地。

四类图片（物品图标、地图矢量图、地图原图、攻略截图）原先各用一把全局锁，
所有图片只能排队一张张下载；这里改成每张图一把锁，可以同时下载多张。

三个保护措施：
- 下载失败的文件在 FAIL_TTL 内不再重试，避免断网时每个请求都干等超时
- 连续失败达到阈值后短暂熔断，整批请求立刻返回，界面不会卡住
- 临时文件写完再改名，中途失败不会留下半个文件
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

FAIL_TTL = 600.0
BREAKER_THRESHOLD = 8
BREAKER_PAUSE = 60.0


class RemoteCache:
	def __init__(self, directory: Path, timeout, headers: dict) -> None:
		self.directory = directory
		self.timeout = timeout
		self.headers = headers
		self._locks: dict[str, threading.Lock] = {}
		self._locks_guard = threading.Lock()
		self._failed: dict[str, float] = {}
		self._state = threading.Lock()
		self._consecutive_failures = 0
		self._paused_until = 0.0
		self._local = threading.local()

	def _session(self) -> requests.Session:
		session = getattr(self._local, "session", None)
		if session is None:
			session = requests.Session()
			session.headers.update(self.headers)
			self._local.session = session
		return session

	def _lock_for(self, key: str) -> threading.Lock:
		with self._locks_guard:
			lock = self._locks.get(key)
			if lock is None:
				lock = threading.Lock()
				self._locks[key] = lock
			return lock

	def _remember_failure(self, key: str, network_error: bool = True) -> None:
		with self._state:
			self._failed[key] = time.monotonic()
			# 404 只是这张图不存在，不代表网络坏了；只有连不上才计入熔断
			if network_error:
				self._consecutive_failures += 1
				if self._consecutive_failures >= BREAKER_THRESHOLD:
					self._paused_until = time.monotonic() + BREAKER_PAUSE
			else:
				self._consecutive_failures = 0

	def _remember_success(self, key: str) -> None:
		with self._state:
			self._failed.pop(key, None)
			self._consecutive_failures = 0

	def _recently_failed(self, key: str) -> bool:
		with self._state:
			stamp = self._failed.get(key)
			if stamp is None:
				return False
			if time.monotonic() - stamp < FAIL_TTL:
				return True
			self._failed.pop(key, None)
			return False

	def _paused(self) -> bool:
		with self._state:
			return time.monotonic() < self._paused_until

	def fetch_path(self, target: Path, url: str) -> Path | None:
		if not url:
			return None
		if target.exists():
			return target
		key = str(target)
		if self._recently_failed(key):
			return None
		with self._lock_for(key):
			if target.exists():
				return target
			if self._recently_failed(key) or self._paused():
				return None
			try:
				response = self._session().get(url, timeout=self.timeout)
			except requests.RequestException:
				self._remember_failure(key, network_error=True)
				return None
			if response.status_code != 200 or not response.content:
				self._remember_failure(key, network_error=False)
				return None
			try:
				target.parent.mkdir(parents=True, exist_ok=True)
				tmp = target.with_suffix(target.suffix + ".tmp")
				tmp.write_bytes(response.content)
				os.replace(tmp, target)
			except OSError:
				self._remember_failure(key)
				return None
			self._remember_success(key)
			return target

	def fetch_text(self, target: Path, url: str) -> str | None:
		local = self.fetch_path(target, url)
		if local is None:
			return None
		try:
			return local.read_text(encoding="utf-8")
		except OSError:
			return None

	def prefetch(self, jobs: list[tuple[Path, str]], workers: int = 8, on_done=None) -> int:
		"""批量下载，返回成功数量。on_done 每完成一张调用一次。"""
		if not jobs:
			return 0
		done = 0

		def run(job: tuple[Path, str]) -> bool:
			target, url = job
			return self.fetch_path(target, url) is not None

		with ThreadPoolExecutor(max_workers=workers) as pool:
			for ok in pool.map(run, jobs):
				if ok:
					done += 1
				if on_done:
					on_done(ok)
		return done
