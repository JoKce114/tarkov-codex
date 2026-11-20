"""把打包程序制成中文安装向导和可直接作为 GitHub Release 附件的静态更新清单。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.paths import APP_ID, APP_NAME, APP_VERSION
from app.updates import RELEASES, installer_name, validate_manifest

NOTES = """• 任务详情中的底图和点位使用同一画布尺寸。「新手上路」等任务可查看地图，缩放和重置后目标仍与底图对齐。
• 普通地图新增 13 个地点的 TarkovBox 中文标注图。海关可查看宿舍楼，海岸线可查看疗养院，实验室可切换 2D 和 2.5D。原有地图标签和交互地图仍可使用。
• 点击地图预览可打开高清图。高清图加载失败时回到预览，已缓存的图片可离线查看。

安装与升级
关闭正在运行的塔科夫百科，再运行 TarkovCodex-0.3.1-Setup.exe。已安装 v0.3.0 的用户可沿用原安装目录，原有设置和任务进度会保留。从 v0.2.0 便携版升级，请选择旧程序所在目录。"""


def compiler_path() -> Path:
	location = os.environ.get("MAKENSIS") or shutil.which("makensis")
	if location:
		return Path(location)
	for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
		if base and (Path(base) / "NSIS" / "makensis.exe").is_file():
			return Path(base) / "NSIS" / "makensis.exe"
	cache = Path(os.environ.get("LOCALAPPDATA", "")) / "electron-builder" / "Cache" / "nsis"
	for compiler in sorted(cache.glob("nsis-*/makensis.exe"), reverse=True):
		if compiler.is_file():
			return compiler
	raise RuntimeError("找不到 NSIS 编译器，请安装 Unicode NSIS 或指定 MAKENSIS 环境变量。")


def create_release(payload: Path) -> Path:
	if not (payload / (APP_NAME + ".exe")).is_file():
		raise ValueError("缺少已打包的程序")
	output = ROOT / "dist" / "release"
	output.mkdir(parents=True, exist_ok=True)
	uninstall = ROOT / "build" / "work" / "uninstall_files.nsh"
	uninstall.parent.mkdir(parents=True, exist_ok=True)
	entries = sorted(payload.rglob("*"), key=lambda item: len(item.parts), reverse=True)
	lines = []
	for entry in entries:
		relative = str(entry.relative_to(payload)).replace("$", "$$")
		operation = "RMDir" if entry.is_dir() else "Delete"
		lines.append(f'{operation} "$INSTDIR\\{relative}"')
	uninstall.write_text("\n".join(lines), encoding="utf-8")
	setup = output / installer_name(APP_VERSION)
	command = [
		str(compiler_path()), "/V2", "/INPUTCHARSET", "UTF8", f"/DOUTPUT={setup}",
		f"/DVERSION={APP_VERSION}", f"/DAPPICON={ROOT / 'app' / 'icon.ico'}",
		f"/DPAYLOAD={payload.resolve()}", f"/DUNINSTALL_FILES={uninstall}",
		str(ROOT / "build" / "installer.nsi"),
	]
	subprocess.run(command, check=True, cwd=ROOT)
	hash_value = hashlib.sha256()
	with setup.open("rb") as stream:
		for chunk in iter(lambda: stream.read(1048576), b""):
			hash_value.update(chunk)
	manifest = validate_manifest({
		"appId": APP_ID, "version": APP_VERSION, "size": setup.stat().st_size, "sha256": hash_value.hexdigest(),
		"url": f"{RELEASES}/download/v{APP_VERSION}/{setup.name}", "notes": NOTES,
		"publishedAt": os.environ.get("TARKOV_RELEASE_DATE") or date.today().isoformat(),
	})
	(output / "update.json").write_text(json.dumps(manifest, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")
	# 0.2 客户端只会自动解压 ZIP；指向发布页让旧用户运行新的安装向导。
	page = f"{RELEASES}/tag/v{APP_VERSION}"
	legacy = {"version": APP_VERSION, "url": page, "notes": NOTES + "\n\n安装包发布页\n" + page, "publishedAt": manifest["publishedAt"]}
	(output / "latest.json").write_text(json.dumps(legacy, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")
	return setup


if __name__ == "__main__":
	print(create_release(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "dist" / APP_NAME))
