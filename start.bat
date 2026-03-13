@echo off
setlocal

set "ROOT=%~dp0"

if "%1"=="" goto :help

if /i "%1"=="setup" goto :setup
if /i "%1"=="up" goto :up
if /i "%1"=="down" goto :down
if /i "%1"=="dev" goto :dev

:help
echo Usage: start.bat setup ^| up ^| down ^| dev
exit /b 1

:setup
python -m venv .venv
"%ROOT%.venv\Scripts\python" -m pip install --upgrade pip
"%ROOT%.venv\Scripts\python" -m pip install -r "%ROOT%backend\requirements.txt"
pushd "%ROOT%frontend"
npm install
popd
exit /b 0

:up
docker compose -f "%ROOT%docker\docker-compose.yml" up -d
exit /b 0

:down
docker compose -f "%ROOT%docker\docker-compose.yml" down
exit /b 0

:dev
start "backend" cmd /k "cd /d %ROOT%backend && ..\.venv\Scripts\python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
start "frontend" cmd /k "cd /d %ROOT%frontend && npm run dev"
exit /b 0
