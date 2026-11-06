"""打包脚本：生成可分发目录 dist/塔科夫百科/。

用法：python build/build.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
APP_NAME = "塔科夫百科"

SPEC = """
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

ROOT = r'{root}'

datas = [
	(ROOT + r'\\app\\seed', 'seed'),
	(ROOT + r'\\web', 'web'),
	(ROOT + r'\\app\\icon.ico', '.'),
	(ROOT + r'\\app\\icon.png', '.'),
	(ROOT + r'\\app\\map_config.json', '.'),
]
hiddenimports = (
	collect_submodules('uvicorn')
	+ collect_submodules('fastapi')
	+ collect_submodules('webview')
	+ collect_submodules('clr_loader')
	+ ['pythonnet', 'clr', 'encodings.idna']
)

a = Analysis(
	[ROOT + r'\\build\\runner.py'],
	pathex=[ROOT],
	binaries=[],
	datas=datas,
	hiddenimports=hiddenimports,
	hookspath=[],
	hooksconfig={},
	runtime_hooks=[],
	excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'PyQt5', 'PySide2', 'PIL'],
	noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
	pyz,
	a.scripts,
	[],
	exclude_binaries=True,
	name='{name}',
	debug=False,
	bootloader_ignore_signals=False,
	strip=False,
	upx=False,
	console=False,
	icon=ROOT + r'\\app\\icon.ico',
)
coll = COLLECT(
	exe,
	a.binaries,
	a.datas,
	strip=False,
	upx=False,
	upx_exclude=[],
	name='{name}',
)
"""

RUNNER = '''"""打包入口：把 app 目录作为包导入后启动。"""

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
	base = Path(sys._MEIPASS)
	sys.path.insert(0, str(base))

from app.main import main

if __name__ == "__main__":
	main()
'''


def main() -> None:
	output_dir = DIST_DIR
	# 上次的产物可能被资源管理器或杀毒占用，换个目录避免打包失败
	if output_dir.exists():
		try:
			shutil.rmtree(output_dir)
		except OSError:
			output_dir = ROOT / "dist_new"
			if output_dir.exists():
				shutil.rmtree(output_dir, ignore_errors=True)

	if (BUILD_DIR / "work").exists():
		shutil.rmtree(BUILD_DIR / "work", ignore_errors=True)

	spec_file = BUILD_DIR / "打包.spec"
	spec_text = SPEC.replace("{root}", str(ROOT).replace("\\", "\\\\")).replace("{name}", APP_NAME)
	spec_file.write_text(spec_text.strip(), encoding="utf-8")
	(BUILD_DIR / "runner.py").write_text(RUNNER, encoding="utf-8")

	command = [
		sys.executable,
		"-m",
		"PyInstaller",
		str(spec_file),
		"--noconfirm",
		"--clean",
		"--distpath",
		str(output_dir),
		"--workpath",
		str(BUILD_DIR / "work"),
	]
	print("开始打包，约需 2-5 分钟…")
	result = subprocess.run(command, cwd=str(ROOT))
	if result.returncode != 0:
		raise SystemExit(f"打包失败，返回码 {result.returncode}")

	target = output_dir / APP_NAME
	print()
	print("打包完成:", target)
	if target.exists():
		size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
		print(f"体积: {size / 1048576:.0f} MB")


if __name__ == "__main__":
	main()
