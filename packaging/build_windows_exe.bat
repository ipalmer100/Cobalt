@echo off
setlocal

cd /d "%~dp0.."

echo ============================================================
echo  Cobalt - Windows build
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
set "COBALT_LIBREOFFICE_DIR="
rem Checked first, and deliberately: a copy sitting in packaging\libreoffice
rem is the one that also works when the app runs from source through
rem run_cobalt.bat. An installed LibreOffice only reaches the packaged .exe.
if exist "packaging\libreoffice\program\soffice.exe" set "COBALT_LIBREOFFICE_DIR=%CD%\packaging\libreoffice"
if not defined COBALT_LIBREOFFICE_DIR if exist "%ProgramFiles%\LibreOffice\program\soffice.exe" set "COBALT_LIBREOFFICE_DIR=%ProgramFiles%\LibreOffice"
if not defined COBALT_LIBREOFFICE_DIR if exist "%ProgramFiles(x86)%\LibreOffice\program\soffice.exe" set "COBALT_LIBREOFFICE_DIR=%ProgramFiles(x86)%\LibreOffice"

if defined COBALT_LIBREOFFICE_DIR goto :have_libreoffice
echo   LibreOffice not found - building without it.
echo.
echo   .docx specs work normally either way. This only affects legacy .doc
echo   files, which Cobalt converts on first sight. If your library has
echo   none, you need none - check by looking for .doc files in it.
echo.
echo   To include it, either install LibreOffice on this machine and
echo   re-run, or unpack a portable copy into:
echo.
echo       packaging\libreoffice\        ^(so that
echo       packaging\libreoffice\program\soffice.exe exists^)
echo.
echo   The second works for both ways of running Cobalt; an installed
echo   copy only reaches the packaged .exe.
goto :python_env

:have_libreoffice
echo   Found LibreOffice at "%COBALT_LIBREOFFICE_DIR%"
echo   It will be bundled, so .doc conversion works on the target machine
echo   with nothing else installed. This adds several hundred MB.

:python_env
echo.
echo === Setting up an isolated Python build environment ===

rem A virtualenv is not relocatable: the .exe shims in Scripts\ have the
rem absolute path of their own python.exe compiled into them. Rename or
rem move the repo folder and every shim still points at where the venv used
rem to be, failing with "Fatal error in launcher: Unable to create process".
rem The path the venv was built at is recorded here so a moved folder is
rem detected and the venv rebuilt, rather than failing several minutes in.
set "VENV_STAMP=packaging\.build-venv\.built-at"
if not exist "packaging\.build-venv\Scripts\activate.bat" goto :make_venv
if not exist "%VENV_STAMP%" goto :stale_venv
set /p VENV_BUILT_AT=<"%VENV_STAMP%"
if /i "%VENV_BUILT_AT%"=="%CD%" goto :have_venv

:stale_venv
echo   The build environment was created at a different path.
echo   Rebuilding it - this is normal after renaming or moving the folder.
rmdir /s /q packaging\.build-venv

:make_venv
%PYCMD% -m venv packaging\.build-venv
if errorlevel 1 goto :error_venv
>"%VENV_STAMP%" echo %CD%

:have_venv

call packaging\.build-venv\Scripts\activate.bat
if errorlevel 1 goto :error_venv

python -m pip install --upgrade pip
python -m pip install -e "backend[build]"
if errorlevel 1 goto :error_deps

echo.
echo === Building Cobalt.exe - this can take a few minutes ===
rem `python -m PyInstaller`, not the bare `pyinstaller` command: that
rem resolves to the Scripts\pyinstaller.exe shim, which carries a baked-in
rem absolute path to its python.exe and breaks if the folder ever moves.
rem Going through the interpreter sidesteps the shim entirely.
python -m PyInstaller --clean --noconfirm --distpath packaging\dist --workpath packaging\build packaging\cobalt.spec
if errorlevel 1 goto :error_pyinstaller

rem === Code signing - optional, and the thing that makes the exe runnable
rem on a managed machine. An unsigned binary fails Defender's "prevalence,
rem age, or trusted list" rule whatever it contains, and no change to this
rem build can satisfy that rule. A signature can.
rem
rem Set COBALT_SIGN_THUMBPRINT to the SHA1 thumbprint of a code-signing
rem certificate installed on this machine and the exe gets signed. Leave it
rem unset and the build behaves exactly as it did before.
rem
rem   set COBALT_SIGN_THUMBPRINT=a1b2c3...
rem   packaging\build_windows_exe.bat
if not defined COBALT_SIGN_THUMBPRINT goto :unsigned

echo.
echo === Signing Cobalt.exe ===
if defined COBALT_SIGNTOOL goto :have_signtool
set "COBALT_SIGNTOOL=signtool"
where signtool >nul 2>nul
if not errorlevel 1 goto :have_signtool
rem signtool ships with the Windows SDK and is not on PATH by default.
for /f "delims=" %%S in ('dir /b /s /o-n "%ProgramFiles(x86)%\Windows Kits\10\bin\*\x64\signtool.exe" 2^>nul') do (
    set "COBALT_SIGNTOOL=%%S"
    goto :have_signtool
)
echo   Could not find signtool.exe. Install the Windows SDK, or set
echo   COBALT_SIGNTOOL to its full path, then re-run.
goto :error_signing

:have_signtool
rem /tr timestamps the signature so it stays valid after the certificate
rem expires - without it, every copy stops verifying on expiry day.
"%COBALT_SIGNTOOL%" sign /fd sha256 /td sha256 /tr http://timestamp.digicert.com /sha1 %COBALT_SIGN_THUMBPRINT% "packaging\dist\Cobalt\Cobalt.exe"
if errorlevel 1 goto :error_signing
"%COBALT_SIGNTOOL%" verify /pa "packaging\dist\Cobalt\Cobalt.exe"
if errorlevel 1 goto :error_signing
echo   Signed and verified.
goto :built

:unsigned
echo.
echo   Not signed - COBALT_SIGN_THUMBPRINT is not set.
echo   The app still works. On a managed PC it may be blocked, in which
echo   case use packaging\run_cobalt.bat while IT issues a certificate.
echo   See "Running it on a managed PC" in packaging\README.md.

:built
echo.
echo ============================================================
echo  Done. The app is at: packaging\dist\Cobalt\
echo.
echo  Double-click Cobalt.exe inside that folder to run it.
echo  To share it, zip the whole Cobalt folder - not just the exe -
echo  and have the recipient unzip it before running.
echo.
echo  For a Desktop shortcut that avoids the exe entirely:
echo      packaging\create_shortcut.bat
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
echo Read the pip output above - the real cause is named in it. Two that
echo look alarming but are quick to fix:
echo.
echo   "Multiple top-level packages discovered in a flat-layout"
echo       A leftover backend\specwrite folder from before the rename to
echo       Cobalt. Delete it and re-run:  rmdir /s /q backend\specwrite
echo.
echo   Connection / SSL / timeout errors
echo       No internet access, or a proxy blocking pip.
echo.
exit /b 1

:error_signing
echo.
echo Signing failed, so the app is built but unsigned.
echo.
echo Read the signtool output above. Common causes: the thumbprint in
echo COBALT_SIGN_THUMBPRINT matches no certificate on this machine, the
echo certificate has no private key attached, or the timestamp server was
echo unreachable.
echo.
echo The unsigned app is still in packaging\dist\Cobalt\ and still runs.
echo.
exit /b 1

:error_pyinstaller
echo.
echo PyInstaller failed to build the app.
echo.
echo If this mentions a missing module, note the name and report it -
echo it likely needs adding to hiddenimports in packaging\cobalt.spec.
echo.
exit /b 1

:end
endlocal
