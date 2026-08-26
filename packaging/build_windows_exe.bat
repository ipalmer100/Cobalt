@echo off
setlocal

cd /d "%~dp0.."

echo ============================================================
echo  SpecWrite - Windows build
echo ============================================================
echo.
echo === Checking prerequisites ===

set "MISSING="

where git >nul 2>nul
if errorlevel 1 set "MISSING=%MISSING% Git"

rem npm ships with Node, so only look for it once Node itself is present -
rem otherwise a missing Node gets reported twice.
where node >nul 2>nul
if errorlevel 1 goto :no_node
where npm >nul 2>nul
if errorlevel 1 set "MISSING=%MISSING% npm"
goto :after_node
:no_node
set "MISSING=%MISSING% Node.js"
:after_node

rem Prefer the py launcher, fall back to python on PATH. Kept flat rather
rem than nested, because setting a variable inside a parenthesised block
rem needs delayed expansion to read back correctly.
set "PYCMD="
where py >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if defined PYCMD goto :have_python
where python >nul 2>nul
if not errorlevel 1 set "PYCMD=python"
:have_python
if not defined PYCMD set "MISSING=%MISSING% Python"

if defined MISSING goto :missing

rem Python must be 3.11+; the backend uses syntax older versions reject,
rem and the failure otherwise surfaces much later as a confusing pip error.
%PYCMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto :old_python

echo   Git      OK
echo   Versions found:
node --version
%PYCMD% --version
echo.

echo === Building frontend - npm install + build ===
pushd frontend
call npm install
if errorlevel 1 goto :error_frontend
call npm run build
if errorlevel 1 goto :error_frontend
popd

echo.
echo === Checking for a LibreOffice install to bundle - optional ===
set "SPECWRITE_LIBREOFFICE_DIR="
if exist "%ProgramFiles%\LibreOffice\program\soffice.exe" set "SPECWRITE_LIBREOFFICE_DIR=%ProgramFiles%\LibreOffice"
if not defined SPECWRITE_LIBREOFFICE_DIR if exist "%ProgramFiles(x86)%\LibreOffice\program\soffice.exe" set "SPECWRITE_LIBREOFFICE_DIR=%ProgramFiles(x86)%\LibreOffice"

if defined SPECWRITE_LIBREOFFICE_DIR goto :have_libreoffice
echo   LibreOffice not found on this build machine - building without it.
echo   .docx specs work normally either way. Legacy .doc files will only
echo   convert if LibreOffice is installed on whichever machine runs
echo   SpecWrite. To bundle it instead, install LibreOffice here and
echo   re-run this script.
goto :python_env

:have_libreoffice
echo   Found LibreOffice at "%SPECWRITE_LIBREOFFICE_DIR%"
echo   It will be bundled, so .doc conversion works on the target machine
echo   with nothing else installed. This adds several hundred MB.

:python_env
echo.
echo === Setting up an isolated Python build environment ===
%PYCMD% -m venv packaging\.build-venv
if errorlevel 1 goto :error_venv

call packaging\.build-venv\Scripts\activate.bat
if errorlevel 1 goto :error_venv

python -m pip install --upgrade pip
python -m pip install -e "backend[build]"
if errorlevel 1 goto :error_deps

echo.
echo === Building SpecWrite.exe - this can take a few minutes ===
pyinstaller --clean --noconfirm --distpath packaging\dist --workpath packaging\build packaging\specwrite.spec
if errorlevel 1 goto :error_pyinstaller

echo.
echo ============================================================
echo  Done. The app is at: packaging\dist\SpecWrite\
echo.
echo  Double-click SpecWrite.exe inside that folder to run it.
echo  To share it, zip the whole SpecWrite folder - not just the exe -
echo  and have the recipient unzip it before running.
echo ============================================================
goto :end

:missing
echo.
echo Missing prerequisite^(s^):%MISSING%
echo.
echo Install what's listed above, then open a NEW terminal and re-run
echo this script. A new terminal matters: an installer that adds itself
echo to PATH does not affect terminals that were already open.
echo.
echo   Git        https://git-scm.com/download/win
echo   Node.js    https://nodejs.org/           - LTS, includes npm
echo   Python     https://www.python.org/downloads/
echo              tick "Add python.exe to PATH" in the installer
echo.
exit /b 1

:old_python
echo.
%PYCMD% --version
echo ...but Python 3.11 or newer is required.
echo.
echo Install a newer Python from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during installation.
echo.
exit /b 1

:error_frontend
popd
echo.
echo Building the frontend failed.
echo.
echo Most common cause: no internet access, or a proxy blocking npm.
echo Check that "npm install" works on its own inside the frontend folder.
echo.
exit /b 1

:error_venv
echo.
echo Could not create the Python build environment at packaging\.build-venv
echo.
echo If that folder already exists from an earlier attempt, delete it and
echo re-run. Otherwise check that Python is installed correctly.
echo.
exit /b 1

:error_deps
echo.
echo Installing the Python dependencies failed.
echo.
echo Most common cause: no internet access, or a proxy blocking pip.
echo.
exit /b 1

:error_pyinstaller
echo.
echo PyInstaller failed to build the app.
echo.
echo If this mentions a missing module, note the name and report it -
echo it likely needs adding to hiddenimports in packaging\specwrite.spec.
echo.
exit /b 1

:end
endlocal
