from __future__ import annotations

import sys
from pathlib import Path


def _log_dir() -> Path:
	from .paths import LOG_DIR as target
	target.mkdir(parents=True, exist_ok=True)
	return target


def redirect_std_streams() -> None:
	"""pythonw 没有控制台，stdout/stderr 为 None，第三方库写日志时会崩。统一转存到文件。"""
	if sys.stdout is not None and sys.stderr is not None:
		return
	handle = open(_log_dir() / "app.log", "a", encoding="utf-8", buffering=1)
	if sys.stdout is None:
		sys.stdout = handle
	if sys.stderr is None:
		sys.stderr = handle


def write_crash(error: BaseException) -> Path:
	import traceback

	target = _log_dir() / "error.log"
	with target.open("a", encoding="utf-8") as handle:
		handle.write("\n=== 启动失败 ===\n")
		handle.write("".join(traceback.format_exception(type(error), error, error.__traceback__)))
	return target
