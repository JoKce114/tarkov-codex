from __future__ import annotations

"""把窗口标题栏改成深色并换上自己的图标（保持标准窗口，稳定优先）。"""

import ctypes
import threading
import time

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010


def _find_window(title: str, timeout: float = 25.0) -> int:
	user32 = ctypes.windll.user32
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		hwnd = user32.FindWindowW(None, title)
		if hwnd:
			return hwnd
		time.sleep(0.3)
	return 0


def apply(title: str, icon_path: str | None) -> bool:
	hwnd = _find_window(title)
	if not hwnd:
		return False

	user32 = ctypes.windll.user32
	dwm = ctypes.windll.dwmapi

	if icon_path:
		load = user32.LoadImageW
		load.restype = ctypes.c_void_p
		load.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
		for size, which in ((16, ICON_SMALL), (32, ICON_BIG)):
			handle = load(None, icon_path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
			if handle:
				user32.SendMessageW(hwnd, WM_SETICON, which, ctypes.c_void_p(handle))

	# WebView2 初始化过程中会把标题栏主题重置，多设几次确保生效
	for delay in (0.0, 0.6, 1.5, 3.0, 5.0):
		if delay:
			time.sleep(delay)
		enabled = ctypes.c_int(1)
		dwm.DwmSetWindowAttribute(
			hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(enabled), ctypes.sizeof(enabled)
		)
		user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)
	return True


def apply_async(title: str, icon_path: str | None) -> None:
	threading.Thread(target=apply, args=(title, icon_path), daemon=True).start()
