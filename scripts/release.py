"""生成可发布的更新包。

用法：
	python scripts/release.py

产物在 release/ 下：
	tarkov-codex-<版本>.zip   程序本体（不含 data/ 和 logs/）
	latest.json               版本清单，上传到 Release 当附件

发版步骤：
	1. python build/build.py
	2. python scripts/release.py
	3. 在发布仓库新建 Release，tag 用 v<版本>（与 latest.json 的 version 一致）
	4. 把 zip 和 latest.json 两个文件都传上去
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist" / "塔科夫百科"
RELEASE_DIR = ROOT / "release"

# 这些是运行时生成的，不能打进更新包，否则会覆盖用户的任务进度和图片缓存
EXCLUDE_DIRS = {"data", "logs"}


def read_version() -> str:
	text = (ROOT / "app" / "paths.py").read_text(encoding="utf-8")
	match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
	if not match:
		raise SystemExit("app/paths.py 里找不到 APP_VERSION")
	return match.group(1)


def build_zip(version: str) -> Path:
	if not DIST_DIR.is_dir():
		raise SystemExit(f"找不到打包产物：{DIST_DIR}\n请先运行 python build/build.py")
	RELEASE_DIR.mkdir(parents=True, exist_ok=True)
	target = RELEASE_DIR / f"tarkov-codex-{version}.zip"
	if target.exists():
		target.unlink()

	added = 0
	with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
		for path in sorted(DIST_DIR.rglob("*")):
			if not path.is_file():
				continue
			relative = path.relative_to(DIST_DIR)
			if relative.parts and relative.parts[0] in EXCLUDE_DIRS:
				continue
			bundle.write(path, relative.as_posix())
			added += 1
	print(f"打包完成：{target.name}（{added} 个文件）")
	return target


def read_notes(version: str) -> str:
	"""从 CHANGELOG.md 里取当前版本的说明；没有就返回空字符串。"""
	changelog = ROOT / "CHANGELOG.md"
	if not changelog.exists():
		return ""
	text = changelog.read_text(encoding="utf-8")
	heading = re.search(rf"^##\s*\[?{re.escape(version)}\]?[^\n]*$", text, re.MULTILINE)
	if not heading:
		return ""
	rest = text[heading.end():]
	next_heading = re.search(r"^##\s", rest, re.MULTILINE)
	body = rest[: next_heading.start()] if next_heading else rest
	lines = [line.rstrip() for line in body.strip().splitlines()]
	return "\n".join(lines).strip()


def write_latest(version: str, archive: Path) -> Path:
	digest = hashlib.sha256()
	with archive.open("rb") as handle:
		for chunk in iter(lambda: handle.read(1024 * 1024), b""):
			digest.update(chunk)
	notes = read_notes(version)
	payload = {
		"version": version,
		"file": archive.name,
		"sha256": digest.hexdigest(),
		"size": archive.stat().st_size,
		"downloadUrl": f"https://github.com/JoKce114/tarkov-codex-releases/releases/download/v{version}/{archive.name}",
		"url": "https://github.com/JoKce114/tarkov-codex-releases/releases",
		"notes": notes,
		"builtAt": datetime.now().isoformat(timespec="seconds"),
	}
	target = RELEASE_DIR / "latest.json"
	target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
	print(f"版本清单：{target}（SHA256 {digest.hexdigest()[:16]}…）")
	if notes:
		first = next((line for line in notes.splitlines() if line.strip().startswith("-")), "")
		print(f"更新说明：{first.strip() or '已生成'}")
	else:
		print("更新说明：CHANGELOG.md 里没有这一版，notes 留空（建议补上）")
	return target


def main() -> None:
	version = read_version()
	print(f"当前版本：{version}")
	archive = build_zip(version)
	write_latest(version, archive)
	print()
	print("下一步：")
	print(f"  1. 在发布仓库新建 Release，tag 填 v{version}")
	print("  2. 上传 release/ 下的 zip 和 latest.json")


if __name__ == "__main__":
	sys.exit(main())
