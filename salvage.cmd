@echo off
rem Salvage entry point for Windows development:
rem     salvage.cmd <input_dir> <output_dir>   (always exits 0)
rem Same behaviour as ./salvage: Python 3.10 or newer, found as "py -3" or
rem "python", with this file's folder first on PYTHONPATH.
setlocal
set "SALVAGE_ROOT=%~dp0"
set "SALVAGE_PY="
where py >nul 2>&1 && set "SALVAGE_PY=py -3"
if not defined SALVAGE_PY where python >nul 2>&1 && set "SALVAGE_PY=python"
if not defined SALVAGE_PY (
    echo salvage: error: neither py nor python was found; Salvage needs Python 3.10 or newer 1>&2
    exit /b 0
)
%SALVAGE_PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo salvage: error: Salvage needs Python 3.10 or newer ^(tried: %SALVAGE_PY%^) 1>&2
    exit /b 0
)
if defined PYTHONPATH (
    set "PYTHONPATH=%SALVAGE_ROOT%;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%SALVAGE_ROOT%"
)
%SALVAGE_PY% -m salvagekit.cli %*
exit /b 0
