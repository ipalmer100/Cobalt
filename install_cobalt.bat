@echo off
rem Plain setlocal, no delayed expansion: nothing here reads back a variable
rem it set inside a block, and with delayed expansion on, an exclamation
rem mark anywhere in an echoed message is silently eaten.
setlocal

rem ---------------------------------------------------------------------
rem  Install or update Cobalt, from a browser and nothing else.
rem
rem  This is the whole install: download this one file, double-click it.
rem  No Git, no clone, no terminal, no administrator rights. It fetches
rem  the current Cobalt from GitHub, sets it up, and leaves a Cobalt
rem  shortcut on the Desktop.
rem
rem  Run it again later and it updates in place -- it is the same file for
rem  installing and for upgrading, because a plant that has to find the
rem  right version of an installer will end up on the wrong one.
rem
rem  It does NOT build Cobalt.exe. The packaged executable is built on a
rem  Windows machine with packaging\build_windows_exe.bat, which is
rem  unchanged and is still how the .exe gets made. What this produces is
rem  the run-from-source install: the same application, the same interface,
rem  on the same port, started through Python instead of an executable.
rem  On a managed machine that is usually the one that is allowed to run.
rem ---------------------------------------------------------------------

set "REPO=ipalmer100/Cobalt"
set "BRANCH=main"
rem Installed under LocalAppData rather than the Desktop or Documents on
rem purpose: those are OneDrive-synced here, and an install directory holds
rem tens of thousands of small node_modules files that would be uploaded
rem one by one. LocalAppData is per-user, needs no elevation, and is not
rem synced.
if "%~1"=="" (set "TARGET=%LOCALAPPDATA%\Cobalt") else (set "TARGET=%~1")
set "WORK=%TEMP%\cobalt-install-%RANDOM%"
set "ZIP=%WORK%\cobalt.zip"

echo ============================================================
echo  Cobalt - install / update
echo ============================================================
echo.
echo   From : github.com/%REPO% (%BRANCH%)
echo   Into : %TARGET%
echo.

rem --- Prerequisites ---------------------------------------------------
rem Checked before anything is downloaded, so a machine that cannot finish
rem the install is told that in five seconds rather than after a 40 MB
rem download and a four-minute npm install.

set "MISSING="

set "PYCMD="
where py >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if defined PYCMD goto :have_python
where python >nul 2>nul
if not errorlevel 1 set "PYCMD=python"
:have_python
if not defined PYCMD set "MISSING=%MISSING% Python"

where node >nul 2>nul
if errorlevel 1 goto :no_node
where npm >nul 2>nul
if errorlevel 1 set "MISSING=%MISSING% npm"
goto :after_node
:no_node
set "MISSING=%MISSING% Node.js"
:after_node

if defined MISSING goto :missing

rem The backend uses syntax older Pythons reject. Caught here, because the
rem failure otherwise surfaces several minutes later as a confusing pip
rem error about a package that is perfectly fine.
%PYCMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto :old_python

echo === Found what it needs ===
%PYCMD% --version
node --version
echo.

rem --- Download --------------------------------------------------------

mkdir "%WORK%" 2>nul
echo === Downloading Cobalt ===

rem curl.exe ships with Windows 10 1803 and later and is tried first: it
rem needs no PowerShell and no execution policy. It does not use the
rem system proxy though, so a machine behind a corporate proxy falls
rem through to PowerShell, which does.
set "URL=https://codeload.github.com/%REPO%/zip/refs/heads/%BRANCH%"
set "GOT="
where curl.exe >nul 2>nul
if errorlevel 1 goto :try_powershell
curl.exe -fsSL --retry 3 -o "%ZIP%" "%URL%"
if not errorlevel 1 if exist "%ZIP%" set "GOT=curl"
if defined GOT goto :downloaded

:try_powershell
echo   Retrying through the system proxy...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
  "$p=[Net.WebRequest]::GetSystemWebProxy(); $p.Credentials=[Net.CredentialCache]::DefaultCredentials;" ^
  "Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%' -UseBasicParsing -Proxy $p.GetProxy('%URL%') -ProxyUseDefaultCredentials" 2>nul
if not errorlevel 1 if exist "%ZIP%" set "GOT=powershell"
if defined GOT goto :downloaded

rem Without a proxy configured at all, GetProxy returns the URL itself and
rem the call above is rejected. Try it plainly before giving up.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
  "Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%' -UseBasicParsing"
if not errorlevel 1 if exist "%ZIP%" set "GOT=powershell"
if not defined GOT goto :error_download

:downloaded
echo   Downloaded.
echo.

rem --- Extract ---------------------------------------------------------

echo === Unpacking ===
rem tar.exe reads zip and ships with the same Windows versions curl does.
where tar.exe >nul 2>nul
if errorlevel 1 goto :unzip_powershell
tar.exe -xf "%ZIP%" -C "%WORK%"
if not errorlevel 1 goto :unzipped
:unzip_powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%WORK%' -Force"
if errorlevel 1 goto :error_unzip
:unzipped

set "SRC=%WORK%\Cobalt-%BRANCH%"
if not exist "%SRC%\backend\pyproject.toml" goto :error_layout

rem --- Put it in place -------------------------------------------------
rem
rem A bundled LibreOffice is 400 MB that somebody chose to put there by
rem hand so .doc conversion works with nothing installed. It is not in the
rem download and must not be thrown away by an update.
set "KEEP_LO="
if exist "%TARGET%\packaging\libreoffice\program\soffice.exe" set "KEEP_LO=1"
if defined KEEP_LO (
  echo   Keeping the bundled LibreOffice from the existing install.
  move "%TARGET%\packaging\libreoffice" "%WORK%\libreoffice" >nul
)

if not exist "%TARGET%" goto :fresh
echo === Replacing the previous install ===
rem Stand outside the folder first. Windows will not delete a directory
rem that any process has as its working directory, and running the
rem installer from inside an existing install is an easy thing to do.
cd /d "%TEMP%"
rem The venv and node_modules are rebuilt below; deleting them is what
rem makes an update an update rather than a merge of two versions.
rmdir /s /q "%TARGET%"
if exist "%TARGET%" goto :error_in_use
:fresh

echo === Installing to %TARGET% ===
move "%SRC%" "%TARGET%" >nul 2>nul
if exist "%TARGET%\backend\pyproject.toml" goto :moved
rem move cannot relocate a directory across volumes, and LocalAppData is
rem redirected to a network drive on some managed machines. robocopy can,
rem and ships with Windows. Its exit codes below 8 are all success.
echo   Copying instead - the destination is on another drive.
robocopy "%SRC%" "%TARGET%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :error_move
if not exist "%TARGET%\backend\pyproject.toml" goto :error_move
:moved
if defined KEEP_LO move "%WORK%\libreoffice" "%TARGET%\packaging\libreoffice" >nul

cd /d "%TARGET%"

rem --- Python environment ----------------------------------------------
rem Built at the path build_windows_exe.bat and run_cobalt.bat both expect,
rem with the same .built-at stamp, so all three scripts share one
rem environment and either launcher works after this.

echo.
echo === Setting up Python - a minute or two ===
%PYCMD% -m venv packaging\.build-venv
if errorlevel 1 goto :error_venv
>"packaging\.build-venv\.built-at" echo %CD%
packaging\.build-venv\Scripts\python.exe -m pip install --quiet --upgrade pip
packaging\.build-venv\Scripts\python.exe -m pip install --quiet -e backend
if errorlevel 1 goto :error_deps

rem --- Frontend ---------------------------------------------------------

echo === Building the interface - a few minutes the first time ===
pushd frontend
call npm install --no-audit --no-fund
if errorlevel 1 goto :error_npm
call npm run build
if errorlevel 1 goto :error_npm
popd
if not exist "frontend\dist\index.html" goto :error_npm

rem --- Shortcut ---------------------------------------------------------

echo.
call packaging\create_shortcut.bat

rmdir /s /q "%WORK%" 2>nul

echo.
echo ============================================================
echo  Cobalt is installed.
echo.
rem create_shortcut.bat prints its own fallback if the Windows Script Host
rem it uses is blocked, which some machines do. The install is complete
rem either way, so say so without claiming a shortcut that is not there.
if not exist "%USERPROFILE%\Desktop\Cobalt.lnk" goto :no_shortcut_line
echo  Start it from the Cobalt shortcut on your Desktop, or by
echo  running:
goto :start_line_done
:no_shortcut_line
echo  Start it by running:
:start_line_done
echo.
echo      %TARGET%\packaging\run_cobalt.bat
echo.
echo  Your browser opens to Cobalt. Click "Browse..." and pick your
echo  folder of spec files.
echo.
echo  To update later, run this installer again - it replaces the
echo  install and keeps nothing stale. Your specs are never touched:
echo  they stay in their own folder, which this does not go near.
echo ============================================================
echo.
pause
goto :end

rem --- Everything below is a failure path -------------------------------

:missing
echo Cobalt needs these first, and they are not on this machine:
echo.
echo    %MISSING%
echo.
echo   Python 3.11 or newer - https://www.python.org/downloads/
echo                          tick "Add python.exe to PATH" during install
echo   Node.js 20 or newer  - https://nodejs.org/  (choose LTS)
echo.
echo Neither needs administrator rights for a per-user install, but on a
echo managed laptop your IT team may have to approve them. Install them,
echo then run this file again.
echo.
pause
exit /b 1

:old_python
echo The Python on this machine is too old. Cobalt needs 3.11 or newer:
%PYCMD% --version
echo.
echo Install a current version from https://www.python.org/downloads/ and
echo run this file again.
echo.
pause
exit /b 1

:error_download
echo Could not download Cobalt from GitHub.
echo.
echo Tried:
echo     %URL%
echo.
echo Open that address in your browser. If it downloads a zip file, the
echo problem is this script's network access rather than the address; if
echo it does not, the repository or branch name has changed.
echo.
echo On a corporate network this is usually a proxy that needs
echo credentials, or GitHub being blocked outright. Whoever manages the
echo machine can confirm which.
echo.
pause
exit /b 1

:error_unzip
echo Downloaded Cobalt but could not unpack it.
echo.
echo The file is at %ZIP% if you want to open it by hand.
echo.
pause
exit /b 1

:error_layout
echo The download unpacked, but does not look like Cobalt - its
echo backend pyproject.toml is missing.
echo.
echo This usually means the branch "%BRANCH%" was renamed. Check
echo github.com/%REPO% for the current branch name.
echo.
pause
exit /b 1

:error_in_use
echo Could not replace the existing install at:
echo.
echo     %TARGET%
echo.
echo Something in that folder is open. Close Cobalt if it is running -
echo the console window it runs in has to be closed, not just the browser
echo tab - then run this file again.
echo.
pause
exit /b 1

:error_move
echo Could not move the downloaded files into %TARGET%.
echo.
pause
exit /b 1

:error_venv
echo Could not create the Python environment.
echo.
echo This is usually a Python install that is missing the "venv" module,
echo or a policy preventing it. Check that this works:
echo.
echo     %PYCMD% -m venv %TEMP%\venvtest
echo.
pause
exit /b 1

:error_deps
echo Could not install Cobalt's Python packages.
echo.
echo On a corporate network pip usually needs the proxy set. Try:
echo.
echo     set HTTPS_PROXY=http://your.proxy:8080
echo.
echo and run this file again, or ask IT for the pip settings used here.
echo.
pause
exit /b 1

:error_npm
popd
echo Could not build the interface.
echo.
echo npm is installed but could not finish. On a corporate network it
echo usually needs the registry proxy set:
echo.
echo     npm config set proxy http://your.proxy:8080
echo     npm config set https-proxy http://your.proxy:8080
echo.
echo Whoever set up Node.js on this machine will know the right values.
echo.
pause
exit /b 1

:end
endlocal
