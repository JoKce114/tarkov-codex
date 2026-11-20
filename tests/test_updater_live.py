"""临时验证：用本地假发布服务跑通检查与下载校验。"""

import hashlib
import json
import sys
import tempfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import updater as updater_module
from app.updater import Updater

def main() -> None:
	"""只在手动执行时运行；pytest 仅收集本文件，不会执行测试主体。"""
	# 隔离设置文件，避免把测试结果写进 data/settings.json
	settings_holder: dict = {}

	def fake_load() -> dict:
		return json.loads(json.dumps(settings_holder))

	def fake_save(data: dict) -> None:
		settings_holder.clear()
		settings_holder.update(json.loads(json.dumps(data)))

	updater_module.paths.load_settings = fake_load
	updater_module.paths.save_settings = fake_save

	work = Path(tempfile.mkdtemp(prefix="upd-test-"))

	archive = work / "tarkov-codex-0.2.0.zip"
	with zipfile.ZipFile(archive, "w") as bundle:
		bundle.writestr("塔科夫百科.exe", b"fake exe")
		bundle.writestr("_internal/base_library.zip", b"fake lib")

	digest = hashlib.sha256(archive.read_bytes()).hexdigest()
	serve_dir = work / "serve"
	serve_dir.mkdir()
	(serve_dir / "payload.zip").write_bytes(archive.read_bytes())
	latest = {
		"version": "0.2.0",
		"file": "tarkov-codex-0.2.0.zip",
		"sha256": digest,
		"size": archive.stat().st_size,
		"downloadUrl": "",
		"url": "https://example.invalid/releases",
		"notes": "测试说明",
	}
	(serve_dir / "latest.json").write_text(json.dumps(latest, ensure_ascii=False), encoding="utf-8")
	(serve_dir / "releases.json").write_text(
		json.dumps([{"tag_name": "v0.2.0", "html_url": "https://example.invalid/v0.2.0", "body": "新增：测试功能"}]),
		encoding="utf-8",
	)


	class Handler(BaseHTTPRequestHandler):
		def do_GET(self):
			name = "payload.zip" if self.path.startswith("/payload") else self.path.lstrip("/").split("?")[0]
			target = serve_dir / name
			if not target.exists():
				self.send_response(404)
				self.end_headers()
				return
			payload = target.read_bytes()
			self.send_response(200)
			self.send_header("Content-Type", "application/json" if name.endswith(".json") else "application/zip")
			self.send_header("Content-Length", str(len(payload)))
			self.send_header("ETag", '"test-etag"')
			self.end_headers()
			self.wfile.write(payload)

		def log_message(self, *args):
			pass


	server = HTTPServer(("127.0.0.1", 0), Handler)
	port = server.server_port
	threading.Thread(target=server.serve_forever, daemon=True).start()

	base = f"http://127.0.0.1:{port}"
	updater_module.LATEST_URL = f"{base}/latest.json"
	updater_module.API_URL = f"{base}/releases.json"

	data_dir = work / "data"
	data_dir.mkdir()
	updater = Updater(data_dir)

	result = updater.check(manual=True)
	print("检查结果:", json.dumps(result, ensure_ascii=False, indent=2)[:600])
	assert result["ok"] is True, result
	assert result["hasUpdate"] is True, result
	assert result["latest"] == "0.2.0"
	assert result["releases"] and result["releases"][0]["notes"] == "新增：测试功能"

	# 第二次立即检查应命中缓存，不再发请求
	cached = updater.check(manual=True)
	assert cached.get("cached") is True, cached
	print("缓存命中: 通过")

	# 下载：把 downloadUrl 指向本地假服务
	updater._download({**result, "downloadUrl": f"{base}/payload"})
	status = updater.progress()
	print("下载状态:", status)
	assert status["phase"] == "downloaded", status
	saved = data_dir / "update" / "tarkov-codex-0.2.0.zip"
	assert saved.exists() and saved.stat().st_size == archive.stat().st_size
	print("下载与 SHA256 校验: 通过")

	# 校验失败必须丢弃
	updater._progress.update({"phase": "idle", "percent": 0, "version": ""})
	updater._download({**result, "downloadUrl": f"{base}/payload", "sha256": "0" * 64})
	status = updater.progress()
	print("错误SHA状态:", status["phase"], status["message"])
	assert status["phase"] == "error"
	assert "校验失败" in status["message"]
	print("错误包拦截: 通过")

	server.shutdown()
	print("\n全部通过")


if __name__ == "__main__":
	main()
