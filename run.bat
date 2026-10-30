@echo off
rem Start PokéBonk Autopilot and open the web dashboard.
cd /d "%~dp0"

.venv\Scripts\python.exe -m autobonk --open-dashboard
pause
