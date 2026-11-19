import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from app import paths, updates


def release(version="0.4.0", body=b"test installer"):
	return {
		"appId": paths.APP_ID, "version": version, "size": len(body),
		"sha256": hashlib.sha256(body).hexdigest(), "notes": "中文公告",
		"url": f"{updates.RELEASES}/download/v{version}/{updates.installer_name(version)}",
	}


def test_automatic_schedule_and_manual_refresh(tmp_path, monkeypatch):
	checks = []
	def fetch(cache):
		checks.append(True)
		return release()
	monkeypatch.setattr(updates, "fetch_manifest", fetch)
	monkeypatch.setattr(paths, "load_settings", lambda: {"update": {"autoCheck": False}})
	service = updates.UpdateService(tmp_path)
	assert not service.check(False)["auto"]
	assert not checks
	assert service.check(True)["notify"]
	service.state["auto"] = True
	service.state["dismissed"] = "0.4.0"
	service.save()
	reopened = updates.UpdateService(tmp_path)
	assert not reopened.check(False)["notify"]
	assert len(checks) == 1
	assert reopened.check(True)["available"]
	assert len(checks) == 1
	reopened.state["lastChecked"] -= updates.MANUAL_INTERVAL
	assert reopened.check(True)["available"]
	assert len(checks) == 2


@pytest.mark.parametrize("overrides", [
	{"appId": "another-app"}, {"version": "0.4"}, {"url": "https://example.com/setup.exe"},
	{"size": 0}, {"sha256": "abc"}, {"notes": ["unsupported"]},
])
def test_invalid_manifests(overrides):
	with pytest.raises(ValueError):
		updates.validate_manifest({**release(), **overrides})


def test_manifest_release_date_is_optional_and_validated():
	assert "publishedAt" not in updates.validate_manifest(release())
	assert updates.validate_manifest({**release(), "publishedAt": "2026-11-19"})["publishedAt"] == "2026-11-19"
	with pytest.raises(ValueError):
		updates.validate_manifest({**release(), "publishedAt": "2026-02-30"})


def test_existing_static_zip_manifest_is_compared_without_launching_zip(tmp_path, monkeypatch):
	def read(url, cache):
		if url == updates.MANIFEST_URL:
			raise FileNotFoundError
		assert url.endswith("/latest/download/latest.json")
		return {"version": "0.2.0", "downloadUrl": "archive.zip"}
	monkeypatch.setattr(updates, "manifest_json", read)
	result = updates.UpdateService(tmp_path).check(True)
	assert result["latest"] == "0.2.0"
	assert not result["available"]
	assert not result["error"]
	assert result["release"] is None


def test_conditional_get_retains_announcement_and_separates_url_caches(monkeypatch):
	headers_sent = []
	class Response:
		headers = {"ETag": '"v4"', "Last-Modified": "Mon, 16 Nov 2026 01:23:00 GMT"}
		def __init__(self, status):
			self.status_code = status
		def iter_content(self, _size):
			assert self.status_code != 304
			yield json.dumps(release()).encode()
	@contextmanager
	def response(url, headers):
		headers_sent.append(headers)
		yield Response(304 if headers else 200)
	monkeypatch.setattr(updates, "release_response", response)
	cache = {}
	first = updates.fetch_manifest(cache)
	# 新进程从磁盘恢复同一份缓存。
	second = updates.fetch_manifest(json.loads(json.dumps(cache)))
	assert first == second
	assert headers_sent == [{}, {"If-None-Match": '"v4"', "If-Modified-Since": "Mon, 16 Nov 2026 01:23:00 GMT"}]
	updates.manifest_json(updates.RELEASES + "/latest/download/latest.json", cache)
	assert headers_sent[-1] == {}


def test_simultaneous_manual_checks_share_one_download(tmp_path, monkeypatch):
	started = threading.Event()
	release_worker = threading.Event()
	checks = []
	def fetch(cache):
		checks.append(True)
		started.set()
		assert release_worker.wait(3)
		return release()
	monkeypatch.setattr(updates, "fetch_manifest", fetch)
	service = updates.UpdateService(tmp_path)
	with ThreadPoolExecutor(max_workers=2) as workers:
		first = workers.submit(service.check, True)
		assert started.wait(3)
		second = workers.submit(service.check, True)
		release_worker.set()
		assert first.result() == second.result()
	assert len(checks) == 1


def test_installer_checks_size_and_digest_before_replacement(tmp_path, monkeypatch):
	class Response:
		def iter_content(self, _size):
			yield b"test installer"
	@contextmanager
	def response(_url):
		yield Response()
	monkeypatch.setattr(updates, "release_response", response)
	destination = updates.download_installer(release(), tmp_path)
	assert destination.read_bytes() == b"test installer"
	for modified in ({"size": 11}, {"sha256": "0" * 64}):
		with pytest.raises(ValueError):
			updates.download_installer({**release(), **modified}, tmp_path)
		assert destination.read_bytes() == b"test installer"
		assert not list(tmp_path.glob("*.part"))


def test_migration_prioritizes_current_generation_and_current_user_data(tmp_path):
	source, target = tmp_path / "portable", tmp_path / "installed"
	source.mkdir()
	target.mkdir()
	gen = "9" * 32
	(source / "current.json").write_text(json.dumps({"generation": gen}), encoding="utf-8")
	(source / "progress.json").write_text("legacy", encoding="utf-8")
	(source / "settings.json").write_text("settings", encoding="utf-8")
	snapshot = source / "snapshots" / gen / "pve"
	snapshot.mkdir(parents=True)
	(snapshot / "items.json").write_text("active", encoding="utf-8")
	older = source / "pve"
	older.mkdir()
	(older / "items.json").write_text("older", encoding="utf-8")
	(target / "progress.json").write_text("current", encoding="utf-8")
	paths.migrate_data(source, target)
	assert (target / "progress.json").read_text() == "current"
	assert (target / "settings.json").read_text() == "settings"
	assert (target / "pve" / "items.json").read_text() == "active"
	assert not (target / "snapshots").exists()
