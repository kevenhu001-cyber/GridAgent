@echo off
set "GRIDAGENT_BENCHMARK_ROOT=%~dp0benchmark-assets"
"%~dp0runtime\python.exe" -X utf8 -c "from gridagent.cli import main; main()" --workspace "%LOCALAPPDATA%\GridAgent" %*
