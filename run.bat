@echo off
rem Open the card weight editor for autobonk.toml, then start the bot.
cd /d "%~dp0"

start "autobonk editor" .venv\Scripts\python.exe -m autobonk.editor

echo Edit card weights in the browser and save.
echo The bot reads autobonk.toml at startup, so save before continuing.
pause

.venv\Scripts\python.exe -m autobonk
pause
