@echo off
setlocal

cd /d "%~dp0.."

echo === Building frontend (npm install + build) ===
pushd frontend
call npm install
if errorlevel 1 goto :error
call npm run build
if errorlevel 1 goto :error
popd

echo === Checking for a LibreOffice install to bundle (optional) ===
set "SPECWRITE_LIBREOFFICE_DIR="
if exist "%ProgramFiles%\LibreOffice\program\soffice.exe" set "SPECWRITE_LIBREOFFICE_DIR=%ProgramFiles%\LibreOffice"
if not defined SPECWRITE_LIBREOFFICE_DIR if exist "%ProgramFiles(x86)%\LibreOffice\program\soffice.exe" set "SPECWRITE_LIBREOFFICE_DIR=%ProgramFiles(x86)%\LibreOffice"

if defined SPECWRITE_LIBREOFFICE_DIR (
    echo Found LibreOffice at "%SPECWRITE_LIBREOFFICE_DIR%" -- it will be bundled,
    echo so .doc conversion works on the target machine with nothing else installed.
    echo This adds several hundred MB to the build.
) else (
    echo LibreOffice not found on this build machine -- building without it.
    echo .doc conversion will still work later if LibreOffice is installed
    echo separately on whichever machine actually runs SpecWrite; install
    echo LibreOffice here first and re-run this script to bundle it instead.
    echo See packaging\README.md for details.
)

echo === Setting up an isolated Python build environment ===
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m venv packaging\.build-venv
) else (
    python -m venv packaging\.build-venv
)
if errorlevel 1 goto :error

call packaging\.build-venv\Scripts\activate.bat
if errorlevel 1 goto :error

python -m pip install --upgrade pip
python -m pip install -e "backend[build]"
if errorlevel 1 goto :error

echo === Building SpecWrite.exe (this can take a few minutes) ===
pyinstaller --clean --noconfirm --distpath packaging\dist --workpath packaging\build packaging\specwrite.spec
if errorlevel 1 goto :error

echo.
echo ============================================================
echo Done! The app is at: packaging\dist\SpecWrite\
echo Double-click SpecWrite.exe inside that folder to run it.
echo To share it, zip the whole SpecWrite folder -- not just the exe --
echo and have the recipient unzip it before running.
echo ============================================================
goto :end

:error
echo.
echo Build failed -- see the error above for details.
exit /b 1

:end
endlocal
