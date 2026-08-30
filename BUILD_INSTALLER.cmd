@echo off
setlocal
cd /d "%~dp0"

echo =========================================
echo   RenPy Tools v0.3 Full Installer Builder
echo =========================================
echo.

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)

if not defined PY (
    echo [ERROR] Python was not found.
    pause
    exit /b 1
)

where iscc >nul 2>nul
if errorlevel 1 (
    if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
        set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    ) else (
        echo [ERROR] Inno Setup 6 was not found.
        echo Install Inno Setup 6 and run this file again.
        pause
        exit /b 1
    )
) else (
    set "ISCC=iscc"
)

echo [1/5] Installing dependencies...
%PY% -m pip install --upgrade pip
if errorlevel 1 goto :fail
%PY% -m pip install --upgrade pyinstaller rpa-toolkit
if errorlevel 1 goto :fail

echo [2/5] Building RenPyExtractor.exe...
%PY% -m PyInstaller --noconfirm --clean --windowed --onefile --collect-all rpatool --name RenPyExtractor RenPyExtractor.py
if errorlevel 1 goto :fail

echo [3/5] Building RenPyAIPatcher.exe...
%PY% -m PyInstaller --noconfirm --clean --windowed --onefile --name RenPyAIPatcher RenPyAIPatcher.py
if errorlevel 1 goto :fail

if not exist "dist\RenPyExtractor.exe" goto :fail
if not exist "dist\RenPyAIPatcher.exe" goto :fail

echo [4/5] Building Setup.exe...
"%ISCC%" installer.iss
if errorlevel 1 goto :fail

echo [5/5] Verifying installer...
if not exist "installer\RenPyTools_Setup.exe" goto :fail

echo.
echo =========================================
echo [SUCCESS]
echo installer\RenPyTools_Setup.exe
echo =========================================
pause
exit /b 0

:fail
echo.
echo =========================================
echo [BUILD FAILED]
echo The installer was NOT created.
echo Check the error above.
echo =========================================
pause
exit /b 1
