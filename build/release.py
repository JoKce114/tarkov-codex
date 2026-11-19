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

NOTES = """• 全部地图都可以筛选撤离点、出生点、容器、散落物资和任务点。点击任务目标可查看地图位置，也能从地图返回任务详情。
• 首页新增 BOSS 图鉴，可查看出没地点、装备和可能掉落的物品。地图标记支持本地缓存，已修复部分图片加载失败的问题。
• 商人任务新增「仅看有攻略」筛选，可与商人、解锁和完成状态组合使用。补上常规 PVP《新起点》二至四转的 OPtarkov 攻略。
• 首页按当前模式显示攻略覆盖。资料同步集中在首页，攻略同步会显示处理进度和更新、复用缓存、失败的页数。
• 在「设置 → 关于我们」可以手动检查更新或启用定时检查，并查看中文更新公告。

安装与升级
下载 TarkovCodex-0.3.0-Setup.exe，关闭正在运行的塔科夫百科，再运行中文安装向导。首次安装可自选目录。
从 0.2.0 便携版升级时，请选择旧版「塔科夫百科.exe」所在目录，首次启动会迁移原有设置和任务进度。以后升级默认沿用安装目录，卸载后个人数据仍保存在本机。"""


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
