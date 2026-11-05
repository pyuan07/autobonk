@echo off
rem Lint, type-check and test before committing. Stops at the first failure.
cd /d "%~dp0"

echo == ruff ==
uv run ruff check autobonk tests || goto :fail
echo == mypy ==
uv run mypy autobonk || goto :fail
echo == pytest ==
uv run pytest -q || goto :fail
echo All checks passed.
exit /b 0

:fail
echo Checks failed.
exit /b 1
