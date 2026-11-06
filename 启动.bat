@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "logs" mkdir "logs"

set "PY="
where pythonw >nul 2>nul && set "PY=pythonw"
if not defined PY (
	where python >nul 2>nul && set "PY=python"
)
if not defined PY (
	echo 没有找到 Python，请先安装 Python 3.10 以上版本。
	pause
	exit /b 1
)

start "" %PY% -m app.main
