"""在没有既有安装记录的 Windows 用户环境中验证安装、升级和卸载。"""

from __future__ import annotations

import json
import ctypes
import os
import re
import subprocess
import sys
import time
import winreg
from pathlib import Path
from tempfile import TemporaryDirectory

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.paths import APP_NAME, APP_VERSION

REGISTRY = r"Software\TarkovCodex"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\TarkovCodex"


def registry_value(path: str, key: str) -> str:
	try:
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as handle:
			return winreg.QueryValueEx(handle, key)[0]
	except FileNotFoundError:
		return ""


def wizard(exe: Path, arguments: str, env: dict) -> None:
	# NSIS 要求 /D= 位于参数末尾，即使路径有空格也不能另外加引号。
	result = subprocess.run(f'"{exe}" /S {arguments}', env=env, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
	if result.returncode:
		raise RuntimeError(f"安装向导退出码 {result.returncode}")


def smoke(installer: Path, previous: Path | None = None) -> None:
	if registry_value(REGISTRY, "InstallDir") or registry_value(UNINSTALL, "DisplayName"):
		raise RuntimeError("当前 Windows 用户已有安装记录，请在干净的测试用户中验证。")
	shortcut = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/塔科夫百科.lnk"
	if shortcut.exists():
		raise RuntimeError("当前用户已有同名开始菜单快捷方式，请在干净的测试用户中验证。")
	mutex = ctypes.windll.kernel32.OpenMutexW
	mutex.restype = ctypes.c_void_p
	handle = mutex(0x100000, False, "Global\\TarkovCodexSingleInstance")
	if handle:
		ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
		raise RuntimeError("已有程序运行，请使用独立的测试环境。")
	with TemporaryDirectory(dir=ROOT / "build/work", prefix="安装验证_") as test_dir:
		folder = Path(test_dir)
		custom = folder / "我的安装目录"
		env = {**os.environ, "LOCALAPPDATA": str(folder / "user"), "TARKOV_NO_WINDOW": "1"}
		user_data = Path(env["LOCALAPPDATA"]) / "TarkovCodex/data"
		exe = custom / (APP_NAME + ".exe")
		uninstall = custom / "卸载塔科夫百科.exe"
		test_data = {"pve": {"completed": ["test-task"]}}
		legacy = custom / "data"
		legacy.mkdir(parents=True)
		(legacy / "progress.json").write_text(json.dumps(test_data), encoding="utf-8")
		try:
			wizard(previous or installer, f"/D={custom}", env)
			assert exe.is_file() and uninstall.is_file()
			assert Path(registry_value(REGISTRY, "InstallDir")) == custom
			if previous:
				assert registry_value(UNINSTALL, "DisplayVersion") == "0.3.0"
				user_data.mkdir(parents=True, exist_ok=True)
				settings = {"mode": "pve", "update": {"proxy": ""}}
				(user_data / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
				(user_data / "progress.json").write_text(json.dumps(test_data), encoding="utf-8")
			wizard(installer, "", env)
			assert Path(registry_value(REGISTRY, "InstallDir")) == custom
			assert registry_value(UNINSTALL, "DisplayVersion") == APP_VERSION
			process = subprocess.Popen([str(exe)], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
			try:
				log = user_data.parent / "logs/app.log"
				deadline = time.monotonic() + 35
				while time.monotonic() < deadline:
					if process.poll() is not None:
						raise RuntimeError("安装后的程序意外退出")
					content = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
					addresses = re.findall(r"http://127\.0\.0\.1:\d+", content)
					if addresses:
						address = addresses[-1]
						try:
							response = requests.get(address + "/api/health", timeout=2)
							if response.json()["version"] == APP_VERSION:
								assert requests.get(address + "/api/updates", timeout=2).json()["version"] == APP_VERSION
								break
						except requests.RequestException:
							pass
					time.sleep(0.2)
				else:
					raise RuntimeError("安装后无法访问本地健康检查")
				with requests.Session() as client:
					spec = client.get(address + "/api/tasks/657315ddab5a49b71f098853/map", timeout=10).json()
					group = next(group for group in spec["maps"] if group["mapKey"] == "ground-zero")
					assert group["width"] > 0 and len(group["points"]) >= 1
					base = client.get(address + "/api/map/svg/ground-zero", timeout=5)
					assert base.ok and "svg" in base.headers["content-type"]
					detail = client.get(address + "/api/game-maps/customs", timeout=5).json()["map"]
					assert detail["images"][0]["title"] == "海关汉化地图"
					preview = client.get(address + "/api/game-map/image", params={"url": detail["previewUrl"]}, timeout=5)
					assert preview.ok and preview.content.startswith(b"\xff\xd8\xff")
					interactive = client.get(address + "/api/atlas/ground-zero", timeout=10).json()
					assert interactive["ok"] and any(point.get("taskId") == "657315ddab5a49b71f098853" for point in interactive["points"])
				assert json.loads((user_data / "progress.json").read_text()) == test_data
				if previous:
					assert json.loads((user_data / "settings.json").read_text()) == settings
			finally:
				process.terminate()
				process.wait(timeout=15)
		finally:
			if uninstall.is_file():
				wizard(uninstall, f"_?={custom}", env)
		assert not registry_value(REGISTRY, "InstallDir") and not registry_value(UNINSTALL, "DisplayName")
		assert not exe.exists() and not shortcut.exists()
		assert json.loads((user_data / "progress.json").read_text()) == test_data
		assert json.loads((legacy / "progress.json").read_text()) == test_data
	print("已验证自选路径安装、沿用路径升级、程序健康检查、迁移旧进度、卸载及保留本地数据。")


if __name__ == "__main__":
	smoke(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None)
