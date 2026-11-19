from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import NamedTemporaryFile
from zlib import crc32

import requests
from fastapi import APIRouter, Request, Response

from . import paths
from .assets import ASSET_HEADERS
from .sync import read_meta

ICON_URL = "https://tarkov.dev/maps/interactive/"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _is_png(payload: bytes) -> bool:
	"""检查 PNG 块边界和校验码，拒绝下载中断或损坏的图标。"""
	if not payload.startswith(PNG_SIGNATURE + b"\x00\x00\x00\rIHDR"):
		return False
	offset = len(PNG_SIGNATURE)
	has_pixels = False
	while offset + 12 <= len(payload):
		size = int.from_bytes(payload[offset:offset + 4], "big")
		end = offset + 8 + size
		if end + 4 > len(payload):
			return False
		chunk = payload[offset + 4:end]
		if crc32(chunk) != int.from_bytes(payload[end:end + 4], "big"):
			return False
		offset = end + 4
		if chunk[:4] == b"IDAT" and size:
			has_pixels = True
		if chunk[:4] == b"IEND":
			return has_pixels and size == 0 and offset == len(payload)
	return False


def _local_icon(cache: Path, bundled: Path) -> bytes:
	for path in (cache, bundled):
		try:
			payload = path.read_bytes()
		except OSError:
			continue
		if _is_png(payload):
			return payload
	return b""


def _replace(target: Path, payload: bytes) -> None:
	with NamedTemporaryFile(dir=target.parent, delete=False) as output:
		temp = Path(output.name)
	try:
		temp.write_bytes(payload)
		temp.replace(target)
	finally:
		temp.unlink(missing_ok=True)


def _sync_icon(bundled: Path, folder: Path, previous: dict) -> tuple[dict, bool]:
	target = folder / bundled.name
	local = _local_icon(target, bundled)
	headers = {**ASSET_HEADERS, "Accept": "image/png"}
	if local and previous.get("digest") == hashlib.sha256(local).hexdigest():
		if previous.get("etag"):
			headers["If-None-Match"] = previous["etag"]
		if previous.get("modified"):
			headers["If-Modified-Since"] = previous["modified"]
	response = requests.get(ICON_URL + bundled.name, headers=headers, timeout=(5, 12))
	if response.status_code == 304 and ("If-None-Match" in headers or "If-Modified-Since" in headers):
		return previous, False
	if response.status_code != 200:
		raise ValueError(f"HTTP {response.status_code}")
	payload = response.content
	if not _is_png(payload):
		raise ValueError("PNG 图标无效")
	changed = payload != local
	if changed:
		_replace(target, payload)
	return {
		"digest": hashlib.sha256(payload).hexdigest(),
		"etag": response.headers.get("ETag", ""),
		"modified": response.headers.get("Last-Modified", ""),
	}, changed


def sync_map_icons(data_dir: Path) -> dict:
	"""首页手动检查随程序提供的地图图标，保留下载失败前的本地版本。"""
	folder = data_dir / "map_icons"
	files = sorted((paths.WEB_DIR / "map_icons").glob("*.png"))
	manifest = folder / "validators.json"
	metadata = read_meta(manifest)
	if not isinstance(metadata, dict):
		metadata = {}
	changed = 0
	count = 0
	errors = []
	try:
		if not files:
			raise OSError("未找到内置地图图标")
		folder.mkdir(parents=True, exist_ok=True)
		with ThreadPoolExecutor(max_workers=4) as pool:
			pending = {}
			for bundled in files:
				entry = metadata.get(bundled.name)
				pending[bundled.name] = pool.submit(_sync_icon, bundled, folder, entry if isinstance(entry, dict) else {})
			for name, future in pending.items():
				try:
					metadata[name], updated = future.result()
					changed += int(updated)
					count += 1
				except (OSError, ValueError, requests.RequestException) as error:
					errors.append(f"{name} ({error})")
		if count:
			_replace(manifest, json.dumps(metadata, ensure_ascii=False).encode("utf-8"))
	except OSError as error:
		errors.append(str(error))
	return {"ok": not errors, "count": count, "changed": changed, "error": "、".join(errors)}


def map_icons_router(data_dir: Path) -> APIRouter:
	router = APIRouter()
	bundled = {path.stem: path for path in (paths.WEB_DIR / "map_icons").glob("*.png")}

	@router.api_route("/map_icons/{icon}.png", methods=["GET", "HEAD"])
	def map_icon(icon: str, request: Request) -> Response:
		path = bundled.get(icon)
		if path is None:
			return Response(status_code=404)
		payload = _local_icon(data_dir / "map_icons" / path.name, path)
		if not payload:
			return Response(status_code=404)
		etag = '"' + hashlib.sha256(payload).hexdigest() + '"'
		headers = {"Cache-Control": "no-cache", "ETag": etag}
		if request.headers.get("If-None-Match") == etag:
			return Response(status_code=304, headers=headers)
		headers["Content-Length"] = str(len(payload))
		return Response(b"" if request.method == "HEAD" else payload, media_type="image/png", headers=headers)

	return router
