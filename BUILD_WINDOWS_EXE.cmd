@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo   RenPy Tools v0.2 Windows EXE Builder
echo ========================================
echo.

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)

if not defined PY (
    echo [ERROR] Python was not found.
    echo.
    echo This BAT cannot build an EXE without Windows Python installed.
    echo Install Python 3.12 or newer, then run this file again.
    echo.
    echo IMPORTANT: This is a BUILD script, not the finished EXE.
    pause
    exit /b 1
)

echo [1/4] Python found:
%PY% --version
if errorlevel 1 goto :fail

echo.
echo [2/4] Installing build dependencies...
%PY% -m pip install --upgrade pip
if errorlevel 1 goto :fail
%PY% -m pip install --upgrade pyinstaller rpa-toolkit
if errorlevel 1 goto :fail

echo.
echo [3/4] Building RenPyExtractor.exe...
%PY% -m PyInstaller --noconfirm --clean --windowed --onefile --collect-all rpatool --name RenPyExtractor RenPyExtractor.py
if errorlevel 1 goto :fail

echo.
echo [4/4] Building RenPyAIPatcher.exe...
%PY% -m PyInstaller --noconfirm --clean --windowed --onefile --name RenPyAIPatcher RenPyAIPatcher.py
if errorlevel 1 goto :fail

if not exist "dist\RenPyExtractor.exe" goto :fail
if not exist "dist\RenPyAIPatcher.exe" goto :fail

echo.
echo ========================================
echo [SUCCESS]
echo dist\RenPyExtractor.exe
echo dist\RenPyAIPatcher.exe
echo ========================================
pause
exit /b 0

:fail
echo.
echo ========================================
echo [BUILD FAILED]
echo No DONE/SUCCESS message is shown unless both EXE files actually exist.
echo Check the error message above.
echo ========================================
pause
exit /b 1
