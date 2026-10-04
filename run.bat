@echo off
cd /d "%~dp0"
if not exist .venv ( python -m venv .venv || py -3 -m venv .venv )
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
start "" http://localhost:8000
python -m uvicorn backend.main:app --port 8000
