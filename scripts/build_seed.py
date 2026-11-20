"""从 Tarkov.dev 重建三种游戏模式的出厂资料。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.sync import SyncManager


def main() -> None:
	result = SyncManager(ROOT / "app" / "seed").sync_all()
	if not result["ok"]:
		for issue in result["errors"]:
			print(f"{issue['mode']} / {issue['key']}：{issue['error']}", file=sys.stderr)
		raise SystemExit(1)
	print(f"三种模式的出厂资料已生成，耗时 {result['seconds']} 秒")


if __name__ == "__main__":
	main()
