from __future__ import annotations

"""检查并安装新版本。

查版本走 Release 的 latest.json 静态附件（GitHub 的 CDN 下载，不占用 REST API
每小时 60 次的配额）；只有确认有新版本、需要展示更新说明时才调一次 REST 接口。
被限流后会把恢复时间记在磁盘上，期间一个请求都不发。
"""

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import paths

# 发布仓库只在这里写一次
RELEASE_REPO = "JoKce114/tarkov-codex-releases"

LATEST_URL = f"https://github.com/{RELEASE_REPO}/releases/latest/download/latest.json"
API_URL = f"https://api.github.com/repos/{RELEASE_REPO}/releases?per_page=30"
RELEASE_PAGE = f"https://github.com/{RELEASE_REPO}/releases"

HEADERS = {
	"User-Agent": "TarkovCodex",
	"Accept": "application/json",
}
TIMEOUT = 10
CACHE_TTL = 5 * 60
STALE_TTL = 24 * 60 * 60
RATE_LIMIT_FALLBACK = 15 * 60
MANUAL_COOLDOWN = 10 * 60
AUTO_INTERVAL = 24 * 60 * 60
NOTES_LIMIT = 2400
MAX_RELEASES = 30


def now_text() -> str:
	return datetime.now().isoformat(timespec="seconds")


def parse_version(text: str) -> tuple[int, int, int] | None:
	match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text or ""))
	if not match:
		return None
	return (int(match.group(1)), int(match.group(2) or 0), int(match.group(3) or 0))


def compare_versions(left: str, right: str) -> int | None:
	a = parse_version(left)
	b = parse_version(right)
	if a is None or b is None:
		return None
	return (a > b) - (a < b)


class Updater:
	def __init__(self, data_dir: Path) -> None:
		self.data_dir = data_dir
		self.cache_file = data_dir / "update_cache.json"
		self.download_dir = data_dir / "update"
		self._lock = threading.RLock()
		self._session = requests.Session()
		self._session.headers.update(HEADERS)
		self._inflight = None
		self._cache = self._read_cache()
		self._progress = {"phase": "idle", "percent": 0, "message": "", "version": ""}
		self._downloading = False
		self._apply_proxy()

	# ---------- 代理 ----------

	@staticmethod
	def normalize_proxy(text: str) -> tuple[str, str]:
		"""校验并规范化代理地址。只接受 http/https，socks 需要额外依赖，不支持。"""
		raw = (text or "").strip()
		if not raw:
			return "", ""
		candidate = raw if "://" in raw else f"http://{raw}"
		parsed = urlparse(candidate)
		if parsed.scheme not in ("http", "https"):
			return "", "代理地址只支持 http:// 或 https://"
		if not parsed.hostname:
			return "", "代理地址缺少主机名"
		try:
			port = parsed.port
		except ValueError:
			return "", "代理端口不正确"
		if port is not None and not (0 < port < 65536):
			return "", "代理端口不正确"
		return candidate, ""

	def _apply_proxy(self) -> None:
		proxy, _error = self.normalize_proxy(self.settings().get("proxy") or "")
		self._session.proxies = {"http": proxy, "https": proxy} if proxy else {}

	def set_proxy(self, text: str) -> dict:
		proxy, error = self.normalize_proxy(text)
		if error:
			return {"ok": False, "message": error}
		self.save_settings({"proxy": proxy})
		self._apply_proxy()
		return {"ok": True, "proxy": proxy}

	# ---------- 缓存 ----------

	def _read_cache(self) -> dict:
		try:
			data = json.loads(self.cache_file.read_text(encoding="utf-8"))
			return data if isinstance(data, dict) else {}
		except (OSError, ValueError):
			return {}

	def _write_cache(self) -> None:
		try:
			self.cache_file.parent.mkdir(parents=True, exist_ok=True)
			tmp = self.cache_file.with_suffix(".json.tmp")
			tmp.write_text(json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8")
			os.replace(tmp, self.cache_file)
		except OSError:
			pass

	def _blocked_until(self) -> float:
		return float(self._cache.get("blockedUntil") or 0)

	def _remember_rate_limit(self, response) -> float:
		retry_after = response.headers.get("Retry-After")
		reset_at = response.headers.get("X-RateLimit-Reset")
		now = time.time()
		if retry_after and retry_after.isdigit():
			until = now + int(retry_after)
		elif reset_at and reset_at.isdigit():
			until = float(reset_at)
		else:
			until = now + RATE_LIMIT_FALLBACK
		with self._lock:
			self._cache["blockedUntil"] = until
			self._write_cache()
		return until

	def _rate_limit_message(self, until: float) -> str:
		minutes = int(round((until - time.time()) / 60))
		if minutes <= 0:
			return "GitHub 接口请求过于频繁，请稍后再试"
		if minutes > 60:
			return "GitHub 接口请求过于频繁，请稍后再试"
		return f"GitHub 接口请求过于频繁，约 {minutes} 分钟后自动恢复"

	# ---------- 设置 ----------

	def settings(self) -> dict:
		settings = paths.load_settings()
		entry = settings.get("update")
		return entry if isinstance(entry, dict) else {}

	def save_settings(self, patch: dict) -> dict:
		settings = paths.load_settings()
		entry = settings.get("update")
		if not isinstance(entry, dict):
			entry = {}
		entry.update(patch)
		settings["update"] = entry
		paths.save_settings(settings)
		return entry

	def auto_check_enabled(self) -> bool:
		return bool(self.settings().get("autoCheck", True))

	# ---------- 检查 ----------

	def status(self) -> dict:
		settings = self.settings()
		return {
			"current": paths.APP_VERSION,
			"autoCheck": bool(settings.get("autoCheck", True)),
			"lastCheckAt": settings.get("lastCheckAt") or "",
			"result": settings.get("lastResult") or None,
			"lastError": settings.get("lastError") or "",
			"proxy": settings.get("proxy") or "",
			"progress": dict(self._progress),
			"checking": self._inflight is not None,
			"downloadable": paths.FROZEN,
		}

	def _latest_probe(self) -> tuple[dict | None, str, str]:
		"""返回 (latest.json 内容, 错误信息, 错误类型)。

		走 Release 静态附件，不占 API 配额；国内网络常连不上 github.com，
		所以调用方要在网络类失败时改走 api.github.com。
		"""
		etag = self._cache.get("latestEtag") or ""
		headers = {"If-None-Match": etag} if etag else {}
		try:
			response = self._session.get(LATEST_URL, headers=headers, timeout=TIMEOUT, allow_redirects=True)
		except requests.RequestException:
			return None, "暂时连不上 GitHub", "network"
		if response.status_code == 304:
			cached = self._cache.get("latest")
			return (cached, "", "") if cached else (None, "发布信息缺失", "other")
		if response.status_code == 404:
			return None, "还没有发布可用的安装包，请前往下载页手动安装", "missing"
		if response.status_code in (403, 429):
			return None, self._rate_limit_message(self._remember_rate_limit(response)), "ratelimit"
		if response.status_code != 200:
			return None, f"GitHub 返回 {response.status_code}", "other"
		try:
			payload = response.json()
		except ValueError:
			return None, "发布信息格式不正确", "other"
		if not isinstance(payload, dict) or not payload.get("version"):
			return None, "发布信息格式不正确", "other"
		with self._lock:
			self._cache["latest"] = payload
			self._cache["latestEtag"] = response.headers.get("ETag", "")
			self._cache["probeAt"] = time.time()
			self._write_cache()
		return payload, "", ""

	def _connection_message(self) -> str:
		if self.settings().get("proxy"):
			return "通过代理连不上 GitHub，请确认代理地址和端口是否可用"
		return "检查更新超时，请确认网络可以访问 GitHub；国内网络可在下方填写代理地址"

	def _api_latest(self) -> tuple[dict | None, list[dict], str]:
		"""静态附件连不上时的备用路径：直接列 Release。消耗一次 API 配额。"""
		try:
			response = self._session.get(API_URL, timeout=TIMEOUT)
		except requests.RequestException:
			return None, [], self._connection_message()
		if response.status_code in (403, 429):
			return None, [], self._rate_limit_message(self._remember_rate_limit(response))
		if response.status_code == 404:
			return None, [], "还没有发布可用的安装包，请前往下载页手动安装"
		if response.status_code != 200:
			return None, [], f"GitHub 返回 {response.status_code}"
		try:
			payload = response.json()
		except ValueError:
			return None, [], "发布信息格式不正确"
		releases, _ = self._usable_releases(payload)
		if not releases:
			return None, [], "还没有发布可用的安装包，请前往下载页手动安装"
		first = releases[0]
		return (
			{
				"version": first["version"],
				"url": first["url"],
				"notes": first["notes"],
				"apiOnly": True,
			},
			releases,
			"",
		)

	def _release_notes(self) -> tuple[list[dict], str]:
		try:
			response = self._session.get(API_URL, timeout=TIMEOUT)
		except requests.RequestException:
			return [], ""
		if response.status_code in (403, 429):
			until = self._remember_rate_limit(response)
			return [], self._rate_limit_message(until)
		if response.status_code != 200:
			return [], ""
		try:
			payload = response.json()
		except ValueError:
			return [], ""
		return self._usable_releases(payload)

	def _range_notes(self, releases: list[dict], current: str, latest: str) -> list[dict]:
		result = []
		for item in releases:
			if compare_versions(item["version"], latest) > 0:
				continue
			if compare_versions(item["version"], current) <= 0:
				continue
			result.append(item)
		return result

	def _usable_releases(self, payload) -> tuple[list[dict], str]:
		if not isinstance(payload, list):
			return [], ""
		items = []
		for entry in payload:
			if not isinstance(entry, dict) or entry.get("draft") or entry.get("prerelease"):
				continue
			tag = entry.get("tag_name") or ""
			if parse_version(tag) is None:
				continue
			notes = (entry.get("body") or "").strip()
			if len(notes) > NOTES_LIMIT:
				notes = notes[:NOTES_LIMIT] + "…"
			items.append(
				{
					"version": tag,
					"url": entry.get("html_url") or RELEASE_PAGE,
					"notes": notes,
				}
			)
		items.sort(key=lambda item: parse_version(item["version"]) or (0, 0, 0), reverse=True)
		return items[:MAX_RELEASES], ""

	def _range_notes(self, releases: list[dict], current: str, latest: str) -> list[dict]:
		result = []
		for item in releases:
			if compare_versions(item["version"], latest) > 0:
				continue
			if compare_versions(item["version"], current) <= 0:
				continue
			result.append(item)
		return result

	def check(self, manual: bool = False) -> dict:
		now = time.time()
		blocked = self._blocked_until()
		if blocked > now:
			return {"ok": False, "message": self._rate_limit_message(blocked), "current": paths.APP_VERSION}

		settings = self.settings()
		last_at = float(settings.get("lastCheckAtEpoch") or 0)
		cached_result = settings.get("lastResult")
		window = MANUAL_COOLDOWN if manual else AUTO_INTERVAL
		if last_at and now - last_at < window and isinstance(cached_result, dict):
			return {**cached_result, "cached": True}

		api_releases: list[dict] = []
		latest, error, kind = self._latest_probe()
		if latest is None and kind in ("network", "other"):
			# github.com 连不上时改走 api.github.com，国内网络很常见
			latest, api_releases, error = self._api_latest()
		if latest is None:
			# 查不到时保留上一次成功的结果，只补一句提示，免得断网就看不了版本信息
			previous = settings.get("lastResult")
			if isinstance(previous, dict) and previous.get("ok"):
				self.save_settings({"lastCheckAt": now_text(), "lastError": error})
				return {**previous, "stale": True, "warning": error or "暂时无法检查更新"}
			self.save_settings({"lastCheckAt": now_text(), "lastError": error})
			return {"ok": False, "message": error or "检查更新失败", "current": paths.APP_VERSION}

		latest_version = str(latest.get("version") or "")
		has_update = (compare_versions(latest_version, paths.APP_VERSION) or 0) > 0
		releases: list[dict] = []
		warning = ""
		if has_update:
			if api_releases:
				releases = api_releases
			else:
				releases, warning = self._release_notes()

		result = {
			"ok": True,
			"current": paths.APP_VERSION,
			"latest": latest_version,
			"hasUpdate": has_update,
			"url": latest.get("url") or RELEASE_PAGE,
			"notes": latest.get("notes") or "",
			"releases": self._range_notes(releases, paths.APP_VERSION, latest_version) if has_update else [],
			"file": latest.get("file") or "",
			"sha256": latest.get("sha256") or "",
			"size": latest.get("size") or 0,
			"downloadUrl": latest.get("downloadUrl") or "",
			# 只从 Release 列表拿到版本、没有 latest.json 时，缺下载地址和校验值，
			# 只能引导用户去发布页手动下载
			"manualOnly": not latest.get("downloadUrl"),
			"warning": warning,
		}
		self.save_settings(
			{
				"lastCheckAt": now_text(),
				"lastCheckAtEpoch": now,
				"lastResult": result,
				"lastError": warning,
			}
		)
		return result

	def check_async(self, manual: bool = False) -> dict:
		with self._lock:
			if self._inflight is not None:
				return {"ok": True, "running": True}
		self._inflight = threading.Thread(target=self._run_check, args=(manual,), daemon=True)
		self._inflight.start()
		return {"ok": True, "running": True}

	def _run_check(self, manual: bool) -> None:
		try:
			self.check(manual=manual)
		finally:
			with self._lock:
				self._inflight = None

	def auto_check(self) -> None:
		if not self.auto_check_enabled():
			return
		settings = self.settings()
		last_at = float(settings.get("lastCheckAtEpoch") or 0)
		if last_at and time.time() - last_at < AUTO_INTERVAL:
			return
		self.check_async(manual=False)

	# ---------- 下载 ----------

	def progress(self) -> dict:
		return dict(self._progress)

	def _set_progress(self, **patch) -> None:
		with self._lock:
			self._progress.update(patch)

	def start_download(self) -> dict:
		if not paths.FROZEN:
			return {"ok": False, "message": "开发模式下不支持自动更新"}
		with self._lock:
			if self._downloading:
				return {"ok": False, "message": "正在下载"}
			self._downloading = True
		settings = self.settings()
		result = settings.get("lastResult") or {}
		threading.Thread(target=self._download, args=(result,), daemon=True, name="update-download").start()
		return {"ok": True}

	def _download(self, result: dict) -> None:
		try:
			url = result.get("downloadUrl") or ""
			version = result.get("version") or result.get("latest") or ""
			expected = (result.get("sha256") or "").lower()
			if not url:
				self._set_progress(phase="error", message="发布信息里缺少下载地址")
				return
			self._set_progress(phase="downloading", percent=0, message="", version=version)
			self.download_dir.mkdir(parents=True, exist_ok=True)
			target = self.download_dir / f"tarkov-codex-{version}.zip"
			digest = hashlib.sha256()
			done = 0
			try:
				response = self._session.get(url, timeout=(10, 300), stream=True)
			except requests.RequestException as error:
				self._set_progress(phase="error", message=f"下载失败，请检查网络或代理（{error}）")
				return
			if response.status_code != 200:
				self._set_progress(phase="error", message=f"下载失败，GitHub 返回 {response.status_code}")
				return
			total = int(response.headers.get("Content-Length") or 0)
			tmp = target.with_suffix(".zip.tmp")
			try:
				with tmp.open("wb") as handle:
					for chunk in response.iter_content(chunk_size=262144):
						if not chunk:
							continue
						handle.write(chunk)
						digest.update(chunk)
						done += len(chunk)
						percent = int(done * 100 / total) if total else 0
						self._set_progress(phase="downloading", percent=min(percent, 99))
			except OSError as error:
				self._set_progress(phase="error", message=f"写入安装包失败（{error}）")
				return
			if expected and digest.hexdigest().lower() != expected:
				tmp.unlink(missing_ok=True)
				self._set_progress(phase="error", message="安装包校验失败，已丢弃，请重试")
				return
			os.replace(tmp, target)
			self._set_progress(phase="downloaded", percent=100, message="", version=version)
		finally:
			with self._lock:
				self._downloading = False

	# ---------- 安装 ----------

	def install(self) -> dict:
		if not paths.FROZEN:
			return {"ok": False, "message": "开发模式下不支持自动更新"}
		progress = self.progress()
		if progress.get("phase") != "downloaded":
			return {"ok": False, "message": "安装包还没有下载完成"}
		version = progress.get("version") or ""
		archive = self.download_dir / f"tarkov-codex-{version}.zip"
		if not archive.exists():
			return {"ok": False, "message": "安装包不存在，请重新下载"}

		staging = self.download_dir / "staging"
		try:
			if staging.exists():
				for item in staging.iterdir():
					if item.is_dir():
						import shutil

						shutil.rmtree(item, ignore_errors=True)
					else:
						item.unlink(missing_ok=True)
			else:
				staging.mkdir(parents=True, exist_ok=True)
			with zipfile.ZipFile(archive) as bundle:
				for member in bundle.namelist():
					name = member.replace("\\", "/")
					# 只允许解包到 staging 内部，挡住 ../ 之类的路径穿越
					if name.startswith("/") or ".." in name.split("/"):
						return {"ok": False, "message": "安装包内容异常，已中止"}
				bundle.extractall(staging)
		except (OSError, zipfile.BadZipFile) as error:
			return {"ok": False, "message": f"解压安装包失败（{error}）"}

		script = self._write_apply_script(staging)
		if script is None:
			return {"ok": False, "message": "无法创建更新脚本"}
		try:
			subprocess.Popen(
				["cmd.exe", "/c", str(script)],
				creationflags=subprocess.CREATE_NO_WINDOW,
				close_fds=True,
			)
		except OSError as error:
			return {"ok": False, "message": f"启动更新脚本失败（{error}）"}
		return {"ok": True, "message": "程序即将关闭并完成更新"}

	def _write_apply_script(self, staging: Path) -> Path | None:
		app_dir = paths.BASE_DIR
		exe = Path(paths.BASE_DIR) / "塔科夫百科.exe"
		if not exe.exists():
			return None
		script = self.download_dir / "apply_update.bat"
		lines = [
			"@echo off",
			"chcp 65001 >nul",
			f'set "PID={os.getpid()}"',
			f'set "SRC={staging}"',
			f'set "DST={app_dir}"',
			"rem 等本程序退出后再覆盖，否则 exe 被占用会替换失败",
			":wait",
			"ping -n 2 127.0.0.1 >nul",
			'tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul',
			"if not errorlevel 1 goto wait",
			"robocopy \"%SRC%\" \"%DST%\" /E /IS /IT /XD data logs /R:2 /W:1 >nul",
			f'start "" "{exe}"',
			"ping -n 3 127.0.0.1 >nul",
			'rd /s /q "%SRC%" >nul 2>nul',
			'del "%~f0" >nul 2>nul',
		]
		try:
			script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
		except OSError:
			return None
		return script
