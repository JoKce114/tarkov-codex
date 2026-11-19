from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urljoin, urlsplit

import requests
from fastapi import APIRouter, Depends, HTTPException, Request

from . import paths

REPOSITORY = "JoKce114/tarkov-codex-releases"
RELEASES = f"https://github.com/{REPOSITORY}/releases"
MANIFEST_URL = f"{RELEASES}/latest/download/update.json"
ASSET_HOSTS = {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}
CHECK_INTERVAL = 24 * 60 * 60
MANUAL_INTERVAL = 15
MAX_INSTALLER = 2 * 1024 * 1024 * 1024


def version_number(value: str) -> tuple[int, ...]:
	if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){2}", value):
		raise ValueError("版本号格式无效")
	return tuple(map(int, value.split(".")))


def installer_name(version: str) -> str:
	version_number(version)
	return f"TarkovCodex-{version}-Setup.exe"


def validate_manifest(value: dict) -> dict:
	if not isinstance(value, dict) or value.get("appId") != paths.APP_ID:
		raise ValueError("更新清单与当前应用不匹配")
	version = value.get("version")
	name = installer_name(version)
	size = value.get("size")
	digest = value.get("sha256")
	notes = value.get("notes")
	url = f"{RELEASES}/download/v{version}/{name}"
	if value.get("url") != url or type(size) is not int or not 0 < size <= MAX_INSTALLER:
		raise ValueError("安装包地址或大小无效")
	if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
		raise ValueError("安装包校验值无效")
	if not isinstance(notes, str) or not notes.strip() or len(notes) > 10000:
		raise ValueError("更新公告无效")
	release = {"appId": paths.APP_ID, "version": version, "url": url, "size": size, "sha256": digest, "notes": notes.strip()}
	if "publishedAt" in value:
		release_date = value["publishedAt"]
		if not isinstance(release_date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", release_date):
			raise ValueError("发布日期格式无效")
		release["publishedAt"] = date.fromisoformat(release_date).isoformat()
	return release


@contextmanager
def release_response(url: str, headers: dict | None = None):
	"""只访问项目发布资源，逐跳验证 GitHub 资源服务器。"""
	with requests.Session() as session:
		config = paths.load_settings().get("update")
		proxy = config.get("proxy") if isinstance(config, dict) else None
		if isinstance(proxy, str) and proxy.startswith(("http://", "https://")):
			session.proxies.update({"http": proxy, "https": proxy})
		for _ in range(5):
			address = urlsplit(url)
			valid_host = address.hostname in ASSET_HOSTS or (
				address.hostname == "github.com" and address.path.startswith(f"/{REPOSITORY}/releases/")
			)
			if address.scheme != "https" or not valid_host or address.username or address.password or address.port not in (443, None):
				raise ValueError("更新资源地址无效")
			with session.get(url, headers=headers, timeout=(5, 20), stream=True, allow_redirects=False) as response:
				if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("Location"):
					url = urljoin(url, response.headers["Location"])
					continue
				if response.status_code == 404:
					raise FileNotFoundError("更新清单或安装包尚未公开，请稍后再试。")
				response.raise_for_status()
				if response.status_code != 200 and not (headers and response.status_code == 304):
					raise ValueError("更新服务响应异常")
				yield response
				return
		raise ValueError("更新资源重定向次数过多")


def manifest_json(url: str, cache: dict) -> dict:
	entry = cache.get(url) or {}
	conditional = {}
	if isinstance(entry.get("body"), dict):
		if entry.get("etag"):
			conditional["If-None-Match"] = entry["etag"]
		if entry.get("modified"):
			conditional["If-Modified-Since"] = entry["modified"]
	with release_response(url, conditional) as response:
		if response.status_code == 304 and conditional:
			return entry["body"]
		body = bytearray()
		for chunk in response.iter_content(8192):
			body.extend(chunk)
			if len(body) > 65536:
				raise ValueError("更新清单过大")
		value = json.loads(body.decode("utf-8-sig"))
		if not isinstance(value, dict):
			raise ValueError("更新清单格式无效")
		cache[url] = {"body": value, "etag": response.headers.get("ETag"), "modified": response.headers.get("Last-Modified")}
		return value


def fetch_manifest(cache: dict) -> dict:
	try:
		return validate_manifest(manifest_json(MANIFEST_URL, cache))
	except FileNotFoundError:
		# 发布页只有 0.2 格式时，只读取版本号。
		legacy = manifest_json(f"{RELEASES}/latest/download/latest.json", cache)
		if not isinstance(legacy, dict):
			raise ValueError("更新清单格式无效")
		version = legacy.get("version")
		version_number(version)
		return {"legacy": True, "version": version}


def download_installer(release: dict, folder: Path) -> Path:
	release = validate_manifest(release)
	folder.mkdir(parents=True, exist_ok=True)
	target = folder / installer_name(release["version"])
	with NamedTemporaryFile(dir=folder, suffix=".part", delete=False) as output:
		temp = Path(output.name)
	try:
		hash_value = hashlib.sha256()
		total = 0
		with release_response(release["url"]) as response, temp.open("wb") as output:
			for chunk in response.iter_content(131072):
				total += len(chunk)
				if total > release["size"]:
					raise ValueError("安装包大小与清单不符")
				output.write(chunk)
				hash_value.update(chunk)
		if total != release["size"] or hash_value.hexdigest() != release["sha256"]:
			raise ValueError("安装包校验失败，请重新检查更新")
		temp.replace(target)
		return target
	finally:
		temp.unlink(missing_ok=True)


class UpdateService:
	def __init__(self, folder: Path) -> None:
		self.folder = folder
		self.settings = folder / "updates.json"
		self.lock = threading.RLock()
		self.install_lock = threading.Lock()
		try:
			state = json.loads(self.settings.read_text(encoding="utf-8"))
		except (OSError, ValueError):
			state = {}
		self.state = state if isinstance(state, dict) else {}
		legacy = paths.load_settings().get("update")
		if isinstance(legacy, dict):
			self.state.setdefault("auto", bool(legacy.get("autoCheck", True)))

	def save(self) -> None:
		self.folder.mkdir(parents=True, exist_ok=True)
		with NamedTemporaryFile(mode="w", dir=self.folder, encoding="utf-8", delete=False) as target:
			json.dump(self.state, target, ensure_ascii=False)
		Path(target.name).replace(self.settings)

	def status(self) -> dict:
		with self.lock:
			try:
				release = validate_manifest(self.state.get("release"))
				available = version_number(release["version"]) > version_number(paths.APP_VERSION)
			except ValueError:
				release, available = None, False
			legacy = paths.load_settings().get("update")
			return {
				"version": paths.APP_VERSION, "auto": self.state.get("auto", True),
				"proxy": legacy.get("proxy", "") if isinstance(legacy, dict) else "",
				"lastChecked": self.state.get("lastChecked", 0), "error": self.state.get("error", ""),
				"latest": self.state.get("latest", ""),
				"release": release, "available": available,
				"notify": available and self.state.get("dismissed") != release["version"],
			}

	def check(self, manual: bool) -> dict:
		with self.lock:
			current = self.status()
			now = int(time.time())
			interval = MANUAL_INTERVAL if manual else CHECK_INTERVAL
			if (not manual and not current["auto"]) or 0 <= now - current["lastChecked"] < interval:
				return current
			try:
				cache = dict(self.state.get("manifests") or {})
				result = fetch_manifest(cache)
				self.state["manifests"] = cache
				self.state["latest"] = result["version"]
				self.state["release"] = None if result.get("legacy") else result
				legacy_update = result.get("legacy") and version_number(result["version"]) > version_number(paths.APP_VERSION)
				self.state["error"] = "已发布新版本，中文安装包清单尚未就绪。" if legacy_update else ""
			except FileNotFoundError:
				self.state["error"] = "更新清单尚未公开，请稍后再试。"
			except requests.RequestException:
				self.state["error"] = "无法连接更新服务，请检查网络后重试。"
			except (ValueError, UnicodeError) as error:
				self.state["error"] = str(error)
			self.state["lastChecked"] = int(time.time())
			self.save()
			return self.status()


def updates_router() -> APIRouter:
	service = UpdateService(paths.DATA_DIR)

	async def reject_foreign_request(request: Request):
		if request.method == "POST" and request.headers.get("origin") != str(request.base_url).rstrip("/"):
			raise HTTPException(status_code=403, detail="请从本应用的设置窗口操作。")

	router = APIRouter(prefix="/api/updates", dependencies=[Depends(reject_foreign_request)])

	@router.get("")
	def status():
		return service.status()

	@router.post("/check")
	def check(manual: bool = False):
		return service.check(manual)

	@router.post("/auto")
	def change_auto(enabled: bool):
		with service.lock:
			service.state["auto"] = enabled
			service.save()
			return service.status()

	@router.post("/dismiss")
	def dismiss(version: str):
		with service.lock:
			service.state["dismissed"] = version
			service.save()
			return service.status()

	@router.post("/proxy")
	async def change_proxy(request: Request):
		body = await request.json()
		raw = body.get("proxy") if isinstance(body, dict) else None
		if not isinstance(raw, str) or len(raw) > 1024:
			return {"ok": False, "error": "代理地址无效。"}
		value = raw.strip()
		if value:
			value = value if "://" in value else "http://" + value
			try:
				address = urlsplit(value)
				if address.scheme not in ("http", "https") or not address.hostname or address.query or address.fragment:
					raise ValueError
				if address.port == 0:
					raise ValueError
			except ValueError:
				return {"ok": False, "error": "请输入有效的 HTTP 或 HTTPS 代理地址。"}
		paths.save_update_proxy(value)
		return {"ok": True, **service.status()}

	@router.post("/install")
	def install(request: Request, version: str):
		# 只接受界面发起的同源请求，参数只能确认已检查的版本。
		if request.headers.get("x-tarkov-update") != "install":
			return {"ok": False, "error": "请从本应用的更新窗口启动安装程序。"}
		if not service.install_lock.acquire(blocking=False):
			return {"ok": False, "error": "已有安装包正在下载。"}
		try:
			info = service.status()
			release = info["release"]
			if not info["available"] or release["version"] != version:
				return {"ok": False, "error": "版本信息已变更，请重新检查更新。"}
			target = download_installer(release, service.folder / "installers")
			if os.name != "nt":
				return {"ok": False, "error": "安装程序需要 Windows。"}
			subprocess.Popen([str(target)], cwd=target.parent)
			return {"ok": True}
		except requests.RequestException:
			return {"ok": False, "error": "安装包下载失败，请检查网络或更新代理。"}
		except (ValueError, OSError) as error:
			return {"ok": False, "error": "安装包下载或启动失败：" + str(error)}
		finally:
			service.install_lock.release()

	return router
